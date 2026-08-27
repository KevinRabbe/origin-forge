from __future__ import annotations

import hashlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.pixelorama_bridge import PixeloramaBridgeProfile
from origin_forge.pixelorama_media import (
    PixeloramaMediaError,
    PixeloramaMediaService,
    PixeloramaOutputAdopter,
)
from origin_forge.pixelorama_models import (
    BridgeBudget,
    BridgeOperation,
    BridgeOutputType,
    BridgeResultStatus,
    ExportSpec,
    FrameSpec,
    PixeloramaBridgeRequest,
    RasterLayerSpec,
    SpriteProjectSpec,
)
from origin_forge.pixelorama_source import (
    build_pixelorama_source_work_order_payload_from_accepted_design,
    create_pixelorama_source,
    create_pixelorama_source_from_accepted_design,
)
from origin_forge.production_design_specification_models import DesignAnimationIntent
from origin_forge.production_design_specification_currentness import AcceptedDesignError
from origin_forge.review import record_task_review_decision
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus

BRIDGE = r'''import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(width, height, empty=False):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            if not empty and x == 0 and y == 0:
                raw.extend((255, 0, 0, 255))
            else:
                raw.extend((0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")

args = sys.argv[1:]
args = args[args.index("--") + 1:]
request_path = Path(args[args.index("--origin-forge-request") + 1])
result_path = Path(args[args.index("--origin-forge-result") + 1])
request = json.loads(request_path.read_text())
spec = request["sprite_spec"]
fingerprint = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
outputs = []
project = Path("project") / (spec["output_basename"] + ".pxo")
project.write_bytes(b"fake project\n")
outputs.append({
    "output_type": "PIXELORAMA_PROJECT",
    "relative_path": project.as_posix(),
    "content_hash": "sha256:" + hashlib.sha256(project.read_bytes()).hexdigest(),
    "byte_count": project.stat().st_size,
    "width": None,
    "height": None,
})
empty = "empty" in Path(__file__).stem
for export in request["export_specs"]:
    path = Path(export["relative_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    data = png(spec["width"], spec["height"], empty=empty)
    path.write_bytes(data)
    outputs.append({
        "output_type": export["output_type"],
        "relative_path": path.as_posix(),
        "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "width": spec["width"],
        "height": spec["height"],
    })
outputs.sort(key=lambda value: value["relative_path"])
result = {
    "protocol_version": 1,
    "operation_id": request["operation_id"],
    "request_hash": request["content_hash"],
    "status": "SUCCEEDED",
    "pixelorama_version": "fake-pixelorama",
    "bridge_version": "test-bridge-1",
    "bridge_fingerprint": fingerprint,
    "outputs": outputs,
    "diagnostics": [],
    "elapsed_ms": 2,
}
result["content_hash"] = canonical_hash(result)
result_path.write_text(json.dumps(result, sort_keys=True))
'''


class PixeloramaMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("pixelorama-media-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.goal = self.runtime.create_goal("Create a 2D asset")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Create sprite")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )
        self.tools = self.root / "tools"
        self.tools.mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _script(self, name: str = "bridge.py") -> Path:
        path = self.tools / name
        path.write_text(textwrap.dedent(BRIDGE), encoding="utf-8")
        return path

    @staticmethod
    def _fingerprint(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def _profile(self, script: Path) -> PixeloramaBridgeProfile:
        return PixeloramaBridgeProfile(
            bridge_id="origin-forge-pixelorama-test",
            bridge_version="test-bridge-1",
            bridge_fingerprint=self._fingerprint(script),
            pixelorama_executable=Path(sys.executable).resolve(),
            bridge_package=script,
            allowed_operations=(BridgeOperation.CREATE_SPRITE_PROJECT,),
            launcher_args=(str(script),),
            timeout_seconds=5,
        )

    @staticmethod
    def _request() -> PixeloramaBridgeRequest:
        spec = SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("idle-0"),),
            output_basename="media-test",
        )
        return PixeloramaBridgeRequest.create(
            operation=BridgeOperation.CREATE_SPRITE_PROJECT,
            sprite_spec=spec,
            export_specs=(ExportSpec(BridgeOutputType.PNG, "exports/frame.png"),),
            budget=BridgeBudget(timeout_seconds=5),
        )

    @staticmethod
    def _assert_run_did_not_complete_task(
        before_task: dict[str, object],
        after_task: dict[str, object],
    ) -> None:
        if after_task["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("Pixelorama Run changed production Task status")
        if after_task["revision"] != before_task["revision"]:
            raise AssertionError("Pixelorama Run changed production Task revision")
        if after_task["attempt_count"] != before_task["attempt_count"] + 1:
            raise AssertionError("Pixelorama Run did not record exactly one Task attempt")
        if after_task["assigned_run_id"] is not None:
            raise AssertionError("finished Pixelorama Run left Task assigned")

    def test_media_run_records_artifacts_and_verification_without_completing_task(self) -> None:
        script = self._script()
        before_task = self.runtime.get_task(self.task)
        result = PixeloramaMediaService(
            self.runtime,
            self._profile(script),
        ).execute(self.task, self._request())

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], PixeloramaMediaService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self._assert_run_did_not_complete_task(
            before_task,
            self.runtime.get_task(self.task),
        )
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertEqual(len(result.output_evidence), 2)
        output_types = {value.output_type for value in result.output_evidence}
        self.assertEqual(
            output_types,
            {BridgeOutputType.PNG, BridgeOutputType.PIXELORAMA_PROJECT},
        )
        for output in result.output_evidence:
            verifications = self.lineage.list_artifact_verifications(output.artifact_id)
            self.assertEqual(len(verifications), 1)
            self.assertEqual(verifications[0]["status"], "PASS")
            self.assertEqual(
                verifications[0]["verification_type"],
                "pixelorama-output-integrity",
            )
        run_verifications = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(run_verifications[0]["status"], "PASS")

    def test_governed_source_creation_uses_bounded_bridge_and_returns_project_evidence(self) -> None:
        script = self._script("create-source-bridge.py")
        request = self._request()
        result = create_pixelorama_source(
            self.runtime,
            self.task,
            self._profile(script),
            request.sprite_spec,
            export_specs=request.export_specs,
            budget=request.budget,
        )
        project_outputs = [
            value
            for value in result.output_evidence
            if value.output_type is BridgeOutputType.PIXELORAMA_PROJECT
        ]
        self.assertEqual(len(project_outputs), 1)
        self.assertEqual(result.operation.bridge_result.status, BridgeResultStatus.SUCCEEDED)
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])

    def test_source_creation_from_accepted_design_records_exact_lineage(self) -> None:
        request = self._request()
        expected = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id="DESIGNACC-accepted",
                content_hash="sha256:" + "a" * 64,
                project_id=self.runtime.project_id(),
            ),
            design_input=SimpleNamespace(design_input_id="DESIGNIN-input"),
            current=True,
            stale_reason=None,
        )
        result = SimpleNamespace(run_id="RUN-pixelorama")
        with (
            patch(
                "origin_forge.pixelorama_source.bridge_accepted_design_to_planning_input",
                return_value=SimpleNamespace(
                    planning_input_id="PLAN-input",
                    content_hash="sha256:" + "c" * 64,
                ),
            ),
            patch(
                "origin_forge.pixelorama_source.inspect_accepted_design",
                return_value=expected,
            ),
            patch(
                "origin_forge.pixelorama_source.PixeloramaMediaService.execute",
                return_value=result,
            ) as execute,
        ):
            actual = create_pixelorama_source_from_accepted_design(
                self.runtime,
                self.task,
                "DESIGNACC-accepted",
                self._profile(self._script("accepted-design-bridge.py")),
                request.sprite_spec,
                export_specs=request.export_specs,
                budget=request.budget,
            )
        self.assertIs(actual, result)
        lineage = execute.call_args.kwargs["accepted_design_lineage"]
        self.assertEqual(
            lineage,
            {
                "acceptance_id": "DESIGNACC-accepted",
                "acceptance_hash": "sha256:" + "a" * 64,
                "design_input_id": "DESIGNIN-input",
                "planning_input_id": "PLAN-input",
                "planning_input_hash": "sha256:" + "c" * 64,
            },
        )

    def test_accepted_design_animation_intent_binds_to_source_request(self) -> None:
        request = self._request()
        sprite_spec = SpriteProjectSpec(
            2,
            2,
            request.sprite_spec.layers,
            (FrameSpec("idle-0"), FrameSpec("idle-1"), FrameSpec("idle-2")),
            output_basename=request.sprite_spec.output_basename,
        )
        expected = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id="DESIGNACC-animation",
                content_hash="sha256:" + "a" * 64,
                project_id=self.runtime.project_id(),
            ),
            design_input=SimpleNamespace(design_input_id="DESIGNIN-input"),
            specification=SimpleNamespace(
                deliverables=(
                    SimpleNamespace(
                        animation_intents=(
                            DesignAnimationIntent("idle", 2, 120, "LOOP", 1),
                        ),
                    ),
                ),
            ),
            current=True,
            stale_reason=None,
        )
        with (
            patch(
                "origin_forge.pixelorama_source.bridge_accepted_design_to_planning_input",
                return_value=SimpleNamespace(
                    planning_input_id="PLAN-input",
                    content_hash="sha256:" + "c" * 64,
                ),
            ),
            patch("origin_forge.pixelorama_source.inspect_accepted_design", return_value=expected),
            patch(
                "origin_forge.pixelorama_source.PixeloramaMediaService.execute",
                return_value=SimpleNamespace(run_id="RUN-animation"),
            ) as execute,
        ):
            create_pixelorama_source_from_accepted_design(
                self.runtime,
                self.task,
                "DESIGNACC-animation",
                self._profile(self._script("animation-bridge.py")),
                sprite_spec,
                export_specs=request.export_specs,
                budget=request.budget,
            )
        bound_request = execute.call_args.args[1]
        self.assertEqual(bound_request.sprite_spec.animations[0].name, "idle")
        self.assertEqual(bound_request.sprite_spec.animations[0].first_frame, 1)
        self.assertEqual(bound_request.sprite_spec.animations[0].last_frame, 2)

    def test_design_animation_range_cannot_exceed_supplied_frames(self) -> None:
        expected = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id="DESIGNACC-overrun",
                content_hash="sha256:" + "a" * 64,
                project_id=self.runtime.project_id(),
            ),
            design_input=SimpleNamespace(design_input_id="DESIGNIN-input"),
            specification=SimpleNamespace(
                deliverables=(
                    SimpleNamespace(
                        animation_intents=(DesignAnimationIntent("idle", 2),),
                    ),
                ),
            ),
            current=True,
            stale_reason=None,
        )
        with (
            patch(
                "origin_forge.pixelorama_source.bridge_accepted_design_to_planning_input",
                return_value=SimpleNamespace(
                    planning_input_id="PLAN-input",
                    content_hash="sha256:" + "c" * 64,
                ),
            ),
            patch("origin_forge.pixelorama_source.inspect_accepted_design", return_value=expected),
            patch("origin_forge.pixelorama_source.PixeloramaMediaService.execute") as execute,
            self.assertRaisesRegex(
                AcceptedDesignError,
                "exceeds supplied raster frames",
            ),
        ):
            create_pixelorama_source_from_accepted_design(
                self.runtime,
                self.task,
                "DESIGNACC-overrun",
                self._profile(self._script("overrun-bridge.py")),
                self._request().sprite_spec,
            )
        execute.assert_not_called()

    def test_accepted_animation_intent_builds_canonical_work_order_payload(self) -> None:
        expected = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id="DESIGNACC-work-order",
                content_hash="sha256:" + "a" * 64,
                project_id=self.runtime.project_id(),
            ),
            specification=SimpleNamespace(
                deliverables=(
                    SimpleNamespace(
                        animation_intents=(DesignAnimationIntent("run", 2, 80, "LOOP", 1),),
                    ),
                ),
            ),
            current=True,
            stale_reason=None,
        )
        sprite_spec = SpriteProjectSpec(
            2,
            2,
            (RasterLayerSpec("base", "Base"),),
            (FrameSpec("run-0"), FrameSpec("run-1"), FrameSpec("run-2")),
            output_basename="runner",
        )
        with (
            patch(
                "origin_forge.pixelorama_source.bridge_accepted_design_to_planning_input",
                return_value=SimpleNamespace(),
            ),
            patch("origin_forge.pixelorama_source.inspect_accepted_design", return_value=expected),
        ):
            payload = build_pixelorama_source_work_order_payload_from_accepted_design(
                self.runtime,
                "DESIGNACC-work-order",
                sprite_spec,
            )
        self.assertEqual(payload["operation"], "CREATE_SPRITE_PROJECT")
        self.assertEqual(
            payload["sprite_spec"]["animations"],
            [{"name": "run", "first_frame": 1, "last_frame": 2, "loop_mode": "LOOP"}],
        )

    def test_source_creation_from_stale_accepted_design_fails_closed(self) -> None:
        request = self._request()
        expected = SimpleNamespace(
            acceptance=SimpleNamespace(
                acceptance_id="DESIGNACC-stale",
                content_hash="sha256:" + "b" * 64,
                project_id=self.runtime.project_id(),
            ),
            design_input=SimpleNamespace(design_input_id="DESIGNIN-input"),
            current=False,
            stale_reason="goal revision drifted",
        )
        with (
            patch(
                "origin_forge.pixelorama_source.bridge_accepted_design_to_planning_input",
                side_effect=RuntimeError("accepted design is stale: goal revision drifted"),
            ),
            patch(
                "origin_forge.pixelorama_source.inspect_accepted_design",
                return_value=expected,
            ),
            self.assertRaisesRegex(RuntimeError, "accepted design is stale"),
        ):
            create_pixelorama_source_from_accepted_design(
                self.runtime,
                self.task,
                "DESIGNACC-stale",
                self._profile(self._script("stale-design-bridge.py")),
                request.sprite_spec,
            )

    def test_created_project_requires_human_review_before_explicit_adoption(self) -> None:
        script = self._script("review-source-bridge.py")
        request = self._request()
        before = self.runtime.get_task(self.task)
        result = create_pixelorama_source(
            self.runtime,
            self.task,
            self._profile(script),
            request.sprite_spec,
            export_specs=request.export_specs,
            budget=request.budget,
        )
        project = next(
            value
            for value in result.output_evidence
            if value.output_type is BridgeOutputType.PIXELORAMA_PROJECT
        )
        rejected = record_task_review_decision(
            self.runtime, self.task, "reject", rationale="sprite silhouette needs revision"
        )
        refined = record_task_review_decision(
            self.runtime, self.task, "refine", rationale="rework the silhouette"
        )
        adopted = PixeloramaOutputAdopter(self.runtime).adopt_new(
            project.artifact_id, "assets/sprites/reviewed-sprite.pxo"
        )
        self.assertTrue(rejected.startswith("DEC-"))
        self.assertTrue(refined.startswith("DEC-"))
        after = self.runtime.get_task(self.task)
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertIsNone(after["assigned_run_id"])
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertEqual(adopted.source_artifact_id, project.artifact_id)
        self.assertFalse(result.to_dict()["task_status_changed"])
        self.assertFalse(result.to_dict()["canonical_asset_adopted"])

    def test_explicit_adoption_creates_new_project_artifact_without_overwrite_or_task_change(self) -> None:
        script = self._script()
        media = PixeloramaMediaService(self.runtime, self._profile(script)).execute(
            self.task, self._request()
        )
        source = next(
            value
            for value in media.output_evidence
            if value.output_type == BridgeOutputType.PNG
        )
        task_before = self.runtime.get_task(self.task)
        adopted = PixeloramaOutputAdopter(self.runtime).adopt_new(
            source.artifact_id,
            "assets/sprites/media-test.png",
        )
        destination = self.root / adopted.destination_path
        self.assertTrue(destination.is_file())
        self.assertEqual(
            "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest(),
            adopted.content_hash,
        )
        with self.runtime.store.session() as conn:
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (adopted.adopted_artifact_id,),
            ).fetchone()
        self.assertEqual(artifact["parent_artifact_id"], source.artifact_id)
        verifications = self.lineage.list_artifact_verifications(
            adopted.adopted_artifact_id
        )
        self.assertEqual(len(verifications), 1)
        self.assertEqual(
            verifications[0]["verification_type"],
            "pixelorama-adoption-integrity",
        )
        self.assertEqual(self.runtime.get_task(self.task), task_before)
        self.assertFalse(adopted.to_dict()["existing_asset_overwritten"])

        with self.assertRaisesRegex(PixeloramaMediaError, "create-only"):
            PixeloramaOutputAdopter(self.runtime).adopt_new(
                source.artifact_id,
                "assets/sprites/media-test.png",
            )

    def test_source_tampering_after_verification_prevents_adoption(self) -> None:
        script = self._script()
        media = PixeloramaMediaService(self.runtime, self._profile(script)).execute(
            self.task, self._request()
        )
        source = next(
            value
            for value in media.output_evidence
            if value.output_type == BridgeOutputType.PNG
        )
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT path_or_uri FROM artifacts WHERE id = ?",
                (source.artifact_id,),
            ).fetchone()
        (self.root / row["path_or_uri"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(PixeloramaMediaError, "drifted"):
            PixeloramaOutputAdopter(self.runtime).adopt_new(
                source.artifact_id,
                "assets/tampered.png",
            )
        self.assertFalse((self.root / "assets/tampered.png").exists())

    def test_failed_deterministic_raster_validation_fails_run_not_task(self) -> None:
        script = self._script("empty_bridge.py")
        before_task = self.runtime.get_task(self.task)
        service = PixeloramaMediaService(self.runtime, self._profile(script))
        with self.assertRaisesRegex(PixeloramaMediaError, "failed deterministic validation"):
            service.execute(self.task, self._request())
        self._assert_run_did_not_complete_task(
            before_task,
            self.runtime.get_task(self.task),
        )
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        runs = [
            row
            for row in self.runtime.list_runs()
            if row["role"] == PixeloramaMediaService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        run_verifications = self.runtime.list_verifications("RUN", runs[0]["id"])
        self.assertEqual(len(run_verifications), 1)
        self.assertEqual(run_verifications[0]["status"], "FAIL")

    def test_adoption_refuses_protected_and_existing_paths(self) -> None:
        script = self._script()
        media = PixeloramaMediaService(self.runtime, self._profile(script)).execute(
            self.task, self._request()
        )
        source = next(
            value
            for value in media.output_evidence
            if value.output_type == BridgeOutputType.PNG
        )
        adopter = PixeloramaOutputAdopter(self.runtime)
        with self.assertRaises(PixeloramaMediaError):
            adopter.adopt_new(source.artifact_id, ".origin-forge/forbidden.png")
        existing = self.root / "existing.png"
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(PixeloramaMediaError, "create-only"):
            adopter.adopt_new(source.artifact_id, "existing.png")
        self.assertEqual(existing.read_bytes(), b"keep")

    def test_media_service_and_adopter_have_no_model_task_merge_release_surface(self) -> None:
        script = self._script()
        objects = (
            PixeloramaMediaService(self.runtime, self._profile(script)),
            PixeloramaOutputAdopter(self.runtime),
        )
        for obj in objects:
            for forbidden in (
                "model",
                "generate",
                "verify_task",
                "transition_task",
                "transition_goal",
                "merge",
                "release",
                "install_plugin",
                "run_script",
            ):
                self.assertFalse(hasattr(obj, forbidden))


if __name__ == "__main__":
    unittest.main()
