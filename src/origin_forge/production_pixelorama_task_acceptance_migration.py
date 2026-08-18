from __future__ import annotations

from .migrations import Migration


PIXELORAMA_PRODUCTION_TASK_ACCEPTANCE_MIGRATION = Migration(
    15,
    r"""
CREATE TABLE pixelorama_production_task_acceptances (
    execution_id TEXT PRIMARY KEY REFERENCES pixelorama_production_adoptions(execution_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE RESTRICT,
    adopted_artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE RESTRICT,
    adoption_verification_id TEXT NOT NULL UNIQUE REFERENCES verifications(id) ON DELETE RESTRICT,
    task_verification_id TEXT NOT NULL UNIQUE REFERENCES verifications(id) ON DELETE RESTRICT,
    task_revision_at_acceptance INTEGER NOT NULL CHECK (task_revision_at_acceptance >= 0),
    accepted_content_hash TEXT NOT NULL CHECK (
        length(accepted_content_hash) = 71
        AND substr(accepted_content_hash, 1, 7) = 'sha256:'
    ),
    accepted_byte_count INTEGER NOT NULL CHECK (accepted_byte_count > 0),
    accepted_destination_path TEXT NOT NULL CHECK (length(accepted_destination_path) > 0),
    acceptance_authority TEXT NOT NULL CHECK (acceptance_authority = 'HUMAN_OPERATOR'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    accepted_at TEXT NOT NULL CHECK (length(accepted_at) > 0),
    CHECK (adoption_verification_id != task_verification_id)
);

CREATE INDEX idx_pixelorama_production_task_acceptances_task
ON pixelorama_production_task_acceptances(task_id, accepted_at, execution_id);

CREATE TRIGGER pixelorama_production_task_acceptances_immutable_update
BEFORE UPDATE ON pixelorama_production_task_acceptances
BEGIN
    SELECT RAISE(ABORT, 'pixelorama production task acceptances are immutable');
END;

CREATE TRIGGER pixelorama_production_task_acceptances_immutable_delete
BEFORE DELETE ON pixelorama_production_task_acceptances
BEGIN
    SELECT RAISE(ABORT, 'pixelorama production task acceptances are immutable');
END;
""",
)
