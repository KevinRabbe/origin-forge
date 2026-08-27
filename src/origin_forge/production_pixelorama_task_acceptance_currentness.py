from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .pixelorama_png import PngError, inspect_rgba8_png
from .production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
)
from .production_pixelorama_adoption_receipt import (
    PRODUCTION_ADOPTION_VERIFICATION_TYPE,
    PRODUCTION_ADOPTION_VERIFIER,
    PixeloramaProductionAdoptionReceipt,
    PixeloramaProductionAdoptionStatus,
    read_pixelorama_production_adoption_receipt,
)
from .production_pixelorama_dispatch_output_binding_models import (
    PixeloramaDispatchOutputBinding,
)
from .production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from .production_pixelorama_dispatch_output_currentness import (
    PixeloramaDispatchOutputCurrentnessStatus,
    inspect_pixelorama_dispatch_output_currentness_readonly,
)
from .production_pixelorama_task_acceptance import (
    PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
    PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION,
    PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    PRODUCTION_TASK_ACCEPTANCE_VERIFIER,
    PixeloramaProductionTaskAcceptanceError,
    PixeloramaProductionTaskAcceptanceReceipt,
    read_pixelorama_production_task_acceptance,
)
from .runtime import OriginForgeRuntime
from .state import TaskStatus


class PixeloramaProductionTaskAcceptanceCurrentnessStatus(StrEnum):
    NOT_ACCEPTED = "NOT_ACCEPTED"
    ACCEPTED_PENDING_TASK_TRANSITION = "ACCEPTED_PENDING_TASK_TRANSITION"
    ACCEPTED_TASK_SUCCEEDED = "ACCEPTED_TASK_SUCCEEDED"
    STALE_OR_CONFLICTING = "STALE_OR_CONFLICTING"


@dataclass(frozen=True)
class PixeloramaProductionTaskAcceptanceCurrentness:
    execution_id: str
    task_id: str | None
    adopted_artifact_id: str | None
    task_verification_id: str | None
    task_revision: int | None
    status: PixeloramaProductionTaskAcceptanceCurrentnessStatus
    detail: str | None = None

    @property
    def acceptance_eligible(self) -> bool:
        return self.status in {
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
        }

    @property
    def accepted(self) -> bool:
        return self.status in {
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "task_verification_id": self.task_verification_id,
            "task_revision": self.task_revision,
            "status": self.status.value,
            "acceptance_eligible": self.acceptance_eligible,
            "accepted": self.accepted,
            "detail": self.detail,
        }


def _json_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} JSON is not text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} JSON is invalid") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{label} JSON is not an object")
    return decoded


def _expected_adoption_evidence(
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
) -> dict[str, object]:
    content_hash = "sha256:" + binding.output_content_hash
    return {
        "source_artifact_id": binding.output_artifact_id,
        "source_content_hash": content_hash,
        "source_byte_count": binding.output_byte_count,
        "destination_path": adoption.destination_path,
        "destination_content_hash": content_hash,
        "existing_asset_overwritten": False,
        "production_task_verified": False,
        "production_dispatch_output_bound": True,
        "dispatch_execution_id": binding.execution_id,
        "dispatch_claim_id": binding.claim_id,
        "production_run_id": binding.run_id,
        "semantic_visual_quality_verified": False,
        "provenance_signed": False,
    }


def _require_historical_adoption_relation(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
) -> None:
    if (
        adoption.status is not PixeloramaProductionAdoptionStatus.PUBLISHED
        or adoption.execution_id != binding.execution_id
        or adoption.output_artifact_id != binding.output_artifact_id
        or adoption.adopted_artifact_id is None
        or adoption.verification_id is None
    ):
        raise RuntimeError("Phase-49 production adoption is not one exact PUBLISHED relation")

    lineage = OriginForgeLineage(runtime)
    try:
        artifact = lineage.get_artifact(adoption.adopted_artifact_id)
    except (KeyError, RuntimeError) as exc:
        raise RuntimeError("adopted production Artifact cannot be read canonically") from exc
    expected_hash = "sha256:" + binding.output_content_hash
    if (
        artifact["type"] != "SPRITESHEET_EXPORT"
        or artifact["status"] != "ADOPTED"
        or artifact["parent_artifact_id"] != binding.output_artifact_id
        or artifact["created_by_run_id"] != binding.run_id
        or artifact["path_or_uri"] != adoption.destination_path
        or artifact["content_hash"] != expected_hash
    ):
        raise RuntimeError("adopted production Artifact drifted from Phase-49 relation")

    matches = [
        item
        for item in lineage.list_artifact_verifications(adoption.adopted_artifact_id)
        if item["id"] == adoption.verification_id
    ]
    if len(matches) != 1:
        raise RuntimeError("Phase-49 production adoption Verification is missing or ambiguous")
    verification = matches[0]
    evidence = _json_object(
        verification["evidence_json"],
        "Phase-49 production adoption Verification evidence",
    )
    if (
        verification["target_type"] != "ARTIFACT"
        or verification["target_id"] != adoption.adopted_artifact_id
        or verification["verification_type"] != PRODUCTION_ADOPTION_VERIFICATION_TYPE
        or verification["verifier"] != PRODUCTION_ADOPTION_VERIFIER
        or verification["status"] != "PASS"
        or verification["run_id"] != binding.run_id
        or evidence != _expected_adoption_evidence(binding, adoption)
    ):
        raise RuntimeError("Phase-49 production adoption Verification drifted")


def _require_current_adopted_bytes(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
) -> None:
    relative = Path(adoption.destination_path)
    current = runtime.project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("canonical adopted destination contains a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(runtime.project_root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError("canonical adopted destination escaped the project root") from exc
    if not resolved.is_file():
        raise RuntimeError("canonical adopted destination is not a regular file")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise RuntimeError("canonical adopted destination bytes cannot be read") from exc
    expected_hash = "sha256:" + binding.output_content_hash
    if (
        len(data) != binding.output_byte_count
        or "sha256:" + hashlib.sha256(data).hexdigest() != expected_hash
    ):
        raise RuntimeError("canonical adopted destination bytes drifted")
    try:
        inspection = inspect_rgba8_png(data)
    except PngError as exc:
        raise RuntimeError("canonical adopted destination failed RGBA8 PNG validation") from exc
    if inspection.byte_count != binding.output_byte_count:
        raise RuntimeError("canonical adopted destination PNG byte count drifted")


def _expected_acceptance_evidence(
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
) -> dict[str, object]:
    return {
        "production_task_verified": True,
        "semantic_visual_quality_verified": True,
        "acceptance_authority": PRODUCTION_TASK_ACCEPTANCE_AUTHORITY,
        "production_dispatch_output_bound": True,
        "canonical_asset_adopted": True,
        "existing_asset_overwritten": False,
        "provenance_signed": False,
        "release_authorized": False,
        "dispatch_execution_id": binding.execution_id,
        "production_claim_id": binding.claim_id,
        "production_run_id": binding.run_id,
        "source_output_artifact_id": binding.output_artifact_id,
        "production_adoption_verification_id": adoption.verification_id,
        "adopted_artifact_id": adoption.adopted_artifact_id,
        "adopted_destination_path": adoption.destination_path,
        "accepted_content_hash": "sha256:" + binding.output_content_hash,
        "accepted_byte_count": binding.output_byte_count,
        "task_content_hash": binding.task_content_hash,
        "task_revision_at_acceptance": receipt.task_revision_at_acceptance,
    }


def _require_exact_acceptance_relation(
    runtime: OriginForgeRuntime,
    binding: PixeloramaDispatchOutputBinding,
    adoption: PixeloramaProductionAdoptionReceipt,
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
) -> None:
    if (
        receipt.execution_id != binding.execution_id
        or receipt.task_id != binding.task_id
        or receipt.adopted_artifact_id != adoption.adopted_artifact_id
        or receipt.adoption_verification_id != adoption.verification_id
        or receipt.task_revision_at_acceptance != binding.task_revision + 1
        or receipt.accepted_content_hash != "sha256:" + binding.output_content_hash
        or receipt.accepted_byte_count != binding.output_byte_count
        or receipt.accepted_destination_path != adoption.destination_path
        or receipt.acceptance_authority != PRODUCTION_TASK_ACCEPTANCE_AUTHORITY
        or receipt.schema_version != PRODUCTION_TASK_ACCEPTANCE_SCHEMA_VERSION
    ):
        raise RuntimeError("Phase-50 production Task acceptance relation is not exact")

    matches = [
        item
        for item in runtime.list_verifications("TASK", binding.task_id)
        if item["id"] == receipt.task_verification_id
    ]
    if len(matches) != 1:
        raise RuntimeError("Phase-50 Task PASS Verification is missing or ambiguous")
    verification = matches[0]
    evidence = _json_object(
        verification["evidence_json"],
        "Phase-50 Task PASS Verification evidence",
    )
    metrics = _json_object(
        verification["metrics_json"],
        "Phase-50 Task PASS Verification metrics",
    )
    if (
        verification["target_type"] != "TASK"
        or verification["target_id"] != binding.task_id
        or verification["verification_type"] != PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE
        or verification["verifier"] != PRODUCTION_TASK_ACCEPTANCE_VERIFIER
        or verification["status"] != "PASS"
        or verification["run_id"] != binding.run_id
        or verification["created_at"] != receipt.accepted_at
        or evidence != _expected_acceptance_evidence(binding, adoption, receipt)
        or metrics != {}
    ):
        raise RuntimeError("Phase-50 Task PASS Verification drifted")


def _read_optional_acceptance(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaProductionTaskAcceptanceReceipt | None:
    try:
        return read_pixelorama_production_task_acceptance(runtime, execution_id)
    except PixeloramaProductionTaskAcceptanceError as exc:
        if str(exc) == "production Task acceptance does not exist":
            return None
        raise


def _require_children_success_compatible(runtime: OriginForgeRuntime, task_id: str) -> None:
    with runtime.store.session() as conn:
        incomplete = conn.execute(
            """SELECT id, status FROM tasks
               WHERE parent_task_id = ? AND status NOT IN (?, ?)
               ORDER BY created_at, rowid""",
            (task_id, TaskStatus.SUCCEEDED.value, TaskStatus.CANCELLED.value),
        ).fetchall()
    if incomplete:
        details = ", ".join(f"{row['id']}={row['status']}" for row in incomplete)
        raise RuntimeError(
            f"production Task has child Tasks incompatible with success: {details}"
        )


def _require_terminal_transition_event(
    runtime: OriginForgeRuntime,
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
    task_revision: int,
) -> None:
    matches = [
        row
        for row in runtime.store.event_history("TASK", receipt.task_id)
        if row["event_type"] == "TASK_STATUS_CHANGED"
        and row["old_state"] == TaskStatus.RUNNING.value
        and row["new_state"] == TaskStatus.SUCCEEDED.value
        and int(row["revision"]) == task_revision
    ]
    if len(matches) != 1:
        raise RuntimeError("canonical Phase-50 Task SUCCEEDED transition event is not exact")


def inspect_pixelorama_production_task_acceptance_currentness_readonly(
    runtime: OriginForgeRuntime,
    execution_id: str,
) -> PixeloramaProductionTaskAcceptanceCurrentness:
    """Read one Phase-50 acceptance relation without writes or external execution."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        raise ValueError("execution_id must be a DISPEXEC ID")

    def result(
        *,
        status: PixeloramaProductionTaskAcceptanceCurrentnessStatus,
        task_id: str | None = None,
        adopted_artifact_id: str | None = None,
        task_verification_id: str | None = None,
        task_revision: int | None = None,
        detail: str | None = None,
    ) -> PixeloramaProductionTaskAcceptanceCurrentness:
        return PixeloramaProductionTaskAcceptanceCurrentness(
            execution_id=execution_id,
            task_id=task_id,
            adopted_artifact_id=adopted_artifact_id,
            task_verification_id=task_verification_id,
            task_revision=task_revision,
            status=status,
            detail=detail,
        )

    try:
        binding = read_pixelorama_dispatch_output_binding(runtime, execution_id)
        execution_currentness = inspect_dispatch_execution_currentness_readonly(
            runtime, execution_id
        )
        if execution_currentness.status is not DispatchExecutionCurrentnessStatus.RETURNED:
            raise RuntimeError(
                "production dispatch execution is not exact RETURNED/CONSUMED durable truth"
            )
        adoption = read_pixelorama_production_adoption_receipt(runtime, execution_id)
        _require_historical_adoption_relation(runtime, binding, adoption)
        task = runtime.get_task(binding.task_id)
        task_status = TaskStatus(task["status"])
        task_revision = int(task["revision"])
    except Exception as exc:
        return result(
            status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
            detail=str(exc),
        )

    if task_status is TaskStatus.RUNNING:
        try:
            output_currentness = inspect_pixelorama_dispatch_output_currentness_readonly(
                runtime, execution_id
            )
            if (
                output_currentness.status
                is not PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE
                or output_currentness.task_id != binding.task_id
                or output_currentness.output_artifact_id != binding.output_artifact_id
                or output_currentness.production_task_verified
            ):
                raise RuntimeError(
                    output_currentness.detail
                    or "Phase-49 production output currentness is not acceptance eligible"
                )
            if task_revision != binding.task_revision + 1:
                raise RuntimeError("production Task RUNNING revision drifted")
            _require_current_adopted_bytes(runtime, binding, adoption)
            _require_children_success_compatible(runtime, binding.task_id)
            receipt = _read_optional_acceptance(runtime, execution_id)
            if receipt is None:
                return result(
                    status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
                    task_id=binding.task_id,
                    adopted_artifact_id=adoption.adopted_artifact_id,
                    task_revision=task_revision,
                )
            _require_exact_acceptance_relation(runtime, binding, adoption, receipt)
            if receipt.task_revision_at_acceptance != task_revision:
                raise RuntimeError("pending Phase-50 acceptance no longer names current Task revision")
            return result(
                status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
                task_id=binding.task_id,
                adopted_artifact_id=adoption.adopted_artifact_id,
                task_verification_id=receipt.task_verification_id,
                task_revision=task_revision,
            )
        except Exception as exc:
            return result(
                status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
                task_id=binding.task_id,
                adopted_artifact_id=adoption.adopted_artifact_id,
                task_revision=task_revision,
                detail=str(exc),
            )

    if task_status is TaskStatus.SUCCEEDED:
        try:
            receipt = _read_optional_acceptance(runtime, execution_id)
            if receipt is None:
                raise RuntimeError("SUCCEEDED production Task lacks Phase-50 acceptance")
            _require_exact_acceptance_relation(runtime, binding, adoption, receipt)
            expected_revision = receipt.task_revision_at_acceptance + 1
            if task_revision != expected_revision:
                raise RuntimeError("SUCCEEDED production Task revision is not exact")
            _require_terminal_transition_event(runtime, receipt, task_revision)
            return result(
                status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
                task_id=binding.task_id,
                adopted_artifact_id=adoption.adopted_artifact_id,
                task_verification_id=receipt.task_verification_id,
                task_revision=task_revision,
            )
        except Exception as exc:
            return result(
                status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
                task_id=binding.task_id,
                adopted_artifact_id=adoption.adopted_artifact_id,
                task_revision=task_revision,
                detail=str(exc),
            )

    return result(
        status=PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        task_id=binding.task_id,
        adopted_artifact_id=adoption.adopted_artifact_id,
        task_revision=task_revision,
        detail=f"production Task state {task_status.value} is not Phase-50 acceptance current",
    )
