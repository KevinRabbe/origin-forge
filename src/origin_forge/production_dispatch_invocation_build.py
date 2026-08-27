from __future__ import annotations

import json
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_dispatch_claim_models import DispatchClaimStatus
from .production_dispatch_execution import mark_dispatch_execution_returned
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_invocation import (
    CompletedDispatchInvocation,
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
)
from .production_execution_assembly import BuildIntegrationExecutionPayload
from .production_work_order_build import (
    BUILD_ADAPTER_ID,
    BUILD_CONTRACT_ID,
    BUILD_REQUEST_TYPE_ID,
)
from .production_work_order_models import content_hash
from .sandbox import SandboxResult
from .sandbox_verification import (
    CommandVerificationResult,
    SandboxedWorkspaceVerifier,
    WorkspaceVerificationResult,
)
from .state import TaskStatus
from .workspaces import GitWorkspaceManager

BUILD_OWNER_ID = "originforge.execution.build.integration@1"
BUILD_RETURNED_DETAIL = "trusted build integration execution owner returned normally"


@dataclass(frozen=True)
class BuildIntegrationInvocationRequest:
    task_id: str
    operation: str
    request_content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise ProductionDispatchInvocationError("build request Task ID is invalid")
        if self.operation != "BUILD":
            raise ProductionDispatchInvocationError("build request operation is invalid")
        if content_hash({"task_id": self.task_id, "operation": self.operation}) != self.request_content_hash:
            raise ProductionDispatchInvocationError("build request hash does not recompute")


def _decode_request(binding) -> BuildIntegrationInvocationRequest:
    projection = binding.request_projection
    if (
        not isinstance(projection, dict)
        or set(projection) != {"task_id", "operation"}
        or not isinstance(projection["task_id"], str)
        or projection["operation"] != "BUILD"
        or binding.request_type_id != BUILD_REQUEST_TYPE_ID
        or binding.selected_adapter_id != BUILD_ADAPTER_ID
        or binding.dispatch_contract_id != BUILD_CONTRACT_ID
    ):
        raise ProductionDispatchInvocationError(
            "build request projection violates the trusted build contract"
        )
    return BuildIntegrationInvocationRequest(
        projection["task_id"], projection["operation"], binding.request_content_hash
    )


def _require_started_relation(runtime, started, claim, request) -> None:
    execution = started.execution
    task = runtime.get_task(execution.task_id)
    if (
        execution.status is not DispatchExecutionStatus.STARTED
        or execution.execution_owner_id != BUILD_OWNER_ID
        or execution.claim_id != claim.claim_id
        or execution.claim_revision_at_start != claim.revision
        or execution.task_id != request.task_id
        or claim.status is not DispatchClaimStatus.ACTIVE
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
        or not isinstance(started.dependencies.payload, BuildIntegrationExecutionPayload)
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution.execution_id, "STARTED_RELATION_MISMATCH"
        )


def dispatch_build_claim_once_if_applicable(runtime, claim_id, expected_claim_revision):
    import origin_forge.production_dispatch_invocation as legacy

    claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    if binding.request_type_id != BUILD_REQUEST_TYPE_ID:
        return None
    request = _decode_request(binding)
    if claim.task_id != request.task_id:
        raise ProductionDispatchInvocationError("build claim Task relation drifted")
    started = legacy.begin_dispatch_execution(runtime, claim_id, expected_claim_revision)
    _require_started_relation(runtime, started, claim, request)
    payload = started.dependencies.payload
    assert isinstance(payload, BuildIntegrationExecutionPayload)
    workspaces = payload.workspaces.list(request.task_id)
    if len(workspaces) != 1:
        legacy._record_raised_or_recovery(
            runtime,
            started,
            claim,
            detail="trusted build integration requires exactly one Task workspace",
        )
        raise ProductionDispatchInvocationError(
            "build integration requires exactly one Task workspace"
        )
    try:
        result = SandboxedWorkspaceVerifier(
            runtime, payload.sandbox_backend, payload.workspaces
        ).verify_build(
            workspaces[0]["workspace_id"], execution_id=started.execution.execution_id
        )
    except Exception as exc:
        legacy._record_raised_or_recovery(
            runtime,
            started,
            claim,
            detail=f"trusted build integration execution owner raised {type(exc).__name__}",
        )
        raise ProductionDispatchInvocationError(
            f"trusted build integration execution owner raised {type(exc).__name__}"
        ) from exc
    if not isinstance(result, WorkspaceVerificationResult) or not result.passed:
        legacy._record_raised_or_recovery(
            runtime,
            started,
            claim,
            detail="trusted build integration execution owner failed verification",
        )
        raise ProductionDispatchInvocationError(
            f"build verification failed; dispatch execution {started.execution.execution_id} recorded RAISED"
        )
    returned = legacy._record_returned_or_recovery(
        runtime, started, claim, detail=BUILD_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, build_result=result)


def recover_build_dispatch_execution_once(runtime, execution_id: str):
    """Materialize already-published build evidence; never rerun the backend."""
    from .production_dispatch_execution_read import read_dispatch_execution

    try:
        execution = read_dispatch_execution(runtime, execution_id)
        if execution.execution_owner_id != BUILD_OWNER_ID:
            raise ValueError("execution owner is not build integration")
        workspaces = GitWorkspaceManager(runtime).list(execution.task_id)
        if len(workspaces) != 1:
            raise ValueError("build execution does not have one Task workspace")
        workspace_id = workspaces[0]["id"]
        rows = runtime.list_verifications("WORKSPACE", workspace_id)
        results: list[CommandVerificationResult] = []
        for row in rows:
            if not str(row["verification_type"]).startswith("sandbox-build:"):
                continue
            evidence = json.loads(row["evidence_json"])
            if (
                row["status"] != "PASS"
                or evidence.get("dispatch_execution_id") != execution_id
                or not isinstance(evidence.get("result"), dict)
            ):
                continue
            result_data = evidence["result"]
            results.append(
                CommandVerificationResult(
                    "build",
                    row["verification_type"].split(":", 1)[1],
                    row["id"],
                    True,
                    SandboxResult(**result_data),
                )
            )
        if not results:
            raise ValueError("complete build verification evidence is missing")
        materialized = WorkspaceVerificationResult(workspace_id, True, tuple(results))
        if execution.status is DispatchExecutionStatus.STARTED:
            returned = mark_dispatch_execution_returned(
                runtime,
                execution.execution_id,
                execution.revision,
                execution.claim_revision_at_start,
                BUILD_RETURNED_DETAIL,
            )
        elif execution.status is DispatchExecutionStatus.RETURNED:
            returned = execution
        else:
            raise ValueError("build execution is not recoverable")
        return CompletedDispatchInvocation(returned, build_result=materialized)
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
