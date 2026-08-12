from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_execution as execution_module
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
from origin_forge.production_dispatch_claim_read import (
    DispatchClaimCurrentnessStatus,
    inspect_dispatch_claim_currentness_readonly,
    read_dispatch_claim,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import (
    ProductionDispatchExecutionError,
    begin_dispatch_execution,
    interrupt_dispatch_execution,
    mark_dispatch_execution_raised,
    mark_dispatch_execution_returned,
)
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_assembly import ProductionExecutionAssemblyError
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
from origin_forge.service import StaleRevision
from origin_forge.state import TaskStatus
from origin_forge.workspaces import GitWorkspaceManager


class ProductionDispatchExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase36-execution")
        self.goal_id = self.runtime.create_goal("own one governed execution")
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
        self._write_execution_config()

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

    def _workspace_count(self) -> int:
        with self.runtime.store.session() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                    (self.task_id,),
                ).fetchone()[0]
            )

    def _execution_rows(self) -> list[dict]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatch_executions WHERE task_id = ? ORDER BY created_at, execution_id",
                (self.task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _event_rows(self, aggregate_type: str, aggregate_id: str) -> list[dict]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = ? AND aggregate_id = ?
                   ORDER BY created_at, rowid""",
                (aggregate_type, aggregate_id),
            ).fetchall()
            return [dict(row) for row in rows]

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

    def test_begin_atomically_consumes_claim_and_creates_one_inert_started_receipt(self) -> None:
        task_before = self.runtime.get_task(self.task_id)
        runs_before = self.runtime.list_runs(self.task_id)
        workspaces_before = self._workspace_count()
        started = self._begin_without_execution_calls()
        execution = started.execution

        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(execution.revision, 0)
        self.assertEqual(execution.claim_id, self.claim.claim_id)
        self.assertEqual(execution.claim_revision_at_start, 0)
        self.assertEqual(execution.task_id, self.task_id)
        self.assertEqual(execution.task_revision, 1)
        self.assertEqual(
            execution.runtime_dependency_plan_hash,
            started.dependencies.plan.plan_hash,
        )
        self.assertEqual(execution.execution_owner_id, started.dependencies.plan.owner_id)
        self.assertEqual(
            execution.execution_owner_fingerprint,
            started.dependencies.plan.owner_fingerprint,
        )

        consumed = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(consumed.revision, 1)
        self.assertEqual(consumed.frozen_authority_dict(), self.claim.frozen_authority_dict())
        self.assertEqual(
            consumed.terminal_reason,
            f"claim consumed by dispatch execution {execution.execution_id}",
        )
        currentness = inspect_dispatch_claim_currentness_readonly(
            self.runtime,
            self.claim.claim_id,
        )
        self.assertEqual(currentness.status, DispatchClaimCurrentnessStatus.CONSUMED)
        self.assertEqual(currentness.detail, consumed.terminal_reason)

        rows = self._execution_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["execution_id"], execution.execution_id)
        self.assertEqual(rows[0]["runtime_dependency_plan_hash"], started.dependencies.plan.plan_hash)
        claim_events = self._event_rows("DISPATCH_CLAIM", self.claim.claim_id)
        execution_events = self._event_rows("DISPATCH_EXECUTION", execution.execution_id)
        self.assertEqual(claim_events[-1]["event_type"], "DISPATCH_CLAIM_CONSUMED")
        self.assertEqual(execution_events[-1]["event_type"], "DISPATCH_EXECUTION_STARTED")

        self.assertEqual(started.dependencies.model_scheduling.resources.status().active_leases, ())
        self.assertEqual(started.dependencies.runtime_dispatch_loader.active_runtime_ids(), ())
        self.assertEqual(started.dependencies.managed_loaders[0].active_instance_count(), 0)
        self.assertFalse((self.root / "missing" / "llama-server").exists())
        self.assertFalse((self.root / "missing" / "model.gguf").exists())
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), workspaces_before)

        with self.assertRaises((ProductionExecutionAssemblyError, ProductionDispatchExecutionError)):
            begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(len(self._execution_rows()), 1)

    def test_second_event_failure_rolls_back_claim_receipt_and_first_event(self) -> None:
        original_append = self.runtime.store._append_event
        call_count = 0

        def injected(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected second event failure")
            return original_append(*args, **kwargs)

        with patch.object(self.runtime.store, "_append_event", side_effect=injected):
            with self.assertRaisesRegex(RuntimeError, "second event failure"):
                begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)

        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim.revision, 0)
        self.assertIsNone(claim.terminal_reason)
        self.assertEqual(self._execution_rows(), [])
        events = self._event_rows("DISPATCH_CLAIM", self.claim.claim_id)
        self.assertFalse(any(row["event_type"] == "DISPATCH_CLAIM_CONSUMED" for row in events))

    def test_stale_revision_and_nonready_task_fail_before_consumption(self) -> None:
        with self.assertRaises(StaleRevision):
            begin_dispatch_execution(self.runtime, self.claim.claim_id, 1)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id).status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(self._execution_rows(), [])

        self.runtime.transition_task(
            self.task_id,
            TaskStatus.RUNNING,
            expected_revision=1,
        )
        with self.assertRaises((ProductionExecutionAssemblyError, ProductionDispatchExecutionError)):
            begin_dispatch_execution(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id).status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(self._execution_rows(), [])

    def test_returned_terminalization_changes_receipt_only_and_hashes_detail(self) -> None:
        started = self._begin_without_execution_calls()
        execution = started.execution
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        task_before = self.runtime.get_task(self.task_id)
        runs_before = self.runtime.list_runs(self.task_id)
        workspaces_before = self._workspace_count()
        detail = "bounded policy returned control to infrastructure"

        returned = mark_dispatch_execution_returned(
            self.runtime,
            execution.execution_id,
            0,
            detail,
        )
        self.assertEqual(returned.status, DispatchExecutionStatus.RETURNED)
        self.assertEqual(returned.revision, 1)
        self.assertRegex(returned.terminal_detail_hash or "", r"^[0-9a-f]{64}$")
        self.assertEqual(returned.frozen_authority_dict(), execution.frozen_authority_dict())
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), runs_before)
        self.assertEqual(self._workspace_count(), workspaces_before)

        rows = self._execution_rows()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(detail, json.dumps(rows[0], sort_keys=True))
        events = self._event_rows("DISPATCH_EXECUTION", execution.execution_id)
        self.assertEqual(events[-1]["event_type"], "DISPATCH_EXECUTION_RETURNED")
        self.assertNotIn(detail, events[-1]["metadata_json"])
        self.assertIn(returned.terminal_detail_hash, events[-1]["metadata_json"])
        with self.assertRaisesRegex(ProductionDispatchExecutionError, "terminal"):
            mark_dispatch_execution_raised(
                self.runtime,
                execution.execution_id,
                1,
                "must not rewrite terminal receipt",
            )

    def test_raised_and_interrupted_are_terminal_mechanics_not_task_authority(self) -> None:
        started = self._begin_without_execution_calls()
        task_before = self.runtime.get_task(self.task_id)
        raised = mark_dispatch_execution_raised(
            self.runtime,
            started.execution.execution_id,
            0,
            "bounded invocation raised before returning",
        )
        self.assertEqual(raised.status, DispatchExecutionStatus.RAISED)
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_interrupted_execution_changes_no_task_or_consumed_claim(self) -> None:
        started = self._begin_without_execution_calls()
        claim_before = read_dispatch_claim(self.runtime, self.claim.claim_id)
        task_before = self.runtime.get_task(self.task_id)
        interrupted = interrupt_dispatch_execution(
            self.runtime,
            started.execution.execution_id,
            0,
            "explicit restart recovery interruption",
        )
        self.assertEqual(interrupted.status, DispatchExecutionStatus.INTERRUPTED)
        self.assertEqual(interrupted.revision, 1)
        self.assertEqual(read_dispatch_claim(self.runtime, self.claim.claim_id), claim_before)
        self.assertEqual(self.runtime.get_task(self.task_id), task_before)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertEqual(self._workspace_count(), 0)

    def test_execution_service_source_stops_before_policy_or_backend_invocation(self) -> None:
        source = inspect.getsource(execution_module)
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
            "transition_task",
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
        begin = inspect.signature(begin_dispatch_execution)
        self.assertEqual(tuple(begin.parameters), ("runtime", "claim_id", "expected_revision"))
        for forbidden in (
            "policy",
            "models",
            "sandbox",
            "workspaces",
            "provider",
            "runtime_id",
            "endpoint",
            "argv",
            "loader",
        ):
            self.assertNotIn(forbidden, begin.parameters)


if __name__ == "__main__":
    unittest.main()
