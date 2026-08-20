from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from origin_forge.blender_adapter import BlenderExecution, BlenderRuntimeProfile
from origin_forge.blender_models import BlenderBudget, BlenderJobRequest
from origin_forge.blockbench_glb import inspect_glb
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.production_blender_export import (
    BlenderExportService,
    ProductionBlenderExportError,
)
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.state import RunStatus, TaskStatus


def _chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    if len(payload) % 4:
        payload += pad * (4 - len(payload) % 4)
    return struct.pack("<II", len(payload), kind) + payload


def _minimal_glb() -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "phase51e-fake-blender"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "OF_CUBOID_crate", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}
        ],
        "bufferViews": [{"buffer": 0, "byteLength": 12}],
        "buffers": [{"byteLength": 12}],
    }
    json_chunk = _chunk(
        0x4E4F534A,
        json.dumps(root, separators=(",", ":")).encode("utf-8"),
        b" ",
    )
    bin_chunk = _chunk(0x004E4942, b"\x00" * 12, b"\x00")
    length = 12 + len(json_chunk) + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, length) + json_chunk + bin_chunk


class _FakeBlenderAdapter:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: BlenderRuntimeProfile,
        *,
        corrupt_output: bool = False,
    ):
        self.runtime = runtime
        self.profile = profile
        self.corrupt_output = corrupt_output
        self.calls = 0
        self.request_was_durable_before_call = False

    def execute(self, request: BlenderJobRequest) -> BlenderExecution:
        self.calls += 1
        evidence_root = self.runtime.state_dir / "blender-production-export-evidence"
        request_files = tuple(evidence_root.glob("*/request.json"))
        self.request_was_durable_before_call = len(request_files) == 1

        workspace = self.runtime.state_dir / "model3d-workspaces" / request.workspace_id
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        output = workspace / request.output_relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        valid = _minimal_glb()
        inspection = inspect_glb(valid)
        output.write_bytes(b"not-a-glb" if self.corrupt_output else valid)
        return BlenderExecution(
            request=request,
            workspace_path=workspace,
            output_path=output,
            inspection=inspection,
            blender_version=self.profile.expected_blender_version,
            runtime_hash=self.profile.runtime_hash,
            runner_fingerprint=self.profile.runner_fingerprint,
            stdout=b"fake blender output",
            stderr=b"",
        )


class Phase51EBlenderExportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51e-blender-export-service")
        goal = self.runtime.create_goal("persist governed Blender output")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow,
            "export governed Blender GLB",
            required_capabilities=("media.3d.blender",),
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        self.project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="body",
                    name="Body",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 3, 4),
                    origin=Vec3(0, 0, 0),
                    rotation=Vec3(0, 0, 0),
                ),
            ),
        )
        self.profile = BlenderRuntimeProfile(
            runtime_root=(self.root / "trusted-blender-runtime").resolve(),
            executable=(self.root / "trusted-blender-runtime" / "blender").resolve(),
            runtime_hash="sha256:" + "1" * 64,
            expected_blender_version="Blender 5.2.0",
            runner_fingerprint="sha256:" + "2" * 64,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _running(self) -> None:
        self.runtime.transition_task(
            self.task_id,
            TaskStatus.RUNNING,
            expected_revision=1,
        )

    def _request(self) -> BlenderJobRequest:
        return BlenderJobRequest.create(
            project=self.project,
            output_relative_path="exports/model.glb",
            runner_fingerprint=self.profile.runner_fingerprint,
            runtime_hash=self.profile.runtime_hash,
            expected_blender_version=self.profile.expected_blender_version,
            budget=BlenderBudget(),
        )

    def test_success_persists_exact_request_result_glb_and_verification_without_task_outcome(self) -> None:
        self._running()
        service = BlenderExportService(self.runtime, self.profile)
        fake = _FakeBlenderAdapter(self.runtime, self.profile)
        service.adapter = fake
        request = self._request()

        result = service.execute(self.task_id, request)

        self.assertEqual(fake.calls, 1)
        self.assertTrue(fake.request_was_durable_before_call)
        self.assertEqual(result.operation.request, request)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["task_id"], self.task_id)
        self.assertEqual(run["role"], BlenderExportService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)

        request_artifact = service.lineage.get_artifact(result.request_artifact_id)
        result_artifact = service.lineage.get_artifact(result.result_artifact_id)
        output_artifact = service.lineage.get_artifact(result.output_artifact_id)
        self.assertEqual(request_artifact["type"], "BLENDER_JOB_REQUEST")
        self.assertEqual(request_artifact["status"], "CAPTURED")
        self.assertIsNone(request_artifact["parent_artifact_id"])
        self.assertEqual(result_artifact["type"], "BLENDER_EXECUTION_RESULT")
        self.assertEqual(result_artifact["parent_artifact_id"], result.request_artifact_id)
        self.assertEqual(output_artifact["type"], "BLENDER_GLB_EXPORT")
        self.assertEqual(output_artifact["parent_artifact_id"], result.result_artifact_id)
        self.assertEqual(output_artifact["status"], "PRODUCED")
        self.assertEqual(
            output_artifact["content_hash"],
            result.operation.inspection.content_hash,
        )
        self.assertEqual(
            output_artifact["path_or_uri"],
            f".origin-forge/model3d-workspaces/{request.workspace_id}/exports/model.glb",
        )

        output_verifications = service.lineage.list_artifact_verifications(
            result.output_artifact_id
        )
        self.assertEqual(len(output_verifications), 1)
        self.assertEqual(output_verifications[0]["id"], result.output_verification_id)
        self.assertEqual(
            output_verifications[0]["verification_type"],
            "blender-glb-export-integrity",
        )
        self.assertEqual(output_verifications[0]["status"], "PASS")
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(run_verifications[0]["id"], result.run_verification_id)
        self.assertEqual(run_verifications[0]["verification_type"], "blender-export-glb")
        self.assertEqual(run_verifications[0]["status"], "PASS")
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])
        self.assertFalse(result.to_dict()["provenance_signed"])

    def test_service_requires_running_task_before_run_or_adapter(self) -> None:
        service = BlenderExportService(self.runtime, self.profile)
        fake = _FakeBlenderAdapter(self.runtime, self.profile)
        service.adapter = fake
        with self.assertRaisesRegex(RuntimeInvariantError, "requires RUNNING Task"):
            service.execute(self.task_id, self._request())
        self.assertEqual(fake.calls, 0)
        self.assertEqual(self.runtime.list_runs(self.task_id), [])
        self.assertFalse(
            (self.runtime.state_dir / "blender-production-export-evidence").exists()
        )

    def test_independent_glb_reinspection_fails_run_without_task_terminalization(self) -> None:
        self._running()
        service = BlenderExportService(self.runtime, self.profile)
        fake = _FakeBlenderAdapter(self.runtime, self.profile, corrupt_output=True)
        service.adapter = fake
        with self.assertRaisesRegex(
            ProductionBlenderExportError,
            "independent GLB inspection",
        ):
            service.execute(self.task_id, self._request())
        self.assertEqual(fake.calls, 1)
        runs = self.runtime.list_runs(self.task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], BlenderExportService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(
            self.runtime.get_task(self.task_id)["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertEqual(self.runtime.list_verifications("TASK", self.task_id), [])


if __name__ == "__main__":
    unittest.main()
