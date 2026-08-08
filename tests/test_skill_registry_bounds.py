from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.skills import SkillBudgetExceeded, SkillRegistry


class SkillRegistryBoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("skill-registry-bounds")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_skill(self, name: str, *, body: str = "Follow the procedure.") -> None:
        directory = self.runtime.state_dir / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("SKILL.md").write_text(
            f"---\nname: {name}\ndescription: bounded test\n---\n\n{body}\n",
            encoding="utf-8",
        )
        directory.joinpath("skill.toml").write_text(
            'version = "1.0.0"\nkeywords = []\ncapabilities = []\n',
            encoding="utf-8",
        )

    def test_catalog_count_limit_fails_before_loading_unbounded_skills(self) -> None:
        for name in ("skill-a", "skill-b", "skill-c"):
            self._write_skill(name)

        with self.assertRaisesRegex(SkillBudgetExceeded, "catalog exceeds count limit"):
            SkillRegistry(self.runtime, max_catalog_skills=2).catalog()

    def test_skill_file_read_is_bounded_by_limit_plus_one(self) -> None:
        self._write_skill("large-skill", body="x" * 1024)

        with self.assertRaisesRegex(SkillBudgetExceeded, "SKILL.md exceeds limit"):
            SkillRegistry(self.runtime, max_skill_bytes=128).catalog()

    def test_catalog_limit_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_catalog_skills"):
            SkillRegistry(self.runtime, max_catalog_skills=0)


if __name__ == "__main__":
    unittest.main()
