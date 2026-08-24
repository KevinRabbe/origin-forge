from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id
from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_design_specification_evidence import (
    DesignSpecificationEvidenceError,
    DesignSpecificationEvidenceStore,
    _semantic_snapshot,
)
from .production_design_specification_models import (
    DesignSpecification,
    DesignSpecificationAudit,
    DesignSpecificationAuditStatus,
    DesignSpecificationInput,
)
from .production_planning_evidence import (
    ProductionPlanningEvidenceError,
    ProductionPlanningEvidenceStore,
    goal_planning_hash,
)
from .production_planning_models import PlanningEvidenceRef, PlanningInput
from .production_read_guard import production_read_connection
from .runtime import OriginForgeRuntime


_ACCEPTANCE_SCHEMA_VERSION = 1
_ACCEPTANCE_AUTHORITY = "HUMAN_OPERATOR"
_MAX_ACCEPTED_AT_CHARS = 128


class AcceptedDesignError(RuntimeError):
    pass


def _canonical_hash(value: object) -> str:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AcceptedDesignError("accepted design evidence is not canonical JSON") from exc
    return hashlib.sha256(data).hexdigest()


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise AcceptedDesignError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class DesignSpecificationAcceptance:
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
    schema_version: int
    accepted_at: str

    def __post_init__(self) -> None:
        checks = (
            (self.acceptance_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE, "acceptance_id"),
            (self.project_id, IdKind.PROJECT, "project_id"),
            (self.goal_id, IdKind.GOAL, "goal_id"),
            (self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT, "design_input_id"),
            (
                self.design_specification_id,
                IdKind.DESIGN_SPECIFICATION,
                "design_specification_id",
            ),
            (self.audit_id, IdKind.DESIGN_SPECIFICATION_AUDIT, "audit_id"),
        )
        for value, kind, label in checks:
            if not validate_id(value, kind):
                raise AcceptedDesignError(f"{label} has invalid identity")
        for value, label in (
            (self.design_input_hash, "design_input_hash"),
            (self.design_specification_hash, "design_specification_hash"),
            (self.audit_hash, "audit_hash"),
        ):
            _sha256(value, label)
        if self.acceptance_authority != _ACCEPTANCE_AUTHORITY:
            raise AcceptedDesignError("design acceptance authority is not HUMAN_OPERATOR")
        if self.schema_version != _ACCEPTANCE_SCHEMA_VERSION:
            raise AcceptedDesignError("design acceptance schema version drifted")
        if (
            not isinstance(self.accepted_at, str)
            or not self.accepted_at
            or len(self.accepted_at) > _MAX_ACCEPTED_AT_CHARS
        ):
            raise AcceptedDesignError("design acceptance timestamp is invalid")

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
            "schema_version": self.schema_version,
            "accepted_at": self.accepted_at,
        }

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class AcceptedDesignInspection:
    acceptance: DesignSpecificationAcceptance
    design_input: DesignSpecificationInput
    specification: DesignSpecification
    audit: DesignSpecificationAudit
    current: bool
    stale_reason: str | None

    def __post_init__(self) -> None:
        if self.current != (self.stale_reason is None):
            raise AcceptedDesignError("accepted design currentness result is inconsistent")


class DesignRecoveryStage(StrEnum):
    INPUT_ONLY = "INPUT_ONLY"
    SPECIFICATION_DURABLE = "SPECIFICATION_DURABLE"
    AUDIT_DURABLE = "AUDIT_DURABLE"
    PASS_AUDIT_DURABLE = "PASS_AUDIT_DURABLE"
    ACCEPTANCE_DURABLE = "ACCEPTANCE_DURABLE"


@dataclass(frozen=True)
class DesignRecoveryCandidate:
    design_specification_id: str
    design_specification_hash: str
    audit_id: str | None
    audit_hash: str | None
    audit_status: str | None
    acceptance_id: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.design_specification_id, IdKind.DESIGN_SPECIFICATION):
            raise AcceptedDesignError("recovery specification identity is invalid")
        _sha256(self.design_specification_hash, "recovery design_specification_hash")
        if self.audit_id is None:
            if self.audit_hash is not None or self.audit_status is not None:
                raise AcceptedDesignError("recovery audit relation is incomplete")
        else:
            if not validate_id(self.audit_id, IdKind.DESIGN_SPECIFICATION_AUDIT):
                raise AcceptedDesignError("recovery audit identity is invalid")
            _sha256(self.audit_hash, "recovery audit_hash")
            if self.audit_status not in (
                DesignSpecificationAuditStatus.PASS.value,
                DesignSpecificationAuditStatus.FAIL.value,
            ):
                raise AcceptedDesignError("recovery audit status is invalid")
        if self.acceptance_id is not None and not validate_id(
            self.acceptance_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE
        ):
            raise AcceptedDesignError("recovery acceptance identity is invalid")


@dataclass(frozen=True)
class DesignRecoveryInspection:
    design_input_id: str
    design_input_hash: str
    stage: DesignRecoveryStage
    candidates: tuple[DesignRecoveryCandidate, ...]
    acceptance_id: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT):
            raise AcceptedDesignError("recovery design input identity is invalid")
        _sha256(self.design_input_hash, "recovery design_input_hash")
        if self.acceptance_id is not None and not validate_id(
            self.acceptance_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE
        ):
            raise AcceptedDesignError("recovery acceptance identity is invalid")


def _acceptance_from_row(row: sqlite3.Row) -> DesignSpecificationAcceptance:
    try:
        value = DesignSpecificationAcceptance(
            acceptance_id=row["acceptance_id"],
            project_id=row["project_id"],
            goal_id=row["goal_id"],
            design_input_id=row["design_input_id"],
            design_input_hash=row["design_input_hash"],
            design_specification_id=row["design_specification_id"],
            design_specification_hash=row["design_specification_hash"],
            audit_id=row["audit_id"],
            audit_hash=row["audit_hash"],
            acceptance_authority=row["acceptance_authority"],
            schema_version=row["schema_version"],
            accepted_at=row["accepted_at"],
        )
    except (AcceptedDesignError, KeyError, TypeError, ValueError) as exc:
        raise AcceptedDesignError("stored DESIGNACC failed typed validation") from exc
    stored_hash = _sha256(row["content_hash"], "stored acceptance content_hash")
    if value.content_hash != stored_hash:
        raise AcceptedDesignError("stored DESIGNACC canonical hash drifted")
    return value


def _load_exact_relation(
    conn: sqlite3.Connection,
    *,
    acceptance_id: str,
    evidence: DesignSpecificationEvidenceStore,
) -> tuple[
    DesignSpecificationAcceptance,
    DesignSpecificationInput,
    DesignSpecification,
    DesignSpecificationAudit,
]:
    if not validate_id(acceptance_id, IdKind.DESIGN_SPECIFICATION_ACCEPTANCE):
        raise AcceptedDesignError("acceptance_id must be a DESIGNACC ID")
    row = conn.execute(
        "SELECT * FROM design_specification_acceptances WHERE acceptance_id = ?",
        (acceptance_id,),
    ).fetchone()
    if row is None:
        raise KeyError(acceptance_id)
    acceptance = _acceptance_from_row(row)
    try:
        design_input = evidence._load_input_conn(conn, acceptance.design_input_id)
        specification = evidence._load_specification_conn(
            conn, acceptance.design_specification_id
        )
        audit = evidence._load_audit_conn(conn, acceptance.audit_id)
    except (DesignSpecificationEvidenceError, KeyError) as exc:
        raise AcceptedDesignError("DESIGNACC referenced evidence failed validation") from exc
    if (
        acceptance.project_id != design_input.project_id
        or acceptance.goal_id != design_input.goal_id
        or acceptance.design_input_hash != design_input.content_hash
        or specification.design_input_id != design_input.design_input_id
        or specification.design_input_hash != design_input.content_hash
        or acceptance.design_specification_hash != specification.content_hash
        or audit.design_input_id != design_input.design_input_id
        or audit.design_input_hash != design_input.content_hash
        or audit.design_specification_id != specification.design_specification_id
        or audit.design_specification_hash != specification.content_hash
        or acceptance.audit_hash != audit.content_hash
        or audit.status is not DesignSpecificationAuditStatus.PASS
    ):
        raise AcceptedDesignError("DESIGNACC exact evidence relation drifted")
    conflicts = conn.execute(
        """SELECT COUNT(*) AS n
           FROM design_specification_acceptances
           WHERE design_input_id = ?""",
        (design_input.design_input_id,),
    ).fetchone()
    if conflicts is None or int(conflicts["n"]) != 1:
        raise AcceptedDesignError("DESIGNACC input relation is ambiguous")
    return acceptance, design_input, specification, audit


def _capability_currentness(
    evidence: DesignSpecificationEvidenceStore,
    design_input: DesignSpecificationInput,
    capability_store: ProductionCapabilityStore,
) -> str | None:
    try:
        catalog_ref, policy_ref, _ = evidence._governed_capability_refs(design_input)
        catalog = capability_store.load_catalog(catalog_ref.ref_id)
        policy = capability_store.load_policy(policy_ref.ref_id)
    except (
        DesignSpecificationEvidenceError,
        ProductionCapabilityStoreError,
        KeyError,
    ):
        return "capability authority is unavailable or invalid"
    if catalog.content_hash != catalog_ref.content_hash:
        return "capability catalog hash drifted"
    if policy.content_hash != policy_ref.content_hash:
        return "capability routing policy hash drifted"
    if (
        policy.catalog_id != catalog.catalog_id
        or policy.catalog_hash != catalog.content_hash
    ):
        return "capability policy/catalog relation drifted"
    if design_input.capability_catalog_hash != catalog.content_hash:
        return "design input capability catalog binding drifted"
    if tuple(design_input.capability_ids) != tuple(sorted(policy.allowed_capability_ids)):
        return "design input capability set drifted"
    return None


def _semantic_currentness_conn(
    conn: sqlite3.Connection,
    evidence: DesignSpecificationEvidenceStore,
    design_input: DesignSpecificationInput,
) -> str | None:
    goal = conn.execute(
        "SELECT * FROM goals WHERE id = ? AND project_id = ?",
        (design_input.goal_id, design_input.project_id),
    ).fetchone()
    if goal is None:
        return "Goal binding is unavailable"
    if (
        int(goal["revision"]) != design_input.goal_revision
        or goal_planning_hash(goal) != design_input.goal_content_hash
    ):
        return "Goal binding is stale"
    try:
        snapshot = _semantic_snapshot(conn, design_input.project_id)
        _, _, semantic_refs = evidence._governed_capability_refs(design_input)
    except DesignSpecificationEvidenceError as exc:
        raise AcceptedDesignError(
            "accepted design semantic evidence failed validation"
        ) from exc
    if semantic_refs != snapshot.verified_state_refs:
        return "verified semantic state drifted"
    if design_input.active_design_rule_refs != snapshot.active_design_rule_refs:
        return "Design Rule binding drifted"
    if design_input.project_intelligence_hash != snapshot.project_intelligence_hash:
        return "Project Intelligence binding drifted"
    return None


def inspect_accepted_design(
    runtime: OriginForgeRuntime,
    acceptance_id: str,
) -> AcceptedDesignInspection:
    """Read and deterministically classify one durable DESIGNACC without mutation."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    evidence = DesignSpecificationEvidenceStore(runtime)
    capability_store = ProductionCapabilityStore(runtime)
    with production_read_connection(runtime) as conn:
        acceptance, design_input, specification, audit = _load_exact_relation(
            conn,
            acceptance_id=acceptance_id,
            evidence=evidence,
        )
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None or project["id"] != acceptance.project_id:
            raise AcceptedDesignError("DESIGNACC belongs to another project")
        stale_reason = _semantic_currentness_conn(conn, evidence, design_input)
        if stale_reason is None:
            stale_reason = _capability_currentness(
                evidence, design_input, capability_store
            )
        return AcceptedDesignInspection(
            acceptance=acceptance,
            design_input=design_input,
            specification=specification,
            audit=audit,
            current=stale_reason is None,
            stale_reason=stale_reason,
        )


def inspect_design_recovery(
    runtime: OriginForgeRuntime,
    design_input_id: str,
) -> DesignRecoveryInspection:
    """Inspect durable Phase-56 checkpoints only; never replay the design model."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    evidence = DesignSpecificationEvidenceStore(runtime)
    with production_read_connection(runtime) as conn:
        try:
            design_input = evidence._load_input_conn(conn, design_input_id)
        except (DesignSpecificationEvidenceError, KeyError) as exc:
            raise AcceptedDesignError("design recovery input failed validation") from exc
        rows = conn.execute(
            """SELECT design_specification_id
               FROM design_specifications
               WHERE design_input_id = ?
               ORDER BY design_specification_id""",
            (design_input_id,),
        ).fetchall()
        candidates: list[DesignRecoveryCandidate] = []
        saw_audit = False
        saw_pass = False
        acceptance_ids: set[str] = set()
        for row in rows:
            try:
                specification = evidence._load_specification_conn(
                    conn, row["design_specification_id"]
                )
            except (DesignSpecificationEvidenceError, KeyError) as exc:
                raise AcceptedDesignError(
                    "durable recovery specification failed validation"
                ) from exc
            audit_row = conn.execute(
                """SELECT audit_id FROM design_specification_audits
                   WHERE design_specification_id = ?""",
                (specification.design_specification_id,),
            ).fetchone()
            audit = None
            if audit_row is not None:
                try:
                    audit = evidence._load_audit_conn(conn, audit_row["audit_id"])
                except (DesignSpecificationEvidenceError, KeyError) as exc:
                    raise AcceptedDesignError(
                        "durable recovery audit failed validation"
                    ) from exc
                saw_audit = True
                saw_pass = saw_pass or audit.status is DesignSpecificationAuditStatus.PASS
            acceptance_row = conn.execute(
                """SELECT acceptance_id
                   FROM design_specification_acceptances
                   WHERE design_specification_id = ?""",
                (specification.design_specification_id,),
            ).fetchone()
            acceptance_id = None
            if acceptance_row is not None:
                acceptance_id = acceptance_row["acceptance_id"]
                _load_exact_relation(
                    conn, acceptance_id=acceptance_id, evidence=evidence
                )
                acceptance_ids.add(acceptance_id)
            candidates.append(
                DesignRecoveryCandidate(
                    design_specification_id=specification.design_specification_id,
                    design_specification_hash=specification.content_hash,
                    audit_id=None if audit is None else audit.audit_id,
                    audit_hash=None if audit is None else audit.content_hash,
                    audit_status=None if audit is None else audit.status.value,
                    acceptance_id=acceptance_id,
                )
            )
        if len(acceptance_ids) > 1:
            raise AcceptedDesignError("design recovery acceptance state is ambiguous")
        if acceptance_ids:
            stage = DesignRecoveryStage.ACCEPTANCE_DURABLE
        elif saw_pass:
            stage = DesignRecoveryStage.PASS_AUDIT_DURABLE
        elif saw_audit:
            stage = DesignRecoveryStage.AUDIT_DURABLE
        elif candidates:
            stage = DesignRecoveryStage.SPECIFICATION_DURABLE
        else:
            stage = DesignRecoveryStage.INPUT_ONLY
        acceptance_id = next(iter(acceptance_ids), None)
        return DesignRecoveryInspection(
            design_input_id=design_input.design_input_id,
            design_input_hash=design_input.content_hash,
            stage=stage,
            candidates=tuple(candidates),
            acceptance_id=acceptance_id,
        )


def _planning_verified_refs(
    evidence: DesignSpecificationEvidenceStore,
    design_input: DesignSpecificationInput,
    acceptance: DesignSpecificationAcceptance,
) -> tuple[PlanningEvidenceRef, ...]:
    """Compress DESIGNIN transport evidence into Phase-31 authority evidence.

    DESIGNIN may contain 126 semantic verification refs plus CAPCAT/CAPPOL, filling
    all 128 PlanningInput slots. Those semantic refs are independently revalidated
    before bridging and remain transitively bound by DESIGNACC -> DESIGNIN. The new
    PlanningInput therefore carries only DESIGNACC plus the established Phase-32
    CAPCAT/CAPPOL evidence refs.
    """
    try:
        catalog_ref, policy_ref, _ = evidence._governed_capability_refs(design_input)
    except DesignSpecificationEvidenceError as exc:
        raise AcceptedDesignError("design input capability evidence is invalid") from exc
    refs = (
        PlanningEvidenceRef(acceptance.acceptance_id, acceptance.content_hash),
        catalog_ref,
        policy_ref,
    )
    return tuple(sorted(refs, key=lambda value: value.key))


def _expected_planning_fields(
    evidence: DesignSpecificationEvidenceStore,
    inspection: AcceptedDesignInspection,
) -> dict[str, object]:
    design_input = inspection.design_input
    return {
        "project_id": design_input.project_id,
        "goal_id": design_input.goal_id,
        "goal_revision": design_input.goal_revision,
        "goal_content_hash": design_input.goal_content_hash,
        "verified_state_refs": _planning_verified_refs(
            evidence, design_input, inspection.acceptance
        ),
        "active_design_rule_refs": design_input.active_design_rule_refs,
        "project_intelligence_hash": design_input.project_intelligence_hash,
        "capability_catalog_hash": design_input.capability_catalog_hash,
        "capability_ids": design_input.capability_ids,
        # Phase 31 has no persistent global model/resource policy registry. These
        # hashes are therefore derived from the accepted DESIGNIN and never from
        # caller-supplied replacements; later Planner admission remains separate.
        "model_policy_hash": design_input.model_policy_hash,
        "resource_policy_hash": design_input.resource_policy_hash,
    }


def _matches_expected_planning_input(
    value: PlanningInput,
    expected: dict[str, object],
) -> bool:
    return all(
        getattr(value, field) == expected_value
        for field, expected_value in expected.items()
    )


def bridge_accepted_design_to_planning_input(
    runtime: OriginForgeRuntime,
    acceptance_id: str,
) -> PlanningInput:
    """Publish or recover exactly one accepted-design PlanningInput; never run Planner."""
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    inspection = inspect_accepted_design(runtime, acceptance_id)
    if not inspection.current:
        raise AcceptedDesignError(
            f"accepted design is stale: {inspection.stale_reason}"
        )

    evidence = DesignSpecificationEvidenceStore(runtime)
    capability_store = ProductionCapabilityStore(runtime)
    planning_store = ProductionPlanningEvidenceStore(runtime)
    expected = _expected_planning_fields(evidence, inspection)

    try:
        evidence._assert_capability_binding(inspection.design_input, capability_store)
    except DesignSpecificationEvidenceError as exc:
        raise AcceptedDesignError(
            "accepted design capability binding failed bridge revalidation"
        ) from exc

    with runtime.store.session() as conn:
        # Reload everything under the authoritative write transaction so restart
        # recovery cannot turn a stale read-only snapshot into a new PLINPUT.
        acceptance, design_input, specification, audit = _load_exact_relation(
            conn,
            acceptance_id=acceptance_id,
            evidence=evidence,
        )
        if (
            acceptance.content_hash != inspection.acceptance.content_hash
            or design_input.content_hash != inspection.design_input.content_hash
            or specification.content_hash != inspection.specification.content_hash
            or audit.content_hash != inspection.audit.content_hash
        ):
            raise AcceptedDesignError("accepted design changed during bridge")
        try:
            evidence._assert_semantic_binding_conn(conn, design_input)
        except DesignSpecificationEvidenceError as exc:
            raise AcceptedDesignError(
                "accepted design became stale before PlanningInput publication"
            ) from exc
        try:
            evidence._assert_capability_binding(design_input, capability_store)
        except DesignSpecificationEvidenceError as exc:
            raise AcceptedDesignError(
                "accepted design capability binding drifted before publication"
            ) from exc

        existing_rows = conn.execute(
            """SELECT planning_input_id
               FROM planning_inputs
               WHERE project_id = ? AND goal_id = ?
               ORDER BY planning_input_id""",
            (design_input.project_id, design_input.goal_id),
        ).fetchall()
        matching: list[PlanningInput] = []
        for row in existing_rows:
            try:
                value = planning_store._load_input_conn(
                    conn, row["planning_input_id"]
                )
            except (ProductionPlanningEvidenceError, KeyError) as exc:
                raise AcceptedDesignError(
                    "existing PlanningInput failed validation during bridge recovery"
                ) from exc
            acceptance_refs = tuple(
                ref
                for ref in value.verified_state_refs
                if ref.ref_id == acceptance.acceptance_id
            )
            if not acceptance_refs:
                continue
            if (
                len(acceptance_refs) != 1
                or acceptance_refs[0].content_hash != acceptance.content_hash
            ):
                raise AcceptedDesignError(
                    "existing accepted-design PlanningInput has forged DESIGNACC evidence"
                )
            if not _matches_expected_planning_input(value, expected):
                raise AcceptedDesignError(
                    "existing accepted-design PlanningInput binding drifted"
                )
            matching.append(value)
        if len(matching) > 1:
            raise AcceptedDesignError(
                "accepted-design PlanningInput recovery is ambiguous"
            )
        if matching:
            return matching[0]

        value = PlanningInput.create(**expected)
        try:
            planning_store._insert_evidence(
                conn,
                "planning_inputs",
                "planning_input_id",
                value.planning_input_id,
                value.content_hash,
                value.to_dict(),
                ("project_id", "goal_id", "goal_revision"),
                (value.project_id, value.goal_id, value.goal_revision),
            )
        except (ProductionPlanningEvidenceError, sqlite3.IntegrityError) as exc:
            raise AcceptedDesignError(
                "accepted-design PlanningInput publication failed"
            ) from exc
        return value
