from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.apply import IsolatedPatchApplier
from origin_forge.audit import WorkspaceAuditor
from origin_forge.patches import parse_patch_proposal
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus, WorkspaceStatus
from origin_forge.workspaces import GitWorkspaceManager


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class AuditCodeDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        self.source = self.root / "hello.py"
        self.source.write_text("VALUE = 1\n", encoding="utf-8")
        git(self.root, "add", "hello.py")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("audit-diagnostics-test")
        goal = self.runtime.create_goal("audit diagnostics")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(flow, "introduce diagnostic fixture")
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
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def test_python_syntax_error_is_visible_but_not_patch_audit_authority(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = parse_patch_proposal(
            json.dumps(
                {
                    "summary": "diagnostic evidence fixture",
                    "changes": [
                        {
                            "operation": "UPDATE",
                            "path": "hello.py",
                            "expected_hash": expected,
                            "content": "def broken(:\n    pass\n",
                        }
                    ],
                    "notes": [],
                }
            )
        )
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)
        IsolatedPatchApplier(self.runtime, self.workspaces)._apply(
            workspace_id,
            proposal,
        )

        auditor = WorkspaceAuditor(self.runtime, self.workspaces)
        diagnostics = auditor._diagnostic_evidence(
            RepositoryReader(workspace_path),
            proposal,
        )
        audit = auditor._audit(workspace_id, proposal)

        self.assertEqual(diagnostics["status"], "COLLECTED")
        self.assertEqual(diagnostics["error_count"], 1)
        self.assertEqual(diagnostics["diagnostics"][0]["severity"], "ERROR")
        self.assertIn("SyntaxError", diagnostics["diagnostics"][0]["code"])

        # The structural patch audit checks whether the intended patch was
        # applied exactly. Diagnostics are evidence only and therefore cannot
        # replace the later sandbox/compiler/test correctness gate.
        self.assertTrue(audit.passed, audit.findings)
        self.assertEqual(audit.findings, ())
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )


if __name__ == "__main__":
    unittest.main()
