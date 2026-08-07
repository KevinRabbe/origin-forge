from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.apply import IsolatedPatchApplier
from origin_forge.audit import WorkspaceAuditor
from origin_forge.lineage import OriginForgeLineage
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.patches import PatchValidationError, parse_patch_proposal
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.state import TaskStatus, WorkspaceStatus
from origin_forge.worker import LocalPatchWorker
from origin_forge.workspaces import GitWorkspaceManager


class FakeProposalModel:
    def __init__(self, text: str):
        self.text = text

    @property
    def model_id(self) -> str:
        return "workspace-test-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(self.text, self.model_id)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class WorkspaceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        self.source = self.root / "hello.py"
        self.source.write_text("print('old')\n", encoding="utf-8")
        git(self.root, "add", "hello.py")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("workspace-test")
        goal = self.runtime.create_goal("isolated change")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(flow, "change greeting")
        revision = self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(self.task, TaskStatus.RUNNING, expected_revision=revision)
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            if Path(self.root / row["path"]).exists():
                try:
                    self.workspaces.abandon(row["id"])
                except Exception:
                    pass
        self.tempdir.cleanup()

    def _proposal(self, expected_hash: str):
        return parse_patch_proposal(
            json.dumps(
                {
                    "summary": "change greeting and add helper",
                    "changes": [
                        {
                            "operation": "UPDATE",
                            "path": "hello.py",
                            "expected_hash": expected_hash,
                            "content": "print('new')\n",
                        },
                        {
                            "operation": "CREATE",
                            "path": "helper.py",
                            "expected_hash": None,
                            "content": "VALUE = 1\n",
                        },
                    ],
                    "notes": [],
                }
            )
        )

    def test_apply_and_audit_only_mutate_worktree(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = self._proposal(expected)
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)

        result = IsolatedPatchApplier(self.runtime, self.workspaces)._apply(
            workspace_id, proposal
        )
        self.assertIn("hello.py", result.diff_text)
        self.assertIn("helper.py", result.diff_text)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")
        self.assertFalse((self.root / "helper.py").exists())
        self.assertEqual(
            (workspace_path / "hello.py").read_text(encoding="utf-8"),
            "print('new')\n",
        )
        self.assertTrue((workspace_path / "helper.py").exists())

        audit = WorkspaceAuditor(self.runtime, self.workspaces)._audit(
            workspace_id, proposal
        )
        self.assertTrue(audit.passed, audit.findings)
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )

    def test_stale_precondition_rejects_before_mutation(self) -> None:
        proposal = self._proposal("sha256:" + "0" * 64)
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)
        with self.assertRaises(PatchValidationError):
            IsolatedPatchApplier(self.runtime, self.workspaces)._apply(
                workspace_id, proposal
            )
        self.assertEqual(
            (workspace_path / "hello.py").read_text(encoding="utf-8"),
            "print('old')\n",
        )
        self.assertFalse((workspace_path / "helper.py").exists())
        self.assertEqual(git(workspace_path, "status", "--porcelain"), "")
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.CREATED.value,
        )

    def test_workspace_requires_running_task(self) -> None:
        goal = self.runtime.create_goal("second")
        flow = self.runtime.create_flow(goal)
        queued = self.runtime.create_task(flow, "not ready")
        with self.assertRaises(RuntimeInvariantError):
            self.workspaces.create(queued)

    def test_failed_apply_removes_ignored_files_and_marks_workspace_failed(self) -> None:
        (self.root / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
        git(self.root, "add", ".gitignore")
        git(self.root, "commit", "-qm", "ignore temp")
        proposal = parse_patch_proposal(
            json.dumps(
                {
                    "summary": "create ignored file",
                    "changes": [
                        {
                            "operation": "CREATE",
                            "path": "ignored.tmp",
                            "expected_hash": None,
                            "content": "temporary\n",
                        }
                    ],
                    "notes": [],
                }
            )
        )
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)
        applier = IsolatedPatchApplier(self.runtime, self.workspaces)
        with patch.object(applier.lineage, "create_change", side_effect=RuntimeError("forced")):
            with self.assertRaises(RuntimeError):
                applier._apply(workspace_id, proposal)
        self.assertFalse((workspace_path / "ignored.tmp").exists())
        self.assertEqual(git(workspace_path, "status", "--porcelain"), "")
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_failed_audit_marks_workspace_failed(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = self._proposal(expected)
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)
        IsolatedPatchApplier(self.runtime, self.workspaces)._apply(workspace_id, proposal)
        (workspace_path / "unexpected.txt").write_text("tamper\n", encoding="utf-8")

        audit = WorkspaceAuditor(self.runtime, self.workspaces)._audit(workspace_id, proposal)
        self.assertFalse(audit.passed)
        self.assertTrue(any("changed paths differ" in finding for finding in audit.findings))
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_only_one_active_workspace_per_task(self) -> None:
        first = self.workspaces.create(self.task)
        with self.assertRaises(RuntimeInvariantError):
            self.workspaces.create(self.task)
        self.workspaces.abandon(first)
        second = self.workspaces.create(self.task)
        self.assertNotEqual(first, second)

    def test_recovery_resets_dirty_created_workspace_and_marks_failed(self) -> None:
        workspace_id = self.workspaces.create(self.task)
        workspace_path = self.workspaces.path(workspace_id)
        (workspace_path / "partial.tmp").write_text("partial\n", encoding="utf-8")
        findings = self.workspaces.recovery_findings()
        self.assertEqual([item.workspace_id for item in findings], [workspace_id])
        self.workspaces.recover()
        self.assertFalse((workspace_path / "partial.tmp").exists())
        self.assertEqual(git(workspace_path, "status", "--porcelain"), "")
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_apply_artifact_links_diff_to_integrity_checked_proposal(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = self._proposal(expected)
        model = FakeProposalModel(proposal.to_json())
        worker_result = LocalPatchWorker(self.runtime, model).execute(
            self.task, selected_paths=["hello.py"]
        )
        workspace_id = self.workspaces.create(self.task)
        result = IsolatedPatchApplier(self.runtime, self.workspaces).apply_artifact(
            workspace_id, worker_result.proposal_artifact_id
        )
        artifact = OriginForgeLineage(self.runtime).get_artifact(result.diff_artifact_id)
        self.assertEqual(
            artifact["parent_artifact_id"], worker_result.proposal_artifact_id
        )
        audit = WorkspaceAuditor(self.runtime, self.workspaces).audit_artifact(
            workspace_id, worker_result.proposal_artifact_id
        )
        self.assertTrue(audit.passed, audit.findings)

    def test_tampered_proposal_artifact_is_rejected_before_apply(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = self._proposal(expected)
        worker_result = LocalPatchWorker(
            self.runtime, FakeProposalModel(proposal.to_json())
        ).execute(self.task, selected_paths=["hello.py"])
        lineage = OriginForgeLineage(self.runtime)
        proposal_path = lineage.local_artifact_path(worker_result.proposal_artifact_id)
        proposal_path.write_text("{}\n", encoding="utf-8")
        workspace_id = self.workspaces.create(self.task)
        with self.assertRaises(RuntimeInvariantError):
            IsolatedPatchApplier(self.runtime, self.workspaces).apply_artifact(
                workspace_id, worker_result.proposal_artifact_id
            )
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"],
            WorkspaceStatus.CREATED.value,
        )
        self.assertEqual(git(self.workspaces.path(workspace_id), "status", "--porcelain"), "")

    def test_origin_forge_state_is_locally_excluded_from_git(self) -> None:
        workspace_id = self.workspaces.create(self.task)
        self.assertTrue(self.workspaces.path(workspace_id).exists())
        status = git(self.root, "status", "--porcelain")
        self.assertNotIn(".origin-forge", status)


if __name__ == "__main__":
    unittest.main()
