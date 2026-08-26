from __future__ import annotations

from .migrations import Migration

PLAYTEST_DISPATCH_OUTPUT_BINDING_MIGRATION = Migration(
    27,
    r"""
CREATE TABLE playtest_dispatch_output_bindings (
    execution_id TEXT PRIMARY KEY REFERENCES dispatch_executions(execution_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL CHECK (length(task_content_hash) = 64),
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL CHECK (length(work_order_hash) = 64),
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL CHECK (length(dispatch_binding_hash) = 64),
    execution_owner_id TEXT NOT NULL CHECK (execution_owner_id = 'originforge.execution.playtest.cooperative@1'),
    run_id TEXT NOT NULL UNIQUE,
    scenario_artifact_id TEXT NOT NULL UNIQUE,
    telemetry_artifact_id TEXT NOT NULL UNIQUE,
    summary_artifact_id TEXT NOT NULL UNIQUE,
    stdout_artifact_id TEXT NOT NULL UNIQUE,
    stderr_artifact_id TEXT NOT NULL UNIQUE,
    telemetry_hash TEXT NOT NULL CHECK (length(telemetry_hash) = 64),
    summary_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    timed_out INTEGER NOT NULL CHECK (timed_out IN (0, 1)),
    exit_code INTEGER,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);
CREATE INDEX idx_playtest_dispatch_output_bindings_task
ON playtest_dispatch_output_bindings(task_id, created_at, execution_id);
""",
)
