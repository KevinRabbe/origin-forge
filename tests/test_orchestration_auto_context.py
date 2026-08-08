from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration import AttemptOutcome, AttemptStage, BoundedTaskOrchestrator
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
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


class RecordingModel:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return "auto-context-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        self.requests.append(request)
        return ModelResponse(self.response, self.model_id)


class PassingSandbox:
    backend_id = "auto-context-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return True

    def run(self, job: SandboxJob) -> SandboxResult:
        return SandboxResult(0, "ok", "", False, 2)


class AutoContextOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")
        (self.root / "docs").mkdir()
        self.source = self.root / "hello.py"
        self.source.write_text("print('old')\n", encoding="utf-8")
        (self.root / "docs" / "architecture.md").write_text(
            "Unrelated architecture notes.\n", encoding="utf-8"
        )
        git(self.root, "add", "hello.py", "docs/architecture.md")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("auto-context-test")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3\n[sandbox]\nbackend = "unconfigured"\nimage = ""\nnetwork = false\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["test-runner"], required = true }]\n''',
            encoding="utf-8",
        )
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for row in self.workspaces.list():
            try:
                self.workspaces.abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _ready_task(self, objective: str) -> str:
        goal = self.runtime.create_goal("auto context")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, objective)
        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        return task

    def _update_model(self) -> RecordingModel:
        expected = RepositoryReader(self.root).hash_file("hello.py")
        return RecordingModel(
            json.dumps(
                {
                    "summary": "change hello greeting",
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

    def test_auto_context_discovers_inside_workspace_and_completes(self) -> None:
        task = self._ready_task("Change hello greeting")
        model = self._update_model()
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            PassingSandbox(),
            workspaces=self.workspaces,
        ).execute(task, auto_context=True)

        self.assertEqual(result.outcome, AttemptOutcome.SUCCEEDED)
        self.assertEqual(result.context_paths, ("hello.py",))
        self.assertEqual(model.calls, 1)
        self.assertEqual(
            [item["path"] for item in model.requests[0].context["files"]],
            ["hello.py"],
        )
        self.assertEqual(self.runtime.get_task(task)["status"], TaskStatus.SUCCEEDED.value)
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.VERIFIED.value,
        )

    def test_auto_context_cannot_see_dirty_live_checkout(self) -> None:
        task = self._ready_task("Change hello greeting")
        model = self._update_model()
        self.source.write_text("print('user-dirty')\n", encoding="utf-8")

        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            PassingSandbox(),
            workspaces=self.workspaces,
        ).execute(task, auto_context=True)

        self.assertEqual(result.outcome, AttemptOutcome.SUCCEEDED)
        self.assertEqual(
            model.requests[0].context["files"][0]["content"],
            "print('old')\n",
        )
        self.assertEqual(
            self.source.read_text(encoding="utf-8"),
            "print('user-dirty')\n",
        )

    def test_no_relevant_auto_context_blocks_before_model(self) -> None:
        task = self._ready_task("Implement quantum banana telemetry")
        model = RecordingModel("must not be used")

        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            PassingSandbox(),
            workspaces=self.workspaces,
        ).execute(task, auto_context=True)

        self.assertEqual(result.outcome, AttemptOutcome.BLOCKED)
        self.assertEqual(result.stage, AttemptStage.CONTEXT)
        self.assertEqual(model.calls, 0)
        self.assertEqual(result.context_paths, ())
        self.assertEqual(self.runtime.get_task(task)["status"], TaskStatus.BLOCKED.value)
        self.assertEqual(
            self.workspaces.get(result.workspace_id)["status"],
            WorkspaceStatus.ABANDONED.value,
        )

    def test_seed_file_is_included_with_auto_context(self) -> None:
        task = self._ready_task("Change hello greeting")
        model = self._update_model()

        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            PassingSandbox(),
            workspaces=self.workspaces,
        ).execute(
            task,
            auto_context=True,
            context_seed_paths=["docs/architecture.md"],
        )

        self.assertEqual(result.outcome, AttemptOutcome.SUCCEEDED)
        self.assertEqual(result.context_paths[0], "docs/architecture.md")
        self.assertIn("hello.py", result.context_paths)
        request_paths = [item["path"] for item in model.requests[0].context["files"]]
        self.assertEqual(request_paths[0], "docs/architecture.md")
        self.assertIn("hello.py", request_paths)

    def test_auto_context_and_explicit_paths_are_mutually_exclusive(self) -> None:
        task = self._ready_task("Change hello greeting")
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            BoundedTaskOrchestrator(
                self.runtime,
                self._update_model(),
                PassingSandbox(),
                workspaces=self.workspaces,
            ).execute(
                task,
                selected_paths=["hello.py"],
                auto_context=True,
            )

    def test_seed_paths_require_auto_context(self) -> None:
        task = self._ready_task("Change hello greeting")
        with self.assertRaisesRegex(ValueError, "require auto_context"):
            BoundedTaskOrchestrator(
                self.runtime,
                self._update_model(),
                PassingSandbox(),
                workspaces=self.workspaces,
            ).execute(
                task,
                selected_paths=["hello.py"],
                context_seed_paths=["docs/architecture.md"],
            )


if __name__ == "__main__":
    unittest.main()
