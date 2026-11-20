"""The pull-request path of .github/workflows/privacy.yml, run for real against synthetic pull requests.

The `run:` blocks are lifted from the workflow file as they stand (a small reader for the block
style the file uses, below) and executed in a subprocess, in a clone laid out the way the
workflow expects it: a bare repository stands in for GitHub, its `main` is the trusted base, a
pull-request branch carries the change, and the job runs in a fresh clone of the bare repository
with the pull request's head checked out. What GitHub supplies (the base ref, the event name,
RUNNER_TEMP, GITHUB_PATH) is given to each step as its environment by this test.

What this test cannot see, because it does not run on GitHub: which commit actions/checkout really
checks out, which refs it fetches (the scans need refs/remotes/origin/<base>), the runner image,
and anything else the provider adds. A green run here is evidence about the shell the workflow
runs, not about the workflow on GitHub; that needs one real run in a private rehearsal repository.

Betterleaks must be installed and must be the version the workflow pins: missing or different,
the tests fail instead of skipping. Fake secrets are built at run time from random characters, so
no secret-looking literal exists in the repository.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import string
import subprocess
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "privacy.yml"
IDENTITY = "1+tester@users.noreply.github.com"
# Files the synthetic base carries, copied from this checkout: the trusted tools the workflow
# reads from the base commit, and the workflow itself.
BASE_FILES = (
    "tools/privacy_scan.py",
    "tools/privacy_rules.json",
    "tools/secret_scan.sh",
    "tools/secret_scan.tmpl",
    ".github/workflows/privacy.yml",
)
SCAN_JOBS = ("scan", "betterleaks")
# Steps that need the network on GitHub; the test provides their result instead (the local
# Betterleaks on PATH, checked against the pinned version).
PROVISION_STEP_PREFIX = "Install Betterleaks"


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def registry_token() -> str:
    """A token shape only Betterleaks knows (the public privacy rules do not)."""
    return "np" + "m_" + random_text(36)


def github_token() -> str:
    """A token shape both scans know."""
    return "gh" + "p_" + random_text(36)


# --- A reader for the YAML subset the workflow uses -------------------------------------------
#
# The standard library has no YAML parser. This reader takes block mappings, block sequences,
# plain and simply quoted scalars, and literal block scalars (`|`, `|-`). Everything else
# (flow collections, anchors, aliases, tags, folded scalars, `|+`, explicit keys, several
# documents, tabs in indentation, duplicate keys) is refused with an error rather than read
# loosely, so the test fails instead of running something other than what GitHub would run.
# Scalars stay strings: `on` is the key "on", `false` is the text "false".


class WorkflowFormatError(Exception):
    pass


KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:\s+(.*))?$")


class _Reader:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.pos = 0
        for number, line in enumerate(self.lines, 1):
            stripped = line.lstrip(" ")
            if stripped.startswith("\t"):
                raise WorkflowFormatError(f"line {number}: tab in indentation")
            if line.rstrip() in ("---", "..."):
                raise WorkflowFormatError(f"line {number}: document markers are not supported")

    @staticmethod
    def _significant(line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("#")

    def _peek(self) -> tuple[int, str] | None:
        while self.pos < len(self.lines) and not self._significant(self.lines[self.pos]):
            self.pos += 1
        if self.pos >= len(self.lines):
            return None
        line = self.lines[self.pos]
        return len(line) - len(line.lstrip(" ")), line.strip()

    def document(self):
        node = self._block(0)
        if self._peek() is not None:
            raise WorkflowFormatError(f"line {self.pos + 1}: unexpected content")
        return node

    def _block(self, indent: int):
        head = self._peek()
        if head is None or head[0] < indent:
            return None
        if head[1] == "-" or head[1].startswith("- "):
            return self._sequence(head[0])
        return self._mapping(head[0])

    def _mapping(self, indent: int) -> dict:
        out: dict = {}
        while True:
            head = self._peek()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                raise WorkflowFormatError(f"line {self.pos + 1}: unexpected indentation")
            text = head[1]
            if text.startswith("- ") or text == "-":
                return out
            match = KEY_RE.match(text)
            if not match:
                raise WorkflowFormatError(f"line {self.pos + 1}: not a supported mapping entry: {text!r}")
            key, rest = match.group(1), (match.group(2) or "")
            if key in out:
                raise WorkflowFormatError(f"line {self.pos + 1}: duplicate key {key!r}")
            self.pos += 1
            rest_value = _strip_comment(rest)
            if rest_value in ("|", "|-"):
                out[key] = self._literal(indent, keep_last=rest_value == "|")
            elif rest_value == "":
                nxt = self._peek()
                if nxt is not None and nxt[0] == indent and (nxt[1] == "-" or nxt[1].startswith("- ")):
                    out[key] = self._sequence(indent)
                else:
                    out[key] = self._block(indent + 1)
            else:
                out[key] = _scalar(rest, self.pos)
        return out

    def _sequence(self, indent: int) -> list:
        out: list = []
        while True:
            head = self._peek()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent or not (head[1] == "-" or head[1].startswith("- ")):
                return out
            line = self.lines[self.pos]
            if head[1] == "-":
                self.pos += 1
                out.append(self._block(indent + 1))
                continue
            content = line[indent + 1 :]
            column = indent + 1 + (len(content) - len(content.lstrip(" ")))
            item = content.strip()
            if KEY_RE.match(item):
                # The item is a mapping whose first key sits on the dash line.
                self.lines[self.pos] = " " * column + item
                out.append(self._mapping(column))
            else:
                self.pos += 1
                out.append(_scalar(item, self.pos))

    def _literal(self, parent_indent: int, keep_last: bool) -> str:
        body: list[str] = []
        block_indent = None
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.strip() == "":
                body.append("")
                self.pos += 1
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= parent_indent:
                break
            if block_indent is None:
                block_indent = indent
            if indent < block_indent:
                raise WorkflowFormatError(f"line {self.pos + 1}: block scalar less indented than its first line")
            body.append(line[block_indent:])
            self.pos += 1
        while body and body[-1] == "":
            body.pop()
        text = "\n".join(body)
        return text + "\n" if keep_last and text else text


def _strip_comment(rest: str) -> str:
    if rest.startswith(("'", '"')):
        return rest.strip()
    cut = re.search(r"(^|\s)#", rest)
    return (rest[: cut.start()] if cut else rest).strip()


def _scalar(rest: str, line_no: int) -> str:
    rest = rest.strip()
    if rest[:1] in ("{", "[", "&", "*", "!", ">", "|", "%", "@", "`", "?"):
        raise WorkflowFormatError(f"line {line_no}: unsupported scalar {rest!r}")
    if rest[:1] == '"':
        end = rest.find('"', 1)
        if end < 0 or "\\" in rest[1:end]:
            raise WorkflowFormatError(f"line {line_no}: unsupported double-quoted scalar {rest!r}")
        tail = rest[end + 1 :].strip()
        if tail and not tail.startswith("#"):
            raise WorkflowFormatError(f"line {line_no}: text after a quoted scalar")
        return rest[1:end]
    if rest[:1] == "'":
        match = re.match(r"^'((?:[^']|'')*)'\s*(#.*)?$", rest)
        if not match:
            raise WorkflowFormatError(f"line {line_no}: unsupported single-quoted scalar {rest!r}")
        return match.group(1).replace("''", "'")
    return _strip_comment(rest)


def load_workflow(path: Path = WORKFLOW) -> dict:
    data = _Reader(path.read_text(encoding="utf-8")).document()
    if not isinstance(data, dict):
        raise WorkflowFormatError("the workflow is not a mapping")
    return data


# --- Running a job the way the runner would -------------------------------------------------

EXPR_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def substitute(text: str, context: dict[str, str]) -> str:
    """GitHub replaces ${{ name }} before the shell sees the text; only known names are allowed."""

    def one(match: re.Match) -> str:
        name = match.group(1)
        if name not in context:
            raise WorkflowFormatError(f"expression not modelled by this test: ${{{{ {name} }}}}")
        return context[name]

    return EXPR_RE.sub(one, text)


@dataclass
class StepResult:
    name: str
    returncode: int
    output: str


@dataclass
class JobResult:
    job: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def failed(self) -> StepResult | None:
        return next((s for s in self.steps if s.returncode != 0), None)


SHELLS = {
    None: ["bash", "-e"],  # GitHub's default for an unspecified shell on Linux: bash -e {0}
    "bash": ["bash", "--noprofile", "--norc", "-eo", "pipefail"],
    "sh": ["sh", "-e"],
}
REFUSED_KEYS = ("if", "continue-on-error", "defaults", "working-directory", "strategy", "container", "services")


def run_job(workflow: dict, job_id: str, clone: Path, context: dict[str, str], scratch: Path, base_env: dict) -> JobResult:
    if "defaults" in workflow:
        raise WorkflowFormatError("workflow-level defaults are not modelled")
    job = workflow["jobs"][job_id]
    for key in REFUSED_KEYS:
        if key in job:
            raise WorkflowFormatError(f"job {job_id}: '{key}' is not modelled; extend the test")
    runner_temp = scratch / f"runner-temp-{job_id}"
    runner_temp.mkdir()
    github_path = scratch / f"github-path-{job_id}"
    github_path.write_text("")
    env = dict(base_env)
    env.update(
        RUNNER_TEMP=str(runner_temp),
        GITHUB_PATH=str(github_path),
        GITHUB_ENV=str(scratch / f"github-env-{job_id}"),
        GITHUB_WORKSPACE=str(clone),
        GITHUB_EVENT_NAME=context["github.event_name"],
        GITHUB_BASE_REF=context["github.base_ref"],
        GITHUB_ACTIONS="true",
        CI="true",
    )
    for source in (workflow.get("env") or {}, job.get("env") or {}):
        env.update({k: substitute(v, context) for k, v in source.items()})
    result = JobResult(job_id)
    for index, step in enumerate(job.get("steps") or []):
        name = step.get("name") or f"step {index}"
        for key in REFUSED_KEYS:
            if key in step:
                raise WorkflowFormatError(f"{job_id} / {name}: '{key}' is not modelled; extend the test")
        if "uses" in step:
            if not step["uses"].startswith("actions/checkout@"):
                raise WorkflowFormatError(f"{job_id} / {name}: action {step['uses']} is not modelled")
            continue  # the clone stands in for the checkout
        if name.startswith(PROVISION_STEP_PREFIX):
            continue  # the local Betterleaks is on PATH (version checked by the test)
        if step.get("shell") not in SHELLS:
            raise WorkflowFormatError(f"{job_id} / {name}: shell {step.get('shell')!r} is not modelled")
        step_env = dict(env)
        step_env.update({k: substitute(v, context) for k, v in (step.get("env") or {}).items()})
        script = scratch / f"{job_id}-{index}.sh"
        script.write_text(substitute(step["run"], context))
        proc = subprocess.run(
            SHELLS[step.get("shell")] + [str(script)],
            cwd=clone,
            env=step_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        result.steps.append(StepResult(name, proc.returncode, proc.stdout + proc.stderr))
        if proc.returncode != 0:
            break
    return result


# --- Synthetic repositories ---------------------------------------------------------------


class PullRequest:
    """A bare 'GitHub' repository with a trusted main, a PR branch, and a CI clone of the PR head."""

    def __init__(self, testcase: unittest.TestCase) -> None:
        self.testcase = testcase
        self.base = Path(tempfile.mkdtemp(prefix="privacy-workflow-"))
        testcase.addCleanup(shutil.rmtree, self.base, True)
        home = self.base / "home"
        home.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(self.base / "tmp"),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "tester",
            "GIT_AUTHOR_EMAIL": IDENTITY,
            "GIT_COMMITTER_NAME": "tester",
            "GIT_COMMITTER_EMAIL": IDENTITY,
        }
        (self.base / "tmp").mkdir()
        self.remote = self.base / "origin.git"
        self.work = self.base / "work"
        self.git(self.base, "init", "-q", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.base, "init", "-q", "--initial-branch=main", str(self.work))
        for rel in BASE_FILES:
            target = self.work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, target)
        self.write("docs/README.md", "# Synthetic base\n")
        self.commit("Synthetic trusted base", ".")

    def git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True)
        if proc.returncode != 0:
            self.testcase.fail(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        target = self.work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message: str, *paths: str) -> str:
        self.git(self.work, "add", "--", *paths)
        self.git(self.work, "commit", "-q", "-m", message)
        return self.git(self.work, "rev-parse", "HEAD")

    def publish_base(self) -> None:
        self.git(self.work, "push", "-q", str(self.remote), "main:refs/heads/main")
        self.git(self.work, "checkout", "-q", "-b", "pr")

    def open(self) -> Path:
        """Push the PR branch and make the CI clone: all branches fetched, PR head detached."""
        head = self.git(self.work, "rev-parse", "HEAD")
        self.git(self.work, "push", "-q", str(self.remote), "pr:refs/heads/pr")
        clone = self.base / "ci"
        self.git(self.base, "clone", "-q", str(self.remote), str(clone))
        self.git(clone, "checkout", "-q", "--detach", head)
        self.head = head
        return clone

    def run_scans(self) -> dict[str, JobResult]:
        clone = self.open()
        workflow = load_workflow(self.work / ".github" / "workflows" / "privacy.yml")
        context = {
            "github.event_name": "pull_request",
            "github.base_ref": "main",
            "github.event.pull_request.head.sha": self.head,
        }
        scratch = self.base / "runner"
        scratch.mkdir()
        return {job: run_job(workflow, job, clone, context, scratch, self.env) for job in SCAN_JOBS}

    def betterleaks_alone(self, *extra: str) -> int:
        """Betterleaks run directly in the CI clone, honouring what the PR ships (no -i, allows on)."""
        clone = self.base / "ci"
        proc = subprocess.run(
            ["betterleaks", "git", "--log-opts=--all", ".", "--redact", "--no-banner", "--log-level", "error", *extra],
            cwd=clone,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return proc.returncode


def finding_fingerprint(work: Path, env: dict, path: str) -> str:
    """The fingerprint Betterleaks gives the finding in PATH, read from a real run."""
    proc = subprocess.run(
        ["betterleaks", "git", ".", "--redact", "--no-banner", "--log-level", "error",
         "--report-format", "json", "--report-path", "-"],
        cwd=work, env=env, capture_output=True, text=True,
    )
    found = [f["Fingerprint"] for f in json.loads(proc.stdout or "[]") if f.get("File") == path]
    if len(found) != 1:
        raise AssertionError(f"expected one finding in {path}, got {len(found)}")
    return found[0]


class PrivacyWorkflowPullRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("betterleaks") is None:
            raise AssertionError("betterleaks is not installed: brew install betterleaks")
        workflow = load_workflow()
        pinned = workflow["jobs"]["betterleaks"]["env"]["BETTERLEAKS_VERSION"]
        local = subprocess.run(["betterleaks", "version"], capture_output=True, text=True).stdout.strip()
        if local.lstrip("v") != pinned:
            raise AssertionError(f"local betterleaks {local} is not the pinned {pinned}")

    def assertStepPassed(self, results: dict[str, JobResult]) -> None:
        for job, result in results.items():
            failed = result.failed
            self.assertIsNone(failed, f"{job} failed: {failed and failed.name}\n{failed and failed.output}")
            self.assertTrue(result.steps, f"{job} ran no step")

    def assertScanBlocked(self, result: JobResult, marker: str) -> None:
        """The scan step itself must refuse with findings (exit 1), not with a harness error."""
        failed = result.failed
        self.assertIsNotNone(failed, f"{result.job} passed:\n" + "\n".join(s.output for s in result.steps))
        self.assertTrue(failed.name.startswith("Scan"), f"{result.job}: '{failed.name}' failed instead\n{failed.output}")
        self.assertEqual(failed.returncode, 1, failed.output)
        self.assertIn(marker, failed.output)

    # The workflow file itself

    def test_pull_requests_trigger_the_scans_unconditionally(self) -> None:
        workflow = load_workflow()
        self.assertIn("pull_request", workflow["on"])
        self.assertIsNone(workflow["on"]["pull_request"], "a filter lets some pull requests skip the scans")
        for job in SCAN_JOBS:
            self.assertIn(job, workflow["jobs"])

    # Controls

    def test_clean_pull_request_passes(self) -> None:
        pr = PullRequest(self)
        pr.publish_base()
        pr.write("docs/notes.md", "# Notes\nPut `betterleaks:allow` on a line to exempt it.\n")
        pr.commit("Add notes", "docs/notes.md")
        self.assertStepPassed(pr.run_scans())

    def test_inline_exemption_already_on_the_base_does_not_fail_later_pull_requests(self) -> None:
        pr = PullRequest(self)
        pr.write("docs/fixture.txt", f'value = "{registry_token()}"  # betterleaks:allow\n')
        pr.commit("Reviewed fixture", "docs/fixture.txt")
        pr.publish_base()
        pr.write("docs/notes.md", "# Notes\n")
        pr.commit("Add notes", "docs/notes.md")
        self.assertStepPassed(pr.run_scans())

    # Attacks: each must fail the scan step

    def test_pull_request_adding_an_ignore_file_is_blocked(self) -> None:
        for name in (".betterleaksignore", ".gitleaksignore"):
            with self.subTest(ignore_file=name):
                pr = PullRequest(self)
                pr.publish_base()
                pr.write("docs/sample.txt", f'value = "{registry_token()}"\n')
                pr.commit("Add sample", "docs/sample.txt")
                fingerprint = finding_fingerprint(pr.work, pr.env, "docs/sample.txt")
                pr.write(name, fingerprint + "\n")
                pr.commit("Add ignore file", name)
                results = pr.run_scans()
                # The ignore file does hide the finding when Betterleaks is left to honour it.
                self.assertEqual(pr.betterleaks_alone(), 0)
                self.assertScanBlocked(results["betterleaks"], "betterleaks exited 1")

    def test_pull_request_adding_an_inline_exemption_is_blocked(self) -> None:
        for comment in ("# gitleaks:allow", "# betterleaks:allow", "# _gitleaks:allow", "# nobetterleaks:allow"):
            with self.subTest(comment=comment):
                pr = PullRequest(self)
                pr.publish_base()
                pr.write("docs/sample.txt", f'value = "{registry_token()}"  {comment}\n')
                pr.commit("Add sample", "docs/sample.txt")
                results = pr.run_scans()
                # Betterleaks itself honours the comment when allowed to.
                self.assertEqual(pr.betterleaks_alone(), 0)
                self.assertScanBlocked(results["betterleaks"], "betterleaks exited 1")
                # The refusal says that the PR's own inline comment was not honoured.
                self.assertRegex(results["betterleaks"].failed.output,
                                 r"\b1 added line\(s\) carry an inline allow comment")

    def test_pull_request_replacing_the_scanners_or_rules_is_blocked(self) -> None:
        stub_py = "import sys\nsys.exit(0)\n"
        stub_sh = "#!/bin/sh\nexit 0\n"
        no_rules = json.dumps({"version": 1, "rules": []})
        cases = {
            "privacy scanner": {"tools/privacy_scan.py": stub_py},
            "privacy rules": {"tools/privacy_rules.json": no_rules},
            "secret wrapper": {"tools/secret_scan.sh": stub_sh},
            "all of them": {"tools/privacy_scan.py": stub_py, "tools/privacy_rules.json": no_rules,
                            "tools/secret_scan.sh": stub_sh},
        }
        for label, swaps in cases.items():
            with self.subTest(swap=label):
                pr = PullRequest(self)
                pr.publish_base()
                for rel, text in swaps.items():
                    pr.write(rel, text)
                pr.write("docs/sample.txt", f'value = "{github_token()}"\n')
                pr.commit("Swap the guard", "docs/sample.txt", *swaps)
                results = pr.run_scans()
                if "tools/privacy_scan.py" in swaps or "tools/privacy_rules.json" in swaps:
                    self.assertScanBlocked(results["scan"], "credential_shape")
                if "tools/secret_scan.sh" in swaps:
                    self.assertScanBlocked(results["betterleaks"], "betterleaks exited 1")


if __name__ == "__main__":
    unittest.main()
