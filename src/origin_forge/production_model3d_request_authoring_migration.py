from __future__ import annotations

from .migrations import Migration


MODEL3D_REQUEST_AUTHORING_MIGRATION = Migration(
    22,
    r"""
CREATE TABLE model3d_request_inputs (
    request_input_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE RESTRICT,
    task_revision INTEGER NOT NULL CHECK (task_revision >= 0),
    task_content_hash TEXT NOT NULL CHECK (length(task_content_hash) = 64),
    materialization_id TEXT NOT NULL REFERENCES plan_materializations(materialization_id) ON DELETE RESTRICT,
    planning_input_id TEXT NOT NULL REFERENCES planning_inputs(planning_input_id) ON DELETE RESTRICT,
    design_acceptance_id TEXT NOT NULL REFERENCES design_specification_acceptances(acceptance_id) ON DELETE RESTRICT,
    design_specification_id TEXT NOT NULL REFERENCES design_specifications(design_specification_id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(
        task_id, task_revision, task_content_hash, materialization_id,
        planning_input_id, design_acceptance_id, design_specification_id
    ),
    UNIQUE(request_input_id, content_hash)
);

CREATE TABLE model3d_request_proposals (
    proposal_id TEXT PRIMARY KEY,
    request_input_id TEXT NOT NULL REFERENCES model3d_request_inputs(request_input_id) ON DELETE RESTRICT,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(proposal_id, content_hash)
);

CREATE TABLE model3d_request_audits (
    audit_id TEXT PRIMARY KEY,
    request_input_id TEXT NOT NULL REFERENCES model3d_request_inputs(request_input_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES model3d_request_proposals(proposal_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(audit_id, content_hash)
);

CREATE INDEX idx_model3d_request_inputs_task
ON model3d_request_inputs(task_id, task_revision, request_input_id);

CREATE INDEX idx_model3d_request_proposals_input
ON model3d_request_proposals(request_input_id, proposal_id);

CREATE INDEX idx_model3d_request_audits_input
ON model3d_request_audits(request_input_id, status, audit_id);

CREATE TRIGGER model3d_request_inputs_relation_insert
BEFORE INSERT ON model3d_request_inputs
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM tasks AS t
        JOIN flows AS f ON f.id = t.flow_id
        JOIN goals AS g ON g.id = f.goal_id
        JOIN plan_materializations AS m ON m.flow_id = f.id
        JOIN planning_inputs AS p ON p.planning_input_id = m.planning_input_id
        JOIN design_specification_acceptances AS a
          ON a.acceptance_id = NEW.design_acceptance_id
        JOIN design_specifications AS s
          ON s.design_specification_id = NEW.design_specification_id
         AND s.design_specification_id = a.design_specification_id
        WHERE t.id = NEW.task_id
          AND t.flow_id = NEW.flow_id
          AND t.revision = NEW.task_revision
          AND g.project_id = NEW.project_id
          AND m.materialization_id = NEW.materialization_id
          AND p.planning_input_id = NEW.planning_input_id
          AND p.project_id = NEW.project_id
          AND p.goal_id = g.id
          AND a.project_id = NEW.project_id
          AND a.goal_id = g.id
    ) THEN RAISE(ABORT, 'MODEL3D request input relation is invalid') END;
END;

CREATE TRIGGER model3d_request_proposals_relation_insert
BEFORE INSERT ON model3d_request_proposals
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM model3d_request_inputs
        WHERE request_input_id = NEW.request_input_id
    ) THEN RAISE(ABORT, 'MODEL3D request proposal input relation is invalid') END;
END;

CREATE TRIGGER model3d_request_audits_relation_insert
BEFORE INSERT ON model3d_request_audits
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM model3d_request_proposals
        WHERE proposal_id = NEW.proposal_id
          AND request_input_id = NEW.request_input_id
    ) THEN RAISE(ABORT, 'MODEL3D request audit relation is invalid') END;
END;

CREATE TRIGGER model3d_request_inputs_immutable_update
BEFORE UPDATE ON model3d_request_inputs
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request inputs are immutable');
END;

CREATE TRIGGER model3d_request_inputs_immutable_delete
BEFORE DELETE ON model3d_request_inputs
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request inputs are immutable');
END;

CREATE TRIGGER model3d_request_proposals_immutable_update
BEFORE UPDATE ON model3d_request_proposals
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request proposals are immutable');
END;

CREATE TRIGGER model3d_request_proposals_immutable_delete
BEFORE DELETE ON model3d_request_proposals
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request proposals are immutable');
END;

CREATE TRIGGER model3d_request_audits_immutable_update
BEFORE UPDATE ON model3d_request_audits
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request audits are immutable');
END;

CREATE TRIGGER model3d_request_audits_immutable_delete
BEFORE DELETE ON model3d_request_audits
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request audits are immutable');
END;
""",
)