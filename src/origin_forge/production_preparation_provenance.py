from __future__ import annotations

from dataclasses import dataclass

from .production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from .production_capability_read import (
    ProductionCapabilityReadError,
    read_capability_catalog,
    read_capability_policy,
)
from .production_planning_evidence import PlanMaterialization
from .production_planning_inspection import (
    ProductionPlanningInspectionError,
    inspect_plan_materialization,
    inspect_planning_input,
)
from .production_planning_models import PlanningInput
from .production_preparation_models import TaskPreparationPolicyBinding
from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_models import DispatchContractCatalog
from .production_work_order_read import (
    ProductionWorkOrderReadError,
    read_dispatch_catalog,
)
from .runtime import OriginForgeRuntime


class ProductionPreparationProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparationPolicyProvenance:
    """Exact non-owner evidence recovered for one Phase-39 preparation policy.

    Phase 39B deliberately does not certify the preparation owner. The code-owned
    owner descriptor and its currentness check are introduced in Phase 39C. This
    value therefore proves only the frozen PLMAT/PLINPUT/CAPCAT/CAPPOL/DISPCAT
    relation and must not itself be treated as executable preparation authority.
    """

    policy: TaskPreparationPolicyBinding
    materialization: PlanMaterialization
    planning_input: PlanningInput
    capability_catalog: CapabilityCatalog
    capability_routing_policy: CapabilityRoutingPolicy
    dispatch_contract_catalog: DispatchContractCatalog

    def to_dict(self) -> dict[str, object]:
        return {
            "preparation_policy_id": self.policy.preparation_policy_id,
            "preparation_policy_hash": self.policy.content_hash,
            "materialization_id": self.materialization.materialization_id,
            "materialization_hash": self.materialization.content_hash,
            "planning_input_id": self.planning_input.planning_input_id,
            "planning_input_hash": self.planning_input.content_hash,
            "capability_catalog_id": self.capability_catalog.catalog_id,
            "capability_catalog_hash": self.capability_catalog.content_hash,
            "capability_routing_policy_id": self.capability_routing_policy.routing_policy_id,
            "capability_routing_policy_hash": self.capability_routing_policy.content_hash,
            "dispatch_contract_catalog_id": self.dispatch_contract_catalog.dispatch_catalog_id,
            "dispatch_contract_catalog_hash": self.dispatch_contract_catalog.content_hash,
            "owner_currentness": "DEFERRED_TO_PHASE_39C",
            "authority": "read-only provenance",
        }


def _require_exact_planning_ref(
    planning_input: PlanningInput,
    *,
    ref_id: str,
    content_hash: str,
    label: str,
) -> None:
    matches = tuple(
        ref for ref in planning_input.verified_state_refs if ref.ref_id == ref_id
    )
    if len(matches) != 1:
        raise ProductionPreparationProvenanceError(
            f"{label} must have exactly one frozen PlanningInput evidence relation"
        )
    match = matches[0]
    if match.revision is not None or match.content_hash != content_hash:
        raise ProductionPreparationProvenanceError(
            f"{label} PlanningInput evidence relation does not match exact immutable authority"
        )


def resolve_preparation_policy_provenance(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
) -> PreparationPolicyProvenance:
    """Recover and independently validate the non-owner authority bound by PREPPOL.

    No evidence is created, migrated, repaired, routed, planned, or dispatched.
    The owner identity fields remain structurally frozen by PREPPOL but are not
    certified here; Phase 39C is the first slice permitted to introduce that
    code-owned owner descriptor.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")

    try:
        materialization = inspect_plan_materialization(
            runtime,
            policy.materialization_id,
        )
        planning_input = inspect_planning_input(
            runtime,
            policy.planning_input_id,
        )
        catalog = read_capability_catalog(runtime, policy.capability_catalog_id)
        routing_policy = read_capability_policy(
            runtime,
            policy.capability_routing_policy_id,
        )
        dispatch_catalog = read_dispatch_catalog(
            runtime,
            policy.dispatch_contract_catalog_id,
            build_builtin_dispatch_validator_registry(),
        )
    except (
        ProductionPlanningInspectionError,
        ProductionCapabilityReadError,
        ProductionWorkOrderReadError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionPreparationProvenanceError(
            "preparation policy evidence could not be loaded and validated"
        ) from exc

    if policy.project_id != planning_input.project_id:
        raise ProductionPreparationProvenanceError(
            "preparation policy project does not match frozen PlanningInput"
        )
    if (
        materialization.materialization_id != policy.materialization_id
        or materialization.content_hash != policy.materialization_hash
        or materialization.planning_input_id != policy.planning_input_id
        or materialization.planning_input_hash != policy.planning_input_hash
    ):
        raise ProductionPreparationProvenanceError(
            "preparation policy materialization relation drifted"
        )
    if (
        planning_input.planning_input_id != policy.planning_input_id
        or planning_input.content_hash != policy.planning_input_hash
    ):
        raise ProductionPreparationProvenanceError(
            "preparation policy PlanningInput relation drifted"
        )

    if (
        catalog.catalog_id != policy.capability_catalog_id
        or catalog.content_hash != policy.capability_catalog_hash
        or planning_input.capability_catalog_hash != catalog.content_hash
    ):
        raise ProductionPreparationProvenanceError(
            "preparation policy capability catalog relation drifted"
        )
    _require_exact_planning_ref(
        planning_input,
        ref_id=catalog.catalog_id,
        content_hash=catalog.content_hash,
        label="CAPCAT",
    )

    if (
        routing_policy.routing_policy_id != policy.capability_routing_policy_id
        or routing_policy.content_hash != policy.capability_routing_policy_hash
        or routing_policy.catalog_id != catalog.catalog_id
        or routing_policy.catalog_hash != catalog.content_hash
    ):
        raise ProductionPreparationProvenanceError(
            "preparation policy capability routing-policy relation drifted"
        )
    _require_exact_planning_ref(
        planning_input,
        ref_id=routing_policy.routing_policy_id,
        content_hash=routing_policy.content_hash,
        label="CAPPOL",
    )
    if tuple(routing_policy.allowed_capability_ids) != tuple(
        planning_input.capability_ids
    ):
        raise ProductionPreparationProvenanceError(
            "CAPPOL allowed capabilities do not exactly match frozen PlanningInput"
        )

    if (
        dispatch_catalog.dispatch_catalog_id
        != policy.dispatch_contract_catalog_id
        or dispatch_catalog.content_hash != policy.dispatch_contract_catalog_hash
        or dispatch_catalog.phase32_catalog_id != catalog.catalog_id
        or dispatch_catalog.phase32_catalog_hash != catalog.content_hash
    ):
        raise ProductionPreparationProvenanceError(
            "preparation policy dispatch catalog relation drifted"
        )

    return PreparationPolicyProvenance(
        policy=policy,
        materialization=materialization,
        planning_input=planning_input,
        capability_catalog=catalog,
        capability_routing_policy=routing_policy,
        dispatch_contract_catalog=dispatch_catalog,
    )
