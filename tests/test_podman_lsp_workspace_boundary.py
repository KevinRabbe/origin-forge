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

    def test_only_direct_origin_forge_worktree_root_is_accepted(self) -> None:
        worktrees = self.state / "worktrees"
        worktrees.mkdir()
        workspace = worktrees / "WORKSPACE-test"
        workspace.mkdir()
        workspace.joinpath("main.py").write_text("VALUE = 1\n", encoding="utf-8")

        self.assertEqual(
            self.backend._validated_workspace_source(workspace),
            workspace.resolve(),
        )

        live_checkout = self.root / "src"
        live_checkout.mkdir()
        with self.assertRaisesRegex(PodmanLspUnavailable, "isolated Origin Forge worktree"):
            self.backend._validated_workspace_source(live_checkout)

        nested = workspace / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(PodmanLspUnavailable, "isolated Origin Forge worktree"):
            self.backend._validated_workspace_source(nested)


if __name__ == "__main__":
    unittest.main()
