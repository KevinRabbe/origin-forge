from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.podman_lsp import PodmanLspBackend, PodmanLspServerSpec, PodmanLspUnavailable


class PodmanLspWorkspaceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state = self.root / ".origin-forge"
        self.state.mkdir()
        self.backend = PodmanLspBackend(
            self.state,
            PodmanLspServerSpec(
                server_id="test",
                image="lsp:local",
                argv=("lsp-server", "--stdio"),
            ),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_only_direct_origin_forge_workspace_root_is_accepted(self) -> None:
        workspaces = self.state / "workspaces"
        workspaces.mkdir()
        workspace = workspaces / "WSPACE-test"
        workspace.mkdir()
        workspace.joinpath("main.py").write_text("VALUE = 1\n", encoding="utf-8")

        self.assertEqual(
            self.backend._validated_workspace_source(workspace),
            workspace.resolve(),
        )

        live_checkout = self.root / "src"
        live_checkout.mkdir()
        with self.assertRaisesRegex(PodmanLspUnavailable, "isolated Origin Forge workspace"):
            self.backend._validated_workspace_source(live_checkout)

        nested = workspace / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(PodmanLspUnavailable, "isolated Origin Forge workspace"):
            self.backend._validated_workspace_source(nested)

    def test_workspace_symlink_is_rejected_before_resolution(self) -> None:
        workspaces = self.state / "workspaces"
        workspaces.mkdir()
        workspace = workspaces / "WSPACE-real"
        workspace.mkdir()
        link = workspaces / "WSPACE-link"
        try:
            link.symlink_to(workspace, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")

        with self.assertRaisesRegex(PodmanLspUnavailable, "not a symlink"):
            self.backend._validated_workspace_source(link)


if __name__ == "__main__":
    unittest.main()
