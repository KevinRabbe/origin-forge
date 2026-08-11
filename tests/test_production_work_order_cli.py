from __future__ import annotations

import argparse
import ast
import inspect
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import origin_forge.production_work_order_cli as cli_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_cli import build_parser, main
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not path.is_symlink()
    }


class ProductionWorkOrderCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("work-order-cli")
        goal = self.runtime.create_goal("inspect work orders from CLI")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(
            flow,
            "change code",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        phase32 = build_builtin_capability_catalog()
        policy = CapabilityRoutingPolicy.create(
            phase32,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(phase32)
        capability_store.publish_policy(policy, phase32)
        route = capability_store.resolve_and_publish(
            task,
            phase32.catalog_id,
            policy.routing_policy_id,
        )
        registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(phase32)
        store = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            registry,
        )
        store.publish_dispatch_catalog(self.dispatch_catalog)
        self.work_order = create_current_work_order(
            self.runtime,
            capability_store,
            self.dispatch_catalog,
            registry,
            route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
            },
        )
        store.publish_work_order(self.work_order)
        self.audit = audit_work_order_frozen(
            capability_store,
            self.dispatch_catalog,
            registry,
            self.work_order,
        )
        store.publish_audit(self.audit)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _commands() -> set[str]:
        parser = build_parser()
        action = next(
            value
            for value in parser._actions
            if isinstance(value, argparse._SubParsersAction)
        )
        return set(action.choices)

    def _call(self, *args: str) -> tuple[int, object]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_parser_exposes_only_read_only_inspection_commands(self) -> None:
        self.assertEqual(
            self._commands(),
            {
                "status",
                "dispatch-catalog-show",
                "contract-show",
                "work-order-show",
                "work-order-audit-show",
                "work-order-currentness",
            },
        )
        for forbidden in (
            "generate",
            "propose",
            "publish",
            "audit",
            "dispatch",
            "execute",
            "run",
            "transition",
            "adopt",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, self._commands())

    def test_help_and_uninitialized_status_create_no_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            root = Path(other)
            output = io.StringIO()
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as raised:
                    main(["--project-root", str(root), "--help"])
            self.assertEqual(raised.exception.code, 0)
            self.assertFalse((root / ".origin-forge").exists())

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", str(root), "status"])
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "initialized": False,
                    "evidence_root_present": False,
                    "dispatch_catalogs": 0,
                    "work_orders": 0,
                    "audits": 0,
                },
            )
            self.assertFalse((root / ".origin-forge").exists())

    def test_every_command_returns_revalidated_json_without_mutation(self) -> None:
        before = _snapshot_tree(self.runtime.state_dir)
        commands = (
            ("status",),
            ("dispatch-catalog-show", self.dispatch_catalog.dispatch_catalog_id),
            (
                "contract-show",
                self.dispatch_catalog.dispatch_catalog_id,
                "code.bounded-retry@1",
            ),
            ("work-order-show", self.work_order.work_order_id),
            ("work-order-audit-show", self.audit.work_order_audit_id),
            (
                "work-order-currentness",
                self.work_order.work_order_id,
                self.audit.work_order_audit_id,
            ),
        )
        results: list[object] = []
        for command in commands:
            code, payload = self._call(*command)
            self.assertEqual(code, 0, command)
            results.append(payload)

        self.assertEqual(results[0]["work_orders"], 1)
        self.assertEqual(
            results[1]["dispatch_catalog_id"],
            self.dispatch_catalog.dispatch_catalog_id,
        )
        self.assertEqual(results[2]["contract_id"], "code.bounded-retry@1")
        self.assertEqual(results[3]["work_order_id"], self.work_order.work_order_id)
        self.assertEqual(
            results[4]["work_order_audit_id"],
            self.audit.work_order_audit_id,
        )
        self.assertEqual(results[5]["status"], "CURRENT_READY")

        after = _snapshot_tree(self.runtime.state_dir)
        self.assertEqual(before, after)

    def test_cli_source_has_no_writer_model_or_execution_call_surface(self) -> None:
        source = inspect.getsource(cli_module)
        self.assertNotIn("ProductionWorkOrderStore", source)
        self.assertNotIn("ScheduledModelAdapter", source)
        tree = ast.parse(source)
        forbidden_calls = {
            "publish_dispatch_catalog",
            "publish_work_order",
            "publish_audit",
            "audit_work_order_frozen",
            "create_current_work_order",
            "generate",
            "transition_task",
            "start_run",
            "create_run",
            "dispatch",
            "drive",
            "execute",
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
