"""What ``cwc compile`` tells its caller on the terminal and in ``--json``: every finding's
message and hint, typo suggestions for ``_meta`` keys and input names, the success summary."""

import copy
import json
import unittest

from tests import test_cli_compile as base
from tests.test_cli_compile import Folder

from cwc.report import ExitCode

TXT2IMG = base.TXT2IMG
run = base.run


def with_meta(doc, node, **meta):
    doc = copy.deepcopy(doc)
    doc[node].setdefault("_meta", {}).update(meta)
    return doc


class FindingsOnTheTerminalTest(Folder):
    def test_a_warning_and_its_hint_reach_stderr_on_success(self):
        code, _, err = run("compile", self.graph(with_meta(TXT2IMG, "decode", optional=True)), "-o", self.out)
        self.assertEqual(code, ExitCode.OK)
        [line] = [line for line in err.splitlines() if "'optional'" in line and "warning" in line]
        self.assertTrue(line.startswith("E7 warning: node 'decode'"), line)
        self.assertIn("  hint: ", err)

    def test_an_error_hint_reaches_stderr(self):
        doc = copy.deepcopy(TXT2IMG)
        doc["sampler"]["inputs"]["positive"] = ["nowhere", 0]
        code, _, err = run("compile", self.graph(doc), "-o", self.out)
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        report = json.loads((self.out / "graph.report.json").read_text(encoding="utf-8"))
        [finding] = [f for f in report["findings"] if f["code"] == "E6"]
        self.assertIn(f"E6: {finding['message']}\n  hint: {finding['hint']}\n", err)

    def test_json_carries_the_report_findings(self):
        code, out, _ = run("compile", self.graph(with_meta(TXT2IMG, "decode", optional=True)), "-o", self.out, "--json")
        self.assertEqual(code, ExitCode.OK)
        summary = json.loads(out)
        report = json.loads((self.out / "graph.report.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["finding_list"], report["findings"])
        self.assertIn("warning", {f["severity"] for f in summary["finding_list"]})
        self.assertEqual(summary["findings"]["warning"], sum(f["severity"] == "warning" for f in report["findings"]))

    def test_json_carries_the_findings_of_a_failed_run(self):
        doc = copy.deepcopy(TXT2IMG)
        doc["sampler"]["inputs"]["positive"] = ["nowhere", 0]
        code, out, _ = run("compile", self.graph(doc), "-o", self.out, "--json")
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        summary = json.loads(out)
        self.assertEqual([f["code"] for f in summary["finding_list"]], ["E6"])
        self.assertIn("hint", summary["finding_list"][0])



class MetaKeyTest(Folder):
    """``_meta``: an unknown ``ui_*`` key fails, a known key without its prefix warns, other
    tools' keys pass."""

    def test_an_unknown_ui_key_is_an_error_with_a_suggestion(self):
        code, _, err = run("compile", self.graph(with_meta(TXT2IMG, "decode", ui_optinal=True)), "-o", self.out)
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        self.assertIn("E7: node 'decode': _meta key 'ui_optinal' is not a cwc key", err)
        self.assertIn("did you mean 'ui_optional'", err)
        self.assertFalse((self.out / "graph.ui.json").exists())

    def test_a_known_key_without_its_prefix_warns_with_the_right_name(self):
        for key, right in (("optional", "ui_optional"), ("group", "ui_group"), ("role", "ui_role")):
            with self.subTest(key=key):
                value = {"optional": True, "group": "extras", "role": "cockpit"}[key]
                code, _, err = run("compile", self.graph(with_meta(TXT2IMG, "decode", **{key: value})), "-o", self.out)
                self.assertEqual(code, ExitCode.OK)
                self.assertIn(f"E7 warning: node 'decode': _meta key {key!r} is ignored; did you mean {right!r}?", err)

    def test_another_tools_key_does_not_fail_the_compile(self):
        code, _, err = run("compile", self.graph(with_meta(TXT2IMG, "decode", some_tool_state={"x": 1})), "-o", self.out)
        self.assertEqual(code, ExitCode.OK)
        self.assertNotIn("E7: ", err)



class InputTypoTest(Folder):
    def misspelt(self, wrong, right):
        doc = copy.deepcopy(TXT2IMG)
        inputs = doc["sampler"]["inputs"]
        inputs[wrong] = inputs.pop(right)
        code, _, err = run("compile", self.graph(doc), "-o", self.out)
        report = json.loads((self.out / "graph.report.json").read_text(encoding="utf-8"))
        return code, err, [f for f in report["findings"] if f["severity"] == "error"]

    def test_a_misspelt_widget_input_is_one_error_with_a_suggestion(self):
        code, err, errors = self.misspelt("sampler_nme", "sampler_name")
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        self.assertEqual([f["code"] for f in errors], ["E2"])
        self.assertIn("E2: node 'sampler': KSampler has no input 'sampler_nme'; did you mean 'sampler_name'?", err)
        self.assertNotIn("E3", err)

    def test_a_misspelt_link_input_is_one_error_with_a_suggestion(self):
        code, err, errors = self.misspelt("postive", "positive")
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        self.assertEqual([f["code"] for f in errors], ["E2"])
        self.assertIn("did you mean 'positive'?", err)

    def test_a_name_close_to_nothing_gets_no_suggestion(self):
        doc = copy.deepcopy(TXT2IMG)
        doc["sampler"]["inputs"]["zzzz"] = 1
        code, _, err = run("compile", self.graph(doc), "-o", self.out)
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        self.assertIn("E2: node 'sampler': KSampler has no input 'zzzz'\n", err)



def fancy(doc):
    """txt2img with its sampler replaced by a type cwc has no definition for."""
    doc = copy.deepcopy(doc)
    doc["sampler"]["class_type"] = "MyFancySampler"
    return doc


FANCY_INFO = {
    "MyFancySampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
                "steps": ["INT", {"default": 20, "min": 1, "max": 100}],
                "cfg": ["FLOAT", {"default": 7.0, "min": 0.0, "max": 30.0}],
                "sampler_name": [["euler", "dpmpp_2m"]],
                "scheduler": [["normal", "karras"]],
            }
        },
        "input_order": {"required": ["model", "positive", "negative", "latent_image", "steps", "cfg", "sampler_name", "scheduler"]},
        "output": ["LATENT"],
        "output_is_list": [False],
        "output_name": ["LATENT"],
        "name": "MyFancySampler",
        "display_name": "My fancy sampler",
        "category": "sampling",
        "output_node": False,
    }
}


class UnknownTypeHintTest(Folder):
    def test_the_hint_names_the_two_ways_through(self):
        code, _, err = run("compile", self.graph(fancy(TXT2IMG)), "-o", self.out)
        self.assertEqual(code, ExitCode.INPUT_ERROR)
        lines = err.splitlines()
        hint = lines[lines.index("E1: node 'sampler': unknown type 'MyFancySampler'") + 1]
        self.assertTrue(hint.startswith("  hint: "), hint)
        self.assertIn("--allow-unknown", hint)
        self.assertIn("--nodedefs", hint)
        self.assertIn("/api/object_info", hint)
        self.assertNotIn("cwc snapshot", err)

    def test_no_hint_names_a_command_cwc_does_not_have(self):
        doc = fancy(TXT2IMG)
        doc["sampler"]["_meta"]["ui_optional"] = True
        for argv in ((), ("--allow-unknown",)):
            with self.subTest(argv=argv):
                _, _, err = run("compile", self.graph(doc), "-o", self.out, *argv)
                self.assertIn("hint: ", err)
                self.assertNotIn("cwc snapshot", err)

    def test_the_nodedefs_the_hint_describes_make_the_type_known(self):
        info = self.dir / "object_info.json"
        info.write_text(json.dumps(FANCY_INFO), encoding="utf-8")
        code, _, err = run("compile", self.graph(fancy(TXT2IMG)), "-o", self.out, "--nodedefs", info)
        self.assertNotIn("E1", err)
        self.assertEqual(code, ExitCode.OK, err)


if __name__ == "__main__":
    unittest.main()
