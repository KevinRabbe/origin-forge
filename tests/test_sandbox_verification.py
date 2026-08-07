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
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.sandbox import (
    SandboxGuarantees,
    SandboxJob,
    SandboxPolicyError,
    SandboxResult,
)
from origin_forge.sandbox_verification import SandboxedWorkspaceVerifier
from origin_forge.state import TaskStatus, WorkspaceStatus
from origin_forge.workspaces import GitWorkspaceManager


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class FakeSandboxBackend:
    def __init__(
        self,
        results: list[SandboxResult] | None = None,
        *,
        guarantees: SandboxGuarantees | None = None,
        error: Exception | None = None,
    ):
        self.backend_id = "fake-secure"
        self.guarantees = guarantees or SandboxGuarantees(True, True, True, True)
        self._results = list(results or [])
        self.error = error
        self.jobs: list[SandboxJob] = []

    def available(self) -> bool:
        return True

    def run(self, job: SandboxJob) -> SandboxResult:
        self.jobs.append(job)
        if self.error is not None:
            raise self.error
        if not self._results:
            raise RuntimeError("no fake result queued")
        return self._results.pop(0)


class SandboxedVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        (self.root / "hello.py").write_text("print('old')\n", encoding="utf-8")
        git(self.root, "add", "hello.py")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("sandbox-test")
        goal = self.runtime.create_goal("sandbox verify")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(flow, "change greeting")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )
        self.workspaces = GitWorkspaceManager(self.runtime)
        self.workspace_id = self.workspaces.create(self.task)
        expected = RepositoryReader(self.root).hash_file("hello.py")
        proposal = parse_patch_proposal(
            json.dumps(
                {
                    "summary": "change greeting",
                    "changes": [
                        {
                            "operation": "UPDATE",
                            "path": "hello.py",
                            "expected_hash": expected,
                            "content": "print('new')\n",
                        }
                    ],
                    "notes": [],
                }
            )
        )
        IsolatedPatchApplier(self.runtime, self.workspaces)._apply(
            self.workspace_id, proposal
        )
        audit = WorkspaceAuditor(self.runtime, self.workspaces)._audit(
            self.workspace_id, proposal
        )
        self.assertTrue(audit.passed)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _write_config(self, *, commands: str, network: bool = False) -> None:
        (self.root / ".origin-forge" / "config.toml").write_text(
            f'''version = 2\npolicy_profile = "local-default"\n[limits]\nmax_strategy_retries = 2\nmax_verification_failures = 3\n[sandbox]\nnetwork = {str(network).lower()}\n[commands]\n{commands}\n''',
            encoding="utf-8",
        )

    def test_successful_required_command_promotes_audited_to_verified(self) -> None:
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["python", "-m", "unittest", "-q"], timeout_seconds = 30, max_output_bytes = 4096, required = true }]'
        )
        backend = FakeSandboxBackend([SandboxResult(0, "ok", "", False, 10)])
        result = SandboxedWorkspaceVerifier(
            self.runtime, backend, self.workspaces
        ).verify(self.workspace_id)
        self.assertTrue(result.passed)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.VERIFIED.value,
        )
        self.assertEqual(
            backend.jobs[0].argv, ("python", "-m", "unittest", "-q")
        )
        self.assertFalse(backend.jobs[0].network_allowed)
        self.assertEqual(
            backend.jobs[0].workspace_path, self.workspaces.path(self.workspace_id)
        )

    def test_nonzero_command_fails_workspace(self) -> None:
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]'
        )
        backend = FakeSandboxBackend([SandboxResult(1, "", "failed", False, 5)])
        result = SandboxedWorkspaceVerifier(
            self.runtime, backend, self.workspaces
        ).verify(self.workspace_id)
        self.assertFalse(result.passed)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_truncated_output_counts_as_failed_verification(self) -> None:
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]'
        )
        backend = FakeSandboxBackend(
            [SandboxResult(0, "partial", "", False, 5, stdout_truncated=True)]
        )
        result = SandboxedWorkspaceVerifier(
            self.runtime, backend, self.workspaces
        ).verify(self.workspace_id)
        self.assertFalse(result.passed)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_backend_error_records_blocked_without_condemning_patch(self) -> None:
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]'
        )
        backend = FakeSandboxBackend(error=RuntimeError("sandbox unavailable mid-run"))
        result = SandboxedWorkspaceVerifier(
            self.runtime, backend, self.workspaces
        ).verify(self.workspace_id)
        self.assertFalse(result.passed)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )
        with self.runtime.store.session() as conn:
            status = conn.execute(
                "SELECT status FROM verifications WHERE id = ?",
                (result.results[0].verification_id,),
            ).fetchone()["status"]
        self.assertEqual(status, "BLOCKED")

    def test_backend_without_isolation_guarantees_is_rejected(self) -> None:
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]'
        )
        backend = FakeSandboxBackend(
            [SandboxResult(0, "", "", False, 1)],
            guarantees=SandboxGuarantees(True, True, False, True),
        )
        with self.assertRaises(SandboxPolicyError):
            SandboxedWorkspaceVerifier(
                self.runtime, backend, self.workspaces
            ).verify(self.workspace_id)
        self.assertEqual(backend.jobs, [])

    def test_no_required_commands_cannot_promote_workspace(self) -> None:
        self._write_config(commands='build = []\ntest = []')
        backend = FakeSandboxBackend([])
        with self.assertRaises(RuntimeInvariantError):
            SandboxedWorkspaceVerifier(
                self.runtime, backend, self.workspaces
            ).verify(self.workspace_id)
        self.assertEqual(
            self.workspaces.get(self.workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )

    def test_verifier_requires_audited_workspace(self) -> None:
        current = self.workspaces.get(self.workspace_id)
        self.workspaces.transition(
            self.workspace_id,
            WorkspaceStatus.FAILED,
            expected_revision=int(current["revision"]),
            event_type="TEST_FORCE_FAILED",
        )
        self._write_config(
            commands='build = []\ntest = [{ name = "unit", argv = ["x"] }]'
        )
        with self.assertRaises(RuntimeInvariantError):
            SandboxedWorkspaceVerifier(
                self.runtime,
                FakeSandboxBackend([SandboxResult(0, "", "", False, 1)]),
                self.workspaces,
            ).verify(self.workspace_id)


if __name__ == "__main__":
    unittest.main()
