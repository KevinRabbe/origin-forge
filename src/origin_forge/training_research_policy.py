from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .ids import IdKind, new_id
from .runtime_observation_models import content_hash, validate_sha256
from .training_research_models import (
    TrainingEligibilityAudit,
    TrainingEvidenceRef,
    TrainingResearchModelError,
    TrainingTrajectory,
    TrainingTrajectoryOutcome,
    _canonical_example,
    _text,
    _token,
)


RUNTIME_REDACTED_PRODUCER_ID = "origin-forge-runtime-redacted"
RUNTIME_REDACTED_PRODUCER_VERSION = "1"
RUNTIME_REDACTED_PRODUCER_FINGERPRINT = content_hash(
    {
        "producer_id": RUNTIME_REDACTED_PRODUCER_ID,
        "version": RUNTIME_REDACTED_PRODUCER_VERSION,
        "source": "OriginForgeRuntime terminal Task/Run/Verification projection",
        "task_fields": ["id", "flow_id", "status", "revision", "attempt_count"],
        "run_fields": [
            "id",
            "task_id",
            "role",
            "model_profile",
            "model_hash",
            "status",
            "input_token_count",
            "output_token_count",
        ],
        "verification_fields": [
            "id",
            "target_type",
            "target_id",
            "verification_type",
            "verifier",
            "status",
            "run_id",
        ],
        "task_text_disclosed": False,
        "verification_payload_disclosed": False,
        "repository_content_disclosed": False,
        "accepted_task_status": "SUCCEEDED",
        "accepted_run_status": "SUCCEEDED",
        "required_verification": "TASK PASS bound to exact run",
    }
)

V1_ELIGIBILITY_POLICY_ID = "verified-runtime-redacted-v1"
V1_ELIGIBILITY_POLICY_VERSION = "1"
V1_ELIGIBILITY_POLICY_FINGERPRINT = content_hash(
    {
        "policy_id": V1_ELIGIBILITY_POLICY_ID,
        "version": V1_ELIGIBILITY_POLICY_VERSION,
        "trusted_producers": [
            {
                "id": RUNTIME_REDACTED_PRODUCER_ID,
                "version": RUNTIME_REDACTED_PRODUCER_VERSION,
                "fingerprint": RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
            }
        ],
        "protected_evidence": "ineligible",
        "production_training_authority": False,
    }
)


def _trusted_producer_tuple(trajectory: "GovernedTrainingTrajectory") -> tuple[str, str, str]:
    return (
        trajectory.producer_id,
        trajectory.producer_version,
        trajectory.producer_fingerprint,
    )


def is_v1_trusted_trajectory(trajectory: TrainingTrajectory) -> bool:
    return isinstance(trajectory, GovernedTrainingTrajectory) and _trusted_producer_tuple(trajectory) == (
        RUNTIME_REDACTED_PRODUCER_ID,
        RUNTIME_REDACTED_PRODUCER_VERSION,
        RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
    )


@dataclass(frozen=True)
class GovernedTrainingTrajectory(TrainingTrajectory):
    producer_id: str
    producer_version: str
    producer_fingerprint: str

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "producer_id", _token(self.producer_id, "trajectory producer_id"))
        object.__setattr__(
            self,
            "producer_version",
            _token(self.producer_version, "trajectory producer_version"),
        )
        validate_sha256(self.producer_fingerprint, "trajectory producer_fingerprint")

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
        producer_id: str,
        producer_version: str,
        producer_fingerprint: str,
        model_profile: str | None = None,
        model_hash: str | None = None,
    ) -> "GovernedTrainingTrajectory":
        return cls(
            trajectory_id=new_id(IdKind.TRAINING_TRAJECTORY),
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            leakage_group_hash=leakage_group_hash,
            outcome=outcome,
            objective=_text(objective, "trajectory objective"),
            model_profile=model_profile,
            model_hash=model_hash,
            example_json=_canonical_example(dict(example)),
            source_refs=tuple(source_refs),
            producer_id=producer_id,
            producer_version=producer_version,
            producer_fingerprint=producer_fingerprint,
        )

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload["producer"] = {
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "producer_fingerprint": self.producer_fingerprint,
        }
        return payload


@dataclass(frozen=True)
class GovernedTrainingEligibilityAudit(TrainingEligibilityAudit):
    trusted_producer_id: str
    trusted_producer_version: str
    trusted_producer_fingerprint: str

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "trusted_producer_id",
            _token(self.trusted_producer_id, "trusted_producer_id"),
        )
        object.__setattr__(
            self,
            "trusted_producer_version",
            _token(self.trusted_producer_version, "trusted_producer_version"),
        )
        validate_sha256(self.trusted_producer_fingerprint, "trusted_producer_fingerprint")

    @staticmethod
    def _reasons(trajectory: TrainingTrajectory) -> tuple[str, ...]:
        reasons = set(TrainingEligibilityAudit._reasons(trajectory))
        if not is_v1_trusted_trajectory(trajectory):
            reasons.add("untrusted-producer")
        return tuple(sorted(reasons))

    @classmethod
    def create(cls, *, trajectory: TrainingTrajectory) -> "GovernedTrainingEligibilityAudit":
        if not isinstance(trajectory, TrainingTrajectory):
            raise TypeError("trajectory must be a TrainingTrajectory")
        reasons = cls._reasons(trajectory)
        return cls(
            audit_id=new_id(IdKind.TRAINING_ELIGIBILITY_AUDIT),
            trajectory_id=trajectory.trajectory_id,
            trajectory_hash=trajectory.content_hash,
            policy_id=V1_ELIGIBILITY_POLICY_ID,
            policy_version=V1_ELIGIBILITY_POLICY_VERSION,
            policy_fingerprint=V1_ELIGIBILITY_POLICY_FINGERPRINT,
            eligible=not reasons,
            reasons=reasons,
            trusted_producer_id=RUNTIME_REDACTED_PRODUCER_ID,
            trusted_producer_version=RUNTIME_REDACTED_PRODUCER_VERSION,
            trusted_producer_fingerprint=RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
        )

    def bind(self, trajectory: TrainingTrajectory) -> None:
        super().bind(trajectory)
        expected = (
            RUNTIME_REDACTED_PRODUCER_ID,
            RUNTIME_REDACTED_PRODUCER_VERSION,
            RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
        )
        actual = (
            self.trusted_producer_id,
            self.trusted_producer_version,
            self.trusted_producer_fingerprint,
        )
        if actual != expected:
            raise TrainingResearchModelError("eligibility audit trusted-producer policy drifted")
        if self.policy_id != V1_ELIGIBILITY_POLICY_ID or self.policy_version != V1_ELIGIBILITY_POLICY_VERSION:
            raise TrainingResearchModelError("eligibility audit policy identity drifted")
        if self.policy_fingerprint != V1_ELIGIBILITY_POLICY_FINGERPRINT:
            raise TrainingResearchModelError("eligibility audit policy fingerprint drifted")

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload["trusted_producer"] = {
            "producer_id": self.trusted_producer_id,
            "producer_version": self.trusted_producer_version,
            "producer_fingerprint": self.trusted_producer_fingerprint,
        }
        return payload
