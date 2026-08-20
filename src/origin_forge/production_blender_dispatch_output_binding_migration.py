from __future__ import annotations

from .migrations import Migration


BLENDER_DISPATCH_OUTPUT_BINDING_MIGRATION = Migration(
    16,
    r"""
CREATE TABLE blender_dispatch_output_bindings (
    execution_id TEXT PRIMARY KEY REFERENCES dispatch_executions(execution_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL CHECK (length(task_content_hash) = 64),
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL CHECK (length(work_order_hash) = 64),
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL CHECK (length(dispatch_binding_hash) = 64),
    execution_owner_id TEXT NOT NULL CHECK (
        execution_owner_id = 'originforge.execution.blender.export-glb@1'
    ),
    run_id TEXT NOT NULL UNIQUE,
    request_artifact_id TEXT NOT NULL UNIQUE,
    result_artifact_id TEXT NOT NULL UNIQUE,
    output_artifact_id TEXT NOT NULL UNIQUE,
    output_verification_id TEXT NOT NULL UNIQUE,
    run_verification_id TEXT NOT NULL UNIQUE,
    output_content_hash TEXT NOT NULL CHECK (length(output_content_hash) = 64),
    output_byte_count INTEGER NOT NULL CHECK (output_byte_count >= 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);

CREATE INDEX idx_blender_dispatch_output_bindings_task
ON blender_dispatch_output_bindings(task_id, created_at, execution_id);
""",
)
