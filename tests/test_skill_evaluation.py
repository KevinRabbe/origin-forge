from __future__ import annotations

import tempfile
import unittest
from collections import defaultdict
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
    def __init__(
        self,
        *,
        candidate_score: float = 0.8,
        baseline_score: float = 0.5,
        environment: str = "env:model-a+harness-v1",
    ):
        self.candidate_score = candidate_score
        self.baseline_score = baseline_score
        self.environment = environment
        self.requests: list[SkillEvalTrialRequest] = []

    def __call__(self, request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
        self.requests.append(request)
        candidate = bool(request.variant.skill_refs)
        return SkillEvalTrialResult(
            success=True,
            score=self.candidate_score if candidate else self.baseline_score,
            duration_ms=120 if candidate else 100,
            model_calls=1,
            fixture_fingerprint=request.case.fixture_ref,
            environment_fingerprint=self.environment,
            scorer_fingerprint=request.case.scorer_ref,
            input_tokens=80 if candidate else 40,
            output_tokens=20,
            metadata=(("seed_applied", "true"),),
        )


class SkillEvaluationTests(unittest.TestCase):
    def _case(self, case_id: str = "parser-fix") -> SkillEvalCase:
        return SkillEvalCase(
            case_id=case_id,
            fixture_ref=f"git-fixture:{case_id}:abc123",
            scorer_ref="scorer:sandbox-tests-v1",
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

    def test_case_hash_pins_fixture_scorer_and_task_meaning(self) -> None:
        first = self._case()
        second = self._case()
        changed_fixture = SkillEvalCase(
            case_id="parser-fix",
            fixture_ref="git-fixture:different",
            scorer_ref=first.scorer_ref,
            objective=first.objective,
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, changed_fixture.content_hash)
        self.assertTrue(first.content_hash.startswith("sha256:"))

    def test_trials_are_paired_with_stable_seeds_and_alternating_order(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            trial = RecordingTrial()
            report = SkillBenchmarkRunner(trial, repetitions=4, seed_base=500).run(
                [self._case()], candidate_skills=[skill]
            )

            pairs: dict[int, list[SkillEvalTrialRequest]] = defaultdict(list)
            for request in trial.requests:
                pairs[request.repetition].append(request)
            self.assertEqual(set(pairs), {0, 1, 2, 3})
            for repetition, requests in pairs.items():
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[0].seed, requests[1].seed)
                self.assertEqual({bool(item.variant.skill_refs) for item in requests}, {False, True})
                self.assertEqual({item.repetition for item in requests}, {repetition})

            comparison = report.comparisons[0]
            self.assertEqual(
                comparison.execution_orders,
                (
                    ("baseline", "candidate"),
                    ("candidate", "baseline"),
                    ("baseline", "candidate"),
                    ("candidate", "baseline"),
                ),
            )
            self.assertEqual(len(comparison.paired_seeds), 4)
            self.assertEqual(report.environment_fingerprint, "env:model-a+harness-v1")
            self.assertEqual(report.overall_verdict, SkillComparisonVerdict.IMPROVED)
        finally:
            temp.cleanup()

    def test_case_seed_does_not_depend_on_suite_order(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            first_trial = RecordingTrial()
            second_trial = RecordingTrial()
            cases = [self._case("alpha"), self._case("beta")]
            SkillBenchmarkRunner(first_trial, repetitions=1, seed_base=10).run(
                cases, candidate_skills=[skill]
            )
            SkillBenchmarkRunner(second_trial, repetitions=1, seed_base=10).run(
                list(reversed(cases)), candidate_skills=[skill]
            )

            def seeds_by_case(requests):
                result = {}
                for request in requests:
                    result.setdefault(request.case.case_id, request.seed)
                return result

            self.assertEqual(seeds_by_case(first_trial.requests), seeds_by_case(second_trial.requests))
        finally:
            temp.cleanup()

    def test_environment_fixture_and_scorer_mismatches_fail_benchmark(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            case = self._case()

            def mismatch_environment(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                candidate = bool(request.variant.skill_refs)
                return SkillEvalTrialResult(
                    True,
                    0.5,
                    10,
                    1,
                    request.case.fixture_ref,
                    "env:candidate" if candidate else "env:baseline",
                    request.case.scorer_ref,
                )

            with self.assertRaisesRegex(SkillEvaluationError, "environment mismatch"):
                SkillBenchmarkRunner(mismatch_environment, repetitions=1).run(
                    [case], candidate_skills=[skill]
                )

            def bad_fixture(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                return SkillEvalTrialResult(
                    True,
                    0.5,
                    10,
                    1,
                    "wrong-fixture",
                    "env:same",
                    request.case.scorer_ref,
                )

            with self.assertRaisesRegex(SkillEvaluationError, "fixture fingerprint"):
                SkillBenchmarkRunner(bad_fixture, repetitions=1).run(
                    [case], candidate_skills=[skill]
                )
        finally:
            temp.cleanup()

    def test_environment_cannot_change_between_cases(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")

            def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                return SkillEvalTrialResult(
                    True,
                    0.5,
                    10,
                    1,
                    request.case.fixture_ref,
                    f"env:{request.case.case_id}",
                    request.case.scorer_ref,
                )

            with self.assertRaisesRegex(SkillEvaluationError, "environment changed"):
                SkillBenchmarkRunner(trial, repetitions=1).run(
                    [self._case("a"), self._case("b")],
                    candidate_skills=[skill],
                )
        finally:
            temp.cleanup()

    def test_report_keeps_raw_trials_costs_protocol_and_skill_ref(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            report = SkillBenchmarkRunner(RecordingTrial(), repetitions=2).run(
                [self._case()], candidate_skills=[skill]
            )
            comparison = report.comparisons[0]
            self.assertEqual(report.protocol_id, "paired-skill-ab-v1")
            self.assertEqual(report.skill_refs, (skill.ref,))
            self.assertEqual(comparison.baseline.trials, 2)
            self.assertEqual(comparison.candidate.trials, 2)
            self.assertEqual(len(comparison.baseline_trials), 2)
            self.assertEqual(comparison.candidate.mean_duration_ms, 120.0)
            self.assertEqual(comparison.candidate.mean_input_tokens, 80.0)
            payload = report.to_dict()
            self.assertEqual(payload["skill_refs"], [skill.ref])
            self.assertEqual(len(payload["comparisons"][0]["candidate_trials"]), 2)
        finally:
            temp.cleanup()

    def test_regression_dominates_over_improvement(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")

            def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                candidate = bool(request.variant.skill_refs)
                score = (
                    0.9 if candidate else 0.5
                ) if request.case.case_id == "good" else (
                    0.2 if candidate else 0.7
                )
                return SkillEvalTrialResult(
                    True,
                    score,
                    10,
                    1,
                    request.case.fixture_ref,
                    "env:same",
                    request.case.scorer_ref,
                )

            report = SkillBenchmarkRunner(trial, repetitions=1).run(
                [self._case("good"), self._case("bad")],
                candidate_skills=[skill],
            )
            self.assertEqual(
                [item.verdict for item in report.comparisons],
                [SkillComparisonVerdict.IMPROVED, SkillComparisonVerdict.REGRESSED],
            )
            self.assertEqual(report.overall_verdict, SkillComparisonVerdict.REGRESSED)
        finally:
            temp.cleanup()

    def test_success_rate_precedes_small_score_delta(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")

            def trial(request: SkillEvalTrialRequest) -> SkillEvalTrialResult:
                candidate = bool(request.variant.skill_refs)
                return SkillEvalTrialResult(
                    candidate,
                    0.51 if candidate else 0.50,
                    10,
                    1,
                    request.case.fixture_ref,
                    "env:same",
                    request.case.scorer_ref,
                    failure_reason=None if candidate else "failed",
                )

            report = SkillBenchmarkRunner(trial, repetitions=2).run(
                [self._case()], candidate_skills=[skill]
            )
            self.assertEqual(report.comparisons[0].verdict, SkillComparisonVerdict.IMPROVED)
        finally:
            temp.cleanup()

    def test_experiment_and_trial_output_bounds_fail_closed(self) -> None:
        temp, runtime = self._skill_runtime()
        try:
            skill = SkillRegistry(runtime).load("python-debug")
            with self.assertRaisesRegex(ValueError, "repetitions exceed limit"):
                SkillBenchmarkRunner(RecordingTrial(), repetitions=21, max_repetitions=20)
            with self.assertRaises(ValueError):
                SkillEvalTrialResult(
                    True,
                    0.5,
                    1,
                    1,
                    "fixture",
                    "environment",
                    "scorer",
                    metadata=(("duplicate", "a"), ("duplicate", "b")),
                )
            with self.assertRaises(ValueError):
                SkillEvalCase(
                    case_id="case",
                    fixture_ref="fixture",
                    scorer_ref="scorer",
                    objective="x" * (16 * 1024 + 1),
                )
            with self.assertRaisesRegex(SkillEvaluationError, "may not be empty"):
                SkillBenchmarkRunner(RecordingTrial()).run(
                    [self._case()], candidate_skills=[]
                )
            self.assertIsNotNone(skill)
        finally:
            temp.cleanup()

    def test_benchmark_selected_skills_never_mutates_registry(self) -> None:
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
            )
            self.assertEqual(before, skill_path.read_bytes())
            self.assertEqual(report.skill_refs, (registry.load("python-debug").ref,))
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
