from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_dispatch_cli as cli_module
import origin_forge.production_dispatch_read as read_module
import origin_forge.production_dispatch_store as store_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_binding_models import (
    DispatchBindingCurrentnessStatus,
)
from origin_forge.production_dispatch_cli import build_parser, main as dispatch_cli_main
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_read import (
    inspect_dispatch_binding_currentness_readonly,
    production_dispatch_read_status,
    read_dispatch_binding,
    read_dispatch_binding_audit,
    read_input_resolution,
)
from origin_forge.production_dispatch_store import (
    ProductionDispatchStore,
    ProductionDispatchStoreError,
)
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


def _state_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    if not root.exists():
        return ()
    rows: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append((relative, b"<symlink>"))
        elif path.is_file():
            rows.append((relative, path.read_bytes()))
    return tuple(rows)


class ProductionDispatchStoreReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dispatch-store-read")
        goal = self.runtime.create_goal("persist audited dispatch binding")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
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
            self.task_id,
            self.phase32.catalog_id,
            self.policy.routing_policy_id,
        )

        self.validator_registry = build_builtin_dispatch_validator_registry()
        self.dispatch_catalog = build_builtin_dispatch_catalog(self.phase32)
        self.work_order_store = ProductionWorkOrderStore(
            self.runtime,
            self.capability_store,
            self.validator_registry,
        )
        self.work_order_store.publish_dispatch_catalog(self.dispatch_catalog)
        self.work_order = create_current_work_order(
            self.runtime,
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            self.route.route_decision_id,
            payload={
                "context_mode": "auto",
                "context_seed_paths": ["src/example.py"],
                "structural_context": True,
            },
        )
        self.work_order_audit = audit_work_order_frozen(
            self.capability_store,
            self.dispatch_catalog,
            self.validator_registry,
            self.work_order,
        )
        self.work_order_store.publish_work_order(self.work_order)
        self.work_order_store.publish_audit(self.work_order_audit)

        self.resolver_registry = build_dispatch_input_resolver_registry()
        self.binder_registry = build_builtin_dispatch_binder_registry()
        self.bundle = create_input_resolution_bundle(
            self.work_order_store,
            self.resolver_registry,
            self.work_order.work_order_id,
            self.work_order_audit.work_order_audit_id,
        )
        self.binding = create_dispatch_binding(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            self.bundle,
        )
        self.binding_audit = audit_dispatch_binding_frozen(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
            self.bundle,
            self.binding,
        )
        self.store = ProductionDispatchStore(
            self.work_order_store,
            self.resolver_registry,
            self.binder_registry,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _publish_chain(self) -> None:
        self.store.publish_input_resolution(self.bundle)
        self.store.publish_binding(self.binding)
        self.store.publish_audit(self.binding_audit)

    def test_complete_chain_round_trips_and_reconstructs_after_restart(self) -> None:
        self._publish_chain()
        self.assertEqual(
            self.store.load_input_resolution(self.bundle.input_resolution_id),
            self.bundle,
        )
        self.assertEqual(
            self.store.load_binding(self.binding.dispatch_binding_id),
            self.binding,
        )
        self.assertEqual(
            self.store.load_audit(self.binding_audit.binding_audit_id),
            self.binding_audit,
        )

        restarted_runtime = OriginForgeRuntime(self.root)
        restarted_capability = ProductionCapabilityStore(restarted_runtime)
        restarted_work_orders = ProductionWorkOrderStore(
            restarted_runtime,
            restarted_capability,
            build_builtin_dispatch_validator_registry(),
        )
        restarted = ProductionDispatchStore(
            restarted_work_orders,
            build_dispatch_input_resolver_registry(),
            build_builtin_dispatch_binder_registry(),
        )
        self.assertEqual(
            restarted.load_input_resolution(self.bundle.input_resolution_id),
            self.bundle,
        )
        self.assertEqual(
            restarted.load_binding(self.binding.dispatch_binding_id),
            self.binding,
        )
        self.assertEqual(
            restarted.load_audit(self.binding_audit.binding_audit_id),
            self.binding_audit,
        )

    def test_every_category_is_strict_no_overwrite(self) -> None:
        self._publish_chain()
        with self.assertRaisesRegex(ProductionDispatchStoreError, "already exists"):
            self.store.publish_input_resolution(self.bundle)
        with self.assertRaisesRegex(ProductionDispatchStoreError, "already exists"):
            self.store.publish_binding(self.binding)
        with self.assertRaisesRegex(ProductionDispatchStoreError, "already exists"):
            self.store.publish_audit(self.binding_audit)

    def test_payload_tamper_and_symlinked_object_fail_closed(self) -> None:
        self._publish_chain()
        binding_path = (
            self.runtime.state_dir
            / "production-dispatch-bindings"
            / "dispatch-bindings"
            / f"{self.binding.dispatch_binding_id}.json"
        )
        raw = json.loads(binding_path.read_text(encoding="utf-8"))
        raw["payload"]["request_projection"]["semantic_context"] = True
        binding_path.write_text(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with self.assertRaises(ProductionDispatchStoreError):
            self.store.load_binding(self.binding.dispatch_binding_id)

        self.tempdir.cleanup()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        runtime = OriginForgeRuntime(self.root)
        runtime.initialize("dispatch-symlink")
        evidence_root = runtime.state_dir / "production-dispatch-bindings"
        category = evidence_root / "input-resolutions"
        category.mkdir(parents=True)
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        link = category / f"{self.bundle.input_resolution_id}.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(Exception, "symlink"):
            read_input_resolution(runtime, self.bundle.input_resolution_id)

    def test_read_chain_and_currentness_leave_all_project_state_bytes_unchanged(self) -> None:
        self._publish_chain()
        before = _state_snapshot(self.runtime.state_dir)

        self.assertEqual(
            read_input_resolution(self.runtime, self.bundle.input_resolution_id),
            self.bundle,
        )
        self.assertEqual(
            read_dispatch_binding(self.runtime, self.binding.dispatch_binding_id),
            self.binding,
        )
        self.assertEqual(
            read_dispatch_binding_audit(
                self.runtime,
                self.binding_audit.binding_audit_id,
            ),
            self.binding_audit,
        )
        currentness = inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            self.bundle.input_resolution_id,
            self.binding.dispatch_binding_id,
            self.binding_audit.binding_audit_id,
            self.resolver_registry,
            self.binder_registry,
        )
        self.assertEqual(
            currentness.status,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
        )
        self.assertEqual(before, _state_snapshot(self.runtime.state_dir))

    def test_uninitialized_status_is_noncreating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = OriginForgeRuntime(root)
            state = runtime.state_dir
            self.assertFalse(state.exists())
            self.assertEqual(
                production_dispatch_read_status(runtime),
                {
                    "initialized": False,
                    "evidence_root_present": False,
                    "input_resolution_count": 0,
                    "dispatch_binding_count": 0,
                    "binding_audit_count": 0,
                    "authority": "read-only",
                },
            )
            self.assertFalse(state.exists())

    def test_read_and_store_sources_have_bounded_disjoint_authority(self) -> None:
        read_source = inspect.getsource(read_module)
        cli_source = inspect.getsource(cli_module)
        store_source = inspect.getsource(store_module)
        self.assertNotIn("subprocess", read_source)
        self.assertNotIn("importlib", read_source)
        self.assertNotIn("subprocess", cli_source)
        self.assertIn("open(\"xb\")", store_source)

        for source in (read_source, cli_source):
            tree = ast.parse(source)
            forbidden = {
                "drive",
                "execute",
                "generate",
                "dispatch",
                "transition_task",
                "start_run",
                "create_run",
                "finish_run",
                "publish_input_resolution",
                "publish_binding",
                "publish_audit",
                "mkdir",
                "write_bytes",
                "write_text",
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
            self.assertTrue(forbidden.isdisjoint(called))

    def test_cli_surface_is_strictly_inspection_only_and_byte_stable(self) -> None:
        parser = build_parser()
        command_action = next(
            action
            for action in parser._actions
            if getattr(action, "dest", None) == "command"
        )
        self.assertEqual(
            set(command_action.choices),
            {
                "status",
                "input-resolution-show",
                "binding-show",
                "binding-audit-show",
                "binding-currentness",
            },
        )
        for forbidden in ("create", "publish", "resolve", "bind", "audit", "dispatch", "run"):
            with self.assertRaises(SystemExit):
                parser.parse_args([forbidden])

        self._publish_chain()
        before = _state_snapshot(self.runtime.state_dir)
        commands = (
            ["--project-root", str(self.root), "status"],
            [
                "--project-root",
                str(self.root),
                "input-resolution-show",
                self.bundle.input_resolution_id,
            ],
            [
                "--project-root",
                str(self.root),
                "binding-show",
                self.binding.dispatch_binding_id,
            ],
            [
                "--project-root",
                str(self.root),
                "binding-audit-show",
                self.binding_audit.binding_audit_id,
            ],
            [
                "--project-root",
                str(self.root),
                "binding-currentness",
                self.bundle.input_resolution_id,
                self.binding.dispatch_binding_id,
                self.binding_audit.binding_audit_id,
            ],
        )
        for command in commands:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(dispatch_cli_main(command), 0)
            self.assertTrue(output.getvalue().strip().startswith("{"))
            self.assertEqual(before, _state_snapshot(self.runtime.state_dir))


if __name__ == "__main__":
    unittest.main()
