from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, new_id, validate_id
from .media_fingerprint_models import MediaFingerprintModelError, WatermarkPlan
from .runtime_observation_models import content_hash, validate_sha256


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")


class WatermarkDetectionStatus(StrEnum):
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    MISMATCH = "MISMATCH"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise MediaFingerprintModelError(f"{label} must be a bounded identity token")
    return value


@dataclass(frozen=True)
class WatermarkResult:
    result_id: str
    plan_id: str
    plan_hash: str
    derivative_hash: str
    detector_id: str
    detector_version: str
    detector_fingerprint: str
    status: WatermarkDetectionStatus
    observed_payload_hash: str | None
    format_validated: bool

    def __post_init__(self) -> None:
        if not validate_id(self.result_id, IdKind.WATERMARK_RESULT):
            raise MediaFingerprintModelError("result_id must be a WMRES ID")
        if not validate_id(self.plan_id, IdKind.WATERMARK_PLAN):
            raise MediaFingerprintModelError("plan_id must be a WMPLAN ID")
        validate_sha256(self.plan_hash, "watermark plan_hash")
        validate_sha256(self.derivative_hash, "watermark derivative_hash")
        object.__setattr__(self, "detector_id", _token(self.detector_id, "detector_id"))
        object.__setattr__(self, "detector_version", _token(self.detector_version, "detector_version"))
        validate_sha256(self.detector_fingerprint, "watermark detector_fingerprint")
        if not isinstance(self.status, WatermarkDetectionStatus):
            raise MediaFingerprintModelError("watermark detection status is invalid")
        if self.observed_payload_hash is not None:
            validate_sha256(self.observed_payload_hash, "observed_payload_hash")
        if type(self.format_validated) is not bool or not self.format_validated:
            raise MediaFingerprintModelError(
                "watermark result requires independently validated derivative format"
            )
        if self.status is WatermarkDetectionStatus.NOT_DETECTED:
            if self.observed_payload_hash is not None:
                raise MediaFingerprintModelError(
                    "NOT_DETECTED watermark result may not contain an observed payload hash"
                )
        elif self.observed_payload_hash is None:
            raise MediaFingerprintModelError(
                "detected/mismatched watermark result requires observed payload hash"
            )

    @classmethod
    def create(
        cls,
        *,
        plan: WatermarkPlan,
        derivative_hash: str,
        observed_payload_hash: str | None,
        format_validated: bool,
    ) -> "WatermarkResult":
        if not isinstance(plan, WatermarkPlan):
            raise TypeError("plan must be a WatermarkPlan")
        if observed_payload_hash is None:
            status = WatermarkDetectionStatus.NOT_DETECTED
        elif observed_payload_hash == plan.payload_hash:
            status = WatermarkDetectionStatus.DETECTED
        else:
            status = WatermarkDetectionStatus.MISMATCH
        return cls(
            result_id=new_id(IdKind.WATERMARK_RESULT),
            plan_id=plan.plan_id,
            plan_hash=plan.content_hash,
            derivative_hash=derivative_hash,
            detector_id=plan.detector_id,
            detector_version=plan.detector_version,
            detector_fingerprint=plan.detector_fingerprint,
            status=status,
            observed_payload_hash=observed_payload_hash,
            format_validated=format_validated,
        )

    def bind_plan(self, plan: WatermarkPlan) -> None:
        if not isinstance(plan, WatermarkPlan):
            raise TypeError("plan must be a WatermarkPlan")
        if self.plan_id != plan.plan_id or self.plan_hash != plan.content_hash:
            raise MediaFingerprintModelError("watermark result does not bind exact plan")
        if (
            self.detector_id != plan.detector_id
            or self.detector_version != plan.detector_version
            or self.detector_fingerprint != plan.detector_fingerprint
        ):
            raise MediaFingerprintModelError("watermark result detector identity drifted")
        if self.status is WatermarkDetectionStatus.DETECTED:
            if self.observed_payload_hash != plan.payload_hash:
                raise MediaFingerprintModelError(
                    "DETECTED watermark result does not match planned payload hash"
                )
        elif self.status is WatermarkDetectionStatus.MISMATCH:
            if self.observed_payload_hash == plan.payload_hash:
                raise MediaFingerprintModelError(
                    "MISMATCH watermark result incorrectly matches planned payload hash"
                )
        elif self.observed_payload_hash is not None:
            raise MediaFingerprintModelError(
                "NOT_DETECTED watermark result contains observed payload evidence"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "result_id": self.result_id,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "derivative_hash": self.derivative_hash,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "detector_fingerprint": self.detector_fingerprint,
            "status": self.status.value,
            "observed_payload_hash": self.observed_payload_hash,
            "format_validated": self.format_validated,
            "authorship_proven": False,
            "cryptographic_provenance_verified": False,
            "parent_lineage_verified": False,
            "canonical_asset_adopted": False,
            "production_task_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
