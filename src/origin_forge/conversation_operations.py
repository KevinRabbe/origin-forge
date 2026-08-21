from __future__ import annotations

import sqlite3
from enum import StrEnum

from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime
from .service import utc_now


class ConversationOperationConflict(RuntimeError):
    pass


class ConversationOperation(StrEnum):
    READ_ONLY_PROJECT_COUNTS = "READ_ONLY_PROJECT_COUNTS"
    PRODUCTION_CREATE_GOAL = "PRODUCTION_CREATE_GOAL"


class ConversationReferenceType(StrEnum):
    GOAL = "GOAL"
    FLOW = "FLOW"
    TASK = "TASK"


class ConversationReferenceRelation(StrEnum):
    RESULT = "RESULT"


def _valid_id(value: object, kind: IdKind) -> bool:
    return isinstance(value, str) and validate_id(value, kind)


def bind_conversation_submission_operation(
    runtime: OriginForgeRuntime,
    submission_id: str,
    operation: ConversationOperation,
) -> ConversationOperation:
    """Bind one non-terminal submission to one semantic operation exactly once."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")
    if not isinstance(operation, ConversationOperation):
        raise TypeError("operation must be a ConversationOperation")

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        submission = conn.execute(
            """SELECT s.status
               FROM conversation_submissions AS s
               JOIN conversation_sessions AS cs ON cs.id = s.session_id
               WHERE s.id = ? AND cs.project_id = ?""",
            (submission_id, project_id),
        ).fetchone()
        if submission is None:
            raise KeyError(submission_id)

        existing = conn.execute(
            """SELECT operation_kind
               FROM conversation_submission_operations
               WHERE submission_id = ?""",
            (submission_id,),
        ).fetchone()
        if existing is not None:
            try:
                stored = ConversationOperation(existing["operation_kind"])
            except ValueError as exc:
                raise ConversationOperationConflict(
                    "stored conversation operation is invalid"
                ) from exc
            if stored is not operation:
                raise ConversationOperationConflict(
                    f"conversation submission is already bound to {stored.value}"
                )
            return stored

        if submission["status"] not in {"ACCEPTED", "PROCESSING"}:
            raise ConversationOperationConflict(
                "unbound terminal conversation submission cannot be reclassified"
            )

        try:
            conn.execute(
                """INSERT INTO conversation_submission_operations(
                       submission_id, operation_kind, created_at
                   ) VALUES (?, ?, ?)""",
                (submission_id, operation.value, utc_now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ConversationOperationConflict(
                "conversation operation binding conflicted with durable state"
            ) from exc
        return operation


def read_conversation_submission_operation(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationOperation | None:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            """SELECT op.operation_kind
               FROM conversation_submission_operations AS op
               JOIN conversation_submissions AS s ON s.id = op.submission_id
               JOIN conversation_sessions AS cs ON cs.id = s.session_id
               WHERE op.submission_id = ? AND cs.project_id = ?""",
            (submission_id, project_id),
        ).fetchone()
    if row is None:
        return None
    try:
        return ConversationOperation(row["operation_kind"])
    except ValueError as exc:
        raise ConversationOperationConflict(
            "stored conversation operation is invalid"
        ) from exc


def _target_exists(
    conn,
    project_id: str,
    reference_type: ConversationReferenceType,
    reference_id: str,
) -> bool:
    if reference_type is ConversationReferenceType.GOAL:
        row = conn.execute(
            "SELECT 1 FROM goals WHERE id = ? AND project_id = ?",
            (reference_id, project_id),
        ).fetchone()
    elif reference_type is ConversationReferenceType.FLOW:
        row = conn.execute(
            """SELECT 1
               FROM flows AS f
               JOIN goals AS g ON g.id = f.goal_id
               WHERE f.id = ? AND g.project_id = ?""",
            (reference_id, project_id),
        ).fetchone()
    elif reference_type is ConversationReferenceType.TASK:
        row = conn.execute(
            """SELECT 1
               FROM tasks AS t
               JOIN flows AS f ON f.id = t.flow_id
               JOIN goals AS g ON g.id = f.goal_id
               WHERE t.id = ? AND g.project_id = ?""",
            (reference_id, project_id),
        ).fetchone()
    else:
        raise TypeError("unsupported conversation reference type")
    return row is not None


def ensure_conversation_turn_reference(
    runtime: OriginForgeRuntime,
    turn_id: str,
    reference_type: ConversationReferenceType,
    reference_id: str,
    relation: ConversationReferenceRelation,
) -> None:
    """Idempotently link one project-owned Turn to one project-owned durable record."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(turn_id, IdKind.CONVERSATION_TURN):
        raise ValueError("turn_id must be a TURN ID")
    if not isinstance(reference_type, ConversationReferenceType):
        raise TypeError("reference_type must be a ConversationReferenceType")
    if not isinstance(relation, ConversationReferenceRelation):
        raise TypeError("relation must be a ConversationReferenceRelation")
    expected_kind = {
        ConversationReferenceType.GOAL: IdKind.GOAL,
        ConversationReferenceType.FLOW: IdKind.FLOW,
        ConversationReferenceType.TASK: IdKind.TASK,
    }[reference_type]
    if not _valid_id(reference_id, expected_kind):
        raise ValueError(
            f"reference_id must be a {expected_kind.value} ID for {reference_type.value}"
        )

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        turn = conn.execute(
            """SELECT ct.id
               FROM conversation_turns AS ct
               JOIN conversation_sessions AS cs ON cs.id = ct.session_id
               WHERE ct.id = ? AND cs.project_id = ?""",
            (turn_id, project_id),
        ).fetchone()
        if turn is None:
            raise KeyError(turn_id)
        if not _target_exists(conn, project_id, reference_type, reference_id):
            raise KeyError(reference_id)
        conn.execute(
            """INSERT OR IGNORE INTO conversation_turn_references(
                   turn_id, reference_type, reference_id, relation, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                turn_id,
                reference_type.value,
                reference_id,
                relation.value,
                utc_now(),
            ),
        )
