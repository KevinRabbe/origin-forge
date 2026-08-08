from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    sql: str


MIGRATION_001 = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    objective TEXT NOT NULL,
    success_criteria_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '[]',
    budgets_json TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    controller TEXT,
    state_json TEXT NOT NULL DEFAULT '{}',
    blocked_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
    parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    objective TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '[]',
    required_capabilities_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    assigned_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    context TEXT,
    decision TEXT NOT NULL,
    rationale TEXT,
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    supersedes_decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    run_id TEXT,
    summary TEXT NOT NULL,
    change_type TEXT NOT NULL,
    before_ref TEXT,
    after_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    change_id TEXT REFERENCES changes(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    path_or_uri TEXT NOT NULL,
    content_hash TEXT,
    parent_artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_by_run_id TEXT,
    model_id TEXT,
    skill_versions_json TEXT NOT NULL DEFAULT '[]',
    tool_versions_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verifications (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    verification_type TEXT NOT NULL,
    verifier TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    run_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    role TEXT NOT NULL,
    model_profile TEXT,
    model_hash TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    input_token_count INTEGER,
    output_token_count INTEGER,
    resource_metrics_json TEXT NOT NULL DEFAULT '{}',
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS state_events (
    id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    revision INTEGER,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goals_project ON goals(project_id);
CREATE INDEX IF NOT EXISTS idx_flows_goal ON flows(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_flow ON tasks(flow_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_events_aggregate ON state_events(aggregate_type, aggregate_id, created_at);
"""

MIGRATION_002 = r"""
ALTER TABLE goals ADD COLUMN revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0);
"""

MIGRATION_003 = r"""
CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    branch_name TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    base_commit TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_workspaces_task ON workspaces(task_id);
CREATE INDEX idx_workspaces_status ON workspaces(status);
"""

MIGRATION_004 = r"""
CREATE UNIQUE INDEX idx_workspaces_one_active_per_task
ON workspaces(task_id)
WHERE status != 'ABANDONED';
"""

MIGRATION_005 = r"""
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, project_id)
);

CREATE TABLE entity_relations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    rationale TEXT NOT NULL DEFAULT '',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, project_id),
    FOREIGN KEY(source_entity_id, project_id)
        REFERENCES entities(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id, project_id)
        REFERENCES entities(id, project_id) ON DELETE CASCADE,
    CHECK(source_entity_id != target_entity_id)
);

CREATE TABLE entity_bindings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    binding_type TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    target_hash TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, project_id),
    FOREIGN KEY(entity_id, project_id)
        REFERENCES entities(id, project_id) ON DELETE CASCADE
);

CREATE TABLE design_rules (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL,
    scope_entity_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    supersedes_rule_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, project_id),
    FOREIGN KEY(supersedes_rule_id, project_id)
        REFERENCES design_rules(id, project_id) ON DELETE RESTRICT,
    CHECK(supersedes_rule_id IS NULL OR supersedes_rule_id != id)
);

CREATE INDEX idx_entities_project_kind_status
ON entities(project_id, kind, status, name, id);

CREATE INDEX idx_entity_relations_outbound
ON entity_relations(project_id, source_entity_id, status, relation_type, target_entity_id);

CREATE INDEX idx_entity_relations_inbound
ON entity_relations(project_id, target_entity_id, status, relation_type, source_entity_id);

CREATE UNIQUE INDEX idx_entity_relations_active_unique
ON entity_relations(project_id, source_entity_id, relation_type, target_entity_id)
WHERE status = 'ACTIVE';

CREATE INDEX idx_entity_bindings_entity
ON entity_bindings(project_id, entity_id, status, binding_type, target_ref);

CREATE UNIQUE INDEX idx_entity_bindings_active_unique
ON entity_bindings(project_id, entity_id, binding_type, target_ref)
WHERE status = 'ACTIVE';

CREATE INDEX idx_design_rules_project_status_category
ON design_rules(project_id, status, category, title, id);
"""

MIGRATIONS = (
    Migration(1, MIGRATION_001),
    Migration(2, MIGRATION_002),
    Migration(3, MIGRATION_003),
    Migration(4, MIGRATION_004),
    Migration(5, MIGRATION_005),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
