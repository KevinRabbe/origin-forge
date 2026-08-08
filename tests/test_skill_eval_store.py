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
            fixture_ref=f"git-fixture:{case_id}",
            scorer_ref="scorer:sandbox-v1",
            objective="Repair parser failure",
            acceptance_criteria=("tests pass",),
            context_paths=("src/parser.py",),
        )

    def _report(self, case: SkillEvalCase | None = None):
        case = case or self._case()
        skill = SkillRegistry(self.runtime).load("python-debug")

        def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
            return SkillEvalTrialResult(
                True,
                0.9 if request.variant.skill_refs else 0.5,
                10,
                1,
                request.case.fixture_ref,
                "env:model-a+harness-v1",
                request.case.scorer_ref,
                input_tokens=20 if request.variant.skill_refs else 10,
                output_tokens=5,
            )

        return SkillBenchmarkRunner(trial, repetitions=2).run(
            [case], candidate_skills=[skill]
        )

    def test_case_put_is_idempotent_but_case_id_is_immutable(self) -> None:
        case = self._case()
        first = self.store.put_case(case)
        second = self.store.put_case(case)
        self.assertEqual(first, second)
        self.assertEqual(self.store.load_case("parser"), case)

        changed = SkillEvalCase(
            case_id="parser",
            fixture_ref="git-fixture:changed",
            scorer_ref=case.scorer_ref,
            objective=case.objective,
        )
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

    def test_report_requires_durable_current_cases_and_skill_snapshot(self) -> None:
        case = self._case()
        report = self._report(case)
        with self.assertRaisesRegex(SkillEvalStoreError, "not durably stored"):
            self.store.save_report(report)

        self.store.put_case(case)
        skill_file = self.runtime.state_dir / "skills" / "python-debug" / "SKILL.md"
        original = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(original + "Changed after evaluation.\n", encoding="utf-8")
        with self.assertRaisesRegex(SkillEvalStoreError, "Skill changed before report save"):
            self.store.save_report(report)

    def test_report_is_content_addressed_and_preserves_raw_pairing(self) -> None:
        case = self._case()
        self.store.put_case(case)
        report = self._report(case)
        first = self.store.save_report(report)
        second = self.store.save_report(report)
        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.suite_hash, second.suite_hash)

        loaded = self.store.load_report(first.report_id)
        payload = loaded.envelope["report"]
        self.assertEqual(payload["protocol_id"], "paired-skill-ab-v1")
        self.assertEqual(payload["environment_fingerprint"], "env:model-a+harness-v1")
        self.assertEqual(len(payload["comparisons"][0]["paired_seeds"]), 2)
        self.assertEqual(len(payload["comparisons"][0]["baseline_trials"]), 2)
        self.assertEqual(len(payload["comparisons"][0]["candidate_trials"]), 2)

    def test_report_content_tampering_breaks_content_addressed_id(self) -> None:
        case = self._case()
        self.store.put_case(case)
        stored = self.store.save_report(self._report(case))
        raw = json.loads(stored.path.read_text(encoding="utf-8"))
        raw["report"]["overall_verdict"] = "REGRESSED"
        stored.path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(SkillEvalStoreError, "content/ID mismatch"):
            self.store.load_report(stored.report_id)

    def test_case_and_report_byte_limits_fail_before_persistence(self) -> None:
        tiny_case_store = SkillEvalStore(self.runtime, max_case_bytes=64)
        with self.assertRaisesRegex(SkillEvalStoreError, "byte limit"):
            tiny_case_store.put_case(self._case("tiny-case"))

        case = self._case()
        self.store.put_case(case)
        tiny_report_store = SkillEvalStore(self.runtime, max_report_bytes=128)
        with self.assertRaisesRegex(SkillEvalStoreError, "byte limit"):
            tiny_report_store.save_report(self._report(case))

    def test_report_catalog_is_bounded(self) -> None:
        store = SkillEvalStore(self.runtime, max_reports=1)
        store.ensure()
        for name in (
            "SKILL-EVAL-00000000000000000000.json",
            "SKILL-EVAL-11111111111111111111.json",
        ):
            store.reports_dir.joinpath(name).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(SkillEvalStoreError, "catalog exceeds limit"):
            store.list_report_ids()


if __name__ == "__main__":
    unittest.main()
