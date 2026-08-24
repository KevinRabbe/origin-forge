from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .production_capability_store import ProductionCapabilityStoreError
from .production_design_specification_currentness import (
    AcceptedDesignError,
    DesignSpecificationAcceptance,
    _ReadOnlyProductionCapabilityStore,
    _load_exact_relation,
    inspect_accepted_design,
)
from .production_design_specification_evidence import (
    DesignSpecificationEvidenceError,
    DesignSpecificationEvidenceStore,
)
from .production_design_specification_models import DesignSpecificationAuditStatus
from .runtime import OriginForgeRuntime
from .service import utc_now


class GovernedDesignSpecificationAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernedDesignSpecificationAcceptanceResult:
    acceptance_id: str
    project_id: str
    goal_id: str
    design_input_id: str
    design_input_hash: str
    design_specification_id: str
    design_specification_hash: str
    audit_id: str
    audit_hash: str
    acceptance_authority: str
    accepted_at: str
    current: bool
    stale_reason: str | None

    @classmethod
    def from_acceptance(
        cls,
        acceptance: DesignSpecificationAcceptance,
        *,
        current: bool,
        stale_reason: str | None,
    ) -> "GovernedDesignSpecificationAcceptanceResult":
        return cls(
            acceptance_id=acceptance.acceptance_id,
            project_id=acceptance.project_id,
            goal_id=acceptance.goal_id,
            design_input_id=acceptance.design_input_id,
            design_input_hash=acceptance.design_input_hash,
            design_specification_id=acceptance.design_specification_id,
            design_specification_hash=acceptance.design_specification_hash,
            audit_id=acceptance.audit_id,
            audit_hash=acceptance.audit_hash,
            acceptance_authority=acceptance.acceptance_authority,
            accepted_at=acceptance.accepted_at,
            current=current,
            stale_reason=stale_reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptance_id": self.acceptance_id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "design_input_id": self.design_input_id,
            "design_input_hash": self.design_input_hash,
            "design_specification_id": self.design_specification_id,
            "design_specification_hash": self.design_specification_hash,
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "acceptance_authority": self.acceptance_authority,
            "accepted_at": self.accepted_at,
            "current": self.current,
            "stale_reason": self.stale_reason,
        }


def _project_id_conn(runtime: OriginForgeRuntime, conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise GovernedDesignSpecificationAcceptanceError(
            "project is not bound to this repository root"
        )
    return row["id"]


def _load_candidate_conn(
    runtime: OriginForgeRuntime,
    conn: sqlite3.Connection,
    *,
    design_specification_id: str,
    evidence: DesignSpecificationEvidenceStore,
    capability_store: _ReadOnlyProductionCapabilityStore,
):
    try:
        specification = evidence._load_specification_conn(
            conn, design_specification_id
        )
        design_input = evidence._load_input_conn(conn, specification.design_input_id)
    except (DesignSpecificationEvidenceError, KeyError) as exc:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification candidate failed durable validation"
        ) from exc

    project_id = _project_id_conn(runtime, conn)
    if design_input.project_id != project_id:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification candidate belongs to another project"
        )

    audit_rows = conn.execute(
        """SELECT audit_id
           FROM design_specification_audits
           WHERE design_specification_id = ?
           ORDER BY audit_id""",
        (design_specification_id,),
    ).fetchall()
    if len(audit_rows) != 1:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification requires exactly one durable structural audit"
        )
    try:
        audit = evidence._load_audit_conn(conn, audit_rows[0]["audit_id"])
    except (DesignSpecificationEvidenceError, KeyError) as exc:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification audit failed durable validation"
        ) from exc
    if audit.status is not DesignSpecificationAuditStatus.PASS:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification audit is not PASS"
        )

    try:
        evidence._assert_semantic_binding_conn(conn, design_input)
        evidence._assert_capability_binding(design_input, capability_store)
    except (
        DesignSpecificationEvidenceError,
        ProductionCapabilityStoreError,
        KeyError,
    ) as exc:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification source evidence is not current"
        ) from exc
    return project_id, design_input, specification, audit


def _existing_acceptance_conn(
    conn: sqlite3.Connection,
    *,
    design_input_id: str,
    design_specification_id: str,
    audit_id: str,
    evidence: DesignSpecificationEvidenceStore,
) -> DesignSpecificationAcceptance | None:
    rows = conn.execute(
        """SELECT acceptance_id, design_input_id, design_specification_id, audit_id
           FROM design_specification_acceptances
           WHERE design_input_id = ? OR design_specification_id = ?
           ORDER BY acceptance_id""",
        (design_input_id, design_specification_id),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise GovernedDesignSpecificationAcceptanceError(
            "design specification acceptance relation is ambiguous"
        )
    row = rows[0]
    if (
        row["design_input_id"] != design_input_id
        or row["design_specification_id"] != design_specification_id
        or row["audit_id"] != audit_id
    ):
        raise GovernedDesignSpecificationAcceptanceError(
            "another design specification already owns acceptance for this input"
        )
    try:
        acceptance, _, _, _ = _load_exact_relation(
            conn,
            acceptance_id=row["acceptance_id"],
            evidence=evidence,
        )
    except (AcceptedDesignError, KeyError) as exc:
        raise GovernedDesignSpecificationAcceptanceError(
            "existing design acceptance failed exact validation"
        ) from exc
    return acceptance


def _publish_acceptance(
    runtime: OriginForgeRuntime,
    design_specification_id: str,
) -> DesignSpecificationAcceptance:
    evidence = DesignSpecificationEvidenceStore(runtime)
    capability_store = _ReadOnlyProductionCapabilityStore(runtime)
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project_id, design_input, specification, audit = _load_candidate_conn(
            runtime,
            conn,
            design_specification_id=design_specification_id,
            evidence=evidence,
            capability_store=capability_store,
        )
        existing = _existing_acceptance_conn(
            conn,
            design_input_id=design_input.design_input_id,
            design_specification_id=specification.design_specification_id,
            audit_id=audit.audit_id,
            evidence=evidence,
        )
        if existing is not None:
            return existing

        acceptance = DesignSpecificationAcceptance(
            acceptance_id=new_id(IdKind.DESIGN_SPECIFICATION_ACCEPTANCE),
            project_id=project_id,
            goal_id=design_input.goal_id,
            design_input_id=design_input.design_input_id,
            design_input_hash=design_input.content_hash,
            design_specification_id=specification.design_specification_id,
            design_specification_hash=specification.content_hash,
            audit_id=audit.audit_id,
            audit_hash=audit.content_hash,
            acceptance_authority="HUMAN_OPERATOR",
            schema_version=1,
            accepted_at=utc_now(),
        )
        try:
            conn.execute(
                """INSERT INTO design_specification_acceptances(
                       acceptance_id, project_id, goal_id,
                       design_input_id, design_input_hash,
                       design_specification_id, design_specification_hash,
                       audit_id, audit_hash, acceptance_authority,
                       schema_version, content_hash, accepted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    acceptance.acceptance_id,
                    acceptance.project_id,
                    acceptance.goal_id,
                    acceptance.design_input_id,
                    acceptance.design_input_hash,
                    acceptance.design_specification_id,
                    acceptance.design_specification_hash,
                    acceptance.audit_id,
                    acceptance.audit_hash,
                    acceptance.acceptance_authority,
                    acceptance.schema_version,
                    acceptance.content_hash,
                    acceptance.accepted_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise GovernedDesignSpecificationAcceptanceError(
                "design specification acceptance conflicted with durable authority"
            ) from exc

        try:
            canonical, loaded_input, loaded_specification, loaded_audit = _load_exact_relation(
                conn,
                acceptance_id=acceptance.acceptance_id,
                evidence=evidence,
            )
        except (AcceptedDesignError, KeyError) as exc:
            raise GovernedDesignSpecificationAcceptanceError(
                "published design acceptance failed exact readback validation"
            ) from exc
        if (
            canonical != acceptance
            or loaded_input != design_input
            or loaded_specification != specification
            or loaded_audit != audit
        ):
            raise GovernedDesignSpecificationAcceptanceError(
                "published design acceptance readback relation drifted"
            )
        return canonical


class GovernedDesignSpecificationAcceptor:
    """Explicit HUMAN_OPERATOR acceptance of one exact durable design proposal."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    def accept(
        self,
        design_specification_id: str,
    ) -> GovernedDesignSpecificationAcceptanceResult:
        if not isinstance(design_specification_id, str) or not validate_id(
            design_specification_id, IdKind.DESIGN_SPECIFICATION
        ):
            raise ValueError("design_specification_id must be a DESIGNSPEC ID")

        acceptance = _publish_acceptance(self.runtime, design_specification_id)
        try:
            inspection = inspect_accepted_design(
                self.runtime,
                acceptance.acceptance_id,
            )
        except (AcceptedDesignError, KeyError) as exc:
            raise GovernedDesignSpecificationAcceptanceError(
                "durable design acceptance failed post-publication inspection"
            ) from exc
        return GovernedDesignSpecificationAcceptanceResult.from_acceptance(
            acceptance,
            current=inspection.current,
            stale_reason=inspection.stale_reason,
        )
