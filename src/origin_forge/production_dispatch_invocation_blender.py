from __future__ import annotations

import json
from dataclasses import dataclass

from .blender_models import BlenderBudget, BlenderJobRequest
from .blockbench_glb import GlbError, inspect_glb
from .blockbench_models import canonical_bytes, validate_sha256
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .model3d_requests import Model3DRequestError, _project
from .production_blender_dispatch_output_binding import bind_blender_dispatch_output
from .production_blender_export import BlenderExportService, BlenderExportServiceResult
from .production_dispatch_binding_blender import (
    BLENDER_BINDER_ID,
    BLENDER_REQUEST_TYPE_ID,
    BlenderExportGLBInputBinder,
)
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_execution_models import DispatchExecution, DispatchExecutionStatus
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_execution_assembly import BlenderExportGLBExecutionPayload
from .production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_CONTRACT_ID,
    BLENDER_OPERATION,
)
from .production_work_order_models import content_hash
from .state import RunStatus, TaskStatus


_BLENDER_OWNER_ID = "originforge.execution.blender.export-glb@1"
_BLENDER_RETURNED_DETAIL = "trusted Blender export-glb execution owner returned normally"
_BLENDER_OUTPUT_PATH = "exports/model.glb"
_BLENDER_REQUEST_FIELDS = {
    "task_id",
    "model3d_request_id",
    "model3d_request_hash",
    "operation",
    "project",
    "project_hash",
}


@dataclass(frozen=True)
class BlenderInvocationRequest:
    task_id: str
    model3d_request_id: str
    model3d_request_hash: str
    operation: str
    project: object
    project_hash: str
    request_content_hash: str

    def __post_init__(self) -> None:
        import origin_forge.production_dispatch_invocation as legacy

        if not validate_id(self.task_id, IdKind.TASK):
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation task_id must be a valid TASK ID"
            )
        if not validate_id(self.model3d_request_id, IdKind.MODEL3D_REQUEST):
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation model3d_request_id must be a MODEL3DREQ ID"
            )
        try:
            validate_sha256(self.model3d_request_hash, "model3d_request_hash")
            validate_sha256(self.project_hash, "project_hash")
        except ValueError as exc:
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation semantic hash is invalid"
            ) from exc
        if self.operation != BLENDER_OPERATION:
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation operation drifted"
            )
        if getattr(self.project, "content_hash", None) != self.project_hash:
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation project hash drifted"
            )
        legacy._digest(self.request_content_hash, "request_content_hash")
        if content_hash(self.projection_dict()) != self.request_content_hash:
            raise legacy.ProductionDispatchInvocationError(
                "Blender invocation request content hash does not recompute"
            )

    def projection_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "model3d_request_id": self.model3d_request_id,
            "model3d_request_hash": self.model3d_request_hash,
            "operation": self.operation,
            "project": self.project.to_dict(),
            "project_hash": self.project_hash,
        }


def _decode_blender_request_projection(binding) -> BlenderInvocationRequest:
    import origin_forge.production_dispatch_invocation as legacy

    projection = binding.request_projection
    if not isinstance(projection, dict) or set(projection) != _BLENDER_REQUEST_FIELDS:
        raise legacy.ProductionDispatchInvocationError(
            "Blender request projection schema drifted"
        )
    try:
        project = _project(projection["project"])
    except (Model3DRequestError, TypeError, ValueError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            "Blender request project failed canonical reconstruction"
        ) from exc
    request = BlenderInvocationRequest(
        task_id=projection["task_id"],
        model3d_request_id=projection["model3d_request_id"],
        model3d_request_hash=projection["model3d_request_hash"],
        operation=projection["operation"],
        project=project,
        project_hash=projection["project_hash"],
        request_content_hash=binding.request_content_hash,
    )
    if request.projection_dict() != projection:
        raise legacy.ProductionDispatchInvocationError(
            "Blender request projection is not canonical"
        )
    return request


def _require_trusted_blender_relation(binding) -> None:
    import origin_forge.production_dispatch_invocation as legacy

    legacy._require_trusted_relation(
        binding,
        descriptor=BlenderExportGLBInputBinder().descriptor,
        expected_owner_id=_BLENDER_OWNER_ID,
        expected_adapter_id=BLENDER_ADAPTER_ID,
        expected_contract_id=BLENDER_CONTRACT_ID,
        expected_binder_id=BLENDER_BINDER_ID,
        expected_request_type_id=BLENDER_REQUEST_TYPE_ID,
    )


def _artifact_json(lineage, artifact_id: str, label: str):
    import origin_forge.production_dispatch_invocation as legacy

    try:
        artifact = lineage.get_artifact(artifact_id)
        path = lineage.local_artifact_path(artifact_id)
        data = path.read_bytes()
        payload = json.loads(data.decode("utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            f"Blender {label} Artifact cannot be revalidated"
        ) from exc
    if not isinstance(payload, dict) or canonical_bytes(payload) != data:
        raise legacy.ProductionDispatchInvocationError(
            f"Blender {label} Artifact is not exact canonical evidence"
        )
    return artifact, payload


def _require_blender_result_durable(
    runtime,
    frozen_request: BlenderInvocationRequest,
    concrete_request: BlenderJobRequest,
    result: BlenderExportServiceResult,
    payload: BlenderExportGLBExecutionPayload,
) -> None:
    import origin_forge.production_dispatch_invocation as legacy

    if not isinstance(result, BlenderExportServiceResult):
        raise legacy.ProductionDispatchInvocationError(
            "Blender owner returned an invalid result type"
        )
    operation = result.operation
    if operation.request != concrete_request:
        raise legacy.ProductionDispatchInvocationError(
            "Blender owner result does not bind the allocated request"
        )
    if (
        concrete_request.project != frozen_request.project
        or concrete_request.project.content_hash != frozen_request.project_hash
        or concrete_request.output_relative_path != _BLENDER_OUTPUT_PATH
        or concrete_request.runtime_hash != payload.profile.runtime_hash
        or concrete_request.runner_fingerprint != payload.profile.runner_fingerprint
        or concrete_request.expected_blender_version != payload.profile.expected_blender_version
        or concrete_request.budget != BlenderBudget()
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender concrete request drifted from frozen semantic/profile authority"
        )
    try:
        run = runtime.get_run(result.run_id)
        task = runtime.get_task(frozen_request.task_id)
    except (KeyError, RuntimeError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            "Blender owner Run/Task relation cannot be read"
        ) from exc
    if (
        run["task_id"] != frozen_request.task_id
        or run["role"] != BlenderExportService.RUN_ROLE
        or run["status"] != RunStatus.SUCCEEDED.value
        or task["status"] != TaskStatus.RUNNING.value
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender owner result does not bind one SUCCEEDED MODEL3D Run to RUNNING Task"
        )

    lineage = OriginForgeLineage(runtime)
    request_artifact, request_payload = _artifact_json(
        lineage, result.request_artifact_id, "request"
    )
    result_artifact, result_payload = _artifact_json(
        lineage, result.result_artifact_id, "result"
    )
    try:
        output_artifact = lineage.get_artifact(result.output_artifact_id)
        output_path = lineage.local_artifact_path(result.output_artifact_id)
        output_bytes = output_path.read_bytes()
        output_inspection = inspect_glb(output_bytes)
    except (KeyError, OSError, RuntimeError, GlbError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            "Blender output Artifact cannot be independently revalidated"
        ) from exc

    request_location = (
        f".origin-forge/blender-production-export-evidence/{result.run_id}/request.json"
    )
    result_location = (
        f".origin-forge/blender-production-export-evidence/{result.run_id}/result.json"
    )
    output_location = (
        f".origin-forge/model3d-workspaces/{concrete_request.workspace_id}/"
        f"{concrete_request.output_relative_path}"
    )
    if (
        request_artifact["type"] != "BLENDER_JOB_REQUEST"
        or request_artifact["created_by_run_id"] != result.run_id
        or request_artifact["parent_artifact_id"] is not None
        or request_artifact["status"] != "CAPTURED"
        or request_artifact["path_or_uri"] != request_location
        or request_payload != concrete_request.to_dict()
        or result_artifact["type"] != "BLENDER_EXECUTION_RESULT"
        or result_artifact["created_by_run_id"] != result.run_id
        or result_artifact["parent_artifact_id"] != result.request_artifact_id
        or result_artifact["status"] != "CAPTURED"
        or result_artifact["path_or_uri"] != result_location
        or result_payload != operation.to_dict()
        or output_artifact["type"] != "BLENDER_GLB_EXPORT"
        or output_artifact["created_by_run_id"] != result.run_id
        or output_artifact["parent_artifact_id"] != result.result_artifact_id
        or output_artifact["status"] != "PRODUCED"
        or output_artifact["path_or_uri"] != output_location
        or output_artifact["content_hash"] != operation.inspection.content_hash
        or output_inspection != operation.inspection
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender owner durable Artifact lineage is not exact"
        )

    matching_output = [
        value
        for value in lineage.list_artifact_verifications(result.output_artifact_id)
        if value["id"] == result.output_verification_id
    ]
    if len(matching_output) != 1:
        raise legacy.ProductionDispatchInvocationError(
            "Blender output Verification identity is missing or ambiguous"
        )
    output_verification = matching_output[0]
    try:
        output_evidence = json.loads(output_verification["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            "Blender output Verification evidence is invalid"
        ) from exc
    expected_output_evidence = {
        "request_hash": concrete_request.content_hash,
        "request_artifact_id": result.request_artifact_id,
        "result_artifact_id": result.result_artifact_id,
        "operation_id": concrete_request.operation_id,
        "workspace_id": concrete_request.workspace_id,
        "project_hash": concrete_request.project.content_hash,
        "output_relative_path": concrete_request.output_relative_path,
        "output_hash": operation.inspection.content_hash,
        "output_byte_count": operation.inspection.byte_count,
        "blender_version": operation.blender_version,
        "runtime_hash": operation.runtime_hash,
        "runner_fingerprint": operation.runner_fingerprint,
        "glb_inspection": operation.inspection.to_dict(),
        "semantic_geometry_verified": False,
        "production_task_verified": False,
        "canonical_asset_adopted": False,
    }
    if (
        output_verification["verification_type"] != "blender-glb-export-integrity"
        or output_verification["verifier"] != BlenderExportService.VERIFIER
        or output_verification["status"] != "PASS"
        or output_verification["run_id"] != result.run_id
        or output_evidence != expected_output_evidence
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender output Verification does not exactly authorize returned evidence"
        )

    verifications = runtime.list_verifications("RUN", result.run_id)
    matching_run = [value for value in verifications if value["id"] == result.run_verification_id]
    if len(matching_run) != 1:
        raise legacy.ProductionDispatchInvocationError(
            "Blender Run Verification identity is missing or ambiguous"
        )
    run_verification = matching_run[0]
    try:
        run_evidence = json.loads(run_verification["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise legacy.ProductionDispatchInvocationError(
            "Blender Run Verification evidence is invalid"
        ) from exc
    expected_run_evidence = {
        "request_hash": concrete_request.content_hash,
        "request_artifact_id": result.request_artifact_id,
        "result_artifact_id": result.result_artifact_id,
        "output_artifact_id": result.output_artifact_id,
        "output_verification_id": result.output_verification_id,
        "operation_id": concrete_request.operation_id,
        "workspace_id": concrete_request.workspace_id,
        "project_hash": concrete_request.project.content_hash,
        "output_relative_path": concrete_request.output_relative_path,
        "output_hash": operation.inspection.content_hash,
        "output_byte_count": operation.inspection.byte_count,
        "blender_version": operation.blender_version,
        "runtime_hash": operation.runtime_hash,
        "runner_fingerprint": operation.runner_fingerprint,
        "production_task_verified": False,
        "canonical_asset_adopted": False,
        "provenance_signed": False,
    }
    if (
        run_verification["verification_type"] != "blender-export-glb"
        or run_verification["verifier"] != BlenderExportService.VERIFIER
        or run_verification["status"] != "PASS"
        or run_verification["run_id"] != result.run_id
        or run_evidence != expected_run_evidence
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender Run Verification does not exactly authorize returned evidence"
        )


@dataclass(frozen=True)
class CompletedBlenderDispatchInvocation(CompletedDispatchInvocation):
    blender_result: BlenderExportServiceResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, DispatchExecution):
            raise TypeError("execution must be a DispatchExecution")
        if self.execution.status is not DispatchExecutionStatus.RETURNED:
            raise ProductionDispatchInvocationError(
                "completed Blender invocation requires RETURNED execution"
            )
        if (
            self.execution.execution_owner_id != _BLENDER_OWNER_ID
            or self.policy_result is not None
            or self.simulation_result is not None
            or self.pixelorama_result is not None
            or not isinstance(self.blender_result, BlenderExportServiceResult)
        ):
            raise ProductionDispatchInvocationError(
                "Blender execution requires exactly one BlenderExportServiceResult"
            )


def dispatch_blender_claim_once_if_applicable(
    runtime,
    claim_id: str,
    expected_claim_revision: int,
):
    """Invoke Blender exactly once when the frozen claim has the reviewed Blender request."""
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    if binding.request_type_id != BLENDER_REQUEST_TYPE_ID:
        return None

    _require_trusted_blender_relation(binding)
    request = _decode_blender_request_projection(binding)
    if (
        frozen_claim.status is not DispatchClaimStatus.ACTIVE
        or frozen_claim.revision != expected_claim_revision
        or frozen_claim.task_id != request.task_id
    ):
        raise legacy.ProductionDispatchInvocationError(
            "Blender dispatch claim changed before execution ownership begin"
        )

    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    execution = started.execution
    plan = started.dependencies.plan
    payload = started.dependencies.payload
    if (
        execution.status is not DispatchExecutionStatus.STARTED
        or execution.claim_id != frozen_claim.claim_id
        or execution.claim_revision_at_start != frozen_claim.revision
        or execution.task_id != request.task_id
        or execution.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or execution.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or execution.execution_owner_id != _BLENDER_OWNER_ID
        or plan.claim_id != frozen_claim.claim_id
        or plan.claim_revision != frozen_claim.revision
        or plan.task_id != request.task_id
        or plan.dispatch_binding_id != frozen_claim.dispatch_binding_id
        or plan.dispatch_binding_hash != frozen_claim.dispatch_binding_hash
        or plan.request_type_id != BLENDER_REQUEST_TYPE_ID
        or plan.request_content_hash != request.request_content_hash
        or plan.owner_id != _BLENDER_OWNER_ID
        or not isinstance(payload, BlenderExportGLBExecutionPayload)
    ):
        raise legacy.ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )

    try:
        concrete_request = BlenderJobRequest.create(
            project=request.project,
            output_relative_path=_BLENDER_OUTPUT_PATH,
            runner_fingerprint=payload.profile.runner_fingerprint,
            runtime_hash=payload.profile.runtime_hash,
            expected_blender_version=payload.profile.expected_blender_version,
            budget=BlenderBudget(),
        )
        blender_result = BlenderExportService(runtime, payload.profile).execute(
            request.task_id, concrete_request
        )
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=f"trusted Blender export-glb execution owner raised {exception_type}",
        )
        raise legacy.ProductionDispatchInvocationError(
            "trusted Blender export-glb execution owner raised "
            f"{exception_type}; dispatch execution {execution.execution_id} recorded RAISED"
        ) from exc

    try:
        _require_blender_result_durable(
            runtime,
            request,
            concrete_request,
            blender_result,
            payload,
        )
    except Exception as exc:
        raise legacy.ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc

    try:
        bind_blender_dispatch_output(runtime, execution, blender_result)
    except Exception as exc:
        raise legacy.ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc

    returned = legacy._record_returned_or_recovery(
        runtime,
        started,
        frozen_claim,
        detail=_BLENDER_RETURNED_DETAIL,
    )
    return CompletedBlenderDispatchInvocation(
        returned,
        blender_result=blender_result,
    )
