from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_execution_assembly as assembly_module
from origin_forge.managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from origin_forge.orchestration_policy import BoundedRetryPolicy
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_assembly import (
    ProductionExecutionAssemblyError,
    assemble_production_execution_dependencies,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.resource_scheduler import ResourceScheduler
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus
from origin_forge.workspaces import GitWorkspaceManager


class ProductionExecutionAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase36-assembly")
        self.goal_id = self.runtime.create_goal("assemble one governed execution")
        self.flow_id = self.runtime.create_flow(self.goal_id)
        self.task_id = self.runtime.create_task(
            self.flow_id,
            "change code through bounded retry",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.READY.value)

        self.catalog = build_builtin_capability_catalog()
        self.routing_policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.routing_policy, self.catalog)
        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.catalog)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.resolver_registry = build_dispatch_input_resolver_registry()
        self.binder_registry = build_builtin_dispatch_binder_registry()
        self.dispatch_store = ProductionDispatchStore(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
        )
        self.claim = self._claim_current_chain()
        self._write_executable_config()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _claim_current_chain(self):
        route = self.capability_store.resolve_and_publish(
            self.task_id,
            self.catalog.catalog_id,
            self.routing_policy.routing_policy_id,
        )
        work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        )
        audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.work_order_store.publish_work_order(work_order)
        self.work_order_store.publish_audit(audit)
        bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolver_registry,
            work_order.work_order_id,
            audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            binding,
        )
        self.dispatch_store.publish_input_resolution(bundle)
        self.dispatch_store.publish_binding(binding)
        self.dispatch_store.publish_audit(binding_audit)
        claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )
        self.assertEqual(
            inspect_dispatch_claim_currentness_readonly(
                self.runtime,
                claim.claim_id,
            ).status,
            DispatchClaimCurrentnessStatus.CURRENT_ACTIVE,
        )
        return claim

    def _write_executable_config(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "podman"
image = "origin-forge-test-sandbox:phase36"
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
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18080, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
''',
            encoding="utf-8",
        )

    def _state_snapshot(self):
        state = self.runtime.state_dir
        result = {}
        for path in sorted(state.rglob("*")):
            relative = path.relative_to(state).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", path.readlink().as_posix())
            elif path.is_file():
                result[relative] = ("file", path.read_bytes())
            elif path.is_dir():
                result[relative] = ("dir", None)
        return result

    def test_current_claim_assembles_exact_lazy_dependencies_without_mutation(self) -> None:
        before = self._state_snapshot()
        task_before = self.runtime.get_task(self.task_id)
        runs_before = self.runtime.list_runs(self.task_id)

        with (
            patch.object(ManagedLlamaCppCpuLoader, "load", side_effect=AssertionError("model load")),
            patch.object(ResourceScheduler, "acquire", side_effect=AssertionError("resource acquire")),
            patch.object(GitWorkspaceManager, "create", side_effect=AssertionError("workspace create")),
            patch.object(OriginForgeRuntime, "start_run", side_effect=AssertionError("run start")),
            patch.object(BoundedRetryPolicy, "drive", side_effect=AssertionError("policy drive")),
            patch("subprocess.Popen", side_effect=AssertionError("process start")),
        ):
            assembled = assemble_production_execution_dependencies(
                self.runtime,
                self.claim.claim_id,
            )

        self.assertEqual(assembled.plan.claim_id, self.claim.claim_id)
        self.assertEqual(assembled.plan.claim_revision, 0)
        self.assertEqual(assembled.plan.task_id, self.task_id)
        self.assertEqual(assembled.plan.task_revision, 1)
        self.assertEqual(
            assembled.plan.owner_id,
            "originforge.execution.bounded-retry@1",
        )
        self.assertEqual(assembled.plan.model_strategy_roles, ("coder_strong",))
        self.assertEqual(assembled.plan.model_profile_ids, ("strong",))
        self.assertEqual(assembled.plan.runtime_ids, ("llamacpp-cpu",))
        self.assertEqual(assembled.plan.config_version, 6)
        self.assertEqual(assembled.plan.sandbox_backend, "podman")
        self.assertRegex(assembled.plan.plan_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(len(assembled.models), 1)
        self.assertEqual(assembled.models[0].model_id, "test-model")
        self.assertEqual(assembled.runtime_registry.runtime_ids(), ("llamacpp-cpu",))
        self.assertEqual(assembled.runtime_dispatch_loader.active_runtime_ids(), ())
        self.assertEqual(assembled.model_scheduling.resources.status().active_leases, ())
        self.assertEqual(len(assembled.managed_loaders), 1)
        self.assertEqual(assembled.managed_loaders[0].active_instance_count(), 0)
        self.assertIs(assembled.bounded_retry_policy.models[0], assembled.models[0])
        self.assertIs(assembled.bounded_retry_policy.workspaces, assembled.workspaces)
        self.assertIs(
            assembled.bounded_retry_policy.sandbox_backend,
            assembled.sandbox_backend,
        )

        second = assemble_production_execution_dependencies(
            self.runtime,
            self.claim.claim_id,
        )
        self.assertEqual(second.plan.to_dict(), assembled.plan.to_dict())
        self.assertEqual(second.plan.plan_hash, assembled.plan.plan_hash)
        self.assertEqual(second.model_scheduling.resources.status().active_leases, ())
        self.assertEqual(second.runtime_dispatch_loader.active_runtime_ids(), ())
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._state_snapshot(), before)

    def test_missing_runtime_binding_and_unconfigured_sandbox_fail_before_authority(self) -> None:
        config_path = self.runtime.state_dir / "config.toml"
        configured = config_path.read_text(encoding="utf-8")

        without_provider = configured.replace(
            '''providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18080, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]''',
            "providers = []",
        )
        config_path.write_text(without_provider, encoding="utf-8")
        with self.assertRaisesRegex(ProductionExecutionAssemblyError, "no protected runtime provider"):
            assemble_production_execution_dependencies(self.runtime, self.claim.claim_id)

        config_path.write_text(
            configured.replace('backend = "podman"', 'backend = "unconfigured"'),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProductionExecutionAssemblyError, "requires an explicitly configured Podman sandbox"):
            assemble_production_execution_dependencies(self.runtime, self.claim.claim_id)

    def test_assembler_source_stops_before_execution_authority(self) -> None:
        source = inspect.getsource(assembly_module)
        tree = ast.parse(source)
        forbidden_calls = {
            "drive",
            "generate",
            "acquire",
            "try_acquire",
            "hold",
            "use",
            "load",
            "unload",
            "start_run",
            "finish_run",
            "create_workspace",
            "available",
            "Popen",
            "run",
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
        constructor = inspect.signature(assemble_production_execution_dependencies)
        self.assertEqual(tuple(constructor.parameters), ("runtime", "claim_id"))
        for forbidden in (
            "owner",
            "models",
            "provider",
            "runtime_id",
            "sandbox",
            "workspaces",
            "argv",
            "endpoint",
            "loader",
            "policy",
        ):
            self.assertNotIn(forbidden, constructor.parameters)


if __name__ == "__main__":
    unittest.main()
