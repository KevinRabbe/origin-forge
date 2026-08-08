from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.apply import IsolatedPatchApplier
from origin_forge.context import ContextBuilder
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration import BoundedTaskOrchestrator
from origin_forge.orchestration_policy import (
    BoundedRetryPolicy,
    PolicyAction,
    PolicyOutcome,
)
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.sandbox import SandboxGuarantees, SandboxJob, SandboxResult
from origin_forge.state import FlowStatus, TaskStatus, WorkspaceStatus
from origin_forge.worker import LocalPatchWorker
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
    def __init__(self, model_id: str, response_text: str):
        self._model_id = model_id
        self.response_text = response_text
        self.calls = 0
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        self.requests.append(request)
        return ModelResponse(self.response_text, self.model_id)


class NeverModel(FakeModel):
    def generate(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("model must not be called while resuming durable workspace state")


class FakeSandbox:
    backend_id = "fake-policy-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    def __init__(
        self,
        results: list[SandboxResult] | None = None,
        *,
        available: bool = True,
        errors: list[Exception | None] | None = None,
    ):
        self._results = list(results or [])
        self._available = available
        self._errors = list(errors or [])
        self.jobs: list[SandboxJob] = []

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return self._available

    def run(self, job: SandboxJob) -> SandboxResult:
        self.jobs.append(job)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        if not self._results:
            raise RuntimeError("no fake sandbox result queued")
        return self._results.pop(0)


class BoundedRetryPolicyTests(unittest.TestCase):
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
        self.runtime.initialize("retry-policy-test")
        self._write_config(max_retries=2, max_verification_failures=3)
        goal = self.runtime.create_goal("retry policy")
        self.flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "change greeting")
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.workspaces = GitWorkspaceManager(self.runtime)
        self.expected_hash = RepositoryReader(self.root).hash_file("hello.py")

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _write_config(
        self,
        *,
        max_retries: int,
        max_verification_failures: int,
    ) -> None:
        (self.root / ".origin-forge" / "config.toml").write_text(
            f'''version = 3\npolicy_profile = "local-default"\n[limits]\nmax_strategy_retries = {max_retries}\nmax_verification_failures = {max_verification_failures}\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\nmemory = "1g"\ncpus = 1.0\npids_limit = 64\n[commands]\nbuild = []\ntest = [{{ name = "unit", argv = ["test-runner"], required = true }}]\n''',
            encoding="utf-8",
        )

    def _proposal(self, content: str, *, summary: str | None = None) -> str:
        return json.dumps(
            {
                "summary": summary or f"set greeting to {content}",
                "changes": [
                    {
                        "operation": "UPDATE",
                        "path": "hello.py",
                        "expected_hash": self.expected_hash,
                        "content": content,
                    }
                ],
                "notes": [],
            }
        )

    def test_escalates_models_and_succeeds_with_bounded_retries(self) -> None:
        small = FakeModel("small", "not json")
        medium = FakeModel("medium", "also not json")
        strong = FakeModel("strong", self._proposal("print('good')\n"))
        sandbox = FakeSandbox([SandboxResult(0, "ok", "", False, 2)])

        result = BoundedRetryPolicy(
            self.runtime,
            [small, medium, strong],
            sandbox,
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual(result.executor_attempts, 3)
        self.assertEqual(result.attempts_started, 3)
        self.assertEqual([small.calls, medium.calls, strong.calls], [1, 1, 1])
        runs = [run for run in self.runtime.list_runs(self.task) if run["role"] == "EXECUTOR"]
        self.assertEqual([run["model_profile"] for run in runs], ["small", "medium", "strong"])
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.SUCCEEDED.value)

    def test_retries_failed_verification_with_next_model(self) -> None:
        first = FakeModel("small", self._proposal("print('first')\n"))
        second = FakeModel("large", self._proposal("print('second')\n"))
        sandbox = FakeSandbox(
            [
                SandboxResult(1, "", "tests failed", False, 2),
                SandboxResult(0, "ok", "", False, 2),
            ]
        )
        result = BoundedRetryPolicy(
            self.runtime,
            [first, second],
            sandbox,
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual([first.calls, second.calls], [1, 1])
        workspaces = self.workspaces.list(self.task)
        self.assertEqual(workspaces[0]["status"], WorkspaceStatus.ABANDONED.value)
        self.assertEqual(workspaces[-1]["status"], WorkspaceStatus.VERIFIED.value)

    def test_exact_repeated_proposal_quarantines_before_third_attempt(self) -> None:
        repeated = self._proposal("print('same')\n", summary="same strategy")
        first = FakeModel("small", repeated)
        second = FakeModel("large", repeated)
        third = FakeModel("largest", self._proposal("print('unused')\n"))
        sandbox = FakeSandbox(
            [
                SandboxResult(1, "", "fail", False, 1),
                SandboxResult(1, "", "fail", False, 1),
            ]
        )

        result = BoundedRetryPolicy(
            self.runtime,
            [first, second, third],
            sandbox,
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.QUARANTINED)
        self.assertIn("repeated", result.reason)
        self.assertEqual([first.calls, second.calls, third.calls], [1, 1, 0])
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.QUARANTINED.value)

    def test_strategy_budget_quarantines_after_total_allowed_attempts(self) -> None:
        self._write_config(max_retries=1, max_verification_failures=10)
        first = FakeModel("small", "bad one")
        second = FakeModel("large", "bad two")
        third = FakeModel("unused", self._proposal("print('unused')\n"))
        result = BoundedRetryPolicy(
            self.runtime,
            [first, second, third],
            FakeSandbox([]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.QUARANTINED)
        self.assertIn("strategy retry budget exhausted", result.reason)
        self.assertEqual([first.calls, second.calls, third.calls], [1, 1, 0])
        self.assertEqual(result.executor_attempts, 2)

    def test_verification_failure_budget_can_stop_before_strategy_budget(self) -> None:
        self._write_config(max_retries=5, max_verification_failures=1)
        first = FakeModel("small", self._proposal("print('first')\n"))
        second = FakeModel("large", self._proposal("print('unused')\n"))
        result = BoundedRetryPolicy(
            self.runtime,
            [first, second],
            FakeSandbox([SandboxResult(1, "", "fail", False, 1)]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.QUARANTINED)
        self.assertIn("verification failure budget exhausted", result.reason)
        self.assertEqual([first.calls, second.calls], [1, 0])

    def test_resumes_audited_workspace_without_model_call(self) -> None:
        model = FakeModel("initial", self._proposal("print('candidate')\n"))
        blocked = BoundedTaskOrchestrator(
            self.runtime,
            model,
            FakeSandbox(
                [SandboxResult(0, "unused", "", False, 1)],
                errors=[RuntimeError("sandbox outage")],
            ),
            workspaces=self.workspaces,
        ).execute(self.task, selected_paths=["hello.py"])
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.BLOCKED.value)
        self.assertEqual(
            self.workspaces.get(blocked.workspace_id)["status"], WorkspaceStatus.AUDITED.value
        )

        never = NeverModel("never", "")
        result = BoundedRetryPolicy(
            self.runtime,
            [never],
            FakeSandbox([SandboxResult(0, "ok", "", False, 1)]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual(result.action, PolicyAction.RESUME_SANDBOX)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.SUCCEEDED.value)

    def test_resumes_applied_workspace_through_audit_and_sandbox(self) -> None:
        task = self.runtime.get_task(self.task)
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=int(task["revision"])
        )
        workspace_id = self.workspaces.create(self.task)
        repository = RepositoryReader(self.workspaces.path(workspace_id))
        model = FakeModel("initial", self._proposal("print('candidate')\n"))
        worker = LocalPatchWorker(
            self.runtime,
            model,
            repository=repository,
            context_builder=ContextBuilder(self.runtime, repository),
        ).execute(self.task, selected_paths=["hello.py"])
        IsolatedPatchApplier(self.runtime, self.workspaces).apply_artifact(
            workspace_id, worker.proposal_artifact_id
        )
        self.assertEqual(
            self.workspaces.get(workspace_id)["status"], WorkspaceStatus.APPLIED.value
        )

        never = NeverModel("never", "")
        result = BoundedRetryPolicy(
            self.runtime,
            [never],
            FakeSandbox([SandboxResult(0, "ok", "", False, 1)]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual(self.workspaces.get(workspace_id)["status"], WorkspaceStatus.VERIFIED.value)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.SUCCEEDED.value)

    def test_clean_created_workspace_is_abandoned_and_retried(self) -> None:
        task = self.runtime.get_task(self.task)
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=int(task["revision"])
        )
        old_workspace = self.workspaces.create(self.task)
        model = FakeModel("primary", self._proposal("print('new')\n"))
        result = BoundedRetryPolicy(
            self.runtime,
            [model],
            FakeSandbox([SandboxResult(0, "ok", "", False, 1)]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual(self.workspaces.get(old_workspace)["status"], WorkspaceStatus.ABANDONED.value)
        self.assertEqual(model.calls, 1)

    def test_dirty_created_workspace_is_quarantined_without_model_call(self) -> None:
        task = self.runtime.get_task(self.task)
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=int(task["revision"])
        )
        workspace_id = self.workspaces.create(self.task)
        (self.workspaces.path(workspace_id) / "partial.txt").write_text(
            "partial\n", encoding="utf-8"
        )
        never = NeverModel("never", "")

        result = BoundedRetryPolicy(
            self.runtime,
            [never],
            FakeSandbox([]),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.QUARANTINED)
        self.assertIn("partial changes", result.reason)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.QUARANTINED.value)
        self.assertEqual(self.workspaces.get(workspace_id)["status"], WorkspaceStatus.CREATED.value)

    def test_unavailable_sandbox_blocks_without_retrying_model(self) -> None:
        model = FakeModel("primary", self._proposal("print('new')\n"))
        result = BoundedRetryPolicy(
            self.runtime,
            [model],
            FakeSandbox([], available=False),
            workspaces=self.workspaces,
        ).drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.BLOCKED)
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.BLOCKED.value)


if __name__ == "__main__":
    unittest.main()
