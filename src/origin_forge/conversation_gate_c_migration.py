from __future__ import annotations

from .migrations import Migration


CONVERSATION_GATE_C_MIGRATION = Migration(
    19,
    r"""
CREATE TABLE conversation_submission_operations (
    submission_id TEXT PRIMARY KEY
        REFERENCES conversation_submissions(id) ON DELETE RESTRICT,
    operation_kind TEXT NOT NULL CHECK (
        operation_kind IN (
            'READ_ONLY_PROJECT_COUNTS',
            'PRODUCTION_CREATE_GOAL'
        )
    ),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);

CREATE INDEX idx_conversation_submission_operations_kind
ON conversation_submission_operations(operation_kind, created_at, submission_id);

CREATE TABLE conversation_turn_references (
    turn_id TEXT NOT NULL
        REFERENCES conversation_turns(id) ON DELETE RESTRICT,
    reference_type TEXT NOT NULL CHECK (
        reference_type IN ('GOAL', 'FLOW', 'TASK', 'RUN', 'ARTIFACT', 'VERIFICATION')
    ),
    reference_id TEXT NOT NULL CHECK (length(reference_id) > 0),
    relation TEXT NOT NULL CHECK (
        relation IN ('FOCUS', 'ATTACHMENT', 'RESULT', 'EVIDENCE')
    ),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    PRIMARY KEY(turn_id, reference_type, reference_id, relation)
);

CREATE INDEX idx_conversation_turn_references_target
ON conversation_turn_references(reference_type, reference_id, relation, turn_id);

CREATE UNIQUE INDEX idx_conversation_goal_created_once_per_submission
ON state_events(actor_id)
WHERE event_type = 'GOAL_CREATED'
  AND actor_type = 'CONVERSATION'
  AND actor_id IS NOT NULL;
""",
)
