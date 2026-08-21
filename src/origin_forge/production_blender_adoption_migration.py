from __future__ import annotations

from .migrations import Migration


BLENDER_PRODUCTION_ADOPTION_MIGRATION = Migration(
    17,
    r"""
CREATE TABLE blender_production_adoptions (
    execution_id TEXT PRIMARY KEY REFERENCES blender_dispatch_output_bindings(execution_id) ON DELETE RESTRICT,
    output_artifact_id TEXT NOT NULL UNIQUE,
    destination_path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('PREPARED', 'PUBLISHED')),
    adopted_artifact_id TEXT UNIQUE REFERENCES artifacts(id) ON DELETE RESTRICT,
    verification_id TEXT UNIQUE REFERENCES verifications(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    published_at TEXT,
    CHECK (
        (status = 'PREPARED' AND adopted_artifact_id IS NULL AND verification_id IS NULL AND published_at IS NULL)
        OR
        (status = 'PUBLISHED' AND adopted_artifact_id IS NOT NULL AND verification_id IS NOT NULL AND published_at IS NOT NULL)
    )
);

CREATE INDEX idx_blender_production_adoptions_status
ON blender_production_adoptions(status, created_at, execution_id);
""",
)
