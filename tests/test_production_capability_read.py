from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_capability_cli as capability_cli_module
import origin_forge.production_capability_read as capability_read_module
from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    TrustedProductionAdapter,
)
from origin_forge.production_capability_read import (
    ProductionCapabilityReadError,
    capability_read_status,
    inspect_task_route,
    read_capability_catalog,
    read_capability_policy,
    read_capability_route,
)
from origin_forge.production_capability_routing import resolve_task_route
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.runtime import OriginForgeRuntime


class ProductionCapabilityReadTests(unittest.TestCase):
    def test_uninitialized_status_creates_no_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            self.assertFalse(runtime.state_dir.exists())
            status = capability_read_status(runtime)
            self.assertFalse(status["initialized"])
            self.assertFalse(status["evidence_root_present"])
            self.assertFalse(runtime.state_dir.exists())

    def test_initialized_without_capability_evidence_does_not_create_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("capability-read-empty")
            evidence_root = runtime.state_dir / "production-capabilities"
            self.assertFalse(evidence_root.exists())
            status = capability_read_status(runtime)
            self.assertTrue(status["initialized"])
            self.assertFalse(status["evidence_root_present"])
            self.assertFalse(evidence_root.exists())

    def _fixture(self, temp: str):
        runtime = OriginForgeRuntime(temp)
        runtime.initialize("capability-read")
        goal = runtime.create_goal("route code")
        flow = runtime.create_flow(goal)
        task = runtime.create_task(
            flow,
            "change code",
            acceptance_criteria=("tests pass",),
            constraints=("bounded",),
            required_capabilities=("code.change",),
        )
        capability = ProductionCapability(
            "code.change",
            "Code change",
            "bounded coding",
            CapabilityDomain.CODE,
            "1",
        )
        adapter = TrustedProductionAdapter(
            "code.bounded",
            "code",
            "1",
            "a" * 64,
            ("code.change",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
        )
        catalog = CapabilityCatalog.create((capability,), (adapter,))
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("code.bounded",),
            allowed_capability_ids=("code.change",),
        )
        writer = ProductionCapabilityStore(runtime)
        writer.publish_catalog(catalog)
        writer.publish_policy(policy, catalog)
        decision = writer.resolve_and_publish(
            task,
            catalog.catalog_id,
            policy.routing_policy_id,
        )
        return runtime, task, catalog, policy, decision

    def test_read_objects_and_task_route_leave_database_and_evidence_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, task, catalog, policy, decision = self._fixture(temp)
            database = runtime.store.db_path
            files = sorted(
                (runtime.state_dir / "production-capabilities").rglob("*.json")
            )
            before_db = database.stat()
            before_files = {path: path.read_bytes() for path in files}
            before_names = {path.name for path in runtime.state_dir.iterdir()}

            loaded_catalog = read_capability_catalog(runtime, catalog.catalog_id)
            loaded_policy = read_capability_policy(runtime, policy.routing_policy_id)
            loaded_route = read_capability_route(runtime, decision.route_decision_id)
            read_resolution = inspect_task_route(
                runtime,
                task,
                catalog.catalog_id,
                policy.routing_policy_id,
            )
            authoritative = resolve_task_route(runtime.store, task, catalog, policy)

            self.assertEqual(loaded_catalog.to_dict(), catalog.to_dict())
            self.assertEqual(loaded_policy.to_dict(), policy.to_dict())
            self.assertEqual(loaded_route.to_dict(), decision.to_dict())
            self.assertEqual(read_resolution.to_dict(), authoritative.to_dict())
            after_db = database.stat()
            self.assertEqual(
                (after_db.st_dev, after_db.st_ino, after_db.st_size, after_db.st_mtime_ns),
                (before_db.st_dev, before_db.st_ino, before_db.st_size, before_db.st_mtime_ns),
            )
            self.assertEqual(
                {path.name for path in runtime.state_dir.iterdir()},
                before_names,
            )
            for path, value in before_files.items():
                self.assertEqual(path.read_bytes(), value)
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(database) + suffix).exists())

    def test_symlinked_evidence_object_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, _, catalog, _, _ = self._fixture(temp)
            path = (
                runtime.state_dir
                / "production-capabilities"
                / "catalogs"
                / f"{catalog.catalog_id}.json"
            )
            outside = runtime.project_root / "outside.json"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            try:
                path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ProductionCapabilityReadError, "may not be a symlink"):
                read_capability_catalog(runtime, catalog.catalog_id)

    def test_malformed_canonical_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime, _, catalog, _, _ = self._fixture(temp)
            path = (
                runtime.state_dir
                / "production-capabilities"
                / "catalogs"
                / f"{catalog.catalog_id}.json"
            )
            envelope = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(ProductionCapabilityReadError, "not canonical"):
                read_capability_catalog(runtime, catalog.catalog_id)

    def test_read_and_cli_sources_have_no_write_or_execution_authority(self) -> None:
        source = inspect.getsource(capability_read_module) + inspect.getsource(
            capability_cli_module
        )
        for forbidden in (
            "resolve_and_publish(",
            "publish_catalog(",
            "publish_policy(",
            "transition_task(",
            "start_run(",
            ".generate(",
            ".acquire(",
            "adopt_artifact",
            "sign_artifact",
            "merge_pull_request",
            "subprocess.",
            "os.system(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("production_read_connection", source)
        self.assertIn("resolve_route_input", source)


if __name__ == "__main__":
    unittest.main()
