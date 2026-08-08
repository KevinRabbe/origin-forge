from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from origin_forge.podman_lsp import PodmanLspBackend, PodmanLspServerSpec, PodmanLspUnavailable


class PodmanLspBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state = self.root / ".origin-forge"
        self.state.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.workspace.joinpath("main.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.backend = PodmanLspBackend(
            self.state,
            PodmanLspServerSpec(
                server_id="python-test",
                image="origin-forge/python-lsp:local",
                argv=("pyright-langserver", "--stdio"),
                memory="1g",
                cpus=1.5,
                pids_limit=64,
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _isolated_workspace(self) -> Path:
        root = self.state / "workspaces"
        root.mkdir(exist_ok=True)
        workspace = root / "WSPACE-test"
        workspace.mkdir(exist_ok=True)
        workspace.joinpath("main.py").write_text("VALUE = 1\n", encoding="utf-8")
        return workspace

    def test_command_uses_content_addressed_image_and_read_only_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch(
            "origin_forge.podman_lsp.shutil.which", return_value="/usr/bin/podman"
        ):
            copy = Path(temp) / "workspace"
            copy.mkdir()
            command = self.backend._build_command(
                copy,
                "sha256:resolved",
                Path(temp) / "container.cid",
            )

        joined = " ".join(command)
        self.assertIn("--pull=never", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=all", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn("--network=none", command)
        self.assertIn("--pids-limit=64", command)
        self.assertIn("--memory=1g", command)
        self.assertIn("--cpus=1.5", command)
        self.assertIn("sha256:resolved", command)
        self.assertNotIn("origin-forge/python-lsp:local", command)
        self.assertIn("target=/workspace,ro=true", joined)
        self.assertIn("pyright-langserver", command)
        self.assertIn("--stdio", command)

    def test_workspace_copy_omits_protected_roots_and_all_symlinks(self) -> None:
        self.workspace.joinpath(".origin-forge").mkdir()
        self.workspace.joinpath(".origin-forge", "secret").write_text("secret", encoding="utf-8")
        mixed = self.workspace / ".GIT"
        mixed.mkdir()
        mixed.joinpath("secret").write_text("secret", encoding="utf-8")
        target = self.root / "outside.py"
        target.write_text("SECRET = 1\n", encoding="utf-8")
        link = self.workspace / "linked.py"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")

        destination = self.root / "copy"
        self.backend._copy_workspace(self.workspace, destination)

        self.assertTrue(destination.joinpath("main.py").exists())
        self.assertFalse(destination.joinpath(".origin-forge").exists())
        self.assertFalse(destination.joinpath(".GIT").exists())
        self.assertFalse(destination.joinpath("linked.py").exists())

    def test_available_resolves_preloaded_local_image_id(self) -> None:
        completed = Mock(returncode=0, stdout="sha256:resolved\n", stderr="")
        with patch("origin_forge.podman_lsp.shutil.which", return_value="podman"), patch(
            "origin_forge.podman_lsp.subprocess.run", return_value=completed
        ) as run:
            self.assertTrue(self.backend.available())

        self.assertEqual(self.backend.provenance["resolved_image_id"], "sha256:resolved")
        self.assertEqual(self.backend.provenance["configured_image"], "origin-forge/python-lsp:local")
        self.assertIn("image", run.call_args.args[0])
        self.assertIn("inspect", run.call_args.args[0])

    def test_start_refuses_missing_local_image_without_pulling(self) -> None:
        workspace = self._isolated_workspace()
        with patch.object(self.backend, "_probe_image_id", return_value=None):
            with self.assertRaises(PodmanLspUnavailable):
                self.backend.start(workspace)

    def test_start_rejects_arbitrary_host_path_before_image_probe(self) -> None:
        with patch.object(self.backend, "_probe_image_id") as probe:
            with self.assertRaisesRegex(PodmanLspUnavailable, "isolated Origin Forge workspace"):
                self.backend.start(self.workspace)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
