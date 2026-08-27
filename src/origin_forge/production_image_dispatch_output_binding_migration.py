from __future__ import annotations

from .migrations import Migration


IMAGE_DISPATCH_OUTPUT_BINDING_MIGRATION = Migration(
    24,
    r"""
CREATE TABLE image_dispatch_output_bindings (
    execution_id TEXT NOT NULL REFERENCES dispatch_executions(execution_id) ON DELETE CASCADE,
    output_index INTEGER NOT NULL CHECK (output_index >= 0 AND output_index < 4),
    claim_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL CHECK (length(task_content_hash) = 64),
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL CHECK (length(work_order_hash) = 64),
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL CHECK (length(dispatch_binding_hash) = 64),
    execution_owner_id TEXT NOT NULL CHECK (
        execution_owner_id = 'originforge.execution.image.generate@1'
    ),
    run_id TEXT NOT NULL,
    request_artifact_id TEXT NOT NULL,
    result_artifact_id TEXT NOT NULL,
    output_artifact_id TEXT NOT NULL,
    output_verification_id TEXT NOT NULL,
    output_relative_path TEXT NOT NULL,
    output_content_hash TEXT NOT NULL CHECK (length(output_content_hash) = 64),
    output_pixel_hash TEXT NOT NULL CHECK (length(output_pixel_hash) = 64),
    output_width INTEGER NOT NULL CHECK (output_width > 0),
    output_height INTEGER NOT NULL CHECK (output_height > 0),
    output_byte_count INTEGER NOT NULL CHECK (output_byte_count > 0),
    backend_result_hash TEXT NOT NULL CHECK (length(backend_result_hash) = 64),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    PRIMARY KEY (execution_id, output_index),
    UNIQUE (execution_id, output_artifact_id),
    UNIQUE (execution_id, output_verification_id)
);

CREATE UNIQUE INDEX idx_image_dispatch_output_bindings_claim
ON image_dispatch_output_bindings(claim_id, output_index);

CREATE INDEX idx_image_dispatch_output_bindings_task
ON image_dispatch_output_bindings(task_id, created_at, execution_id);
""",
)
