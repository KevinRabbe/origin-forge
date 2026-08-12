from __future__ import annotations

import inspect
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
import origin_forge.production_dispatch_invocation_read as invocation_read_module
from origin_forge.managed_llamacpp_loader import ManagedLlamaCppCpuLoader
from origin_forge.orchestration_policy import (
    BoundedRetryPolicy,
    PolicyAction,
    PolicyOutcome,
    PolicyResult,
)
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claim_lifecycle import (
    DispatchClaimLifecycleError,
    interrupt_dispatch_claim,
    release_dispatch_claim,
)
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import interrupt_dispatch_execution
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_read import (
    DispatchInvocationStatus,
    inspect_dispatch_invocation_status_readonly,
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
from origin_forge.production_work_order_models import canonical_bytes
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
image = "origin-forge-test-sandbox:phase37"
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


class _Phase37Harness:
    def __init__(self, root: Path):
        self.root = root
        self.runtime = OriginForgeRuntime(root)
        self.runtime.initialize("phase37-acceptance")
        self.goal_id = self.runtime.create_goal("prove governed single-shot production dispatch")
        self.flow_id = self.runtime.create_flow(self.goal_id)
        self.catalog = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.catalog)
        self.capability_store.publish_policy(self.policy, self.catalog)
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
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _CONFIG,
            encoding="utf-8",
        )
        self._counter = 0

    def new_claim(self):
        self._counter += 1
        task_id = self.runtime.create_task(
            self.flow_id,
            f"bounded production change {self._counter}",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        activate_dependency_ready_task(self.runtime, task_id, 0)
        if self.runtime.get_task(task_id)["status"] != TaskStatus.READY.value:
            raise AssertionError("test fixture Task did not become READY")
        route = self.capability_store.resolve_and_publish(
            task_id,
            self.catalog.catalog_id,
            self.policy.routing_policy_id,
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
                "semantic_context": False,
            },
        )
        work_order_audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            work_order,
        )
        self.work_order_store.publish_work_order(work_order)
        self.work_order_store.publish_audit(work_order_audit)
        bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolver_registry,
            work_order.work_order_id,
            work_order_audit.work_order_audit_id,
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
        return task_id, binding, binding_audit, claim

    @staticmethod
    def policy_result(task_id: str, outcome: PolicyOutcome) -> PolicyResult:
        return PolicyResult(
            task_id=task_id,
            outcome=outcome,
            action=PolicyAction.STOP,
            reason="canonical downstream state remains authoritative",
            executor_attempts=0,
            attempts_started=0,
        )


class Phase37CrossPhaseAcceptanceTests(unittest.TestCase):
    def test_complete_chain_returns_for_every_policy_outcome_without_extra_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness = _Phase37Harness(Path(temp))
            runtime = harness.runtime
            for outcome in (
                PolicyOutcome.SUCCEEDED,
                PolicyOutcome.BLOCKED,
                PolicyOutcome.FAILED,
                PolicyOutcome.QUARANTINED,
            ):
                with self.subTest(outcome=outcome.value):
                    task_id, _, _, claim = harness.new_claim()
                    task_before = runtime.get_task(task_id)
                    runs_before = runtime.list_runs(task_id)
                    with runtime.store.session() as conn:
                        workspaces_before = int(
                            conn.execute(
                                "SELECT COUNT(*) FROM workspaces WHERE task_id = ?",
                                (task_id,),
                            ).fetchone()[0]
                        )
                    pre = inspect_dispatch_invocation_status_readonly(
                        runtime,
                        claim.claim_id,
                    )
                    self.assertEqual(pre.status, DispatchInvocationStatus.READY_TO_INVOKE)
                    result = harness.policy_result(task_id, outcome)
                    with (
                        patch.object(
                            ManagedLlamaCppCpuLoader,
                            "load",
                            side_effect=AssertionError("model load before owner call"),
                        ),
                        patch.object(
                            ResourceScheduler,
                            "acquire",
                            side_effect=AssertionError("resource acquire before owner call"),
                        ),
                        patch.object(
                            GitWorkspaceManager,
                            "create",
                            side_effect=AssertionError("workspace create before owner call"),
                        ),
                        patch.object(
                            OriginForgeRuntime,
                            "start_run",
                            side_effect=AssertionError("run start before owner call"),
                        ),
                        patch.object(
                            BoundedRetryPolicy,
                            "drive",
                            return_value=result,
                        ) as drive,
                        patch(
                            "subprocess.Popen",
                            side_effect=AssertionError("process start before owner call"),
                        ),
                    ):
                        completed = dispatch_claim_once(runtime, claim.claim_id, 0)
                    self.assertEqual(drive.call_count, 1)
                    self.assertIs(completed.policy_result, result)
                    self.assertEqual(
                        completed.execution.status,
                        DispatchExecutionStatus.RETURNED,
                    )
                    self.assertEqual(
                        drive.call_args.kwargs,
                        {
                            "task_id": task_id,
                            "selected_paths": (),
                            "auto_context": True,
                            "context_seed_paths": ("src/example.py",),
                            "structural_context": True,
                            "semantic_context": False,
                        },
                    )
                    post = inspect_dispatch_invocation_status_readonly(
                        runtime,
                        claim.claim_id,
                    )
                    self.assertEqual(post.status, DispatchInvocationStatus.RETURNED)
                    consumed = read_dispatch_claim(runtime, claim.claim_id)
                    self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
                    self.assertEqual(consumed.revision, 1)
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
            self.assertFalse((harness.root / "missing" / "llama-server").exists())
            self.assertFalse((harness.root / "missing" / "model.gguf").exists())

    def test_started_execution_seals_claim_and_concurrent_dispatch_never_calls_owner_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness = _Phase37Harness(Path(temp))
            runtime = harness.runtime
            task_id, binding, binding_audit, claim = harness.new_claim()
            result = harness.policy_result(task_id, PolicyOutcome.SUCCEEDED)
            drive_entered = threading.Event()
            allow_return = threading.Event()
            call_lock = threading.Lock()
            drive_calls: list[dict[str, object]] = []
            results: dict[str, object] = {}
            errors: dict[str, BaseException] = {}

            def fake_drive(_self, **kwargs):
                with call_lock:
                    drive_calls.append(dict(kwargs))
                drive_entered.set()
                if not allow_return.wait(10.0):
                    raise RuntimeError("acceptance test timed out waiting to return")
                return result

            def run_dispatch(label: str) -> None:
                try:
                    results[label] = dispatch_claim_once(runtime, claim.claim_id, 0)
                except BaseException as exc:
                    errors[label] = exc

            with patch.object(BoundedRetryPolicy, "drive", new=fake_drive):
                first = threading.Thread(target=run_dispatch, args=("first",), daemon=True)
                first.start()
                self.assertTrue(drive_entered.wait(10.0))
                self.assertEqual(len(drive_calls), 1)

                live = inspect_dispatch_invocation_status_readonly(
                    runtime,
                    claim.claim_id,
                )
                self.assertEqual(
                    live.status,
                    DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
                )
                with self.assertRaises(RuntimeError):
                    acquire_dispatch_claim(
                        runtime,
                        binding.dispatch_binding_id,
                        binding_audit.binding_audit_id,
                        1,
                    )
                with self.assertRaises(DispatchClaimLifecycleError):
                    release_dispatch_claim(runtime, claim.claim_id, 0)
                with self.assertRaises(DispatchClaimLifecycleError):
                    interrupt_dispatch_claim(
                        runtime,
                        claim.claim_id,
                        0,
                        "legacy claim interruption must be sealed",
                    )
                with self.assertRaises(sqlite3.DatabaseError):
                    with runtime.store.session() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute(
                            """UPDATE dispatch_claims
                               SET status = 'RELEASED', revision = 1,
                                   terminal_reason = 'direct bypass'
                               WHERE claim_id = ?""",
                            (claim.claim_id,),
                        )

                second = threading.Thread(target=run_dispatch, args=("second",), daemon=True)
                second.start()
                second.join(5.0)
                self.assertFalse(second.is_alive())
                self.assertEqual(len(drive_calls), 1)
                self.assertIn("second", errors)

                allow_return.set()
                first.join(10.0)
                self.assertFalse(first.is_alive())

            self.assertEqual(len(drive_calls), 1)
            self.assertIn("first", results)
            self.assertNotIn("first", errors)
            self.assertEqual(
                inspect_dispatch_invocation_status_readonly(
                    runtime,
                    claim.claim_id,
                ).status,
                DispatchInvocationStatus.RETURNED,
            )
            self.assertEqual(
                read_dispatch_claim(runtime, claim.claim_id).status,
                DispatchClaimStatus.CONSUMED,
            )

    def test_base_exception_restart_requires_explicit_phase36_recovery_before_fresh_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            harness = _Phase37Harness(root)
            runtime = harness.runtime
            _, binding, binding_audit, claim = harness.new_claim()
            with patch.object(
                BoundedRetryPolicy,
                "drive",
                side_effect=KeyboardInterrupt(),
            ) as drive:
                with self.assertRaises(KeyboardInterrupt):
                    dispatch_claim_once(runtime, claim.claim_id, 0)
            self.assertEqual(drive.call_count, 1)

            started = inspect_dispatch_invocation_status_readonly(
                runtime,
                claim.claim_id,
            )
            self.assertEqual(
                started.status,
                DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
            )
            self.assertIsNotNone(started.execution_id)
            active = read_dispatch_claim(runtime, claim.claim_id)
            self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)
            self.assertEqual(active.revision, 0)

            restarted = OriginForgeRuntime(root)
            with patch.object(
                BoundedRetryPolicy,
                "drive",
                side_effect=AssertionError("restart must not auto-replay owner"),
            ) as replay:
                after_restart = inspect_dispatch_invocation_status_readonly(
                    restarted,
                    claim.claim_id,
                )
            replay.assert_not_called()
            self.assertEqual(
                after_restart.status,
                DispatchInvocationStatus.STARTED_RECOVERY_REQUIRED,
            )
            self.assertEqual(after_restart.execution_id, started.execution_id)

            interrupted = interrupt_dispatch_execution(
                restarted,
                started.execution_id,
                0,
                0,
                "explicit operator recovery after uncertain invocation",
            )
            self.assertEqual(interrupted.status, DispatchExecutionStatus.INTERRUPTED)
            old_status = inspect_dispatch_invocation_status_readonly(
                restarted,
                claim.claim_id,
            )
            self.assertEqual(old_status.status, DispatchInvocationStatus.INTERRUPTED)
            interrupted_claim = read_dispatch_claim(restarted, claim.claim_id)
            self.assertEqual(interrupted_claim.status, DispatchClaimStatus.INTERRUPTED)
            self.assertEqual(interrupted_claim.revision, 1)

            fresh = acquire_dispatch_claim(
                restarted,
                binding.dispatch_binding_id,
                binding_audit.binding_audit_id,
                1,
            )
            self.assertEqual(fresh.status, DispatchClaimStatus.ACTIVE)
            self.assertNotEqual(fresh.claim_id, claim.claim_id)
            self.assertEqual(
                inspect_dispatch_invocation_status_readonly(
                    restarted,
                    fresh.claim_id,
                ).status,
                DispatchInvocationStatus.READY_TO_INVOKE,
            )

    def test_owner_exception_is_raised_evidence_and_claim_consumption_not_task_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness = _Phase37Harness(Path(temp))
            runtime = harness.runtime
            task_id, _, _, claim = harness.new_claim()
            task_before = runtime.get_task(task_id)

            class SensitiveOwnerFailure(RuntimeError):
                pass

            with patch.object(
                BoundedRetryPolicy,
                "drive",
                side_effect=SensitiveOwnerFailure(
                    "sensitive downstream text must not become dispatch evidence"
                ),
            ) as drive:
                with self.assertRaises(ProductionDispatchInvocationError) as caught:
                    dispatch_claim_once(runtime, claim.claim_id, 0)
            self.assertEqual(drive.call_count, 1)
            self.assertNotIn("sensitive downstream text", str(caught.exception))
            status = inspect_dispatch_invocation_status_readonly(
                runtime,
                claim.claim_id,
            )
            self.assertEqual(status.status, DispatchInvocationStatus.RAISED)
            consumed = read_dispatch_claim(runtime, claim.claim_id)
            self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
            self.assertEqual(runtime.get_task(task_id), task_before)

    def test_forged_phase34_invocation_authority_fails_before_begin_and_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness = _Phase37Harness(Path(temp))
            runtime = harness.runtime
            _, binding, _, claim = harness.new_claim()
            drifted_projection = dict(binding.request_projection)
            drifted_projection["semantic_context"] = not drifted_projection["semantic_context"]
            forged_bindings = (
                replace(binding, request_schema_hash="0" * 64),
                replace(
                    binding,
                    request_projection_json=canonical_bytes(drifted_projection).decode("utf-8"),
                ),
                replace(binding, binder_fingerprint="2" * 64),
                replace(binding, selected_adapter_id="originforge.other.adapter"),
                replace(binding, dispatch_contract_id="other.contract@1"),
            )
            for forged in forged_bindings:
                with self.subTest(
                    adapter=forged.selected_adapter_id,
                    contract=forged.dispatch_contract_id,
                    request_schema=forged.request_schema_hash,
                ):
                    with (
                        patch.object(
                            invocation_module,
                            "read_dispatch_binding",
                            return_value=forged,
                        ),
                        patch.object(
                            invocation_module,
                            "begin_dispatch_execution",
                            side_effect=AssertionError("begin must not occur"),
                        ) as begin,
                        patch.object(
                            BoundedRetryPolicy,
                            "drive",
                            side_effect=AssertionError("owner must not occur"),
                        ) as drive,
                    ):
                        with self.assertRaises(ProductionDispatchInvocationError):
                            dispatch_claim_once(runtime, claim.claim_id, 0)
                    begin.assert_not_called()
                    drive.assert_not_called()
            self.assertEqual(
                read_dispatch_claim(runtime, claim.claim_id).status,
                DispatchClaimStatus.ACTIVE,
            )

    def test_phase37_invocation_surface_is_narrow_and_non_generic(self) -> None:
        signature = inspect.signature(dispatch_claim_once)
        self.assertEqual(
            tuple(signature.parameters),
            ("runtime", "claim_id", "expected_claim_revision"),
        )
        source = inspect.getsource(invocation_module)
        self.assertEqual(source.count(".drive("), 1)
        self.assertNotIn("PolicyOutcome", source)
        for forbidden in (
            "importlib",
            "subprocess",
            "getattr(",
            "eval(",
            "exec(",
            "artifact_adopt",
            "artifact_sign",
            "merge_branch",
            "release_build",
            "dream_promote",
            "training_activate",
        ):
            self.assertNotIn(forbidden, source)
        read_source = inspect.getsource(invocation_read_module)
        self.assertNotIn("dispatch_claim_once(", read_source)
        self.assertNotIn("begin_dispatch_execution(", read_source)
        self.assertNotIn("interrupt_dispatch_execution(", read_source)
        self.assertNotIn(".drive(", read_source)
        for forbidden_parameter in (
            "owner",
            "adapter",
            "contract",
            "binder",
            "model",
            "profile",
            "runtime_id",
            "provider",
            "endpoint",
            "sandbox",
            "workspace",
            "selected_paths",
            "auto_context",
            "context_seed_paths",
            "structural_context",
            "semantic_context",
        ):
            self.assertNotIn(forbidden_parameter, signature.parameters)


if __name__ == "__main__":
    unittest.main()
