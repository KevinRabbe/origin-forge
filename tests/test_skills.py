from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skills import SkillBudgetExceeded, SkillFormatError, SkillRegistry
from origin_forge.state import TaskStatus
from origin_forge.worker import LocalPatchWorker


class FakeModel:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return "fake-skill-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.response_text, self.model_id)


class GovernedSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skills-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_skill(
        self,
        name: str,
        *,
        description: str,
        instructions: str,
        version: str = "1.0.0",
        keywords: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
    ) -> Path:
        directory = self.runtime.state_dir / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n{instructions}\n",
            encoding="utf-8",
        )
        keyword_text = ", ".join(json.dumps(item) for item in keywords)
        capability_text = ", ".join(json.dumps(item) for item in capabilities)
        directory.joinpath("skill.toml").write_text(
            f'version = "{version}"\nkeywords = [{keyword_text}]\ncapabilities = [{capability_text}]\n',
            encoding="utf-8",
        )
        return directory

    def _task(
        self,
        objective: str,
        *,
        capabilities: tuple[str, ...] = (),
    ) -> str:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        return self.runtime.create_task(
            flow,
            objective,
            required_capabilities=capabilities,
        )

    def test_catalog_is_deterministic_and_fingerprinted(self) -> None:
        self._write_skill(
            "python-debug",
            description="Diagnose Python failures",
            instructions="Inspect the failing path before proposing a minimal repair.",
            keywords=("debug", "python"),
            capabilities=("debug",),
        )
        registry = SkillRegistry(self.runtime)
        first = registry.catalog()
        second = registry.catalog()
        self.assertEqual(first, second)
        self.assertEqual(first[0].name, "python-debug")
        self.assertTrue(first[0].content_hash.startswith("sha256:"))
        self.assertTrue(first[0].ref.startswith("python-debug@1.0.0#"))

    def test_selection_prefers_matching_capability_and_has_no_fallback(self) -> None:
        self._write_skill(
            "python-debug",
            description="Diagnose Python failures",
            instructions="Debug carefully.",
            keywords=("bug", "failure"),
            capabilities=("debug",),
        )
        self._write_skill(
            "write-docs",
            description="Write project documentation",
            instructions="Document public behavior.",
            keywords=("documentation",),
            capabilities=("documentation",),
        )
        registry = SkillRegistry(self.runtime)
        debug_task = self._task("Fix the failing parser", capabilities=("debug",))
        selected = registry.select(debug_task)
        self.assertEqual([skill.metadata.name for skill in selected.skills], ["python-debug"])

        unrelated = self._task("Rotate spaceship thrusters")
        self.assertEqual(registry.select(unrelated).skills, ())

    def test_explicit_selection_is_bounded(self) -> None:
        for name in ("skill-a", "skill-b", "skill-c"):
            self._write_skill(
                name,
                description=f"Description for {name}",
                instructions=f"Instructions for {name}.",
            )
        task = self._task("anything")
        registry = SkillRegistry(self.runtime, max_selected_skills=2)
        with self.assertRaises(SkillBudgetExceeded):
            registry.select(task, names=("skill-a", "skill-b", "skill-c"))

    def test_instruction_only_registry_rejects_extra_content(self) -> None:
        directory = self._write_skill(
            "safe-review",
            description="Review changes",
            instructions="Review evidence only.",
        )
        directory.joinpath("run.py").write_text("print('no')\n", encoding="utf-8")
        with self.assertRaises(SkillFormatError):
            SkillRegistry(self.runtime).catalog()

    def test_skill_registry_root_symlink_is_rejected(self) -> None:
        target = self.root / "external-skill-root"
        target.mkdir()
        registry_root = self.runtime.state_dir / "skills"
        try:
            registry_root.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(SkillFormatError, "root may not be a symlink"):
            SkillRegistry(self.runtime).catalog()

    def test_skill_directory_symlink_is_rejected(self) -> None:
        target = self.root / "real-skill"
        target.mkdir()
        target.joinpath("SKILL.md").write_text(
            "---\nname: linked\ndescription: linked skill\n---\nbody\n",
            encoding="utf-8",
        )
        target.joinpath("skill.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
        registry_root = self.runtime.state_dir / "skills"
        registry_root.mkdir(parents=True, exist_ok=True)
        try:
            registry_root.joinpath("linked").symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(SkillFormatError):
            SkillRegistry(self.runtime).catalog()

    def test_worker_captures_selected_skill_without_new_authority(self) -> None:
        self._write_skill(
            "python-debug",
            description="Diagnose Python failures",
            instructions="Prefer the smallest evidence-backed code change.",
            keywords=("debug", "fix"),
            capabilities=("debug",),
        )
        source = self.root / "hello.py"
        source.write_text("print('old')\n", encoding="utf-8")
        task = self._task("Fix hello.py", capabilities=("debug",))
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

        expected = RepositoryReader(self.root).hash_file("hello.py")
        response = json.dumps(
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
        model = FakeModel(response)
        result = LocalPatchWorker(self.runtime, model).execute(
            task,
            selected_paths=["hello.py"],
        )

        self.assertEqual(source.read_text(encoding="utf-8"), "print('old')\n")
        self.assertEqual(len(result.skill_refs), 1)
        self.assertIsNotNone(result.skill_bundle_artifact_id)
        self.assertIn("Prefer the smallest evidence-backed code change.", model.requests[0].instructions)
        self.assertEqual(
            model.requests[0].context["selected_skills"][0]["name"],
            "python-debug",
        )

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(json.loads(run["skills_json"]), list(result.skill_refs))
        with self.runtime.store.session() as conn:
            artifacts = conn.execute(
                """SELECT id, type, parent_artifact_id, skill_versions_json
                   FROM artifacts WHERE created_by_run_id = ?
                   ORDER BY created_at, rowid""",
                (result.run_id,),
            ).fetchall()
        self.assertEqual(
            [row["type"] for row in artifacts],
            ["CONTEXT_PACKAGE", "SKILL_BUNDLE", "MODEL_RESPONSE", "PATCH_PROPOSAL"],
        )
        self.assertEqual(artifacts[1]["parent_artifact_id"], artifacts[0]["id"])
        self.assertEqual(artifacts[2]["parent_artifact_id"], artifacts[1]["id"])
        self.assertEqual(artifacts[3]["parent_artifact_id"], artifacts[2]["id"])
        self.assertEqual(json.loads(artifacts[3]["skill_versions_json"]), list(result.skill_refs))


if __name__ == "__main__":
    unittest.main()
