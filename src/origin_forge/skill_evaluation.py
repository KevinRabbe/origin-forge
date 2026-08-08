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
_PROTOCOL_ID = "paired-skill-ab-v1"
_MAX_CASE_BYTES = 64 * 1024
_MAX_OBJECTIVE_CHARS = 16 * 1024
_MAX_CASE_LIST_ITEMS = 64
_MAX_CASE_ITEM_CHARS = 4096
_MAX_TAG_ITEMS = 32
_MAX_TAG_CHARS = 128
_MAX_REF_CHARS = 512
_MAX_FAILURE_REASON_CHARS = 4096
_MAX_METADATA_ITEMS = 32
_MAX_METADATA_KEY_CHARS = 128
_MAX_METADATA_VALUE_CHARS = 2048


class SkillEvaluationError(RuntimeError):
    pass


class SkillComparisonVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _bounded_string(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds character limit ({len(value)} > {maximum})")
    return value


def _bounded_tuple(
    values: tuple[str, ...],
    *,
    field: str,
    max_items: int = _MAX_CASE_LIST_ITEMS,
    max_chars: int = _MAX_CASE_ITEM_CHARS,
) -> tuple[str, ...]:
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds item limit ({len(values)} > {max_items})")
    if len(set(values)) != len(values):
        raise ValueError(f"{field} contains duplicates")
    for item in values:
        _bounded_string(item, field=field, maximum=max_chars)
    return values


@dataclass(frozen=True)
class SkillEvalCase:
    case_id: str
    fixture_ref: str
    scorer_ref: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _CASE_ID_RE.fullmatch(self.case_id):
            raise ValueError(f"invalid Skill eval case_id: {self.case_id!r}")
        _bounded_string(self.fixture_ref, field="fixture_ref", maximum=_MAX_REF_CHARS)
        _bounded_string(self.scorer_ref, field="scorer_ref", maximum=_MAX_REF_CHARS)
        _bounded_string(
            self.objective,
            field="Skill eval objective",
            maximum=_MAX_OBJECTIVE_CHARS,
        )
        _bounded_tuple(self.acceptance_criteria, field="acceptance_criteria")
        _bounded_tuple(self.constraints, field="constraints")
        _bounded_tuple(self.required_capabilities, field="required_capabilities")
        _bounded_tuple(self.context_paths, field="context_paths")
        _bounded_tuple(
            self.tags,
            field="tags",
            max_items=_MAX_TAG_ITEMS,
            max_chars=_MAX_TAG_CHARS,
        )
        size = len(_canonical_bytes(self.canonical_dict()))
        if size > _MAX_CASE_BYTES:
            raise ValueError(
                f"Skill eval case exceeds canonical byte limit ({size} > {_MAX_CASE_BYTES})"
            )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "fixture_ref": self.fixture_ref,
            "scorer_ref": self.scorer_ref,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "required_capabilities": list(self.required_capabilities),
            "context_paths": list(self.context_paths),
            "tags": list(self.tags),
        }

    @property
    def content_hash(self) -> str:
        return f"sha256:{hashlib.sha256(_canonical_bytes(self.canonical_dict())).hexdigest()}"


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
    fixture_fingerprint: str
    environment_fingerprint: str
    scorer_fingerprint: str
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
        _bounded_string(
            self.fixture_fingerprint,
            field="fixture_fingerprint",
            maximum=_MAX_REF_CHARS,
        )
        _bounded_string(
            self.environment_fingerprint,
            field="environment_fingerprint",
            maximum=_MAX_REF_CHARS,
        )
        _bounded_string(
            self.scorer_fingerprint,
            field="scorer_fingerprint",
            maximum=_MAX_REF_CHARS,
        )
        if self.failure_reason is not None:
            if not isinstance(self.failure_reason, str):
                raise ValueError("Skill eval failure_reason must be a string or null")
            if len(self.failure_reason) > _MAX_FAILURE_REASON_CHARS:
                raise ValueError("Skill eval failure_reason exceeds character limit")
        if len(self.metadata) > _MAX_METADATA_ITEMS:
            raise ValueError("Skill eval metadata exceeds item limit")
        keys = [key for key, _ in self.metadata]
        if len(keys) != len(set(keys)):
            raise ValueError("Skill eval metadata contains duplicate keys")
        for key, value in self.metadata:
            _bounded_string(
                key,
                field="Skill eval metadata key",
                maximum=_MAX_METADATA_KEY_CHARS,
            )
            if not isinstance(value, str):
                raise ValueError("Skill eval metadata values must be strings")
            if len(value) > _MAX_METADATA_VALUE_CHARS:
                raise ValueError("Skill eval metadata value exceeds character limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "score": float(self.score),
            "duration_ms": self.duration_ms,
            "model_calls": self.model_calls,
            "fixture_fingerprint": self.fixture_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "scorer_fingerprint": self.scorer_fingerprint,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failure_reason": self.failure_reason,
            "metadata": {key: value for key, value in self.metadata},
        }


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
    paired_seeds: tuple[int, ...]
    execution_orders: tuple[tuple[str, str], ...]
    baseline: SkillVariantSummary
    candidate: SkillVariantSummary
    baseline_trials: tuple[SkillEvalTrialResult, ...]
    candidate_trials: tuple[SkillEvalTrialResult, ...]
    score_delta: float
    success_rate_delta: float
    verdict: SkillComparisonVerdict


@dataclass(frozen=True)
class SkillBenchmarkReport:
    protocol_id: str
    environment_fingerprint: str
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
            "protocol_id": self.protocol_id,
            "environment_fingerprint": self.environment_fingerprint,
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
                    "paired_seeds": list(item.paired_seeds),
                    "execution_orders": [list(order) for order in item.execution_orders],
                    "baseline": summary(item.baseline),
                    "candidate": summary(item.candidate),
                    "baseline_trials": [trial.to_dict() for trial in item.baseline_trials],
                    "candidate_trials": [trial.to_dict() for trial in item.candidate_trials],
                    "score_delta": item.score_delta,
                    "success_rate_delta": item.success_rate_delta,
                    "verdict": item.verdict.value,
                }
                for item in self.comparisons
            ],
        }


class SkillBenchmarkRunner:
    """Run paired baseline/candidate trials without modifying or promoting Skills."""

    def __init__(
        self,
        trial: SkillEvalTrial | Callable[[SkillEvalTrialRequest], SkillEvalTrialResult],
        *,
        repetitions: int = 3,
        seed_base: int = 1103,
        min_score_delta: float = 0.05,
        equivalence_margin: float = 0.01,
        max_cases: int = 128,
        max_repetitions: int = 20,
        max_candidate_skills: int = 3,
        max_candidate_instruction_bytes: int = 96 * 1024,
    ):
        if repetitions <= 0:
            raise ValueError("Skill benchmark repetitions must be positive")
        if max_repetitions <= 0:
            raise ValueError("max_repetitions must be positive")
        if repetitions > max_repetitions:
            raise ValueError(
                f"Skill benchmark repetitions exceed limit ({repetitions} > {max_repetitions})"
            )
        if not isinstance(seed_base, int) or isinstance(seed_base, bool):
            raise ValueError("Skill benchmark seed_base must be an integer")
        if not 0.0 < min_score_delta <= 1.0:
            raise ValueError("min_score_delta must be between 0 and 1")
        if not 0.0 <= equivalence_margin < min_score_delta:
            raise ValueError("equivalence_margin must be non-negative and below min_score_delta")
        if max_cases <= 0 or max_candidate_skills <= 0:
            raise ValueError("Skill benchmark count limits must be positive")
        if max_candidate_instruction_bytes <= 0:
            raise ValueError("max_candidate_instruction_bytes must be positive")
        self.trial = trial
        self.repetitions = repetitions
        self.seed_base = seed_base
        self.min_score_delta = min_score_delta
        self.equivalence_margin = equivalence_margin
        self.max_cases = max_cases
        self.max_repetitions = max_repetitions
        self.max_candidate_skills = max_candidate_skills
        self.max_candidate_instruction_bytes = max_candidate_instruction_bytes

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
        return SkillEvalVariant("candidate" if refs else "baseline", refs, instructions)

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

    def _validate_candidate(self, candidate_skills: Sequence[Skill]) -> None:
        if not candidate_skills:
            raise SkillEvaluationError("candidate Skill variant may not be empty")
        if len(candidate_skills) > self.max_candidate_skills:
            raise SkillEvaluationError(
                f"candidate Skill count exceeds limit ({len(candidate_skills)} > {self.max_candidate_skills})"
            )
        refs = [skill.ref for skill in candidate_skills]
        if len(refs) != len(set(refs)):
            raise SkillEvaluationError("candidate Skill variant contains duplicate Skill refs")
        total = sum(skill.instruction_bytes for skill in candidate_skills)
        if total > self.max_candidate_instruction_bytes:
            raise SkillEvaluationError(
                "candidate Skill instructions exceed limit "
                f"({total} > {self.max_candidate_instruction_bytes} bytes)"
            )

    @staticmethod
    def _validate_trial_identity(
        case: SkillEvalCase,
        baseline: SkillEvalTrialResult,
        candidate: SkillEvalTrialResult,
        expected_environment: str | None,
    ) -> str:
        for result in (baseline, candidate):
            if result.fixture_fingerprint != case.fixture_ref:
                raise SkillEvaluationError(
                    f"trial fixture fingerprint does not match case {case.case_id}"
                )
            if result.scorer_fingerprint != case.scorer_ref:
                raise SkillEvaluationError(
                    f"trial scorer fingerprint does not match case {case.case_id}"
                )
        if baseline.environment_fingerprint != candidate.environment_fingerprint:
            raise SkillEvaluationError(
                f"baseline/candidate environment mismatch for case {case.case_id}"
            )
        environment = baseline.environment_fingerprint
        if expected_environment is not None and environment != expected_environment:
            raise SkillEvaluationError(
                "benchmark environment changed between paired trials/cases"
            )
        return environment

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
        self._validate_candidate(candidate_skills)

        baseline = self._variant_from_skills(())
        candidate = self._variant_from_skills(tuple(candidate_skills))
        comparisons: list[SkillCaseComparison] = []
        environment_fingerprint: str | None = None

        for case in case_list:
            baseline_results: list[SkillEvalTrialResult] = []
            candidate_results: list[SkillEvalTrialResult] = []
            seeds: list[int] = []
            orders: list[tuple[str, str]] = []
            case_seed_offset = int(case.content_hash.removeprefix("sha256:")[:8], 16)
            for repetition in range(self.repetitions):
                seed = self.seed_base + case_seed_offset + repetition
                baseline_request = SkillEvalTrialRequest(case, baseline, repetition, seed)
                candidate_request = SkillEvalTrialRequest(case, candidate, repetition, seed)
                if repetition % 2 == 0:
                    order = ("baseline", "candidate")
                    baseline_result = self.trial(baseline_request)
                    candidate_result = self.trial(candidate_request)
                else:
                    order = ("candidate", "baseline")
                    candidate_result = self.trial(candidate_request)
                    baseline_result = self.trial(baseline_request)
                environment_fingerprint = self._validate_trial_identity(
                    case,
                    baseline_result,
                    candidate_result,
                    environment_fingerprint,
                )
                seeds.append(seed)
                orders.append(order)
                baseline_results.append(baseline_result)
                candidate_results.append(candidate_result)

            baseline_summary = self._summary(baseline, baseline_results)
            candidate_summary = self._summary(candidate, candidate_results)
            comparisons.append(
                SkillCaseComparison(
                    case_id=case.case_id,
                    case_hash=case.content_hash,
                    paired_seeds=tuple(seeds),
                    execution_orders=tuple(orders),
                    baseline=baseline_summary,
                    candidate=candidate_summary,
                    baseline_trials=tuple(baseline_results),
                    candidate_trials=tuple(candidate_results),
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

        assert environment_fingerprint is not None
        return SkillBenchmarkReport(
            protocol_id=_PROTOCOL_ID,
            environment_fingerprint=environment_fingerprint,
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
    """Benchmark exact governed Skill snapshots selected by operator-owned names."""

    names = tuple(dict.fromkeys(skill_names))
    if not names:
        raise SkillEvaluationError("benchmark_selected_skills requires Skill names")
    skills = tuple(registry.load(name) for name in names)
    return SkillBenchmarkRunner(
        trial,
        repetitions=repetitions,
        seed_base=seed_base,
    ).run(cases, candidate_skills=skills)
