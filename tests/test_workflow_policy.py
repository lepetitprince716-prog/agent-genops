"""The workflow policy (tools/workflow_policy.py) and the committed standard workflows.

The committed tree must pass; each kind of violation is planted in a copy of the tree in a
temporary folder and must be refused, and the report must not repeat the planted value or
the planted file name. Planted values are synthetic and built at run time (random account
names, made-up hosts, random credentials), so no private-looking literal sits in this file.

The regression tests compile every registered workflow's input again with the cwc in this
repository and compare the result with the committed canvas and API prompt, byte for byte
(cwc promises identical bytes for the same input, version and data: cwc/docs/ARCHITECTURE.md,
"Deterministic output"), and check with cwc's own equivalence check that the committed
canvas exports the committed API prompt.
"""

import contextlib
import io
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / "workflows"
CWC = ROOT / "cwc"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(CWC / "src"))

import workflow_policy  # noqa: E402

POLICY = workflow_policy.load_policy()
RULES = workflow_policy.load_rules()
SLUG = "sdxl-txt2img"


def token(length=12):
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))


def run_cli(root):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = workflow_policy.main(["--root", str(root)])
    return code, out.getvalue() + err.getvalue()


class Tree(unittest.TestCase):
    """A copy of workflows/ in a temporary folder, to plant violations in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workflows"
        shutil.copytree(WORKFLOWS, self.root, symlinks=True)
        self.folder = self.root / SLUG

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, suffix):
        return json.loads((self.folder / f"{SLUG}{suffix}").read_text(encoding="utf-8"))

    def save(self, suffix, doc):
        (self.folder / f"{SLUG}{suffix}").write_text(json.dumps(doc), encoding="utf-8")

    def rules(self):
        return sorted({f.rule for f in workflow_policy.check(self.root, POLICY, RULES)})

    def assertRefused(self, rule, *hidden):
        """The planted violation is refused with ``rule``, and no hidden value is printed."""
        self.assertIn(rule, self.rules())
        code, output = run_cli(self.root)
        self.assertEqual(code, 1, output)
        for value in hidden:
            self.assertNotIn(value, output)


class CommittedTreeTest(unittest.TestCase):
    def test_the_committed_workflows_pass(self):
        findings = workflow_policy.check(WORKFLOWS, POLICY, RULES)
        self.assertEqual([str(f) for f in findings], [])

    def test_the_command_line_reports_clean(self):
        self.assertEqual(run_cli(WORKFLOWS), (0, "workflow_policy: clean\n"))

    def test_a_json_file_outside_workflows_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workflows"
            shutil.copytree(WORKFLOWS, root)
            (Path(tmp) / "schema.json").write_text(json.dumps({"$id": "https://example.org/schema"}))
            self.assertEqual(workflow_policy.check(root, POLICY, RULES), [])


class RecompileTest(unittest.TestCase):
    def test_compiling_the_input_again_gives_the_committed_files(self):
        for slug in sorted(POLICY.workflows):
            with self.subTest(slug), tempfile.TemporaryDirectory() as tmp:
                child = dict(os.environ, PYTHONPATH=str(CWC / "src"))
                source = WORKFLOWS / slug / f"{slug}.json"
                done = subprocess.run(
                    [sys.executable, "-B", "-m", "cwc", "compile", str(source), "-o", tmp],
                    cwd=CWC, env=child, capture_output=True, text=True,
                )
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                report = json.loads((Path(tmp) / f"{slug}.report.json").read_text(encoding="utf-8"))
                self.assertTrue(report["ok"])
                self.assertEqual([f for f in report["findings"] if f["severity"] != "info"], [])
                for suffix in (".ui.json", ".api.json"):
                    built = (Path(tmp) / f"{slug}{suffix}").read_bytes()
                    committed = (WORKFLOWS / slug / f"{slug}{suffix}").read_bytes()
                    self.assertEqual(built, committed, f"{slug}{suffix} differs from a fresh compile")

    def test_the_committed_canvas_exports_the_committed_prompt(self):
        from cwc.ingest import load_canvas
        from cwc.nodedefs import derive
        from cwc.nodedefs.registry import NodeDefs
        from cwc.prompt.from_canvas import canvas_to_prompt
        from cwc.prompt.model import prompt_diff

        defs = NodeDefs.load()
        for slug in sorted(POLICY.workflows):
            with self.subTest(slug):
                canvas = load_canvas((WORKFLOWS / slug / f"{slug}.ui.json").read_bytes())
                api = json.loads((WORKFLOWS / slug / f"{slug}.api.json").read_text(encoding="utf-8"))
                exported = canvas_to_prompt(canvas, defs, widget_layout=derive.widget_layout)
                self.assertEqual(prompt_diff(api, exported), [])


class PrivatePathTest(Tree):
    def test_a_home_path_in_a_node_note_is_refused(self):
        account = "acct" + token()
        path = "/" + "Users" + "/" + account + "/models"
        doc = self.load(".json")
        doc["latent"]["_meta"]["ui_note"] = f"weights live in {path}"
        self.save(".json", doc)
        self.assertRefused("abs_path", account)

    def test_a_windows_profile_path_in_a_canvas_group_title_is_refused(self):
        account = "acct" + token()
        doc = self.load(".ui.json")
        doc["groups"][0]["title"] = "C:" + "\\" + "Users" + "\\" + account + "\\notes"
        self.save(".ui.json", doc)
        self.assertRefused("abs_path", account)

    def test_a_percent_encoded_home_path_in_a_node_note_is_refused(self):
        account = "acct" + token()
        plain = "/" + "Users" + "/" + account + "/models"
        once = plain.replace("/", "%2F")
        for label, value in (("once", once), ("twice", once.replace("%", "%25")), ("mixed case", once.replace("%2F", "%2f"))):
            with self.subTest(encoding=label):
                doc = self.load(".json")
                doc["latent"]["_meta"]["ui_note"] = f"weights live in {value}"
                self.save(".json", doc)
                self.assertRefused("abs_path", account, value)

    def test_a_drive_relative_windows_path_is_refused(self):
        account = "acct" + token()
        for value in ("C:" + "Users" + "\\" + account + "\\notes", "d:" + "Users" + "/" + account + "/notes"):
            with self.subTest(value=value):
                doc = self.load(".ui.json")
                doc["groups"][0]["title"] = value
                self.save(".ui.json", doc)
                self.assertRefused("abs_path", account)

    def test_decoding_stops_after_a_bounded_number_of_rounds(self):
        """A value nested in more encoding layers than the bound is not decoded forever."""
        value = "/" + "Users" + "/" + "acct" + token()
        for _ in range(workflow_policy.MAX_DECODE_ROUNDS + 3):
            value = value.replace("%", "%25").replace("/", "%2F")
        variants = workflow_policy.decoded_variants(value)
        self.assertLessEqual(len(variants), workflow_policy.MAX_DECODE_ROUNDS + 1)
        self.assertEqual(variants[0], value)

    def test_a_home_path_encoded_past_the_bound_is_refused_not_passed(self):
        """More encoding layers than the bound cannot be decided, so they are refused, never clean."""
        account = "acct" + token()
        value = "/" + "Users" + "/" + account + "/models"
        for layers in range(1, workflow_policy.MAX_DECODE_ROUNDS + 4):
            value = quote(value, safe="")
            with self.subTest(layers=layers):
                doc = self.load(".json")
                doc["latent"]["_meta"]["ui_note"] = f"weights live in {value}"
                self.save(".json", doc)
                if layers > workflow_policy.MAX_DECODE_ROUNDS:
                    self.assertRefused("over_encoded", account, value)
                else:
                    self.assertRefused("abs_path", account, value)
                    self.assertNotIn("over_encoded", self.rules())

    def test_an_over_encoded_string_is_refused_even_without_a_path_in_it(self):
        value = "a/b"
        for _ in range(workflow_policy.MAX_DECODE_ROUNDS + 1):
            value = quote(value, safe="")
        doc = self.load(".json")
        doc["latent"]["_meta"]["ui_note"] = value
        self.save(".json", doc)
        self.assertEqual(self.rules(), ["over_encoded"])

    def test_filename_placeholders_and_literal_percent_signs_are_not_over_encoded(self):
        values = ("%date%", "%date:yyyy-MM-dd%/img_%seed%", "%KSampler.seed%_%width%x%height%", "50%", "100% detail", "%25")
        for value in values:
            with self.subTest(value=value):
                doc = self.load(".json")
                doc["latent"]["_meta"]["ui_note"] = value
                self.save(".json", doc)
                self.assertEqual(self.rules(), [])

    def test_control_prompt_weights_and_plain_percent_signs_are_accepted(self):
        doc = self.load(".json")
        doc["latent"]["_meta"]["ui_note"] = "(a:1.2), 100% detail, 50%2 off, x:1"
        self.save(".json", doc)
        self.assertNotIn("abs_path", self.rules())

    def test_a_lan_address_in_an_extra_property_is_refused(self):
        address = ".".join(["192", "168", str(secrets.randbelow(200) + 1), str(secrets.randbelow(200) + 1)])
        doc = self.load(".ui.json")
        doc["extra"]["origin"] = {"server": address}
        self.save(".ui.json", doc)
        self.assertRefused("privacy:lan_ip", address)

    def test_a_model_name_with_a_folder_is_refused(self):
        folder = "acct" + token()
        doc = self.load(".api.json")
        node = next(n for n in doc.values() if n["class_type"] == "CheckpointLoaderSimple")
        node["inputs"]["ckpt_name"] = f"{folder}/sd_xl_base_1.0.safetensors"
        self.save(".api.json", doc)
        self.assertRefused("model_name", folder)


class CredentialUrlTest(Tree):
    def plant_url(self, url):
        doc = self.load(".json")
        doc["_workflow"]["models"][0]["url"] = url
        self.save(".json", doc)

    def test_user_info_in_a_model_url_is_refused(self):
        user, secret = "u" + token(), "p" + token(20)
        self.plant_url(f"https://{user}:{secret}@huggingface.co/x/resolve/main/sd_xl_base_1.0.safetensors")
        self.assertRefused("url_credentials", user, secret)

    def test_a_token_query_parameter_is_refused(self):
        secret = token(32)
        self.plant_url(f"https://huggingface.co/x/resolve/main/sd_xl_base_1.0.safetensors?access_token={secret}")
        self.assertRefused("url_credentials", secret)

    def test_user_info_in_a_readme_link_is_refused(self):
        user, secret = "u" + token(), "p" + token(20)
        readme = self.folder / "README.md"
        readme.write_text(readme.read_text() + f"\nmirror: https://{user}:{secret}@github.com/x/y\n")
        self.assertRefused("url_credentials", user, secret)

    def test_user_info_without_a_scheme_is_refused(self):
        user, secret = "u" + token(), "p" + token(20)
        doc = self.load(".ui.json")
        doc["extra"]["mirror"] = f"//{user}:{secret}@files.example.org/x"
        self.save(".ui.json", doc)
        self.assertRefused("url_credentials", user, secret)

    def test_an_unregistered_host_is_refused(self):
        host = "h" + token() + ".example.net"
        self.plant_url(f"https://{host}/sd_xl_base_1.0.safetensors")
        self.assertRefused("url_host", host)


class MediaAndSidecarTest(Tree):
    def test_an_image_file_in_a_workflow_folder_is_refused(self):
        name = "preview-" + token() + ".png"
        (self.folder / name).write_bytes(b"\x89PNG\r\n\x1a\n" + secrets.token_bytes(64))
        self.assertRefused("unregistered_entry", name)

    def test_the_compile_report_sidecar_is_refused(self):
        (self.folder / f"{SLUG}.report.json").write_text("{}")
        self.assertRefused("unregistered_entry", f"{SLUG}.report.json")

    def test_a_hidden_file_and_an_unregistered_folder_are_refused(self):
        hidden = "." + token()
        (self.folder / hidden).write_text("x")
        extra = "wf-" + token()
        (self.root / extra).mkdir()
        self.assertRefused("unregistered_entry", hidden, extra)
        self.assertEqual(sum(f.rule == "unregistered_entry" for f in workflow_policy.check(self.root, POLICY, RULES)), 2)

    def test_a_symlink_is_refused(self):
        name = "link-" + token() + ".json"
        (self.folder / name).symlink_to(self.folder / f"{SLUG}.json")
        self.assertRefused("unregistered_entry", name)

    def test_a_data_uri_in_a_widget_value_is_refused(self):
        payload = secrets.token_hex(16)
        doc = self.load(".ui.json")
        save = next(n for n in doc["nodes"] if n["type"] == "SaveImage")
        save["widgets_values"][0] = "data:image/png;base64," + payload
        self.save(".ui.json", doc)
        self.assertRefused("embedded_media", payload)

    def test_an_opaque_blob_in_a_prompt_is_refused(self):
        import base64

        blob = base64.b64encode(secrets.token_bytes(150)).decode()
        doc = self.load(".api.json")
        node = next(n for n in doc.values() if n["class_type"] == "CLIPTextEncode")
        node["inputs"]["text"] = "a lake " + blob
        self.save(".api.json", doc)
        self.assertRefused("opaque_blob", blob[:40])

    def test_an_image_in_a_readme_is_refused(self):
        readme = self.folder / "README.md"
        readme.write_text(readme.read_text() + "\n![cover](cover.png)\n")
        self.assertRefused("embedded_media")


class GraphShapeTest(Tree):
    def test_an_unregistered_node_type_is_refused(self):
        doc = self.load(".api.json")
        doc["99"] = {"class_type": "LoadImage", "inputs": {"image": "x.png"}, "_meta": {"title": "x"}}
        self.save(".api.json", doc)
        self.assertRefused("node_type")

    def test_an_unregistered_model_name_is_refused(self):
        name = "m" + token() + ".safetensors"
        doc = self.load(".ui.json")
        loader = next(n for n in doc["nodes"] if n["type"] == "CheckpointLoaderSimple")
        loader["widgets_values"][0] = name
        self.save(".ui.json", doc)
        self.assertRefused("model_name", name)

    def test_an_unreviewed_canvas_field_is_refused(self):
        doc = self.load(".ui.json")
        doc["definitions"] = {"subgraphs": []}
        self.save(".ui.json", doc)
        self.assertRefused("unknown_field")

    def test_an_unreviewed_node_field_is_refused(self):
        doc = self.load(".api.json")
        next(iter(doc.values()))["extra"] = {}
        self.save(".api.json", doc)
        self.assertRefused("unknown_field")

    def test_a_duplicate_key_is_refused(self):
        path = self.folder / f"{SLUG}.api.json"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("{", '{"1": {}, ', 1), encoding="utf-8")
        self.assertRefused("json")


class StringLimitsTest(Tree):
    def test_an_address_that_is_not_https_is_refused(self):
        tail = token(20)
        doc = self.load(".json")
        doc["_workflow"]["models"][0]["url"] = f"http://huggingface.co/x/resolve/main/{tail}/sd_xl_base_1.0.safetensors"
        self.save(".json", doc)
        self.assertRefused("url_scheme", tail)
        # The host is registered and the address carries no credentials: only the scheme is wrong.
        self.assertEqual([r for r in self.rules() if r.startswith("url_")], ["url_scheme"])

    def test_a_string_over_the_length_limit_is_refused(self):
        marker = token(16)
        doc = self.load(".api.json")
        node = next(n for n in doc.values() if n["class_type"] == "CLIPTextEncode")
        # Short words with spaces, so only the length rule can fire (no blob, path or address).
        node["inputs"]["text"] = marker + " " + "lake " * (workflow_policy.MAX_STRING // 5 + 1)
        self.save(".api.json", doc)
        self.assertRefused("oversize_string", marker)
        self.assertEqual(self.rules(), ["oversize_string"])

    def test_a_string_at_the_length_limit_is_accepted(self):
        doc = self.load(".api.json")
        node = next(n for n in doc.values() if n["class_type"] == "CLIPTextEncode")
        node["inputs"]["text"] = ("lake " * workflow_policy.MAX_STRING)[: workflow_policy.MAX_STRING]
        self.save(".api.json", doc)
        self.assertEqual(self.rules(), [])


class EncodingTest(Tree):
    def test_a_json_file_that_is_not_utf8_is_refused(self):
        path = self.folder / f"{SLUG}.api.json"
        path.write_bytes(path.read_bytes() + b"\xff\xfe")
        self.assertRefused("encoding")
        self.assertNotIn("json", [f.rule for f in workflow_policy.check(self.root, POLICY, RULES)])

    def test_a_readme_that_is_not_utf8_is_refused(self):
        readme = self.folder / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\n\xc3\x28 broken\n")
        self.assertRefused("encoding")

    def test_the_top_level_readme_that_is_not_utf8_is_refused(self):
        readme = self.root / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\xff")
        self.assertRefused("encoding")


class DocumentShapeTest(Tree):
    def test_a_graph_that_is_not_an_object_is_refused(self):
        self.save(".api.json", [1, 2, 3])
        self.assertRefused("shape")

    def test_a_graph_entry_that_is_not_a_node_is_refused(self):
        doc = self.load(".api.json")
        doc["99"] = "not a node"
        self.save(".api.json", doc)
        self.assertRefused("shape")

    def test_a_canvas_without_a_nodes_list_is_refused(self):
        doc = self.load(".ui.json")
        doc["nodes"] = {"1": {}}
        self.save(".ui.json", doc)
        self.assertRefused("shape")


class FileTypeTest(Tree):
    def test_a_registered_file_of_an_unreadable_type_is_refused(self):
        name = "notes-" + token() + ".txt"
        registry = json.loads((workflow_policy.POLICY_PATH).read_text(encoding="utf-8"))
        registry["workflows"][SLUG]["files"].append(name)
        policy_path = Path(self.tmp.name) / "policy.json"
        policy_path.write_text(json.dumps(registry), encoding="utf-8")
        (self.folder / name).write_text("plain text the policy cannot read", encoding="utf-8")
        policy = workflow_policy.load_policy(policy_path)
        self.assertEqual([f.rule for f in workflow_policy.check(self.root, policy, RULES)], ["file_type"])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = workflow_policy.main(["--root", str(self.root), "--policy", str(policy_path)])
        self.assertEqual(code, 1)
        self.assertIn("file_type", out.getvalue())
        # The same file is unregistered under the committed registry, so it is refused there too.
        self.assertIn("unregistered_entry", self.rules())


class RegistryTest(Tree):
    def test_a_missing_registered_file_is_reported(self):
        (self.folder / f"{SLUG}.api.json").rename(Path(self.tmp.name) / "moved.json")
        self.assertIn("missing", self.rules())

    def test_a_workflows_folder_that_is_a_symlink_is_refused(self):
        """A good tree behind a link is not the folder that gets committed."""
        real = Path(self.tmp.name) / "elsewhere"
        self.root.rename(real)
        self.root.symlink_to(real, target_is_directory=True)
        self.assertEqual([f.rule for f in workflow_policy.check(self.root, POLICY, RULES)], ["missing"])
        code, _output = run_cli(self.root)
        self.assertEqual(code, 1)

    def test_a_broken_registry_exits_2(self):
        bad = Path(self.tmp.name) / "policy.json"
        bad.write_text(json.dumps({"version": 2}))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = workflow_policy.main(["--root", str(self.root), "--policy", str(bad)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
