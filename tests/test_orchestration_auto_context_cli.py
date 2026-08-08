from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration_cli import main
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
        return "auto-context-cli-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(self.response, self.model_id)


class FakeSandbox:
    backend_id = "auto-context-cli-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return True

    def run(self, job: SandboxJob) -> SandboxResult:
        return SandboxResult(0, "ok", "", False, 1)


class AutoContextCliTests(unittest.TestCase):
    def test_cli_auto_context_selects_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Origin Forge Test")
            (root / "hello.py").write_text("print('old')\n", encoding="utf-8")
            git(root, "add", "hello.py")
            git(root, "commit", "-qm", "initial")

            runtime = OriginForgeRuntime(root)
            runtime.initialize("auto-context-cli")
            (root / ".origin-forge" / "config.toml").write_text(
                '''version = 3\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]\n''',
                encoding="utf-8",
            )
            goal = runtime.create_goal("auto cli")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "Change hello greeting")
            runtime.transition_task(task, TaskStatus.READY, expected_revision=0)

            expected = RepositoryReader(root).hash_file("hello.py")
            model = FakeModel(
                json.dumps(
                    {
                        "summary": "change hello",
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

            output = StringIO()
            with patch(
                "origin_forge.orchestration_cli.LlamaCppAdapter",
                return_value=model,
            ), patch(
                "origin_forge.orchestration_cli.create_sandbox_backend",
                return_value=FakeSandbox(),
            ), redirect_stdout(output):
                code = main(
                    [
                        "--project-root",
                        str(root),
                        task,
                        "--auto-context",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["outcome"], "SUCCEEDED")
            self.assertEqual(payload["context_paths"], ["hello.py"])

            from origin_forge.workspaces import GitWorkspaceManager

            workspaces = GitWorkspaceManager(runtime)
            for row in workspaces.list():
                try:
                    workspaces.abandon(row["id"])
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
