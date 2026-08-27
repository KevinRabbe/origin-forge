from __future__ import annotations

from .migrations import Migration


PIXELORAMA_SOURCE_PRODUCTION_ADOPTION_MIGRATION = Migration(
    31,
    r"""
CREATE TABLE pixelorama_source_production_adoptions (
    execution_id TEXT NOT NULL,
    output_index INTEGER NOT NULL CHECK (output_index >= 0 AND output_index < 64),
    output_artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE RESTRICT,
    destination_path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('PREPARED', 'PUBLISHED')),
    adopted_artifact_id TEXT UNIQUE REFERENCES artifacts(id) ON DELETE RESTRICT,
    verification_id TEXT UNIQUE REFERENCES verifications(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    published_at TEXT,
    PRIMARY KEY (execution_id, output_index),
    CHECK (
        (status = 'PREPARED' AND adopted_artifact_id IS NULL AND verification_id IS NULL AND published_at IS NULL)
        OR
        (status = 'PUBLISHED' AND adopted_artifact_id IS NOT NULL AND verification_id IS NOT NULL AND published_at IS NOT NULL)
    )
);

CREATE INDEX idx_pixelorama_source_adoptions_status
ON pixelorama_source_production_adoptions(status, created_at, execution_id);
""",
)
