from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.db import SCHEMA_VERSION
from origin_forge.migrations import MIGRATION_001
from origin_forge.service import OriginForgeStore


class MigrationTests(unittest.TestCase):
    def test_version_one_database_upgrades_to_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.db"
            conn = sqlite3.connect(path)
            try:
                conn.executescript(MIGRATION_001)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-01-01T00:00:00Z')"
                )
                conn.commit()
            finally:
                conn.close()

            store = OriginForgeStore(path)
            with store.session() as upgraded:
                version = upgraded.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                goal_columns = {
                    row["name"] for row in upgraded.execute("PRAGMA table_info(goals)")
                }

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 4)
            self.assertIn("revision", goal_columns)
            with store.session() as upgraded:
                workspace_columns = {
                    row["name"] for row in upgraded.execute("PRAGMA table_info(workspaces)")
                }
            self.assertIn("revision", workspace_columns)
            self.assertIn("base_commit", workspace_columns)


if __name__ == "__main__":
    unittest.main()
