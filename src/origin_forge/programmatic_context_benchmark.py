from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .programmatic_context_models import ContextProgram, ProgrammaticContextModelError
from .runtime_observation_models import content_hash, validate_sha256


_MAX_METRIC = 10_000_000_000
_MAX_CASES = 256


class ContextExperimentVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"


def _exact_int(value: int, label: str, minimum: int = 0, maximum: int = _MAX_METRIC) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProgrammaticContextModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or any(c.isspace() for c in value):
        raise ProgrammaticContextModelError(f"{label} must be a bounded token")
    return value


@dataclass(frozen=True)
class ContextExperimentObservation:
    success: bool
    quality_milli: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    context_bytes: int
    wall_time_ms: int
    resource_units: int
    evidence_hash: str

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise ProgrammaticContextModelError("success must be bool")
        _exact_int(self.quality_milli, "quality_milli", 0, 1000)
        for field in (
            "model_calls",
            "input_tokens",
            "output_tokens",
            "context_bytes",
            "wall_time_ms",
            "resource_units",
        ):
            _exact_int(getattr(self, field), field)
        validate_sha256(self.evidence_hash, "experiment evidence_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "quality_milli": self.quality_milli,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "context_bytes": self.context_bytes,
            "wall_time_ms": self.wall_time_ms,
            "resource_units": self.resource_units,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True)
class ContextExperimentPolicy:
    max_quality_regression_milli: int = 0
    max_model_call_increase: int = 0
    max_input_token_increase: int = 0
    max_output_token_increase: int = 0
    max_context_byte_increase: int = 0
    max_wall_time_increase_ms: int = 60_000
    max_resource_unit_increase: int = 0

    def __post_init__(self) -> None:
        _exact_int(self.max_quality_regression_milli, "max_quality_regression_milli", 0, 1000)
        for field in (
            "max_model_call_increase",
            "max_input_token_increase",
            "max_output_token_increase",
            "max_context_byte_increase",
            "max_wall_time_increase_ms",
            "max_resource_unit_increase",
        ):
            _exact_int(getattr(self, field), field)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_quality_regression_milli": self.max_quality_regression_milli,
            "max_model_call_increase": self.max_model_call_increase,
            "max_input_token_increase": self.max_input_token_increase,
            "max_output_token_increase": self.max_output_token_increase,
            "max_context_byte_increase": self.max_context_byte_increase,
            "max_wall_time_increase_ms": self.max_wall_time_increase_ms,
            "max_resource_unit_increase": self.max_resource_unit_increase,
        }


@dataclass(frozen=True)
class ContextExperimentCase:
    case_id: str
    case_hash: str
    environment_hash: str
    baseline: ContextExperimentObservation
    programmatic: ContextExperimentObservation
    verdict: ContextExperimentVerdict
    regression_reasons: tuple[str, ...]
    improvements: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _token(self.case_id, "case_id"))
        validate_sha256(self.case_hash, "case_hash")
        validate_sha256(self.environment_hash, "environment_hash")
        if not isinstance(self.baseline, ContextExperimentObservation) or not isinstance(
            self.programmatic, ContextExperimentObservation
        ):
            raise ProgrammaticContextModelError("experiment observations are invalid")
        if not isinstance(self.verdict, ContextExperimentVerdict):
            raise ProgrammaticContextModelError("case verdict is invalid")
        if len(set(self.regression_reasons)) != len(self.regression_reasons):
            raise ProgrammaticContextModelError("duplicate regression reasons")
        if len(set(self.improvements)) != len(self.improvements):
            raise ProgrammaticContextModelError("duplicate improvement labels")
        object.__setattr__(self, "regression_reasons", tuple(sorted(self.regression_reasons)))
        object.__setattr__(self, "improvements", tuple(sorted(self.improvements)))

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "case_hash": self.case_hash,
            "environment_hash": self.environment_hash,
            "baseline": self.baseline.to_dict(),
            "programmatic": self.programmatic.to_dict(),
            "verdict": self.verdict.value,
            "regression_reasons": list(self.regression_reasons),
            "improvements": list(self.improvements),
        }


def compare_context_case(
    *,
    case_id: str,
    case_hash: str,
    environment_hash: str,
    baseline: ContextExperimentObservation,
    programmatic: ContextExperimentObservation,
    policy: ContextExperimentPolicy,
) -> ContextExperimentCase:
    if not isinstance(policy, ContextExperimentPolicy):
        raise TypeError("policy must be a ContextExperimentPolicy")
    regressions: list[str] = []
    improvements: list[str] = []

    if baseline.success and not programmatic.success:
        regressions.append("success")
    elif programmatic.success and not baseline.success:
        improvements.append("success")

    quality_delta = programmatic.quality_milli - baseline.quality_milli
    if quality_delta < -policy.max_quality_regression_milli:
        regressions.append("quality_milli")
    elif quality_delta > 0:
        improvements.append("quality_milli")

    limits = {
        "model_calls": policy.max_model_call_increase,
        "input_tokens": policy.max_input_token_increase,
        "output_tokens": policy.max_output_token_increase,
        "context_bytes": policy.max_context_byte_increase,
        "wall_time_ms": policy.max_wall_time_increase_ms,
        "resource_units": policy.max_resource_unit_increase,
    }
    for field, maximum_increase in limits.items():
        delta = getattr(programmatic, field) - getattr(baseline, field)
        if delta > maximum_increase:
            regressions.append(field)
        elif delta < 0:
            improvements.append(field)

    if regressions:
        verdict = ContextExperimentVerdict.REGRESSED
    elif programmatic.success and improvements:
        # Efficiency/quality improvements are useful only when the candidate path
        # actually succeeds. Two failed variants cannot create an IMPROVED verdict
        # merely because the second failure was cheaper.
        verdict = ContextExperimentVerdict.IMPROVED
    else:
        verdict = ContextExperimentVerdict.EQUIVALENT

    return ContextExperimentCase(
        case_id=case_id,
        case_hash=case_hash,
        environment_hash=environment_hash,
        baseline=baseline,
        programmatic=programmatic,
        verdict=verdict,
        regression_reasons=tuple(regressions),
        improvements=tuple(improvements),
    )


@dataclass(frozen=True)
class ContextExperimentReport:
    experiment_id: str
    program_id: str
    program_hash: str
    policy: ContextExperimentPolicy
    cases: tuple[ContextExperimentCase, ...]
    verdict: ContextExperimentVerdict

    def __post_init__(self) -> None:
        if not validate_id(self.experiment_id, IdKind.CONTEXT_EXPERIMENT):
            raise ProgrammaticContextModelError("experiment_id must be a CTXEXP ID")
        if not validate_id(self.program_id, IdKind.CONTEXT_PROGRAM):
            raise ProgrammaticContextModelError("program_id must be a CTXPROG ID")
        validate_sha256(self.program_hash, "program_hash")
        if not isinstance(self.policy, ContextExperimentPolicy):
            raise ProgrammaticContextModelError("experiment policy is invalid")
        cases = tuple(self.cases)
        if not cases or len(cases) > _MAX_CASES or not all(
            isinstance(v, ContextExperimentCase) for v in cases
        ):
            raise ProgrammaticContextModelError("experiment cases are outside bounds")
        ids = [v.case_id for v in cases]
        if len(ids) != len(set(ids)):
            raise ProgrammaticContextModelError("experiment contains duplicate case IDs")
        environments = {v.environment_hash for v in cases}
        if len(environments) != 1:
            raise ProgrammaticContextModelError("experiment environment changed between cases")
        for case in cases:
            expected_case = compare_context_case(
                case_id=case.case_id,
                case_hash=case.case_hash,
                environment_hash=case.environment_hash,
                baseline=case.baseline,
                programmatic=case.programmatic,
                policy=self.policy,
            )
            if (
                case.verdict is not expected_case.verdict
                or case.regression_reasons != expected_case.regression_reasons
                or case.improvements != expected_case.improvements
            ):
                raise ProgrammaticContextModelError(
                    f"experiment case classification is inconsistent: {case.case_id}"
                )
        object.__setattr__(self, "cases", tuple(sorted(cases, key=lambda v: v.case_id)))
        if not isinstance(self.verdict, ContextExperimentVerdict):
            raise ProgrammaticContextModelError("experiment verdict is invalid")
        expected = self._overall(self.cases)
        if self.verdict is not expected:
            raise ProgrammaticContextModelError("experiment verdict is inconsistent")

    @staticmethod
    def _overall(cases: tuple[ContextExperimentCase, ...]) -> ContextExperimentVerdict:
        verdicts = {v.verdict for v in cases}
        if ContextExperimentVerdict.REGRESSED in verdicts:
            return ContextExperimentVerdict.REGRESSED
        if ContextExperimentVerdict.IMPROVED in verdicts:
            return ContextExperimentVerdict.IMPROVED
        return ContextExperimentVerdict.EQUIVALENT

    @classmethod
    def create(
        cls,
        *,
        program: ContextProgram,
        policy: ContextExperimentPolicy,
        cases: Iterable[ContextExperimentCase],
    ) -> "ContextExperimentReport":
        if not isinstance(program, ContextProgram):
            raise TypeError("program must be a ContextProgram")
        case_tuple = tuple(cases)
        return cls(
            experiment_id=new_id(IdKind.CONTEXT_EXPERIMENT),
            program_id=program.program_id,
            program_hash=program.content_hash,
            policy=policy,
            cases=case_tuple,
            verdict=cls._overall(case_tuple),
        )

    def bind_program(self, program: ContextProgram) -> None:
        if self.program_id != program.program_id or self.program_hash != program.content_hash:
            raise ProgrammaticContextModelError("experiment does not bind exact program")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "program_id": self.program_id,
            "program_hash": self.program_hash,
            "policy": self.policy.to_dict(),
            "cases": [v.to_dict() for v in self.cases],
            "verdict": self.verdict.value,
            "phase26_promotion_authorized": False,
            "production_activation_authorized": False,
            "production_task_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
