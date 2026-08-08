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

    def test_cli_has_no_skill_promotion_or_mutation_command(self) -> None:
        text = build_parser().format_help().casefold()
        for forbidden in ("promote", "install", "rewrite", "apply-skill", "self-modify"):
            self.assertNotIn(forbidden, text)

    def test_case_add_list_show_requires_fixture_and_scorer_identity(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "case-add",
                    "parser",
                    "--fixture-ref",
                    "git-fixture:parser-v1",
                    "--scorer-ref",
                    "scorer:sandbox-v1",
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
        self.assertTrue(created["path"].startswith(".origin-forge/skill-evals/cases/"))

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main(["--project-root", str(self.root), "case-list"]),
                0,
            )
        self.assertEqual(json.loads(output.getvalue()), {"cases": ["parser"]})

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main(["--project-root", str(self.root), "case-show", "parser"]),
                0,
            )
        shown = json.loads(output.getvalue())
        self.assertEqual(shown["case"]["fixture_ref"], "git-fixture:parser-v1")
        self.assertEqual(shown["case"]["scorer_ref"], "scorer:sandbox-v1")

    def test_changed_case_meaning_under_same_id_is_refused(self) -> None:
        SkillEvalStore(self.runtime).put_case(
            SkillEvalCase(
                case_id="parser",
                fixture_ref="fixture:v1",
                scorer_ref="scorer:v1",
                objective="Original benchmark",
            )
        )
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "case-add",
                    "parser",
                    "--fixture-ref",
                    "fixture:v2",
                    "--scorer-ref",
                    "scorer:v1",
                    "--objective",
                    "Original benchmark",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("immutable", json.loads(output.getvalue())["detail"])

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
