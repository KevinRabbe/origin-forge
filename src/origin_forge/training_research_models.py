from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import canonical_bytes, content_hash, validate_sha256


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_MAX_TEXT_CHARS = 8192
_MAX_EXAMPLE_BYTES = 128 * 1024
_MAX_EVIDENCE_REFS = 128
_MAX_TRAJECTORIES = 100_000
_MAX_REASONS = 64
_MAX_METRIC = 10_000_000_000
_MAX_TRAINING_TOKENS = 10_000_000_000
_MAX_WALL_TIME_MS = 30 * 24 * 60 * 60 * 1000
_MAX_CHECKPOINT_BYTES = 1024 * 1024 * 1024 * 1024


class TrainingResearchModelError(ValueError):
    pass


class TrainingEvidenceType(StrEnum):
    TASK = "TASK"
    RUN = "RUN"
    VERIFICATION = "VERIFICATION"
    ARTIFACT = "ARTIFACT"
    DECISION = "DECISION"


class ResearchDisclosureClass(StrEnum):
    ALLOWED = "ALLOWED"
    PROTECTED = "PROTECTED"


class TrainingTrajectoryOutcome(StrEnum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"


class TrainingDatasetSplit(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class TrainingMethodFamily(StrEnum):
    ROUTING_CLASSIFIER = "ROUTING_CLASSIFIER"
    SUPERVISED_FINETUNE = "SUPERVISED_FINETUNE"
    ADAPTER_LORA = "ADAPTER_LORA"
    OFFLINE_DISTILLATION = "OFFLINE_DISTILLATION"


class TrainingExperimentVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise TrainingResearchModelError(f"{label} must be a bounded identity token")
    return value


def _text(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TrainingResearchModelError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_TEXT_CHARS:
        raise TrainingResearchModelError(f"{label} is outside text bounds")
    for character in normalized:
        codepoint = ord(character)
        if codepoint == 0 or (codepoint < 32 and character not in ("\t", "\n", "\r")) or codepoint == 127:
            raise TrainingResearchModelError(f"{label} contains forbidden control characters")
    return normalized


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise TrainingResearchModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _canonical_example(value: object) -> str:
    if not isinstance(value, dict):
        raise TrainingResearchModelError("trajectory example must be a JSON object")
    try:
        data = canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise TrainingResearchModelError("trajectory example must be finite canonical JSON") from exc
    if len(data) > _MAX_EXAMPLE_BYTES:
        raise TrainingResearchModelError("trajectory example exceeds byte limit")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise TrainingResearchModelError("trajectory example canonicalization failed") from exc
    if not isinstance(parsed, dict):  # pragma: no cover
        raise TrainingResearchModelError("trajectory example must remain a JSON object")
    return data.decode("utf-8")


_EVIDENCE_KIND = {
    TrainingEvidenceType.TASK: IdKind.TASK,
    TrainingEvidenceType.RUN: IdKind.RUN,
    TrainingEvidenceType.VERIFICATION: IdKind.VERIFICATION,
    TrainingEvidenceType.ARTIFACT: IdKind.ARTIFACT,
    TrainingEvidenceType.DECISION: IdKind.DECISION,
}


@dataclass(frozen=True)
class TrainingEvidenceRef:
    evidence_type: TrainingEvidenceType
    ref_id: str
    content_hash: str
    revision: int | None
    disclosure: ResearchDisclosureClass

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_type, TrainingEvidenceType):
            raise TrainingResearchModelError("evidence_type is invalid")
        if not validate_id(self.ref_id, _EVIDENCE_KIND[self.evidence_type]):
            raise TrainingResearchModelError("training evidence ref ID has wrong type")
        validate_sha256(self.content_hash, "training evidence content_hash")
        if self.revision is not None:
            _exact_int(self.revision, "training evidence revision", 0, 2_147_483_647)
        if not isinstance(self.disclosure, ResearchDisclosureClass):
            raise TrainingResearchModelError("training evidence disclosure is invalid")

    @property
    def key(self) -> tuple[str, str, str, int, str]:
        return (
            self.evidence_type.value,
            self.ref_id,
            self.content_hash,
            -1 if self.revision is None else self.revision,
            self.disclosure.value,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type.value,
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "revision": self.revision,
            "disclosure": self.disclosure.value,
        }


@dataclass(frozen=True)
class TrainingTrajectory:
    trajectory_id: str
    project_id: str
    task_id: str
    run_id: str
    leakage_group_hash: str
    outcome: TrainingTrajectoryOutcome
    objective: str
    model_profile: str | None
    model_hash: str | None
    example_json: str
    source_refs: tuple[TrainingEvidenceRef, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.trajectory_id, IdKind.TRAINING_TRAJECTORY):
            raise TrainingResearchModelError("trajectory_id must be a TRAJ ID")
        if not validate_id(self.project_id, IdKind.PROJECT):
            raise TrainingResearchModelError("trajectory project_id is invalid")
        if not validate_id(self.task_id, IdKind.TASK):
            raise TrainingResearchModelError("trajectory task_id is invalid")
        if not validate_id(self.run_id, IdKind.RUN):
            raise TrainingResearchModelError("trajectory run_id is invalid")
        validate_sha256(self.leakage_group_hash, "trajectory leakage_group_hash")
        if not isinstance(self.outcome, TrainingTrajectoryOutcome):
            raise TrainingResearchModelError("trajectory outcome is invalid")
        object.__setattr__(self, "objective", _text(self.objective, "trajectory objective"))
        if self.model_profile is not None:
            object.__setattr__(self, "model_profile", _token(self.model_profile, "model_profile"))
        if self.model_hash is not None:
            validate_sha256(self.model_hash, "trajectory model_hash")
        try:
            example = json.loads(self.example_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TrainingResearchModelError("trajectory example_json is invalid") from exc
        canonical = _canonical_example(example)
        if canonical != self.example_json:
            raise TrainingResearchModelError("trajectory example_json must be canonical")
        refs = tuple(self.source_refs)
        if not 2 <= len(refs) <= _MAX_EVIDENCE_REFS or not all(
            isinstance(value, TrainingEvidenceRef) for value in refs
        ):
            raise TrainingResearchModelError("trajectory source_refs are outside bounds")
        keys = [value.key for value in refs]
        if len(keys) != len(set(keys)):
            raise TrainingResearchModelError("trajectory source_refs contain duplicates")
        task_refs = [value for value in refs if value.evidence_type is TrainingEvidenceType.TASK]
        run_refs = [value for value in refs if value.evidence_type is TrainingEvidenceType.RUN]
        if len(task_refs) != 1 or task_refs[0].ref_id != self.task_id:
            raise TrainingResearchModelError("trajectory must bind exactly its Task evidence")
        if len(run_refs) != 1 or run_refs[0].ref_id != self.run_id:
            raise TrainingResearchModelError("trajectory must bind exactly its Run evidence")
        if self.outcome is not TrainingTrajectoryOutcome.INFRASTRUCTURE_FAILURE:
            if not any(
                value.evidence_type is TrainingEvidenceType.VERIFICATION for value in refs
            ):
                raise TrainingResearchModelError(
                    "verified trajectory outcome requires verification evidence"
                )
        object.__setattr__(self, "source_refs", tuple(sorted(refs, key=lambda value: value.key)))

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        task_id: str,
        run_id: str,
        leakage_group_hash: str,
        outcome: TrainingTrajectoryOutcome,
        objective: str,
        example: Mapping[str, object],
        source_refs: Iterable[TrainingEvidenceRef],
        model_profile: str | None = None,
        model_hash: str | None = None,
    ) -> "TrainingTrajectory":
        return cls(
            trajectory_id=new_id(IdKind.TRAINING_TRAJECTORY),
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            leakage_group_hash=leakage_group_hash,
            outcome=outcome,
            objective=objective,
            model_profile=model_profile,
            model_hash=model_hash,
            example_json=_canonical_example(dict(example)),
            source_refs=tuple(source_refs),
        )

    @property
    def example(self) -> dict[str, object]:
        value = json.loads(self.example_json)
        assert isinstance(value, dict)
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "trajectory_id": self.trajectory_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "leakage_group_hash": self.leakage_group_hash,
            "outcome": self.outcome.value,
            "objective": self.objective,
            "model_profile": self.model_profile,
            "model_hash": self.model_hash,
            "example": self.example,
            "source_refs": [value.to_dict() for value in self.source_refs],
            "production_training_authorized": False,
            "production_model_activation_authorized": False,
            "production_task_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class TrainingEligibilityAudit:
    audit_id: str
    trajectory_id: str
    trajectory_hash: str
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.audit_id, IdKind.TRAINING_ELIGIBILITY_AUDIT):
            raise TrainingResearchModelError("audit_id must be a TRAUD ID")
        if not validate_id(self.trajectory_id, IdKind.TRAINING_TRAJECTORY):
            raise TrainingResearchModelError("eligibility trajectory_id is invalid")
        validate_sha256(self.trajectory_hash, "eligibility trajectory_hash")
        object.__setattr__(self, "policy_id", _token(self.policy_id, "eligibility policy_id"))
        object.__setattr__(self, "policy_version", _token(self.policy_version, "eligibility policy_version"))
        validate_sha256(self.policy_fingerprint, "eligibility policy_fingerprint")
        if type(self.eligible) is not bool:
            raise TrainingResearchModelError("eligibility eligible must be bool")
        reasons = tuple(self.reasons)
        if len(reasons) > _MAX_REASONS or len(set(reasons)) != len(reasons):
            raise TrainingResearchModelError("eligibility reasons are outside bounds")
        for reason in reasons:
            _token(reason, "eligibility reason")
        object.__setattr__(self, "reasons", tuple(sorted(reasons)))
        if self.eligible == bool(self.reasons):
            raise TrainingResearchModelError(
                "eligible audit requires zero reasons; ineligible audit requires reasons"
            )

    @staticmethod
    def _reasons(trajectory: TrainingTrajectory) -> tuple[str, ...]:
        reasons: set[str] = set()
        if any(
            value.disclosure is ResearchDisclosureClass.PROTECTED
            for value in trajectory.source_refs
        ):
            reasons.add("protected-evidence")
        return tuple(sorted(reasons))

    @classmethod
    def create(
        cls,
        *,
        trajectory: TrainingTrajectory,
        policy_id: str,
        policy_version: str,
        policy_fingerprint: str,
    ) -> "TrainingEligibilityAudit":
        if not isinstance(trajectory, TrainingTrajectory):
            raise TypeError("trajectory must be a TrainingTrajectory")
        reasons = cls._reasons(trajectory)
        return cls(
            audit_id=new_id(IdKind.TRAINING_ELIGIBILITY_AUDIT),
            trajectory_id=trajectory.trajectory_id,
            trajectory_hash=trajectory.content_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_fingerprint=policy_fingerprint,
            eligible=not reasons,
            reasons=reasons,
        )

    def bind(self, trajectory: TrainingTrajectory) -> None:
        if self.trajectory_id != trajectory.trajectory_id or self.trajectory_hash != trajectory.content_hash:
            raise TrainingResearchModelError("eligibility audit trajectory binding drifted")
        reasons = self._reasons(trajectory)
        if self.reasons != reasons or self.eligible != (not reasons):
            raise TrainingResearchModelError("eligibility audit classification is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "trajectory_id": self.trajectory_id,
            "trajectory_hash": self.trajectory_hash,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "training_execution_authorized": False,
            "production_model_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class TrainingDatasetEntry:
    trajectory_id: str
    trajectory_hash: str
    audit_id: str
    audit_hash: str
    leakage_group_hash: str
    split: TrainingDatasetSplit

    def __post_init__(self) -> None:
        if not validate_id(self.trajectory_id, IdKind.TRAINING_TRAJECTORY):
            raise TrainingResearchModelError("dataset trajectory_id is invalid")
        validate_sha256(self.trajectory_hash, "dataset trajectory_hash")
        if not validate_id(self.audit_id, IdKind.TRAINING_ELIGIBILITY_AUDIT):
            raise TrainingResearchModelError("dataset audit_id is invalid")
        validate_sha256(self.audit_hash, "dataset audit_hash")
        validate_sha256(self.leakage_group_hash, "dataset leakage_group_hash")
        if not isinstance(self.split, TrainingDatasetSplit):
            raise TrainingResearchModelError("dataset split is invalid")

    @property
    def key(self) -> tuple[str, str]:
        return (self.trajectory_id, self.trajectory_hash)

    def to_dict(self) -> dict[str, str]:
        return {
            "trajectory_id": self.trajectory_id,
            "trajectory_hash": self.trajectory_hash,
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "leakage_group_hash": self.leakage_group_hash,
            "split": self.split.value,
        }


def deterministic_training_split(
    *,
    split_salt_hash: str,
    leakage_group_hash: str,
) -> TrainingDatasetSplit:
    validate_sha256(split_salt_hash, "split_salt_hash")
    validate_sha256(leakage_group_hash, "leakage_group_hash")
    digest = hashlib.sha256(
        canonical_bytes(
            {
                "leakage_group_hash": leakage_group_hash,
                "split_salt_hash": split_salt_hash,
                "split_policy": "80-10-10-v1",
            }
        )
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 1000
    if bucket < 800:
        return TrainingDatasetSplit.TRAIN
    if bucket < 900:
        return TrainingDatasetSplit.VALIDATION
    return TrainingDatasetSplit.TEST


@dataclass(frozen=True)
class TrainingDatasetManifest:
    dataset_id: str
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    split_salt_hash: str
    entries: tuple[TrainingDatasetEntry, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.dataset_id, IdKind.TRAINING_DATASET):
            raise TrainingResearchModelError("dataset_id must be a TRDATA ID")
        object.__setattr__(self, "policy_id", _token(self.policy_id, "dataset policy_id"))
        object.__setattr__(self, "policy_version", _token(self.policy_version, "dataset policy_version"))
        validate_sha256(self.policy_fingerprint, "dataset policy_fingerprint")
        validate_sha256(self.split_salt_hash, "dataset split_salt_hash")
        entries = tuple(self.entries)
        if not entries or len(entries) > _MAX_TRAJECTORIES or not all(
            isinstance(value, TrainingDatasetEntry) for value in entries
        ):
            raise TrainingResearchModelError("dataset entries are outside bounds")
        keys = [value.key for value in entries]
        if len(keys) != len(set(keys)):
            raise TrainingResearchModelError("dataset contains duplicate trajectories")
        group_splits: dict[str, TrainingDatasetSplit] = {}
        for entry in entries:
            expected = deterministic_training_split(
                split_salt_hash=self.split_salt_hash,
                leakage_group_hash=entry.leakage_group_hash,
            )
            if entry.split is not expected:
                raise TrainingResearchModelError("dataset split assignment is inconsistent")
            previous = group_splits.setdefault(entry.leakage_group_hash, entry.split)
            if previous is not entry.split:
                raise TrainingResearchModelError("leakage group crosses dataset splits")
        object.__setattr__(self, "entries", tuple(sorted(entries, key=lambda value: value.key)))

    @classmethod
    def create(
        cls,
        *,
        trajectories: Iterable[TrainingTrajectory],
        audits: Iterable[TrainingEligibilityAudit],
        policy_id: str,
        policy_version: str,
        policy_fingerprint: str,
        split_salt_hash: str,
    ) -> "TrainingDatasetManifest":
        trajectory_values = tuple(trajectories)
        audit_values = tuple(audits)
        if len(trajectory_values) != len(audit_values):
            raise TrainingResearchModelError("dataset requires one audit per trajectory")
        by_id = {value.trajectory_id: value for value in audit_values}
        if len(by_id) != len(audit_values):
            raise TrainingResearchModelError("dataset audits contain duplicate trajectory IDs")
        entries: list[TrainingDatasetEntry] = []
        for trajectory in trajectory_values:
            try:
                audit = by_id[trajectory.trajectory_id]
            except KeyError as exc:
                raise TrainingResearchModelError("dataset trajectory is missing its audit") from exc
            audit.bind(trajectory)
            if (
                audit.policy_id != policy_id
                or audit.policy_version != policy_version
                or audit.policy_fingerprint != policy_fingerprint
            ):
                raise TrainingResearchModelError("dataset audit policy binding drifted")
            if not audit.eligible:
                raise TrainingResearchModelError("ineligible trajectory may not enter dataset")
            entries.append(
                TrainingDatasetEntry(
                    trajectory_id=trajectory.trajectory_id,
                    trajectory_hash=trajectory.content_hash,
                    audit_id=audit.audit_id,
                    audit_hash=audit.content_hash,
                    leakage_group_hash=trajectory.leakage_group_hash,
                    split=deterministic_training_split(
                        split_salt_hash=split_salt_hash,
                        leakage_group_hash=trajectory.leakage_group_hash,
                    ),
                )
            )
        return cls(
            dataset_id=new_id(IdKind.TRAINING_DATASET),
            policy_id=policy_id,
            policy_version=policy_version,
            policy_fingerprint=policy_fingerprint,
            split_salt_hash=split_salt_hash,
            entries=tuple(entries),
        )

    def to_dict(self) -> dict[str, object]:
        counts = {split.value: 0 for split in TrainingDatasetSplit}
        for entry in self.entries:
            counts[entry.split.value] += 1
        return {
            "dataset_id": self.dataset_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "split_salt_hash": self.split_salt_hash,
            "entries": [value.to_dict() for value in self.entries],
            "split_counts": counts,
            "training_execution_authorized": False,
            "production_model_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class TrainingAcceptancePolicy:
    max_success_regression_milli: int = 0
    max_quality_regression_milli: int = 0
    max_critical_failure_increase: int = 0
    max_model_call_increase: int = 0
    max_input_token_increase: int = 0
    max_output_token_increase: int = 0
    max_wall_time_increase_ms: int = 60_000

    def __post_init__(self) -> None:
        _exact_int(self.max_success_regression_milli, "max_success_regression_milli", 0, 1000)
        _exact_int(self.max_quality_regression_milli, "max_quality_regression_milli", 0, 1000)
        for field in (
            "max_critical_failure_increase",
            "max_model_call_increase",
            "max_input_token_increase",
            "max_output_token_increase",
            "max_wall_time_increase_ms",
        ):
            _exact_int(getattr(self, field), field, 0, _MAX_METRIC)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_success_regression_milli": self.max_success_regression_milli,
            "max_quality_regression_milli": self.max_quality_regression_milli,
            "max_critical_failure_increase": self.max_critical_failure_increase,
            "max_model_call_increase": self.max_model_call_increase,
            "max_input_token_increase": self.max_input_token_increase,
            "max_output_token_increase": self.max_output_token_increase,
            "max_wall_time_increase_ms": self.max_wall_time_increase_ms,
        }


@dataclass(frozen=True)
class TrainingExperimentPlan:
    plan_id: str
    dataset_id: str
    dataset_hash: str
    base_model_profile: str
    base_model_hash: str
    tokenizer_hash: str
    method_family: TrainingMethodFamily
    trainer_id: str
    trainer_version: str
    trainer_fingerprint: str
    evaluator_id: str
    evaluator_version: str
    evaluator_fingerprint: str
    evaluation_suite_id: str
    evaluation_suite_hash: str
    max_training_tokens: int
    max_wall_time_ms: int
    max_checkpoint_bytes: int
    acceptance: TrainingAcceptancePolicy

    def __post_init__(self) -> None:
        if not validate_id(self.plan_id, IdKind.TRAINING_EXPERIMENT_PLAN):
            raise TrainingResearchModelError("plan_id must be a TRPLAN ID")
        if not validate_id(self.dataset_id, IdKind.TRAINING_DATASET):
            raise TrainingResearchModelError("training plan dataset_id is invalid")
        for field in (
            "dataset_hash",
            "base_model_hash",
            "tokenizer_hash",
            "trainer_fingerprint",
            "evaluator_fingerprint",
            "evaluation_suite_hash",
        ):
            validate_sha256(getattr(self, field), field)
        for field in (
            "base_model_profile",
            "trainer_id",
            "trainer_version",
            "evaluator_id",
            "evaluator_version",
            "evaluation_suite_id",
        ):
            object.__setattr__(self, field, _token(getattr(self, field), field))
        if not isinstance(self.method_family, TrainingMethodFamily):
            raise TrainingResearchModelError("training method_family is invalid")
        _exact_int(self.max_training_tokens, "max_training_tokens", 1, _MAX_TRAINING_TOKENS)
        _exact_int(self.max_wall_time_ms, "max_wall_time_ms", 1, _MAX_WALL_TIME_MS)
        _exact_int(self.max_checkpoint_bytes, "max_checkpoint_bytes", 1, _MAX_CHECKPOINT_BYTES)
        if not isinstance(self.acceptance, TrainingAcceptancePolicy):
            raise TrainingResearchModelError("training acceptance policy is invalid")

    @classmethod
    def create(
        cls,
        *,
        dataset: TrainingDatasetManifest,
        base_model_profile: str,
        base_model_hash: str,
        tokenizer_hash: str,
        method_family: TrainingMethodFamily,
        trainer_id: str,
        trainer_version: str,
        trainer_fingerprint: str,
        evaluator_id: str,
        evaluator_version: str,
        evaluator_fingerprint: str,
        evaluation_suite_id: str,
        evaluation_suite_hash: str,
        max_training_tokens: int,
        max_wall_time_ms: int,
        max_checkpoint_bytes: int,
        acceptance: TrainingAcceptancePolicy,
    ) -> "TrainingExperimentPlan":
        if not isinstance(dataset, TrainingDatasetManifest):
            raise TypeError("dataset must be a TrainingDatasetManifest")
        return cls(
            plan_id=new_id(IdKind.TRAINING_EXPERIMENT_PLAN),
            dataset_id=dataset.dataset_id,
            dataset_hash=dataset.content_hash,
            base_model_profile=base_model_profile,
            base_model_hash=base_model_hash,
            tokenizer_hash=tokenizer_hash,
            method_family=method_family,
            trainer_id=trainer_id,
            trainer_version=trainer_version,
            trainer_fingerprint=trainer_fingerprint,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            evaluator_fingerprint=evaluator_fingerprint,
            evaluation_suite_id=evaluation_suite_id,
            evaluation_suite_hash=evaluation_suite_hash,
            max_training_tokens=max_training_tokens,
            max_wall_time_ms=max_wall_time_ms,
            max_checkpoint_bytes=max_checkpoint_bytes,
            acceptance=acceptance,
        )

    def bind_dataset(self, dataset: TrainingDatasetManifest) -> None:
        if self.dataset_id != dataset.dataset_id or self.dataset_hash != dataset.content_hash:
            raise TrainingResearchModelError("training plan dataset binding drifted")

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "base_model_profile": self.base_model_profile,
            "base_model_hash": self.base_model_hash,
            "tokenizer_hash": self.tokenizer_hash,
            "method_family": self.method_family.value,
            "trainer_id": self.trainer_id,
            "trainer_version": self.trainer_version,
            "trainer_fingerprint": self.trainer_fingerprint,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "evaluation_suite_id": self.evaluation_suite_id,
            "evaluation_suite_hash": self.evaluation_suite_hash,
            "max_training_tokens": self.max_training_tokens,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "acceptance": self.acceptance.to_dict(),
            "training_execution_authorized": False,
            "production_model_activation_authorized": False,
            "routing_activation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class TrainingEvaluationObservation:
    success_milli: int
    quality_milli: int
    critical_failures: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    evidence_hash: str

    def __post_init__(self) -> None:
        _exact_int(self.success_milli, "success_milli", 0, 1000)
        _exact_int(self.quality_milli, "quality_milli", 0, 1000)
        for field in (
            "critical_failures",
            "model_calls",
            "input_tokens",
            "output_tokens",
            "wall_time_ms",
        ):
            _exact_int(getattr(self, field), field, 0, _MAX_METRIC)
        validate_sha256(self.evidence_hash, "evaluation evidence_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "success_milli": self.success_milli,
            "quality_milli": self.quality_milli,
            "critical_failures": self.critical_failures,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time_ms": self.wall_time_ms,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True)
class TrainingExperimentReport:
    report_id: str
    plan_id: str
    plan_hash: str
    candidate_checkpoint_hash: str
    checkpoint_bytes: int
    evaluator_id: str
    evaluator_version: str
    evaluator_fingerprint: str
    baseline: TrainingEvaluationObservation
    candidate: TrainingEvaluationObservation
    verdict: TrainingExperimentVerdict
    regression_reasons: tuple[str, ...]
    improvements: tuple[str, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.report_id, IdKind.TRAINING_EXPERIMENT_REPORT):
            raise TrainingResearchModelError("report_id must be a TRREP ID")
        if not validate_id(self.plan_id, IdKind.TRAINING_EXPERIMENT_PLAN):
            raise TrainingResearchModelError("training report plan_id is invalid")
        validate_sha256(self.plan_hash, "training report plan_hash")
        validate_sha256(self.candidate_checkpoint_hash, "candidate_checkpoint_hash")
        _exact_int(self.checkpoint_bytes, "checkpoint_bytes", 1, _MAX_CHECKPOINT_BYTES)
        for field in ("evaluator_id", "evaluator_version"):
            object.__setattr__(self, field, _token(getattr(self, field), field))
        validate_sha256(self.evaluator_fingerprint, "report evaluator_fingerprint")
        if not isinstance(self.baseline, TrainingEvaluationObservation) or not isinstance(
            self.candidate, TrainingEvaluationObservation
        ):
            raise TrainingResearchModelError("training report observations are invalid")
        if not isinstance(self.verdict, TrainingExperimentVerdict):
            raise TrainingResearchModelError("training report verdict is invalid")
        for label, values in (
            ("regression reasons", self.regression_reasons),
            ("improvements", self.improvements),
        ):
            if len(values) > _MAX_REASONS or len(set(values)) != len(values):
                raise TrainingResearchModelError(f"training report {label} are outside bounds")
            for value in values:
                _token(value, label)
        object.__setattr__(self, "regression_reasons", tuple(sorted(self.regression_reasons)))
        object.__setattr__(self, "improvements", tuple(sorted(self.improvements)))

    @staticmethod
    def _classification(
        *,
        baseline: TrainingEvaluationObservation,
        candidate: TrainingEvaluationObservation,
        acceptance: TrainingAcceptancePolicy,
    ) -> tuple[TrainingExperimentVerdict, tuple[str, ...], tuple[str, ...]]:
        regressions: list[str] = []
        improvements: list[str] = []
        quality_fields = {
            "success_milli": acceptance.max_success_regression_milli,
            "quality_milli": acceptance.max_quality_regression_milli,
        }
        for field, allowed_regression in quality_fields.items():
            delta = getattr(candidate, field) - getattr(baseline, field)
            if delta < -allowed_regression:
                regressions.append(field)
            elif delta > 0:
                improvements.append(field)
        cost_fields = {
            "critical_failures": acceptance.max_critical_failure_increase,
            "model_calls": acceptance.max_model_call_increase,
            "input_tokens": acceptance.max_input_token_increase,
            "output_tokens": acceptance.max_output_token_increase,
            "wall_time_ms": acceptance.max_wall_time_increase_ms,
        }
        for field, allowed_increase in cost_fields.items():
            delta = getattr(candidate, field) - getattr(baseline, field)
            if delta > allowed_increase:
                regressions.append(field)
            elif delta < 0:
                improvements.append(field)
        if regressions:
            verdict = TrainingExperimentVerdict.REGRESSED
        elif improvements:
            verdict = TrainingExperimentVerdict.IMPROVED
        else:
            verdict = TrainingExperimentVerdict.EQUIVALENT
        return verdict, tuple(sorted(regressions)), tuple(sorted(improvements))

    @classmethod
    def create(
        cls,
        *,
        plan: TrainingExperimentPlan,
        candidate_checkpoint_hash: str,
        checkpoint_bytes: int,
        baseline: TrainingEvaluationObservation,
        candidate: TrainingEvaluationObservation,
    ) -> "TrainingExperimentReport":
        if not isinstance(plan, TrainingExperimentPlan):
            raise TypeError("plan must be a TrainingExperimentPlan")
        if checkpoint_bytes > plan.max_checkpoint_bytes:
            raise TrainingResearchModelError("candidate checkpoint exceeds frozen plan byte limit")
        verdict, regressions, improvements = cls._classification(
            baseline=baseline,
            candidate=candidate,
            acceptance=plan.acceptance,
        )
        return cls(
            report_id=new_id(IdKind.TRAINING_EXPERIMENT_REPORT),
            plan_id=plan.plan_id,
            plan_hash=plan.content_hash,
            candidate_checkpoint_hash=candidate_checkpoint_hash,
            checkpoint_bytes=checkpoint_bytes,
            evaluator_id=plan.evaluator_id,
            evaluator_version=plan.evaluator_version,
            evaluator_fingerprint=plan.evaluator_fingerprint,
            baseline=baseline,
            candidate=candidate,
            verdict=verdict,
            regression_reasons=regressions,
            improvements=improvements,
        )

    def bind_plan(self, plan: TrainingExperimentPlan) -> None:
        if self.plan_id != plan.plan_id or self.plan_hash != plan.content_hash:
            raise TrainingResearchModelError("training report plan binding drifted")
        if (
            self.evaluator_id != plan.evaluator_id
            or self.evaluator_version != plan.evaluator_version
            or self.evaluator_fingerprint != plan.evaluator_fingerprint
        ):
            raise TrainingResearchModelError("training report evaluator identity drifted")
        if self.checkpoint_bytes > plan.max_checkpoint_bytes:
            raise TrainingResearchModelError("training report checkpoint exceeds plan limit")
        verdict, regressions, improvements = self._classification(
            baseline=self.baseline,
            candidate=self.candidate,
            acceptance=plan.acceptance,
        )
        if (
            self.verdict is not verdict
            or self.regression_reasons != regressions
            or self.improvements != improvements
        ):
            raise TrainingResearchModelError("training report classification is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "candidate_checkpoint_hash": self.candidate_checkpoint_hash,
            "checkpoint_bytes": self.checkpoint_bytes,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "verdict": self.verdict.value,
            "regression_reasons": list(self.regression_reasons),
            "improvements": list(self.improvements),
            "training_loss_is_promotion_evidence": False,
            "production_model_activation_authorized": False,
            "routing_activation_authorized": False,
            "production_task_verified": False,
            "phase26_promotion_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
