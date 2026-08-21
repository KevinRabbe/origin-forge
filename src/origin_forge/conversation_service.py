from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .ids import IdKind, new_id, validate_id
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


MAX_CONVERSATION_CONTENT_BYTES = 64 * 1024
MAX_CLIENT_SUBMISSION_ID_BYTES = 256
MAX_CONVERSATION_READ_LIMIT = 1_000
DEFAULT_SESSION_READ_LIMIT = 100
DEFAULT_TURN_READ_LIMIT = 200


class ConversationError(RuntimeError):
    pass


class ConversationConflict(ConversationError):
    pass


class ConversationInvariantError(ConversationError):
    pass


class ConversationSessionStatus(StrEnum):
    OPEN = "OPEN"
    ARCHIVED = "ARCHIVED"


class ConversationActorType(StrEnum):
    HUMAN = "HUMAN"
    FORGE = "FORGE"
    SYSTEM = "SYSTEM"


class ConversationSubmissionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    RESPONDED = "RESPONDED"
    FAILED = "FAILED"


def _valid_id(value: object, kind: IdKind) -> bool:
    return isinstance(value, str) and validate_id(value, kind)


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _read_limit(value: int, *, name: str = "limit") -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONVERSATION_READ_LIMIT:
        raise ValueError(
            f"{name} must be an integer from 1 to {MAX_CONVERSATION_READ_LIMIT}"
        )
    return value


def _after_sequence(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("after_sequence must be a non-negative integer")
    return value


def _submission_key(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("client_submission_id must be a string")
    encoded = value.encode("utf-8")
    if not value or value.strip() != value or len(encoded) > MAX_CLIENT_SUBMISSION_ID_BYTES:
        raise ValueError(
            "client_submission_id must be non-empty canonical text within the byte limit"
        )
    return value


def _human_content(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("content must be a string")
    encoded = value.encode("utf-8")
    if not value or len(encoded) > MAX_CONVERSATION_CONTENT_BYTES:
        raise ValueError("content must be non-empty UTF-8 text within the byte limit")
    return value


@dataclass(frozen=True)
class ConversationSession:
    id: str
    project_id: str
    status: ConversationSessionStatus
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not _valid_id(self.id, IdKind.CONVERSATION_SESSION):
            raise ConversationInvariantError("session id must be a CONV ID")
        if not _valid_id(self.project_id, IdKind.PROJECT):
            raise ConversationInvariantError("project_id must be a PROJECT ID")
        if type(self.revision) is not int or self.revision < 0:
            raise ConversationInvariantError("session revision is invalid")
        if not _valid_timestamp(self.created_at) or not _valid_timestamp(self.updated_at):
            raise ConversationInvariantError("session timestamps are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ConversationTurn:
    id: str
    session_id: str
    sequence: int
    actor_type: ConversationActorType
    content: str
    content_hash: str
    client_submission_id: str | None
    created_at: str

    def __post_init__(self) -> None:
        if not _valid_id(self.id, IdKind.CONVERSATION_TURN):
            raise ConversationInvariantError("turn id must be a TURN ID")
        if not _valid_id(self.session_id, IdKind.CONVERSATION_SESSION):
            raise ConversationInvariantError("turn session_id must be a CONV ID")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ConversationInvariantError("turn sequence is invalid")
        try:
            content = _human_content(self.content)
        except (TypeError, ValueError) as exc:
            raise ConversationInvariantError("stored turn content is invalid") from exc
        if self.content_hash != _content_hash(content):
            raise ConversationInvariantError("turn content hash does not match content")
        if self.actor_type is ConversationActorType.HUMAN:
            if self.client_submission_id is None:
                raise ConversationInvariantError(
                    "HUMAN turn requires client_submission_id"
                )
            try:
                _submission_key(self.client_submission_id)
            except (TypeError, ValueError) as exc:
                raise ConversationInvariantError(
                    "stored HUMAN client_submission_id is invalid"
                ) from exc
        elif self.client_submission_id is not None:
            raise ConversationInvariantError(
                "non-HUMAN turn may not carry client_submission_id"
            )
        if not _valid_timestamp(self.created_at):
            raise ConversationInvariantError("turn created_at is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "actor_type": self.actor_type.value,
            "content": self.content,
            "content_hash": self.content_hash,
            "client_submission_id": self.client_submission_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ConversationSubmissionReceipt:
    id: str
    session_id: str
    human_turn_id: str
    status: ConversationSubmissionStatus
    expected_session_revision: int
    response_turn_id: str | None
    failure_code: str | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not _valid_id(self.id, IdKind.CONVERSATION_SUBMISSION):
            raise ConversationInvariantError("submission id must be a CONVSUB ID")
        if not _valid_id(self.session_id, IdKind.CONVERSATION_SESSION):
            raise ConversationInvariantError("submission session_id must be a CONV ID")
        if not _valid_id(self.human_turn_id, IdKind.CONVERSATION_TURN):
            raise ConversationInvariantError("human_turn_id must be a TURN ID")
        if type(self.expected_session_revision) is not int or self.expected_session_revision < 0:
            raise ConversationInvariantError(
                "submission expected_session_revision is invalid"
            )
        if self.status in (
            ConversationSubmissionStatus.ACCEPTED,
            ConversationSubmissionStatus.PROCESSING,
        ):
            if self.response_turn_id is not None or self.failure_code is not None:
                raise ConversationInvariantError(
                    "non-terminal submission contains terminal detail"
                )
        elif self.status is ConversationSubmissionStatus.RESPONDED:
            if not _valid_id(self.response_turn_id, IdKind.CONVERSATION_TURN):
                raise ConversationInvariantError(
                    "RESPONDED submission requires response TURN ID"
                )
            if self.failure_code is not None:
                raise ConversationInvariantError(
                    "RESPONDED submission may not contain failure_code"
                )
        elif self.status is ConversationSubmissionStatus.FAILED:
            if self.response_turn_id is not None:
                raise ConversationInvariantError(
                    "FAILED submission may not contain response_turn_id"
                )
            if (
                not isinstance(self.failure_code, str)
                or not self.failure_code
                or self.failure_code.strip() != self.failure_code
            ):
                raise ConversationInvariantError(
                    "FAILED submission requires bounded failure_code"
                )
        if not _valid_timestamp(self.created_at) or not _valid_timestamp(self.updated_at):
            raise ConversationInvariantError("submission timestamps are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "human_turn_id": self.human_turn_id,
            "status": self.status.value,
            "expected_session_revision": self.expected_session_revision,
            "response_turn_id": self.response_turn_id,
            "failure_code": self.failure_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
            "stored conversation session failed canonical validation"
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
            "stored conversation turn failed canonical validation"
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
            "stored conversation submission failed canonical validation"
        ) from exc


def create_conversation_session(runtime: OriginForgeRuntime) -> ConversationSession:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    project_id = runtime.project_id()
    session_id = new_id(IdKind.CONVERSATION_SESSION)
    now = utc_now()
    candidate = ConversationSession(
        id=session_id,
        project_id=project_id,
        status=ConversationSessionStatus.OPEN,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    with runtime.store.session() as conn:
        conn.execute(
            """INSERT INTO conversation_sessions(
                   id, project_id, status, revision, created_at, updated_at
               ) VALUES (?, ?, 'OPEN', 0, ?, ?)""",
            (session_id, project_id, now, now),
        )
        row = conn.execute(
            "SELECT * FROM conversation_sessions WHERE id = ? AND project_id = ?",
            (session_id, project_id),
        ).fetchone()
    if row is None:
        raise ConversationInvariantError(
            "conversation session disappeared during creation"
        )
    stored = _session_from_row(row)
    if stored != candidate:
        raise ConversationInvariantError(
            "conversation session changed during creation"
        )
    return stored


def read_conversation_session(
    runtime: OriginForgeRuntime,
    session_id: str,
) -> ConversationSession:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(session_id, IdKind.CONVERSATION_SESSION):
        raise ValueError("session_id must be a CONV ID")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            "SELECT * FROM conversation_sessions WHERE id = ? AND project_id = ?",
            (session_id, project_id),
        ).fetchone()
    if row is None:
        raise KeyError(session_id)
    return _session_from_row(row)


def list_conversation_sessions(
    runtime: OriginForgeRuntime,
    *,
    limit: int = DEFAULT_SESSION_READ_LIMIT,
) -> tuple[ConversationSession, ...]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    normalized_limit = _read_limit(limit)
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT * FROM conversation_sessions
               WHERE project_id = ?
               ORDER BY updated_at DESC, created_at DESC, id DESC
               LIMIT ?""",
            (project_id, normalized_limit),
        ).fetchall()
    return tuple(_session_from_row(row) for row in rows)


def list_conversation_turns(
    runtime: OriginForgeRuntime,
    session_id: str,
    *,
    after_sequence: int = 0,
    limit: int = DEFAULT_TURN_READ_LIMIT,
) -> tuple[ConversationTurn, ...]:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(session_id, IdKind.CONVERSATION_SESSION):
        raise ValueError("session_id must be a CONV ID")
    normalized_after = _after_sequence(after_sequence)
    normalized_limit = _read_limit(limit)
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        session = conn.execute(
            "SELECT id FROM conversation_sessions WHERE id = ? AND project_id = ?",
            (session_id, project_id),
        ).fetchone()
        if session is None:
            raise KeyError(session_id)
        rows = conn.execute(
            """SELECT * FROM conversation_turns
               WHERE session_id = ? AND sequence > ?
               ORDER BY sequence, id
               LIMIT ?""",
            (session_id, normalized_after, normalized_limit),
        ).fetchall()
    return tuple(_turn_from_row(row) for row in rows)


def read_conversation_submission(
    runtime: OriginForgeRuntime,
    submission_id: str,
) -> ConversationSubmissionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(submission_id, IdKind.CONVERSATION_SUBMISSION):
        raise ValueError("submission_id must be a CONVSUB ID")
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        row = conn.execute(
            """SELECT s.*
               FROM conversation_submissions AS s
               JOIN conversation_sessions AS cs ON cs.id = s.session_id
               WHERE s.id = ? AND cs.project_id = ?""",
            (submission_id, project_id),
        ).fetchone()
    if row is None:
        raise KeyError(submission_id)
    return _submission_from_row(row)


def submit_human_turn(
    runtime: OriginForgeRuntime,
    session_id: str,
    content: str,
    client_submission_id: str,
    *,
    expected_revision: int,
) -> ConversationSubmissionReceipt:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not _valid_id(session_id, IdKind.CONVERSATION_SESSION):
        raise ValueError("session_id must be a CONV ID")
    normalized_content = _human_content(content)
    normalized_key = _submission_key(client_submission_id)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")

    project_id = runtime.project_id()
    expected_hash = _content_hash(normalized_content)
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        session_row = conn.execute(
            "SELECT * FROM conversation_sessions WHERE id = ? AND project_id = ?",
            (session_id, project_id),
        ).fetchone()
        if session_row is None:
            raise KeyError(session_id)
        session = _session_from_row(session_row)

        existing_turn_row = conn.execute(
            """SELECT * FROM conversation_turns
               WHERE session_id = ? AND client_submission_id = ?""",
            (session_id, normalized_key),
        ).fetchone()
        if existing_turn_row is not None:
            existing_turn = _turn_from_row(existing_turn_row)
            if (
                existing_turn.actor_type is not ConversationActorType.HUMAN
                or existing_turn.content_hash != expected_hash
                or existing_turn.content != normalized_content
            ):
                raise ConversationConflict(
                    "client_submission_id is already bound to different content"
                )
            receipt_row = conn.execute(
                """SELECT * FROM conversation_submissions
                   WHERE session_id = ? AND human_turn_id = ?""",
                (session_id, existing_turn.id),
            ).fetchone()
            if receipt_row is None:
                raise ConversationInvariantError(
                    "idempotent HUMAN turn is missing its durable submission receipt"
                )
            return _submission_from_row(receipt_row)

        if session.status is not ConversationSessionStatus.OPEN:
            raise ConversationConflict("conversation session is not open")
        if session.revision != expected_revision:
            raise StaleRevision(
                f"conversation session {session_id} revision {session.revision} "
                f"!= expected {expected_revision}"
            )

        now = utc_now()
        turn_id = new_id(IdKind.CONVERSATION_TURN)
        submission_id = new_id(IdKind.CONVERSATION_SUBMISSION)
        sequence = session.revision + 1
        turn = ConversationTurn(
            id=turn_id,
            session_id=session_id,
            sequence=sequence,
            actor_type=ConversationActorType.HUMAN,
            content=normalized_content,
            content_hash=expected_hash,
            client_submission_id=normalized_key,
            created_at=now,
        )
        receipt = ConversationSubmissionReceipt(
            id=submission_id,
            session_id=session_id,
            human_turn_id=turn_id,
            status=ConversationSubmissionStatus.ACCEPTED,
            expected_session_revision=expected_revision,
            response_turn_id=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
        )

        try:
            conn.execute(
                """INSERT INTO conversation_turns(
                       id, session_id, sequence, actor_type, content, content_hash,
                       client_submission_id, created_at
                   ) VALUES (?, ?, ?, 'HUMAN', ?, ?, ?, ?)""",
                (
                    turn_id,
                    session_id,
                    sequence,
                    normalized_content,
                    expected_hash,
                    normalized_key,
                    now,
                ),
            )
            cursor = conn.execute(
                """UPDATE conversation_sessions
                   SET revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND status = 'OPEN' AND revision = ?""",
                (
                    sequence,
                    now,
                    session_id,
                    project_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRevision(
                    f"conversation session {session_id} changed concurrently"
                )
            conn.execute(
                """INSERT INTO conversation_submissions(
                       id, session_id, human_turn_id, status,
                       expected_session_revision, response_turn_id, failure_code,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, 'ACCEPTED', ?, NULL, NULL, ?, ?)""",
                (
                    submission_id,
                    session_id,
                    turn_id,
                    expected_revision,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConversationConflict(
                "conversation submission violated durable ordering or idempotency"
            ) from exc

        stored_turn_row = conn.execute(
            "SELECT * FROM conversation_turns WHERE id = ?",
            (turn_id,),
        ).fetchone()
        stored_receipt_row = conn.execute(
            "SELECT * FROM conversation_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
        if stored_turn_row is None or stored_receipt_row is None:
            raise ConversationInvariantError(
                "conversation submission disappeared during transaction"
            )
        if _turn_from_row(stored_turn_row) != turn:
            raise ConversationInvariantError(
                "conversation turn changed during transaction"
            )
        if _submission_from_row(stored_receipt_row) != receipt:
            raise ConversationInvariantError(
                "conversation submission receipt changed during transaction"
            )
        return receipt
