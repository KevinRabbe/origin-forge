from __future__ import annotations

from typing import Iterable

from .production_capability_store import (
    ProductionCapabilityStore,
    ProductionCapabilityStoreError,
)
from .production_planning_evidence import freeze_planning_input
from .production_planning_models import PlanningEvidenceRef, PlanningInput
from .runtime import OriginForgeRuntime


class GovernedPlanningCapabilityError(RuntimeError):
    pass


def freeze_governed_planning_input(
    runtime: OriginForgeRuntime,
    goal_id: str,
    *,
    capability_store: ProductionCapabilityStore,
    catalog_id: str,
    routing_policy_id: str,
    verified_state_refs: Iterable[PlanningEvidenceRef] = (),
    active_design_rule_refs: Iterable[PlanningEvidenceRef] = (),
    project_intelligence_hash: str,
    model_policy_hash: str,
    resource_policy_hash: str,
) -> PlanningInput:
    """Freeze Phase-31 planning input from persisted Phase-32 capability authority.

    The caller chooses which already-persisted catalog/policy pair to use, but it
    cannot supply the catalog hash or capability IDs. Those values are derived
    from the exact validated objects, and their identities/hashes are added to
    the frozen evidence references.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(capability_store, ProductionCapabilityStore):
        raise TypeError("capability_store must be a ProductionCapabilityStore")
    if capability_store.runtime.project_root != runtime.project_root:
        raise GovernedPlanningCapabilityError(
            "capability authority belongs to a different project root"
        )

    try:
        catalog = capability_store.load_catalog(catalog_id)
        policy = capability_store.load_policy(routing_policy_id)
    except ProductionCapabilityStoreError as exc:
        raise GovernedPlanningCapabilityError(
            "capability authority could not be loaded and validated"
        ) from exc
    if policy.catalog_id != catalog.catalog_id or policy.catalog_hash != catalog.content_hash:
        raise GovernedPlanningCapabilityError("routing policy/catalog binding drifted")

    refs = tuple(verified_state_refs)
    reserved = {catalog.catalog_id, policy.routing_policy_id}
    if any(ref.ref_id in reserved for ref in refs):
        raise GovernedPlanningCapabilityError(
            "caller may not pre-bind governed catalog/policy evidence refs"
        )
    governed_refs = (
        *refs,
        PlanningEvidenceRef(catalog.catalog_id, catalog.content_hash),
        PlanningEvidenceRef(policy.routing_policy_id, policy.content_hash),
    )

    return freeze_planning_input(
        runtime,
        goal_id,
        verified_state_refs=governed_refs,
        active_design_rule_refs=active_design_rule_refs,
        project_intelligence_hash=project_intelligence_hash,
        capability_catalog_hash=catalog.content_hash,
        capability_ids=policy.allowed_capability_ids,
        model_policy_hash=model_policy_hash,
        resource_policy_hash=resource_policy_hash,
    )
