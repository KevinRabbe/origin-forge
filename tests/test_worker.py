from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.context import ContextBuilder
from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.patches import PatchValidationError, parse_patch_proposal
from origin_forge.repository import ContextBudgetExceeded, RepositoryAccessError, RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus
from origin_forge.worker import LocalPatchWorker


class FakeModel:
    def __init__(self, response_text: str, model_id: str = "fake-local-model"):
        self.response_text = response_text
        self._model_id = model_id
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.response_text, self.model_id)


class PhaseTwoWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase-two-test")
        self.source = self.root / "hello.py"
        self.source.write_text("print('old')\n", encoding="utf-8")

        goal = self.runtime.create_goal("Update greeting")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(
            flow,
            "Change hello.py greeting",
            acceptance_criteria=["hello.py prints new"],
            constraints=["do not change other files"],
            required_capabilities=["code-edit"],
        )
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_repository_reader_is_contained_and_protects_state(self) -> None:
        reader = RepositoryReader(self.root)
        source = reader.read_text("hello.py")
        self.assertEqual(source.content, "print('old')\n")
        self.assertTrue(source.content_hash.startswith("sha256:"))
        with self.assertRaises(RepositoryAccessError):
            reader.read_text("../outside.txt")
        with self.assertRaises(RepositoryAccessError):
            reader.read_text(".origin-forge/config.toml")

    def test_context_builder_only_includes_selected_files(self) -> None:
        other = self.root / "other.py"
        other.write_text("ignored = True\n", encoding="utf-8")
        package = ContextBuilder(self.runtime).build(self.task, ["hello.py"])
        self.assertEqual(package.objective, "Change hello.py greeting")
        self.assertEqual([file.path for file in package.files], ["hello.py"])
        self.assertNotIn("other.py", json.dumps(package.to_dict()))

    def test_context_budget_is_enforced(self) -> None:
        reader = RepositoryReader(self.root, max_file_bytes=4)
        with self.assertRaises(ContextBudgetExceeded):
            reader.read_text("hello.py")

    def test_patch_parser_rejects_protected_path(self) -> None:
        raw = json.dumps(
            {
                "summary": "tamper",
                "changes": [
                    {
                        "operation": "CREATE",
                        "path": ".origin-forge/config.toml",
                        "expected_hash": None,
                        "content": "bad",
                    }
                ],
            }
        )
        with self.assertRaises(PatchValidationError):
            parse_patch_proposal(raw)

    def test_worker_persists_valid_proposal_without_applying_it(self) -> None:
        reader = RepositoryReader(self.root)
        expected = reader.hash_file("hello.py")
        response = json.dumps(
            {
                "summary": "Update greeting",
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
        model = FakeModel(response)
        result = LocalPatchWorker(self.runtime, model).execute(
            self.task, selected_paths=["hello.py"]
        )

        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")
        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(model.requests[0].context["files"][0]["content_hash"], expected)

        with self.runtime.store.session() as conn:
            artifacts = conn.execute(
                "SELECT type, status FROM artifacts WHERE created_by_run_id = ? ORDER BY created_at, rowid",
                (result.run_id,),
            ).fetchall()
        self.assertEqual(
            [row["type"] for row in artifacts],
            ["CONTEXT_PACKAGE", "MODEL_RESPONSE", "PATCH_PROPOSAL"],
        )

    def test_stale_proposal_fails_run_and_does_not_modify_file(self) -> None:
        response = json.dumps(
            {
                "summary": "stale",
                "changes": [
                    {
                        "operation": "UPDATE",
                        "path": "hello.py",
                        "expected_hash": "sha256:" + "0" * 64,
                        "content": "print('new')\n",
                    }
                ],
                "notes": [],
            }
        )
        model = FakeModel(response)
        worker = LocalPatchWorker(self.runtime, model)
        with self.assertRaises(PatchValidationError):
            worker.execute(self.task, selected_paths=["hello.py"])

        self.assertEqual(self.source.read_text(encoding="utf-8"), "print('old')\n")
        runs = self.runtime.list_runs(self.task)
        self.assertEqual(runs[-1]["status"], RunStatus.FAILED.value)
        self.assertIsNone(self.runtime.get_task(self.task)["assigned_run_id"])


class RepositorySymlinkTests(unittest.TestCase):
    def test_symlink_alias_to_origin_forge_state_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "secret.txt").write_text("secret", encoding="utf-8")
            alias = root / "normal-looking"
            try:
                alias.symlink_to(state, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            reader = RepositoryReader(root)
            with self.assertRaises(RepositoryAccessError):
                reader.read_text("normal-looking/secret.txt")

    def test_create_precondition_rejects_parent_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            alias = root / "external"
            try:
                alias.symlink_to(Path(outside), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            proposal = parse_patch_proposal(
                json.dumps(
                    {
                        "summary": "escape",
                        "changes": [
                            {
                                "operation": "CREATE",
                                "path": "external/new.py",
                                "expected_hash": None,
                                "content": "x = 1\n",
                            }
                        ],
                        "notes": [],
                    }
                )
            )
            from origin_forge.patches import validate_patch_preconditions

            with self.assertRaises(RepositoryAccessError):
                validate_patch_preconditions(proposal, RepositoryReader(root))


if __name__ == "__main__":
    unittest.main()
