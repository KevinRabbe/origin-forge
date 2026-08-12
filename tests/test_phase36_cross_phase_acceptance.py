from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.managed_llamacpp_loader as loader_module
import origin_forge.model_runtime_config as runtime_config_module
import origin_forge.production_dispatch_execution as execution_module
import origin_forge.production_dispatch_execution_read as execution_read_module
import origin_forge.production_execution_assembly as assembly_module
import origin_forge.production_execution_owner as owner_module
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
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import (
    begin_dispatch_execution,
    interrupt_dispatch_execution,
)
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
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


_CONFIG = '''version = 6
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
'''


class Phase36CrossPhaseAcceptanceTests(unittest.TestCase):
    def test_governed_chain_reaches_terminal_execution_mechanics_without_executor_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("phase36-acceptance")
            goal_id = runtime.create_goal("prove pre-dispatch execution ownership")
            flow_id = runtime.create_flow(goal_id)
            task_id = runtime.create_task(
                flow_id,
                "change code through bounded retry",
                acceptance_criteria=("tests pass",),
                constraints=("bounded",),
                required_capabilities=("code.change",),
            )
            activate_dependency_ready_task(runtime, task_id, 0)
            self.assertEqual(runtime.get_task(task_id)["status"], TaskStatus.READY.value)

            catalog = build_builtin_capability_catalog()
            policy = CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("originforge.code.bounded-retry",),
                allowed_capability_ids=("code.change",),
            )
            capability_store = ProductionCapabilityStore(runtime)
            capability_store.publish_catalog(catalog)
            capability_store.publish_policy(policy, catalog)
            validator_registry = build_builtin_dispatch_validator_registry()
            dispatch_catalog = build_builtin_dispatch_catalog(catalog)
            work_order_store = ProductionWorkOrderStore(
                runtime,
                capability_store,
                validator_registry,
            )
            work_order_store.publish_dispatch_catalog(dispatch_catalog)
            resolver_registry = build_dispatch_input_resolver_registry()
            binder_registry = build_builtin_dispatch_binder_registry()
            dispatch_store = ProductionDispatchStore(
                work_order_store,
                resolver_registry,
                binder_registry,
            )

            route = capability_store.resolve_and_publish(
                task_id,
                catalog.catalog_id,
                policy.routing_policy_id,
            )
            work_order = create_current_work_order(
                runtime,
                capability_store,
                dispatch_catalog,
                validator_registry,
                route.route_decision_id,
                payload={
                    "context_mode": "auto",
                    "context_seed_paths": ["src/example.py"],
                    "structural_context": True,
                },
            )
            work_order_audit = audit_work_order_frozen(
                capability_store,
                dispatch_catalog,
                validator_registry,
                work_order,
            )
            work_order_store.publish_work_order(work_order)
            work_order_store.publish_audit(work_order_audit)
            bundle = create_input_resolution_bundle(
                work_order_store,
                resolver_registry,
                work_order.work_order_id,
                work_order_audit.work_order_audit_id,
            )
            binding = create_dispatch_binding(
                work_order_store,
                resolver_registry,
                binder_registry,
                bundle,
            )
            binding_audit = audit_dispatch_binding_frozen(
                work_order_store,
                resolver_registry,
                binder_registry,
                bundle,
                binding,
            )
            dispatch_store.publish_input_resolution(bundle)
            dispatch_store.publish_binding(binding)
            dispatch_store.publish_audit(binding_audit)
            claim = acquire_dispatch_claim(
                runtime,
                binding.dispatch_binding_id,
                binding_audit.binding_audit_id,
                1,
            )
            runtime.state_dir.joinpath("config.toml").write_text(
                _CONFIG,
                encoding="utf-8",
            )

            task_before = runtime.get_task(task_id)
            runs_before = runtime.list_runs(task_id)
            with runtime.store.session() as conn:
                workspaces_before = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()[0]
                )

            with (
                patch.object(ManagedLlamaCppCpuLoader, "load", side_effect=AssertionError("model load")),
                patch.object(ResourceScheduler, "acquire", side_effect=AssertionError("resource acquire")),
                patch.object(GitWorkspaceManager, "create", side_effect=AssertionError("workspace create")),
                patch.object(OriginForgeRuntime, "start_run", side_effect=AssertionError("run start")),
                patch.object(BoundedRetryPolicy, "drive", side_effect=AssertionError("policy drive")),
                patch("subprocess.Popen", side_effect=AssertionError("process start")),
            ):
                started = begin_dispatch_execution(runtime, claim.claim_id, 0)
                current = inspect_dispatch_execution_currentness_readonly(
                    runtime,
                    started.execution.execution_id,
                )

            self.assertEqual(started.execution.status, DispatchExecutionStatus.STARTED)
            self.assertEqual(
                current.status,
                DispatchExecutionCurrentnessStatus.CURRENT_STARTED,
            )
            consumed = read_dispatch_claim(runtime, claim.claim_id)
            self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
            self.assertEqual(consumed.revision, 1)
            self.assertEqual(
                started.execution.runtime_dependency_plan_hash,
                started.dependencies.plan.plan_hash,
            )
            self.assertEqual(
                started.dependencies.model_scheduling.resources.status().active_leases,
                (),
            )
            self.assertEqual(
                started.dependencies.runtime_dispatch_loader.active_runtime_ids(),
                (),
            )
            self.assertEqual(
                started.dependencies.managed_loaders[0].active_instance_count(),
                0,
            )

            terminal = interrupt_dispatch_execution(
                runtime,
                started.execution.execution_id,
                0,
                "phase36 acceptance stops before production invocation",
            )
            self.assertEqual(terminal.status, DispatchExecutionStatus.INTERRUPTED)
            historical = inspect_dispatch_execution_currentness_readonly(
                runtime,
                terminal.execution_id,
            )
            self.assertEqual(
                historical.status,
                DispatchExecutionCurrentnessStatus.INTERRUPTED,
            )
            self.assertEqual(runtime.get_task(task_id), task_before)
            self.assertEqual(runtime.list_runs(task_id), runs_before)
            with runtime.store.session() as conn:
                self.assertEqual(
                    int(
                        conn.execute(
                            "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                            (task_id,),
                        ).fetchone()[0]
                    ),
                    workspaces_before,
                )
            self.assertFalse((root / "missing" / "llama-server").exists())
            self.assertFalse((root / "missing" / "model.gguf").exists())

    def test_phase36_source_tree_stops_before_bounded_retry_drive(self) -> None:
        modules = (
            owner_module,
            runtime_config_module,
            loader_module,
            assembly_module,
            execution_module,
            execution_read_module,
        )
        for module in modules:
            with self.subTest(module=module.__name__):
                source = inspect.getsource(module)
                self.assertNotIn(".drive(", source)
        self.assertIn("BoundedRetryPolicy(", inspect.getsource(assembly_module))
        self.assertNotIn(".generate(", inspect.getsource(execution_module))
        self.assertNotIn("subprocess", inspect.getsource(execution_read_module))


if __name__ == "__main__":
    unittest.main()
