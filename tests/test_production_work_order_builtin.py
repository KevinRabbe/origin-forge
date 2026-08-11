from __future__ import annotations

import inspect
import tempfile
import unittest

import origin_forge.production_work_order_builtin as builtin_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_builtin import (
    BuiltinDispatchReviewStatus,
    CodeBoundedRetryDispatchValidator,
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
    builtin_dispatch_review,
)
from origin_forge.production_work_order_validators import DispatchValidatorError
from origin_forge.production_work_orders import (
    ProductionWorkOrderError,
    create_current_work_order,
)
from origin_forge.runtime import OriginForgeRuntime


class BuiltinProductionWorkOrderTests(unittest.TestCase):
    def test_review_supports_only_bounded_code_and_records_every_deferred_boundary(self) -> None:
        rows = {value.adapter_id: value for value in builtin_dispatch_review()}
        self.assertEqual(
            rows["originforge.code.bounded-retry"].status,
            BuiltinDispatchReviewStatus.SUPPORTED,
        )
        for adapter_id in (
            "originforge.pixelorama.export",
            "originforge.blender.model3d",
            "originforge.image.generate",
            "originforge.vision.inspect",
            "originforge.audio.ffmpeg",
            "originforge.audio.piper",
            "originforge.runtime.observe",
            "originforge.playtest.cooperative",
            "originforge.simulation.deterministic",
        ):
            self.assertEqual(
                rows[adapter_id].status,
                BuiltinDispatchReviewStatus.DEFERRED_INPUT_EVIDENCE_RESOLUTION,
            )
        self.assertEqual(
            rows["design.specify"].status,
            BuiltinDispatchReviewStatus.NO_PHASE32_ADAPTER,
        )
        self.assertEqual(
            rows["blockbench"].status,
            BuiltinDispatchReviewStatus.DEFERRED_BACKEND,
        )

    def test_builtin_dispatch_catalog_has_exactly_one_safe_contract(self) -> None:
        phase32 = build_builtin_capability_catalog()
        catalog = build_builtin_dispatch_catalog(phase32)
        self.assertEqual(catalog.phase32_catalog_id, phase32.catalog_id)
        self.assertEqual(catalog.phase32_catalog_hash, phase32.content_hash)
        self.assertEqual(catalog.contract_ids, ("code.bounded-retry@1",))
        contract = catalog.contract("code.bounded-retry@1")
        self.assertEqual(contract.adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(contract.allowed_input_ref_types, ())
        self.assertEqual(contract.max_input_refs, 0)
        for forbidden in (
            "pixelorama",
            "blender",
            "ffmpeg",
            "piper",
            "playtest",
            "simulation",
            "blockbench",
        ):
            self.assertNotIn(forbidden, " ".join(catalog.contract_ids).lower())

    def test_code_validator_normalizes_exact_drive_inputs(self) -> None:
        validator = CodeBoundedRetryDispatchValidator()
        manual = validator.validate(
            {
                "context_mode": "manual",
                "selected_paths": ["src/example.py", "tests/test_example.py"],
                "structural_context": True,
            },
            (),
        )
        self.assertEqual(
            manual,
            {
                "context_mode": "manual",
                "selected_paths": ["src/example.py", "tests/test_example.py"],
                "context_seed_paths": [],
                "structural_context": True,
                "semantic_context": False,
            },
        )
        automatic = validator.validate(
            {
                "context_mode": "auto",
                "context_seed_paths": ["src/core.py"],
                "semantic_context": True,
            },
            (),
        )
        self.assertEqual(
            automatic,
            {
                "context_mode": "auto",
                "selected_paths": [],
                "context_seed_paths": ["src/core.py"],
                "structural_context": False,
                "semantic_context": True,
            },
        )

    def test_code_validator_rejects_cross_mode_and_unsafe_paths(self) -> None:
        validator = CodeBoundedRetryDispatchValidator()
        with self.assertRaisesRegex(DispatchValidatorError, "requires selected_paths"):
            validator.validate({"context_mode": "manual"}, ())
        with self.assertRaisesRegex(DispatchValidatorError, "cannot contain selected_paths"):
            validator.validate(
                {
                    "context_mode": "auto",
                    "selected_paths": ["src/example.py"],
                },
                (),
            )
        with self.assertRaisesRegex(DispatchValidatorError, "cannot contain context_seed_paths"):
            validator.validate(
                {
                    "context_mode": "manual",
                    "selected_paths": ["src/example.py"],
                    "context_seed_paths": ["tests/test_example.py"],
                },
                (),
            )
        for path in (
            "/etc/passwd",
            "../outside.py",
            ".origin-forge/config.toml",
            ".git/config",
            "src\\windows.py",
            "src//noncanonical.py",
        ):
            with self.subTest(path=path):
                with self.assertRaises(DispatchValidatorError):
                    validator.validate(
                        {
                            "context_mode": "manual",
                            "selected_paths": [path],
                        },
                        (),
                    )

    def test_code_validator_identity_is_deterministic(self) -> None:
        first = CodeBoundedRetryDispatchValidator()
        second = CodeBoundedRetryDispatchValidator()
        self.assertEqual(first.validator_id, second.validator_id)
        self.assertEqual(first.validator_fingerprint, second.validator_fingerprint)
        self.assertEqual(first.payload_schema_id, second.payload_schema_id)
        self.assertEqual(first.payload_schema_hash, second.payload_schema_hash)

    def test_builtin_code_route_can_construct_work_order_but_deferred_route_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("builtin-work-orders")
            goal = runtime.create_goal("dispatch-review")
            flow = runtime.create_flow(goal)
            phase32 = build_builtin_capability_catalog()
            policy = CapabilityRoutingPolicy.create(
                phase32,
                ordered_adapter_ids=(
                    "originforge.code.bounded-retry",
                    "originforge.runtime.observe",
                ),
                allowed_capability_ids=("code.change", "runtime.observe"),
            )
            capability_store = ProductionCapabilityStore(runtime)
            capability_store.publish_catalog(phase32)
            capability_store.publish_policy(policy, phase32)
            dispatch_catalog = build_builtin_dispatch_catalog(phase32)
            registry = build_builtin_dispatch_validator_registry()

            code_task = runtime.create_task(
                flow,
                "change code",
                required_capabilities=("code.change",),
            )
            code_route = capability_store.resolve_and_publish(
                code_task,
                phase32.catalog_id,
                policy.routing_policy_id,
            )
            work_order = create_current_work_order(
                runtime,
                capability_store,
                dispatch_catalog,
                registry,
                code_route.route_decision_id,
                payload={
                    "context_mode": "auto",
                    "context_seed_paths": ["src/example.py"],
                },
            )
            self.assertEqual(
                work_order.selected_adapter_id,
                "originforge.code.bounded-retry",
            )
            self.assertEqual(
                work_order.payload,
                {
                    "context_mode": "auto",
                    "selected_paths": [],
                    "context_seed_paths": ["src/example.py"],
                    "structural_context": False,
                    "semantic_context": False,
                },
            )

            observe_task = runtime.create_task(
                flow,
                "observe runtime",
                required_capabilities=("runtime.observe",),
            )
            observe_route = capability_store.resolve_and_publish(
                observe_task,
                phase32.catalog_id,
                policy.routing_policy_id,
            )
            with self.assertRaisesRegex(ProductionWorkOrderError, "no contract"):
                create_current_work_order(
                    runtime,
                    capability_store,
                    dispatch_catalog,
                    registry,
                    observe_route.route_decision_id,
                    payload={"context_mode": "auto"},
                )
            self.assertEqual(runtime.list_runs(code_task), [])
            self.assertEqual(runtime.list_runs(observe_task), [])

    def test_builtin_dispatch_module_has_no_backend_execution_surface(self) -> None:
        source = inspect.getsource(builtin_module)
        for forbidden in (
            "subprocess",
            "os.system",
            "importlib",
            ".drive(",
            ".execute(",
            ".run(",
            ".generate(",
            "create_sandbox_backend",
            "LlamaCpp",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
