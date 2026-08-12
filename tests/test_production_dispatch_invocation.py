from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
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
from origin_forge.production_dispatch_invocation import (
    BoundedRetryInvocationRequest,
    ProductionDispatchInvocationError,
    _decode_request_projection,
    _require_trusted_bounded_retry_relation,
    freeze_bounded_retry_invocation_request,
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
from origin_forge.production_work_order_models import canonical_bytes, content_hash
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


class ProductionDispatchInvocationRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase37-invocation")
        goal_id = self.runtime.create_goal("freeze one governed invocation request")
        flow_id = self.runtime.create_flow(goal_id)
        self.task_id = self.runtime.create_task(
            flow_id,
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
        self.binding = create_dispatch_binding(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
        )
        self.binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            bundle,
            self.binding,
        )
        self.dispatch_store.publish_input_resolution(bundle)
        self.dispatch_store.publish_binding(self.binding)
        self.dispatch_store.publish_audit(self.binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime,
            self.binding.dispatch_binding_id,
            self.binding_audit.binding_audit_id,
            1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

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

    @staticmethod
    def _request_hash(
        *,
        task_id: str,
        selected_paths: tuple[str, ...],
        auto_context: bool,
        context_seed_paths: tuple[str, ...],
        structural_context: bool,
        semantic_context: bool,
    ) -> str:
        return content_hash(
            {
                "task_id": task_id,
                "selected_paths": list(selected_paths),
                "auto_context": auto_context,
                "context_seed_paths": list(context_seed_paths),
                "structural_context": structural_context,
                "semantic_context": semantic_context,
            }
        )

    def test_exact_auto_request_reconstructs_without_mutation_or_invocation(self) -> None:
        before = self._state_snapshot()
        request = freeze_bounded_retry_invocation_request(
            self.runtime,
            self.claim.claim_id,
            0,
        )
        self.assertEqual(self._state_snapshot(), before)
        self.assertEqual(request.task_id, self.task_id)
        self.assertEqual(request.selected_paths, ())
        self.assertTrue(request.auto_context)
        self.assertEqual(request.context_seed_paths, ("src/example.py",))
        self.assertTrue(request.structural_context)
        self.assertFalse(request.semantic_context)
        self.assertEqual(request.request_content_hash, self.binding.request_content_hash)
        self.assertEqual(request.projection_dict(), self.binding.request_projection)

    def test_manual_and_path_contract_reuses_phase33_bounds(self) -> None:
        selected = ("src/example.py",)
        request = BoundedRetryInvocationRequest(
            task_id=self.task_id,
            selected_paths=selected,
            auto_context=False,
            context_seed_paths=(),
            structural_context=False,
            semantic_context=True,
            request_content_hash=self._request_hash(
                task_id=self.task_id,
                selected_paths=selected,
                auto_context=False,
                context_seed_paths=(),
                structural_context=False,
                semantic_context=True,
            ),
        )
        self.assertEqual(request.selected_paths, selected)
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "bounded coding context"):
            BoundedRetryInvocationRequest(
                task_id=self.task_id,
                selected_paths=(),
                auto_context=False,
                context_seed_paths=(),
                structural_context=False,
                semantic_context=False,
                request_content_hash=self._request_hash(
                    task_id=self.task_id,
                    selected_paths=(),
                    auto_context=False,
                    context_seed_paths=(),
                    structural_context=False,
                    semantic_context=False,
                ),
            )
        bad = (".origin-forge/secret",)
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "bounded coding context"):
            BoundedRetryInvocationRequest(
                task_id=self.task_id,
                selected_paths=bad,
                auto_context=False,
                context_seed_paths=(),
                structural_context=False,
                semantic_context=False,
                request_content_hash=self._request_hash(
                    task_id=self.task_id,
                    selected_paths=bad,
                    auto_context=False,
                    context_seed_paths=(),
                    structural_context=False,
                    semantic_context=False,
                ),
            )

    def test_projection_schema_boolean_and_hash_drift_fail_closed(self) -> None:
        extra_projection = dict(self.binding.request_projection)
        extra_projection["model_profile"] = "caller-choice"
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "schema drifted"):
            _decode_request_projection(
                replace(
                    self.binding,
                    request_projection_json=canonical_bytes(extra_projection).decode("utf-8"),
                )
            )

        bad_bool_projection = dict(self.binding.request_projection)
        bad_bool_projection["auto_context"] = 1
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "exact boolean"):
            _decode_request_projection(
                replace(
                    self.binding,
                    request_projection_json=canonical_bytes(bad_bool_projection).decode("utf-8"),
                )
            )

        with self.assertRaisesRegex(ProductionDispatchInvocationError, "does not recompute"):
            BoundedRetryInvocationRequest(
                task_id=self.task_id,
                selected_paths=(),
                auto_context=True,
                context_seed_paths=("src/example.py",),
                structural_context=True,
                semantic_context=False,
                request_content_hash="0" * 64,
            )

    def test_current_trusted_owner_binder_and_request_schema_are_mandatory(self) -> None:
        _require_trusted_bounded_retry_relation(self.binding)
        for drifted in (
            replace(self.binding, request_type_id="OtherRequest@1"),
            replace(self.binding, request_schema_hash="0" * 64),
            replace(self.binding, binder_fingerprint="0" * 64),
            replace(self.binding, selected_adapter_id="originforge.other.adapter"),
            replace(self.binding, dispatch_contract_id="other.contract@1"),
        ):
            with self.assertRaises(ProductionDispatchInvocationError):
                _require_trusted_bounded_retry_relation(drifted)

    def test_freeze_requires_exact_active_claim_revision_and_audit_relation(self) -> None:
        with self.assertRaisesRegex(ProductionDispatchInvocationError, "revision"):
            freeze_bounded_retry_invocation_request(
                self.runtime,
                self.claim.claim_id,
                1,
            )

        forged_audit = replace(
            self.binding_audit,
            request_content_hash="0" * 64,
        )
        with patch.object(
            invocation_module,
            "read_dispatch_binding_audit",
            return_value=forged_audit,
        ):
            with self.assertRaisesRegex(ProductionDispatchInvocationError, "audit"):
                freeze_bounded_retry_invocation_request(
                    self.runtime,
                    self.claim.claim_id,
                    0,
                )

    def test_37b_surface_contains_no_execution_authority(self) -> None:
        source = inspect.getsource(invocation_module)
        tree = ast.parse(source)
        forbidden_calls = {
            "drive",
            "begin_dispatch_execution",
            "assemble_production_execution_dependencies",
            "start_run",
            "finish_run",
            "generate",
            "acquire",
            "try_acquire",
            "load",
            "unload",
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
        signature = inspect.signature(freeze_bounded_retry_invocation_request)
        self.assertEqual(
            tuple(signature.parameters),
            ("runtime", "claim_id", "expected_claim_revision"),
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
