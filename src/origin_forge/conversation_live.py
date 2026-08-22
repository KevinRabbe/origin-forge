from __future__ import annotations

from dataclasses import dataclass

from .conversation_service import (
    ConversationSession,
    ConversationSubmissionStatus,
    ConversationTurn,
    list_conversation_turns,
    read_conversation_session,
)
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


MAX_LIVE_TURNS = 48
MAX_LIVE_SUBMISSIONS = 48
MAX_LIVE_TASKS = 32
MAX_LIVE_RUNS_PER_TASK = 64


class ConversationLiveError(RuntimeError):
    pass


class ConversationLiveInvariantError(ConversationLiveError):
    pass


def _bounded_limit(value: int, *, maximum: int, name: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    return value


def _non_negative_optional_int(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ConversationLiveInvariantError(f"stored {name} is invalid")
    return value


@dataclass(frozen=True)
class ConversationLiveSubmission:
    id: str
    human_turn_id: str
    human_turn_sequence: int
    status: ConversationSubmissionStatus
    response_turn_id: str | None
    failure_code: str | None
    updated_at: str

    def __post_init__(self) -> None:
        if not validate_id(self.id, IdKind.CONVERSATION_SUBMISSION):
            raise ConversationLiveInvariantError("live submission id is invalid")
        if not validate_id(self.human_turn_id, IdKind.CONVERSATION_TURN):
            raise ConversationLiveInvariantError("live submission HUMAN turn id is invalid")
        if type(self.human_turn_sequence) is not int or self.human_turn_sequence < 1:
            raise ConversationLiveInvariantError("live submission sequence is invalid")
        if self.response_turn_id is not None and not validate_id(
            self.response_turn_id, IdKind.CONVERSATION_TURN
        ):
            raise ConversationLiveInvariantError("live response turn id is invalid")
        if not isinstance(self.updated_at, str) or not self.updated_at:
            raise ConversationLiveInvariantError("live submission updated_at is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "human_turn_id": self.human_turn_id,
            "human_turn_sequence": self.human_turn_sequence,
            "status": self.status.value,
            "response_turn_id": self.response_turn_id,
            "failure_code": self.failure_code,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ConversationLiveRunTelemetry:
    id: str
    status: str
    role: str
    model_profile: str | None
    input_token_count: int | None
    output_token_count: int | None
    started_at: str
    ended_at: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.id, IdKind.RUN):
            raise ConversationLiveInvariantError("live Run id is invalid")
        if not isinstance(self.status, str) or not self.status:
            raise ConversationLiveInvariantError("live Run status is invalid")
        if not isinstance(self.role, str) or not self.role:
            raise ConversationLiveInvariantError("live Run role is invalid")
        if self.model_profile is not None and not isinstance(self.model_profile, str):
            raise ConversationLiveInvariantError("live Run model profile is invalid")
        _non_negative_optional_int(self.input_token_count, name="input token count")
        _non_negative_optional_int(self.output_token_count, name="output token count")
        if not isinstance(self.started_at, str) or not self.started_at:
            raise ConversationLiveInvariantError("live Run started_at is invalid")
        if self.ended_at is not None and not isinstance(self.ended_at, str):
            raise ConversationLiveInvariantError("live Run ended_at is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "role": self.role,
            "model_profile": self.model_profile,
            "input_token_count": self.input_token_count,
            "output_token_count": self.output_token_count,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass(frozen=True)
class ConversationLiveTaskTelemetry:
    task_id: str
    task_status: str
    runs: tuple[ConversationLiveRunTelemetry, ...]
    total_run_count: int
    runs_truncated: bool
    reported_input_tokens: int
    reported_output_tokens: int
    fully_reported_runs: int
    missing_token_counters: int

    def __post_init__(self) -> None:
        if not validate_id(self.task_id, IdKind.TASK):
            raise ConversationLiveInvariantError("live Task id is invalid")
        if not isinstance(self.task_status, str) or not self.task_status:
            raise ConversationLiveInvariantError("live Task status is invalid")
        if type(self.total_run_count) is not int or self.total_run_count < len(self.runs):
            raise ConversationLiveInvariantError("live Task Run count is invalid")
        if self.runs_truncated != (self.total_run_count > len(self.runs)):
            raise ConversationLiveInvariantError("live Task Run truncation is invalid")
        for value in (
            self.reported_input_tokens,
            self.reported_output_tokens,
            self.fully_reported_runs,
            self.missing_token_counters,
        ):
            if type(value) is not int or value < 0:
                raise ConversationLiveInvariantError("live Task telemetry aggregate is invalid")

    @property
    def reported_tokens(self) -> int:
        return self.reported_input_tokens + self.reported_output_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_status": self.task_status,
            "runs": [run.to_dict() for run in self.runs],
            "visible_run_count": len(self.runs),
            "total_run_count": self.total_run_count,
            "runs_truncated": self.runs_truncated,
            "reported_input_tokens": self.reported_input_tokens,
            "reported_output_tokens": self.reported_output_tokens,
            "reported_tokens": self.reported_tokens,
            "fully_reported_runs": self.fully_reported_runs,
            "missing_token_counters": self.missing_token_counters,
        }


@dataclass(frozen=True)
class ConversationLiveState:
    session: ConversationSession
    turns: tuple[ConversationTurn, ...]
    submissions: tuple[ConversationLiveSubmission, ...]
    task_telemetry: tuple[ConversationLiveTaskTelemetry, ...]
    task_references_truncated: bool

    def __post_init__(self) -> None:
        for turn in self.turns:
            if turn.session_id != self.session.id:
                raise ConversationLiveInvariantError("live Turn belongs to another session")


def _read_submissions(
    runtime: OriginForgeRuntime,
    session_id: str,
    *,
    limit: int,
) -> tuple[ConversationLiveSubmission, ...]:
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT s.id, s.human_turn_id, s.status, s.response_turn_id,
                      s.failure_code, s.updated_at, ct.sequence AS human_turn_sequence
               FROM conversation_submissions AS s
               JOIN conversation_turns AS ct ON ct.id = s.human_turn_id
               JOIN conversation_sessions AS cs ON cs.id = s.session_id
               WHERE s.session_id = ? AND cs.project_id = ?
               ORDER BY ct.sequence DESC, s.id DESC
               LIMIT ?""",
            (session_id, project_id, limit),
        ).fetchall()
    items: list[ConversationLiveSubmission] = []
    for row in reversed(rows):
        try:
            items.append(
                ConversationLiveSubmission(
                    id=row["id"],
                    human_turn_id=row["human_turn_id"],
                    human_turn_sequence=int(row["human_turn_sequence"]),
                    status=ConversationSubmissionStatus(row["status"]),
                    response_turn_id=row["response_turn_id"],
                    failure_code=row["failure_code"],
                    updated_at=row["updated_at"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationLiveInvariantError(
                "stored conversation submission failed live validation"
            ) from exc
    return tuple(items)


def _referenced_task_ids(
    runtime: OriginForgeRuntime,
    session_id: str,
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    project_id = runtime.project_id()
    with runtime.store.session() as conn:
        total = int(
            conn.execute(
                """SELECT COUNT(DISTINCT ctr.reference_id)
                   FROM conversation_turn_references AS ctr
                   JOIN conversation_turns AS ct ON ct.id = ctr.turn_id
                   JOIN conversation_sessions AS cs ON cs.id = ct.session_id
                   WHERE ct.session_id = ? AND cs.project_id = ?
                     AND ctr.reference_type = 'TASK' AND ctr.relation = 'RESULT'""",
                (session_id, project_id),
            ).fetchone()[0]
        )
        rows = conn.execute(
            """SELECT ctr.reference_id, MAX(ct.sequence) AS last_sequence
               FROM conversation_turn_references AS ctr
               JOIN conversation_turns AS ct ON ct.id = ctr.turn_id
               JOIN conversation_sessions AS cs ON cs.id = ct.session_id
               WHERE ct.session_id = ? AND cs.project_id = ?
                 AND ctr.reference_type = 'TASK' AND ctr.relation = 'RESULT'
               GROUP BY ctr.reference_id
               ORDER BY last_sequence DESC, ctr.reference_id DESC
               LIMIT ?""",
            (session_id, project_id, limit),
        ).fetchall()
    task_ids = tuple(str(row["reference_id"]) for row in reversed(rows))
    for task_id in task_ids:
        if not validate_id(task_id, IdKind.TASK):
            raise ConversationLiveInvariantError("stored conversation Task reference is invalid")
    return task_ids, total > len(task_ids)


def _read_task_telemetry(
    runtime: OriginForgeRuntime,
    task_id: str,
    *,
    run_limit: int,
) -> ConversationLiveTaskTelemetry:
    task = runtime.get_task(task_id)
    task_status = task.get("status")
    if not isinstance(task_status, str) or not task_status:
        raise ConversationLiveInvariantError("referenced Task status is invalid")
    total_run_count = runtime.count_runs(task_id)
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT id, status, role, model_profile, input_token_count,
                      output_token_count, started_at, ended_at
               FROM runs
               WHERE task_id = ?
               ORDER BY started_at DESC, rowid DESC
               LIMIT ?""",
            (task_id, run_limit),
        ).fetchall()

    runs: list[ConversationLiveRunTelemetry] = []
    for row in reversed(rows):
        try:
            runs.append(
                ConversationLiveRunTelemetry(
                    id=row["id"],
                    status=row["status"],
                    role=row["role"],
                    model_profile=row["model_profile"],
                    input_token_count=_non_negative_optional_int(
                        row["input_token_count"], name="input token count"
                    ),
                    output_token_count=_non_negative_optional_int(
                        row["output_token_count"], name="output token count"
                    ),
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationLiveInvariantError(
                "stored Run failed conversation live validation"
            ) from exc

    input_total = sum(
        run.input_token_count for run in runs if run.input_token_count is not None
    )
    output_total = sum(
        run.output_token_count for run in runs if run.output_token_count is not None
    )
    fully_reported = sum(
        1
        for run in runs
        if run.input_token_count is not None and run.output_token_count is not None
    )
    missing_counters = sum(
        int(run.input_token_count is None) + int(run.output_token_count is None)
        for run in runs
    )
    return ConversationLiveTaskTelemetry(
        task_id=task_id,
        task_status=task_status,
        runs=tuple(runs),
        total_run_count=total_run_count,
        runs_truncated=total_run_count > len(runs),
        reported_input_tokens=input_total,
        reported_output_tokens=output_total,
        fully_reported_runs=fully_reported,
        missing_token_counters=missing_counters,
    )


def read_conversation_live_state(
    runtime: OriginForgeRuntime,
    session_id: str,
    *,
    turn_limit: int = MAX_LIVE_TURNS,
    submission_limit: int = MAX_LIVE_SUBMISSIONS,
    task_limit: int = MAX_LIVE_TASKS,
    run_limit: int = MAX_LIVE_RUNS_PER_TASK,
) -> ConversationLiveState:
    """Rebuild bounded live conversation state exclusively from durable project records."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(session_id, str) or not validate_id(
        session_id, IdKind.CONVERSATION_SESSION
    ):
        raise ValueError("session_id must be a CONV ID")
    turn_limit = _bounded_limit(turn_limit, maximum=MAX_LIVE_TURNS, name="turn_limit")
    submission_limit = _bounded_limit(
        submission_limit, maximum=MAX_LIVE_SUBMISSIONS, name="submission_limit"
    )
    task_limit = _bounded_limit(task_limit, maximum=MAX_LIVE_TASKS, name="task_limit")
    run_limit = _bounded_limit(
        run_limit, maximum=MAX_LIVE_RUNS_PER_TASK, name="run_limit"
    )

    session = read_conversation_session(runtime, session_id)
    after_sequence = max(0, session.revision - turn_limit)
    turns = list_conversation_turns(
        runtime,
        session_id,
        after_sequence=after_sequence,
        limit=turn_limit,
    )
    submissions = _read_submissions(runtime, session_id, limit=submission_limit)
    task_ids, task_references_truncated = _referenced_task_ids(
        runtime, session_id, limit=task_limit
    )
    telemetry = tuple(
        _read_task_telemetry(runtime, task_id, run_limit=run_limit)
        for task_id in task_ids
    )
    return ConversationLiveState(
        session=session,
        turns=turns,
        submissions=submissions,
        task_telemetry=telemetry,
        task_references_truncated=task_references_truncated,
    )
