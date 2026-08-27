from __future__ import annotations

from .migrations import Migration

AUDIO_DISPATCH_OUTPUT_BINDING_MIGRATION = Migration(
    25,
    r"""
CREATE TABLE audio_dispatch_output_bindings (
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
        execution_owner_id = 'originforge.execution.audio.piper-tts@1'
    ),
    run_id TEXT NOT NULL UNIQUE,
    request_artifact_id TEXT NOT NULL UNIQUE,
    result_artifact_id TEXT NOT NULL UNIQUE,
    output_artifact_id TEXT NOT NULL UNIQUE,
    output_verification_id TEXT NOT NULL UNIQUE,
    output_relative_path TEXT NOT NULL,
    output_content_hash TEXT NOT NULL CHECK (length(output_content_hash) = 64),
    output_pcm_hash TEXT NOT NULL CHECK (length(output_pcm_hash) = 64),
    output_byte_count INTEGER NOT NULL CHECK (output_byte_count > 0),
    output_frame_count INTEGER NOT NULL CHECK (output_frame_count > 0),
    output_sample_rate INTEGER NOT NULL CHECK (output_sample_rate > 0),
    output_channels INTEGER NOT NULL CHECK (output_channels IN (1, 2)),
    output_peak_abs_sample INTEGER NOT NULL CHECK (output_peak_abs_sample BETWEEN 0 AND 32768),
    output_clipped_sample_count INTEGER NOT NULL CHECK (output_clipped_sample_count >= 0),
    output_nonzero_sample_count INTEGER NOT NULL CHECK (output_nonzero_sample_count >= 0),
    backend_result_hash TEXT NOT NULL CHECK (length(backend_result_hash) = 64),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);

CREATE INDEX idx_audio_dispatch_output_bindings_task
ON audio_dispatch_output_bindings(task_id, created_at, execution_id);
""",
)
