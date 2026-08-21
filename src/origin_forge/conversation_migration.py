from __future__ import annotations

from .migrations import Migration


CONVERSATION_GATE_A_MIGRATION = Migration(
    18,
    r"""
CREATE TABLE conversation_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'ARCHIVED')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    updated_at TEXT NOT NULL CHECK (length(updated_at) > 0)
);

CREATE INDEX idx_conversation_sessions_project_history
ON conversation_sessions(project_id, updated_at, id);

CREATE INDEX idx_conversation_sessions_project_status
ON conversation_sessions(project_id, status, updated_at, id);

CREATE TABLE conversation_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('HUMAN', 'FORGE', 'SYSTEM')),
    content TEXT NOT NULL CHECK (length(content) > 0),
    content_hash TEXT NOT NULL CHECK (
        length(content_hash) = 71 AND substr(content_hash, 1, 7) = 'sha256:'
    ),
    client_submission_id TEXT,
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(session_id, sequence),
    CHECK (
        (actor_type = 'HUMAN' AND client_submission_id IS NOT NULL AND length(client_submission_id) > 0)
        OR
        (actor_type != 'HUMAN' AND client_submission_id IS NULL)
    )
);

CREATE UNIQUE INDEX idx_conversation_turns_client_submission
ON conversation_turns(session_id, client_submission_id)
WHERE client_submission_id IS NOT NULL;

CREATE INDEX idx_conversation_turns_session_history
ON conversation_turns(session_id, sequence, id);

CREATE TRIGGER conversation_turns_immutable_update
BEFORE UPDATE ON conversation_turns
BEGIN
    SELECT RAISE(ABORT, 'conversation turns are immutable');
END;

CREATE TRIGGER conversation_turns_immutable_delete
BEFORE DELETE ON conversation_turns
BEGIN
    SELECT RAISE(ABORT, 'conversation turns are immutable');
END;

CREATE TABLE conversation_submissions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE RESTRICT,
    human_turn_id TEXT NOT NULL UNIQUE REFERENCES conversation_turns(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'PROCESSING', 'RESPONDED', 'FAILED')),
    expected_session_revision INTEGER NOT NULL CHECK (expected_session_revision >= 0),
    response_turn_id TEXT UNIQUE REFERENCES conversation_turns(id) ON DELETE RESTRICT,
    failure_code TEXT,
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    updated_at TEXT NOT NULL CHECK (length(updated_at) > 0),
    CHECK (
        (status IN ('ACCEPTED', 'PROCESSING') AND response_turn_id IS NULL AND failure_code IS NULL)
        OR
        (status = 'RESPONDED' AND response_turn_id IS NOT NULL AND failure_code IS NULL)
        OR
        (status = 'FAILED' AND response_turn_id IS NULL AND failure_code IS NOT NULL AND length(failure_code) > 0)
    )
);

CREATE INDEX idx_conversation_submissions_session_history
ON conversation_submissions(session_id, created_at, id);

CREATE INDEX idx_conversation_submissions_status
ON conversation_submissions(status, updated_at, id);
""",
)
