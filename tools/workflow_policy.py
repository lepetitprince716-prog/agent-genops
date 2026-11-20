#!/usr/bin/env python3
"""Policy check for the standard ComfyUI workflows under ``workflows/``.

Every file there is parsed, not grepped: JSON documents are decoded strictly and every key
and string value is checked wherever it sits (inputs, widget values, titles, notes, extra
properties). The registry ``tools/workflow_policy.json`` lists, per workflow folder, the files
it may hold, the node types its graphs may use and the public model file names they may
name. Anything not registered is refused, nothing is silently dropped.

Checks:

- layout: only registered folders and files, no symlinks, no hidden or extra files, every
  registered file present;
- graphs: the expected top-level shape for authoring, API and canvas documents, node types
  from the workflow's list, model names from the workflow's list (bare file names);
- every string: no absolute or home paths, no URL that is not https on a registered host or
  that carries credentials (user info, token-like query parameters), no embedded media or
  opaque blobs, and none of the public rules in ``tools/privacy_rules.json``;
- README files: the same string checks per line, and no images.

A finding names the rule and the place (file, JSON pointer or line), never the matched
value. Names of unregistered files are shown as a hash, since the name itself may be private.
The scope is ``workflows/`` only; the repository-wide guards are ``tools/privacy_scan.py``
and ``tools/secret_scan.sh``.

Exit status: 0 clean, 1 findings, 2 the registry or the rules could not be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, unquote, urlsplit

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import privacy_scan  # noqa: E402

POLICY_PATH = TOOLS / "workflow_policy.json"
RULES_PATH = TOOLS / "privacy_rules.json"

# Top-level keys each kind of document may carry.
AUTHORING_INFO = "_workflow"
NODE_KEYS = frozenset({"class_type", "inputs", "_meta"})
CANVAS_KEYS = frozenset(
    {"last_node_id", "last_link_id", "nodes", "links", "groups", "config", "extra", "version", "models"}
)
# Inputs that name a model file; their values must be registered model names.
MODEL_INPUTS = frozenset(
    {
        "ckpt_name",
        "lora_name",
        "vae_name",
        "unet_name",
        "clip_name",
        "clip_name1",
        "clip_name2",
        "control_net_name",
        "model_name",
        "upscale_model",
        "style_model_name",
    }
)

SAFE_KEY = re.compile(r"[A-Za-z0-9_. -]{1,64}")
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>()\[\]]*")
# User info after a bare "//", with no scheme in front (URLs with a scheme go through urlsplit).
SCHEMELESS_USERINFO = re.compile(r"(?<![A-Za-z0-9+.-]:)(?<![A-Za-z0-9])//[^\s/@]+:[^\s/@]*@")
DATA_URI = re.compile(r"\bdata:[A-Za-z0-9.+-]*/?[A-Za-z0-9.+-]*(?:;[A-Za-z0-9=.+-]+)*,", re.I)
BLOB = re.compile(r"[A-Za-z0-9+/_-]{120,}={0,2}")
# Absolute paths: POSIX roots that hold machine or account data, home shorthands, Windows
# drives and UNC shares. URLs are removed before this runs.
ABS_PATH = re.compile(
    r"(?:^|[^A-Za-z0-9._~-])/(?:Users|home|root|private|tmp|var|mnt|media|Volumes|opt|srv|etc|data|workspace)(?:/|$)"
    r"|(?:^|[^A-Za-z0-9._-])~[A-Za-z0-9._-]*/"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    # A drive-relative Windows path (C:Users\name): a drive letter, a folder name, a separator.
    r"|(?<![A-Za-z0-9])[A-Za-z]:[^\s\\/:]+[\\/]"
    r"|\\\\[A-Za-z0-9]"
)
CREDENTIAL_PARAM = re.compile(
    r"(?i)token|key|sig|signature|auth|pass|secret|credential|session|cookie|^x-amz-|^x-goog-"
)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(|<img\b", re.I)
MAX_STRING = 4000
# Percent-encoding is undone this many times at most; each string is checked as written and as
# each decoding gives it, so an encoded path cannot slip past the path and privacy checks. A
# string that one more round would still change cannot be judged, so it is refused (over_encoded).
MAX_DECODE_ROUNDS = 4


def decoded_variants(text: str) -> list[str]:
    """``text`` and each distinct percent-decoding of it, until decoding changes nothing."""
    variants = [text]
    for _ in range(MAX_DECODE_ROUNDS):
        decoded = unquote(variants[-1])
        if decoded == variants[-1]:
            break
        variants.append(decoded)
    return variants


def over_encoded(variants: list[str]) -> bool:
    """True when ``variants`` stopped at the round limit and one more decoding would still change it."""
    return len(variants) > MAX_DECODE_ROUNDS and unquote(variants[-1]) != variants[-1]


class PolicyError(Exception):
    """The registry or the rules cannot be used (exit status 2)."""


@dataclass(frozen=True)
class Finding:
    where: str
    place: str
    rule: str
    why: str

    def __str__(self) -> str:
        place = f" {self.place}" if self.place else ""
        return f"{self.where}:{place} {self.rule} -- {self.why}"


@dataclass(frozen=True)
class Workflow:
    files: frozenset[str]
    nodes: frozenset[str]
    models: frozenset[str]


@dataclass(frozen=True)
class Policy:
    top_files: frozenset[str]
    url_hosts: frozenset[str]
    model_extensions: tuple[str, ...]
    workflows: dict[str, Workflow]


def _strings(value: Any, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise PolicyError(f"{where} must be a list of non-empty strings")
    return frozenset(value)


def load_policy(path: Path = POLICY_PATH) -> Policy:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"cannot read the registry: {type(exc).__name__}") from None
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("workflows"), dict):
        raise PolicyError("the registry needs version 1 and a workflows object")
    workflows = {}
    for slug, entry in doc["workflows"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug) or not isinstance(entry, dict):
            raise PolicyError("a workflow entry has a bad folder name or is not an object")
        models = _strings(entry.get("models", []), f"workflows.{slug}.models") if entry.get("models") else frozenset()
        if any("/" in m or "\\" in m for m in models):
            raise PolicyError(f"workflows.{slug}.models must be bare file names")
        workflows[slug] = Workflow(
            files=_strings(entry.get("files"), f"workflows.{slug}.files"),
            nodes=_strings(entry.get("nodes"), f"workflows.{slug}.nodes"),
            models=models,
        )
    return Policy(
        top_files=_strings(doc.get("top_files", []), "top_files") if doc.get("top_files") else frozenset(),
        url_hosts=_strings(doc.get("url_hosts"), "url_hosts"),
        model_extensions=tuple(sorted(_strings(doc.get("model_extensions"), "model_extensions"))),
        workflows=workflows,
    )


def load_rules(path: Path = RULES_PATH) -> privacy_scan.RuleSet:
    try:
        return privacy_scan.load_ruleset(path)
    except privacy_scan.ScanError as exc:
        raise PolicyError(f"cannot load the public privacy rules: {exc}") from None


def alias(name: str) -> str:
    """A name that may be private, shown as a short hash."""
    return "entry#" + hashlib.sha256(name.encode("utf-8", "surrogateescape")).hexdigest()[:8]


def pointer(parts: tuple[Any, ...]) -> str:
    out = []
    for part in parts:
        if isinstance(part, int):
            out.append(str(part))
        elif SAFE_KEY.fullmatch(part) and not ABS_PATH.search(part):
            out.append(part.replace("~", "~0").replace("/", "~1"))
        else:
            out.append("<" + alias(part) + ">")
    return "/" + "/".join(out)


class Checker:
    def __init__(self, policy: Policy, rules: privacy_scan.RuleSet):
        self.policy = policy
        self.rules = rules
        self.findings: list[Finding] = []

    def add(self, where: str, place: str, rule: str, why: str) -> None:
        self.findings.append(Finding(where, place, rule, why))

    # --- strings ---------------------------------------------------------------

    def check_string(self, text: str, where: str, place: str, workflow: Workflow | None) -> None:
        if len(text) > MAX_STRING:
            self.add(where, place, "oversize_string", f"a string longer than {MAX_STRING} characters")
        first = len(self.findings)
        self.check_content(text, where, place)
        found = {f.rule for f in self.findings[first:]}
        variants = decoded_variants(text)
        if over_encoded(variants):
            self.add(where, place, "over_encoded", "encoded in more layers than the check decodes, so it cannot be judged")
        for variant in variants[1:]:
            probe = Checker(self.policy, self.rules)
            probe.check_content(variant, where, place)
            for finding in probe.findings:
                if finding.rule not in found:
                    found.add(finding.rule)
                    self.findings.append(finding)
        lowered = text.lower()
        if workflow is not None and lowered.endswith(self.policy.model_extensions) and "://" not in text:
            self.check_model(text, where, place, workflow)

    def check_content(self, text: str, where: str, place: str) -> None:
        """The checks on what a string says, run on it as written and on each decoding of it."""
        if DATA_URI.search(text):
            self.add(where, place, "embedded_media", "a data: URI embeds a file")
        if BLOB.search(text):
            self.add(where, place, "opaque_blob", "a long base64-like run hides data that cannot be reviewed")
        for match in URL.finditer(text):
            self.check_url(match.group(), where, place)
        if SCHEMELESS_USERINFO.search(text):
            self.add(where, place, "url_credentials", "an address carries a user name or password")
        bare = URL.sub(" ", text)
        if ABS_PATH.search(bare):
            self.add(where, place, "abs_path", "an absolute or home path; use a bare file name")
        for hit in privacy_scan.scan_values([text], self.rules, ".json"):
            self.add(where, place, f"privacy:{hit.rule_id}", hit.why)

    def check_url(self, url: str, where: str, place: str) -> None:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            self.add(where, place, "url_host", "an address that does not parse")
            return
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            self.add(where, place, "url_credentials", "an address carries a user name or password")
        if any(CREDENTIAL_PARAM.search(name) for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
            self.add(where, place, "url_credentials", "an address carries a credential-like query parameter")
        if parts.scheme.lower() != "https":
            self.add(where, place, "url_scheme", "only https addresses are allowed")
        host = (parts.hostname or "").lower()
        if host not in self.policy.url_hosts or port is not None:
            self.add(where, place, "url_host", "the host is not on the registry's list of public hosts")

    def check_model(self, name: str, where: str, place: str, workflow: Workflow) -> None:
        # Registered names are bare file names, so a name with a folder is never registered.
        if name not in workflow.models:
            self.add(where, place, "model_name", "a model file name (bare, no folder) not registered for this workflow")

    def walk(self, value: Any, where: str, parts: tuple[Any, ...], workflow: Workflow) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                self.check_string(key, where, pointer(parts + (key,)) + " (key)", workflow)
                if key in MODEL_INPUTS and isinstance(item, str):
                    self.check_model(item, where, pointer(parts + (key,)), workflow)
                self.walk(item, where, parts + (key,), workflow)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.walk(item, where, parts + (index,), workflow)
        elif isinstance(value, str):
            self.check_string(value, where, pointer(parts), workflow)

    # --- documents -------------------------------------------------------------

    def node_type(self, value: Any, where: str, place: str, workflow: Workflow) -> None:
        if not isinstance(value, str) or value not in workflow.nodes:
            self.add(where, place, "node_type", "a node type not registered for this workflow")

    def check_graph(self, doc: Any, where: str, name: str, workflow: Workflow) -> None:
        if not isinstance(doc, dict):
            self.add(where, "", "shape", "the document is not a JSON object")
            return
        if name.endswith(".ui.json"):
            for key in doc:
                if key not in CANVAS_KEYS:
                    self.add(where, pointer((key,)), "unknown_field", "a canvas field this policy has not reviewed")
            nodes = doc.get("nodes")
            if not isinstance(nodes, list):
                self.add(where, "/nodes", "shape", "a canvas needs a nodes list")
                nodes = []
            for index, node in enumerate(nodes):
                kind = node.get("type") if isinstance(node, dict) else None
                self.node_type(kind, where, pointer(("nodes", index, "type")), workflow)
        else:
            for key, node in doc.items():
                if key == AUTHORING_INFO and not name.endswith(".api.json"):
                    continue
                if not isinstance(node, dict):
                    self.add(where, pointer((key,)), "shape", "a graph entry is not a node object")
                    continue
                for field in node:
                    if field not in NODE_KEYS:
                        self.add(where, pointer((key, field)), "unknown_field", "a node field this policy has not reviewed")
                self.node_type(node.get("class_type"), where, pointer((key, "class_type")), workflow)
        self.walk(doc, where, (), workflow)

    def check_json(self, path: Path, where: str, workflow: Workflow) -> None:
        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            keys = [k for k, _ in pairs]
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate key")
            return dict(pairs)

        def no_constant(_: str) -> Any:
            raise ValueError("non-finite number")

        try:
            text = path.read_bytes().decode("utf-8")
            doc = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constant)
        except UnicodeDecodeError:
            self.add(where, "", "encoding", "the file is not UTF-8 text")
            return
        except ValueError:
            self.add(where, "", "json", "the file is not strict JSON (syntax, duplicate key or NaN)")
            return
        self.check_graph(doc, where, path.name, workflow)

    def check_markdown(self, path: Path, where: str) -> None:
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            self.add(where, "", "encoding", "the file is not UTF-8 text")
            return
        for number, line in enumerate(text.split("\n"), start=1):
            place = f"line {number}"
            if MARKDOWN_IMAGE.search(line):
                self.add(where, place, "embedded_media", "images do not belong in workflow folders")
            self.check_string(line, where, place, None)

    # --- tree ------------------------------------------------------------------

    def entries(self, folder: Path, rel: str) -> Iterator[tuple[Path, str]]:
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            yield path, f"{rel}/{path.name}"

    def unregistered(self, path: Path, rel_dir: str) -> None:
        kind = "symlink" if path.is_symlink() else "folder" if path.is_dir() else "file"
        self.add(f"{rel_dir}/{alias(path.name)}", "", "unregistered_entry", f"a {kind} the registry does not list")

    def check_tree(self, root: Path) -> list[Finding]:
        base = "workflows"
        if not root.is_dir() or root.is_symlink():
            self.add(base, "", "missing", "the workflows folder is missing")
            return self.findings
        seen = set()
        for path, rel in self.entries(root, base):
            name = path.name
            if path.is_symlink():
                self.unregistered(path, base)
            elif path.is_dir() and name in self.policy.workflows:
                seen.add(name)
                self.check_workflow(path, rel, self.policy.workflows[name])
            elif path.is_file() and name in self.policy.top_files:
                self.check_markdown(path, rel)
            else:
                self.unregistered(path, base)
        for slug in sorted(self.policy.workflows.keys() - seen):
            self.add(f"{base}/{slug}", "", "missing", "a registered workflow folder is missing")
        return self.findings

    def check_workflow(self, folder: Path, rel: str, workflow: Workflow) -> None:
        present = set()
        for path, child in self.entries(folder, rel):
            if path.is_symlink() or not path.is_file() or path.name not in workflow.files:
                self.unregistered(path, rel)
                continue
            present.add(path.name)
            if path.name.endswith(".json"):
                self.check_json(path, child, workflow)
            elif path.name.endswith(".md"):
                self.check_markdown(path, child)
            else:
                self.add(child, "", "file_type", "a registered file of a type this policy cannot read")
        for name in sorted(workflow.files - present):
            self.add(f"{rel}/{name}", "", "missing", "a registered file is missing")


def check(root: Path, policy: Policy | None = None, rules: privacy_scan.RuleSet | None = None) -> list[Finding]:
    checker = Checker(policy or load_policy(), rules or load_rules())
    return checker.check_tree(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check workflows/ against tools/workflow_policy.json.")
    parser.add_argument("--root", type=Path, default=ROOT / "workflows", help="the workflows folder")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH, help="the registry")
    args = parser.parse_args(argv)
    try:
        findings = check(args.root, load_policy(args.policy), load_rules())
    except PolicyError as exc:
        print(f"workflow_policy: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    if findings:
        print(f"workflow_policy: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("workflow_policy: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
