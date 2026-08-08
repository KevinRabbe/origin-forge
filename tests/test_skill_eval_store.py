from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skill_eval_store import SkillEvalStore, SkillEvalStoreError
from origin_forge.skill_evaluation import (
    SkillBenchmarkRunner,
    SkillEvalCase,
    SkillEvalTrialRequest,
    SkillEvalTrialResult,
)
from origin_forge.skills import SkillRegistry


class SkillEvalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skill-eval-store-test")
        self.store = SkillEvalStore(self.runtime)

        skill_dir = self.runtime.state_dir / "skills" / "python-debug"
        skill_dir.mkdir(parents=True)
        skill_dir.joinpath("SKILL.md").write_text(
            "---\nname: python-debug\ndescription: Debug Python failures\n---\n\nInspect evidence first.\n",
            encoding="utf-8",
        )
        skill_dir.joinpath("skill.toml").write_text(
            'version = "1.0.0"\nkeywords = ["debug"]\ncapabilities = ["debug"]\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _case(self, case_id: str = "parser") -> SkillEvalCase:
        return SkillEvalCase(
            case_id=case_id,
            objective="Repair parser failure",
            acceptance_criteria=("tests pass",),
            context_paths=("src/parser.py",),
        )

    def _report(self):
        skill = SkillRegistry(self.runtime).load("python-debug")

        def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
            candidate = bool(request.variant.skill_refs)
            return SkillEvalTrialResult(
                True,
                0.9 if candidate else 0.5,
                10,
                1,
                input_tokens=20 if candidate else 10,
                output_tokens=5,
            )

        return SkillBenchmarkRunner(trial, repetitions=2).run(
            [self._case()], candidate_skills=[skill]
        )

    def test_case_put_is_idempotent_but_case_id_is_immutable(self) -> None:
        case = self._case()
        first = self.store.put_case(case)
        second = self.store.put_case(case)
        self.assertEqual(first, second)
        self.assertEqual(self.store.load_case("parser"), case)

        changed = SkillEvalCase(case_id="parser", objective="Changed benchmark meaning")
        with self.assertRaisesRegex(SkillEvalStoreError, "immutable"):
            self.store.put_case(changed)

    def test_case_catalog_is_sorted_bounded_and_symlink_safe(self) -> None:
        self.store.put_case(self._case("zeta"))
        self.store.put_case(self._case("alpha"))
        self.assertEqual(self.store.list_case_ids(), ("alpha", "zeta"))

        bad = self.store.cases_dir / "bad-link.json"
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        try:
            bad.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(SkillEvalStoreError, "unsupported entry"):
            self.store.list_case_ids()

    def test_case_hash_tampering_is_detected(self) -> None:
        path = self.store.put_case(self._case())
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["case"]["objective"] = "tampered"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(SkillEvalStoreError, "hash mismatch"):
            self.store.load_case("parser")

    def test_report_is_content_addressed_and_preserves_raw_trials(self) -> None:
        report = self._report()
        first = self.store.save_report(report)
        second = self.store.save_report(report)
        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.suite_hash, second.suite_hash)
        self.assertTrue(first.path.exists())

        envelope = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual(envelope["suite_hash"], first.suite_hash)
        self.assertEqual(
            len(envelope["report"]["comparisons"][0]["baseline_trials"]),
            2,
        )
        self.assertEqual(
            len(envelope["report"]["comparisons"][0]["candidate_trials"]),
            2,
        )

    def test_case_size_limit_fails_before_write(self) -> None:
        store = SkillEvalStore(self.runtime, max_case_bytes=64)
        with self.assertRaisesRegex(SkillEvalStoreError, "byte limit"):
            store.put_case(self._case())

    def test_report_size_limit_fails_before_write(self) -> None:
        store = SkillEvalStore(self.runtime, max_report_bytes=128)
        with self.assertRaisesRegex(SkillEvalStoreError, "byte limit"):
            store.save_report(self._report())


if __name__ == "__main__":
    unittest.main()
