from __future__ import annotations

import json
import sqlite3

from .ids import IdKind, new_id, validate_id
from .model3d_requests import (
    Model3DProductionRequest,
    Model3DRequestError,
    Model3DRequestReader,
    Model3DRequestStore,
)
from .production_model3d_request_authoring_evidence import (
    Model3DRequestAuthoringEvidenceStore,
    inspect_model3d_request_input,
)
from .production_model3d_request_authoring_models import Model3DRequestAuditStatus
from .production_model3d_request_publication_models import (
    Model3DRequestApproval,
    Model3DRequestPublication,
    Model3DRequestPublicationModelError,
    canonical_request_json,
)
from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime
from .service import utc_now


class Model3DRequestPublicationError(RuntimeError):
    pass


def _load_approval_conn(
    conn: sqlite3.Connection, approval_id: str
) -> Model3DRequestApproval:
    row = conn.execute(
        """SELECT approval_id, project_id, task_id, request_input_id, proposal_id,
                  audit_id, request_id, request_hash, request_json, authority, operator_id,
                  schema_version, content_hash, approved_at
           FROM model3d_request_approvals WHERE approval_id = ?""",
        (approval_id,),
    ).fetchone()
    if row is None:
        raise KeyError(approval_id)
    try:
        value = Model3DRequestApproval(
            approval_id=row["approval_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            request_input_id=row["request_input_id"],
            proposal_id=row["proposal_id"],
            audit_id=row["audit_id"],
            request_id=row["request_id"],
            request_hash=row["request_hash"],
            request_json=row["request_json"],
            operator_id=row["operator_id"],
            approved_at=row["approved_at"],
            authority=row["authority"],
            schema_version=row["schema_version"],
        )
    except (Model3DRequestPublicationModelError, TypeError, ValueError) as exc:
        raise Model3DRequestPublicationError("stored M3DREQAPP evidence is invalid") from exc
    if value.content_hash != row["content_hash"]:
        raise Model3DRequestPublicationError("M3DREQAPP content hash drifted")
    return value


def _load_publication_conn(
    conn: sqlite3.Connection, publication_id: str
) -> Model3DRequestPublication:
    row = conn.execute(
        """SELECT publication_id, approval_id, project_id, task_id,
                  request_id, request_hash, schema_version, content_hash, published_at
           FROM model3d_request_publications WHERE publication_id = ?""",
        (publication_id,),
    ).fetchone()
    if row is None:
        raise KeyError(publication_id)
    try:
        value = Model3DRequestPublication(
            publication_id=row["publication_id"],
            approval_id=row["approval_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            request_id=row["request_id"],
            request_hash=row["request_hash"],
            published_at=row["published_at"],
            schema_version=row["schema_version"],
        )
    except (Model3DRequestPublicationModelError, TypeError, ValueError) as exc:
        raise Model3DRequestPublicationError("stored M3DREQPUB evidence is invalid") from exc
    if value.content_hash != row["content_hash"]:
        raise Model3DRequestPublicationError("M3DREQPUB content hash drifted")
    return value


def read_model3d_request_approval(
    runtime: OriginForgeRuntime, approval_id: str
) -> Model3DRequestApproval:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(approval_id, IdKind.MODEL3D_REQUEST_APPROVAL):
        raise ValueError("approval_id must be an M3DREQAPP ID")
    with production_read_connection(runtime) as conn:
        value = _load_approval_conn(conn, approval_id)
        if value.project_id != runtime.project_id():
            raise Model3DRequestPublicationError("M3DREQAPP belongs to another project")
        return value


def read_model3d_request_publication(
    runtime: OriginForgeRuntime, publication_id: str
) -> Model3DRequestPublication:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(publication_id, IdKind.MODEL3D_REQUEST_PUBLICATION):
        raise ValueError("publication_id must be an M3DREQPUB ID")
    with production_read_connection(runtime) as conn:
        value = _load_publication_conn(conn, publication_id)
        if value.project_id != runtime.project_id():
            raise Model3DRequestPublicationError("M3DREQPUB belongs to another project")
        approval = _load_approval_conn(conn, value.approval_id)
        if (
            approval.project_id != value.project_id
            or approval.task_id != value.task_id
            or approval.request_id != value.request_id
            or approval.request_hash != value.request_hash
        ):
            raise Model3DRequestPublicationError("M3DREQPUB approval relation drifted")
        return value


def require_current_model3d_publication(
    runtime: OriginForgeRuntime,
    *,
    task_id: str,
    request_id: str,
    request_hash: str,
) -> Model3DRequestPublication:
    """Require the exact current Phase-57 publication for Blender admission."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(task_id, IdKind.TASK):
        raise ValueError("task_id must be a TASK ID")
    if not validate_id(request_id, IdKind.MODEL3D_REQUEST):
        raise ValueError("request_id must be a MODEL3DREQ ID")
    if not isinstance(request_hash, str) or not request_hash.startswith("sha256:"):
        raise ValueError("request_hash must be a sha256-prefixed digest")
    with production_read_connection(runtime) as conn:
        rows = conn.execute(
            "SELECT publication_id FROM model3d_request_publications WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        if len(rows) != 1:
            raise Model3DRequestPublicationError(
                "Blender admission requires exactly one Phase-57 publication for the Task"
            )
        publication = _load_publication_conn(conn, rows[0]["publication_id"])
        if (
            publication.task_id != task_id
            or publication.request_id != request_id
            or publication.request_hash != request_hash
        ):
            raise Model3DRequestPublicationError(
                "Blender admission request does not match the exact Phase-57 publication"
            )
        approval = _load_approval_conn(conn, publication.approval_id)
        if approval.project_id != runtime.project_id():
            raise Model3DRequestPublicationError("Phase-57 publication belongs to another project")
        if (
            approval.task_id != task_id
            or approval.request_id != request_id
            or approval.request_hash != request_hash
        ):
            raise Model3DRequestPublicationError("Phase-57 approval relation drifted")
    evidence = Model3DRequestAuthoringEvidenceStore(runtime)
    inspection = inspect_model3d_request_input(
        runtime, approval.request_input_id, evidence_store=evidence
    )
    if not inspection.current:
        raise Model3DRequestPublicationError(
            f"Phase-57 publication is historical: {inspection.stale_reason}"
        )
    try:
        request = Model3DRequestReader(runtime).get(request_id, request_hash)
    except (KeyError, Model3DRequestError, RuntimeError, TypeError, ValueError) as exc:
        raise Model3DRequestPublicationError(
            "Phase-57 publication protected request is unavailable or drifted"
        ) from exc
    if request.request_hash != request_hash:
        raise Model3DRequestPublicationError("Phase-57 protected request hash drifted")
    return publication


def _request_for_approval(
    runtime: OriginForgeRuntime,
    *,
    proposal_id: str,
    audit_id: str,
) -> tuple[object, object, object, Model3DProductionRequest]:
    evidence = Model3DRequestAuthoringEvidenceStore(runtime)
    proposal = evidence.load_proposal(proposal_id)
    audit = evidence.load_audit(audit_id)
    if audit.proposal_id != proposal.proposal_id or audit.status is not Model3DRequestAuditStatus.PASS:
        raise Model3DRequestPublicationError("publication requires the exact PASS M3DREQAUD")
    request_input = evidence.load_input(proposal.request_input_id)
    inspection = inspect_model3d_request_input(
        runtime, request_input.request_input_id, evidence_store=evidence
    )
    if not inspection.current:
        raise Model3DRequestPublicationError(
            f"M3DREQIN is stale: {inspection.stale_reason}"
        )
    request = Model3DProductionRequest.create(project=proposal.project)
    return request_input, proposal, audit, request


def approve_model3d_request_publication(
    runtime: OriginForgeRuntime,
    proposal_id: str,
    *,
    audit_id: str | None = None,
    operator_id: str | None = None,
) -> Model3DRequestApproval:
    """Explicit HUMAN_OPERATOR approval of one exact audited proposal."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not validate_id(proposal_id, IdKind.MODEL3D_REQUEST_PROPOSAL):
        raise ValueError("proposal_id must be an M3DREQPROP ID")
    evidence = Model3DRequestAuthoringEvidenceStore(runtime)
    proposal = evidence.load_proposal(proposal_id)
    audit = evidence.audit_for_proposal(proposal_id)
    if audit_id is not None and audit_id != (audit.audit_id if audit else None):
        raise Model3DRequestPublicationError("audit_id does not match the exact proposal audit")
    if audit is None:
        raise Model3DRequestPublicationError("publication requires durable M3DREQAUD evidence")
    request_input, proposal, audit, request = _request_for_approval(
        runtime, proposal_id=proposal_id, audit_id=audit.audit_id
    )
    request_json = canonical_request_json(request)
    candidate = Model3DRequestApproval(
        approval_id=new_id(IdKind.MODEL3D_REQUEST_APPROVAL),
        project_id=runtime.project_id(),
        task_id=request_input.task_id,
        request_input_id=request_input.request_input_id,
        proposal_id=proposal.proposal_id,
        audit_id=audit.audit_id,
        request_id=request.request_id,
        request_hash=request.request_hash,
        request_json=request_json,
        operator_id=operator_id,
        approved_at=utc_now(),
    )
    with runtime.store.session() as conn:
        existing = conn.execute(
            "SELECT approval_id FROM model3d_request_approvals WHERE task_id = ?",
            (candidate.task_id,),
        ).fetchone()
        if existing is not None:
            value = _load_approval_conn(conn, existing["approval_id"])
            if (
                value.project_id != candidate.project_id
                or value.task_id != candidate.task_id
                or value.request_input_id != candidate.request_input_id
                or value.proposal_id != candidate.proposal_id
                or value.audit_id != candidate.audit_id
            ):
                raise Model3DRequestPublicationError(
                    "a different M3DREQAPP already exists for this Task"
                )
            return value
        try:
            conn.execute(
                """INSERT INTO model3d_request_approvals(
                    approval_id, project_id, task_id, request_input_id, proposal_id,
                    audit_id, request_id, request_hash, request_json, authority,
                    operator_id, schema_version, content_hash, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate.approval_id,
                    candidate.project_id,
                    candidate.task_id,
                    candidate.request_input_id,
                    candidate.proposal_id,
                    candidate.audit_id,
                    candidate.request_id,
                    candidate.request_hash,
                    candidate.request_json,
                    candidate.authority,
                    candidate.operator_id,
                    candidate.schema_version,
                    candidate.content_hash,
                    candidate.approved_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise Model3DRequestPublicationError("M3DREQAPP publication relation failed") from exc
    return candidate


def publish_approved_model3d_request(
    runtime: OriginForgeRuntime, approval_id: str
) -> Model3DRequestPublication:
    """Create-only publish the exact approval-frozen request and relation."""
    approval = read_model3d_request_approval(runtime, approval_id)
    with runtime.store.session() as conn:
        existing = conn.execute(
            "SELECT publication_id FROM model3d_request_publications WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone()
        existing_id = existing["publication_id"] if existing is not None else None
    if existing_id is not None:
        return read_model3d_request_publication(runtime, existing_id)

    try:
        payload = json.loads(approval.request_json)
        if not isinstance(payload, dict):
            raise TypeError("request JSON must be an object")
        proposal = Model3DRequestAuthoringEvidenceStore(runtime).load_proposal(approval.proposal_id)
        request = Model3DProductionRequest(
            request_id=approval.request_id,
            operation=proposal.operation,
            project=proposal.project,
        )
        if request.request_hash != approval.request_hash or request.to_dict() != payload:
            raise Model3DRequestPublicationError("approval-frozen request bytes drifted")
        Model3DRequestStore(runtime).put(request)
        stored = Model3DRequestReader(runtime).get(request.request_id, request.request_hash)
        if stored.to_dict() != payload:
            raise Model3DRequestPublicationError("protected MODEL3D request readback drifted")
    except (KeyError, TypeError, ValueError, Model3DRequestError, Model3DRequestPublicationError) as exc:
        if isinstance(exc, Model3DRequestPublicationError):
            raise
        raise Model3DRequestPublicationError("approval-frozen MODEL3D request is invalid") from exc

    candidate = Model3DRequestPublication(
        publication_id=new_id(IdKind.MODEL3D_REQUEST_PUBLICATION),
        approval_id=approval.approval_id,
        project_id=approval.project_id,
        task_id=approval.task_id,
        request_id=approval.request_id,
        request_hash=approval.request_hash,
        published_at=utc_now(),
    )
    with runtime.store.session() as conn:
        existing = conn.execute(
            "SELECT publication_id FROM model3d_request_publications WHERE task_id = ?",
            (candidate.task_id,),
        ).fetchone()
        if existing is not None:
            value = _load_publication_conn(conn, existing["publication_id"])
            if value.to_dict() != candidate.to_dict():
                raise Model3DRequestPublicationError(
                    "a different M3DREQPUB already exists for this Task"
                )
            return value
        try:
            conn.execute(
                """INSERT INTO model3d_request_publications(
                    publication_id, approval_id, project_id, task_id, request_id,
                    request_hash, schema_version, content_hash, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate.publication_id,
                    candidate.approval_id,
                    candidate.project_id,
                    candidate.task_id,
                    candidate.request_id,
                    candidate.request_hash,
                    candidate.schema_version,
                    candidate.content_hash,
                    candidate.published_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise Model3DRequestPublicationError("M3DREQPUB publication relation failed") from exc
    return candidate
