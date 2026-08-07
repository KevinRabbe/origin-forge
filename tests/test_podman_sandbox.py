from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from origin_forge.podman_sandbox import (
    PodmanSandboxBackend,
    PodmanSandboxSettings,
    run_bounded_process,
)
from origin_forge.sandbox import SandboxJob, SandboxResult, SandboxUnavailable


class BoundedProcessTests(unittest.TestCase):
    def test_output_is_bounded_while_process_is_drained(self) -> None:
        result = run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stdout.write('x'*100000)"],
            timeout_seconds=5,
            max_output_bytes=1024,
        )
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.stdout_truncated)
        self.assertEqual(len(result.stdout.encode("utf-8")), 1024)

    def test_timeout_kills_process(self) -> None:
        result = run_bounded_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_seconds=0.1,
            max_output_bytes=1024,
        )
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)


class PodmanBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state = self.root / ".origin-forge"
        self.state.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "hello.txt").write_text("original\n", encoding="utf-8")
        (self.workspace / ".git").write_text("gitdir: hidden\n", encoding="utf-8")
        (self.workspace / ".origin-forge").mkdir()
        (self.workspace / ".origin-forge" / "secret").write_text("secret", encoding="utf-8")
        self.backend = PodmanSandboxBackend(
            self.state,
            PodmanSandboxSettings(
                image="example/test:local",
                memory="1g",
                cpus=1.5,
                pids_limit=64,
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _job(self, *, network: bool = False) -> SandboxJob:
        return SandboxJob(
            workspace_path=self.workspace,
            argv=("python", "-m", "unittest", "-q"),
            timeout_seconds=10,
            max_output_bytes=4096,
            network_allowed=network,
            environment={"ORIGIN_FORGE_SANDBOX": "1"},
        )

    def test_command_has_security_flags_and_content_addressed_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp)
            with patch("origin_forge.podman_sandbox.shutil.which", return_value="/usr/bin/podman"):
                command = self.backend._build_command(
                    self._job(), copy, "sha256:abc123", copy / "container.cid"
                )
        joined = " ".join(command)
        self.assertIn("--pull=never", command)
        self.assertIn("--read-only", command)
        self.assertTrue(any(arg.startswith("--cidfile=") for arg in command))
        self.assertIn("--cap-drop=all", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn("--network=none", command)
        self.assertIn("--pids-limit=64", command)
        self.assertIn("--memory=1g", command)
        self.assertIn("--cpus=1.5", command)
        self.assertIn("sha256:abc123", command)
        self.assertIn("--entrypoint", command)
        self.assertNotIn("example/test:local", command)
        self.assertIn("target=/workspace,rw=true", joined)

    def test_explicit_network_policy_omits_none_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch("origin_forge.podman_sandbox.shutil.which", return_value="podman"):
                command = self.backend._build_command(
                    self._job(network=True),
                    Path(temp),
                    "sha256:id",
                    Path(temp) / "container.cid",
                )
        self.assertNotIn("--network=none", command)

    def test_available_resolves_local_image_id(self) -> None:
        completed = Mock(returncode=0, stdout="sha256:resolved\n", stderr="")
        with patch("origin_forge.podman_sandbox.shutil.which", return_value="podman"), patch(
            "origin_forge.podman_sandbox.subprocess.run", return_value=completed
        ) as run:
            self.assertTrue(self.backend.available())
        self.assertEqual(self.backend._resolved_image_id, "sha256:resolved")
        self.assertIn("image", run.call_args.args[0])
        self.assertIn("inspect", run.call_args.args[0])

    def test_unavailable_without_podman_or_image(self) -> None:
        with patch("origin_forge.podman_sandbox.shutil.which", return_value=None):
            self.assertFalse(self.backend.available())
        with patch.object(self.backend, "_probe_image_id", return_value=None):
            with self.assertRaises(SandboxUnavailable):
                self.backend.run(self._job())

    def test_run_uses_disposable_copy_and_cleans_it(self) -> None:
        observed: dict[str, object] = {}

        def fake_run(argv, *, timeout_seconds, max_output_bytes, cwd=None):
            mount_arg = next(arg for arg in argv if arg.startswith("type=bind,src="))
            src = mount_arg.split("src=", 1)[1].split(",target=", 1)[0]
            copied = Path(src)
            observed["copy"] = copied
            self.assertTrue((copied / "hello.txt").exists())
            self.assertFalse((copied / ".git").exists())
            self.assertFalse((copied / ".origin-forge").exists())
            (copied / "hello.txt").write_text("mutated-in-container-copy\n", encoding="utf-8")
            return SandboxResult(0, "ok", "", False, 10)

        with patch.object(self.backend, "_probe_image_id", return_value="sha256:resolved"), patch(
            "origin_forge.podman_sandbox.run_bounded_process", side_effect=fake_run
        ), patch.object(self.backend, "_cleanup_container") as cleanup:
            result = self.backend.run(self._job())
        cleanup.assert_called_once()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            (self.workspace / "hello.txt").read_text(encoding="utf-8"), "original\n"
        )
        copied = observed["copy"]
        assert isinstance(copied, Path)
        self.assertFalse(copied.exists())

    def test_cleanup_uses_cidfile_force_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cidfile = Path(temp) / "container.cid"
            with patch("origin_forge.podman_sandbox.shutil.which", return_value="podman"), patch(
                "origin_forge.podman_sandbox.subprocess.run"
            ) as run:
                self.backend._cleanup_container(cidfile)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:2], ["podman", "rm"])
        self.assertIn("--force", argv)
        self.assertIn("--ignore", argv)
        self.assertIn("--time", argv)
        self.assertIn("0", argv)
        self.assertIn(f"--cidfile={cidfile}", argv)


if __name__ == "__main__":
    unittest.main()
