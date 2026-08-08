from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration_policy import BoundedRetryPolicy, PolicyAction, PolicyOutcome
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.sandbox import SandboxGuarantees, SandboxJob, SandboxResult
from origin_forge.state import FlowStatus, TaskStatus
from origin_forge.workspaces import GitWorkspaceManager


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class CountingModel:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    @property
    def model_id(self) -> str:
        return "counting-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(self.response, self.model_id)


class PassingSandbox:
    backend_id = "passing-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return True

    def run(self, job: SandboxJob) -> SandboxResult:
        return SandboxResult(0, "ok", "", False, 1)


class PolicyInfrastructureBoundTests(unittest.TestCase):
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
        self.runtime.initialize("policy-edge-test")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3\n[limits]\nmax_strategy_retries = 5\nmax_verification_failures = 5\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]\n''',
            encoding="utf-8",
        )
        goal = self.runtime.create_goal("bounded infra failure")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "change greeting")
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def test_workspace_creation_failure_stops_without_model_retry_loop(self) -> None:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        model = CountingModel(
            json.dumps(
                {
                    "summary": "unused",
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
        policy = BoundedRetryPolicy(
            self.runtime,
            [model],
            PassingSandbox(),
            workspaces=self.workspaces,
        )

        with patch.object(
            self.workspaces, "create", side_effect=RuntimeError("workspace service down")
        ) as create:
            result = policy.drive(self.task, selected_paths=["hello.py"])

        self.assertEqual(result.outcome, PolicyOutcome.FAILED)
        self.assertEqual(result.action, PolicyAction.STOP)
        self.assertEqual(result.attempts_started, 1)
        self.assertEqual(result.executor_attempts, 0)
        self.assertEqual(model.calls, 0)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(self.runtime.get_task(self.task)["status"], TaskStatus.FAILED.value)


if __name__ == "__main__":
    unittest.main()
