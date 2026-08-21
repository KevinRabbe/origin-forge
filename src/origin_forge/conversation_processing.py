from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .conversation_service import (
    MAX_CONVERSATION_CONTENT_BYTES,
    ConversationActorType,
    ConversationInvariantError,
    ConversationSession,
    ConversationSessionStatus,
    ConversationSubmissionReceipt,
    ConversationSubmissionStatus,
    ConversationTurn,
)
from .ids import IdKind, new_id, validate_id
from .runtime import OriginForgeRuntime
from .service import utc_now


MAX_CONVERSATION_FAILURE_CODE_BYTES = 128


class ConversationProcessingError(RuntimeError):
    pass


class ConversationProcessingConflict(ConversationProcessingError):
    pass


class ConversationProcessingFailed(ConversationProcessingError):
    pass


class ConversationReadOnlyInspection(StrEnum):
    PROJECT_COUNTS = "PROJECT_COUNTS"


@dataclass(frozen=True)
class ConversationProcessingResult:
    submission: ConversationSubmissionReceipt
    response_turn: ConversationTurn

    def __post_init__(self) -> None:
        if self.submission.status is not ConversationSubmissionStatus.RESPONDED:
            raise ConversationInvariantError(
                "processing result requires a RESPONDED submission"
            )
        if self.response_turn.actor_type is not ConversationActorType.FORGE:
            raise ConversationInvariantError(
                "processing result requires a FORGE response turn"
            )
        if self.submission.response_turn_id != self.response_turn.id:
            raise ConversationInvariantError(
                "processing result response identity does not match submission"
            )
        if self.submission.session_id != self.response_turn.session_id:
            raise ConversationInvariantError(
                "processing result response belongs to a different session"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "submission": self.submission.to_dict(),
            "response_turn": self.response_turn.to_dict(),
        }


def _valid_id(value: object, kind: IdKind) -> bool:
    return isinstance(value, str) and validate_id(value, kind)


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _response_content(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("response content must be a string")
    encoded = value.encode("utf-8")
    if not value or len(encoded) > MAX_CONVERSATION_CONTENT_BYTES:
        raise ValueError(
            "response content must be non-empty UTF-8 text within the byte limit"
        )
    return value


def _failure_code(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("failure_code must be a string")
    encoded = value.encode("utf-8")
    if (
        not value
        or value.strip() != value
        or len(encoded) > MAX_CONVERSATION_FAILURE_CODE_BYTES
    ):
        raise ValueError(
            "failure_code must be non-empty canonical text within the byte limit"
        )
    return value


def _session_from_row(row) -> ConversationSession:
    try:
        return ConversationSession(
            id=row["id"],
            project_id=row["project_id"],
            status=ConversationSessionStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError, ConversationInvariantError) as exc:
        raise ConversationInvariantError(
            "stored processing session failed canonical validation"
        ) from exc


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
            "stored processing turn failed canonical validation"
        ) from exc


def _submission_from_row(row) -> ConversationSubmissionReceipt:
    try:
        return ConversationSubmissionReceipt(
            id=row["id"],
            session_id=row["session_id"],
            human_turn_id=row["human_turn_id"],
            status=ConversationSubmissionStatus(row["status"]),
            expected_session_revision=int(row["expected_session_revision"]),
            response_turn_id=row["response_turn_id"],
            failure_code=row["failure_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError, ConversationInvariantError) as exc:
        raise ConversationInvariantError(
            "stored processing submission failed canonical validation"
        ) from exc


def _read_submission_row(conn, submission_id: str, project_id: str):
    return conn.execute(
        """SELECT s.*
           FROM conversation_submissions AS s
           JOIN conversation_sessions AS cs ON cs.id = s.session_id
           WHERE s.id = ? AND cs.project_id = ?""",
        (submission_id, project_id),
    ).fetchone()


def _read_response_turn(conn, receipt: ConversationSubmissionReceipt) -> ConversationTurn:
    if receipt.status is not ConversationSubmissionStatus.RESPONDED:
        raise ConversationInvariantError(
            "response turn requested for a non-RESPONDED submission"
        )
    row = conn.execute(
        "SELECT * FROM conversation_turns WHERE id = ? AND session_id = ?",
        (receipt.response_turn_id, receipt.session_id),
    ).fetchone()
    if row is None:
        raise ConversationInvariantError(
            "RESPONDED submission is missing its durable response turn"
        )
    turn = _turn_from_row(row)
    if turn.actor_type is not ConversationActorType.FORGE:
        raise ConversationInvariantError(
            "RESPONDED submission does not point to a FORGE turn"
        )
    return turn


def claim_conversation_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationSubmissionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")

    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _read_submission_row(conn, submission_id, project_id)
        if row is None:
            raise KeyError(submission_id)
        receipt = _submission_from_row(row)
        if receipt.status is not ConversationSubmissionStatus.ACCEPTED:
            return receipt

        now = utc_now()
        cursor = conn.execute(
            """UPDATE conversation_submissions
               SET status = 'PROCESSING', updated_at = ?
               WHERE id = ? AND status = 'ACCEPTED'
                 AND response_turn_id IS NULL AND failure_code IS NULL""",
            (now, submission_id),
        )
        if cursor.rowcount != 1:
            raise ConversationProcessingConflict(
                "conversation submission changed while processing was claimed"
            )
        stored_row = _read_submission_row(conn, submission_id, project_id)
        if stored_row is None:
            raise ConversationInvariantError(
                "claimed conversation submission disappeared during transaction"
            )
        stored = _submission_from_row(stored_row)
        if stored.status is not ConversationSubmissionStatus.PROCESSING:
            raise ConversationInvariantError(
                "claimed conversation submission did not enter PROCESSING"
            )
        return stored


def _complete_conversation_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
    response_content: str,
) -> ConversationProcessingResult:
    normalized_content = _response_content(response_content)
    project_id = runtime.project_id()

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        submission_row = _read_submission_row(conn, submission_id, project_id)
        if submission_row is None:
            raise KeyError(submission_id)
        receipt = _submission_from_row(submission_row)

        if receipt.status is ConversationSubmissionStatus.RESPONDED:
            return ConversationProcessingResult(
                submission=receipt,
                response_turn=_read_response_turn(conn, receipt),
            )
        if receipt.status is ConversationSubmissionStatus.FAILED:
            raise ConversationProcessingFailed(
                f"conversation submission failed with {receipt.failure_code}"
            )
        if receipt.status is not ConversationSubmissionStatus.PROCESSING:
            raise ConversationProcessingConflict(
                "conversation submission must be PROCESSING before completion"
            )

        session_row = conn.execute(
            """SELECT * FROM conversation_sessions
               WHERE id = ? AND project_id = ?""",
            (receipt.session_id, project_id),
        ).fetchone()
        if session_row is None:
            raise ConversationInvariantError(
                "processing submission session is missing"
            )
        session = _session_from_row(session_row)
        if session.status is not ConversationSessionStatus.OPEN:
            raise ConversationProcessingConflict(
                "conversation session is not open for a FORGE response"
            )

        human_row = conn.execute(
            """SELECT * FROM conversation_turns
               WHERE id = ? AND session_id = ?""",
            (receipt.human_turn_id, receipt.session_id),
        ).fetchone()
        if human_row is None:
            raise ConversationInvariantError(
                "processing submission is missing its HUMAN turn"
            )
        human_turn = _turn_from_row(human_row)
        if human_turn.actor_type is not ConversationActorType.HUMAN:
            raise ConversationInvariantError(
                "processing submission human_turn_id is not a HUMAN turn"
            )

        now = utc_now()
        response_turn_id = new_id(IdKind.CONVERSATION_TURN)
        response_sequence = session.revision + 1
        response_turn = ConversationTurn(
            id=response_turn_id,
            session_id=receipt.session_id,
            sequence=response_sequence,
            actor_type=ConversationActorType.FORGE,
            content=normalized_content,
            content_hash=_content_hash(normalized_content),
            client_submission_id=None,
            created_at=now,
        )

        try:
            conn.execute(
                """INSERT INTO conversation_turns(
                       id, session_id, sequence, actor_type, content, content_hash,
                       client_submission_id, created_at
                   ) VALUES (?, ?, ?, 'FORGE', ?, ?, NULL, ?)""",
                (
                    response_turn.id,
                    response_turn.session_id,
                    response_turn.sequence,
                    response_turn.content,
                    response_turn.content_hash,
                    response_turn.created_at,
                ),
            )
            session_cursor = conn.execute(
                """UPDATE conversation_sessions
                   SET revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND status = 'OPEN' AND revision = ?""",
                (
                    response_sequence,
                    now,
                    receipt.session_id,
                    project_id,
                    session.revision,
                ),
            )
            if session_cursor.rowcount != 1:
                raise ConversationProcessingConflict(
                    "conversation session changed while response was committed"
                )
            submission_cursor = conn.execute(
                """UPDATE conversation_submissions
                   SET status = 'RESPONDED', response_turn_id = ?, updated_at = ?
                   WHERE id = ? AND status = 'PROCESSING'
                     AND response_turn_id IS NULL AND failure_code IS NULL""",
                (response_turn_id, now, submission_id),
            )
            if submission_cursor.rowcount != 1:
                raise ConversationProcessingConflict(
                    "conversation submission changed while response was committed"
                )
        except sqlite3.IntegrityError as exc:
            raise ConversationProcessingConflict(
                "conversation response violated durable ordering or linkage"
            ) from exc

        stored_submission_row = _read_submission_row(conn, submission_id, project_id)
        stored_turn_row = conn.execute(
            "SELECT * FROM conversation_turns WHERE id = ?",
            (response_turn_id,),
        ).fetchone()
        if stored_submission_row is None or stored_turn_row is None:
            raise ConversationInvariantError(
                "conversation response disappeared during transaction"
            )
        stored_submission = _submission_from_row(stored_submission_row)
        stored_turn = _turn_from_row(stored_turn_row)
        if stored_submission.status is not ConversationSubmissionStatus.RESPONDED:
            raise ConversationInvariantError(
                "conversation response did not finalize its submission"
            )
        if stored_turn != response_turn:
            raise ConversationInvariantError(
                "conversation response turn changed during transaction"
            )
        return ConversationProcessingResult(
            submission=stored_submission,
            response_turn=stored_turn,
        )


def fail_conversation_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
    failure_code: str,
) -> ConversationSubmissionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")
    normalized_code = _failure_code(failure_code)
    project_id = runtime.project_id()

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _read_submission_row(conn, submission_id, project_id)
        if row is None:
            raise KeyError(submission_id)
        receipt = _submission_from_row(row)
        if receipt.status in (
            ConversationSubmissionStatus.RESPONDED,
            ConversationSubmissionStatus.FAILED,
        ):
            return receipt
        if receipt.status is not ConversationSubmissionStatus.PROCESSING:
            raise ConversationProcessingConflict(
                "conversation submission must be PROCESSING before failure"
            )

        now = utc_now()
        cursor = conn.execute(
            """UPDATE conversation_submissions
               SET status = 'FAILED', failure_code = ?, updated_at = ?
               WHERE id = ? AND status = 'PROCESSING'
                 AND response_turn_id IS NULL AND failure_code IS NULL""",
            (normalized_code, now, submission_id),
        )
        if cursor.rowcount != 1:
            raise ConversationProcessingConflict(
                "conversation submission changed while failure was committed"
            )
        stored_row = _read_submission_row(conn, submission_id, project_id)
        if stored_row is None:
            raise ConversationInvariantError(
                "failed conversation submission disappeared during transaction"
            )
        stored = _submission_from_row(stored_row)
        if (
            stored.status is not ConversationSubmissionStatus.FAILED
            or stored.failure_code != normalized_code
        ):
            raise ConversationInvariantError(
                "conversation failure changed during transaction"
            )
        return stored


def _project_counts_response(runtime: OriginForgeRuntime) -> str:
    goals = runtime.count_goals()
    flows = runtime.count_flows()
    tasks = runtime.count_tasks()
    runs = runtime.count_runs()
    return (
        "Read-only project counts at response creation: "
        f"Goals {goals}; Flows {flows}; Tasks {tasks}; Runs {runs}."
    )


def _read_existing_result(
    runtime: OriginForgeRuntime,
    receipt: ConversationSubmissionReceipt,
) -> ConversationProcessingResult:
    if receipt.status is not ConversationSubmissionStatus.RESPONDED:
        raise ConversationInvariantError(
            "existing processing result requires RESPONDED status"
        )
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = _read_submission_row(conn, receipt.id, project_id)
        if row is None:
            raise KeyError(receipt.id)
        stored = _submission_from_row(row)
        return ConversationProcessingResult(
            submission=stored,
            response_turn=_read_response_turn(conn, stored),
        )


def process_read_only_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
    inspection: ConversationReadOnlyInspection,
) -> ConversationProcessingResult:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")
    if not isinstance(inspection, ConversationReadOnlyInspection):
        raise TypeError("inspection must be a ConversationReadOnlyInspection")

    receipt = claim_conversation_submission(runtime, submission_id)
    if receipt.status is ConversationSubmissionStatus.RESPONDED:
        return _read_existing_result(runtime, receipt)
    if receipt.status is ConversationSubmissionStatus.FAILED:
        raise ConversationProcessingFailed(
            f"conversation submission failed with {receipt.failure_code}"
        )
    if receipt.status is not ConversationSubmissionStatus.PROCESSING:
        raise ConversationInvariantError(
            "claimed conversation submission is not processable"
        )

    try:
        if inspection is ConversationReadOnlyInspection.PROJECT_COUNTS:
            response_content = _project_counts_response(runtime)
        else:
            raise ConversationProcessingError(
                "unsupported read-only conversation inspection"
            )
    except Exception as exc:
        terminal = fail_conversation_submission(
            runtime,
            submission_id,
            "READ_ONLY_INSPECTION_FAILED",
        )
        if terminal.status is ConversationSubmissionStatus.RESPONDED:
            return _read_existing_result(runtime, terminal)
        raise ConversationProcessingError(
            "read-only conversation inspection failed"
        ) from exc

    return _complete_conversation_submission(
        runtime,
        submission_id,
        response_content,
    )
