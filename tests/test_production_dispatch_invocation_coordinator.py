from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
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
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_execution import ProductionDispatchExecutionError
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_execution_read import read_dispatch_execution
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
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
from origin_forge.runtime import OriginForgeRuntime


class ProductionDispatchInvocationCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase37-coordinator")
        self.goal_id = self.runtime.create_goal("invoke one governed production claim")
        self.flow_id = self.runtime.create_flow(self.goal_id)

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
        self._write_executable_config()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_executable_config(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
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
''',
            encoding="utf-8",
        )

    def _new_claim(self, suffix: str):
        task_id = self.runtime.create_task(
            self.flow_id,
            f"bounded production change {suffix}",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        activate_dependency_ready_task(self.runtime, task_id, 0)
        route = self.capability_store.resolve_and_publish(
            task_id,
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
        return task_id, claim

    def _execution_for_claim(self, claim_id: str):
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT execution_id FROM dispatch_executions WHERE claim_id = ?",
                (claim_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        return read_dispatch_execution(self.runtime, rows[0]["execution_id"])

    @staticmethod
    def _result(task_id: str, outcome: PolicyOutcome) -> PolicyResult:
        return PolicyResult(
            task_id=task_id,
            outcome=outcome,
            action=PolicyAction.STOP,
            reason="live policy result is not dispatch terminal evidence",
            executor_attempts=0,
            attempts_started=0,
        )

    def test_every_policy_outcome_is_dispatch_returned_without_reinterpretation(self) -> None:
        for index, outcome in enumerate(PolicyOutcome):
            with self.subTest(outcome=outcome.value):
                task_id, claim = self._new_claim(f"outcome-{index}")
                policy_result = self._result(task_id, outcome)
                task_before = self.runtime.get_task(task_id)
                with patch.object(
                    BoundedRetryPolicy,
                    "drive",
                    return_value=policy_result,
                ) as drive:
                    completed = dispatch_claim_once(
                        self.runtime,
                        claim.claim_id,
                        0,
                    )
                self.assertEqual(drive.call_count, 1)
                self.assertIs(completed.policy_result, policy_result)
                self.assertEqual(completed.execution.status, DispatchExecutionStatus.RETURNED)
                self.assertEqual(completed.execution.revision, 1)
                consumed = read_dispatch_claim(self.runtime, claim.claim_id)
                self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
                self.assertEqual(consumed.revision, 1)
                self.assertEqual(self.runtime.get_task(task_id), task_before)
                kwargs = drive.call_args.kwargs
                self.assertEqual(
                    set(kwargs),
                    {
                        "task_id",
                        "selected_paths",
                        "auto_context",
                        "context_seed_paths",
                        "structural_context",
                        "semantic_context",
                    },
                )
                self.assertEqual(kwargs["task_id"], task_id)
                self.assertEqual(kwargs["selected_paths"], ())
                self.assertTrue(kwargs["auto_context"])
                self.assertEqual(kwargs["context_seed_paths"], ("src/example.py",))
                self.assertTrue(kwargs["structural_context"])
                self.assertFalse(kwargs["semantic_context"])

    def test_ordinary_owner_exception_records_raised_and_consumes_claim(self) -> None:
        task_id, claim = self._new_claim("raised")
        task_before = self.runtime.get_task(task_id)

        class SensitiveFailure(RuntimeError):
            pass

        with patch.object(
            BoundedRetryPolicy,
            "drive",
            side_effect=SensitiveFailure("secret model text must not persist here"),
        ) as drive:
            with self.assertRaises(ProductionDispatchInvocationError) as caught:
                dispatch_claim_once(self.runtime, claim.claim_id, 0)
        self.assertEqual(drive.call_count, 1)
        self.assertNotIsInstance(
            caught.exception,
            ProductionDispatchInvocationRecoveryRequired,
        )
        self.assertNotIn("secret model text", str(caught.exception))
        self.assertIn("SensitiveFailure", str(caught.exception))
        execution = self._execution_for_claim(claim.claim_id)
        self.assertEqual(execution.status, DispatchExecutionStatus.RAISED)
        self.assertEqual(execution.revision, 1)
        consumed = read_dispatch_claim(self.runtime, claim.claim_id)
        self.assertEqual(consumed.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(consumed.revision, 1)
        self.assertEqual(self.runtime.get_task(task_id), task_before)

    def test_base_exception_leaves_started_active_for_explicit_recovery(self) -> None:
        task_id, claim = self._new_claim("keyboard-interrupt")
        task_before = self.runtime.get_task(task_id)
        with patch.object(
            BoundedRetryPolicy,
            "drive",
            side_effect=KeyboardInterrupt(),
        ) as drive:
            with self.assertRaises(KeyboardInterrupt):
                dispatch_claim_once(self.runtime, claim.claim_id, 0)
        self.assertEqual(drive.call_count, 1)
        execution = self._execution_for_claim(claim.claim_id)
        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        self.assertEqual(execution.revision, 0)
        active = read_dispatch_claim(self.runtime, claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(active.revision, 0)
        self.assertEqual(self.runtime.get_task(task_id), task_before)

    def test_return_terminalization_failure_never_replays_owner(self) -> None:
        task_id, claim = self._new_claim("terminalization-failure")
        policy_result = self._result(task_id, PolicyOutcome.SUCCEEDED)
        with (
            patch.object(
                BoundedRetryPolicy,
                "drive",
                return_value=policy_result,
            ) as drive,
            patch.object(
                invocation_module,
                "mark_dispatch_execution_returned",
                side_effect=RuntimeError("injected terminalization failure"),
            ),
        ):
            with self.assertRaises(
                ProductionDispatchInvocationRecoveryRequired
            ) as caught:
                dispatch_claim_once(self.runtime, claim.claim_id, 0)
        self.assertEqual(drive.call_count, 1)
        self.assertEqual(
            caught.exception.reason_code,
            "RETURNED_TERMINALIZATION_FAILED",
        )
        execution = self._execution_for_claim(claim.claim_id)
        self.assertEqual(caught.exception.execution_id, execution.execution_id)
        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        active = read_dispatch_claim(self.runtime, claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(active.revision, 0)

    def test_invalid_owner_return_requires_recovery_without_false_returned_receipt(self) -> None:
        _, claim = self._new_claim("invalid-return")
        with patch.object(
            BoundedRetryPolicy,
            "drive",
            return_value=object(),
        ) as drive:
            with self.assertRaises(
                ProductionDispatchInvocationRecoveryRequired
            ) as caught:
                dispatch_claim_once(self.runtime, claim.claim_id, 0)
        self.assertEqual(drive.call_count, 1)
        self.assertEqual(
            caught.exception.reason_code,
            "OWNER_RETURN_CONTRACT_MISMATCH",
        )
        execution = self._execution_for_claim(claim.claim_id)
        self.assertEqual(execution.status, DispatchExecutionStatus.STARTED)
        active = read_dispatch_claim(self.runtime, claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)

    def test_begin_failure_occurs_before_owner_call(self) -> None:
        _, claim = self._new_claim("begin-failure")
        with (
            patch.object(
                invocation_module,
                "begin_dispatch_execution",
                side_effect=ProductionDispatchExecutionError("injected begin failure"),
            ),
            patch.object(
                BoundedRetryPolicy,
                "drive",
                side_effect=AssertionError("owner must not be called"),
            ) as drive,
        ):
            with self.assertRaises(ProductionDispatchExecutionError):
                dispatch_claim_once(self.runtime, claim.claim_id, 0)
        drive.assert_not_called()
        with self.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM dispatch_executions WHERE claim_id = ?",
                (claim.claim_id,),
            ).fetchone()["count"]
        self.assertEqual(count, 0)
        active = read_dispatch_claim(self.runtime, claim.claim_id)
        self.assertEqual(active.status, DispatchClaimStatus.ACTIVE)

    def test_coordinator_has_one_drive_call_site_no_retry_and_no_outcome_branch(self) -> None:
        signature = inspect.signature(dispatch_claim_once)
        self.assertEqual(
            tuple(signature.parameters),
            ("runtime", "claim_id", "expected_claim_revision"),
        )
        source = inspect.getsource(invocation_module._legacy_dispatch_claim_once)
        tree = ast.parse(source)
        drive_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "drive"
        ]
        self.assertEqual(len(drive_calls), 1)
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "outcome"
                for node in ast.walk(tree)
            )
        )
        self.assertFalse(
            any(isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in ast.walk(tree))
        )
        for forbidden in (
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
            self.assertNotIn(forbidden, signature.parameters)


if __name__ == "__main__":
    unittest.main()
