from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skill_eval_cli import build_parser, main
from origin_forge.skill_eval_store import SkillEvalStore
from origin_forge.skill_evaluation import SkillEvalCase


class SkillEvalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skill-eval-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_cli_has_no_promotion_or_skill_mutation_command(self) -> None:
        help_text = build_parser().format_help().casefold()
        self.assertNotIn("promote", help_text)
        self.assertNotIn("install", help_text)
        self.assertNotIn("rewrite", help_text)
        self.assertNotIn("skill-edit", help_text)

    def test_case_add_list_and_show(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "case-add",
                    "parser",
                    "--objective",
                    "Repair parser failure",
                    "--acceptance",
                    "tests pass",
                    "--context",
                    "src/parser.py",
                    "--tag",
                    "python",
                ]
            )
        self.assertEqual(code, 0)
        created = json.loads(output.getvalue())
        self.assertEqual(created["case_id"], "parser")
        self.assertTrue(created["case_hash"].startswith("sha256:"))

        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), "case-list"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"cases": ["parser"]})

        output = StringIO()
        with redirect_stdout(output):
            code = main(
                ["--project-root", str(self.root), "case-show", "parser"]
            )
        self.assertEqual(code, 0)
        shown = json.loads(output.getvalue())
        self.assertEqual(shown["case"]["objective"], "Repair parser failure")
        self.assertEqual(shown["case"]["context_paths"], ["src/parser.py"])

    def test_case_add_refuses_changed_meaning_under_same_id(self) -> None:
        SkillEvalStore(self.runtime).put_case(
            SkillEvalCase(case_id="parser", objective="Original benchmark")
        )
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "case-add",
                    "parser",
                    "--objective",
                    "Changed benchmark",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertIn("immutable", payload["detail"])

    def test_unknown_report_is_safe_not_found(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "report-show",
                    "SKILL-EVAL-00000000000000000000",
                ]
            )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.getvalue())["error"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
