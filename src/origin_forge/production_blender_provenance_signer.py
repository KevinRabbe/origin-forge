from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .blockbench_glb import GlbError, inspect_glb
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .production_blender_adoption_receipt import (
    BlenderProductionAdoptionStatus,
    read_blender_production_adoption_receipt,
)
from .production_blender_dispatch_output_binding import (
    read_blender_dispatch_output_binding,
)
from .production_blender_task_acceptance import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
    read_blender_production_task_acceptance,
)
from .production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
    inspect_blender_production_task_acceptance_currentness_readonly,
)
from .provenance_crypto import SecretContainmentError, SignatureBackendError
from .provenance_service import ProvenanceService, ProvenanceServiceError
from .runtime import OriginForgeRuntime


class BlenderProductionProvenanceSigningFailureCode(StrEnum):
    INVALID_EXECUTION_ID = "INVALID_EXECUTION_ID"
    TASK_NOT_TERMINALLY_ACCEPTED = "TASK_NOT_TERMINALLY_ACCEPTED"
    ADOPTED_ARTIFACT_DRIFT = "ADOPTED_ARTIFACT_DRIFT"
    PROVENANCE_TRUST_NOT_READY = "PROVENANCE_TRUST_NOT_READY"
    SIGNING_REJECTED = "SIGNING_REJECTED"
    SIGNED_MANIFEST_CONFLICT = "SIGNED_MANIFEST_CONFLICT"
    SIGNED_MANIFEST_NOT_CURRENT = "SIGNED_MANIFEST_NOT_CURRENT"


class BlenderProductionProvenanceSigningError(RuntimeError):
    def __init__(
        self,
        code: BlenderProductionProvenanceSigningFailureCode,
        detail: str,
    ) -> None:
        self.code = code
        super().__init__(detail)


class BlenderProductionProvenanceSigningBlocked(
    BlenderProductionProvenanceSigningError
):
    pass


@dataclass(frozen=True)
class GovernedBlenderProductionProvenanceResult:
    execution_id: str
    task_id: str
    adopted_artifact_id: str
    adopted_destination_path: str
    accepted_content_hash: str
    accepted_byte_count: int
    acceptance_verification_id: str
    manifest_id: str
    manifest_content_hash: str
    signing_certificate_id: str
    signing_key_id: str
    signature_hash: str
    trusted: bool
    current: bool
    artifact_status_changed: bool = False
    task_status_changed: bool = False
    production_verification_changed: bool = False
    release_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "adopted_destination_path": self.adopted_destination_path,
            "accepted_content_hash": self.accepted_content_hash,
            "accepted_byte_count": self.accepted_byte_count,
            "acceptance_verification_id": self.acceptance_verification_id,
            "manifest_id": self.manifest_id,
            "manifest_content_hash": self.manifest_content_hash,
            "signing_certificate_id": self.signing_certificate_id,
            "signing_key_id": self.signing_key_id,
            "signature_hash": self.signature_hash,
            "trusted": self.trusted,
            "current": self.current,
            "artifact_status_changed": self.artifact_status_changed,
            "task_status_changed": self.task_status_changed,
            "production_verification_changed": self.production_verification_changed,
            "release_authorized": self.release_authorized,
        }


def _production_snapshot(
    runtime: OriginForgeRuntime,
    *,
    task_id: str,
    artifact_id: str,
) -> tuple[dict[str, object], dict[str, object], tuple[tuple[object, ...], ...]]:
    task = dict(runtime.get_task(task_id))
    artifact = dict(OriginForgeLineage(runtime).get_artifact(artifact_id))
    with runtime.store.session() as conn:
        rows = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT id, target_type, target_id, verification_type, verifier,
                          status, run_id, evidence_json, metrics_json, created_at
                   FROM verifications
                   WHERE (target_type = 'TASK' AND target_id = ?)
                      OR (target_type = 'ARTIFACT' AND target_id = ?)
                   ORDER BY id""",
                (task_id, artifact_id),
            )
        )
    return task, artifact, rows


def _require_current_adopted_glb(
    runtime: OriginForgeRuntime,
    *,
    destination_path: str,
    accepted_content_hash: str,
    accepted_byte_count: int,
) -> None:
    relative = Path(destination_path)
    current = runtime.project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
                "canonical adopted Blender Artifact is not current",
            )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(runtime.project_root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        ) from exc
    if not resolved.is_file():
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        )
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        ) from exc
    actual_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    if len(data) != accepted_byte_count or actual_hash != accepted_content_hash:
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        )
    try:
        inspection = inspect_glb(data)
    except GlbError as exc:
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        ) from exc
    if (
        inspection.byte_count != accepted_byte_count
        or inspection.content_hash != accepted_content_hash
    ):
        raise BlenderProductionProvenanceSigningBlocked(
            BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
            "canonical adopted Blender Artifact is not current",
        )


class GovernedBlenderProductionProvenanceSigner:
    """Sign one terminally accepted Blender production Artifact without production authority."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        provenance_service: ProvenanceService | None = None,
    ) -> None:
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.provenance_service = provenance_service or ProvenanceService(runtime)
        if not isinstance(self.provenance_service, ProvenanceService):
            raise TypeError("provenance_service must be a ProvenanceService")
        if self.provenance_service.runtime.project_root != runtime.project_root:
            raise ValueError("provenance service and runtime must belong to the same project")

    def sign(
        self,
        execution_id: str,
        certificate_id: str,
        *,
        operational_private_key_handle: Path,
    ) -> GovernedBlenderProductionProvenanceResult:
        if not isinstance(execution_id, str) or not validate_id(
            execution_id, IdKind.DISPATCH_EXECUTION
        ):
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.INVALID_EXECUTION_ID,
                "execution_id must be a DISPEXEC ID",
            )
        if not isinstance(certificate_id, str) or not validate_id(
            certificate_id, IdKind.KEY_CERTIFICATE
        ):
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.PROVENANCE_TRUST_NOT_READY,
                "certificate_id must be a KEYCERT ID",
            )
        if not isinstance(operational_private_key_handle, Path):
            raise TypeError("operational_private_key_handle must be a Path")

        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            self.runtime,
            execution_id,
        )
        if (
            currentness.status
            is not BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
            or currentness.task_id is None
            or currentness.adopted_artifact_id is None
            or currentness.task_verification_id is None
            or currentness.task_revision is None
        ):
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.TASK_NOT_TERMINALLY_ACCEPTED,
                "Blender production execution is not terminally accepted",
            )

        try:
            binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
            adoption = read_blender_production_adoption_receipt(self.runtime, execution_id)
            acceptance = read_blender_production_task_acceptance(self.runtime, execution_id)
            artifact = OriginForgeLineage(self.runtime).get_artifact(
                currentness.adopted_artifact_id
            )
        except Exception as exc:
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
                "canonical Blender production relation cannot be resolved",
            ) from exc

        expected_hash = "sha256:" + binding.output_content_hash
        if (
            adoption.status is not BlenderProductionAdoptionStatus.PUBLISHED
            or adoption.adopted_artifact_id != currentness.adopted_artifact_id
            or acceptance.execution_id != execution_id
            or acceptance.task_id != binding.task_id
            or acceptance.task_id != currentness.task_id
            or acceptance.adopted_artifact_id != currentness.adopted_artifact_id
            or acceptance.adoption_verification_id != adoption.verification_id
            or acceptance.task_verification_id != currentness.task_verification_id
            or acceptance.acceptance_authority
            != BLENDER_PRODUCTION_TASK_ACCEPTANCE_AUTHORITY
            or acceptance.accepted_destination_path != adoption.destination_path
            or acceptance.accepted_content_hash != expected_hash
            or acceptance.accepted_byte_count != binding.output_byte_count
            or artifact["id"] != currentness.adopted_artifact_id
            or artifact["type"] != "BLENDER_GLB_EXPORT"
            or artifact["status"] != "ADOPTED"
            or artifact["parent_artifact_id"] != binding.output_artifact_id
            or artifact["created_by_run_id"] != binding.run_id
            or artifact["path_or_uri"] != adoption.destination_path
            or artifact["content_hash"] != acceptance.accepted_content_hash
        ):
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
                "canonical Blender production relation is not exact",
            )

        _require_current_adopted_glb(
            self.runtime,
            destination_path=acceptance.accepted_destination_path,
            accepted_content_hash=acceptance.accepted_content_hash,
            accepted_byte_count=acceptance.accepted_byte_count,
        )

        before = _production_snapshot(
            self.runtime,
            task_id=binding.task_id,
            artifact_id=acceptance.adopted_artifact_id,
        )
        try:
            certificate = self.provenance_service.store.load_certificate(certificate_id)
        except Exception as exc:
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.PROVENANCE_TRUST_NOT_READY,
                "Phase-18 provenance trust is not ready for this certificate",
            ) from exc

        try:
            signed = self.provenance_service.sign_artifact(
                acceptance.adopted_artifact_id,
                certificate_id,
                operational_private_key_handle=operational_private_key_handle,
                parent_manifest_ids=(),
            )
        except ProvenanceServiceError as exc:
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.SIGNING_REJECTED,
                "Phase-18 provenance signing was rejected",
            ) from exc
        except (SecretContainmentError, SignatureBackendError) as exc:
            raise BlenderProductionProvenanceSigningBlocked(
                BlenderProductionProvenanceSigningFailureCode.SIGNING_REJECTED,
                "Phase-18 provenance signing was rejected",
            ) from exc

        manifest = signed.manifest
        verification_ids = {ref.record_id for ref in manifest.verification_refs}
        if (
            manifest.artifact_ref.record_id != acceptance.adopted_artifact_id
            or manifest.artifact_content_hash != acceptance.accepted_content_hash
            or manifest.artifact_type != "BLENDER_GLB_EXPORT"
            or manifest.artifact_location != acceptance.accepted_destination_path
            or manifest.task_ref is None
            or manifest.task_ref.record_id != binding.task_id
            or manifest.run_ref is None
            or manifest.run_ref.record_id != binding.run_id
            or adoption.verification_id not in verification_ids
            or acceptance.task_verification_id not in verification_ids
            or manifest.parent_manifest_refs
            or signed.signing_certificate_hash != certificate.content_hash
            or signed.signing_key_id != certificate.certificate.key_id
        ):
            raise BlenderProductionProvenanceSigningError(
                BlenderProductionProvenanceSigningFailureCode.SIGNED_MANIFEST_CONFLICT,
                "new signed provenance manifest does not bind the exact Blender production relation",
            )

        inspection = self.provenance_service.verify_manifest(manifest.manifest_id)
        if not inspection.trusted_and_current:
            raise BlenderProductionProvenanceSigningError(
                BlenderProductionProvenanceSigningFailureCode.SIGNED_MANIFEST_NOT_CURRENT,
                "new signed provenance manifest is not trusted and current",
            )

        after = _production_snapshot(
            self.runtime,
            task_id=binding.task_id,
            artifact_id=acceptance.adopted_artifact_id,
        )
        if after != before:
            raise BlenderProductionProvenanceSigningError(
                BlenderProductionProvenanceSigningFailureCode.SIGNED_MANIFEST_CONFLICT,
                "provenance signing changed governed production state",
            )

        return GovernedBlenderProductionProvenanceResult(
            execution_id=execution_id,
            task_id=binding.task_id,
            adopted_artifact_id=acceptance.adopted_artifact_id,
            adopted_destination_path=acceptance.accepted_destination_path,
            accepted_content_hash=acceptance.accepted_content_hash,
            accepted_byte_count=acceptance.accepted_byte_count,
            acceptance_verification_id=acceptance.task_verification_id,
            manifest_id=manifest.manifest_id,
            manifest_content_hash=manifest.content_hash,
            signing_certificate_id=certificate_id,
            signing_key_id=signed.signing_key_id,
            signature_hash=signed.signature.signature_hash,
            trusted=inspection.cryptographic.trusted,
            current=inspection.freshness.current,
        )
