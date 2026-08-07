from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration import (
    AttemptOutcome,
    AttemptStage,
    BoundedTaskOrchestrator,
)
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime, RuntimeInvariantError
from origin_forge.sandbox import SandboxGuarantees, SandboxJob, SandboxResult
from origin_forge.state import FlowStatus, TaskStatus, WorkspaceStatus
from origin_forge.workspaces import GitWorkspaceManager


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class FakeModel:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    @property
    def model_id(self) -> str:
        return "fake-orchestrator-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(self.response_text, self.model_id)


class FakeSandbox:
    backend_id = "fake-secure"
    guarantees = SandboxGuarantees(True, True, True, True)

    def __init__(
        self,
        results: list[SandboxResult] | None = None,
        *,
        available: bool = True,
        error: Exception | None = None,
    ):
        self._results = list(results or [])
        self._available = available
        self.error = error
        self.jobs: list[SandboxJob] = []

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return self._available

    def run(self, job: SandboxJob) -> SandboxResult:
        self.jobs.append(job)
        if self.error is not None:
            raise self.error
        if not self._results:
            raise RuntimeError("no fake sandbox result queued")
        return self._results.pop(0)


class BoundedOrchestrationTests(unittest.TestCase):
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
        self.runtime.initialize("orchestration-test")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3\npolicy_profile = "local-default"\n[limits]\nmax_strategy_retries = 2\nmax_verification_failures = 3\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\nmemory = "1g"\ncpus = 1.0\npids_limit = 64\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]\n''',
            encoding="utf-8",
        )
        self.goal = self.runtime.create_goal("update greeting")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(
            self.flow,
            "change hello.py",
            acceptance_criteria=["sandbox verification passes"],
        )
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _model_for_update(self) -> FakeModel:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        return FakeModel(
            json.dumps(
                {
                    "summary": "update greeting",
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

    def test_successful_attempt_completes_verified_pipeline_once(self) -> None:
        model = self._model_for_update()
        sandbox = FakeSandbox([SandboxResult(0, "ok", "", False, 5)])
        result = BoundedTaskOrchestrator(
            self.runtime, model, sandbox, workspaces=self.workspaces
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.SUCCEEDED)
        self.assertEqual(result.stage, AttemptStage.COMPLETE)
        self.assertEqual(model.calls, 1)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.SUCCEEDED.value
        )
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.VERIFIED.value,
        )
        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")
        verifications = self.runtime.list_verifications("TASK", self.task)
        self.assertEqual(verifications[-1]["status"], "PASS")

    def test_empty_proposal_blocks_without_workspace_or_retry(self) -> None:
        model = FakeModel(
            json.dumps(
                {
                    "summary": "need more context",
                    "changes": [],
                    "notes": ["missing dependency"],
                }
            )
        )
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox([SandboxResult(0, "", "", False, 1)]),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.BLOCKED)
        self.assertEqual(result.stage, AttemptStage.EXECUTOR)
        self.assertEqual(model.calls, 1)
        self.assertIsNone(result.workspace_id)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.BLOCKED.value
        )
        self.assertEqual(self.workspaces.list(self.task), [])

    def test_preflight_sandbox_unavailable_blocks_before_model_call(self) -> None:
        model = self._model_for_update()
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox(available=False),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.BLOCKED)
        self.assertEqual(result.stage, AttemptStage.PREFLIGHT)
        self.assertEqual(model.calls, 0)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.BLOCKED.value
        )
        self.assertIsNotNone(result.task_verification_id)

    def test_invalid_model_output_fails_task_without_workspace(self) -> None:
        model = FakeModel("not json")
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox([SandboxResult(0, "", "", False, 1)]),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.FAILED)
        self.assertEqual(result.stage, AttemptStage.EXECUTOR)
        self.assertEqual(model.calls, 1)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.FAILED.value
        )
        self.assertEqual(self.workspaces.list(self.task), [])

    def test_failed_sandbox_command_fails_task_and_workspace(self) -> None:
        model = self._model_for_update()
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox([SandboxResult(1, "", "tests failed", False, 3)]),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.FAILED)
        self.assertEqual(result.stage, AttemptStage.SANDBOX)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.FAILED.value
        )
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )
        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")

    def test_sandbox_infrastructure_error_blocks_task_and_keeps_audited_workspace(self) -> None:
        model = self._model_for_update()
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox(error=RuntimeError("sandbox outage")),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, AttemptOutcome.BLOCKED)
        self.assertEqual(result.stage, AttemptStage.SANDBOX)
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.BLOCKED.value
        )
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.AUDITED.value,
        )

    def test_requires_ready_task_and_running_flow(self) -> None:
        model = self._model_for_update()
        self.runtime.transition_task(
            self.task,
            TaskStatus.CANCELLED,
            expected_revision=int(self.runtime.get_task(self.task)["revision"]),
        )
        with self.assertRaises(RuntimeInvariantError):
            BoundedTaskOrchestrator(
                self.runtime, model, FakeSandbox(available=True), workspaces=self.workspaces
            ).execute(self.task, selected_paths=["hello.py"])

    def test_requires_running_flow_without_starting_task(self) -> None:
        goal = self.runtime.create_goal("other")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "ready but flow queued")
        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        model = self._model_for_update()
        with self.assertRaises(RuntimeInvariantError):
            BoundedTaskOrchestrator(
                self.runtime, model, FakeSandbox(available=True), workspaces=self.workspaces
            ).execute(task, selected_paths=["hello.py"])
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.runtime.get_task(task)["status"], TaskStatus.READY.value)

    def test_existing_active_workspace_must_be_resumed_or_abandoned(self) -> None:
        workspace_id = self.workspaces.create(
            self._running_task_for_workspace_preflight()
        )
        task_id = self.workspaces.get(workspace_id)["task_id"]
        task = self.runtime.get_task(task_id)
        self.runtime.transition_task(
            task_id, TaskStatus.BLOCKED, expected_revision=int(task["revision"])
        )
        blocked = self.runtime.get_task(task_id)
        self.runtime.transition_task(
            task_id, TaskStatus.READY, expected_revision=int(blocked["revision"])
        )
        model = self._model_for_update()
        with self.assertRaisesRegex(RuntimeInvariantError, "active workspace"):
            BoundedTaskOrchestrator(
                self.runtime, model, FakeSandbox(available=True), workspaces=self.workspaces
            ).execute(task_id, selected_paths=["hello.py"])
        self.assertEqual(model.calls, 0)

    def _running_task_for_workspace_preflight(self) -> str:
        goal = self.runtime.create_goal("workspace-resume")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "workspace exists")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        return task

    def test_audit_exception_fails_task_and_workspace(self) -> None:
        model = self._model_for_update()
        orchestrator = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox([SandboxResult(0, "ok", "", False, 1)]),
            workspaces=self.workspaces,
        )
        with patch(
            "origin_forge.orchestration.WorkspaceAuditor.audit_artifact",
            side_effect=RuntimeError("audit crashed"),
        ):
            result = orchestrator.execute(self.task, selected_paths=["hello.py"])
        self.assertEqual(result.outcome, AttemptOutcome.FAILED)
        self.assertEqual(result.stage, AttemptStage.AUDIT)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.FAILED.value)
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.FAILED.value,
        )

    def test_no_required_verification_commands_refuses_to_start(self) -> None:
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\n[commands]\nbuild = []\ntest = []\n''',
            encoding="utf-8",
        )
        model = self._model_for_update()
        with self.assertRaisesRegex(RuntimeInvariantError, "required sandbox verification"):
            BoundedTaskOrchestrator(
                self.runtime, model, FakeSandbox(available=True), workspaces=self.workspaces
            ).execute(self.task, selected_paths=["hello.py"])
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.READY.value)

    def test_requires_explicit_context_files(self) -> None:
        with self.assertRaises(ValueError):
            BoundedTaskOrchestrator(
                self.runtime,
                self._model_for_update(),
                FakeSandbox(available=True),
                workspaces=self.workspaces,
            ).execute(self.task, selected_paths=[])


if __name__ == "__main__":
    unittest.main()
