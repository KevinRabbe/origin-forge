from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .config import ProjectConfig, load_config
from .model_scheduler import ModelRole
from .production_capability_builtin import build_builtin_capability_catalog
from .production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from .production_capability_store import ProductionCapabilityStore
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from .production_goal_bootstrap_store import (
    acquire_goal_bootstrap_receipt,
    checkpoint_goal_bootstrap_authority_published,
    checkpoint_goal_bootstrap_planning_input_published,
    fail_goal_bootstrap_before_planner,
    read_goal_bootstrap_receipt,
)
from .production_planning_capabilities import freeze_governed_planning_input
from .production_planning_evidence import ProductionPlanningEvidenceStore
from .production_planning_models import PlanningInput
from .production_preparation_owner import build_builtin_preparation_owner_registry
from .production_read_guard import existing_config_path, production_read_connection
from .production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from .production_work_order_models import DispatchContractCatalog
from .production_work_order_store import ProductionWorkOrderStore
from .runtime import OriginForgeRuntime
from .service import StaleRevision


_BOOTSTRAP_OWNER_ID = "originforge.bootstrap.goal-planner@1"
_BOOTSTRAP_CONTRACT_VERSION = "1"
_PLANNER_CONTRACT_ID = "BoundedProductionPlanner.propose@1"
_SUPPORTED_CAPABILITY_ID = "code.change"
_SUPPORTED_ADAPTER_ID = "originforge.code.bounded-retry"
_SUPPORTED_DISPATCH_CONTRACT_ID = "code.bounded-retry@1"
_SUPPORTED_PREPARATION_OWNER_ID = "originforge.preparation.work-order-planner@1"
_PROJECT_INTELLIGENCE_PROJECTION_VERSION = "phase45.project-intelligence@1"
_MODEL_POLICY_PROJECTION_VERSION = "phase45.goal-planner-model-policy@1"
_RESOURCE_POLICY_PROJECTION_VERSION = "phase45.goal-planner-resource-policy@1"
_MAX_PROJECT_INTELLIGENCE_ROWS = 10_000
_PREPLANNER_STAGES = frozenset(
    {
        GoalBootstrapStage.CLAIMED,
        GoalBootstrapStage.AUTHORITY_PUBLISHED,
        GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
    }
)
_INPUT_AVAILABLE_STAGES = frozenset(
    {
        GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
        GoalBootstrapStage.PLANNER_STARTED,
        GoalBootstrapStage.PLANNER_RETURNED,
        GoalBootstrapStage.PLAN_AUDITED,
        GoalBootstrapStage.MATERIALIZED,
        GoalBootstrapStage.PREPPOL_PUBLISHED,
    }
)


class GoalBootstrapAuthorityError(RuntimeError):
    pass


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class GoalBootstrapOwnerDescriptor:
    owner_id: str
    bootstrap_contract_version: str
    planner_contract_id: str
    semantic_model_role: ModelRole
    supported_capability_id: str
    supported_adapter_id: str
    supported_adapter_fingerprint: str
    supported_dispatch_contract_id: str
    supported_dispatch_contract_hash: str
    preparation_owner_id: str
    preparation_owner_fingerprint: str

    def authority_dict(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "bootstrap_contract_version": self.bootstrap_contract_version,
            "planner_contract_id": self.planner_contract_id,
            "semantic_model_role": self.semantic_model_role.value,
            "supported_capability_id": self.supported_capability_id,
            "supported_adapter_id": self.supported_adapter_id,
            "supported_adapter_fingerprint": self.supported_adapter_fingerprint,
            "supported_dispatch_contract_id": self.supported_dispatch_contract_id,
            "supported_dispatch_contract_hash": self.supported_dispatch_contract_hash,
            "preparation_owner_id": self.preparation_owner_id,
            "preparation_owner_fingerprint": self.preparation_owner_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.authority_dict())


def build_builtin_goal_bootstrap_owner() -> GoalBootstrapOwnerDescriptor:
    """Build the inert reviewed Phase-45 v1 Goal-planning authority descriptor."""

    catalog = build_builtin_capability_catalog()
    try:
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=(_SUPPORTED_ADAPTER_ID,),
            allowed_capability_ids=(_SUPPORTED_CAPABILITY_ID,),
        )
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        contract = dispatch_catalog.contract_for_adapter(_SUPPORTED_ADAPTER_ID)
    except (KeyError, TypeError, ValueError) as exc:
        raise GoalBootstrapAuthorityError(
            "current built-in capability/dispatch authority does not support Phase-45 v1"
        ) from exc
    if (
        policy.allowed_capability_ids != (_SUPPORTED_CAPABILITY_ID,)
        or policy.ordered_adapter_ids != (_SUPPORTED_ADAPTER_ID,)
        or len(dispatch_catalog.contracts) != 1
        or contract.contract_id != _SUPPORTED_DISPATCH_CONTRACT_ID
    ):
        raise GoalBootstrapAuthorityError(
            "current built-in capability/dispatch authority is broader or different than Phase-45 v1"
        )

    registry = build_builtin_preparation_owner_registry()
    preparation_owners = tuple(
        owner
        for owner in registry.descriptors
        if owner.owner_id == _SUPPORTED_PREPARATION_OWNER_ID
    )
    if len(preparation_owners) != 1:
        raise GoalBootstrapAuthorityError(
            "current code preparation owner is not unique for Phase-45 v1"
        )
    preparation_owner = preparation_owners[0]
    adapters = {adapter.adapter_id: adapter for adapter in catalog.adapters}
    try:
        adapter = adapters[_SUPPORTED_ADAPTER_ID]
    except KeyError as exc:
        raise GoalBootstrapAuthorityError(
            "current built-in catalog lacks the Phase-45 code adapter"
        ) from exc
    if (
        preparation_owner.supported_adapter_id != _SUPPORTED_ADAPTER_ID
        or preparation_owner.supported_adapter_fingerprint
        != adapter.implementation_fingerprint
        or preparation_owner.supported_dispatch_contract_id
        != _SUPPORTED_DISPATCH_CONTRACT_ID
        or preparation_owner.supported_dispatch_contract_hash != contract.content_hash
        or preparation_owner.model_strategy_roles != (ModelRole.CODER_STRONG,)
    ):
        raise GoalBootstrapAuthorityError(
            "Phase-32/33 authority drifted from the current Phase-39 preparation owner"
        )

    return GoalBootstrapOwnerDescriptor(
        owner_id=_BOOTSTRAP_OWNER_ID,
        bootstrap_contract_version=_BOOTSTRAP_CONTRACT_VERSION,
        planner_contract_id=_PLANNER_CONTRACT_ID,
        semantic_model_role=ModelRole.CODER_STRONG,
        supported_capability_id=_SUPPORTED_CAPABILITY_ID,
        supported_adapter_id=_SUPPORTED_ADAPTER_ID,
        supported_adapter_fingerprint=adapter.implementation_fingerprint,
        supported_dispatch_contract_id=_SUPPORTED_DISPATCH_CONTRACT_ID,
        supported_dispatch_contract_hash=contract.content_hash,
        preparation_owner_id=preparation_owner.owner_id,
        preparation_owner_fingerprint=preparation_owner.fingerprint,
    )


def acquire_current_goal_bootstrap(
    runtime: OriginForgeRuntime,
    goal_id: str,
) -> GoalBootstrapReceipt:
    owner = build_builtin_goal_bootstrap_owner()
    return acquire_goal_bootstrap_receipt(
        runtime,
        goal_id,
        bootstrap_owner_id=owner.owner_id,
        bootstrap_owner_fingerprint=owner.fingerprint,
        bootstrap_contract_version=owner.bootstrap_contract_version,
    )


def _rows(
    conn,
    *,
    project_id: str,
    table: str,
    columns: tuple[str, ...],
    order_by: str,
) -> list[dict[str, object]]:
    count = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
    )
    if count > _MAX_PROJECT_INTELLIGENCE_ROWS:
        raise GoalBootstrapAuthorityError(
            f"Project Intelligence {table} exceeds Phase-45 bounded projection"
        )
    if count == 0:
        return []
    selected = ", ".join(columns)
    rows = conn.execute(
        f"SELECT {selected} FROM {table} WHERE project_id = ? ORDER BY {order_by}",
        (project_id,),
    ).fetchall()
    if len(rows) != count:
        raise GoalBootstrapAuthorityError(
            f"Project Intelligence {table} changed during bounded projection"
        )
    return [{column: row[column] for column in columns} for row in rows]


def project_intelligence_projection_hash(runtime: OriginForgeRuntime) -> str:
    """Hash one bounded, read-only, infrastructure-selected Phase-17 projection."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    with production_read_connection(runtime) as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise GoalBootstrapAuthorityError("project is not initialized")
        project_id = str(project["id"])
        payload = {
            "projection_version": _PROJECT_INTELLIGENCE_PROJECTION_VERSION,
            "project_id": project_id,
            "entities": _rows(
                conn,
                project_id=project_id,
                table="entities",
                columns=(
                    "id",
                    "kind",
                    "name",
                    "description",
                    "status",
                    "revision",
                    "created_at",
                    "updated_at",
                ),
                order_by="kind, name, id",
            ),
            "relations": _rows(
                conn,
                project_id=project_id,
                table="entity_relations",
                columns=(
                    "id",
                    "source_entity_id",
                    "relation_type",
                    "target_entity_id",
                    "status",
                    "revision",
                    "rationale",
                    "created_at",
                    "updated_at",
                ),
                order_by="relation_type, source_entity_id, target_entity_id, id",
            ),
            "bindings": _rows(
                conn,
                project_id=project_id,
                table="entity_bindings",
                columns=(
                    "id",
                    "entity_id",
                    "binding_type",
                    "target_ref",
                    "target_hash",
                    "status",
                    "revision",
                    "created_at",
                    "updated_at",
                ),
                order_by="entity_id, binding_type, target_ref, id",
            ),
            "design_rules": _rows(
                conn,
                project_id=project_id,
                table="design_rules",
                columns=(
                    "id",
                    "category",
                    "title",
                    "statement",
                    "rationale",
                    "authority",
                    "scope_entity_ids_json",
                    "status",
                    "revision",
                    "supersedes_rule_id",
                    "created_at",
                    "updated_at",
                ),
                order_by="category, title, id",
            ),
        }
    return _canonical_hash(payload)


def _capacity_payload(config: ProjectConfig) -> dict[str, object] | None:
    capacity = config.resource_models.capacity
    if capacity is None:
        return None
    return {
        "cpu_slots": capacity.cpu_slots,
        "ram_mib": capacity.ram_mib,
        "max_active_leases": capacity.max_active_leases,
        "gpus": [
            {
                "device_id": gpu.device_id,
                "vram_mib": gpu.vram_mib,
                "reserve_vram_mib": gpu.reserve_vram_mib,
                "compute_slots": gpu.compute_slots,
            }
            for gpu in sorted(capacity.gpus, key=lambda value: value.device_id)
        ],
    }


def goal_planner_policy_hashes(runtime: OriginForgeRuntime) -> tuple[str, str]:
    """Derive model/resource hashes for exactly the protected CODER_STRONG chain."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    existing_config_path(runtime.project_root)
    config = load_config(runtime.project_root)
    if config.version < 6 or not config.resource_models.enabled:
        raise GoalBootstrapAuthorityError(
            "Phase-45 Goal planning requires protected enabled config version 6"
        )
    try:
        policy = config.resource_models.policy(ModelRole.CODER_STRONG)
        registry = config.resource_models.registry()
        profiles = tuple(
            registry.profile(profile_id) for profile_id in policy.ordered_profile_ids
        )
    except KeyError as exc:
        raise GoalBootstrapAuthorityError(
            "protected model configuration lacks the CODER_STRONG planning chain"
        ) from exc
    if not profiles or any(
        profile.role is not ModelRole.CODER_STRONG for profile in profiles
    ):
        raise GoalBootstrapAuthorityError(
            "protected CODER_STRONG planning chain contains a role mismatch"
        )

    provider_by_runtime = {}
    for profile in profiles:
        try:
            provider = config.model_runtimes.provider_for_profile(profile.profile_id)
            binding = provider.binding(profile.profile_id)
        except KeyError as exc:
            raise GoalBootstrapAuthorityError(
                "protected Goal-planner profile lacks an exact runtime/provider binding"
            ) from exc
        if provider.runtime_id != profile.runtime_id:
            raise GoalBootstrapAuthorityError(
                "protected Goal-planner runtime/provider relation drifted"
            )
        if profile.model_hash is not None and binding.model_sha256 != profile.model_hash:
            raise GoalBootstrapAuthorityError(
                "protected Goal-planner model hash/runtime binding drifted"
            )
        existing = provider_by_runtime.get(provider.runtime_id)
        if existing is not None and existing != provider:
            raise GoalBootstrapAuthorityError(
                "one Goal-planner runtime resolved to conflicting providers"
            )
        provider_by_runtime[provider.runtime_id] = provider

    model_policy_hash = _canonical_hash(
        {
            "projection_version": _MODEL_POLICY_PROJECTION_VERSION,
            "config_version": config.version,
            "semantic_model_role": ModelRole.CODER_STRONG.value,
            "selection_policy": {
                "primary_profile_id": policy.primary_profile_id,
                "fallback_profile_ids": list(policy.fallback_profile_ids),
            },
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "role": profile.role.value,
                    "model_id": profile.model_id,
                    "model_hash": profile.model_hash,
                    "runtime_id": profile.runtime_id,
                }
                for profile in profiles
            ],
            "runtime_providers": [
                provider_by_runtime[runtime_id].to_dict()
                for runtime_id in sorted(provider_by_runtime)
            ],
        }
    )
    resource_policy_hash = _canonical_hash(
        {
            "projection_version": _RESOURCE_POLICY_PROJECTION_VERSION,
            "config_version": config.version,
            "enabled": config.resource_models.enabled,
            "capacity": _capacity_payload(config),
            "profile_resources": [
                {
                    "profile_id": profile.profile_id,
                    "resources": profile.to_dict()["resources"],
                }
                for profile in profiles
            ],
        }
    )
    return model_policy_hash, resource_policy_hash


def _require_exact_authority(
    catalog: CapabilityCatalog,
    policy: CapabilityRoutingPolicy,
    dispatch_catalog: DispatchContractCatalog,
    owner: GoalBootstrapOwnerDescriptor,
) -> None:
    if (
        policy.catalog_id != catalog.catalog_id
        or policy.catalog_hash != catalog.content_hash
        or policy.allowed_capability_ids != (_SUPPORTED_CAPABILITY_ID,)
        or policy.ordered_adapter_ids != (_SUPPORTED_ADAPTER_ID,)
        or dispatch_catalog.phase32_catalog_id != catalog.catalog_id
        or dispatch_catalog.phase32_catalog_hash != catalog.content_hash
        or len(dispatch_catalog.contracts) != 1
    ):
        raise GoalBootstrapAuthorityError(
            "persisted Phase-45 capability/dispatch authority relation drifted"
        )
    adapters = {adapter.adapter_id: adapter for adapter in catalog.adapters}
    try:
        adapter = adapters[_SUPPORTED_ADAPTER_ID]
        contract = dispatch_catalog.contract_for_adapter(_SUPPORTED_ADAPTER_ID)
    except KeyError as exc:
        raise GoalBootstrapAuthorityError(
            "persisted Phase-45 authority lacks the exact code adapter/contract"
        ) from exc
    if (
        adapter.implementation_fingerprint != owner.supported_adapter_fingerprint
        or contract.contract_id != owner.supported_dispatch_contract_id
        or contract.content_hash != owner.supported_dispatch_contract_hash
        or contract.adapter_fingerprint != owner.supported_adapter_fingerprint
    ):
        raise GoalBootstrapAuthorityError(
            "persisted Phase-45 authority no longer matches code-owned v1 fingerprints"
        )


def _publish_authority(
    runtime: OriginForgeRuntime,
    owner: GoalBootstrapOwnerDescriptor,
) -> tuple[CapabilityCatalog, CapabilityRoutingPolicy, DispatchContractCatalog]:
    catalog = build_builtin_capability_catalog()
    policy = CapabilityRoutingPolicy.create(
        catalog,
        ordered_adapter_ids=(_SUPPORTED_ADAPTER_ID,),
        allowed_capability_ids=(_SUPPORTED_CAPABILITY_ID,),
    )
    dispatch_catalog = build_builtin_dispatch_catalog(catalog)
    _require_exact_authority(catalog, policy, dispatch_catalog, owner)

    capability_store = ProductionCapabilityStore(runtime)
    capability_store.publish_catalog(catalog)
    capability_store.publish_policy(policy, catalog)
    work_order_store = ProductionWorkOrderStore(
        runtime,
        capability_store,
        build_builtin_dispatch_validator_registry(),
    )
    work_order_store.publish_dispatch_catalog(dispatch_catalog)

    durable_catalog = capability_store.load_catalog(catalog.catalog_id)
    durable_policy = capability_store.load_policy(policy.routing_policy_id)
    durable_dispatch = work_order_store.load_dispatch_catalog(
        dispatch_catalog.dispatch_catalog_id
    )
    _require_exact_authority(
        durable_catalog,
        durable_policy,
        durable_dispatch,
        owner,
    )
    return durable_catalog, durable_policy, durable_dispatch


def _load_receipt_authority(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    owner: GoalBootstrapOwnerDescriptor,
) -> tuple[CapabilityCatalog, CapabilityRoutingPolicy, DispatchContractCatalog]:
    if (
        receipt.capability_catalog_id is None
        or receipt.capability_catalog_hash is None
        or receipt.capability_routing_policy_id is None
        or receipt.capability_routing_policy_hash is None
        or receipt.dispatch_contract_catalog_id is None
        or receipt.dispatch_contract_catalog_hash is None
    ):
        raise GoalBootstrapAuthorityError("GOALBOOT authority checkpoint is incomplete")
    capability_store = ProductionCapabilityStore(runtime)
    catalog = capability_store.load_catalog(receipt.capability_catalog_id)
    policy = capability_store.load_policy(receipt.capability_routing_policy_id)
    work_order_store = ProductionWorkOrderStore(
        runtime,
        capability_store,
        build_builtin_dispatch_validator_registry(),
    )
    dispatch_catalog = work_order_store.load_dispatch_catalog(
        receipt.dispatch_contract_catalog_id
    )
    if (
        catalog.content_hash != receipt.capability_catalog_hash
        or policy.content_hash != receipt.capability_routing_policy_hash
        or dispatch_catalog.content_hash != receipt.dispatch_contract_catalog_hash
    ):
        raise GoalBootstrapAuthorityError(
            "GOALBOOT authority checkpoint hash differs from persisted authority"
        )
    _require_exact_authority(catalog, policy, dispatch_catalog, owner)
    return catalog, policy, dispatch_catalog


def _publish_planning_input(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    catalog: CapabilityCatalog,
    policy: CapabilityRoutingPolicy,
) -> PlanningInput:
    project_hash = project_intelligence_projection_hash(runtime)
    model_hash, resource_hash = goal_planner_policy_hashes(runtime)
    capability_store = ProductionCapabilityStore(runtime)
    planning_input = freeze_governed_planning_input(
        runtime,
        receipt.goal_id,
        capability_store=capability_store,
        catalog_id=catalog.catalog_id,
        routing_policy_id=policy.routing_policy_id,
        project_intelligence_hash=project_hash,
        model_policy_hash=model_hash,
        resource_policy_hash=resource_hash,
    )
    if (
        planning_input.project_id != receipt.project_id
        or planning_input.goal_id != receipt.goal_id
        or planning_input.goal_revision != receipt.goal_revision
        or planning_input.goal_content_hash != receipt.goal_content_hash
        or planning_input.capability_catalog_hash != catalog.content_hash
        or planning_input.capability_ids != (_SUPPORTED_CAPABILITY_ID,)
    ):
        raise GoalBootstrapAuthorityError(
            "governed PlanningInput drifted from exact GOALBOOT authority"
        )
    evidence = ProductionPlanningEvidenceStore(runtime)
    evidence.publish_input(planning_input)
    durable = evidence.load_input(planning_input.planning_input_id)
    if durable != planning_input or durable.content_hash != planning_input.content_hash:
        raise GoalBootstrapAuthorityError("published PlanningInput failed exact reload")
    return durable


def _load_receipt_planning_input(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> PlanningInput:
    if receipt.planning_input_id is None or receipt.planning_input_hash is None:
        raise GoalBootstrapAuthorityError("GOALBOOT PlanningInput checkpoint is incomplete")
    planning_input = ProductionPlanningEvidenceStore(runtime).load_input(
        receipt.planning_input_id
    )
    if (
        planning_input.content_hash != receipt.planning_input_hash
        or planning_input.project_id != receipt.project_id
        or planning_input.goal_id != receipt.goal_id
        or planning_input.goal_revision != receipt.goal_revision
        or planning_input.goal_content_hash != receipt.goal_content_hash
        or planning_input.capability_catalog_hash != receipt.capability_catalog_hash
        or planning_input.capability_ids != (_SUPPORTED_CAPABILITY_ID,)
    ):
        raise GoalBootstrapAuthorityError(
            "persisted PlanningInput drifted from exact GOALBOOT checkpoint"
        )
    expected_refs = {
        (receipt.capability_catalog_id, receipt.capability_catalog_hash),
        (
            receipt.capability_routing_policy_id,
            receipt.capability_routing_policy_hash,
        ),
    }
    actual_refs = {
        (ref.ref_id, ref.content_hash) for ref in planning_input.verified_state_refs
    }
    if actual_refs != expected_refs or planning_input.active_design_rule_refs:
        raise GoalBootstrapAuthorityError(
            "PlanningInput contains authority/evidence outside Phase-45 v1 freeze"
        )
    return planning_input


def _terminalize_preplanner_failure(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    exc: Exception,
) -> None:
    if receipt.stage not in _PREPLANNER_STAGES:
        return
    try:
        fail_goal_bootstrap_before_planner(
            runtime,
            receipt.bootstrap_id,
            receipt.revision,
            receipt.stage,
            f"Phase-45B authority/input freeze failed: {type(exc).__name__}: {exc}",
        )
    except StaleRevision:
        return


def prepare_goal_bootstrap_input(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
) -> tuple[GoalBootstrapReceipt, PlanningInput]:
    """Advance one GOALBOOT only through the governed PLINPUT boundary.

    Fresh immutable authority or PlanningInput evidence may be orphaned by a
    pre-checkpoint crash. Recovery never discovers orphans by ordering: it reads
    only exact IDs/hashes from the winning GOALBOOT receipt and may publish fresh
    immutable evidence before retrying the missing CAS checkpoint.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    owner = build_builtin_goal_bootstrap_owner()

    for _ in range(8):
        receipt = read_goal_bootstrap_receipt(runtime, bootstrap_id)
        if (
            receipt.bootstrap_owner_id != owner.owner_id
            or receipt.bootstrap_owner_fingerprint != owner.fingerprint
            or receipt.bootstrap_contract_version != owner.bootstrap_contract_version
        ):
            raise GoalBootstrapAuthorityError(
                "GOALBOOT is not owned by the current code-owned Phase-45 authority"
            )
        if receipt.status is not GoalBootstrapStatus.ACTIVE:
            raise GoalBootstrapAuthorityError(
                f"GOALBOOT is not active: {receipt.status.value}"
            )

        if receipt.stage is GoalBootstrapStage.CLAIMED:
            try:
                catalog, policy, dispatch_catalog = _publish_authority(runtime, owner)
                checkpoint_goal_bootstrap_authority_published(
                    runtime,
                    receipt.bootstrap_id,
                    receipt.revision,
                    capability_catalog_id=catalog.catalog_id,
                    capability_catalog_hash=catalog.content_hash,
                    capability_routing_policy_id=policy.routing_policy_id,
                    capability_routing_policy_hash=policy.content_hash,
                    dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
                    dispatch_contract_catalog_hash=dispatch_catalog.content_hash,
                )
            except StaleRevision:
                continue
            except Exception as exc:
                _terminalize_preplanner_failure(runtime, receipt, exc)
                raise GoalBootstrapAuthorityError(
                    "Phase-45B failed while publishing code-owned authority"
                ) from exc
            continue

        try:
            catalog, policy, _ = _load_receipt_authority(runtime, receipt, owner)
        except Exception as exc:
            _terminalize_preplanner_failure(runtime, receipt, exc)
            raise GoalBootstrapAuthorityError(
                "Phase-45B failed while revalidating code-owned authority"
            ) from exc

        if receipt.stage is GoalBootstrapStage.AUTHORITY_PUBLISHED:
            try:
                planning_input = _publish_planning_input(
                    runtime,
                    receipt,
                    catalog,
                    policy,
                )
                checkpoint_goal_bootstrap_planning_input_published(
                    runtime,
                    receipt.bootstrap_id,
                    receipt.revision,
                    planning_input_id=planning_input.planning_input_id,
                    planning_input_hash=planning_input.content_hash,
                )
            except StaleRevision:
                continue
            except Exception as exc:
                _terminalize_preplanner_failure(runtime, receipt, exc)
                raise GoalBootstrapAuthorityError(
                    "Phase-45B failed while freezing governed PlanningInput"
                ) from exc
            continue

        if receipt.stage in _INPUT_AVAILABLE_STAGES:
            planning_input = _load_receipt_planning_input(runtime, receipt)
            return receipt, planning_input

        raise GoalBootstrapAuthorityError(
            f"GOALBOOT stage is outside Phase-45B boundary: {receipt.stage.value}"
        )

    raise GoalBootstrapAuthorityError(
        "GOALBOOT changed too many times while advancing Phase-45B boundary"
    )