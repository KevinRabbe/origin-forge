from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from origin_forge.podman_lsp import (
    PodmanLspBackend,
    PodmanLspServerSpec,
    PodmanLspUnavailable,
)


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO(b"server log\n")
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class FakeSession:
    def __init__(self, reader, writer, **kwargs) -> None:
        self.reader = reader
        self.writer = writer
        self.kwargs = kwargs
        self.requests: list[tuple[str, object | None, float]] = []
        self.notifications: list[tuple[str, object | None]] = []
        self.closed = False

    def request(self, method, params=None, *, timeout_seconds=10.0):
        self.requests.append((method, params, timeout_seconds))
        if method == "initialize":
            return {
                "capabilities": {
                    "positionEncoding": "utf-8",
                    "workspaceSymbolProvider": True,
                    "definitionProvider": True,
                    "referencesProvider": True,
                    "diagnosticProvider": {},
                }
            }
        if method == "shutdown":
            return None
        raise AssertionError(f"unexpected request: {method}")

    def notify(self, method, params=None) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


class FailingInitializeSession(FakeSession):
    def request(self, method, params=None, *, timeout_seconds=10.0):
        self.requests.append((method, params, timeout_seconds))
        if method == "initialize":
            raise RuntimeError("initialize failed")
        return None


class PodmanLspTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state = self.root / ".origin-forge"
        self.state.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.workspace.joinpath("hello.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.spec = PodmanLspServerSpec(
            server_id="pyright",
            image="origin-forge/pyright:local",
            argv=("pyright-langserver", "--stdio"),
            memory="1g",
            cpus=1.5,
            pids_limit=64,
            max_protocol_message_bytes=12345,
            max_pending_notifications=17,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_command_is_content_addressed_network_off_and_workspace_read_only(self) -> None:
        backend = PodmanLspBackend(self.state, self.spec)
        with patch("origin_forge.podman_lsp.shutil.which", return_value="/usr/bin/podman"):
            command = backend._build_command(
                self.workspace,
                "sha256:resolved",
                self.root / "container.cid",
            )

        joined = " ".join(command)
        self.assertIn("--pull=never", command)
        self.assertIn("-i", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=all", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn("--network=none", command)
        self.assertIn("--pids-limit=64", command)
        self.assertIn("--memory=1g", command)
        self.assertIn("--cpus=1.5", command)
        self.assertIn("HOME=/tmp", command)
        self.assertIn("XDG_CACHE_HOME=/tmp/cache", command)
        self.assertIn("target=/workspace,ro=true", joined)
        self.assertIn("--entrypoint", command)
        self.assertIn("pyright-langserver", command)
        self.assertIn("sha256:resolved", command)
        self.assertNotIn("origin-forge/pyright:local", command)

    def test_explicit_network_policy_can_enable_container_network(self) -> None:
        spec = PodmanLspServerSpec(
            server_id="networked",
            image="local/image",
            argv=("server",),
            network_allowed=True,
        )
        backend = PodmanLspBackend(self.state, spec)
        with patch("origin_forge.podman_lsp.shutil.which", return_value="podman"):
            command = backend._build_command(
                self.workspace,
                "sha256:id",
                self.root / "container.cid",
            )
        self.assertNotIn("--network=none", command)

    def test_copy_excludes_protected_roots_and_symlinks(self) -> None:
        self.workspace.joinpath(".git").mkdir()
        self.workspace.joinpath(".origin-forge").mkdir()
        git_alias = self.workspace / ".GIT"
        if not git_alias.exists():
            git_alias.mkdir()
        state_alias = self.workspace / ".ORIGIN-FORGE"
        if not state_alias.exists():
            state_alias.mkdir()

        outside = self.root / "outside.py"
        outside.write_text("SECRET = 1\n", encoding="utf-8")
        link = self.workspace / "linked.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")

        destination = self.root / "copy"
        PodmanLspBackend._copy_workspace(self.workspace, destination)

        self.assertTrue(destination.joinpath("hello.py").is_file())
        self.assertFalse(destination.joinpath(".git").exists())
        self.assertFalse(destination.joinpath(".origin-forge").exists())
        self.assertFalse(destination.joinpath(".GIT").exists())
        self.assertFalse(destination.joinpath(".ORIGIN-FORGE").exists())
        self.assertFalse(destination.joinpath("linked.py").exists())

    def test_available_resolves_local_image_id(self) -> None:
        backend = PodmanLspBackend(self.state, self.spec)
        completed = Mock(returncode=0, stdout="sha256:resolved\n", stderr="")
        with patch("origin_forge.podman_lsp.shutil.which", return_value="podman"), patch(
            "origin_forge.podman_lsp.subprocess.run",
            return_value=completed,
        ):
            self.assertTrue(backend.available())
        self.assertEqual(backend.provenance["resolved_image_id"], "sha256:resolved")
        self.assertEqual(backend.provenance["server_id"], "pyright")

    def test_start_initializes_against_container_visible_workspace_and_cleans_on_close(self) -> None:
        sessions: list[FakeSession] = []

        def factory(reader, writer, **kwargs):
            session = FakeSession(reader, writer, **kwargs)
            sessions.append(session)
            return session

        backend = PodmanLspBackend(
            self.state,
            self.spec,
            session_factory=factory,
        )
        process = FakeProcess()
        with patch.object(backend, "_probe_image_id", return_value="sha256:resolved"), patch(
            "origin_forge.podman_lsp.subprocess.Popen",
            return_value=process,
        ), patch.object(backend, "_cleanup_container") as cleanup:
            handle = backend.start(self.workspace)
            job_root = handle.job_root
            copied = handle.workspace_copy
            self.assertTrue(copied.joinpath("hello.py").is_file())
            self.assertEqual(handle.provider.mapper.server_root_uri, "file:///workspace")
            self.assertEqual(handle.provider.repository.project_root, copied.resolve())
            self.assertEqual(
                sessions[0].kwargs,
                {
                    "max_message_bytes": 12345,
                    "max_pending_notifications": 17,
                },
            )
            initialize = sessions[0].requests[0]
            self.assertEqual(initialize[0], "initialize")
            self.assertEqual(initialize[1]["rootUri"], "file:///workspace")
            self.assertEqual(sessions[0].notifications[0], ("initialized", {}))

            handle.close()

        self.assertTrue(sessions[0].closed)
        self.assertIn(("exit", None), sessions[0].notifications)
        self.assertFalse(job_root.exists())
        cleanup.assert_called_once()

    def test_initialization_failure_closes_resources_and_removes_job(self) -> None:
        sessions: list[FailingInitializeSession] = []

        def factory(reader, writer, **kwargs):
            session = FailingInitializeSession(reader, writer, **kwargs)
            sessions.append(session)
            return session

        backend = PodmanLspBackend(
            self.state,
            self.spec,
            session_factory=factory,
        )
        process = FakeProcess()
        with patch.object(backend, "_probe_image_id", return_value="sha256:resolved"), patch(
            "origin_forge.podman_lsp.subprocess.Popen",
            return_value=process,
        ), patch.object(backend, "_cleanup_container") as cleanup:
            with self.assertRaisesRegex(RuntimeError, "initialize failed"):
                backend.start(self.workspace)

        self.assertTrue(sessions[0].closed)
        self.assertTrue(process.terminated)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        cleanup.assert_called_once()
        lsp_jobs = self.state / "lsp-jobs"
        if lsp_jobs.exists():
            self.assertEqual(list(lsp_jobs.iterdir()), [])

    def test_unavailable_without_local_image(self) -> None:
        backend = PodmanLspBackend(self.state, self.spec)
        with patch.object(backend, "_probe_image_id", return_value=None):
            with self.assertRaises(PodmanLspUnavailable):
                backend.start(self.workspace)


if __name__ == "__main__":
    unittest.main()
