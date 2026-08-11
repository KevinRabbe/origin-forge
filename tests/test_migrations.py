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
            self.assertEqual(SCHEMA_VERSION, 8)
            self.assertIn("revision", goal_columns)
            with store.session() as upgraded:
                workspace_columns = {
                    row["name"] for row in upgraded.execute("PRAGMA table_info(workspaces)")
                }
                tables = {
                    row["name"]
                    for row in upgraded.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                relation_indexes = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA index_list(entity_relations)")
                }
                dependency_indexes = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA index_list(task_dependencies)")
                }
                dependency_triggers = {
                    row["name"]
                    for row in upgraded.execute(
                        """SELECT name FROM sqlite_master
                           WHERE type = 'trigger' AND tbl_name = 'task_dependencies'"""
                    )
                }
                planning_indexes = {
                    row["name"]
                    for table in (
                        "planning_inputs",
                        "plan_proposals",
                        "plan_audits",
                        "plan_materializations",
                    )
                    for row in upgraded.execute(f"PRAGMA index_list({table})")
                }
                dispatch_claim_columns = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA table_info(dispatch_claims)")
                }
                dispatch_claim_indexes = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA index_list(dispatch_claims)")
                }
            self.assertIn("revision", workspace_columns)
            self.assertIn("base_commit", workspace_columns)
            for table in (
                "entities",
                "entity_relations",
                "entity_bindings",
                "design_rules",
                "task_dependencies",
                "planning_inputs",
                "plan_proposals",
                "plan_audits",
                "plan_materializations",
                "dispatch_claims",
            ):
                self.assertIn(table, tables)
            self.assertIn("idx_entity_relations_active_unique", relation_indexes)
            self.assertIn("idx_task_dependencies_required", dependency_indexes)
            self.assertEqual(
                dependency_triggers,
                {
                    "task_dependencies_same_flow_insert",
                    "task_dependencies_no_cycle_insert",
                },
            )
            for index in (
                "idx_planning_inputs_goal",
                "idx_plan_proposals_input",
                "idx_plan_audits_proposal",
                "idx_plan_materializations_goal",
            ):
                self.assertIn(index, planning_indexes)
            self.assertTrue(
                {
                    "claim_id",
                    "project_id",
                    "task_id",
                    "task_revision",
                    "task_content_hash",
                    "dispatch_binding_id",
                    "binding_audit_id",
                    "status",
                    "revision",
                    "terminal_reason",
                }.issubset(dispatch_claim_columns)
            )
            self.assertIn("idx_dispatch_claims_task_history", dispatch_claim_indexes)
            self.assertIn("idx_dispatch_claims_binding", dispatch_claim_indexes)
            self.assertIn("idx_dispatch_claims_one_active_per_task", dispatch_claim_indexes)


if __name__ == "__main__":
    unittest.main()
