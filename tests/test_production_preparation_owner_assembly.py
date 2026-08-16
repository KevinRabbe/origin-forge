from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_preparation_assembly as assembly_module
from origin_forge.managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_assembly import (
    ProductionPreparationAssemblyError,
    assemble_preparation_planner_dependencies,
)
from origin_forge.production_preparation_owner import (
    ProductionPreparationOwnerError,
    build_builtin_preparation_owner_registry,
    require_current_preparation_owner,
)
from origin_forge.production_preparation_policy_store import create_preparation_policy_binding
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.resource_scheduler import ResourceScheduler
from origin_forge.runtime import OriginForgeRuntime


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class PreparationOwnerAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase39c-owner-assembly")
        self.goal = self.runtime.create_goal("prepare one bounded code task")

        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)
        self.planning_input = freeze_governed_planning_input(
            self.runtime,
            self.goal,
            capability_store=self.capability_store,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Prepare one bounded code task.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement the bounded change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        audit = audit_plan(self.planning_input, proposal)
        evidence = ProductionPlanningEvidenceStore(self.runtime)
        evidence.publish_input(self.planning_input)
        evidence.publish_proposal(proposal)
        evidence.publish_audit(audit)
        self.materialization = evidence.materialize(
            planning_input_id=self.planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(self.dispatch_catalog)
        self.policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=self.materialization.materialization_id,
            capability_catalog_id=self.catalog.catalog_id,
            capability_routing_policy_id=self.routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=self.dispatch_catalog.dispatch_catalog_id,
        )
        self._write_model_config()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_model_config(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []

[code_intelligence]
lsp_servers = []

[resources]
enabled = true
cpu_slots = 8
ram_mib = 16384
max_active_leases = 8
gpus = []

[models]
profiles = [
  { profile_id = "strong", role = "coder_strong", model_id = "test-model", model_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime_id = "llamacpp-cpu", resources = { cpu_slots = 2, ram_mib = 4096 } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "strong", fallback_profile_ids = [] }
]

[model_runtimes]
providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18081, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
''',
            encoding="utf-8",
        )

    def _state_snapshot(self):
        result = {}
        for path in sorted(self.runtime.state_dir.rglob("*")):
            relative = path.relative_to(self.runtime.state_dir).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", path.readlink().as_posix())
            elif path.is_file():
                result[relative] = ("file", path.read_bytes())
            elif path.is_dir():
                result[relative] = ("dir", None)
        return result

    def test_builtin_owner_is_deterministic_inert_and_preserves_code_owner(self) -> None:
        first = build_builtin_preparation_owner_registry()
        second = build_builtin_preparation_owner_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.descriptors), 3)
        owner = first.owner("originforge.preparation.work-order-planner@1")
        self.assertEqual(owner.owner_id, "originforge.preparation.work-order-planner@1")
        self.assertEqual(owner.planner_contract_id, "BoundedProductionWorkOrderPlanner.propose@1")
        self.assertEqual(owner.supported_adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(owner.supported_dispatch_contract_id, "code.bounded-retry@1")
        self.assertEqual(owner.model_strategy_roles, (ModelRole.CODER_STRONG,))
        self.assertEqual(owner.policy_role_names, ("CODER_STRONG",))
        simulation_owner = first.owner(
            "originforge.preparation.simulation-work-order-planner@1"
        )
        self.assertEqual(
            simulation_owner.planner_contract_id,
            "BoundedProductionWorkOrderPlanner.propose@1",
        )
        self.assertEqual(
            simulation_owner.supported_adapter_id,
            "originforge.simulation.deterministic",
        )
        self.assertEqual(
            simulation_owner.supported_dispatch_contract_id,
            "simulation.deterministic@1",
        )
        self.assertEqual(
            simulation_owner.model_strategy_roles,
            (ModelRole.CODER_STRONG,),
        )
        pixelorama_owner = first.owner(
            "originforge.preparation.pixelorama-spritesheet-export-planner@1"
        )
        self.assertEqual(pixelorama_owner.supported_adapter_id, "originforge.pixelorama.export")
        self.assertEqual(pixelorama_owner.supported_dispatch_contract_id, "pixelorama.spritesheet-export@1")
        self.assertEqual(pixelorama_owner.model_strategy_roles, (ModelRole.CODER_STRONG,))
        forbidden = {
            "callable",
            "import_path",
            "endpoint",
            "executable",
            "argv",
            "environment",
            "secret",
            "model_path",
            "process",
            "sandbox",
            "workspace",
        }
        self.assertTrue(forbidden.isdisjoint(owner.to_dict()))
        self.assertTrue(forbidden.isdisjoint(simulation_owner.to_dict()))
        self.assertTrue(forbidden.isdisjoint(pixelorama_owner.to_dict()))

    def test_policy_owner_fields_are_derived_and_current(self) -> None:
        owner = require_current_preparation_owner(
            self.policy,
            self.dispatch_catalog,
        )
        self.assertEqual(self.policy.preparation_owner_id, owner.owner_id)
        self.assertEqual(self.policy.preparation_owner_fingerprint, owner.fingerprint)
        self.assertEqual(self.policy.planner_request_version, owner.planner_request_version)
        self.assertEqual(self.policy.planner_contract_id, owner.planner_contract_id)
        self.assertEqual(self.policy.model_strategy_roles, owner.policy_role_names)
        with self.assertRaisesRegex(
            ProductionPreparationOwnerError,
            "not current",
        ):
            require_current_preparation_owner(
                replace(self.policy, preparation_owner_fingerprint="0" * 64),
                self.dispatch_catalog,
            )

    def test_lazy_assembler_freezes_exact_model_runtime_plan_without_authority_crossing(self) -> None:
        before = self._state_snapshot()
        runs_before = self.runtime.list_runs()
        with (
            patch.object(ResourceScheduler, "acquire", side_effect=AssertionError("resource acquire")),
            patch.object(ResourceScheduler, "try_acquire", side_effect=AssertionError("resource try_acquire")),
            patch.object(ManagedLlamaCppCpuLoader, "load", side_effect=AssertionError("model load")),
            patch("subprocess.Popen", side_effect=AssertionError("process start")),
        ):
            assembled = assemble_preparation_planner_dependencies(
                self.runtime,
                self.policy,
            )
        self.assertEqual(self._state_snapshot(), before)
        self.assertEqual(self.runtime.list_runs(), runs_before)
        self.assertEqual(assembled.plan.preparation_policy_id, self.policy.preparation_policy_id)
        self.assertEqual(assembled.plan.preparation_policy_hash, self.policy.content_hash)
        self.assertEqual(
            assembled.plan.preparation_owner_id,
            "originforge.preparation.work-order-planner@1",
        )
        self.assertEqual(assembled.plan.model_strategy_roles, ("coder_strong",))
        self.assertEqual(
            assembled.plan.model_policy_chain,
            (("coder_strong", "strong", ()),),
        )
        self.assertEqual(assembled.plan.model_profile_ids, ("strong",))
        self.assertEqual(assembled.plan.runtime_ids, ("llamacpp-cpu",))
        self.assertRegex(assembled.plan.resource_model_config_hash, r"^[0-9a-f]{64}$")
        self.assertRegex(assembled.plan.model_runtime_config_fingerprint, r"^[0-9a-f]{64}$")
        self.assertRegex(assembled.plan.plan_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(assembled.model.model_id, "test-model")
        self.assertEqual(assembled.model_scheduling.resources.status().active_leases, ())
        self.assertEqual(assembled.runtime_dispatch_loader.active_runtime_ids(), ())
        self.assertEqual(len(assembled.managed_loaders), 1)
        self.assertEqual(assembled.managed_loaders[0].active_instance_count(), 0)

        second = assemble_preparation_planner_dependencies(self.runtime, self.policy)
        self.assertEqual(second.plan.to_dict(), assembled.plan.to_dict())
        self.assertEqual(second.plan.plan_hash, assembled.plan.plan_hash)
        self.assertEqual(second.model_scheduling.resources.status().active_leases, ())
        self.assertEqual(second.runtime_dispatch_loader.active_runtime_ids(), ())
        self.assertEqual(self._state_snapshot(), before)

    def test_model_policy_semantics_change_dependency_plan_identity(self) -> None:
        first = assemble_preparation_planner_dependencies(self.runtime, self.policy)
        config_path = self.runtime.state_dir / "config.toml"
        raw = config_path.read_text(encoding="utf-8")
        changed = raw.replace(
            'resources = { cpu_slots = 2, ram_mib = 4096 }',
            'resources = { cpu_slots = 3, ram_mib = 4096 }',
        )
        self.assertNotEqual(changed, raw)
        config_path.write_text(changed, encoding="utf-8")
        second = assemble_preparation_planner_dependencies(self.runtime, self.policy)
        self.assertNotEqual(
            first.plan.resource_model_config_hash,
            second.plan.resource_model_config_hash,
        )
        self.assertNotEqual(first.plan.plan_hash, second.plan.plan_hash)
        self.assertEqual(first.plan.model_runtime_config_fingerprint, second.plan.model_runtime_config_fingerprint)

    def test_missing_provider_or_forged_owner_fails_before_model_authority(self) -> None:
        config_path = self.runtime.state_dir / "config.toml"
        configured = config_path.read_text(encoding="utf-8")
        without_provider = configured.replace(
            '''providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18081, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]''',
            "providers = []",
        )
        config_path.write_text(without_provider, encoding="utf-8")
        with self.assertRaisesRegex(
            ProductionPreparationAssemblyError,
            "no protected runtime provider",
        ):
            assemble_preparation_planner_dependencies(self.runtime, self.policy)

        config_path.write_text(configured, encoding="utf-8")
        with self.assertRaisesRegex(
            ProductionPreparationAssemblyError,
            "not current code-owned",
        ):
            assemble_preparation_planner_dependencies(
                self.runtime,
                replace(self.policy, preparation_owner_fingerprint="0" * 64),
            )

    def test_assembler_source_stops_before_planner_execution_authority(self) -> None:
        source = inspect.getsource(assembly_module)
        tree = ast.parse(source)
        forbidden_calls = {
            "generate",
            "propose",
            "acquire",
            "try_acquire",
            "hold",
            "use",
            "load",
            "unload",
            "create_run",
            "finish_run",
            "Popen",
            "create_workspace",
            "drive",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue(
            all("sandbox" not in module and "workspace" not in module for module in imported_modules)
        )
        signature = inspect.signature(assemble_preparation_planner_dependencies)
        self.assertEqual(tuple(signature.parameters), ("runtime", "policy"))
        for forbidden in (
            "profile",
            "provider",
            "runtime_id",
            "endpoint",
            "loader",
            "model",
            "sandbox",
            "workspace",
        ):
            self.assertNotIn(forbidden, signature.parameters)


if __name__ == "__main__":
    unittest.main()
