from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .media_fingerprint_models import MediaFingerprint, MediaFingerprintModelError
from .provenance_models import ProvenanceManifest, ProvenanceRecordType
from .runtime_observation_models import content_hash, validate_sha256


@dataclass(frozen=True)
class FingerprintProvenanceLink:
    link_id: str
    fingerprint_id: str
    fingerprint_hash: str
    manifest_id: str
    manifest_hash: str
    artifact_id: str
    artifact_record_hash: str
    artifact_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.link_id, IdKind.FINGERPRINT_PROVENANCE_LINK):
            raise MediaFingerprintModelError("link_id must be an FPLINK ID")
        if not validate_id(self.fingerprint_id, IdKind.MEDIA_FINGERPRINT):
            raise MediaFingerprintModelError("fingerprint_id must be an MFPR ID")
        validate_sha256(self.fingerprint_hash, "fingerprint_hash")
        if not validate_id(self.manifest_id, IdKind.PROVENANCE_MANIFEST):
            raise MediaFingerprintModelError("manifest_id must be a PROV ID")
        validate_sha256(self.manifest_hash, "manifest_hash")
        if not validate_id(self.artifact_id, IdKind.ARTIFACT):
            raise MediaFingerprintModelError("artifact_id must be an ART ID")
        validate_sha256(self.artifact_record_hash, "artifact_record_hash")
        validate_sha256(self.artifact_content_hash, "artifact_content_hash")

    @classmethod
    def create(
        cls,
        *,
        fingerprint: MediaFingerprint,
        manifest: ProvenanceManifest,
    ) -> "FingerprintProvenanceLink":
        if not isinstance(fingerprint, MediaFingerprint):
            raise TypeError("fingerprint must be a MediaFingerprint")
        if not isinstance(manifest, ProvenanceManifest):
            raise TypeError("manifest must be a ProvenanceManifest")
        if manifest.artifact_ref.record_type is not ProvenanceRecordType.ARTIFACT:
            raise MediaFingerprintModelError("Phase-18 manifest artifact_ref must target ARTIFACT")
        if fingerprint.source_ref != manifest.artifact_ref.record_id:
            raise MediaFingerprintModelError(
                "fingerprint source_ref does not match Phase-18 manifest artifact ID"
            )
        if fingerprint.source_hash != manifest.artifact_content_hash:
            raise MediaFingerprintModelError(
                "fingerprint source_hash does not match Phase-18 artifact content hash"
            )
        return cls(
            link_id=new_id(IdKind.FINGERPRINT_PROVENANCE_LINK),
            fingerprint_id=fingerprint.fingerprint_id,
            fingerprint_hash=fingerprint.content_hash,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.content_hash,
            artifact_id=manifest.artifact_ref.record_id,
            artifact_record_hash=manifest.artifact_ref.record_hash,
            artifact_content_hash=manifest.artifact_content_hash,
        )

    def bind(self, fingerprint: MediaFingerprint, manifest: ProvenanceManifest) -> None:
        if self.fingerprint_id != fingerprint.fingerprint_id or self.fingerprint_hash != fingerprint.content_hash:
            raise MediaFingerprintModelError("provenance link fingerprint binding drifted")
        if self.manifest_id != manifest.manifest_id or self.manifest_hash != manifest.content_hash:
            raise MediaFingerprintModelError("provenance link manifest binding drifted")
        if (
            self.artifact_id != manifest.artifact_ref.record_id
            or self.artifact_record_hash != manifest.artifact_ref.record_hash
            or self.artifact_content_hash != manifest.artifact_content_hash
        ):
            raise MediaFingerprintModelError("provenance link Artifact binding drifted")

    def to_dict(self) -> dict[str, object]:
        return {
            "link_id": self.link_id,
            "fingerprint_id": self.fingerprint_id,
            "fingerprint_hash": self.fingerprint_hash,
            "manifest_id": self.manifest_id,
            "manifest_hash": self.manifest_hash,
            "artifact_id": self.artifact_id,
            "artifact_record_hash": self.artifact_record_hash,
            "artifact_content_hash": self.artifact_content_hash,
            "phase18_manifest_bound": True,
            "phase18_signature_verified": False,
            "cryptographic_provenance_verified": False,
            "authorship_proven": False,
            "production_task_verified": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
