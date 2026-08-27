from __future__ import annotations

import hashlib
import json

from .lineage import OriginForgeLineage
from .playtest_analysis import PlaytestSummary
from .playtest_harness import CooperativePlaytestHarness
from .playtest_service import PlaytestService, PlaytestServiceResult
from .production_dispatch_binding_playtest import CooperativePlaytestInputBinder
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
from .production_execution_assembly import CooperativePlaytestExecutionPayload
from .production_execution_owner_playtest import PLAYTEST_EXECUTION_OWNER_ID
from .production_playtest_dispatch_output_binding import (
    binding_from_playtest_result,
    publish_playtest_dispatch_output_binding,
    read_playtest_dispatch_output_binding,
)
from .service import utc_now
from .state import TaskStatus

PLAYTEST_RETURNED_DETAIL = "trusted cooperative playtest owner returned normally"


def dispatch_playtest_claim_once_if_applicable(
    runtime, claim_id: str, expected_claim_revision: int
):
    import origin_forge.production_dispatch_invocation as legacy

    frozen_claim, binding = legacy._read_frozen_request_evidence(
        runtime, claim_id, expected_claim_revision
    )
    descriptor = CooperativePlaytestInputBinder().descriptor
    if binding.request_type_id != descriptor.request_type_id:
        return None
    legacy._require_trusted_relation(
        binding,
        descriptor=descriptor,
        expected_owner_id=PLAYTEST_EXECUTION_OWNER_ID,
        expected_adapter_id="originforge.playtest.cooperative",
        expected_contract_id="playtest.cooperative@1",
        expected_binder_id=descriptor.binder_id,
        expected_request_type_id=descriptor.request_type_id,
    )
    started = legacy.begin_dispatch_execution(
        runtime, claim_id, expected_claim_revision
    )
    payload = started.dependencies.payload
    if not isinstance(payload, CooperativePlaytestExecutionPayload):
        raise ProductionDispatchInvocationRecoveryRequired(
            started.execution.execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        harness = CooperativePlaytestHarness(
            workspace_root=runtime.state_dir / "playtests",
            executable=payload.infrastructure.executable,
            executable_hash=payload.infrastructure.executable_hash,
            harness_id=payload.scenario.harness_id,
            harness_version=payload.scenario.harness_version,
            target_id=payload.scenario.target_id,
            target_version=payload.scenario.target_version,
        )
        result = PlaytestService(runtime, harness).execute(
            started.execution.task_id, payload.scenario
        )
        publish_playtest_dispatch_output_binding(
            runtime,
            binding_from_playtest_result(
                started.execution, result, created_at=utc_now()
            ),
        )
    except ProductionDispatchInvocationRecoveryRequired:
        raise
    except Exception as exc:
        exception_type = legacy._exception_type_commitment(exc)
        legacy._record_raised_or_recovery(
            runtime,
            started,
            frozen_claim,
            detail=f"trusted playtest owner raised {exception_type}",
        )
        raise ProductionDispatchInvocationError(
            f"trusted playtest owner raised {exception_type}; dispatch execution {started.execution.execution_id} recorded RAISED"
        ) from exc
    returned = legacy._record_returned_or_recovery(
        runtime, started, frozen_claim, detail=PLAYTEST_RETURNED_DETAIL
    )
    return CompletedDispatchInvocation(returned, playtest_result=result)


def _materialize(runtime, binding):
    lineage = OriginForgeLineage(runtime)
    artifact_ids = (
        (binding.scenario_artifact_id, "PLAYTEST_SCENARIO", None),
        (binding.telemetry_artifact_id, "PLAYTEST_TELEMETRY", binding.scenario_artifact_id),
        (binding.summary_artifact_id, "PLAYTEST_SUMMARY", binding.telemetry_artifact_id),
        (binding.stdout_artifact_id, "PLAYTEST_STDOUT_LOG", binding.telemetry_artifact_id),
        (binding.stderr_artifact_id, "PLAYTEST_STDERR_LOG", binding.telemetry_artifact_id),
    )
    for artifact_id, expected_type, expected_parent in artifact_ids:
        artifact = lineage.get_artifact(artifact_id)
        if (
            artifact.get("type") != expected_type
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("parent_artifact_id") != expected_parent
        ):
            raise ValueError("playtest artifact lineage does not match output binding")
        lineage.local_artifact_path(artifact_id)
    telemetry_path = lineage.local_artifact_path(binding.telemetry_artifact_id)
    telemetry_hash = "sha256:" + hashlib.sha256(telemetry_path.read_bytes()).hexdigest()
    if telemetry_hash.removeprefix("sha256:") != binding.telemetry_hash:
        raise ValueError("playtest telemetry artifact hash does not match output binding")
    fields = set(PlaytestSummary.__dataclass_fields__)
    summary_value = json.loads(binding.summary_json)
    for key in ("incomplete_encounters", "unmatched_encounter_ends"):
        if key in summary_value:
            summary_value[key] = tuple(summary_value[key])
    summary_path = lineage.local_artifact_path(binding.summary_artifact_id)
    if json.loads(summary_path.read_text(encoding="utf-8")) != binding_summary_json(summary_value):
        raise ValueError("playtest summary artifact does not match output binding")
    summary = PlaytestSummary(**{key: summary_value[key] for key in fields})
    return PlaytestServiceResult(
        run_id=binding.run_id,
        scenario_artifact_id=binding.scenario_artifact_id,
        telemetry_artifact_id=binding.telemetry_artifact_id,
        summary_artifact_id=binding.summary_artifact_id,
        stdout_artifact_id=binding.stdout_artifact_id,
        stderr_artifact_id=binding.stderr_artifact_id,
        telemetry_hash="sha256:" + binding.telemetry_hash,
        summary=summary,
        outcome=binding.outcome,
        timed_out=binding.timed_out,
        exit_code=binding.exit_code,
    )


def binding_summary_json(summary_value):
    """Return the canonical JSON-compatible summary representation."""
    value = dict(summary_value)
    for key in ("incomplete_encounters", "unmatched_encounter_ends"):
        if key in value:
            value[key] = list(value[key])
    return value


def recover_playtest_dispatch_execution_once(
    runtime, execution_id: str
) -> CompletedDispatchInvocation:
    execution = read_dispatch_execution(runtime, execution_id)
    if execution.execution_owner_id != PLAYTEST_EXECUTION_OWNER_ID:
        raise ProductionDispatchInvocationError(
            "execution is not owned by cooperative playtesting"
        )
    try:
        result = _materialize(
            runtime, read_playtest_dispatch_output_binding(runtime, execution_id)
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "OWNER_RETURN_CONTRACT_MISMATCH"
        ) from exc
    if execution.status is DispatchExecutionStatus.RETURNED:
        return CompletedDispatchInvocation(execution, playtest_result=result)
    if execution.status is not DispatchExecutionStatus.STARTED:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    claim = read_dispatch_claim(runtime, execution.claim_id)
    task = runtime.get_task(execution.task_id)
    if (
        claim.status is not DispatchClaimStatus.ACTIVE
        or claim.revision != execution.claim_revision_at_start
        or task["status"] != TaskStatus.RUNNING.value
        or int(task["revision"]) != execution.task_revision + 1
    ):
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "STARTED_RELATION_MISMATCH"
        )
    try:
        returned = mark_dispatch_execution_returned(
            runtime,
            execution_id,
            execution.revision,
            execution.claim_revision_at_start,
            PLAYTEST_RETURNED_DETAIL,
        )
    except Exception as exc:
        raise ProductionDispatchInvocationRecoveryRequired(
            execution_id, "RETURNED_TERMINALIZATION_FAILED"
        ) from exc
    return CompletedDispatchInvocation(returned, playtest_result=result)
