from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skill_eval_replay import SkillEvalReplayInspector
from origin_forge.skill_eval_store import SkillEvalStore, SkillEvalStoreError
from origin_forge.skill_evaluation import (
    SkillBenchmarkRunner,
    SkillEvalCase,
    SkillEvalTrialRequest,
    SkillEvalTrialResult,
)
from origin_forge.skills import SkillRegistry


class SkillEvalReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skill-eval-replay-test")
        self.store = SkillEvalStore(self.runtime)
        self.case = SkillEvalCase(
            case_id="parser",
            objective="Repair parser failure",
            acceptance_criteria=("tests pass",),
        )
        self.store.put_case(self.case)
        self._write_skill("Inspect evidence first.")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_skill(self, instruction: str) -> None:
        directory = self.runtime.state_dir / "skills" / "python-debug"
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("SKILL.md").write_text(
            "---\nname: python-debug\ndescription: Debug Python failures\n---\n\n"
            + instruction
            + "\n",
            encoding="utf-8",
        )
        directory.joinpath("skill.toml").write_text(
            'version = "1.0.0"\nkeywords = ["debug"]\ncapabilities = ["debug"]\n',
            encoding="utf-8",
        )

    def _stored_report(self):
        skill = SkillRegistry(self.runtime).load("python-debug")

        def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
            return SkillEvalTrialResult(
                True,
                0.8 if request.variant.skill_refs else 0.5,
                10,
                1,
            )

        report = SkillBenchmarkRunner(trial, repetitions=1).run(
            [self.case], candidate_skills=[skill]
        )
        return self.store.save_report(report)

    def test_current_cases_and_skill_snapshot_are_replayable(self) -> None:
        stored = self._stored_report()
        status = SkillEvalReplayInspector(self.runtime).inspect(stored.report_id)
        self.assertTrue(status.replayable)
        self.assertEqual(status.stale_case_ids, ())
        self.assertEqual(status.stale_skill_refs, ())
        self.assertEqual(status.content_hash, stored.content_hash)
        self.assertEqual(status.suite_hash, stored.suite_hash)

    def test_changed_live_skill_makes_old_report_non_replayable_not_invalid(self) -> None:
        stored = self._stored_report()
        old_ref = SkillRegistry(self.runtime).load("python-debug").ref
        self._write_skill("Use a completely different debugging procedure.")

        status = SkillEvalReplayInspector(self.runtime).inspect(stored.report_id)
        self.assertFalse(status.replayable)
        self.assertEqual(status.stale_case_ids, ())
        self.assertEqual(status.stale_skill_refs, (old_ref,))

    def test_missing_case_makes_report_non_replayable(self) -> None:
        stored = self._stored_report()
        self.store.cases_dir.joinpath("parser.json").unlink()
        status = SkillEvalReplayInspector(self.runtime).inspect(stored.report_id)
        self.assertFalse(status.replayable)
        self.assertEqual(status.stale_case_ids, ("parser",))

    def test_report_content_tampering_is_detected_before_replayability(self) -> None:
        stored = self._stored_report()
        raw = json.loads(stored.path.read_text(encoding="utf-8"))
        raw["report"]["overall_verdict"] = "REGRESSED"
        stored.path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(SkillEvalStoreError, "content/ID mismatch"):
            SkillEvalReplayInspector(self.runtime).inspect(stored.report_id)

    def test_suite_hash_tampering_is_detected_even_with_rehashed_filename(self) -> None:
        stored = self._stored_report()
        raw = json.loads(stored.path.read_text(encoding="utf-8"))
        raw["suite_hash"] = "sha256:" + "0" * 64
        canonical = (
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        import hashlib

        content_hash = hashlib.sha256(canonical).hexdigest()
        new_id = f"SKILL-EVAL-{content_hash[:20]}"
        new_path = self.store.reports_dir / f"{new_id}.json"
        new_path.write_bytes(canonical)
        with self.assertRaisesRegex(SkillEvalStoreError, "suite hash mismatch"):
            SkillEvalReplayInspector(self.runtime).inspect(new_id)


if __name__ == "__main__":
    unittest.main()
