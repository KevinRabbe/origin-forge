from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skills import SkillRegistry


class CountingSkillRegistry(SkillRegistry):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loads = 0

    def _load_from_dir(self, directory: Path):
        self.loads += 1
        return super()._load_from_dir(directory)


class SkillRegistryLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skill-loading-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_skill(self, name: str, capability: str) -> None:
        directory = self.runtime.state_dir / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Procedure for {capability}\n---\n\nFollow {capability} procedure.\n",
            encoding="utf-8",
        )
        directory.joinpath("skill.toml").write_text(
            "version = \"1.0.0\"\n"
            f"keywords = [{json.dumps(capability)}]\n"
            f"capabilities = [{json.dumps(capability)}]\n",
            encoding="utf-8",
        )

    def test_selection_loads_each_catalog_skill_once(self) -> None:
        self._write_skill("python-debug", "debug")
        self._write_skill("write-docs", "documentation")

        goal = self.runtime.create_goal("test skill selection")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(
            flow,
            "Fix parser failure",
            required_capabilities=["debug"],
        )

        registry = CountingSkillRegistry(self.runtime)
        selection = registry.select(task)

        self.assertEqual(registry.loads, 2)
        self.assertEqual(
            [skill.metadata.name for skill in selection.skills],
            ["python-debug"],
        )


if __name__ == "__main__":
    unittest.main()
