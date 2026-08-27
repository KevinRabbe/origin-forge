from __future__ import annotations

import hashlib
import json

from .image_png import inspect_truecolor8_png
from .lineage import OriginForgeLineage
from .production_dispatch_binding_runtime import RuntimeObservationInputBinder
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_claim_read import read_dispatch_claim
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_execution_assembly import RuntimeObservationExecutionPayload
from .production_execution_owner_runtime import RUNTIME_EXECUTION_OWNER_ID
from .production_runtime_dispatch_output_binding import (
    binding_from_runtime_result,
    publish_runtime_dispatch_output_binding,
    read_runtime_dispatch_output_binding,
)
from .production_runtime_dispatch_output_binding_models import RuntimeDispatchCapture
from .runtime_observation_models import canonical_bytes
from .runtime_observation_service import (
    RuntimeCaptureArtifactEvidence,
    RuntimeObservationService,
    RuntimeObservationServiceResult,
)
from .runtime_observer import LocalProcessRuntimeObserver
from .service import utc_now
from .state import TaskStatus

RUNTIME_RETURNED_DETAIL = "trusted runtime observation owner returned normally"


def _capture_bindings(runtime, request, result: RuntimeObservationServiceResult) -> tuple[RuntimeDispatchCapture, ...]:
    lineage = OriginForgeLineage(runtime)
    specs = {value.capture_id: value for value in request.captures}
    values: list[RuntimeDispatchCapture] = []
    for evidence in result.captures:
        spec = specs.get(evidence.capture_id)
        if spec is None:
            raise ProductionDispatchInvocationError("runtime result contains an undeclared capture")
        path = lineage.local_artifact_path(evidence.artifact_id)
        data = path.read_bytes()
        inspection = inspect_truecolor8_png(data)
        artifact = lineage.get_artifact(evidence.artifact_id)
        content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        if artifact.get("content_hash") != content_hash:
            raise ProductionDispatchInvocationError(
                f"runtime capture content hash drifted: {evidence.capture_id}"
            )
        values.append(
            RuntimeDispatchCapture(
                capture_id=evidence.capture_id,
                artifact_id=evidence.artifact_id,
                integrity_verification_id=evidence.integrity_verification_id,
                visual_verification_id=evidence.visual_verification_id,
                relative_path=spec.relative_path,
                content_hash=content_hash[7:],
                pixel_hash=inspection.pixel_hash,
                byte_count=len(data),
                width=inspection.width,
                height=inspection.height,
            )
        )
    return tuple(values)


def _materialize(binding):
    return RuntimeObservationServiceResult(
        run_id=binding.run_id,
        request_artifact_id=binding.request_artifact_id,
        result_artifact_id=binding.result_artifact_id,
        stdout_artifact_id=binding.stdout_artifact_id,
        stderr_artifact_id=binding.stderr_artifact_id,
        captures=tuple(
            RuntimeCaptureArtifactEvidence(
                capture_id=value.capture_id,
                artifact_id=value.artifact_id,
                integrity_verification_id=value.integrity_verification_id,
                visual_verification_id=value.visual_verification_id,
                visual_diff=None,
            )
            for value in binding.captures
        ),
        missing_capture_ids=(),
        backend_result_hash="sha256:" + binding.backend_result_hash,
        crash_detected=False,
        timed_out=False,
    )


def _require_runtime_binding_evidence(runtime, binding) -> None:
    """Revalidate every persisted runtime Artifact before recovery terminalization."""
    lineage = OriginForgeLineage(runtime)
    request_artifact = lineage.get_artifact(binding.request_artifact_id)
    result_artifact = lineage.get_artifact(binding.result_artifact_id)
    request_path = lineage.local_artifact_path(binding.request_artifact_id)
    result_path = lineage.local_artifact_path(binding.result_artifact_id)
    request_bytes = request_path.read_bytes()
    result_bytes = result_path.read_bytes()
    try:
        request_payload = json.loads(request_bytes.decode("utf-8"))
        result_payload = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionDispatchInvocationError(
            "runtime request/result evidence is not strict JSON"
        ) from exc
    expected_request_hash = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
    expected_result_hash = "sha256:" + hashlib.sha256(result_bytes).hexdigest()
    if (
        request_artifact.get("type") != "RUNTIME_OBSERVATION_REQUEST"
        or request_artifact.get("parent_artifact_id") is not None
        or request_artifact.get("created_by_run_id") != binding.run_id
        or request_artifact.get("status") != "CAPTURED"
        or request_artifact.get("content_hash") != expected_request_hash
        or result_artifact.get("type") != "RUNTIME_OBSERVATION_RESULT"
        or result_artifact.get("parent_artifact_id") != binding.request_artifact_id
        or result_artifact.get("created_by_run_id") != binding.run_id
        or result_artifact.get("status") != "CAPTURED"
        or result_artifact.get("content_hash") != expected_result_hash
        or canonical_bytes(request_payload) != request_bytes
        or canonical_bytes(result_payload) != result_bytes
    ):
        raise ProductionDispatchInvocationError(
            "runtime request/result Artifact lineage or bytes drifted"
        )
    for artifact_id in (binding.stdout_artifact_id, binding.stderr_artifact_id):
        artifact = lineage.get_artifact(artifact_id)
        path = lineage.local_artifact_path(artifact_id)
        data = path.read_bytes()
        if (
            artifact.get("parent_artifact_id") != binding.result_artifact_id
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("status") != "CAPTURED"
            or artifact.get("content_hash") != "sha256:" + hashlib.sha256(data).hexdigest()
        ):
            raise ProductionDispatchInvocationError(
                "runtime log Artifact lineage or bytes drifted"
            )
    for capture in binding.captures:
        artifact = lineage.get_artifact(capture.artifact_id)
        path = lineage.local_artifact_path(capture.artifact_id)
        data = path.read_bytes()
        inspection = inspect_truecolor8_png(data)
        verification_ids = {
            value["id"]
            for value in lineage.list_artifact_verifications(capture.artifact_id)
        }
        if (
            artifact.get("parent_artifact_id") != binding.result_artifact_id
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("status") != "PRODUCED"
            or artifact.get("content_hash") != "sha256:" + capture.content_hash
            or len(data) != capture.byte_count
            or inspection.pixel_hash != capture.pixel_hash
            or inspection.width != capture.width
            or inspection.height != capture.height
            or capture.integrity_verification_id not in verification_ids
            or (
                capture.visual_verification_id is not None
                and capture.visual_verification_id not in verification_ids
            )
        ):
            raise ProductionDispatchInvocationError(
                f"runtime capture evidence drifted: {capture.capture_id}"
            )


def dispatch_runtime_claim_once_if_applicable(runtime, claim_id: str, expected_claim_revision: int):
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(runtime, claim_id, expected_claim_revision)
    descriptor = RuntimeObservationInputBinder().descriptor
    if binding.request_type_id != descriptor.request_type_id:
        return None
    legacy._require_trusted_relation(
        binding,
        descriptor=descriptor,
        expected_owner_id=RUNTIME_EXECUTION_OWNER_ID,
        expected_adapter_id="originforge.runtime.observe",
        expected_contract_id="runtime.observe@1",
        expected_binder_id=descriptor.binder_id,
        expected_request_type_id=descriptor.request_type_id,
    )
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    payload = started.dependencies.payload
    if not isinstance(payload, RuntimeObservationExecutionPayload):
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        observer = LocalProcessRuntimeObserver(
            workspace_root=runtime.state_dir / "runtime-observations",
            executable=payload.infrastructure.executable,
            executable_hash=payload.infrastructure.executable_hash,
            backend_id=payload.request.backend_id,
            backend_version=payload.request.backend_version,
            target_id=payload.request.target_id,
            target_version=payload.request.target_version,
        )
        result = RuntimeObservationService(runtime, observer).execute(
            started.execution.task_id, payload.request
        )
        candidate = binding_from_runtime_result(
            started.execution,
            result,
            captures=_capture_bindings(runtime, payload.request, result),
            created_at=utc_now(),
        )
        publish_runtime_dispatch_output_binding(runtime, candidate)
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        legacy._record_raised_or_recovery(
            runtime, started, frozen_claim,
            detail=f"trusted runtime observation owner raised {legacy._exception_type_commitment(exc)}",
        )
        raise ProductionDispatchInvocationError(
            f"trusted runtime observation owner raised {legacy._exception_type_commitment(exc)}"
        ) from exc
    returned = legacy._record_returned_or_recovery(
        runtime, started, frozen_claim, detail=RUNTIME_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, runtime_result=result)


def recover_runtime_dispatch_execution_once(runtime, execution_id: str) -> CompletedDispatchInvocation:
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != RUNTIME_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError("execution is not owned by runtime observation")
    try:
        binding = read_runtime_dispatch_output_binding(runtime, execution_id)
        _require_runtime_binding_evidence(runtime, binding)
        result = _materialize(binding)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, runtime_result=result)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise ProductionDispatchInvocationRecoveryRequired(execution_id, "STARTED_RELATION_MISMATCH")
    try:
        returned = mark_dispatch_execution_returned(
            runtime, execution_id, execution.revision,
            execution.claim_revision_at_start, RUNTIME_RETURNED_DETAIL,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned, runtime_result=result)
