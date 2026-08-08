from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skill_evaluation import (
    SkillBenchmarkRunner,
    SkillComparisonVerdict,
    SkillEvalCase,
    SkillEvalTrialRequest,
    SkillEvalTrialResult,
    SkillEvaluationError,
    benchmark_selected_skills,
)
from origin_forge.skills import SkillRegistry


class RecordingTrial:
    def __init__(self, *, candidate_score: float = 0.8, baseline_score: float = 0.5):
        self.candidate_score = candidate_score
        self.baseline_score = baseline_score
        self.requests: list[SkillEvalTrialRequest] = []

    def __call__(self, request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
        self.requests.append(request)
        candidate = bool(request.variant.skill_refs)
        return SkillEvalTrialResult(
            success=True,
            score=self.candidate_score if candidate else self.baseline_score,
            duration_ms=120 if candidate else 100,
            model_calls=1,
            input_tokens=80 if candidate else 40,
            output_tokens=20,
            metadata=(("seed", str(request.seed)),),
        )


class SkillEvaluationTests(unittest.TestCase):
    def _case(self, case_id: str = "parser-fix") -> SkillEvalCase:
        return SkillEvalCase(
            case_id=case_id,
            objective="Repair WidgetParser failure",
            acceptance_criteria=("parser tests pass",),
            constraints=("do not change public API",),
            required_capabilities=("debug",),
            context_paths=("src/parser.py", "tests/test_parser.py"),
            tags=("python", "bugfix"),
        )

    def _skill_runtime(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize("skill-eval-test")
        directory = runtime.state_dir / "skills" / "python-debug"
        directory.mkdir(parents=True)
        directory.joinpath("SKILL.md").write_text(
            "---\n"
            "name: python-debug\n"
            "description: Debug Python failures systematically\n"
            "---\n\n"
            "Inspect the failing test before editing implementation code.\n",
            encoding="utf-8",
        )
        directory.joinpath("skill.toml").write_text(
            'version = "1.0.0"\n'
            'keywords = ["python", "debug"]\n'
            'capabilities = ["debug"]\n',
            encoding="utf-8",
        )
        return temp, runtime

    def test_case_hash_is_content_addressed_and_deterministic(self) -> None:
        first = self._case()
        second = self._case()
        changed = SkillEvalCase(
            case_id="parser-fix",
            objective="Repair a different parser failure",
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, changed.content_hash)
        self.assertTrue(first.content_hash.startswith("sha256:"))

    def test_baseline_and_candidate_use_identical_paired_seeds(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            registry = SkillRegistry(runtime)
            skill = registry.load("python-debug")
            trial = RecordingTrial()
            report = SkillBenchmarkRunner(
                trial,
                repetitions=3,
                seed_base=500,
            ).run([self._case()], candidate_skills=[skill])

            self.assertEqual(len(trial.requests), 6)
            baseline = trial.requests[0::2]
            candidate = trial.requests[1::2]
            self.assertEqual([item.seed for item in baseline], [500, 501, 502])
            self.assertEqual(
                [item.seed for item in baseline],
                [item.seed for item in candidate],
            )
            self.assertTrue(all(not item.variant.skill_refs for item in baseline))
            self.assertTrue(all(item.variant.skill_refs for item in candidate))
            self.assertEqual(report.overall_verdict, SkillComparisonVerdict.IMPROVED)
        finally:
            temp.cleanup()

    def test_report_aggregates_quality_cost_and_exact_skill_ref(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            registry = SkillRegistry(runtime)
            skill = registry.load("python-debug")
            report = SkillBenchmarkRunner(RecordingTrial(), repetitions=2).run(
                [self._case()],
                candidate_skills=[skill],
            )
            comparison = report.comparisons[0]
            self.assertEqual(report.skill_refs, (skill.ref,))
            self.assertEqual(comparison.baseline.trials, 2)
            self.assertEqual(comparison.candidate.trials, 2)
            self.assertEqual(comparison.baseline.mean_score, 0.5)
            self.assertEqual(comparison.candidate.mean_score, 0.8)
            self.assertEqual(comparison.candidate.mean_duration_ms, 120.0)
            self.assertEqual(comparison.candidate.mean_input_tokens, 80.0)
            self.assertEqual(comparison.candidate.mean_output_tokens, 20.0)
            payload = report.to_dict()
            self.assertEqual(payload["skill_refs"], [skill.ref])
            self.assertEqual(payload["comparisons"][0]["case_hash"], self._case().content_hash)
        finally:
            temp.cleanup()

    def test_any_case_regression_makes_overall_report_regressed(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")

            def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                candidate = bool(request.variant.skill_refs)
                if request.case.case_id == "good":
                    score = 0.9 if candidate else 0.5
                else:
                    score = 0.2 if candidate else 0.7
                return SkillEvalTrialResult(True, score, 10, 1)

            report = SkillBenchmarkRunner(trial, repetitions=1).run(
                [self._case("good"), self._case("bad")],
                candidate_skills=[skill],
            )
            self.assertEqual(
                [item.verdict for item in report.comparisons],
                [SkillComparisonVerdict.IMPROVED, SkillComparisonVerdict.REGRESSED],
            )
            self.assertEqual(report.overall_verdict, SkillComparisonVerdict.REGRESSED)
            self.assertEqual(report.improved_cases, 1)
            self.assertEqual(report.regressed_cases, 1)
        finally:
            temp.cleanup()

    def test_success_rate_difference_outranks_small_score_difference(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")

            def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                candidate = bool(request.variant.skill_refs)
                if candidate:
                    return SkillEvalTrialResult(True, 0.51, 10, 1)
                return SkillEvalTrialResult(False, 0.50, 10, 1, failure_reason="failed")

            report = SkillBenchmarkRunner(trial, repetitions=2).run(
                [self._case()], candidate_skills=[skill]
            )
            comparison = report.comparisons[0]
            self.assertEqual(comparison.success_rate_delta, 1.0)
            self.assertEqual(comparison.verdict, SkillComparisonVerdict.IMPROVED)
        finally:
            temp.cleanup()

    def test_small_score_delta_is_inconclusive_and_equal_is_equivalent(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            inconclusive = SkillBenchmarkRunner(
                RecordingTrial(candidate_score=0.53, baseline_score=0.50),
                repetitions=1,
            ).run([self._case()], candidate_skills=[skill])
            self.assertEqual(
                inconclusive.overall_verdict,
                SkillComparisonVerdict.INCONCLUSIVE,
            )

            equivalent = SkillBenchmarkRunner(
                RecordingTrial(candidate_score=0.505, baseline_score=0.50),
                repetitions=1,
            ).run([self._case()], candidate_skills=[skill])
            self.assertEqual(
                equivalent.overall_verdict,
                SkillComparisonVerdict.EQUIVALENT,
            )
        finally:
            temp.cleanup()

    def test_case_and_trial_validation_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            SkillEvalCase(case_id="bad id", objective="x")
        with self.assertRaises(ValueError):
            SkillEvalCase(case_id="ok", objective="")
        with self.assertRaises(ValueError):
            SkillEvalTrialResult(True, 1.1, 1, 1)
        with self.assertRaises(ValueError):
            SkillEvalTrialResult(True, 0.5, -1, 1)

    def test_case_count_and_candidate_bounds_fail_before_trials(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            trial = RecordingTrial()
            with self.assertRaisesRegex(SkillEvaluationError, "case count exceeds"):
                SkillBenchmarkRunner(trial, max_cases=1).run(
                    [self._case("a"), self._case("b")],
                    candidate_skills=[skill],
                )
            self.assertEqual(trial.requests, [])
            with self.assertRaisesRegex(SkillEvaluationError, "may not be empty"):
                SkillBenchmarkRunner(trial).run([self._case()], candidate_skills=[])
        finally:
            temp.cleanup()

    def test_benchmark_selected_skills_loads_exact_governed_snapshot_without_mutation(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            registry = SkillRegistry(runtime)
            skill_path = runtime.state_dir / "skills" / "python-debug" / "SKILL.md"
            before = skill_path.read_bytes()
            report = benchmark_selected_skills(
                registry,
                [self._case()],
                RecordingTrial(),
                skill_names=["python-debug"],
                repetitions=1,
                seed_base=10,
            )
            after = skill_path.read_bytes()
            self.assertEqual(before, after)
            self.assertEqual(report.skill_refs, (registry.load("python-debug").ref,))
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
