from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from .ids import IdKind, validate_id
from .production_goal_bootstrap_authority import prepare_goal_bootstrap_input
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from .production_goal_bootstrap_store import (
    GoalBootstrapStoreError,
    _load_receipt_connection,
    _require_active_checkpoint,
    _require_goal_current,
    checkpoint_goal_bootstrap_materialized,
    checkpoint_goal_bootstrap_preppol_published,
    interrupt_goal_bootstrap,
    read_goal_bootstrap_receipt,
)
from .production_planning_evidence import (
    PlanMaterialization,
    ProductionPlanningEvidenceError,
    ProductionPlanningEvidenceStore,
)
from .production_planning_inspection import inspect_plan_materialization
from .production_planning_models import (
    PlanAudit,
    PlanAuditStatus,
    PlanProposal,
    PlanningInput,
    audit_plan,
)
from .production_preparation_models import TaskPreparationPolicyBinding
from . import production_preparation_policy_store as _preppol_store
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    create_preparation_policy_binding,
    read_preparation_policy,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


_MAX_PLAN_AUDITS = 10_000
_MAX_PREPARATION_POLICIES = 10_000
_FINALIZE_STAGES = (
    GoalBootstrapStage.PLANNER_RETURNED,
    GoalBootstrapStage.PLAN_AUDITED,
    GoalBootstrapStage.MATERIALIZED,
)


class GoalBootstrapFinalizeError(RuntimeError):
    pass


class GoalBootstrapFinalizeInterrupted(GoalBootstrapFinalizeError):
    pass


class GoalBootstrapFinalizeStatus(StrEnum):
    READY = "READY"
    ALREADY_READY = "ALREADY_READY"


@dataclass(frozen=True)
class GoalBootstrapFinalizeResult:
    status: GoalBootstrapFinalizeStatus
    receipt: GoalBootstrapReceipt
    plan_audit: PlanAudit
    materialization: PlanMaterialization
    preparation_policy: TaskPreparationPolicyBinding
    reused_audit: bool
    reused_materialization: bool
    reused_preparation_policy: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "receipt": self.receipt.to_dict(),
            "plan_audit": self.plan_audit.to_dict(),
            "materialization": self.materialization.to_dict(),
            "preparation_policy": self.preparation_policy.to_dict(),
            "reused_audit": self.reused_audit,
            "reused_materialization": self.reused_materialization,
            "reused_preparation_policy": self.reused_preparation_policy,
            "authority": "phase45d-goal-bootstrap-finalization",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _semantic_dict(value: object, id_field: str) -> dict[str, object]:
    payload = dict(value.to_dict())
    payload.pop(id_field)
    return payload


def _required(value: str | None, label: str) -> str:
    if value is None:
        raise GoalBootstrapFinalizeError(f"GOALBOOT lacks {label}")
    return value


def _checkpoint_locked(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    bootstrap_id: str,
    expected_revision: int,
    expected_stage: GoalBootstrapStage,
    target_stage: GoalBootstrapStage,
    updates: dict[str, object],
    target_status: GoalBootstrapStatus = GoalBootstrapStatus.ACTIVE,
) -> GoalBootstrapReceipt:
    receipt = _load_receipt_connection(conn, bootstrap_id)
    if receipt.project_id != project_id:
        raise GoalBootstrapStoreError("GOALBOOT receipt belongs to another project")
    _require_active_checkpoint(
        receipt,
        expected_stage=expected_stage,
        expected_revision=expected_revision,
    )
    _require_goal_current(conn, receipt)
    now = utc_now()
    candidate = replace(
        receipt,
        **updates,
        stage=target_stage,
        status=target_status,
        revision=receipt.revision + 1,
        updated_at=now,
    )
    set_values = dict(updates)
    set_values.update(
        {
            "stage": target_stage.value,
            "status": target_status.value,
            "new_revision": candidate.revision,
            "updated_at": now,
            "bootstrap_id": receipt.bootstrap_id,
            "expected_stage": expected_stage.value,
            "expected_revision": receipt.revision,
        }
    )
    set_clause = ", ".join(f"{column} = :{column}" for column in updates)
    if set_clause:
        set_clause += ", "
    cursor = conn.execute(
        f"""UPDATE goal_bootstraps
            SET {set_clause}stage = :stage, status = :status,
                revision = :new_revision, updated_at = :updated_at
            WHERE bootstrap_id = :bootstrap_id AND status = 'ACTIVE'
              AND stage = :expected_stage AND revision = :expected_revision""",
        set_values,
    )
    if cursor.rowcount != 1:
        raise StaleRevision("GOALBOOT changed during locked checkpoint")
    return _load_receipt_connection(conn, bootstrap_id)


def _load_exact_planner_chain_connection(
    evidence_store: ProductionPlanningEvidenceStore,
    conn: sqlite3.Connection,
    receipt: GoalBootstrapReceipt,
) -> tuple[PlanningInput, PlanProposal]:
    planning_input_id = _required(receipt.planning_input_id, "PlanningInput ID")
    planning_input_hash = _required(receipt.planning_input_hash, "PlanningInput hash")
    proposal_id = _required(receipt.plan_proposal_id, "PlanProposal ID")
    proposal_hash = _required(receipt.plan_proposal_hash, "PlanProposal hash")
    planning_input = evidence_store._load_input_conn(conn, planning_input_id)
    proposal = evidence_store._load_proposal_conn(conn, proposal_id)
    if (
        planning_input.content_hash != planning_input_hash
        or planning_input.project_id != receipt.project_id
        or planning_input.goal_id != receipt.goal_id
        or planning_input.goal_revision != receipt.goal_revision
        or planning_input.goal_content_hash != receipt.goal_content_hash
        or proposal.content_hash != proposal_hash
        or proposal.planning_input_id != planning_input.planning_input_id
        or proposal.planning_input_hash != planning_input.content_hash
    ):
        raise GoalBootstrapFinalizeError(
            "Planner-return evidence drifted from exact GOALBOOT authority"
        )
    return planning_input, proposal


def _audit_and_checkpoint(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> tuple[GoalBootstrapReceipt, PlanAudit, bool]:
    project_id = runtime.project_id()
    evidence_store = ProductionPlanningEvidenceStore(runtime)
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _load_receipt_connection(conn, receipt.bootstrap_id)
        _require_active_checkpoint(
            current,
            expected_stage=GoalBootstrapStage.PLANNER_RETURNED,
            expected_revision=receipt.revision,
        )
        planning_input, proposal = _load_exact_planner_chain_connection(
            evidence_store,
            conn,
            current,
        )
        expected = audit_plan(planning_input, proposal)
        expected_semantic = _semantic_dict(expected, "audit_id")
        rows = conn.execute(
            """SELECT audit_id FROM plan_audits
               WHERE proposal_id = ? ORDER BY audit_id LIMIT ?""",
            (proposal.proposal_id, _MAX_PLAN_AUDITS + 1),
        ).fetchall()
        if len(rows) > _MAX_PLAN_AUDITS:
            raise GoalBootstrapFinalizeError("PlanAudit recovery scan limit exceeded")
        existing: list[PlanAudit] = []
        for row in rows:
            audit = evidence_store._load_audit_conn(conn, row["audit_id"])
            if (
                audit.planning_input_id != planning_input.planning_input_id
                or audit.planning_input_hash != planning_input.content_hash
                or audit.proposal_id != proposal.proposal_id
                or audit.proposal_hash != proposal.content_hash
            ):
                raise GoalBootstrapFinalizeError(
                    "existing PlanAudit relation conflicts with exact Planner return"
                )
            if _semantic_dict(audit, "audit_id") != expected_semantic:
                raise GoalBootstrapFinalizeError(
                    "multiple PlanAudit semantics exist for exact Planner return"
                )
            existing.append(audit)
        if existing:
            audit = min(existing, key=lambda value: value.audit_id)
            reused = True
        else:
            audit = expected
            evidence_store._insert_evidence(
                conn,
                "plan_audits",
                "audit_id",
                audit.audit_id,
                audit.content_hash,
                audit.to_dict(),
                ("planning_input_id", "proposal_id", "status"),
                (audit.planning_input_id, audit.proposal_id, audit.status.value),
            )
            audit = evidence_store._load_audit_conn(conn, audit.audit_id)
            reused = False
        updated = _checkpoint_locked(
            conn,
            project_id=project_id,
            bootstrap_id=current.bootstrap_id,
            expected_revision=current.revision,
            expected_stage=GoalBootstrapStage.PLANNER_RETURNED,
            target_stage=GoalBootstrapStage.PLAN_AUDITED,
            updates={
                "plan_audit_id": audit.audit_id,
                "plan_audit_hash": audit.content_hash,
            },
        )
        return updated, audit, reused


def _load_exact_audit(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> PlanAudit:
    audit_id = _required(receipt.plan_audit_id, "PlanAudit ID")
    audit_hash = _required(receipt.plan_audit_hash, "PlanAudit hash")
    evidence_store = ProductionPlanningEvidenceStore(runtime)
    audit = evidence_store.load_audit(audit_id)
    proposal_id = _required(receipt.plan_proposal_id, "PlanProposal ID")
    proposal_hash = _required(receipt.plan_proposal_hash, "PlanProposal hash")
    if (
        audit.content_hash != audit_hash
        or audit.planning_input_id != receipt.planning_input_id
        or audit.planning_input_hash != receipt.planning_input_hash
        or audit.proposal_id != proposal_id
        or audit.proposal_hash != proposal_hash
    ):
        raise GoalBootstrapFinalizeError("PlanAudit drifted from GOALBOOT checkpoint")
    return audit


def _existing_materialization(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> PlanMaterialization | None:
    proposal_id = _required(receipt.plan_proposal_id, "PlanProposal ID")
    with runtime.store.session() as conn:
        rows = conn.execute(
            """SELECT materialization_id FROM plan_materializations
               WHERE proposal_id = ? ORDER BY materialization_id LIMIT 2""",
            (proposal_id,),
        ).fetchall()
    if len(rows) > 1:
        raise GoalBootstrapFinalizeError(
            "multiple materializations exist for one exact PlanProposal"
        )
    if not rows:
        return None
    materialization = inspect_plan_materialization(runtime, rows[0]["materialization_id"])
    if (
        materialization.planning_input_id != receipt.planning_input_id
        or materialization.planning_input_hash != receipt.planning_input_hash
        or materialization.proposal_id != receipt.plan_proposal_id
        or materialization.proposal_hash != receipt.plan_proposal_hash
        or materialization.audit_id != receipt.plan_audit_id
        or materialization.audit_hash != receipt.plan_audit_hash
        or materialization.goal_id != receipt.goal_id
        or materialization.goal_revision != receipt.goal_revision
    ):
        raise GoalBootstrapFinalizeError(
            "existing PlanMaterialization does not exactly continue GOALBOOT audit authority"
        )
    return materialization


def _materialize_and_checkpoint(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> tuple[GoalBootstrapReceipt, PlanMaterialization, bool]:
    audit = _load_exact_audit(runtime, receipt)
    if audit.status is not PlanAuditStatus.PASS:
        raise GoalBootstrapFinalizeError("structural PlanAudit is not PASS")
    existing = _existing_materialization(runtime, receipt)
    if existing is not None:
        materialization = existing
        reused = True
    else:
        evidence_store = ProductionPlanningEvidenceStore(runtime)
        try:
            materialization = evidence_store.materialize(
                planning_input_id=_required(receipt.planning_input_id, "PlanningInput ID"),
                proposal_id=_required(receipt.plan_proposal_id, "PlanProposal ID"),
                audit_id=audit.audit_id,
            )
            reused = False
        except ProductionPlanningEvidenceError:
            materialization = _existing_materialization(runtime, receipt)
            if materialization is None:
                raise
            reused = True
    persisted = inspect_plan_materialization(runtime, materialization.materialization_id)
    if persisted != materialization:
        raise GoalBootstrapFinalizeError("PlanMaterialization failed exact reload")
    updated = checkpoint_goal_bootstrap_materialized(
        runtime,
        receipt.bootstrap_id,
        receipt.revision,
        materialization_id=materialization.materialization_id,
        materialization_hash=materialization.content_hash,
    )
    return updated, materialization, reused


def _policy_root(runtime: OriginForgeRuntime) -> Path:
    return runtime.state_dir / "production-preparation" / "policies"


def _read_policy_without_provenance(
    runtime: OriginForgeRuntime,
    preparation_policy_id: str,
) -> TaskPreparationPolicyBinding:
    path = _preppol_store._policy_path(
        runtime,
        preparation_policy_id,
        require_file=True,
        create_root=False,
    )
    try:
        size = path.stat().st_size
        if size <= 0 or size > _preppol_store._MAX_POLICY_BYTES:
            raise ProductionPreparationPolicyStoreError(
                "stored PREPPOL byte size is outside bounds"
            )
        raw = path.read_bytes()
        envelope = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_preppol_store._strict_object,
        )
    except ProductionPreparationPolicyStoreError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionPreparationPolicyStoreError(
            "stored PREPPOL is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "object_type",
        "object_id",
        "content_hash",
        "payload",
    }:
        raise ProductionPreparationPolicyStoreError("PREPPOL envelope schema drifted")
    if (
        envelope["schema_version"] != _preppol_store._SCHEMA_VERSION
        or envelope["object_type"] != "preparation-policy"
        or envelope["object_id"] != preparation_policy_id
        or not isinstance(envelope["payload"], dict)
        or _preppol_store._canonical_bytes(envelope) != raw
    ):
        raise ProductionPreparationPolicyStoreError("PREPPOL envelope binding drifted")
    policy = _preppol_store._policy_from_dict(envelope["payload"])
    if (
        policy.preparation_policy_id != preparation_policy_id
        or policy.content_hash != envelope["content_hash"]
    ):
        raise ProductionPreparationPolicyStoreError("PREPPOL content hash drifted")
    return policy


def _matching_policies_without_provenance(
    runtime: OriginForgeRuntime,
    expected: TaskPreparationPolicyBinding,
) -> tuple[TaskPreparationPolicyBinding, ...]:
    root = _policy_root(runtime)
    parent = root.parent
    if parent.is_symlink() or root.is_symlink():
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL recovery path may not be a symlink"
        )
    if parent.exists() and not parent.is_dir():
        raise ProductionPreparationPolicyStoreError(
            "PREPPOL recovery parent is not a directory"
        )
    if not root.exists():
        return ()
    root = _preppol_store._root(runtime, create=False)
    paths = tuple(root.iterdir())
    if len(paths) > _MAX_PREPARATION_POLICIES:
        raise GoalBootstrapFinalizeError("PREPPOL recovery scan limit exceeded")
    expected_semantic = _semantic_dict(expected, "preparation_policy_id")
    matches: list[TaskPreparationPolicyBinding] = []
    for path in sorted(paths, key=lambda value: value.name):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL recovery contains an undeclared or aliased entry"
            )
        policy_id = path.stem
        if (
            path.name != f"{policy_id}.json"
            or not validate_id(policy_id, IdKind.TASK_PREPARATION_POLICY)
            or path.resolve(strict=True) != path
        ):
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL recovery contains invalid evidence"
            )
        policy = _read_policy_without_provenance(runtime, policy_id)
        if policy.materialization_id != expected.materialization_id:
            continue
        if _semantic_dict(policy, "preparation_policy_id") != expected_semantic:
            raise GoalBootstrapFinalizeError(
                "multiple PREPPOL semantics exist for exact materialization"
            )
        matches.append(policy)
    return tuple(matches)


def _publish_policy_without_provenance(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
) -> TaskPreparationPolicyBinding:
    root = _preppol_store._root(runtime, create=True)
    if len(tuple(root.glob("PREPPOL-*.json"))) >= _MAX_PREPARATION_POLICIES:
        raise ProductionPreparationPolicyStoreError("PREPPOL object-count limit reached")
    path = _preppol_store._policy_path(
        runtime,
        policy.preparation_policy_id,
        require_file=False,
        create_root=True,
    )
    if path.exists() or path.is_symlink():
        raise ProductionPreparationPolicyStoreError("PREPPOL already exists")
    envelope = {
        "schema_version": _preppol_store._SCHEMA_VERSION,
        "object_type": "preparation-policy",
        "object_id": policy.preparation_policy_id,
        "content_hash": policy.content_hash,
        "payload": policy.to_dict(),
    }
    data = _preppol_store._canonical_bytes(envelope)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProductionPreparationPolicyStoreError("PREPPOL already exists") from exc
    return _read_policy_without_provenance(runtime, policy.preparation_policy_id)


def _preppol_and_checkpoint(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> tuple[GoalBootstrapReceipt, TaskPreparationPolicyBinding, bool]:
    project_id = runtime.project_id()
    materialization_id = _required(receipt.materialization_id, "PlanMaterialization ID")
    materialization_hash = _required(receipt.materialization_hash, "PlanMaterialization hash")
    materialization = inspect_plan_materialization(runtime, materialization_id)
    if materialization.content_hash != materialization_hash:
        raise GoalBootstrapFinalizeError("PlanMaterialization hash drifted before PREPPOL")
    expected = create_preparation_policy_binding(
        runtime,
        materialization_id=materialization.materialization_id,
        capability_catalog_id=_required(receipt.capability_catalog_id, "CAPCAT ID"),
        capability_routing_policy_id=_required(
            receipt.capability_routing_policy_id,
            "CAPPOL ID",
        ),
        dispatch_contract_catalog_id=_required(
            receipt.dispatch_contract_catalog_id,
            "DISPCAT ID",
        ),
    )

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _load_receipt_connection(conn, receipt.bootstrap_id)
        if current.project_id != project_id:
            raise GoalBootstrapStoreError("GOALBOOT receipt belongs to another project")
        _require_active_checkpoint(
            current,
            expected_stage=GoalBootstrapStage.MATERIALIZED,
            expected_revision=receipt.revision,
        )
        _require_goal_current(conn, current)
        if (
            current.materialization_id != materialization.materialization_id
            or current.materialization_hash != materialization.content_hash
            or current.capability_catalog_id != expected.capability_catalog_id
            or current.capability_catalog_hash != expected.capability_catalog_hash
            or current.capability_routing_policy_id != expected.capability_routing_policy_id
            or current.capability_routing_policy_hash != expected.capability_routing_policy_hash
            or current.dispatch_contract_catalog_id != expected.dispatch_contract_catalog_id
            or current.dispatch_contract_catalog_hash != expected.dispatch_contract_catalog_hash
        ):
            raise GoalBootstrapFinalizeError(
                "locked GOALBOOT PREPPOL authority drifted"
            )
        existing = _matching_policies_without_provenance(runtime, expected)
        if existing:
            selected = min(existing, key=lambda value: value.preparation_policy_id)
            reused = True
        else:
            selected = _publish_policy_without_provenance(runtime, expected)
            reused = False

    policy = read_preparation_policy(runtime, selected.preparation_policy_id)
    if _semantic_dict(policy, "preparation_policy_id") != _semantic_dict(
        expected,
        "preparation_policy_id",
    ):
        raise GoalBootstrapFinalizeError(
            "persisted PREPPOL drifted from code-owned expected policy"
        )
    updated = checkpoint_goal_bootstrap_preppol_published(
        runtime,
        receipt.bootstrap_id,
        receipt.revision,
        preparation_policy_id=policy.preparation_policy_id,
        preparation_policy_hash=policy.content_hash,
    )
    return updated, policy, reused


def _validate_ready(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> tuple[PlanAudit, PlanMaterialization, TaskPreparationPolicyBinding]:
    if (
        receipt.status is not GoalBootstrapStatus.READY
        or receipt.stage is not GoalBootstrapStage.PREPPOL_PUBLISHED
    ):
        raise GoalBootstrapFinalizeError("GOALBOOT is not at READY PREPPOL checkpoint")
    with runtime.store.session() as conn:
        _require_goal_current(conn, receipt)
        evidence_store = ProductionPlanningEvidenceStore(runtime)
        planning_input, proposal = _load_exact_planner_chain_connection(
            evidence_store,
            conn,
            receipt,
        )
        del planning_input, proposal
    audit = _load_exact_audit(runtime, receipt)
    if audit.status is not PlanAuditStatus.PASS:
        raise GoalBootstrapFinalizeError("READY GOALBOOT does not bind a PASS PlanAudit")
    materialization_id = _required(receipt.materialization_id, "PlanMaterialization ID")
    materialization = inspect_plan_materialization(runtime, materialization_id)
    if (
        materialization.content_hash != receipt.materialization_hash
        or materialization.audit_id != audit.audit_id
        or materialization.audit_hash != audit.content_hash
        or materialization.proposal_id != receipt.plan_proposal_id
        or materialization.proposal_hash != receipt.plan_proposal_hash
    ):
        raise GoalBootstrapFinalizeError("READY PlanMaterialization drifted")
    policy_id = _required(receipt.preparation_policy_id, "PREPPOL ID")
    policy = read_preparation_policy(runtime, policy_id)
    if (
        policy.content_hash != receipt.preparation_policy_hash
        or policy.materialization_id != materialization.materialization_id
        or policy.materialization_hash != materialization.content_hash
        or policy.planning_input_id != receipt.planning_input_id
        or policy.planning_input_hash != receipt.planning_input_hash
        or policy.capability_catalog_id != receipt.capability_catalog_id
        or policy.capability_catalog_hash != receipt.capability_catalog_hash
        or policy.capability_routing_policy_id != receipt.capability_routing_policy_id
        or policy.capability_routing_policy_hash != receipt.capability_routing_policy_hash
        or policy.dispatch_contract_catalog_id != receipt.dispatch_contract_catalog_id
        or policy.dispatch_contract_catalog_hash != receipt.dispatch_contract_catalog_hash
    ):
        raise GoalBootstrapFinalizeError("READY PREPPOL drifted from GOALBOOT authority")
    expected = create_preparation_policy_binding(
        runtime,
        materialization_id=materialization.materialization_id,
        capability_catalog_id=_required(receipt.capability_catalog_id, "CAPCAT ID"),
        capability_routing_policy_id=_required(
            receipt.capability_routing_policy_id,
            "CAPPOL ID",
        ),
        dispatch_contract_catalog_id=_required(receipt.dispatch_contract_catalog_id, "DISPCAT ID"),
    )
    if _semantic_dict(policy, "preparation_policy_id") != _semantic_dict(
        expected,
        "preparation_policy_id",
    ):
        raise GoalBootstrapFinalizeError(
            "READY PREPPOL no longer matches code-owned preparation authority"
        )
    return audit, materialization, policy


def _interrupt_if_unchanged(
    runtime: OriginForgeRuntime,
    original: GoalBootstrapReceipt,
    exc: Exception,
) -> GoalBootstrapReceipt | None:
    current = read_goal_bootstrap_receipt(runtime, original.bootstrap_id)
    if (
        current.status is not GoalBootstrapStatus.ACTIVE
        or current.stage != original.stage
        or current.revision != original.revision
        or current.stage not in _FINALIZE_STAGES
    ):
        return None
    try:
        return interrupt_goal_bootstrap(
            runtime,
            current.bootstrap_id,
            current.revision,
            current.stage,
            f"Phase-45D finalization failed closed: {_detail(exc)}",
        )
    except StaleRevision:
        return None


def _result(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    *,
    status: GoalBootstrapFinalizeStatus,
    reused_audit: bool,
    reused_materialization: bool,
    reused_policy: bool,
) -> GoalBootstrapFinalizeResult:
    audit, materialization, policy = _validate_ready(runtime, receipt)
    return GoalBootstrapFinalizeResult(
        status,
        receipt,
        audit,
        materialization,
        policy,
        reused_audit,
        reused_materialization,
        reused_policy,
    )


def finalize_goal_bootstrap(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
) -> GoalBootstrapFinalizeResult:
    """Finalize one exact PLANNER_RETURNED GOALBOOT through PREPPOL READY.

    This is Phase-45D authority only. It independently structural-audits the
    untrusted PlanProposal, materializes the exact passing plan, publishes the
    existing Phase-39 PREPPOL, and then stops. It has no Manager advancement,
    dispatch, model-call, task-activation, retry-loop, CLI, or API authority.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    initial = read_goal_bootstrap_receipt(runtime, bootstrap_id)
    if initial.status is GoalBootstrapStatus.READY:
        return _result(
            runtime,
            initial,
            status=GoalBootstrapFinalizeStatus.ALREADY_READY,
            reused_audit=False,
            reused_materialization=False,
            reused_policy=False,
        )
    reused_audit = False
    reused_materialization = False
    reused_policy = False

    for _ in range(8):
        receipt = read_goal_bootstrap_receipt(runtime, bootstrap_id)
        if receipt.status is GoalBootstrapStatus.READY:
            return _result(
                runtime,
                receipt,
                status=GoalBootstrapFinalizeStatus.READY,
                reused_audit=reused_audit,
                reused_materialization=reused_materialization,
                reused_policy=reused_policy,
            )
        if receipt.status is not GoalBootstrapStatus.ACTIVE:
            raise GoalBootstrapFinalizeError(
                f"GOALBOOT is terminal with status {receipt.status.value}"
            )
        if receipt.stage not in _FINALIZE_STAGES:
            raise GoalBootstrapFinalizeError(
                f"GOALBOOT cannot Phase-45D finalize from stage {receipt.stage.value}"
            )
        try:
            prepared, _ = prepare_goal_bootstrap_input(runtime, bootstrap_id)
            if prepared != receipt:
                receipt = prepared
            if receipt.stage is GoalBootstrapStage.PLANNER_RETURNED:
                updated, audit, reused = _audit_and_checkpoint(runtime, receipt)
                reused_audit = reused_audit or reused
                if audit.status is not PlanAuditStatus.PASS:
                    interrupted = interrupt_goal_bootstrap(
                        runtime,
                        updated.bootstrap_id,
                        updated.revision,
                        GoalBootstrapStage.PLAN_AUDITED,
                        "Phase-45D structural PlanAudit did not PASS",
                    )
                    raise GoalBootstrapFinalizeInterrupted(
                        interrupted.terminal_reason or "structural PlanAudit failed"
                    )
                continue
            if receipt.stage is GoalBootstrapStage.PLAN_AUDITED:
                _, _, reused = _materialize_and_checkpoint(runtime, receipt)
                reused_materialization = reused_materialization or reused
                continue
            if receipt.stage is GoalBootstrapStage.MATERIALIZED:
                _, _, reused = _preppol_and_checkpoint(runtime, receipt)
                reused_policy = reused_policy or reused
                continue
        except StaleRevision as exc:
            current = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
            if (
                current.status is GoalBootstrapStatus.ACTIVE
                and current.stage == receipt.stage
                and current.revision == receipt.revision
            ):
                interrupted = _interrupt_if_unchanged(runtime, receipt, exc)
                if interrupted is not None:
                    raise GoalBootstrapFinalizeInterrupted(
                        interrupted.terminal_reason or "Phase-45D authority became stale"
                    ) from exc
            continue
        except GoalBootstrapFinalizeInterrupted:
            raise
        except Exception as exc:
            interrupted = _interrupt_if_unchanged(runtime, receipt, exc)
            if interrupted is None:
                continue
            raise GoalBootstrapFinalizeInterrupted(
                interrupted.terminal_reason or "Phase-45D finalization interrupted"
            ) from exc

    raise GoalBootstrapFinalizeError(
        "GOALBOOT changed too many times while advancing Phase-45D finalization"
    )
