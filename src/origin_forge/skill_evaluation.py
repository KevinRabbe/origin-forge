from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean
from typing import Callable, Iterable, Protocol, Sequence, runtime_checkable

from .skills import Skill, SkillRegistry


_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SkillEvaluationError(RuntimeError):
    pass


class SkillComparisonVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class SkillEvalCase:
    case_id: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _CASE_ID_RE.fullmatch(self.case_id):
            raise ValueError(f"invalid Skill eval case_id: {self.case_id!r}")
        if not self.objective.strip():
            raise ValueError("Skill eval objective may not be empty")
        for field_name in (
            "acceptance_criteria",
            "constraints",
            "required_capabilities",
            "context_paths",
            "tags",
        ):
            values = getattr(self, field_name)
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"Skill eval {field_name} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"Skill eval {field_name} contains duplicates")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "required_capabilities": list(self.required_capabilities),
            "context_paths": list(self.context_paths),
            "tags": list(self.tags),
        }

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class SkillEvalVariant:
    variant_id: str
    skill_refs: tuple[str, ...]
    instructions: str

    def __post_init__(self) -> None:
        if not _CASE_ID_RE.fullmatch(self.variant_id):
            raise ValueError(f"invalid Skill eval variant_id: {self.variant_id!r}")
        if len(set(self.skill_refs)) != len(self.skill_refs):
            raise ValueError("Skill eval variant contains duplicate Skill refs")


@dataclass(frozen=True)
class SkillEvalTrialRequest:
    case: SkillEvalCase
    variant: SkillEvalVariant
    repetition: int
    seed: int


@dataclass(frozen=True)
class SkillEvalTrialResult:
    success: bool
    score: float
    duration_ms: int
    model_calls: int
    input_tokens: int = 0
    output_tokens: int = 0
    failure_reason: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("Skill eval trial success must be boolean")
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise ValueError("Skill eval trial score must be numeric")
        if not math.isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("Skill eval trial score must be finite and between 0 and 1")
        for value, name in (
            (self.duration_ms, "duration_ms"),
            (self.model_calls, "model_calls"),
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Skill eval trial {name} must be a non-negative integer")
        if self.failure_reason is not None and not isinstance(self.failure_reason, str):
            raise ValueError("Skill eval failure_reason must be a string or null")
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            for key, value in self.metadata
        ):
            raise ValueError("Skill eval metadata must contain non-empty string pairs")


@runtime_checkable
class SkillEvalTrial(Protocol):
    def __call__(self, request: SkillEvalTrialRequest) -> SkillEvalTrialResult: ...


@dataclass(frozen=True)
class SkillVariantSummary:
    variant_id: str
    skill_refs: tuple[str, ...]
    trials: int
    success_rate: float
    mean_score: float
    mean_duration_ms: float
    mean_model_calls: float
    mean_input_tokens: float
    mean_output_tokens: float


@dataclass(frozen=True)
class SkillCaseComparison:
    case_id: str
    case_hash: str
    baseline: SkillVariantSummary
    candidate: SkillVariantSummary
    score_delta: float
    success_rate_delta: float
    verdict: SkillComparisonVerdict


@dataclass(frozen=True)
class SkillBenchmarkReport:
    skill_refs: tuple[str, ...]
    repetitions: int
    seed_base: int
    comparisons: tuple[SkillCaseComparison, ...]
    overall_verdict: SkillComparisonVerdict

    @property
    def improved_cases(self) -> int:
        return sum(item.verdict == SkillComparisonVerdict.IMPROVED for item in self.comparisons)

    @property
    def regressed_cases(self) -> int:
        return sum(item.verdict == SkillComparisonVerdict.REGRESSED for item in self.comparisons)

    def to_dict(self) -> dict[str, object]:
        def summary(value: SkillVariantSummary) -> dict[str, object]:
            return {
                "variant_id": value.variant_id,
                "skill_refs": list(value.skill_refs),
                "trials": value.trials,
                "success_rate": value.success_rate,
                "mean_score": value.mean_score,
                "mean_duration_ms": value.mean_duration_ms,
                "mean_model_calls": value.mean_model_calls,
                "mean_input_tokens": value.mean_input_tokens,
                "mean_output_tokens": value.mean_output_tokens,
            }

        return {
            "skill_refs": list(self.skill_refs),
            "repetitions": self.repetitions,
            "seed_base": self.seed_base,
            "overall_verdict": self.overall_verdict.value,
            "improved_cases": self.improved_cases,
            "regressed_cases": self.regressed_cases,
            "comparisons": [
                {
                    "case_id": item.case_id,
                    "case_hash": item.case_hash,
                    "baseline": summary(item.baseline),
                    "candidate": summary(item.candidate),
                    "score_delta": item.score_delta,
                    "success_rate_delta": item.success_rate_delta,
                    "verdict": item.verdict.value,
                }
                for item in self.comparisons
            ],
        }


class SkillBenchmarkRunner:
    """Run paired baseline/candidate Skill trials without promoting Skills.

    The runner owns experimental pairing and aggregation only. The injected
    trial callable owns model/tool execution and external scoring. Baseline and
    candidate receive the same deterministic seed for each case/repetition.
    """

    def __init__(
        self,
        trial: SkillEvalTrial | Callable[[SkillEvalTrialRequest], SkillEvalTrialResult],
        *,
        repetitions: int = 3,
        seed_base: int = 1103,
        min_score_delta: float = 0.05,
        equivalence_margin: float = 0.01,
        max_cases: int = 128,
    ):
        if repetitions <= 0:
            raise ValueError("Skill benchmark repetitions must be positive")
        if not isinstance(seed_base, int) or isinstance(seed_base, bool):
            raise ValueError("Skill benchmark seed_base must be an integer")
        if not 0.0 < min_score_delta <= 1.0:
            raise ValueError("min_score_delta must be between 0 and 1")
        if not 0.0 <= equivalence_margin < min_score_delta:
            raise ValueError("equivalence_margin must be non-negative and below min_score_delta")
        if max_cases <= 0:
            raise ValueError("max_cases must be positive")
        self.trial = trial
        self.repetitions = repetitions
        self.seed_base = seed_base
        self.min_score_delta = min_score_delta
        self.equivalence_margin = equivalence_margin
        self.max_cases = max_cases

    @staticmethod
    def _variant_from_skills(skills: Sequence[Skill]) -> SkillEvalVariant:
        refs = tuple(skill.ref for skill in skills)
        instructions = ""
        if skills:
            sections = [
                "The following Origin Forge Skills are trusted project instructions selected for this evaluation variant. "
                "They do not grant additional authority."
            ]
            for skill in skills:
                metadata = skill.metadata
                sections.append(
                    f"## Skill: {metadata.name}@{metadata.version}\n"
                    f"Fingerprint: {metadata.content_hash}\n\n"
                    f"{skill.instructions.strip()}"
                )
            instructions = "\n\n".join(sections).strip() + "\n"
        variant_id = "candidate" if refs else "baseline"
        return SkillEvalVariant(variant_id, refs, instructions)

    @staticmethod
    def _summary(
        variant: SkillEvalVariant,
        trials: Sequence[SkillEvalTrialResult],
    ) -> SkillVariantSummary:
        if not trials:
            raise SkillEvaluationError("cannot summarize empty Skill eval trial set")
        return SkillVariantSummary(
            variant_id=variant.variant_id,
            skill_refs=variant.skill_refs,
            trials=len(trials),
            success_rate=fmean(1.0 if result.success else 0.0 for result in trials),
            mean_score=fmean(float(result.score) for result in trials),
            mean_duration_ms=fmean(float(result.duration_ms) for result in trials),
            mean_model_calls=fmean(float(result.model_calls) for result in trials),
            mean_input_tokens=fmean(float(result.input_tokens) for result in trials),
            mean_output_tokens=fmean(float(result.output_tokens) for result in trials),
        )

    def _verdict(
        self,
        baseline: SkillVariantSummary,
        candidate: SkillVariantSummary,
    ) -> SkillComparisonVerdict:
        success_delta = candidate.success_rate - baseline.success_rate
        score_delta = candidate.mean_score - baseline.mean_score

        if success_delta > 0:
            return SkillComparisonVerdict.IMPROVED
        if success_delta < 0:
            return SkillComparisonVerdict.REGRESSED
        if score_delta >= self.min_score_delta:
            return SkillComparisonVerdict.IMPROVED
        if score_delta <= -self.min_score_delta:
            return SkillComparisonVerdict.REGRESSED
        if abs(score_delta) <= self.equivalence_margin:
            return SkillComparisonVerdict.EQUIVALENT
        return SkillComparisonVerdict.INCONCLUSIVE

    def run(
        self,
        cases: Iterable[SkillEvalCase],
        *,
        candidate_skills: Sequence[Skill],
    ) -> SkillBenchmarkReport:
        case_list = tuple(cases)
        if not case_list:
            raise SkillEvaluationError("Skill benchmark requires at least one eval case")
        if len(case_list) > self.max_cases:
            raise SkillEvaluationError(
                f"Skill benchmark case count exceeds limit ({len(case_list)} > {self.max_cases})"
            )
        ids = [case.case_id for case in case_list]
        if len(ids) != len(set(ids)):
            raise SkillEvaluationError("Skill benchmark contains duplicate case IDs")

        baseline = self._variant_from_skills(())
        candidate = self._variant_from_skills(tuple(candidate_skills))
        if not candidate.skill_refs:
            raise SkillEvaluationError("candidate Skill variant may not be empty")

        comparisons: list[SkillCaseComparison] = []
        for case_index, case in enumerate(case_list):
            baseline_results: list[SkillEvalTrialResult] = []
            candidate_results: list[SkillEvalTrialResult] = []
            for repetition in range(self.repetitions):
                seed = self.seed_base + case_index * self.repetitions + repetition
                baseline_results.append(
                    self.trial(
                        SkillEvalTrialRequest(case, baseline, repetition, seed)
                    )
                )
                candidate_results.append(
                    self.trial(
                        SkillEvalTrialRequest(case, candidate, repetition, seed)
                    )
                )
            baseline_summary = self._summary(baseline, baseline_results)
            candidate_summary = self._summary(candidate, candidate_results)
            comparisons.append(
                SkillCaseComparison(
                    case_id=case.case_id,
                    case_hash=case.content_hash,
                    baseline=baseline_summary,
                    candidate=candidate_summary,
                    score_delta=candidate_summary.mean_score - baseline_summary.mean_score,
                    success_rate_delta=candidate_summary.success_rate - baseline_summary.success_rate,
                    verdict=self._verdict(baseline_summary, candidate_summary),
                )
            )

        verdicts = {item.verdict for item in comparisons}
        if SkillComparisonVerdict.REGRESSED in verdicts:
            overall = SkillComparisonVerdict.REGRESSED
        elif SkillComparisonVerdict.INCONCLUSIVE in verdicts:
            overall = SkillComparisonVerdict.INCONCLUSIVE
        elif SkillComparisonVerdict.IMPROVED in verdicts:
            overall = SkillComparisonVerdict.IMPROVED
        else:
            overall = SkillComparisonVerdict.EQUIVALENT

        return SkillBenchmarkReport(
            skill_refs=candidate.skill_refs,
            repetitions=self.repetitions,
            seed_base=self.seed_base,
            comparisons=tuple(comparisons),
            overall_verdict=overall,
        )


def benchmark_selected_skills(
    registry: SkillRegistry,
    cases: Iterable[SkillEvalCase],
    trial: SkillEvalTrial | Callable[[SkillEvalTrialRequest], SkillEvalTrialResult],
    *,
    skill_names: Iterable[str],
    repetitions: int = 3,
    seed_base: int = 1103,
) -> SkillBenchmarkReport:
    """Convenience boundary for benchmarking exact governed Skill snapshots."""

    names = tuple(dict.fromkeys(skill_names))
    if not names:
        raise SkillEvaluationError("benchmark_selected_skills requires Skill names")
    skills = tuple(registry.load(name) for name in names)
    return SkillBenchmarkRunner(
        trial,
        repetitions=repetitions,
        seed_base=seed_base,
    ).run(cases, candidate_skills=skills)
