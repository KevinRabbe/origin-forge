from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .conversation_operations import (
    ConversationOperation,
    ConversationOperationConflict,
    ConversationReferenceRelation,
    ConversationReferenceType,
    bind_conversation_submission_operation,
    ensure_conversation_turn_reference,
)
from .conversation_processing import (
    ConversationProcessingConflict,
    ConversationProcessingFailed,
    claim_conversation_submission,
)
from .conversation_service import (
    ConversationActorType,
    ConversationInvariantError,
    ConversationSubmissionReceipt,
    ConversationSubmissionStatus,
    ConversationTurn,
)
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


class ConversationProductionError(RuntimeError):
    pass


class ConversationProductionConflict(ConversationProductionError):
    pass


@dataclass(frozen=True)
class ConversationGoalAdmission:
    submission: ConversationSubmissionReceipt
    human_turn: ConversationTurn
    goal_id: str

    def __post_init__(self) -> None:
        if self.submission.status not in {
            ConversationSubmissionStatus.PROCESSING,
            ConversationSubmissionStatus.RESPONDED,
        }:
            raise ConversationInvariantError(
                "Goal admission requires PROCESSING or RESPONDED submission state"
            )
        if self.human_turn.actor_type is not ConversationActorType.HUMAN:
            raise ConversationInvariantError("Goal admission requires a HUMAN turn")
        if self.human_turn.id != self.submission.human_turn_id:
            raise ConversationInvariantError(
                "Goal admission HUMAN turn does not match submission"
            )
        if not validate_id(self.goal_id, IdKind.GOAL):
            raise ConversationInvariantError("Goal admission has invalid Goal identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "submission": self.submission.to_dict(),
            "human_turn": self.human_turn.to_dict(),
            "goal_id": self.goal_id,
            "authority": "conversation-production-goal-admission",
        }


def _turn_from_row(row) -> ConversationTurn:
    try:
        return ConversationTurn(
            id=row["id"],
            session_id=row["session_id"],
            sequence=int(row["sequence"]),
            actor_type=ConversationActorType(row["actor_type"]),
            content=row["content"],
            content_hash=row["content_hash"],
            client_submission_id=row["client_submission_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError, ConversationInvariantError) as exc:
        raise ConversationInvariantError(
            "stored production-intent HUMAN turn failed canonical validation"
        ) from exc


def _read_human_turn(
    runtime: OriginForgeRuntime,
    receipt: ConversationSubmissionReceipt,
) -> ConversationTurn:
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            """SELECT ct.*
               FROM conversation_turns AS ct
               JOIN conversation_sessions AS cs ON cs.id = ct.session_id
               WHERE ct.id = ? AND ct.session_id = ? AND cs.project_id = ?""",
            (receipt.human_turn_id, receipt.session_id, project_id),
        ).fetchone()
    if row is None:
        raise ConversationInvariantError(
            "production submission is missing its project-owned HUMAN turn"
        )
    turn = _turn_from_row(row)
    if turn.actor_type is not ConversationActorType.HUMAN:
        raise ConversationInvariantError(
            "production submission human_turn_id is not a HUMAN turn"
        )
    return turn


def _read_admitted_goal_id(
    runtime: OriginForgeRuntime,
    submission_id: str,
    expected_objective: str,
) -> str | None:
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT se.aggregate_id, g.objective
               FROM state_events AS se
               JOIN goals AS g ON g.id = se.aggregate_id
               WHERE se.event_type = 'GOAL_CREATED'
                 AND se.aggregate_type = 'GOAL'
                 AND se.actor_type = 'CONVERSATION'
                 AND se.actor_id = ?
                 AND g.project_id = ?
               ORDER BY se.created_at, se.id
               LIMIT 2""",
            (submission_id, project_id),
        ).fetchall()
    if len(rows) > 1:
        raise ConversationProductionConflict(
            "conversation submission is linked to multiple created Goals"
        )
    if not rows:
        return None
    row = rows[0]
    goal_id = str(row["aggregate_id"])
    if not validate_id(goal_id, IdKind.GOAL):
        raise ConversationInvariantError(
            "conversation Goal creation event has invalid aggregate identity"
        )
    if row["objective"] != expected_objective:
        raise ConversationProductionConflict(
            "conversation Goal objective does not match immutable HUMAN intent"
        )
    return goal_id


def _create_goal_once(
    runtime: OriginForgeRuntime,
    submission_id: str,
    objective: str,
) -> str:
    existing = _read_admitted_goal_id(runtime, submission_id, objective)
    if existing is not None:
        return existing

    project_id = runtime.project_id()
    try:
        created = runtime.store.create_goal(
            project_id,
            objective,
            actor_type="CONVERSATION",
            actor_id=submission_id,
        )
    except sqlite3.IntegrityError as exc:
        recovered = _read_admitted_goal_id(runtime, submission_id, objective)
        if recovered is None:
            raise ConversationProductionConflict(
                "conversation Goal admission conflicted without recoverable authority"
            ) from exc
        return recovered

    recovered = _read_admitted_goal_id(runtime, submission_id, objective)
    if recovered is None:
        raise ConversationInvariantError(
            "created conversation Goal lacks its durable GOAL_CREATED authority event"
        )
    if recovered != created:
        raise ConversationProductionConflict(
            "created Goal identity differs from durable conversation authority"
        )
    return recovered


def admit_conversation_goal(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationGoalAdmission:
    """Admit one HUMAN Turn as one durable Goal, without bootstrapping or dispatching it.

    This is the Gate-C1 mutation boundary. The operation binding is committed
    before PROCESSING. Goal creation uses the existing typed Goal store authority;
    its GOAL_CREATED event is uniquely keyed by the CONVSUB identity so retries,
    process restarts, and concurrent processors converge on one Goal.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(submission_id, str) or not validate_id(
        submission_id, IdKind.CONVERSATION_SUBMISSION
    ):
        raise ValueError("submission_id must be a CONVSUB ID")

    try:
        bind_conversation_submission_operation(
            runtime,
            submission_id,
            ConversationOperation.PRODUCTION_CREATE_GOAL,
        )
        receipt = claim_conversation_submission(runtime, submission_id)
    except (ConversationOperationConflict, ConversationProcessingConflict) as exc:
        raise ConversationProductionConflict(str(exc)) from exc

    if receipt.status is ConversationSubmissionStatus.FAILED:
        raise ConversationProcessingFailed(
            f"conversation submission failed with {receipt.failure_code}"
        )
    if receipt.status not in {
        ConversationSubmissionStatus.PROCESSING,
        ConversationSubmissionStatus.RESPONDED,
    }:
        raise ConversationProductionConflict(
            "production Goal admission requires PROCESSING or RESPONDED submission state"
        )

    human_turn = _read_human_turn(runtime, receipt)
    if receipt.status is ConversationSubmissionStatus.RESPONDED:
        goal_id = _read_admitted_goal_id(runtime, submission_id, human_turn.content)
        if goal_id is None:
            raise ConversationProductionConflict(
                "RESPONDED production submission has no durable Goal admission"
            )
    else:
        goal_id = _create_goal_once(runtime, submission_id, human_turn.content)

    ensure_conversation_turn_reference(
        runtime,
        human_turn.id,
        ConversationReferenceType.GOAL,
        goal_id,
        ConversationReferenceRelation.RESULT,
    )
    return ConversationGoalAdmission(
        submission=receipt,
        human_turn=human_turn,
        goal_id=goal_id,
    )
