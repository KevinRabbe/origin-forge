from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from origin_forge.blender_adapter import (
    BlenderAdapter,
    BlenderIntegrityError,
    BlenderProcessError,
    BlenderProcessOutcome,
    BlenderRuntimeProfile,
    blender_runner_v1_fingerprint,
    blender_runtime_tree_hash,
)
from origin_forge.blender_models import BlenderBudget, BlenderJobRequest
from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.runtime import OriginForgeRuntime


def _chunk(kind: int, payload: bytes, pad: bytes) -> bytes:
    if len(payload) % 4:
        payload += pad * (4 - len(payload) % 4)
    return struct.pack("<II", len(payload), kind) + payload


def _minimal_glb() -> bytes:
    root = {
        "asset": {"version": "2.0", "generator": "fake-blender"},
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


class FakeBlenderRunner:
    def __init__(self, *, mode: str = "success"):
        self.mode = mode
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def run(
        self,
        argv,
        *,
        cwd,
        env,
        timeout_seconds,
        max_stdout_bytes,
        max_stderr_bytes,
    ) -> BlenderProcessOutcome:
        args = tuple(argv)
        self.calls.append((args, dict(env)))
        if args[-1] == "--version" or (len(args) == 2 and args[1] == "--version"):
            version = b"Blender 5.2.9\n" if self.mode == "wrong_version" else b"Blender 5.2.0\n"
            return BlenderProcessOutcome(0, version, b"")
        if self.mode == "timeout":
            return BlenderProcessOutcome(-9, b"", b"", timed_out=True)
        if self.mode == "overflow":
            return BlenderProcessOutcome(-9, b"x", b"", output_limit_exceeded=True)
        if self.mode == "nonzero":
            return BlenderProcessOutcome(7, b"", b"boom")

        def arg(name: str) -> str:
            return args[args.index(name) + 1]

        request_path = Path(arg("--request"))
        result_path = Path(arg("--result"))
        output_path = Path(arg("--output"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        glb = b"not-glb" if self.mode == "invalid_glb" else _minimal_glb()
        output_path.write_bytes(glb)
        if self.mode == "extra_output":
            (output_path.parent / "extra.glb").write_bytes(_minimal_glb())
        result = {
            "protocol_version": 1,
            "status": "SUCCEEDED",
            "operation_id": request["operation_id"],
            "workspace_id": request["workspace_id"],
            "request_hash": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    request,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "project_hash": request["project_hash"],
            "output_relative_path": request["output_relative_path"],
            "blender_version": request["expected_blender_version"],
        }
        if self.mode == "wrong_result":
            result["task_verified"] = True
        result_path.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return BlenderProcessOutcome(0, b"render log", b"")


class BlenderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root / "project")
        self.runtime.initialize("blender-adapter-test")
        self.blender_root = self.root / "blender-runtime"
        self.blender_root.mkdir()
        self.executable = self.blender_root / "blender"
        self.executable.write_bytes(b"fake portable blender executable")
        self.runtime_hash = blender_runtime_tree_hash(self.blender_root)
        self.runner_fingerprint = blender_runner_v1_fingerprint()
        self.project = BlockbenchProjectSpec(
            project_name="crate",
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="crate",
                    name="Crate",
                    from_point=Vec3(-1, -1, -1),
                    to_point=Vec3(1, 1, 1),
                    origin=Vec3(0, 0, 0),
                ),
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _profile(self, **overrides) -> BlenderRuntimeProfile:
        values = {
            "runtime_root": self.blender_root,
            "executable": self.executable,
            "runtime_hash": self.runtime_hash,
            "expected_blender_version": "Blender 5.2.0",
            "runner_fingerprint": self.runner_fingerprint,
        }
        values.update(overrides)
        return BlenderRuntimeProfile(**values)

    def _request(self, **overrides) -> BlenderJobRequest:
        values = {
            "project": self.project,
            "output_relative_path": "exports/model.glb",
            "runner_fingerprint": self.runner_fingerprint,
            "runtime_hash": self.runtime_hash,
            "expected_blender_version": "Blender 5.2.0",
            "budget": BlenderBudget(timeout_seconds=5),
        }
        values.update(overrides)
        return BlenderJobRequest.create(**values)

    def test_success_uses_fixed_hardened_argv_and_reinspects_glb(self) -> None:
        fake = FakeBlenderRunner()
        before_runs = self.runtime.list_runs()
        execution = BlenderAdapter(self.runtime, self._profile(), runner=fake).execute(
            self._request()
        )
        self.assertEqual(execution.inspection.mesh_count, 1)
        self.assertEqual(execution.blender_version, "Blender 5.2.0")
        self.assertFalse(execution.to_dict()["production_verification_changed"])
        self.assertFalse(execution.to_dict()["canonical_asset_adopted"])
        self.assertEqual(self.runtime.list_runs(), before_runs)
        run_argv, env = fake.calls[1]
        for token in (
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "--python",
        ):
            self.assertIn(token, run_argv)
        for forbidden in ("--python-expr", "--python-text", "--python-console", "--addons", "--online-mode"):
            self.assertNotIn(forbidden, run_argv)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertEqual(env["HOME"].startswith(str(execution.workspace_path)), True)

    def test_runtime_runner_and_version_drift_fail_closed(self) -> None:
        with self.assertRaisesRegex(BlenderIntegrityError, "runtime hash"):
            BlenderAdapter(self.runtime, self._profile(), runner=FakeBlenderRunner()).execute(
                self._request(runtime_hash="sha256:" + "0" * 64)
            )

        with self.assertRaisesRegex(BlenderIntegrityError, "runner fingerprint"):
            BlenderAdapter(self.runtime, self._profile(), runner=FakeBlenderRunner()).execute(
                self._request(runner_fingerprint="sha256:" + "0" * 64)
            )

        self.executable.write_bytes(b"runtime drift")
        with self.assertRaisesRegex(BlenderIntegrityError, "runtime tree hash"):
            BlenderAdapter(self.runtime, self._profile(), runner=FakeBlenderRunner()).execute(
                self._request()
            )

        other_runtime = OriginForgeRuntime(self.root / "wrong-version-project")
        other_runtime.initialize("wrong-version")
        with self.assertRaisesRegex(BlenderIntegrityError, "version"):
            BlenderAdapter(
                other_runtime,
                self._profile(runtime_hash=blender_runtime_tree_hash(self.blender_root)),
                runner=FakeBlenderRunner(mode="wrong_version"),
            ).execute(
                self._request(runtime_hash=blender_runtime_tree_hash(self.blender_root))
            )

    def test_timeout_output_overflow_nonzero_invalid_glb_and_extra_output_fail_closed(self) -> None:
        for mode, pattern in (
            ("timeout", "timed out"),
            ("overflow", "budget"),
            ("nonzero", "exited with 7"),
            ("invalid_glb", "independent validation"),
            ("extra_output", "export set"),
            ("wrong_result", "strict schema"),
        ):
            with self.subTest(mode=mode):
                runtime = OriginForgeRuntime(self.root / f"case-{mode}")
                runtime.initialize(mode)
                adapter = BlenderAdapter(runtime, self._profile(), runner=FakeBlenderRunner(mode=mode))
                with self.assertRaisesRegex((BlenderIntegrityError, BlenderProcessError), pattern):
                    adapter.execute(self._request())

    def test_profile_rejects_symlinked_or_escaped_runtime_executable(self) -> None:
        outside = self.root / "outside"
        outside.write_bytes(b"outside")
        profile = self._profile(executable=outside)
        with self.assertRaisesRegex(BlenderIntegrityError, "inside runtime tree"):
            profile.verify()

    def test_adapter_has_no_model_task_adoption_merge_release_or_install_surface(self) -> None:
        adapter = BlenderAdapter(self.runtime, self._profile(), runner=FakeBlenderRunner())
        for forbidden in (
            "model",
            "generate_python",
            "execute_python",
            "verify_task",
            "transition_task",
            "adopt",
            "merge",
            "release",
            "install_addon",
            "download",
        ):
            self.assertFalse(hasattr(adapter, forbidden))


if __name__ == "__main__":
    unittest.main()
