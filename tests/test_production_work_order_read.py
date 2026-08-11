from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_work_order_read as read_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_audit import (
    WorkOrderCurrentnessStatus,
    audit_work_order_frozen,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_read import (
    ProductionWorkOrderReadError,
    inspect_work_order_currentness_readonly,
    read_dispatch_catalog,
    read_work_order,
    read_work_order_audit,
    work_order_read_status,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus
from origin_forge.task_readiness import DependencyReadinessStatus


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            result[f"SYMLINK:{path.relative_to(root).as_posix()}"] = b""
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


class ProductionWorkOrderReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("work-order-read")
        goal = self.runtime.create_goal("inspect one governed work order")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            flow,
            "change code",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        self.phase32 = build_builtin_capability_catalog()
        self.policy = CapabilityRoutingPolicy.create(
            self.phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        self.capability_store = ProductionCapabilityStore(self.runtime)
        self.capability_store.publish_catalog(self.phase32)
        self.capability_store.publish_policy(self.policy, self.phase32)
        self.route = self.capability_store.resolve_and_publish(
            self.task,
            self.phase32.catalog_id,
            self.policy.routing_policy_id,
        )
        self.registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.phase32)
        self.store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.registry,
        )
        self.store.publish_dispatch_catalog(self.dispatch_catalog)
        self.work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            self.route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
            },
        )
        self.store.publish_work_order(self.work_order)
        self.audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.registry,
            self.work_order,
        )
        self.store.publish_audit(self.audit)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_read_chain_and_currentness_leave_all_project_state_bytes_unchanged(self) -> None:
        state = self.runtime.state_dir
        before = _snapshot_tree(state)

        status = work_order_read_status(self.runtime)
        catalog = read_dispatch_catalog(
            self.runtime,
            self.dispatch_catalog.dispatch_catalog_id,
            self.registry,
        )
        work_order = read_work_order(
            self.runtime,
            self.work_order.work_order_id,
            self.registry,
        )
        audit = read_work_order_audit(
            self.runtime,
            self.audit.work_order_audit_id,
            self.registry,
        )
        currentness = inspect_work_order_currentness_readonly(
            self.runtime,
            self.work_order.work_order_id,
            self.audit.work_order_audit_id,
            self.registry,
        )

        self.assertEqual(status["dispatch_catalogs"], 1)
        self.assertEqual(status["work_orders"], 1)
        self.assertEqual(status["audits"], 1)
        self.assertEqual(catalog, self.dispatch_catalog)
        self.assertEqual(work_order, self.work_order)
        self.assertEqual(audit, self.audit)
        self.assertEqual(currentness.status, WorkOrderCurrentnessStatus.CURRENT_READY)
        self.assertEqual(
            currentness.dependency_readiness_status,
            DependencyReadinessStatus.READY,
        )

        after = _snapshot_tree(state)
        self.assertEqual(before, after)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(self.runtime.store.db_path) + suffix).exists())

    def test_uninitialized_status_creates_no_origin_forge_state(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            root = Path(other)
            runtime = OriginForgeRuntime(root)
            status = work_order_read_status(runtime)
            self.assertEqual(
                status,
                {
                    "initialized": False,
                    "evidence_root_present": False,
                    "dispatch_catalogs": 0,
                    "work_orders": 0,
                    "audits": 0,
                },
            )
            self.assertFalse((root / ".origin-forge").exists())

    def test_task_revision_drift_reports_stale_without_invalidating_history(self) -> None:
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)

        historical_work_order = read_work_order(
            self.runtime,
            self.work_order.work_order_id,
            self.registry,
        )
        historical_audit = read_work_order_audit(
            self.runtime,
            self.audit.work_order_audit_id,
            self.registry,
        )
        currentness = inspect_work_order_currentness_readonly(
            self.runtime,
            self.work_order.work_order_id,
            self.audit.work_order_audit_id,
            self.registry,
        )

        self.assertEqual(historical_work_order, self.work_order)
        self.assertEqual(historical_audit, self.audit)
        self.assertEqual(
            currentness.status,
            WorkOrderCurrentnessStatus.STALE_TASK_ROUTE,
        )
        self.assertIsNone(currentness.dependency_readiness_status)

    def test_self_consistently_rehashed_work_order_tamper_fails_read(self) -> None:
        import json
        from origin_forge.production_work_order_models import content_hash

        path = (
            self.runtime.state_dir
            / "production-work-orders"
            / "work-orders"
            / f"{self.work_order.work_order_id}.json"
        )
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["payload"] = {
            "context_mode": "manual",
            "selected_paths": [],
            "context_seed_paths": [],
            "structural_context": False,
            "semantic_context": False,
        }
        envelope["content_hash"] = content_hash(envelope["payload"])
        path.write_text(
            json.dumps(
                envelope,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ProductionWorkOrderReadError):
            read_work_order(
                self.runtime,
                self.work_order.work_order_id,
                self.registry,
            )

    def test_symlinked_work_order_object_fails_closed(self) -> None:
        path = (
            self.runtime.state_dir
            / "production-work-orders"
            / "work-orders"
            / f"{self.work_order.work_order_id}.json"
        )
        outside = self.root / "outside-work-order.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(
            ProductionWorkOrderReadError,
            "may not be a symlink",
        ):
            read_work_order(
                self.runtime,
                self.work_order.work_order_id,
                self.registry,
            )

    def test_reader_source_has_no_writer_model_or_execution_call_surface(self) -> None:
        source = inspect.getsource(read_module)
        self.assertNotIn("ProductionWorkOrderStore(", source)
        self.assertNotIn("ScheduledModelAdapter", source)
        tree = ast.parse(source)
        forbidden_calls = {
            "publish_dispatch_catalog",
            "publish_work_order",
            "publish_audit",
            "transition_task",
            "start_run",
            "create_run",
            "generate",
            "drive",
            "execute_adapter",
            "dispatch",
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called_attributes | called_names))


if __name__ == "__main__":
    unittest.main()
