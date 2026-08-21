from __future__ import annotations

from .conversation_operations import (
    ConversationReferenceRelation,
    ConversationReferenceType,
    ensure_conversation_turn_reference,
)
from .conversation_processing import (
    ConversationProcessingResult,
    _complete_conversation_submission,
    _read_existing_result,
)
from .conversation_production import admit_conversation_goal
from .conversation_service import ConversationSubmissionStatus
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from .production_goal_bootstrap_operator import (
    GoalBootstrapDecision,
    GoalBootstrapOperatorBlocked,
    GoalBootstrapOperatorError,
    bootstrap_goal_once,
    inspect_goal_bootstrap_status_readonly,
    recover_goal_once,
)
from .production_materialization_read import read_plan_materialization
from .runtime import OriginForgeRuntime


class ConversationProductionProcessingError(RuntimeError):
    pass


class ConversationProductionRecoveryRequired(ConversationProductionProcessingError):
    pass


_RECOVERABLE_DECISIONS = frozenset(
    {
        GoalBootstrapDecision.ACTIVE_PRE_PLANNER,
        GoalBootstrapDecision.PLANNER_RECOVERY_REQUIRED,
        GoalBootstrapDecision.POST_PLANNER_RESUMABLE,
        GoalBootstrapDecision.MATERIALIZED_NEEDS_PREPPOL,
    }
)


def _validate_ready_materialization(
    runtime: OriginForgeRuntime,
    goal_id: str,
    receipt: GoalBootstrapReceipt,
):
    if (
        receipt.project_id != runtime.project_id()
        or receipt.goal_id != goal_id
        or receipt.status is not GoalBootstrapStatus.READY
        or receipt.stage is not GoalBootstrapStage.PREPPOL_PUBLISHED
        or receipt.materialization_id is None
        or receipt.materialization_hash is None
    ):
        raise ConversationProductionProcessingError(
            "Goal bootstrap is not an exact READY_FOR_MANAGER handoff"
        )
    materialization = read_plan_materialization(runtime, receipt.materialization_id)
    if (
        materialization.content_hash != receipt.materialization_hash
        or materialization.goal_id != goal_id
        or materialization.goal_revision != receipt.goal_revision
    ):
        raise ConversationProductionProcessingError(
            "Goal bootstrap materialization drifted from its durable receipt"
        )
    return materialization


def _response_content(
    *,
    goal_id: str,
    bootstrap_id: str,
    flow_id: str,
    task_ids: tuple[str, ...],
) -> str:
    task_text = ", ".join(task_ids)
    return (
        "Production request is durably prepared for governed Manager handling: "
        f"Goal {goal_id}; bootstrap {bootstrap_id} is READY_FOR_MANAGER; "
        f"Flow {flow_id}; Tasks {task_text}. "
        "Execution, verification, and adoption remain owned by their existing authorities."
    )


def _complete_ready_submission(
    runtime: OriginForgeRuntime,
    *,
    submission_id: str,
    human_turn_id: str,
    goal_id: str,
    receipt: GoalBootstrapReceipt,
) -> ConversationProcessingResult:
    materialization = _validate_ready_materialization(runtime, goal_id, receipt)
    ensure_conversation_turn_reference(
        runtime,
        human_turn_id,
        ConversationReferenceType.GOAL,
        goal_id,
        ConversationReferenceRelation.RESULT,
    )
    ensure_conversation_turn_reference(
        runtime,
        human_turn_id,
        ConversationReferenceType.FLOW,
        materialization.flow_id,
        ConversationReferenceRelation.RESULT,
    )
    task_ids = tuple(binding.task_id for binding in materialization.task_bindings)
    for task_id in task_ids:
        ensure_conversation_turn_reference(
            runtime,
            human_turn_id,
            ConversationReferenceType.TASK,
            task_id,
            ConversationReferenceRelation.RESULT,
        )
    return _complete_conversation_submission(
        runtime,
        submission_id,
        _response_content(
            goal_id=goal_id,
            bootstrap_id=receipt.bootstrap_id,
            flow_id=materialization.flow_id,
            task_ids=task_ids,
        ),
    )


def process_production_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationProcessingResult:
    """Advance a fresh production request only to the governed Manager handoff boundary."""

    admission = admit_conversation_goal(runtime, submission_id)
    if admission.submission.status is ConversationSubmissionStatus.RESPONDED:
        return _read_existing_result(runtime, admission.submission)
    if admission.submission.status is not ConversationSubmissionStatus.PROCESSING:
        raise ConversationProductionProcessingError(
            "production submission is not PROCESSING after Goal admission"
        )

    projection = inspect_goal_bootstrap_status_readonly(runtime, admission.goal_id)
    if projection.decision is GoalBootstrapDecision.READY_FOR_MANAGER:
        if projection.receipt is None:
            raise ConversationProductionProcessingError(
                "READY_FOR_MANAGER projection lacks its durable bootstrap receipt"
            )
        receipt = projection.receipt
    elif projection.decision is GoalBootstrapDecision.ELIGIBLE:
        try:
            receipt = bootstrap_goal_once(runtime, admission.goal_id).receipt
        except GoalBootstrapOperatorBlocked as exc:
            if exc.decision in _RECOVERABLE_DECISIONS:
                raise ConversationProductionRecoveryRequired(
                    f"Goal {admission.goal_id} entered recoverable bootstrap state "
                    f"{exc.decision.value}; explicit recovery is required"
                ) from exc
            raise ConversationProductionProcessingError(str(exc)) from exc
        except GoalBootstrapOperatorError as exc:
            raise ConversationProductionProcessingError(str(exc)) from exc
    elif projection.decision in _RECOVERABLE_DECISIONS:
        raise ConversationProductionRecoveryRequired(
            f"Goal {admission.goal_id} has recoverable bootstrap state "
            f"{projection.decision.value}; explicit recovery is required"
        )
    else:
        detail = projection.detail or projection.decision.value
        raise ConversationProductionProcessingError(
            f"Goal {admission.goal_id} cannot enter Manager handoff: {detail}"
        )

    return _complete_ready_submission(
        runtime,
        submission_id=submission_id,
        human_turn_id=admission.human_turn.id,
        goal_id=admission.goal_id,
        receipt=receipt,
    )


def recover_production_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationProcessingResult:
    """Explicitly recover one already-admitted production request without fresh replay."""

    admission = admit_conversation_goal(runtime, submission_id)
    if admission.submission.status is ConversationSubmissionStatus.RESPONDED:
        return _read_existing_result(runtime, admission.submission)
    if admission.submission.status is not ConversationSubmissionStatus.PROCESSING:
        raise ConversationProductionProcessingError(
            "production submission is not PROCESSING after Goal admission"
        )

    projection = inspect_goal_bootstrap_status_readonly(runtime, admission.goal_id)
    if projection.decision is GoalBootstrapDecision.READY_FOR_MANAGER:
        if projection.receipt is None:
            raise ConversationProductionProcessingError(
                "READY_FOR_MANAGER projection lacks its durable bootstrap receipt"
            )
        receipt = projection.receipt
    elif projection.decision in _RECOVERABLE_DECISIONS:
        try:
            receipt = recover_goal_once(runtime, admission.goal_id).receipt
        except GoalBootstrapOperatorBlocked as exc:
            raise ConversationProductionProcessingError(str(exc)) from exc
        except GoalBootstrapOperatorError as exc:
            raise ConversationProductionProcessingError(str(exc)) from exc
    elif projection.decision is GoalBootstrapDecision.ELIGIBLE:
        raise ConversationProductionProcessingError(
            "production recovery cannot acquire fresh bootstrap authority; use normal processing"
        )
    else:
        detail = projection.detail or projection.decision.value
        raise ConversationProductionProcessingError(
            f"Goal {admission.goal_id} cannot recover to Manager handoff: {detail}"
        )

    return _complete_ready_submission(
        runtime,
        submission_id=submission_id,
        human_turn_id=admission.human_turn.id,
        goal_id=admission.goal_id,
        receipt=receipt,
    )
