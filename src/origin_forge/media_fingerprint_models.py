from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import canonical_bytes, content_hash, validate_sha256


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_MAX_SUMMARY_BYTES = 64 * 1024
_MAX_REF_CHARS = 256
_MAX_MARK_PAYLOAD_BYTES = 4096


class MediaFingerprintModelError(ValueError):
    pass


class FingerprintMediaClass(StrEnum):
    SOURCE_TEXT = "SOURCE_TEXT"
    RASTER_IMAGE = "RASTER_IMAGE"
    PCM_AUDIO = "PCM_AUDIO"
    MODEL3D_GLB = "MODEL3D_GLB"


class FingerprintComparisonOutcome(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    DIFFERENT = "DIFFERENT"
    INCOMPARABLE = "INCOMPARABLE"


class WatermarkRobustnessClass(StrEnum):
    FRAGILE_METADATA = "FRAGILE_METADATA"
    FRAGILE_CONTENT = "FRAGILE_CONTENT"
    TRANSFORM_TOLERANT_EXPERIMENTAL = "TRANSFORM_TOLERANT_EXPERIMENTAL"


class WatermarkMutationClass(StrEnum):
    METADATA_ONLY = "METADATA_ONLY"
    CONTENT_MUTATION = "CONTENT_MUTATION"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise MediaFingerprintModelError(f"{label} must be a bounded identity token")
    return value


def _ref(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_REF_CHARS
        or any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in value)
    ):
        raise MediaFingerprintModelError(f"{label} must be a bounded non-whitespace reference")
    return value


def _canonical_summary(value: object) -> str:
    try:
        data = canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise MediaFingerprintModelError("structural summary must be canonical JSON") from exc
    if len(data) > _MAX_SUMMARY_BYTES:
        raise MediaFingerprintModelError("structural summary exceeds byte limit")
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise MediaFingerprintModelError("structural summary canonicalization failed") from exc
    if not isinstance(decoded, dict):
        raise MediaFingerprintModelError("structural summary must be a JSON object")
    return data.decode("utf-8")


@dataclass(frozen=True)
class FingerprintAlgorithm:
    algorithm_id: str
    version: str
    canonicalizer_id: str
    canonicalizer_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm_id", _token(self.algorithm_id, "algorithm_id"))
        object.__setattr__(self, "version", _token(self.version, "algorithm version"))
        object.__setattr__(
            self,
            "canonicalizer_id",
            _token(self.canonicalizer_id, "canonicalizer_id"),
        )
        validate_sha256(self.canonicalizer_fingerprint, "canonicalizer_fingerprint")

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.algorithm_id,
            self.version,
            self.canonicalizer_id,
            self.canonicalizer_fingerprint,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm_id": self.algorithm_id,
            "version": self.version,
            "canonicalizer_id": self.canonicalizer_id,
            "canonicalizer_fingerprint": self.canonicalizer_fingerprint,
        }


@dataclass(frozen=True)
class MediaFingerprint:
    fingerprint_id: str
    media_class: FingerprintMediaClass
    source_ref: str
    source_hash: str
    algorithm: FingerprintAlgorithm
    canonical_content_hash: str
    structural_summary_json: str

    def __post_init__(self) -> None:
        if not validate_id(self.fingerprint_id, IdKind.MEDIA_FINGERPRINT):
            raise MediaFingerprintModelError("fingerprint_id must be an MFPR ID")
        if not isinstance(self.media_class, FingerprintMediaClass):
            raise MediaFingerprintModelError("media_class is invalid")
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))
        validate_sha256(self.source_hash, "source_hash")
        if not isinstance(self.algorithm, FingerprintAlgorithm):
            raise MediaFingerprintModelError("algorithm is invalid")
        validate_sha256(self.canonical_content_hash, "canonical_content_hash")
        try:
            value = json.loads(self.structural_summary_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise MediaFingerprintModelError("structural_summary_json is invalid") from exc
        canonical = _canonical_summary(value)
        if canonical != self.structural_summary_json:
            raise MediaFingerprintModelError("structural_summary_json must be canonical")

    @classmethod
    def create(
        cls,
        *,
        media_class: FingerprintMediaClass,
        source_ref: str,
        source_hash: str,
        algorithm: FingerprintAlgorithm,
        canonical_content_hash: str,
        structural_summary: object,
    ) -> "MediaFingerprint":
        return cls(
            fingerprint_id=new_id(IdKind.MEDIA_FINGERPRINT),
            media_class=media_class,
            source_ref=source_ref,
            source_hash=source_hash,
            algorithm=algorithm,
            canonical_content_hash=canonical_content_hash,
            structural_summary_json=_canonical_summary(structural_summary),
        )

    @property
    def structural_summary(self) -> dict[str, object]:
        value = json.loads(self.structural_summary_json)
        assert isinstance(value, dict)
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "fingerprint_id": self.fingerprint_id,
            "media_class": self.media_class.value,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "algorithm": self.algorithm.to_dict(),
            "canonical_content_hash": self.canonical_content_hash,
            "structural_summary": self.structural_summary,
            "cryptographic_provenance_verified": False,
            "production_task_verified": False,
            "canonical_asset_adopted": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class FingerprintComparison:
    comparison_id: str
    left_fingerprint_id: str
    left_fingerprint_hash: str
    right_fingerprint_id: str
    right_fingerprint_hash: str
    outcome: FingerprintComparisonOutcome
    comparable_algorithm: bool

    def __post_init__(self) -> None:
        if not validate_id(self.comparison_id, IdKind.FINGERPRINT_COMPARISON):
            raise MediaFingerprintModelError("comparison_id must be an FPCMP ID")
        if not validate_id(self.left_fingerprint_id, IdKind.MEDIA_FINGERPRINT):
            raise MediaFingerprintModelError("left_fingerprint_id is invalid")
        if not validate_id(self.right_fingerprint_id, IdKind.MEDIA_FINGERPRINT):
            raise MediaFingerprintModelError("right_fingerprint_id is invalid")
        validate_sha256(self.left_fingerprint_hash, "left_fingerprint_hash")
        validate_sha256(self.right_fingerprint_hash, "right_fingerprint_hash")
        if not isinstance(self.outcome, FingerprintComparisonOutcome):
            raise MediaFingerprintModelError("comparison outcome is invalid")
        if type(self.comparable_algorithm) is not bool:
            raise MediaFingerprintModelError("comparable_algorithm must be bool")
        if not self.comparable_algorithm and self.outcome is not FingerprintComparisonOutcome.INCOMPARABLE:
            raise MediaFingerprintModelError("incomparable algorithms require INCOMPARABLE outcome")
        if self.comparable_algorithm and self.outcome is FingerprintComparisonOutcome.INCOMPARABLE:
            raise MediaFingerprintModelError("comparable algorithms may not use INCOMPARABLE outcome")

    @classmethod
    def compare(
        cls,
        left: MediaFingerprint,
        right: MediaFingerprint,
    ) -> "FingerprintComparison":
        if not isinstance(left, MediaFingerprint) or not isinstance(right, MediaFingerprint):
            raise TypeError("left/right must be MediaFingerprint values")
        comparable = (
            left.media_class is right.media_class
            and left.algorithm.identity == right.algorithm.identity
        )
        if not comparable:
            outcome = FingerprintComparisonOutcome.INCOMPARABLE
        elif left.canonical_content_hash == right.canonical_content_hash:
            outcome = FingerprintComparisonOutcome.EXACT_MATCH
        else:
            outcome = FingerprintComparisonOutcome.DIFFERENT
        return cls(
            comparison_id=new_id(IdKind.FINGERPRINT_COMPARISON),
            left_fingerprint_id=left.fingerprint_id,
            left_fingerprint_hash=left.content_hash,
            right_fingerprint_id=right.fingerprint_id,
            right_fingerprint_hash=right.content_hash,
            outcome=outcome,
            comparable_algorithm=comparable,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "left_fingerprint_id": self.left_fingerprint_id,
            "left_fingerprint_hash": self.left_fingerprint_hash,
            "right_fingerprint_id": self.right_fingerprint_id,
            "right_fingerprint_hash": self.right_fingerprint_hash,
            "outcome": self.outcome.value,
            "comparable_algorithm": self.comparable_algorithm,
            "authorship_proven": False,
            "cryptographic_provenance_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class WatermarkPlan:
    plan_id: str
    media_class: FingerprintMediaClass
    parent_ref: str
    parent_hash: str
    payload_hash: str
    embedder_id: str
    embedder_version: str
    embedder_fingerprint: str
    detector_id: str
    detector_version: str
    detector_fingerprint: str
    robustness_class: WatermarkRobustnessClass
    mutation_class: WatermarkMutationClass

    def __post_init__(self) -> None:
        if not validate_id(self.plan_id, IdKind.WATERMARK_PLAN):
            raise MediaFingerprintModelError("plan_id must be a WMPLAN ID")
        if not isinstance(self.media_class, FingerprintMediaClass):
            raise MediaFingerprintModelError("watermark media_class is invalid")
        object.__setattr__(self, "parent_ref", _ref(self.parent_ref, "parent_ref"))
        validate_sha256(self.parent_hash, "parent_hash")
        validate_sha256(self.payload_hash, "payload_hash")
        for field in ("embedder_id", "embedder_version", "detector_id", "detector_version"):
            object.__setattr__(self, field, _token(getattr(self, field), field))
        validate_sha256(self.embedder_fingerprint, "embedder_fingerprint")
        validate_sha256(self.detector_fingerprint, "detector_fingerprint")
        if not isinstance(self.robustness_class, WatermarkRobustnessClass):
            raise MediaFingerprintModelError("watermark robustness_class is invalid")
        if not isinstance(self.mutation_class, WatermarkMutationClass):
            raise MediaFingerprintModelError("watermark mutation_class is invalid")

    @classmethod
    def create(
        cls,
        *,
        media_class: FingerprintMediaClass,
        parent_ref: str,
        parent_hash: str,
        mark_payload: bytes,
        embedder_id: str,
        embedder_version: str,
        embedder_fingerprint: str,
        detector_id: str,
        detector_version: str,
        detector_fingerprint: str,
        robustness_class: WatermarkRobustnessClass,
        mutation_class: WatermarkMutationClass,
    ) -> "WatermarkPlan":
        if not isinstance(mark_payload, bytes) or not mark_payload or len(mark_payload) > _MAX_MARK_PAYLOAD_BYTES:
            raise MediaFingerprintModelError("mark_payload must be bounded non-empty bytes")
        return cls(
            plan_id=new_id(IdKind.WATERMARK_PLAN),
            media_class=media_class,
            parent_ref=parent_ref,
            parent_hash=parent_hash,
            payload_hash="sha256:" + __import__("hashlib").sha256(mark_payload).hexdigest(),
            embedder_id=embedder_id,
            embedder_version=embedder_version,
            embedder_fingerprint=embedder_fingerprint,
            detector_id=detector_id,
            detector_version=detector_version,
            detector_fingerprint=detector_fingerprint,
            robustness_class=robustness_class,
            mutation_class=mutation_class,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "media_class": self.media_class.value,
            "parent_ref": self.parent_ref,
            "parent_hash": self.parent_hash,
            "payload_hash": self.payload_hash,
            "embedder_id": self.embedder_id,
            "embedder_version": self.embedder_version,
            "embedder_fingerprint": self.embedder_fingerprint,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "detector_fingerprint": self.detector_fingerprint,
            "robustness_class": self.robustness_class.value,
            "mutation_class": self.mutation_class.value,
            "robust_provenance_claim": False,
            "canonical_asset_mutation_authorized": False,
            "production_task_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
