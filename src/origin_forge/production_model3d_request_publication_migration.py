from __future__ import annotations

from .migrations import Migration

MODEL3D_REQUEST_PUBLICATION_MIGRATION = Migration(
    23,
    r"""
CREATE TABLE model3d_request_approvals (
    approval_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    request_input_id TEXT NOT NULL REFERENCES model3d_request_inputs(request_input_id) ON DELETE RESTRICT,
    proposal_id TEXT NOT NULL REFERENCES model3d_request_proposals(proposal_id) ON DELETE RESTRICT,
    audit_id TEXT NOT NULL UNIQUE REFERENCES model3d_request_audits(audit_id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 71 AND substr(request_hash, 1, 7) = 'sha256:'),
    request_json TEXT NOT NULL CHECK (length(request_json) > 0),
    operator_id TEXT,
    authority TEXT NOT NULL CHECK (authority = 'HUMAN_OPERATOR'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    approved_at TEXT NOT NULL CHECK (length(approved_at) > 0),
    UNIQUE(approval_id, content_hash),
    UNIQUE(task_id),
    UNIQUE(request_id, request_hash)
);

CREATE TABLE model3d_request_publications (
    publication_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL UNIQUE REFERENCES model3d_request_approvals(approval_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 71 AND substr(request_hash, 1, 7) = 'sha256:'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    published_at TEXT NOT NULL CHECK (length(published_at) > 0),
    UNIQUE(publication_id, content_hash),
    FOREIGN KEY (request_id, request_hash)
        REFERENCES model3d_request_approvals(request_id, request_hash)
        ON DELETE RESTRICT
);

CREATE INDEX idx_model3d_request_approvals_task
ON model3d_request_approvals(task_id, approval_id);

CREATE INDEX idx_model3d_request_publications_task
ON model3d_request_publications(task_id, publication_id);

CREATE TRIGGER model3d_request_approvals_relation_insert
BEFORE INSERT ON model3d_request_approvals
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM model3d_request_inputs AS i
        JOIN model3d_request_proposals AS p ON p.proposal_id = NEW.proposal_id
                                           AND p.request_input_id = i.request_input_id
        JOIN model3d_request_audits AS a ON a.audit_id = NEW.audit_id
                                         AND a.proposal_id = p.proposal_id
                                         AND a.request_input_id = i.request_input_id
                                         AND a.status = 'PASS'
        WHERE i.request_input_id = NEW.request_input_id
          AND i.project_id = NEW.project_id
          AND i.task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'MODEL3D request approval relation is invalid') END;
END;

CREATE TRIGGER model3d_request_publications_relation_insert
BEFORE INSERT ON model3d_request_publications
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM model3d_request_approvals AS a
        WHERE a.approval_id = NEW.approval_id
          AND a.project_id = NEW.project_id
          AND a.task_id = NEW.task_id
          AND a.request_id = NEW.request_id
          AND a.request_hash = NEW.request_hash
    ) THEN RAISE(ABORT, 'MODEL3D request publication relation is invalid') END;
END;

CREATE TRIGGER model3d_request_approvals_immutable_update
BEFORE UPDATE ON model3d_request_approvals
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request approvals are immutable');
END;

CREATE TRIGGER model3d_request_approvals_immutable_delete
BEFORE DELETE ON model3d_request_approvals
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request approvals are immutable');
END;

CREATE TRIGGER model3d_request_publications_immutable_update
BEFORE UPDATE ON model3d_request_publications
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request publications are immutable');
END;

CREATE TRIGGER model3d_request_publications_immutable_delete
BEFORE DELETE ON model3d_request_publications
BEGIN
    SELECT RAISE(ABORT, 'MODEL3D request publications are immutable');
END;
""",
)
