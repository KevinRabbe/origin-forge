from __future__ import annotations

from typing import Any

from .runtime import OriginForgeRuntime
from .runtime_observation_models import content_hash
from .state import RunStatus, TaskStatus
from .training_research_models import (
    ResearchDisclosureClass,
    TrainingEvidenceRef,
    TrainingEvidenceType,
    TrainingResearchModelError,
    TrainingTrajectory,
    TrainingTrajectoryOutcome,
)


class TrainingTrajectoryAdapterError(RuntimeError):
    pass


def _task_projection(task: dict[str, Any]) -> dict[str, object]:
    return {
        "id": task["id"],
        "flow_id": task["flow_id"],
        "status": task["status"],
        "revision": int(task["revision"]),
        "attempt_count": int(task["attempt_count"]),
    }


def _run_projection(run: dict[str, Any]) -> dict[str, object]:
    return {
        "id": run["id"],
        "task_id": run["task_id"],
        "role": run["role"],
        "model_profile": run["model_profile"],
        "model_hash": run["model_hash"],
        "status": run["status"],
        "input_token_count": run["input_token_count"],
        "output_token_count": run["output_token_count"],
    }


def _verification_projection(verification: dict[str, Any]) -> dict[str, object]:
    return {
        "id": verification["id"],
        "target_type": verification["target_type"],
        "target_id": verification["target_id"],
        "verification_type": verification["verification_type"],
        "verifier": verification["verifier"],
        "status": verification["status"],
        "run_id": verification["run_id"],
    }


def build_verified_runtime_trajectory(
    runtime: OriginForgeRuntime,
    *,
    run_id: str,
) -> TrainingTrajectory:
    """Build one redacted research trajectory from exact successful durable state.

    v1 intentionally exports only stable structural/cost metadata. Task objective,
    acceptance criteria, constraints, verification evidence/metrics, failure text,
    arbitrary artifacts, and repository content remain undisclosed until a future
    explicit research-disclosure policy exists.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    run = runtime.get_run(run_id)
    task_id = run.get("task_id")
    if not isinstance(task_id, str):
        raise TrainingTrajectoryAdapterError("research trajectory requires a task-scoped Run")
    task = runtime.get_task(task_id)
    if run["status"] != RunStatus.SUCCEEDED.value:
        raise TrainingTrajectoryAdapterError("v1 research adapter requires a SUCCEEDED Run")
    if task["status"] != TaskStatus.SUCCEEDED.value:
        raise TrainingTrajectoryAdapterError("v1 research adapter requires a terminal SUCCEEDED Task")

    verifications = [
        value
        for value in runtime.list_verifications("TASK", task_id)
        if value["status"] == "PASS" and value["run_id"] == run_id
    ]
    if not verifications:
        raise TrainingTrajectoryAdapterError(
            "v1 research adapter requires PASS Task verification bound to the exact Run"
        )

    task_projection = _task_projection(task)
    run_projection = _run_projection(run)
    verification_projections = tuple(
        sorted(
            (_verification_projection(value) for value in verifications),
            key=lambda value: str(value["id"]),
        )
    )
    refs: list[TrainingEvidenceRef] = [
        TrainingEvidenceRef(
            evidence_type=TrainingEvidenceType.TASK,
            ref_id=task_id,
            content_hash=content_hash(task_projection),
            revision=int(task["revision"]),
            disclosure=ResearchDisclosureClass.ALLOWED,
        ),
        TrainingEvidenceRef(
            evidence_type=TrainingEvidenceType.RUN,
            ref_id=run_id,
            content_hash=content_hash(run_projection),
            revision=None,
            disclosure=ResearchDisclosureClass.ALLOWED,
        ),
    ]
    refs.extend(
        TrainingEvidenceRef(
            evidence_type=TrainingEvidenceType.VERIFICATION,
            ref_id=str(value["id"]),
            content_hash=content_hash(value),
            revision=None,
            disclosure=ResearchDisclosureClass.ALLOWED,
        )
        for value in verification_projections
    )

    leakage_group_hash = content_hash(
        {
            "group_policy": "project-task-v1",
            "project_id": runtime.project_id(),
            "task_id": task_id,
        }
    )
    example = {
        "input": {
            "role": run["role"],
            "model_profile": run["model_profile"],
            "model_hash": run["model_hash"],
            "attempt_count": int(task["attempt_count"]),
        },
        "target": {
            "task_status": task["status"],
            "run_status": run["status"],
            "verification_types": sorted(
                {str(value["verification_type"]) for value in verification_projections}
            ),
            "verification_count": len(verification_projections),
        },
        "cost": {
            "input_token_count": run["input_token_count"],
            "output_token_count": run["output_token_count"],
        },
        "redaction": {
            "task_objective_disclosed": False,
            "task_constraints_disclosed": False,
            "verification_payload_disclosed": False,
            "repository_content_disclosed": False,
        },
    }
    try:
        return TrainingTrajectory.create(
            project_id=runtime.project_id(),
            task_id=task_id,
            run_id=run_id,
            leakage_group_hash=leakage_group_hash,
            outcome=TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
            objective="verified terminal runtime trajectory",
            model_profile=run["model_profile"],
            model_hash=run["model_hash"],
            example=example,
            source_refs=refs,
        )
    except (KeyError, TypeError, ValueError, TrainingResearchModelError) as exc:
        raise TrainingTrajectoryAdapterError(
            "durable runtime evidence cannot be represented by the v1 research contract"
        ) from exc
