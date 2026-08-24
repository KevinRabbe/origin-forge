from __future__ import annotations

from .migrations import Migration


DESIGN_SPECIFICATION_MIGRATION = Migration(
    21,
    r"""
CREATE TABLE design_specification_inputs (
    design_input_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
    goal_revision INTEGER NOT NULL CHECK (goal_revision >= 0),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(design_input_id, content_hash)
);

CREATE TABLE design_specifications (
    design_specification_id TEXT PRIMARY KEY,
    design_input_id TEXT NOT NULL REFERENCES design_specification_inputs(design_input_id) ON DELETE RESTRICT,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(design_specification_id, content_hash)
);

CREATE TABLE design_specification_audits (
    audit_id TEXT PRIMARY KEY,
    design_input_id TEXT NOT NULL REFERENCES design_specification_inputs(design_input_id) ON DELETE RESTRICT,
    design_specification_id TEXT NOT NULL UNIQUE REFERENCES design_specifications(design_specification_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 0),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE(audit_id, content_hash)
);

-- Reserved by schema v21 for Phase 56C. Phase 56A intentionally exposes no
-- application service capable of inserting this relation.
CREATE TABLE design_specification_acceptances (
    acceptance_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
    design_input_id TEXT NOT NULL UNIQUE REFERENCES design_specification_inputs(design_input_id) ON DELETE RESTRICT,
    design_input_hash TEXT NOT NULL CHECK (length(design_input_hash) = 64),
    design_specification_id TEXT NOT NULL UNIQUE REFERENCES design_specifications(design_specification_id) ON DELETE RESTRICT,
    design_specification_hash TEXT NOT NULL CHECK (length(design_specification_hash) = 64),
    audit_id TEXT NOT NULL UNIQUE REFERENCES design_specification_audits(audit_id) ON DELETE RESTRICT,
    audit_hash TEXT NOT NULL CHECK (length(audit_hash) = 64),
    acceptance_authority TEXT NOT NULL CHECK (acceptance_authority = 'HUMAN_OPERATOR'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    accepted_at TEXT NOT NULL CHECK (length(accepted_at) > 0)
);

CREATE INDEX idx_design_specification_inputs_goal
ON design_specification_inputs(project_id, goal_id, created_at, design_input_id);

CREATE INDEX idx_design_specifications_input
ON design_specifications(design_input_id, created_at, design_specification_id);

CREATE INDEX idx_design_specification_audits_input
ON design_specification_audits(design_input_id, status, created_at, audit_id);

CREATE TRIGGER design_specification_inputs_project_goal_insert
BEFORE INSERT ON design_specification_inputs
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM goals
        WHERE id = NEW.goal_id AND project_id = NEW.project_id
    ) THEN RAISE(ABORT, 'design input project/Goal relation is invalid') END;
END;

CREATE TRIGGER design_specifications_input_relation_insert
BEFORE INSERT ON design_specifications
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM design_specification_inputs
        WHERE design_input_id = NEW.design_input_id
    ) THEN RAISE(ABORT, 'design specification input relation is invalid') END;
END;

CREATE TRIGGER design_specification_audits_relation_insert
BEFORE INSERT ON design_specification_audits
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM design_specifications
        WHERE design_specification_id = NEW.design_specification_id
          AND design_input_id = NEW.design_input_id
    ) THEN RAISE(ABORT, 'design audit input/specification relation is invalid') END;
END;

CREATE TRIGGER design_specification_acceptances_relation_insert
BEFORE INSERT ON design_specification_acceptances
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM design_specification_inputs AS i
        JOIN design_specifications AS s
          ON s.design_input_id = i.design_input_id
        JOIN design_specification_audits AS a
          ON a.design_input_id = i.design_input_id
         AND a.design_specification_id = s.design_specification_id
        WHERE i.design_input_id = NEW.design_input_id
          AND i.project_id = NEW.project_id
          AND i.goal_id = NEW.goal_id
          AND i.content_hash = NEW.design_input_hash
          AND s.design_specification_id = NEW.design_specification_id
          AND s.content_hash = NEW.design_specification_hash
          AND a.audit_id = NEW.audit_id
          AND a.content_hash = NEW.audit_hash
          AND a.status = 'PASS'
    ) THEN RAISE(ABORT, 'design acceptance relation is invalid') END;
END;

CREATE TRIGGER design_specification_inputs_immutable_update
BEFORE UPDATE ON design_specification_inputs
BEGIN
    SELECT RAISE(ABORT, 'design specification inputs are immutable');
END;

CREATE TRIGGER design_specification_inputs_immutable_delete
BEFORE DELETE ON design_specification_inputs
BEGIN
    SELECT RAISE(ABORT, 'design specification inputs are immutable');
END;

CREATE TRIGGER design_specifications_immutable_update
BEFORE UPDATE ON design_specifications
BEGIN
    SELECT RAISE(ABORT, 'design specifications are immutable');
END;

CREATE TRIGGER design_specifications_immutable_delete
BEFORE DELETE ON design_specifications
BEGIN
    SELECT RAISE(ABORT, 'design specifications are immutable');
END;

CREATE TRIGGER design_specification_audits_immutable_update
BEFORE UPDATE ON design_specification_audits
BEGIN
    SELECT RAISE(ABORT, 'design specification audits are immutable');
END;

CREATE TRIGGER design_specification_audits_immutable_delete
BEFORE DELETE ON design_specification_audits
BEGIN
    SELECT RAISE(ABORT, 'design specification audits are immutable');
END;

CREATE TRIGGER design_specification_acceptances_immutable_update
BEFORE UPDATE ON design_specification_acceptances
BEGIN
    SELECT RAISE(ABORT, 'design specification acceptances are immutable');
END;

CREATE TRIGGER design_specification_acceptances_immutable_delete
BEFORE DELETE ON design_specification_acceptances
BEGIN
    SELECT RAISE(ABORT, 'design specification acceptances are immutable');
END;
""",
)
