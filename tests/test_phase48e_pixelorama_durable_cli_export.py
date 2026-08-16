from __future__ import annotations

import binascii
import hashlib
import inspect
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import origin_forge.production_pixelorama_export as export_module
from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_cli_export import (
    PixeloramaCliExportRequest,
    PixeloramaCliExportResult,
    PixeloramaCliProfile,
    PixeloramaCliUnavailable,
)
from origin_forge.production_pixelorama_export import (
    PixeloramaCliExportService,
    ProductionPixeloramaExportError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _rgba_png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\xff\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


class _FakeCliAdapter:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        version: str,
        failure: Exception | None = None,
        wrong_hash: bool = False,
    ):
        self.runtime = runtime
        self.version = version
        self.failure = failure
        self.wrong_hash = wrong_hash
        self.calls = 0
        self.source_paths: list[Path] = []

    def execute(
        self,
        request: PixeloramaCliExportRequest,
        *,
        source_path: Path,
    ) -> PixeloramaCliExportResult:
        self.calls += 1
        self.source_paths.append(Path(source_path))
        if self.failure is not None:
            raise self.failure
        workspace = self.runtime.state_dir / "media-workspaces" / request.workspace_id
        (workspace / "inputs").mkdir(parents=True)
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        output = workspace / request.output_relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        data = _rgba_png()
        output.write_bytes(data)
        output_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        if self.wrong_hash:
            output_hash = "sha256:" + "0" * 64
        return PixeloramaCliExportResult(
            request=request,
            workspace_path=workspace,
            pixelorama_version=self.version,
            process_exit_code=0,
            output_hash=output_hash,
            output_byte_count=len(data),
            width=1,
            height=1,
            stdout=b"ok\n",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class Phase48EPixeloramaDurableCliExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase48e-pixelorama")
        self.lineage = OriginForgeLineage(self.runtime)
        goal = self.runtime.create_goal("Export governed Pixelorama spritesheet")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Export one opaque pxo")
        revision = self.runtime.transition_task(
            self.task,
            TaskStatus.READY,
            expected_revision=0,
        )
        self.runtime.transition_task(
            self.task,
            TaskStatus.RUNNING,
            expected_revision=revision,
        )
        self.source = self.root / "source.pxo"
        self.source.write_bytes(b"opaque-pixelorama-project\n")
        self.source_hash = "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.profile = PixeloramaCliProfile(
            pixelorama_executable=self.root / "pixelorama",
            pixelorama_fingerprint="sha256:" + "a" * 64,
            expected_pixelorama_version="1.2-test",
            timeout_seconds=5,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _request(self) -> PixeloramaCliExportRequest:
        return PixeloramaCliExportRequest.create(
            source_hash=self.source_hash,
            source_byte_count=self.source.stat().st_size,
            timeout_seconds=5,
            max_output_bytes=1024 * 1024,
        )

    def _service(self, adapter: _FakeCliAdapter) -> PixeloramaCliExportService:
        service = PixeloramaCliExportService(self.runtime, self.profile)
        service.adapter = adapter
        return service

    def test_success_persists_request_result_export_and_structural_evidence_only(self) -> None:
        request = self._request()
        adapter = _FakeCliAdapter(
            self.runtime,
            version=self.profile.expected_pixelorama_version,
        )
        service = self._service(adapter)
        before = self.runtime.get_task(self.task)

        result = service.execute(self.task, request, source_path=self.source)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(adapter.source_paths, [self.source])
        self.assertEqual(result.operation.request, request)
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], "PIXELORAMA")
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        after = self.runtime.get_task(self.task)
        self.assertEqual(after["status"], TaskStatus.RUNNING.value)
        self.assertEqual(after["revision"], before["revision"])

        request_path = self.lineage.local_artifact_path(result.request_artifact_id)
        result_path = self.lineage.local_artifact_path(result.result_artifact_id)
        self.assertEqual(json.loads(request_path.read_text()), request.to_dict())
        self.assertEqual(json.loads(result_path.read_text()), result.operation.to_dict())

        request_artifact = self.lineage.get_artifact(result.request_artifact_id)
        result_artifact = self.lineage.get_artifact(result.result_artifact_id)
        output_artifact = self.lineage.get_artifact(result.output_artifact_id)
        self.assertEqual(request_artifact["type"], "PIXELORAMA_CLI_EXPORT_REQUEST")
        self.assertEqual(request_artifact["created_by_run_id"], result.run_id)
        self.assertEqual(result_artifact["type"], "PIXELORAMA_CLI_EXPORT_RESULT")
        self.assertEqual(result_artifact["parent_artifact_id"], result.request_artifact_id)
        self.assertEqual(output_artifact["type"], "SPRITESHEET_EXPORT")
        self.assertEqual(output_artifact["parent_artifact_id"], result.result_artifact_id)
        self.assertEqual(output_artifact["content_hash"], result.operation.output_hash)

        output_verifications = self.lineage.list_artifact_verifications(
            result.output_artifact_id
        )
        self.assertEqual(len(output_verifications), 1)
        self.assertEqual(output_verifications[0]["id"], result.output_verification_id)
        self.assertEqual(output_verifications[0]["status"], "PASS")
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(run_verifications[0]["id"], result.run_verification_id)
        self.assertEqual(run_verifications[0]["status"], "PASS")
        projection = result.to_dict()
        self.assertFalse(projection["task_status_changed"])
        self.assertFalse(projection["canonical_asset_adopted"])
        self.assertFalse(projection["provenance_signed"])

    def test_adapter_failure_keeps_request_evidence_and_fails_run_not_task(self) -> None:
        request = self._request()
        adapter = _FakeCliAdapter(
            self.runtime,
            version=self.profile.expected_pixelorama_version,
            failure=PixeloramaCliUnavailable("synthetic CLI failure"),
        )
        service = self._service(adapter)
        before = self.runtime.get_task(self.task)

        with self.assertRaisesRegex(PixeloramaCliUnavailable, "synthetic CLI failure"):
            service.execute(self.task, request, source_path=self.source)

        self.assertEqual(adapter.calls, 1)
        after = self.runtime.get_task(self.task)
        self.assertEqual(after["status"], TaskStatus.RUNNING.value)
        self.assertEqual(after["revision"], before["revision"])
        runs = self.runtime.list_runs(self.task)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        artifacts = self.lineage.list_artifacts()
        self.assertEqual(
            [value["type"] for value in artifacts],
            ["PIXELORAMA_CLI_EXPORT_REQUEST"],
        )
        self.assertEqual(
            json.loads(self.lineage.local_artifact_path(artifacts[0]["id"]).read_text()),
            request.to_dict(),
        )
        verifications = self.runtime.list_verifications("RUN", runs[0]["id"])
        self.assertEqual(len(verifications), 1)
        self.assertEqual(verifications[0]["status"], "FAIL")

    def test_independent_rehash_rejects_typed_output_drift_and_fails_run_only(self) -> None:
        request = self._request()
        adapter = _FakeCliAdapter(
            self.runtime,
            version=self.profile.expected_pixelorama_version,
            wrong_hash=True,
        )
        service = self._service(adapter)
        before = self.runtime.get_task(self.task)

        with self.assertRaisesRegex(
            ProductionPixeloramaExportError,
            "typed CLI result",
        ):
            service.execute(self.task, request, source_path=self.source)

        self.assertEqual(adapter.calls, 1)
        after = self.runtime.get_task(self.task)
        self.assertEqual(after["status"], TaskStatus.RUNNING.value)
        self.assertEqual(after["revision"], before["revision"])
        runs = self.runtime.list_runs(self.task)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        artifacts = self.lineage.list_artifacts()
        self.assertEqual(
            [value["type"] for value in artifacts],
            ["PIXELORAMA_CLI_EXPORT_REQUEST", "PIXELORAMA_CLI_EXPORT_RESULT"],
        )
        self.assertFalse(
            any(value["type"] == "SPRITESHEET_EXPORT" for value in artifacts)
        )

    def test_service_surface_does_not_gain_task_adoption_signing_or_generic_bridge_authority(self) -> None:
        source = inspect.getsource(export_module)
        for forbidden in (
            "PixeloramaOutputAdopter",
            "PixeloramaBridgeAdapter",
            "transition_task(",
            "CREATE_SPRITE_PROJECT",
            "IMPORT_LAYER_PNG",
            "SAVE_PROJECT",
            "sign_manifest",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, source)
        self.assertEqual(PixeloramaCliExportService.RUN_ROLE, "PIXELORAMA")


if __name__ == "__main__":
    unittest.main()
