from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_execution_read as execution_read_module
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
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import (
    begin_dispatch_execution,
    interrupt_dispatch_execution,
    mark_dispatch_execution_returned,
)
from origin_forge.production_dispatch_execution_read import (
    DispatchExecutionCurrentnessStatus,
    inspect_dispatch_execution_currentness_readonly,
    read_dispatch_execution,
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


class ProductionDispatchExecutionReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase36-execution-read")
        self.goal_id = self.runtime.create_goal("inspect one started execution")
        self.flow_id = self.runtime.create_flow(self.goal_id)
        self.task_id = self.runtime.create_task(
            self.flow_id,
            "change code through bounded retry",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

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
        self._write_execution_config()
        self.started = self._begin_without_execution_calls()

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
        return acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )

    def _write_execution_config(self) -> None:
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

    def _begin_without_execution_calls(self):
        with (
            patch.object(ManagedLlamaCppCpuLoader, "load", side_effect=AssertionError("model load")),
            patch.object(ResourceScheduler, "acquire", side_effect=AssertionError("resource acquire")),
            patch.object(GitWorkspaceManager, "create", side_effect=AssertionError("workspace create")),
            patch.object(OriginForgeRuntime, "start_run", side_effect=AssertionError("run start")),
            patch.object(BoundedRetryPolicy, "drive", side_effect=AssertionError("policy drive")),
            patch("subprocess.Popen", side_effect=AssertionError("process start")),
        ):
            return begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)

    def _state_snapshot(self):
        result = {}
        state = self.runtime.state_dir
        for path in sorted(state.rglob("*")):
            relative = path.relative_to(state).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", path.readlink().as_posix())
            elif path.is_file():
                result[relative] = ("file", path.read_bytes())
            elif path.is_dir():
                result[relative] = ("dir", None)
        return result

    def test_started_receipt_is_current_and_inspection_is_byte_stable(self) -> None:
        before = self._state_snapshot()
        with (
            patch.object(ManagedLlamaCppCpuLoader, "load", side_effect=AssertionError("model load")),
            patch.object(ResourceScheduler, "acquire", side_effect=AssertionError("resource acquire")),
            patch.object(BoundedRetryPolicy, "drive", side_effect=AssertionError("policy drive")),
            patch("subprocess.Popen", side_effect=AssertionError("process start")),
        ):
            receipt = read_dispatch_execution(
                self.runtime,
                self.started.execution.execution_id,
            )
            currentness = inspect_dispatch_execution_currentness_readonly(
                self.runtime,
                self.started.execution.execution_id,
            )
        self.assertEqual(receipt, self.started.execution)
        self.assertEqual(
            currentness.status,
            DispatchExecutionCurrentnessStatus.CURRENT_STARTED,
        )
        self.assertIsNone(currentness.detail)
        self.assertEqual(self._state_snapshot(), before)
        self.assertFalse((self.runtime.state_dir / "origin-forge.db-wal").exists())
        self.assertFalse((self.runtime.state_dir / "origin-forge.db-shm").exists())

    def test_phase14_resource_drift_is_stale_dependency_plan_only(self) -> None:
        config_path = self.runtime.state_dir / "config.toml"
        original = config_path.read_text(encoding="utf-8")
        changed = original.replace(
            'resources = { cpu_slots = 2, ram_mib = 4096 }',
            'resources = { cpu_slots = 3, ram_mib = 4096 }',
        )
        self.assertNotEqual(changed, original)
        config_path.write_text(changed, encoding="utf-8")
        database_before = self.runtime.store.db_path.read_bytes()
        currentness = inspect_dispatch_execution_currentness_readonly(
            self.runtime,
            self.started.execution.execution_id,
        )
        self.assertEqual(
            currentness.status,
            DispatchExecutionCurrentnessStatus.STALE_DEPENDENCY_PLAN,
        )
        self.assertEqual(self.runtime.store.db_path.read_bytes(), database_before)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.READY.value)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_task_drift_is_stale_binding_without_changing_receipt(self) -> None:
        receipt_before = read_dispatch_execution(
            self.runtime,
            self.started.execution.execution_id,
        )
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.RUNNING,
            expected_revision=1,
        )
        currentness = inspect_dispatch_execution_currentness_readonly(
            self.runtime,
            self.started.execution.execution_id,
        )
        self.assertEqual(
            currentness.status,
            DispatchExecutionCurrentnessStatus.STALE_BINDING,
        )
        self.assertEqual(
            read_dispatch_execution(self.runtime, self.started.execution.execution_id),
            receipt_before,
        )
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_consumed_claim_relation_tamper_is_stale_claim(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE dispatch_claims SET terminal_reason = ? WHERE claim_id = ?",
                ("tampered consumed relation", self.claim.claim_id),
            )
        currentness = inspect_dispatch_execution_currentness_readonly(
            self.runtime,
            self.started.execution.execution_id,
        )
        self.assertEqual(
            currentness.status,
            DispatchExecutionCurrentnessStatus.STALE_CLAIM,
        )
        self.assertIn("reason", currentness.detail or "")

    def test_terminal_receipts_remain_historical_and_not_pre_dispatch_current(self) -> None:
        returned = mark_dispatch_execution_returned(
            self.runtime,
            self.started.execution.execution_id,
            0,
            "bounded invocation returned",
        )
        currentness = inspect_dispatch_execution_currentness_readonly(
            self.runtime,
            returned.execution_id,
        )
        self.assertEqual(currentness.status, DispatchExecutionCurrentnessStatus.RETURNED)

    def test_interrupted_receipt_is_historical(self) -> None:
        interrupted = interrupt_dispatch_execution(
            self.runtime,
            self.started.execution.execution_id,
            0,
            "explicit pre-dispatch interruption",
        )
        currentness = inspect_dispatch_execution_currentness_readonly(
            self.runtime,
            interrupted.execution_id,
        )
        self.assertEqual(
            currentness.status,
            DispatchExecutionCurrentnessStatus.INTERRUPTED,
        )

    def test_reader_source_has_no_writer_or_execution_authority(self) -> None:
        source = inspect.getsource(execution_read_module)
        self.assertNotIn("runtime.store.session", source)
        self.assertNotIn("BEGIN IMMEDIATE", source)
        for forbidden_text in (
            "INSERT INTO",
            "UPDATE dispatch_",
            "DELETE FROM",
            "subprocess",
            "ManagedLlamaCppCpuLoader",
            "BoundedRetryPolicy",
            "GitWorkspaceManager",
        ):
            self.assertNotIn(forbidden_text, source)
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
            "transition_task",
            "create",
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
        signature = inspect.signature(inspect_dispatch_execution_currentness_readonly)
        self.assertEqual(tuple(signature.parameters), ("runtime", "execution_id"))


if __name__ == "__main__":
    unittest.main()
