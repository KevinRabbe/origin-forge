from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .config import load_config
from .ids import IdKind, new_id
from .managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from .model import ModelAdapter, ModelRequest, ModelResponse
from .model_runtime_registry import ModelRuntimeBinding, ModelRuntimeRegistry, RuntimeDispatchLoader
from .model_scheduler import (
    ModelCapacityUnavailable,
    ModelRole,
    ModelSelectionPolicy,
    ScheduledModel,
)
from .model_scheduler_factory import ConfiguredModelScheduling, create_model_scheduling
from .production_goal_bootstrap_authority import (
    GoalBootstrapOwnerDescriptor,
    build_builtin_goal_bootstrap_owner,
    goal_planner_policy_hashes,
    prepare_goal_bootstrap_input,
)
from .production_goal_bootstrap_models import (
    GoalBootstrapReceipt,
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from .production_goal_bootstrap_store import (
    checkpoint_goal_bootstrap_planner_returned,
    checkpoint_goal_bootstrap_planner_started,
    interrupt_goal_bootstrap,
    read_goal_bootstrap_receipt,
)
from .production_planner import PLAN_PROPOSAL_SCHEMA, PLANNER_INSTRUCTIONS
from .production_planning_evidence import (
    ProductionPlanningEvidenceStore,
    goal_planning_hash,
)
from .production_planning_models import PlanProposal, PlanningInput, ProductionPlanningModelError
from .production_planning_proposal import parse_plan_proposal
from .production_read_guard import existing_config_path
from .runs import finish_run
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now
from .state import RunStatus


_PLANNER_ROLE = "PLANNER"
_PLANNER_GENERATION_VERIFIER = "OriginForge.GoalBootstrapPlanner"
_PLANNER_DISPATCH_MARKER = "goal-bootstrap-planner-dispatch"
_DEPENDENCY_PLAN_VERSION = "phase45.goal-bootstrap-planner-dependencies@1"


class GoalBootstrapPlannerError(RuntimeError):
    pass


class GoalBootstrapPlannerInterrupted(GoalBootstrapPlannerError):
    pass


def _canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GoalBootstrapPlannerError("Goal planner evidence is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decode_json_object(raw: object, *, label: str) -> dict[str, object]:
    if not isinstance(raw, str):
        raise GoalBootstrapPlannerError(f"{label} is not stored JSON")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GoalBootstrapPlannerError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise GoalBootstrapPlannerError(f"{label} is not an object")
    return value


@dataclass(frozen=True)
class GoalBootstrapPlannerSelection:
    requested_profile_id: str
    selected_profile_id: str
    attempted_profile_ids: tuple[str, ...]
    model_id: str
    model_hash: str | None
    runtime_id: str
    selected_profile_fingerprint: str
    runtime_provider_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_profile_id": self.requested_profile_id,
            "selected_profile_id": self.selected_profile_id,
            "attempted_profile_ids": list(self.attempted_profile_ids),
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "runtime_id": self.runtime_id,
            "selected_profile_fingerprint": self.selected_profile_fingerprint,
            "runtime_provider_fingerprint": self.runtime_provider_fingerprint,
        }


@dataclass(frozen=True)
class GoalBootstrapPlannerDependencyPlan:
    bootstrap_id: str
    bootstrap_owner_id: str
    bootstrap_owner_fingerprint: str
    bootstrap_contract_version: str
    planner_contract_id: str
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    capability_catalog_id: str
    capability_catalog_hash: str
    capability_routing_policy_id: str
    capability_routing_policy_hash: str
    dispatch_contract_catalog_id: str
    dispatch_contract_catalog_hash: str
    planning_input_id: str
    planning_input_hash: str
    project_intelligence_hash: str
    model_policy_hash: str
    resource_policy_hash: str
    semantic_model_role: str
    config_version: int
    model_runtime_config_fingerprint: str
    primary_profile_id: str
    fallback_profile_ids: tuple[str, ...]
    allowed_profile_fingerprints: tuple[tuple[str, str], ...]
    runtime_provider_fingerprints: tuple[tuple[str, str], ...]
    selection: GoalBootstrapPlannerSelection

    def to_dict(self) -> dict[str, object]:
        return {
            "dependency_plan_version": _DEPENDENCY_PLAN_VERSION,
            "bootstrap_id": self.bootstrap_id,
            "bootstrap_owner_id": self.bootstrap_owner_id,
            "bootstrap_owner_fingerprint": self.bootstrap_owner_fingerprint,
            "bootstrap_contract_version": self.bootstrap_contract_version,
            "planner_contract_id": self.planner_contract_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "authority": {
                "capability_catalog_id": self.capability_catalog_id,
                "capability_catalog_hash": self.capability_catalog_hash,
                "capability_routing_policy_id": self.capability_routing_policy_id,
                "capability_routing_policy_hash": self.capability_routing_policy_hash,
                "dispatch_contract_catalog_id": self.dispatch_contract_catalog_id,
                "dispatch_contract_catalog_hash": self.dispatch_contract_catalog_hash,
            },
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "project_intelligence_hash": self.project_intelligence_hash,
            "model_policy_hash": self.model_policy_hash,
            "resource_policy_hash": self.resource_policy_hash,
            "semantic_model_role": self.semantic_model_role,
            "config_version": self.config_version,
            "model_runtime_config_fingerprint": self.model_runtime_config_fingerprint,
            "selection_policy": {
                "primary_profile_id": self.primary_profile_id,
                "fallback_profile_ids": list(self.fallback_profile_ids),
            },
            "allowed_profile_fingerprints": [
                {"profile_id": profile_id, "fingerprint": fingerprint}
                for profile_id, fingerprint in self.allowed_profile_fingerprints
            ],
            "runtime_provider_fingerprints": [
                {"runtime_id": runtime_id, "fingerprint": fingerprint}
                for runtime_id, fingerprint in self.runtime_provider_fingerprints
            ],
            "selection": self.selection.to_dict(),
        }

    @property
    def plan_hash(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class GoalBootstrapPlannerEnvironment:
    owner: GoalBootstrapOwnerDescriptor
    config_version: int
    model_runtime_config_fingerprint: str
    policy: ModelSelectionPolicy
    scheduling: ConfiguredModelScheduling
    runtime_dispatch_loader: RuntimeDispatchLoader
    allowed_profile_fingerprints: tuple[tuple[str, str], ...]
    runtime_provider_fingerprints: tuple[tuple[str, str], ...]

    @property
    def primary_model_id(self) -> str:
        return self.scheduling.registry.profile(self.policy.primary_profile_id).model_id

    def selection_from_scheduled(self, scheduled: ScheduledModel) -> GoalBootstrapPlannerSelection:
        profile = scheduled.profile
        providers = dict(self.runtime_provider_fingerprints)
        try:
            provider_fingerprint = providers[profile.runtime_id]
        except KeyError as exc:
            raise GoalBootstrapPlannerError(
                "selected Goal-planner runtime lacks protected provider fingerprint"
            ) from exc
        return GoalBootstrapPlannerSelection(
            requested_profile_id=scheduled.requested_profile_id,
            selected_profile_id=profile.profile_id,
            attempted_profile_ids=tuple(scheduled.attempted_profile_ids),
            model_id=profile.model_id,
            model_hash=profile.model_hash,
            runtime_id=profile.runtime_id,
            selected_profile_fingerprint=_canonical_hash(profile.to_dict()),
            runtime_provider_fingerprint=provider_fingerprint,
        )

    def validate_selection(self, selection: GoalBootstrapPlannerSelection) -> None:
        ordered = self.policy.ordered_profile_ids
        if selection.requested_profile_id != self.policy.primary_profile_id:
            raise GoalBootstrapPlannerError("Goal-planner requested profile drifted")
        if selection.selected_profile_id not in ordered:
            raise GoalBootstrapPlannerError("Goal-planner selected profile escaped policy")
        selected_index = ordered.index(selection.selected_profile_id)
        if selection.attempted_profile_ids != ordered[: selected_index + 1]:
            raise GoalBootstrapPlannerError("Goal-planner attempted profile chain drifted")
        profile = self.scheduling.registry.profile(selection.selected_profile_id)
        if (
            profile.role is not ModelRole.CODER_STRONG
            or selection.model_id != profile.model_id
            or selection.model_hash != profile.model_hash
            or selection.runtime_id != profile.runtime_id
            or selection.selected_profile_fingerprint != _canonical_hash(profile.to_dict())
        ):
            raise GoalBootstrapPlannerError("Goal-planner selected profile identity drifted")
        providers = dict(self.runtime_provider_fingerprints)
        if providers.get(profile.runtime_id) != selection.runtime_provider_fingerprint:
            raise GoalBootstrapPlannerError("Goal-planner runtime provider fingerprint drifted")

    def dependency_plan(
        self,
        receipt: GoalBootstrapReceipt,
        planning_input: PlanningInput,
        selection: GoalBootstrapPlannerSelection,
    ) -> GoalBootstrapPlannerDependencyPlan:
        self.validate_selection(selection)
        required = (
            receipt.capability_catalog_id,
            receipt.capability_catalog_hash,
            receipt.capability_routing_policy_id,
            receipt.capability_routing_policy_hash,
            receipt.dispatch_contract_catalog_id,
            receipt.dispatch_contract_catalog_hash,
            receipt.planning_input_id,
            receipt.planning_input_hash,
        )
        if any(value is None for value in required):
            raise GoalBootstrapPlannerError("GOALBOOT lacks frozen planning authority")
        if (
            planning_input.planning_input_id != receipt.planning_input_id
            or planning_input.content_hash != receipt.planning_input_hash
            or planning_input.goal_id != receipt.goal_id
            or planning_input.goal_revision != receipt.goal_revision
            or planning_input.goal_content_hash != receipt.goal_content_hash
        ):
            raise GoalBootstrapPlannerError("PlanningInput drifted from GOALBOOT")
        return GoalBootstrapPlannerDependencyPlan(
            bootstrap_id=receipt.bootstrap_id,
            bootstrap_owner_id=receipt.bootstrap_owner_id,
            bootstrap_owner_fingerprint=receipt.bootstrap_owner_fingerprint,
            bootstrap_contract_version=receipt.bootstrap_contract_version,
            planner_contract_id=self.owner.planner_contract_id,
            goal_id=receipt.goal_id,
            goal_revision=receipt.goal_revision,
            goal_content_hash=receipt.goal_content_hash,
            capability_catalog_id=str(receipt.capability_catalog_id),
            capability_catalog_hash=str(receipt.capability_catalog_hash),
            capability_routing_policy_id=str(receipt.capability_routing_policy_id),
            capability_routing_policy_hash=str(receipt.capability_routing_policy_hash),
            dispatch_contract_catalog_id=str(receipt.dispatch_contract_catalog_id),
            dispatch_contract_catalog_hash=str(receipt.dispatch_contract_catalog_hash),
            planning_input_id=planning_input.planning_input_id,
            planning_input_hash=planning_input.content_hash,
            project_intelligence_hash=planning_input.project_intelligence_hash,
            model_policy_hash=planning_input.model_policy_hash,
            resource_policy_hash=planning_input.resource_policy_hash,
            semantic_model_role=self.owner.semantic_model_role.value,
            config_version=self.config_version,
            model_runtime_config_fingerprint=self.model_runtime_config_fingerprint,
            primary_profile_id=self.policy.primary_profile_id,
            fallback_profile_ids=tuple(self.policy.fallback_profile_ids),
            allowed_profile_fingerprints=self.allowed_profile_fingerprints,
            runtime_provider_fingerprints=self.runtime_provider_fingerprints,
            selection=selection,
        )


@dataclass(frozen=True)
class GoalBootstrapPlannerResult:
    receipt: GoalBootstrapReceipt
    proposal: PlanProposal
    planner_run_id: str
    planner_dependency_plan_hash: str
    recovered: bool


def assemble_goal_bootstrap_planner_environment(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
) -> GoalBootstrapPlannerEnvironment:
    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    owner = build_builtin_goal_bootstrap_owner()
    if (
        receipt.bootstrap_owner_id != owner.owner_id
        or receipt.bootstrap_owner_fingerprint != owner.fingerprint
        or receipt.bootstrap_contract_version != owner.bootstrap_contract_version
        or owner.semantic_model_role is not ModelRole.CODER_STRONG
    ):
        raise GoalBootstrapPlannerError("GOALBOOT owner no longer matches code-owned planner authority")
    model_policy_hash, resource_policy_hash = goal_planner_policy_hashes(runtime)
    if (
        planning_input.model_policy_hash != model_policy_hash
        or planning_input.resource_policy_hash != resource_policy_hash
    ):
        raise GoalBootstrapPlannerError("PlanningInput model/resource policy hashes drifted")

    existing_config_path(runtime.project_root)
    config = load_config(runtime.project_root)
    if config.version < 6 or not config.resource_models.enabled:
        raise GoalBootstrapPlannerError("Goal planning requires protected enabled config version 6")
    try:
        policy = config.resource_models.policy(ModelRole.CODER_STRONG)
        scheduling = create_model_scheduling(config.resource_models)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise GoalBootstrapPlannerError("protected Goal-planner scheduling is unavailable") from exc

    provider_by_runtime: dict[str, object] = {}
    profile_fingerprints: list[tuple[str, str]] = []
    for profile_id in policy.ordered_profile_ids:
        profile = scheduling.registry.profile(profile_id)
        if profile.role is not ModelRole.CODER_STRONG:
            raise GoalBootstrapPlannerError("Goal-planner policy contains a role mismatch")
        try:
            provider = config.model_runtimes.provider_for_profile(profile.profile_id)
            binding = provider.binding(profile.profile_id)
        except KeyError as exc:
            raise GoalBootstrapPlannerError(
                "Goal-planner profile lacks protected runtime/provider binding"
            ) from exc
        if provider.runtime_id != profile.runtime_id:
            raise GoalBootstrapPlannerError("Goal-planner runtime/provider relation drifted")
        if profile.model_hash is not None and binding.model_sha256 != profile.model_hash:
            raise GoalBootstrapPlannerError("Goal-planner model/runtime hash binding drifted")
        existing = provider_by_runtime.get(provider.runtime_id)
        if existing is not None and existing != provider:
            raise GoalBootstrapPlannerError("one Goal-planner runtime resolved to conflicting providers")
        provider_by_runtime[provider.runtime_id] = provider
        profile_fingerprints.append((profile.profile_id, _canonical_hash(profile.to_dict())))

    managed_loaders = tuple(
        ManagedLlamaCppCpuLoader(runtime.project_root, provider_by_runtime[runtime_id])
        for runtime_id in sorted(provider_by_runtime)
    )
    loader_by_runtime = {loader.provider.runtime_id: loader for loader in managed_loaders}
    runtime_registry = ModelRuntimeRegistry(
        tuple(
            ModelRuntimeBinding(runtime_id, loader_by_runtime[runtime_id])
            for runtime_id in sorted(loader_by_runtime)
        )
    )
    provider_fingerprints = tuple(
        (runtime_id, provider_by_runtime[runtime_id].fingerprint)
        for runtime_id in sorted(provider_by_runtime)
    )
    return GoalBootstrapPlannerEnvironment(
        owner=owner,
        config_version=config.version,
        model_runtime_config_fingerprint=config.model_runtimes.fingerprint,
        policy=policy,
        scheduling=scheduling,
        runtime_dispatch_loader=runtime_registry.dispatch_loader(),
        allowed_profile_fingerprints=tuple(profile_fingerprints),
        runtime_provider_fingerprints=provider_fingerprints,
    )


def _planner_context(runtime: OriginForgeRuntime, planning_input: PlanningInput) -> dict[str, object]:
    project_id = runtime.project_id()
    if planning_input.project_id != project_id:
        raise GoalBootstrapPlannerError("planning input belongs to another project")
    with runtime.store.session() as conn:
        goal = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND project_id = ?",
            (planning_input.goal_id, project_id),
        ).fetchone()
        if goal is None:
            raise GoalBootstrapPlannerError("GOALBOOT Goal is unavailable")
        if (
            int(goal["revision"]) != planning_input.goal_revision
            or goal_planning_hash(goal) != planning_input.goal_content_hash
        ):
            raise GoalBootstrapPlannerError("planning input became stale before Planner generation")
        try:
            success = json.loads(goal["success_criteria_json"])
            constraints = json.loads(goal["constraints_json"])
            budgets = json.loads(goal["budgets_json"])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise GoalBootstrapPlannerError("Goal planning context is invalid") from exc
        return {
            "planning_input": planning_input.to_dict(),
            "goal": {
                "id": goal["id"],
                "revision": int(goal["revision"]),
                "objective": goal["objective"],
                "success_criteria": success,
                "constraints": constraints,
                "budgets": budgets,
                "priority": int(goal["priority"]),
                "status": goal["status"],
            },
        }


def _planner_request(
    runtime: OriginForgeRuntime,
    planning_input: PlanningInput,
    run_id: str,
) -> tuple[ModelRequest, str]:
    request = ModelRequest(
        run_id=run_id,
        task_id=None,
        instructions=PLANNER_INSTRUCTIONS,
        context=_planner_context(runtime, planning_input),
        response_schema=PLAN_PROPOSAL_SCHEMA,
    )
    request_hash = _canonical_hash(
        {
            "run_id": request.run_id,
            "task_id": request.task_id,
            "instructions": request.instructions,
            "context": request.context,
            "response_schema": request.response_schema,
        }
    )
    return request, request_hash


def _checkpoint_planner_started(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    *,
    planner_dependency_plan_hash: str,
) -> GoalBootstrapReceipt:
    return checkpoint_goal_bootstrap_planner_started(
        runtime,
        receipt.bootstrap_id,
        receipt.revision,
        planner_dependency_plan_hash=planner_dependency_plan_hash,
    )


def _dispatch_marker_evidence(
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    plan: GoalBootstrapPlannerDependencyPlan,
) -> dict[str, object]:
    return {
        "goal_bootstrap_id": receipt.bootstrap_id,
        "goal_bootstrap_revision": receipt.revision,
        "planner_dependency_plan_hash": plan.plan_hash,
        "planning_input_id": planning_input.planning_input_id,
        "planning_input_hash": planning_input.content_hash,
        "dependency_plan": plan.to_dict(),
        **plan.selection.to_dict(),
    }


def _selection_from_evidence(evidence: dict[str, object]) -> GoalBootstrapPlannerSelection:
    attempted = evidence.get("attempted_profile_ids")
    if not isinstance(attempted, list) or not all(isinstance(value, str) for value in attempted):
        raise GoalBootstrapPlannerError("planner selection attempted profile chain is invalid")
    values = {
        "requested_profile_id": evidence.get("requested_profile_id"),
        "selected_profile_id": evidence.get("selected_profile_id"),
        "model_id": evidence.get("model_id"),
        "runtime_id": evidence.get("runtime_id"),
        "selected_profile_fingerprint": evidence.get("selected_profile_fingerprint"),
        "runtime_provider_fingerprint": evidence.get("runtime_provider_fingerprint"),
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise GoalBootstrapPlannerError("planner selection identity evidence is incomplete")
    model_hash = evidence.get("model_hash")
    if model_hash is not None and not isinstance(model_hash, str):
        raise GoalBootstrapPlannerError("planner selection model hash is invalid")
    return GoalBootstrapPlannerSelection(
        requested_profile_id=str(values["requested_profile_id"]),
        selected_profile_id=str(values["selected_profile_id"]),
        attempted_profile_ids=tuple(attempted),
        model_id=str(values["model_id"]),
        model_hash=model_hash,
        runtime_id=str(values["runtime_id"]),
        selected_profile_fingerprint=str(values["selected_profile_fingerprint"]),
        runtime_provider_fingerprint=str(values["runtime_provider_fingerprint"]),
    )


def _validate_dispatch_marker(
    evidence: dict[str, object],
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    plan: GoalBootstrapPlannerDependencyPlan,
) -> None:
    if evidence != _dispatch_marker_evidence(receipt, planning_input, plan):
        raise GoalBootstrapPlannerError("planner dispatch marker drifted from frozen GOALBOOT attempt")


def _dispatch_marker_rows(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with runtime.store.session() as conn:
        stored = conn.execute(
            """SELECT * FROM verifications
               WHERE verification_type = ? AND verifier = ? AND status = 'PASS'
               ORDER BY created_at, id""",
            (_PLANNER_DISPATCH_MARKER, _PLANNER_GENERATION_VERIFIER),
        ).fetchall()
        for row in stored:
            evidence = _decode_json_object(row["evidence_json"], label="planner dispatch marker")
            if evidence.get("goal_bootstrap_id") == bootstrap_id:
                rows.append(dict(row))
    if len(rows) > 1:
        raise GoalBootstrapPlannerError("multiple planner dispatch markers exist for one GOALBOOT")
    return rows


def _validate_marker_run(
    runtime: OriginForgeRuntime,
    run_id: str,
    plan: GoalBootstrapPlannerDependencyPlan,
) -> dict[str, object]:
    run = runtime.get_run(run_id)
    if (
        run["task_id"] is not None
        or run["role"] != _PLANNER_ROLE
        or run["model_profile"] != plan.selection.model_id
        or run["model_hash"] != plan.selection.model_hash
    ):
        raise GoalBootstrapPlannerError("durable planner Run identity drifted")
    return run


def _claim_or_load_dispatch_marker(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    plan: GoalBootstrapPlannerDependencyPlan,
    requested_run_id: str,
) -> tuple[str, bool]:
    if (
        receipt.stage is not GoalBootstrapStage.PLANNER_STARTED
        or receipt.status is not GoalBootstrapStatus.ACTIVE
        or receipt.planner_dependency_plan_hash != plan.plan_hash
        or receipt.planner_run_id is not None
    ):
        raise GoalBootstrapPlannerError("planner dispatch marker requires exact PLANNER_STARTED authority")
    expected_evidence = _dispatch_marker_evidence(receipt, planning_input, plan)
    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """SELECT revision, status, stage, planner_dependency_plan_hash, planner_run_id
               FROM goal_bootstraps WHERE bootstrap_id = ?""",
            (receipt.bootstrap_id,),
        ).fetchone()
        if current is None:
            raise GoalBootstrapPlannerError("GOALBOOT disappeared before planner dispatch marker")
        if (
            int(current["revision"]) != receipt.revision
            or current["status"] != GoalBootstrapStatus.ACTIVE.value
            or current["stage"] != GoalBootstrapStage.PLANNER_STARTED.value
            or current["planner_dependency_plan_hash"] != plan.plan_hash
            or current["planner_run_id"] is not None
        ):
            raise StaleRevision(receipt.bootstrap_id)

        matches: list[tuple[object, dict[str, object]]] = []
        marker_rows = conn.execute(
            """SELECT * FROM verifications
               WHERE verification_type = ? AND verifier = ? AND status = 'PASS'
               ORDER BY created_at, id""",
            (_PLANNER_DISPATCH_MARKER, _PLANNER_GENERATION_VERIFIER),
        ).fetchall()
        for row in marker_rows:
            evidence = _decode_json_object(row["evidence_json"], label="planner dispatch marker")
            if evidence.get("goal_bootstrap_id") == receipt.bootstrap_id:
                matches.append((row, evidence))
        if len(matches) > 1:
            raise GoalBootstrapPlannerError("multiple planner dispatch markers exist for one GOALBOOT")
        if matches:
            row, evidence = matches[0]
            if row["target_type"] != "RUN" or row["run_id"] != row["target_id"]:
                raise GoalBootstrapPlannerError("planner dispatch marker target binding is invalid")
            _validate_dispatch_marker(evidence, receipt, planning_input, plan)
            run_id = str(row["target_id"])
            run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise GoalBootstrapPlannerError("planner dispatch marker targets a missing Run")
            if (
                run["task_id"] is not None
                or run["role"] != _PLANNER_ROLE
                or run["model_profile"] != plan.selection.model_id
                or run["model_hash"] != plan.selection.model_hash
            ):
                raise GoalBootstrapPlannerError("planner dispatch marker Run identity drifted")
            return run_id, False

        verification_id = new_id(IdKind.VERIFICATION)
        conn.execute(
            """INSERT INTO runs(
                   id, task_id, role, model_profile, model_hash, skills_json,
                   allowed_tools_json, started_at, status
               ) VALUES (?, NULL, ?, ?, ?, '[]', '[]', ?, ?)""",
            (
                requested_run_id,
                _PLANNER_ROLE,
                plan.selection.model_id,
                plan.selection.model_hash,
                now,
                RunStatus.RUNNING.value,
            ),
        )
        runtime.store._append_event(
            conn,
            "RUN",
            requested_run_id,
            "RUN_STARTED",
            None,
            RunStatus.RUNNING.value,
            None,
            "SYSTEM",
            None,
            {"task_id": None, "role": _PLANNER_ROLE},
            now,
        )
        conn.execute(
            """INSERT INTO verifications(
                   id, target_type, target_id, verification_type, verifier,
                   status, evidence_json, metrics_json, run_id, created_at
               ) VALUES (?, 'RUN', ?, ?, ?, 'PASS', ?, '{}', ?, ?)""",
            (
                verification_id,
                requested_run_id,
                _PLANNER_DISPATCH_MARKER,
                _PLANNER_GENERATION_VERIFIER,
                _json(expected_evidence),
                requested_run_id,
                now,
            ),
        )
        runtime.store._append_event(
            conn,
            "RUN",
            requested_run_id,
            "VERIFICATION_RECORDED",
            None,
            "PASS",
            None,
            "SYSTEM",
            None,
            {
                "verification_id": verification_id,
                "verification_type": _PLANNER_DISPATCH_MARKER,
            },
            now,
        )
    return requested_run_id, True


def _record_selection(
    runtime: OriginForgeRuntime,
    run_id: str,
    receipt: GoalBootstrapReceipt,
    plan: GoalBootstrapPlannerDependencyPlan,
    scheduled: ScheduledModel,
) -> None:
    gpu = scheduled.lease.gpu
    runtime.record_verification(
        "RUN",
        run_id,
        verification_type="model-resource-selection",
        verifier=_PLANNER_GENERATION_VERIFIER,
        status="PASS",
        evidence={
            "goal_bootstrap_id": receipt.bootstrap_id,
            "planner_dependency_plan_hash": plan.plan_hash,
            **plan.selection.to_dict(),
            "lease_id": scheduled.lease.lease_id,
            "gpu_device_id": gpu.device_id if gpu is not None else None,
            "gpu_exclusive": gpu.exclusive if gpu is not None else False,
        },
        metrics={
            "cpu_slots": scheduled.lease.cpu_slots,
            "ram_mib": scheduled.lease.ram_mib,
            "vram_mib": gpu.vram_mib if gpu is not None else 0,
            "gpu_compute_slots": gpu.compute_slots if gpu is not None else 0,
        },
        run_id=run_id,
    )


def _publish_proposal_and_generation_proof(
    runtime: OriginForgeRuntime,
    planning_input: PlanningInput,
    proposal: PlanProposal,
    *,
    run_id: str,
    receipt: GoalBootstrapReceipt,
    plan: GoalBootstrapPlannerDependencyPlan,
    request_hash: str,
    response_hash: str,
    response: ModelResponse,
) -> str:
    evidence_store = ProductionPlanningEvidenceStore(runtime)
    verification_id = new_id(IdKind.VERIFICATION)
    now = utc_now()
    evidence = {
        "goal_bootstrap_id": receipt.bootstrap_id,
        "planner_dependency_plan_hash": plan.plan_hash,
        "planning_input_id": planning_input.planning_input_id,
        "planning_input_hash": planning_input.content_hash,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "proposal_id": proposal.proposal_id,
        "proposal_hash": proposal.content_hash,
        "selected_profile_id": plan.selection.selected_profile_id,
        "model_id": response.model_id,
        "model_hash": response.model_hash,
        "materialized": False,
    }
    metrics = {
        "response_bytes": len(response.text.encode("utf-8")),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "model_calls": 1,
    }
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        exact_input = evidence_store._load_input_conn(conn, planning_input.planning_input_id)
        if exact_input != planning_input:
            raise GoalBootstrapPlannerError("PlanningInput changed before proposal publication")
        try:
            proposal.bind(exact_input)
        except ProductionPlanningModelError as exc:
            raise GoalBootstrapPlannerError("PlanProposal failed exact PlanningInput binding") from exc
        evidence_store._insert_evidence(
            conn,
            "plan_proposals",
            "proposal_id",
            proposal.proposal_id,
            proposal.content_hash,
            proposal.to_dict(),
            ("planning_input_id",),
            (proposal.planning_input_id,),
        )
        conn.execute(
            """INSERT INTO verifications(
                   id, target_type, target_id, verification_type, verifier,
                   status, evidence_json, metrics_json, run_id, created_at
               ) VALUES (?, 'RUN', ?, 'planner-generation', ?, 'PASS', ?, ?, ?, ?)""",
            (
                verification_id,
                run_id,
                _PLANNER_GENERATION_VERIFIER,
                _json(evidence),
                _json(metrics),
                run_id,
                now,
            ),
        )
        runtime.store._append_event(
            conn,
            "RUN",
            run_id,
            "VERIFICATION_RECORDED",
            None,
            "PASS",
            None,
            "SYSTEM",
            None,
            {
                "verification_id": verification_id,
                "verification_type": "planner-generation",
            },
            now,
        )
    return verification_id


def _invoke_reserved_planner(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    environment: GoalBootstrapPlannerEnvironment,
    scheduled: ScheduledModel,
    plan: GoalBootstrapPlannerDependencyPlan,
    run_id: str,
) -> PlanProposal:
    _validate_marker_run(runtime, run_id, plan)
    _record_selection(runtime, run_id, receipt, plan, scheduled)
    instance: object | None = None
    try:
        instance = environment.runtime_dispatch_loader.load(scheduled.profile, scheduled.lease)
        if not isinstance(instance, ModelAdapter):
            raise GoalBootstrapPlannerError("protected Goal-planner runtime did not load a ModelAdapter")
        if instance.model_id != scheduled.profile.model_id:
            raise GoalBootstrapPlannerError("loaded Goal-planner model identity drifted")
        request, request_hash = _planner_request(runtime, planning_input, run_id)
        response = instance.generate(request)
        if not isinstance(response, ModelResponse) or not response.model_id:
            raise GoalBootstrapPlannerError("Goal Planner returned an invalid response envelope")
        if response.model_id != scheduled.profile.model_id:
            raise GoalBootstrapPlannerError("Goal Planner response model identity drifted")
        if (
            response.model_hash is not None
            and scheduled.profile.model_hash is not None
            and response.model_hash != scheduled.profile.model_hash
        ):
            raise GoalBootstrapPlannerError("Goal Planner response model hash drifted")
        proposal = parse_plan_proposal(response.text, planning_input=planning_input)
        response_hash = _text_hash(response.text)
        _publish_proposal_and_generation_proof(
            runtime,
            planning_input,
            proposal,
            run_id=run_id,
            receipt=receipt,
            plan=plan,
            request_hash=request_hash,
            response_hash=response_hash,
            response=response,
        )
        finish_run(
            runtime.store,
            run_id,
            RunStatus.SUCCEEDED,
            input_token_count=response.input_tokens,
            output_token_count=response.output_tokens,
        )
        return proposal
    except Exception as exc:
        try:
            run = runtime.get_run(run_id)
            if run["status"] == RunStatus.RUNNING.value:
                finish_run(
                    runtime.store,
                    run_id,
                    RunStatus.FAILED,
                    failure_reason=f"{type(exc).__name__}: {exc}"[:1000],
                )
        except Exception:
            pass
        raise
    finally:
        if instance is not None:
            environment.runtime_dispatch_loader.unload(instance)


def _verification_evidence(row: dict[str, object]) -> dict[str, object]:
    return _decode_json_object(row.get("evidence_json"), label="planner verification evidence")


def _selection_from_verification(row: dict[str, object]) -> GoalBootstrapPlannerSelection:
    return _selection_from_evidence(_verification_evidence(row))


def _matching_verifications(
    runtime: OriginForgeRuntime,
    run_id: str,
    verification_type: str,
) -> list[dict[str, object]]:
    rows = runtime.list_verifications("RUN", run_id)
    return [
        row
        for row in rows
        if row.get("verification_type") == verification_type
        and row.get("verifier") == _PLANNER_GENERATION_VERIFIER
        and row.get("status") == "PASS"
        and row.get("run_id") == run_id
    ]


def _interrupt_started(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    reason: str,
) -> GoalBootstrapReceipt:
    try:
        return interrupt_goal_bootstrap(
            runtime,
            receipt.bootstrap_id,
            receipt.revision,
            GoalBootstrapStage.PLANNER_STARTED,
            reason[:4096],
        )
    except StaleRevision:
        return read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)


def _interrupt_run_if_running(runtime: OriginForgeRuntime, run_id: str, reason: str) -> None:
    try:
        run = runtime.get_run(run_id)
        if run["status"] == RunStatus.RUNNING.value:
            finish_run(
                runtime.store,
                run_id,
                RunStatus.INTERRUPTED,
                failure_reason=reason[:1000],
            )
    except Exception:
        pass


def _load_returned(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
) -> GoalBootstrapPlannerResult:
    if (
        receipt.planner_run_id is None
        or receipt.planner_dependency_plan_hash is None
        or receipt.plan_proposal_id is None
        or receipt.plan_proposal_hash is None
    ):
        raise GoalBootstrapPlannerError("planner return checkpoint is incomplete")
    proposal = ProductionPlanningEvidenceStore(runtime).load_proposal(receipt.plan_proposal_id)
    if proposal.content_hash != receipt.plan_proposal_hash:
        raise GoalBootstrapPlannerError("planner return proposal hash drifted")
    return GoalBootstrapPlannerResult(
        receipt=receipt,
        proposal=proposal,
        planner_run_id=receipt.planner_run_id,
        planner_dependency_plan_hash=receipt.planner_dependency_plan_hash,
        recovered=True,
    )


def _recover_from_marker(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    environment: GoalBootstrapPlannerEnvironment,
    marker: dict[str, object],
) -> GoalBootstrapPlannerResult:
    run_id = marker.get("target_id")
    if not isinstance(run_id, str) or marker.get("target_type") != "RUN" or marker.get("run_id") != run_id:
        raise GoalBootstrapPlannerError("planner dispatch marker target binding is invalid")
    marker_evidence = _verification_evidence(marker)
    selection = _selection_from_evidence(marker_evidence)
    environment.validate_selection(selection)
    plan = environment.dependency_plan(receipt, planning_input, selection)
    dependency_hash = receipt.planner_dependency_plan_hash
    if dependency_hash is None or plan.plan_hash != dependency_hash:
        raise GoalBootstrapPlannerError("reconstructed planner dependency plan drifted")
    _validate_dispatch_marker(marker_evidence, receipt, planning_input, plan)
    run = _validate_marker_run(runtime, run_id, plan)

    selection_rows = _matching_verifications(runtime, run_id, "model-resource-selection")
    generation_rows = _matching_verifications(runtime, run_id, "planner-generation")
    if len(generation_rows) != 1:
        raise GoalBootstrapPlannerError(
            "exact original Planner result cannot be proven without one generation verification"
        )
    if len(selection_rows) != 1:
        raise GoalBootstrapPlannerError(
            "exact original Planner selection cannot be proven without one selection verification"
        )
    selection_evidence = _verification_evidence(selection_rows[0])
    if (
        selection_evidence.get("goal_bootstrap_id") != receipt.bootstrap_id
        or selection_evidence.get("planner_dependency_plan_hash") != dependency_hash
    ):
        raise GoalBootstrapPlannerError("planner selection verification escaped GOALBOOT binding")
    proven_selection = _selection_from_verification(selection_rows[0])
    if proven_selection != selection:
        raise GoalBootstrapPlannerError("planner selection verification drifted from dispatch marker")

    generation = _verification_evidence(generation_rows[0])
    request, request_hash = _planner_request(runtime, planning_input, run_id)
    del request
    if (
        generation.get("goal_bootstrap_id") != receipt.bootstrap_id
        or generation.get("planner_dependency_plan_hash") != dependency_hash
        or generation.get("planning_input_id") != planning_input.planning_input_id
        or generation.get("planning_input_hash") != planning_input.content_hash
        or generation.get("request_hash") != request_hash
        or generation.get("selected_profile_id") != selection.selected_profile_id
        or generation.get("model_id") != selection.model_id
    ):
        raise GoalBootstrapPlannerError("planner generation verification drifted from frozen attempt")
    if generation.get("model_hash") not in (None, selection.model_hash):
        raise GoalBootstrapPlannerError("planner generation model hash drifted")
    proposal_id = generation.get("proposal_id")
    proposal_hash = generation.get("proposal_hash")
    if not isinstance(proposal_id, str) or not _digest(proposal_hash):
        raise GoalBootstrapPlannerError("planner generation proposal binding is invalid")
    proposal = ProductionPlanningEvidenceStore(runtime).load_proposal(proposal_id)
    if (
        proposal.content_hash != proposal_hash
        or proposal.planning_input_id != planning_input.planning_input_id
    ):
        raise GoalBootstrapPlannerError("persisted PlanProposal escaped frozen Planner input")

    if run["status"] == RunStatus.RUNNING.value:
        metrics_raw = generation_rows[0].get("metrics_json")
        metrics = _decode_json_object(metrics_raw, label="planner generation metrics")
        input_tokens = metrics.get("input_tokens")
        output_tokens = metrics.get("output_tokens")
        finish_run(
            runtime.store,
            run_id,
            RunStatus.SUCCEEDED,
            input_token_count=input_tokens if isinstance(input_tokens, int) else None,
            output_token_count=output_tokens if isinstance(output_tokens, int) else None,
        )
    elif run["status"] != RunStatus.SUCCEEDED.value:
        raise GoalBootstrapPlannerError("planner Run terminal state conflicts with durable result proof")

    try:
        returned = checkpoint_goal_bootstrap_planner_returned(
            runtime,
            receipt.bootstrap_id,
            receipt.revision,
            planner_run_id=run_id,
            plan_proposal_id=proposal.proposal_id,
            plan_proposal_hash=proposal.content_hash,
        )
    except StaleRevision:
        current = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
        if (
            current.stage is not GoalBootstrapStage.PLANNER_RETURNED
            or current.planner_run_id != run_id
            or current.plan_proposal_id != proposal.proposal_id
            or current.plan_proposal_hash != proposal.content_hash
        ):
            raise
        returned = current
    return GoalBootstrapPlannerResult(
        receipt=returned,
        proposal=proposal,
        planner_run_id=run_id,
        planner_dependency_plan_hash=dependency_hash,
        recovered=True,
    )


def _recover_started(
    runtime: OriginForgeRuntime,
    receipt: GoalBootstrapReceipt,
    planning_input: PlanningInput,
    environment: GoalBootstrapPlannerEnvironment,
) -> GoalBootstrapPlannerResult:
    dependency_hash = receipt.planner_dependency_plan_hash
    if dependency_hash is None or receipt.planner_run_id is not None:
        interrupted = _interrupt_started(
            runtime,
            receipt,
            "PLANNER_STARTED violates frozen dependency/Run schema",
        )
        raise GoalBootstrapPlannerInterrupted(interrupted.terminal_reason or "planner recovery interrupted")

    try:
        markers = _dispatch_marker_rows(runtime, receipt.bootstrap_id)
        if markers:
            return _recover_from_marker(runtime, receipt, planning_input, environment, markers[0])

        candidate_run_id = new_id(IdKind.RUN)
        scheduled: ScheduledModel | None = None
        try:
            scheduled = environment.scheduling.scheduler.acquire(candidate_run_id, environment.policy)
            selection = environment.selection_from_scheduled(scheduled)
            plan = environment.dependency_plan(receipt, planning_input, selection)
            if plan.plan_hash != dependency_hash:
                raise GoalBootstrapPlannerError("planner dependency plan changed before safe dispatch recovery")
            run_id, created = _claim_or_load_dispatch_marker(
                runtime,
                receipt,
                planning_input,
                plan,
                candidate_run_id,
            )
            if not created:
                marker_rows = _dispatch_marker_rows(runtime, receipt.bootstrap_id)
                if len(marker_rows) != 1:
                    raise GoalBootstrapPlannerError("planner dispatch marker race did not converge")
                return _recover_from_marker(
                    runtime,
                    receipt,
                    planning_input,
                    environment,
                    marker_rows[0],
                )
            proposal = _invoke_reserved_planner(
                runtime,
                receipt,
                planning_input,
                environment,
                scheduled,
                plan,
                run_id,
            )
            try:
                returned = checkpoint_goal_bootstrap_planner_returned(
                    runtime,
                    receipt.bootstrap_id,
                    receipt.revision,
                    planner_run_id=run_id,
                    plan_proposal_id=proposal.proposal_id,
                    plan_proposal_hash=proposal.content_hash,
                )
            except StaleRevision:
                current = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
                if (
                    current.stage is not GoalBootstrapStage.PLANNER_RETURNED
                    or current.planner_run_id != run_id
                    or current.plan_proposal_id != proposal.proposal_id
                    or current.plan_proposal_hash != proposal.content_hash
                ):
                    raise
                returned = current
            return GoalBootstrapPlannerResult(
                receipt=returned,
                proposal=proposal,
                planner_run_id=run_id,
                planner_dependency_plan_hash=dependency_hash,
                recovered=True,
            )
        finally:
            if scheduled is not None:
                environment.scheduling.scheduler.release(scheduled)
    except ModelCapacityUnavailable as exc:
        raise GoalBootstrapPlannerError("Goal-planner capacity is unavailable before model dispatch") from exc
    except GoalBootstrapPlannerInterrupted:
        raise
    except Exception as exc:
        marker_rows = _dispatch_marker_rows(runtime, receipt.bootstrap_id)
        run_id = str(marker_rows[0]["target_id"]) if marker_rows else None
        if run_id is not None:
            _interrupt_run_if_running(runtime, run_id, f"Planner recovery failed closed: {exc}")
        interrupted = _interrupt_started(runtime, receipt, f"Planner recovery failed closed: {exc}")
        if interrupted.stage is GoalBootstrapStage.PLANNER_RETURNED:
            return _load_returned(runtime, interrupted)
        raise GoalBootstrapPlannerInterrupted(
            interrupted.terminal_reason or "Planner recovery failed closed"
        ) from exc


def advance_goal_bootstrap_planner(
    runtime: OriginForgeRuntime,
    bootstrap_id: str,
) -> GoalBootstrapPlannerResult:
    """Advance one governed GOALBOOT through exactly the Planner-return checkpoint.

    PLANNER_STARTED stores only the frozen dependency-plan hash, preserving the
    v12 receipt invariant. The exact taskless Run and selected model are then
    published atomically in a Run-targeted dispatch marker before any model
    request. A started receipt with no marker is safe to resume once; a started
    receipt with a marker but no exact generation proof is never auto-replayed.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    initial = read_goal_bootstrap_receipt(runtime, bootstrap_id)
    try:
        receipt, planning_input = prepare_goal_bootstrap_input(runtime, bootstrap_id)
    except Exception as exc:
        if (
            initial.status is GoalBootstrapStatus.ACTIVE
            and initial.stage is GoalBootstrapStage.PLANNER_STARTED
        ):
            interrupted = _interrupt_started(
                runtime,
                initial,
                f"Planner recovery authority drifted: {exc}",
            )
            raise GoalBootstrapPlannerInterrupted(
                interrupted.terminal_reason or "Planner recovery authority drifted"
            ) from exc
        raise

    if receipt.status is not GoalBootstrapStatus.ACTIVE:
        raise GoalBootstrapPlannerError(
            f"GOALBOOT is terminal with status {receipt.status.value}"
        )
    if receipt.stage in (
        GoalBootstrapStage.PLANNER_RETURNED,
        GoalBootstrapStage.PLAN_AUDITED,
        GoalBootstrapStage.MATERIALIZED,
        GoalBootstrapStage.PREPPOL_PUBLISHED,
    ):
        return _load_returned(runtime, receipt)

    environment = assemble_goal_bootstrap_planner_environment(runtime, receipt, planning_input)
    if receipt.stage is GoalBootstrapStage.PLANNER_STARTED:
        return _recover_started(runtime, receipt, planning_input, environment)
    if receipt.stage is not GoalBootstrapStage.PLANNING_INPUT_PUBLISHED:
        raise GoalBootstrapPlannerError(
            f"GOALBOOT cannot invoke Planner from stage {receipt.stage.value}"
        )

    candidate_run_id = new_id(IdKind.RUN)
    scheduled: ScheduledModel | None = None
    started: GoalBootstrapReceipt | None = None
    marker_created = False
    try:
        scheduled = environment.scheduling.scheduler.acquire(candidate_run_id, environment.policy)
        selection = environment.selection_from_scheduled(scheduled)
        plan = environment.dependency_plan(receipt, planning_input, selection)
        try:
            started = _checkpoint_planner_started(
                runtime,
                receipt,
                planner_dependency_plan_hash=plan.plan_hash,
            )
        except StaleRevision:
            current = read_goal_bootstrap_receipt(runtime, receipt.bootstrap_id)
            if (
                current.stage is not GoalBootstrapStage.PLANNER_STARTED
                or current.status is not GoalBootstrapStatus.ACTIVE
                or current.planner_dependency_plan_hash != plan.plan_hash
                or current.planner_run_id is not None
            ):
                raise
            started = current

        run_id, marker_created = _claim_or_load_dispatch_marker(
            runtime,
            started,
            planning_input,
            plan,
            candidate_run_id,
        )
        if not marker_created:
            return _recover_started(runtime, started, planning_input, environment)

        proposal = _invoke_reserved_planner(
            runtime,
            started,
            planning_input,
            environment,
            scheduled,
            plan,
            run_id,
        )
        try:
            returned = checkpoint_goal_bootstrap_planner_returned(
                runtime,
                started.bootstrap_id,
                started.revision,
                planner_run_id=run_id,
                plan_proposal_id=proposal.proposal_id,
                plan_proposal_hash=proposal.content_hash,
            )
        except StaleRevision:
            current = read_goal_bootstrap_receipt(runtime, started.bootstrap_id)
            if (
                current.stage is not GoalBootstrapStage.PLANNER_RETURNED
                or current.planner_run_id != run_id
                or current.plan_proposal_id != proposal.proposal_id
                or current.plan_proposal_hash != proposal.content_hash
            ):
                raise
            returned = current
        return GoalBootstrapPlannerResult(
            receipt=returned,
            proposal=proposal,
            planner_run_id=run_id,
            planner_dependency_plan_hash=plan.plan_hash,
            recovered=False,
        )
    except BaseException as exc:
        if not isinstance(exc, Exception):
            raise
        if started is None:
            if isinstance(exc, ModelCapacityUnavailable):
                raise GoalBootstrapPlannerError(
                    "Goal-planner capacity is unavailable before Planner start"
                ) from exc
            raise
        if marker_created:
            return _recover_started(runtime, started, planning_input, environment)
        return _recover_started(runtime, started, planning_input, environment)
    finally:
        if scheduled is not None:
            environment.scheduling.scheduler.release(scheduled)
