from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.orchestration import AttemptOutcome, AttemptStage, BoundedTaskOrchestrator
from origin_forge.orchestration_policy import BoundedRetryPolicy, PolicyOutcome
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


class RecordingModel:
    def __init__(self, response: str, model_id: str):
        self.response = response
        self._model_id = model_id
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.response, self.model_id)


class SequencedSandbox:
    backend_id = "phase10-test-sandbox"
    guarantees = SandboxGuarantees(True, True, True, True)

    def __init__(self, exit_codes: tuple[int, ...] = (0,)):
        self.exit_codes = list(exit_codes)
        self.calls = 0

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return True

    def run(self, job: SandboxJob) -> SandboxResult:
        index = min(self.calls, len(self.exit_codes) - 1)
        code = self.exit_codes[index]
        self.calls += 1
        return SandboxResult(code, "ok" if code == 0 else "", "" if code == 0 else "failed", False, 1)


class Phase10ContextOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Origin Forge Test")

        src = self.root / "src"
        tests = self.root / "tests"
        src.mkdir()
        tests.mkdir()
        (src / "models.py").write_text(
            "class WidgetParser:\n"
            "    def parse(self, value):\n"
            "        return value\n",
            encoding="utf-8",
        )
        (src / "service.py").write_text(
            "from models import WidgetParser\n\n"
            "def build_widget(value):\n"
            "    return WidgetParser().parse(value)\n",
            encoding="utf-8",
        )
        (tests / "test_service.py").write_text(
            "from service import build_widget\n\n"
            "def test_build_widget():\n"
            "    assert build_widget('x') == 'x'\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src", "tests")
        git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase10-integration")
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 3
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false

[commands]
build = []
test = [{ name = "unit", argv = ["test-runner"], required = true }]
''',
            encoding="utf-8",
        )
        self.workspaces = GitWorkspaceManager(self.runtime)

    def tearDown(self) -> None:
        for workspace in self.workspaces.list():
            try:
                self.workspaces.abandon(workspace["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def _ready_task(self, objective: str) -> str:
        goal = self.runtime.create_goal("Phase 10 integration")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, objective)
        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        return task

    def _response(self, *, value: str) -> str:
        expected = RepositoryReader(self.root).hash_file("src/service.py")
        return json.dumps(
            {
                "summary": f"change service to {value}",
                "changes": [
                    {
                        "operation": "UPDATE",
                        "path": "src/service.py",
                        "expected_hash": expected,
                        "content": (
                            "from models import WidgetParser\n\n"
                            "def build_widget(value):\n"
                            f"    return {value!r}\n"
                        ),
                    }
                ],
                "notes": [],
            }
        )

    def test_one_shot_manual_structural_expansion_reaches_executor(self) -> None:
        task = self._ready_task("Change build_widget behavior")
        model = RecordingModel(self._response(value="new"), "model-a")
        result = BoundedTaskOrchestrator(
            self.runtime,
            model,
            SequencedSandbox(),
            workspaces=self.workspaces,
        ).execute(
            task,
            selected_paths=["src/service.py"],
            structural_context=True,
        )

        self.assertEqual(result.outcome, AttemptOutcome.SUCCEEDED)
        self.assertEqual(result.context_paths[0], "src/service.py")
        self.assertIn("src/models.py", result.context_paths)
        request_paths = tuple(item["path"] for item in model.requests[0].context["files"])
        self.assertEqual(request_paths, result.context_paths)

    def test_retry_policy_auto_context_blocks_once_when_no_evidence_exists(self) -> None:
        task = self._ready_task("Implement quantum banana telemetry")
        model = RecordingModel("must not be called", "model-a")
        result = BoundedRetryPolicy(
            self.runtime,
            [model],
            SequencedSandbox(),
            workspaces=self.workspaces,
        ).drive(task, auto_context=True)

        self.assertEqual(result.outcome, PolicyOutcome.BLOCKED)
        self.assertEqual(result.attempts_started, 1)
        self.assertEqual(result.executor_attempts, 0)
        self.assertEqual(model.requests, [])
        self.assertIsNotNone(result.last_attempt)
        self.assertEqual(result.last_attempt.stage, AttemptStage.CONTEXT)
        self.assertEqual(self.runtime.get_task(task)["status"], TaskStatus.BLOCKED.value)

    def test_retry_reselects_auto_structural_context_in_each_fresh_workspace(self) -> None:
        task = self._ready_task("Change build_widget service behavior")
        first = RecordingModel(self._response(value="first"), "model-small")
        second = RecordingModel(self._response(value="second"), "model-strong")
        sandbox = SequencedSandbox((1, 0))

        result = BoundedRetryPolicy(
            self.runtime,
            [first, second],
            sandbox,
            workspaces=self.workspaces,
        ).drive(
            task,
            auto_context=True,
            structural_context=True,
        )

        self.assertEqual(result.outcome, PolicyOutcome.SUCCEEDED)
        self.assertEqual(result.attempts_started, 2)
        self.assertEqual(result.executor_attempts, 2)
        self.assertEqual(len(first.requests), 1)
        self.assertEqual(len(second.requests), 1)
        first_paths = tuple(item["path"] for item in first.requests[0].context["files"])
        second_paths = tuple(item["path"] for item in second.requests[0].context["files"])
        self.assertEqual(first_paths, second_paths)
        self.assertIn("src/service.py", first_paths)
        self.assertIn("src/models.py", first_paths)

        workspaces = self.workspaces.list(task)
        self.assertGreaterEqual(len(workspaces), 2)
        self.assertNotEqual(workspaces[0]["id"], workspaces[-1]["id"])


if __name__ == "__main__":
    unittest.main()
