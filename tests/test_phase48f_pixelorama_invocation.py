from __future__ import annotations

import ast
import binascii
import hashlib
import inspect
import os
import struct
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_dispatch_invocation as invocation_module
from origin_forge.ids import IdKind, validate_id
from origin_forge.pixelorama_cli_export import PixeloramaCliExportResult
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
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
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_pixelorama_export import (
    PixeloramaCliExportService,
    PixeloramaCliExportServiceResult,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_SOURCE_ARTIFACT_TYPE,
    PIXELORAMA_SOURCE_ROLE,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\x00\xff\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


class _FakeCliAdapter:
    def __init__(self, runtime: OriginForgeRuntime, version: str):
        self.runtime = runtime
        self.version = version
        self.calls = 0

    def execute(self, request, *, source_path):
        self.calls += 1
        workspace = self.runtime.state_dir / "media-workspaces" / request.workspace_id
        (workspace / "inputs").mkdir(parents=True)
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        output = workspace / request.output_relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        data = _png()
        output.write_bytes(data)
        return PixeloramaCliExportResult(
            request=request,
            workspace_path=workspace,
            pixelorama_version=self.version,
            process_exit_code=0,
            output_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            output_byte_count=len(data),
            width=1,
            height=1,
            stdout=b"ok\n",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class Phase48FPixeloramaInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase48f-pixelorama-invocation")
        goal = self.runtime.create_goal("invoke governed Pixelorama export")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export one governed Pixelorama project",
            required_capabilities=("media.2d.export",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        self.source = self.root / "assets" / "player.pxo"
        self.source.parent.mkdir()
        self.source.write_bytes(b"opaque-pixelorama-project\n")
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter(PIXELORAMA_ADAPTER_ID),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=(PIXELORAMA_ADAPTER_ID,),
            allowed_capability_ids=("media.2d.export",),
        )
        cap_store = ProductionCapabilityStore(self.runtime)
        cap_store.publish_catalog(catalog)
        cap_store.publish_policy(policy, catalog)
        route = cap_store.resolve_and_publish(
            self.task_id,
            catalog.catalog_id,
            policy.routing_policy_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        source_artifact_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type=PIXELORAMA_SOURCE_ARTIFACT_TYPE,
            path_or_uri="assets/player.pxo",
            content_hash=self.source_hash,
        )
        ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            source_artifact_id,
            self.source_hash,
            PIXELORAMA_SOURCE_ROLE,
            None,
        )
        work_order = create_current_work_order(
            self.runtime,
            cap_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            input_refs=(ref,),
            payload={},
        )
        wo_audit = audit_work_order_frozen(
            cap_store,
            dispatch_catalog,
            validators,
            work_order,
        )
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(wo_audit)
        bundle = create_input_resolution_bundle(
            wo_store,
            resolvers,
            work_order.work_order_id,
            wo_audit.work_order_audit_id,
        )
        binding = create_dispatch_binding(
            wo_store,
            resolvers,
            binders,
            bundle,
        )
        binding_audit = audit_dispatch_binding_frozen(
            wo_store,
            resolvers,
            binders,
            bundle,
            binding,
        )
        dispatch_store = ProductionDispatchStore(wo_store, resolvers, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            1,
        )
        self.env = {
            "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE": str(
                (self.root / "tools" / "Pixelorama").resolve()
            ),
            "ORIGIN_FORGE_PIXELORAMA_SHA256": "sha256:" + "1" * 64,
            "ORIGIN_FORGE_PIXELORAMA_VERSION": "v1.2-stable",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _execution(self) -> dict[str, object]:
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatch_executions WHERE claim_id = ?",
                (self.claim.claim_id,),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        return dict(rows[0])

    def _real_service_with_fake_adapter(self, service, task_id, request, *, source_path):
        row = self._execution()
        self.assertEqual(row["status"], DispatchExecutionStatus.STARTED.value)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(source_path, self.source.resolve())
        self.assertTrue(validate_id(request.operation_id, IdKind.PIXELORAMA_OPERATION))
        self.assertTrue(validate_id(request.workspace_id, IdKind.MEDIA_WORKSPACE))
        self.assertEqual(request.source_hash, "sha256:" + self.source_hash)
        self.assertEqual(request.source_byte_count, self.source.stat().st_size)
        service.adapter = _FakeCliAdapter(
            self.runtime,
            self.env["ORIGIN_FORGE_PIXELORAMA_VERSION"],
        )
        return self.original_service_execute(
            service,
            task_id,
            request,
            source_path=source_path,
        )

    def test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns(self) -> None:
        self.original_service_execute = PixeloramaCliExportService.execute
        with patch.dict(os.environ, self.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=self._real_service_with_fake_adapter,
        ) as execute:
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

        self.assertEqual(execute.call_count, 1)
        self.assertIsNone(completed.policy_result)
        self.assertIsNone(completed.simulation_result)
        self.assertIsInstance(completed.pixelorama_result, PixeloramaCliExportServiceResult)
        self.assertEqual(completed.execution.status, DispatchExecutionStatus.RETURNED)
        self.assertEqual(
            completed.execution.execution_owner_id,
            "originforge.execution.pixelorama.spritesheet-export@1",
        )
        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.CONSUMED)
        self.assertEqual(claim.revision, 1)
        task = self.runtime.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(int(task["revision"]), 2)
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], PixeloramaCliExportService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

    def test_source_tamper_after_claim_raises_without_service_or_fallback(self) -> None:
        self.source.write_bytes(b"tampered-after-claim\n")
        with patch.dict(os.environ, self.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationError):
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 0)
        self.assertEqual(self._execution()["status"], DispatchExecutionStatus.RAISED.value)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.CONSUMED,
        )
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_ordinary_service_exception_records_raised_and_keeps_task_running(self) -> None:
        class PixeloramaFailure(RuntimeError):
            pass

        with patch.dict(os.environ, self.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=PixeloramaFailure("sensitive process text"),
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationError) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("sensitive process text", str(caught.exception))
        self.assertIn("PixeloramaFailure", str(caught.exception))
        self.assertEqual(self._execution()["status"], DispatchExecutionStatus.RAISED.value)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.CONSUMED,
        )
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)

    def test_base_exception_leaves_started_active_running_and_never_replays(self) -> None:
        with patch.dict(os.environ, self.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=KeyboardInterrupt(),
        ) as execute:
            with self.assertRaises(KeyboardInterrupt):
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(self._execution()["status"], DispatchExecutionStatus.STARTED.value)
        claim = read_dispatch_claim(self.runtime, self.claim.claim_id)
        self.assertEqual(claim.status, DispatchClaimStatus.ACTIVE)
        self.assertEqual(claim.revision, 0)
        self.assertEqual(self.runtime.get_task(self.task_id)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])

    def test_forged_typed_service_return_requires_recovery_without_false_returned(self) -> None:
        self.original_service_execute = PixeloramaCliExportService.execute

        def forged(service, task_id, request, *, source_path):
            result = self._real_service_with_fake_adapter(
                service,
                task_id,
                request,
                source_path=source_path,
            )
            return replace(result, output_artifact_id=result.request_artifact_id)

        with patch.dict(os.environ, self.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=forged,
        ) as execute:
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")
        self.assertEqual(self._execution()["status"], DispatchExecutionStatus.STARTED.value)
        self.assertEqual(
            read_dispatch_claim(self.runtime, self.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)

    def test_closed_coordinator_surface_has_exact_three_owner_call_sites_and_no_loop(self) -> None:
        legacy_source = inspect.getsource(invocation_module._legacy_dispatch_claim_once)
        public_source = inspect.getsource(invocation_module.dispatch_claim_once)
        tree = ast.parse(legacy_source + "\n" + public_source)
        drive_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "drive"
        ]
        execute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]
        self.assertEqual(len(drive_calls), 1)
        self.assertEqual(len(execute_calls), 2)
        self.assertFalse(
            any(isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in ast.walk(tree))
        )
        self.assertNotIn("importlib", public_source)
        self.assertNotIn("getattr(", public_source)
        self.assertNotIn("callable(", public_source)


if __name__ == "__main__":
    unittest.main()
