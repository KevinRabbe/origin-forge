from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from origin_forge.orchestration_cli import main
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.sandbox import SandboxGuarantees, SandboxJob, SandboxResult
from origin_forge.state import FlowStatus, TaskStatus


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


class FakeModel:
    def __init__(self, response: str):
        self.response = response

    @property
    def model_id(self) -> str:
        return "fake-cli-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(self.response, self.model_id)


class FakeSandbox:
    backend_id = "fake-cli-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    def __init__(self, *, available: bool = True):
        self._available = available

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return self._available

    def run(self, job: SandboxJob) -> SandboxResult:
        return SandboxResult(0, "ok", "", False, 2)


class OrchestrationCliTests(unittest.TestCase):
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
        self.runtime.initialize("orchestration-cli")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]\n''',
            encoding="utf-8",
        )
        goal = self.runtime.create_goal("cli goal")
        self.flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "change greeting")
        self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)

    def tearDown(self) -> None:
        from origin_forge.workspaces import GitWorkspaceManager

        workspaces = GitWorkspaceManager(self.runtime)
        for row in workspaces.list():
            try:
                workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _model(self) -> FakeModel:
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

    def test_attempt_cli_runs_bounded_pipeline_without_merging(self) -> None:
        output = StringIO()
        with patch(
            "origin_forge.orchestration_cli.LlamaCppAdapter",
            return_value=self._model(),
        ), patch(
            "origin_forge.orchestration_cli.create_sandbox_backend",
            return_value=FakeSandbox(),
        ), redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    self.task,
                    "--file",
                    "hello.py",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["outcome"], "SUCCEEDED")
        self.assertEqual(payload["stage"], "COMPLETE")
        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")
        self.assertEqual(
            self.runtime.get_task(self.task)["status"], TaskStatus.SUCCEEDED.value
        )

    def test_attempt_cli_returns_blocked_code_when_preflight_cannot_verify(self) -> None:
        output = StringIO()
        with patch(
            "origin_forge.orchestration_cli.LlamaCppAdapter",
            return_value=self._model(),
        ), patch(
            "origin_forge.orchestration_cli.create_sandbox_backend",
            return_value=FakeSandbox(available=False),
        ), redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    self.task,
                    "--file",
                    "hello.py",
                ]
            )
        self.assertEqual(code, 13)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["outcome"], "BLOCKED")
        self.assertEqual(payload["stage"], "PREFLIGHT")


if __name__ == "__main__":
    unittest.main()
