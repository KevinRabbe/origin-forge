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

MIGRATION_006 = r"""
CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    required_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL DEFAULT 'REQUIRES_SUCCESS'
        CHECK (dependency_type = 'REQUIRES_SUCCESS'),
    created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, required_task_id),
    CHECK(task_id != required_task_id)
);

CREATE INDEX idx_task_dependencies_required
ON task_dependencies(required_task_id, task_id);

CREATE TRIGGER task_dependencies_same_flow_insert
BEFORE INSERT ON task_dependencies
BEGIN
    SELECT CASE
        WHEN (SELECT flow_id FROM tasks WHERE id = NEW.task_id)
             != (SELECT flow_id FROM tasks WHERE id = NEW.required_task_id)
        THEN RAISE(ABORT, 'task dependencies must belong to the same flow')
    END;
END;

CREATE TRIGGER task_dependencies_no_cycle_insert
BEFORE INSERT ON task_dependencies
BEGIN
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE requirements(task_id) AS (
            SELECT required_task_id
            FROM task_dependencies
            WHERE task_id = NEW.required_task_id
            UNION
            SELECT td.required_task_id
            FROM task_dependencies td
            JOIN requirements r ON td.task_id = r.task_id
        )
        SELECT 1 FROM requirements WHERE task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'task dependency would create a cycle') END;
END;
"""

MIGRATION_007 = r"""
CREATE TABLE planning_inputs (
    planning_input_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
    goal_revision INTEGER NOT NULL CHECK (goal_revision >= 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_planning_inputs_goal
ON planning_inputs(project_id, goal_id, created_at, planning_input_id);

CREATE TABLE plan_proposals (
    proposal_id TEXT PRIMARY KEY,
    planning_input_id TEXT NOT NULL REFERENCES planning_inputs(planning_input_id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_plan_proposals_input
ON plan_proposals(planning_input_id, created_at, proposal_id);

CREATE TABLE plan_audits (
    audit_id TEXT PRIMARY KEY,
    planning_input_id TEXT NOT NULL REFERENCES planning_inputs(planning_input_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL REFERENCES plan_proposals(proposal_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_plan_audits_proposal
ON plan_audits(proposal_id, created_at, audit_id);

CREATE TABLE plan_materializations (
    materialization_id TEXT PRIMARY KEY,
    planning_input_id TEXT NOT NULL REFERENCES planning_inputs(planning_input_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES plan_proposals(proposal_id) ON DELETE RESTRICT,
    audit_id TEXT NOT NULL UNIQUE REFERENCES plan_audits(audit_id) ON DELETE RESTRICT,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
    flow_id TEXT NOT NULL UNIQUE REFERENCES flows(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_plan_materializations_goal
ON plan_materializations(goal_id, created_at, materialization_id);
"""

MIGRATION_008 = r"""
CREATE TABLE dispatch_claims (
    claim_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL,
    work_order_audit_id TEXT NOT NULL,
    work_order_audit_hash TEXT NOT NULL,
    input_resolution_id TEXT NOT NULL,
    input_resolution_hash TEXT NOT NULL,
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL,
    binding_audit_id TEXT NOT NULL,
    binding_audit_hash TEXT NOT NULL,
    selected_adapter_id TEXT NOT NULL,
    selected_adapter_fingerprint TEXT NOT NULL,
    dispatch_contract_id TEXT NOT NULL,
    dispatch_contract_hash TEXT NOT NULL,
    binder_id TEXT NOT NULL,
    binder_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'INTERRUPTED')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_reason TEXT,
    CHECK (
        (status = 'ACTIVE' AND terminal_reason IS NULL)
        OR
        (status IN ('RELEASED', 'INTERRUPTED') AND terminal_reason IS NOT NULL AND length(terminal_reason) > 0)
    )
);

CREATE INDEX idx_dispatch_claims_task_history
ON dispatch_claims(project_id, task_id, created_at, claim_id);

CREATE INDEX idx_dispatch_claims_binding
ON dispatch_claims(dispatch_binding_id, created_at, claim_id);

CREATE UNIQUE INDEX idx_dispatch_claims_one_active_per_task
ON dispatch_claims(task_id)
WHERE status = 'ACTIVE';
"""

MIGRATION_009 = r"""
ALTER TABLE dispatch_claims RENAME TO dispatch_claims_v8;

CREATE TABLE dispatch_claims (
    claim_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL,
    work_order_audit_id TEXT NOT NULL,
    work_order_audit_hash TEXT NOT NULL,
    input_resolution_id TEXT NOT NULL,
    input_resolution_hash TEXT NOT NULL,
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL,
    binding_audit_id TEXT NOT NULL,
    binding_audit_hash TEXT NOT NULL,
    selected_adapter_id TEXT NOT NULL,
    selected_adapter_fingerprint TEXT NOT NULL,
    dispatch_contract_id TEXT NOT NULL,
    dispatch_contract_hash TEXT NOT NULL,
    binder_id TEXT NOT NULL,
    binder_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'INTERRUPTED', 'CONSUMED')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_reason TEXT,
    CHECK (
        (status = 'ACTIVE' AND terminal_reason IS NULL)
        OR
        (status IN ('RELEASED', 'INTERRUPTED', 'CONSUMED') AND terminal_reason IS NOT NULL AND length(terminal_reason) > 0)
    )
);

INSERT INTO dispatch_claims(
    claim_id, project_id, task_id, task_revision, task_content_hash,
    work_order_id, work_order_hash, work_order_audit_id, work_order_audit_hash,
    input_resolution_id, input_resolution_hash,
    dispatch_binding_id, dispatch_binding_hash,
    binding_audit_id, binding_audit_hash,
    selected_adapter_id, selected_adapter_fingerprint,
    dispatch_contract_id, dispatch_contract_hash,
    binder_id, binder_fingerprint,
    status, revision, created_at, updated_at, terminal_reason
)
SELECT
    claim_id, project_id, task_id, task_revision, task_content_hash,
    work_order_id, work_order_hash, work_order_audit_id, work_order_audit_hash,
    input_resolution_id, input_resolution_hash,
    dispatch_binding_id, dispatch_binding_hash,
    binding_audit_id, binding_audit_hash,
    selected_adapter_id, selected_adapter_fingerprint,
    dispatch_contract_id, dispatch_contract_hash,
    binder_id, binder_fingerprint,
    status, revision, created_at, updated_at, terminal_reason
FROM dispatch_claims_v8;

DROP TABLE dispatch_claims_v8;

CREATE INDEX idx_dispatch_claims_task_history
ON dispatch_claims(project_id, task_id, created_at, claim_id);

CREATE INDEX idx_dispatch_claims_binding
ON dispatch_claims(dispatch_binding_id, created_at, claim_id);

CREATE UNIQUE INDEX idx_dispatch_claims_one_active_per_task
ON dispatch_claims(task_id)
WHERE status = 'ACTIVE';

CREATE TABLE dispatch_executions (
    execution_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL UNIQUE REFERENCES dispatch_claims(claim_id) ON DELETE CASCADE,
    claim_revision_at_start INTEGER NOT NULL CHECK (claim_revision_at_start >= 0),
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    work_order_hash TEXT NOT NULL,
    input_resolution_id TEXT NOT NULL,
    input_resolution_hash TEXT NOT NULL,
    dispatch_binding_id TEXT NOT NULL,
    dispatch_binding_hash TEXT NOT NULL,
    binding_audit_id TEXT NOT NULL,
    binding_audit_hash TEXT NOT NULL,
    selected_adapter_id TEXT NOT NULL,
    selected_adapter_fingerprint TEXT NOT NULL,
    dispatch_contract_id TEXT NOT NULL,
    dispatch_contract_hash TEXT NOT NULL,
    binder_id TEXT NOT NULL,
    binder_fingerprint TEXT NOT NULL,
    execution_owner_id TEXT NOT NULL,
    execution_owner_fingerprint TEXT NOT NULL,
    runtime_dependency_plan_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STARTED', 'RETURNED', 'RAISED', 'INTERRUPTED')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_detail_hash TEXT,
    CHECK (
        (status = 'STARTED' AND terminal_detail_hash IS NULL)
        OR
        (status IN ('RETURNED', 'RAISED', 'INTERRUPTED') AND terminal_detail_hash IS NOT NULL AND length(terminal_detail_hash) = 64)
    )
);

CREATE INDEX idx_dispatch_executions_task_history
ON dispatch_executions(project_id, task_id, created_at, execution_id);

CREATE INDEX idx_dispatch_executions_status
ON dispatch_executions(project_id, status, created_at, execution_id);

CREATE UNIQUE INDEX idx_dispatch_executions_one_started_per_task
ON dispatch_executions(task_id)
WHERE status = 'STARTED';
"""

MIGRATION_010 = r"""
CREATE TRIGGER dispatch_claims_started_execution_seals_legacy_terminalization
BEFORE UPDATE OF status ON dispatch_claims
WHEN OLD.status = 'ACTIVE'
 AND NEW.status IN ('RELEASED', 'INTERRUPTED')
 AND EXISTS (
     SELECT 1
     FROM dispatch_executions
     WHERE claim_id = OLD.claim_id
       AND status = 'STARTED'
 )
BEGIN
    SELECT RAISE(
        ABORT,
        'dispatch claim with STARTED execution must use execution lifecycle terminalization'
    );
END;
"""

MIGRATION_011 = r"""
CREATE TABLE task_preparations (
    preparation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    preparation_policy_id TEXT NOT NULL,
    preparation_policy_hash TEXT NOT NULL,
    materialization_id TEXT NOT NULL REFERENCES plan_materializations(materialization_id) ON DELETE RESTRICT,
    materialization_hash TEXT NOT NULL,
    planning_input_id TEXT NOT NULL REFERENCES planning_inputs(planning_input_id) ON DELETE RESTRICT,
    planning_input_hash TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    queued_task_revision INTEGER NOT NULL CHECK (queued_task_revision >= 0),
    queued_task_hash TEXT NOT NULL,
    ready_task_revision INTEGER CHECK (ready_task_revision >= 0),
    ready_task_hash TEXT,
    route_decision_id TEXT,
    route_decision_hash TEXT,
    planner_dependency_plan_hash TEXT,
    planner_run_id TEXT REFERENCES runs(id) ON DELETE RESTRICT,
    work_order_id TEXT,
    work_order_hash TEXT,
    work_order_audit_id TEXT,
    work_order_audit_hash TEXT,
    input_resolution_id TEXT,
    input_resolution_hash TEXT,
    dispatch_binding_id TEXT,
    dispatch_binding_hash TEXT,
    binding_audit_id TEXT,
    binding_audit_hash TEXT,
    stage TEXT NOT NULL CHECK (
        stage IN (
            'CLAIMED', 'ACTIVATED', 'ROUTED', 'PLANNER_STARTED',
            'PLANNER_RETURNED', 'WORK_ORDER_AUDITED', 'BOUND'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'READY', 'INTERRUPTED', 'FAILED_PRE_PLANNER')
    ),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_reason TEXT,
    CHECK ((ready_task_revision IS NULL) = (ready_task_hash IS NULL)),
    CHECK ((route_decision_id IS NULL) = (route_decision_hash IS NULL)),
    CHECK ((work_order_id IS NULL) = (work_order_hash IS NULL)),
    CHECK ((work_order_audit_id IS NULL) = (work_order_audit_hash IS NULL)),
    CHECK ((input_resolution_id IS NULL) = (input_resolution_hash IS NULL)),
    CHECK ((dispatch_binding_id IS NULL) = (dispatch_binding_hash IS NULL)),
    CHECK ((binding_audit_id IS NULL) = (binding_audit_hash IS NULL)),
    CHECK (
        (status IN ('ACTIVE', 'READY') AND terminal_reason IS NULL)
        OR
        (status IN ('INTERRUPTED', 'FAILED_PRE_PLANNER')
         AND terminal_reason IS NOT NULL AND length(terminal_reason) > 0)
    ),
    CHECK (status != 'READY' OR stage = 'BOUND'),
    CHECK (
        status != 'FAILED_PRE_PLANNER'
        OR stage IN ('CLAIMED', 'ACTIVATED', 'ROUTED')
    ),
    CHECK (
        (stage = 'CLAIMED'
         AND ready_task_revision IS NULL
         AND route_decision_id IS NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND work_order_id IS NULL
         AND work_order_audit_id IS NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'ACTIVATED'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND work_order_id IS NULL
         AND work_order_audit_id IS NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'ROUTED'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NOT NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND work_order_id IS NULL
         AND work_order_audit_id IS NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'PLANNER_STARTED'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NULL
         AND work_order_id IS NULL
         AND work_order_audit_id IS NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'PLANNER_RETURNED'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND work_order_id IS NOT NULL
         AND work_order_audit_id IS NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'WORK_ORDER_AUDITED'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND work_order_id IS NOT NULL
         AND work_order_audit_id IS NOT NULL
         AND input_resolution_id IS NULL
         AND dispatch_binding_id IS NULL
         AND binding_audit_id IS NULL)
        OR
        (stage = 'BOUND'
         AND ready_task_revision IS NOT NULL
         AND route_decision_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND work_order_id IS NOT NULL
         AND work_order_audit_id IS NOT NULL
         AND input_resolution_id IS NOT NULL
         AND dispatch_binding_id IS NOT NULL
         AND binding_audit_id IS NOT NULL)
    )
);

CREATE INDEX idx_task_preparations_task_history
ON task_preparations(project_id, task_id, created_at, preparation_id);

CREATE INDEX idx_task_preparations_policy_status
ON task_preparations(project_id, preparation_policy_id, status, created_at, preparation_id);

CREATE INDEX idx_task_preparations_status
ON task_preparations(project_id, status, stage, created_at, preparation_id);

CREATE UNIQUE INDEX idx_task_preparations_one_active_per_task
ON task_preparations(task_id)
WHERE status = 'ACTIVE';
"""

MIGRATION_012 = r"""
CREATE TABLE goal_bootstraps (
    bootstrap_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
    goal_revision INTEGER NOT NULL CHECK (goal_revision >= 0),
    goal_content_hash TEXT NOT NULL CHECK (length(goal_content_hash) = 64),
    bootstrap_owner_id TEXT NOT NULL,
    bootstrap_owner_fingerprint TEXT NOT NULL CHECK (length(bootstrap_owner_fingerprint) = 64),
    bootstrap_contract_version TEXT NOT NULL,
    capability_catalog_id TEXT,
    capability_catalog_hash TEXT,
    capability_routing_policy_id TEXT,
    capability_routing_policy_hash TEXT,
    dispatch_contract_catalog_id TEXT,
    dispatch_contract_catalog_hash TEXT,
    planning_input_id TEXT,
    planning_input_hash TEXT,
    planner_dependency_plan_hash TEXT,
    planner_run_id TEXT,
    plan_proposal_id TEXT,
    plan_proposal_hash TEXT,
    plan_audit_id TEXT,
    plan_audit_hash TEXT,
    materialization_id TEXT,
    materialization_hash TEXT,
    preparation_policy_id TEXT,
    preparation_policy_hash TEXT,
    stage TEXT NOT NULL CHECK (
        stage IN (
            'CLAIMED', 'AUTHORITY_PUBLISHED', 'PLANNING_INPUT_PUBLISHED',
            'PLANNER_STARTED', 'PLANNER_RETURNED', 'PLAN_AUDITED',
            'MATERIALIZED', 'PREPPOL_PUBLISHED'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'READY', 'FAILED_PRE_PLANNER', 'INTERRUPTED')
    ),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_reason TEXT,
    CHECK ((capability_catalog_id IS NULL) = (capability_catalog_hash IS NULL)),
    CHECK ((capability_routing_policy_id IS NULL) = (capability_routing_policy_hash IS NULL)),
    CHECK ((dispatch_contract_catalog_id IS NULL) = (dispatch_contract_catalog_hash IS NULL)),
    CHECK ((planning_input_id IS NULL) = (planning_input_hash IS NULL)),
    CHECK ((plan_proposal_id IS NULL) = (plan_proposal_hash IS NULL)),
    CHECK ((plan_audit_id IS NULL) = (plan_audit_hash IS NULL)),
    CHECK ((materialization_id IS NULL) = (materialization_hash IS NULL)),
    CHECK ((preparation_policy_id IS NULL) = (preparation_policy_hash IS NULL)),
    CHECK (
        (status IN ('ACTIVE', 'READY') AND terminal_reason IS NULL)
        OR
        (status IN ('FAILED_PRE_PLANNER', 'INTERRUPTED')
         AND terminal_reason IS NOT NULL AND length(terminal_reason) > 0)
    ),
    CHECK (status != 'READY' OR stage = 'PREPPOL_PUBLISHED'),
    CHECK (
        status != 'FAILED_PRE_PLANNER'
        OR stage IN ('CLAIMED', 'AUTHORITY_PUBLISHED', 'PLANNING_INPUT_PUBLISHED')
    ),
    CHECK (
        (stage = 'CLAIMED'
         AND capability_catalog_id IS NULL
         AND capability_routing_policy_id IS NULL
         AND dispatch_contract_catalog_id IS NULL
         AND planning_input_id IS NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND plan_proposal_id IS NULL
         AND plan_audit_id IS NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'AUTHORITY_PUBLISHED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND plan_proposal_id IS NULL
         AND plan_audit_id IS NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'PLANNING_INPUT_PUBLISHED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NULL
         AND planner_run_id IS NULL
         AND plan_proposal_id IS NULL
         AND plan_audit_id IS NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'PLANNER_STARTED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NULL
         AND plan_proposal_id IS NULL
         AND plan_audit_id IS NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'PLANNER_RETURNED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND plan_proposal_id IS NOT NULL
         AND plan_audit_id IS NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'PLAN_AUDITED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND plan_proposal_id IS NOT NULL
         AND plan_audit_id IS NOT NULL
         AND materialization_id IS NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'MATERIALIZED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND plan_proposal_id IS NOT NULL
         AND plan_audit_id IS NOT NULL
         AND materialization_id IS NOT NULL
         AND preparation_policy_id IS NULL)
        OR
        (stage = 'PREPPOL_PUBLISHED'
         AND capability_catalog_id IS NOT NULL
         AND capability_routing_policy_id IS NOT NULL
         AND dispatch_contract_catalog_id IS NOT NULL
         AND planning_input_id IS NOT NULL
         AND planner_dependency_plan_hash IS NOT NULL
         AND planner_run_id IS NOT NULL
         AND plan_proposal_id IS NOT NULL
         AND plan_audit_id IS NOT NULL
         AND materialization_id IS NOT NULL
         AND preparation_policy_id IS NOT NULL)
    )
);

CREATE INDEX idx_goal_bootstraps_goal_history
ON goal_bootstraps(project_id, goal_id, goal_revision, created_at, bootstrap_id);

CREATE INDEX idx_goal_bootstraps_status
ON goal_bootstraps(project_id, status, stage, created_at, bootstrap_id);

CREATE UNIQUE INDEX idx_goal_bootstraps_one_current_per_goal_revision
ON goal_bootstraps(project_id, goal_id, goal_revision)
WHERE status IN ('ACTIVE', 'READY');
"""

MIGRATIONS = (
    Migration(1, MIGRATION_001),
    Migration(2, MIGRATION_002),
    Migration(3, MIGRATION_003),
    Migration(4, MIGRATION_004),
    Migration(5, MIGRATION_005),
    Migration(6, MIGRATION_006),
    Migration(7, MIGRATION_007),
    Migration(8, MIGRATION_008),
    Migration(9, MIGRATION_009),
    Migration(10, MIGRATION_010),
    Migration(11, MIGRATION_011),
    Migration(12, MIGRATION_012),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
