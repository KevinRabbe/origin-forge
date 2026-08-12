from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.db import SCHEMA_VERSION
from origin_forge.migrations import MIGRATION_001, MIGRATIONS
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
            self.assertEqual(SCHEMA_VERSION, 10)
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
                dispatch_execution_columns = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA table_info(dispatch_executions)")
                }
                dispatch_execution_indexes = {
                    row["name"]
                    for row in upgraded.execute("PRAGMA index_list(dispatch_executions)")
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
                "dispatch_executions",
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
            self.assertTrue(
                {
                    "execution_id",
                    "project_id",
                    "claim_id",
                    "task_id",
                    "dispatch_binding_id",
                    "execution_owner_id",
                    "runtime_dependency_plan_hash",
                    "status",
                    "revision",
                    "terminal_detail_hash",
                }.issubset(dispatch_execution_columns)
            )
            self.assertIn(
                "idx_dispatch_executions_task_history",
                dispatch_execution_indexes,
            )
            self.assertIn(
                "idx_dispatch_executions_status",
                dispatch_execution_indexes,
            )
            self.assertIn(
                "idx_dispatch_executions_one_started_per_task",
                dispatch_execution_indexes,
            )

    def test_version_nine_claim_rows_are_preserved_exactly_by_version_ten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                for migration in MIGRATIONS[:-1]:
                    conn.executescript(migration.sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (migration.version, "2026-08-11T00:00:00Z"),
                    )
                project_id = "PROJECT-00000000-0000-4000-8000-000000000001"
                goal_id = "GOAL-00000000-0000-4000-8000-000000000002"
                flow_id = "FLOW-00000000-0000-4000-8000-000000000003"
                task_id = "TASK-00000000-0000-4000-8000-000000000004"
                claim_id = "DISPCLAIM-00000000-0000-4000-8000-000000000005"
                now = "2026-08-11T18:00:00Z"
                conn.execute(
                    "INSERT INTO projects(id, name, root_path, created_at, updated_at) VALUES (?, 'p', ?, ?, ?)",
                    (project_id, str(Path(temp).resolve()), now, now),
                )
                conn.execute(
                    "INSERT INTO goals(id, project_id, objective, status, created_at, updated_at) VALUES (?, ?, 'g', 'OPEN', ?, ?)",
                    (goal_id, project_id, now, now),
                )
                conn.execute(
                    "INSERT INTO flows(id, goal_id, status, revision, created_at, updated_at) VALUES (?, ?, 'QUEUED', 0, ?, ?)",
                    (flow_id, goal_id, now, now),
                )
                conn.execute(
                    """INSERT INTO tasks(
                           id, flow_id, objective, status, revision, attempt_count,
                           created_at, updated_at
                       ) VALUES (?, ?, 't', 'READY', 1, 0, ?, ?)""",
                    (task_id, flow_id, now, now),
                )
                conn.execute(
                    """INSERT INTO dispatch_claims(
                        claim_id, project_id, task_id, task_revision, task_content_hash,
                        work_order_id, work_order_hash,
                        work_order_audit_id, work_order_audit_hash,
                        input_resolution_id, input_resolution_hash,
                        dispatch_binding_id, dispatch_binding_hash,
                        binding_audit_id, binding_audit_hash,
                        selected_adapter_id, selected_adapter_fingerprint,
                        dispatch_contract_id, dispatch_contract_hash,
                        binder_id, binder_fingerprint,
                        status, revision, created_at, updated_at, terminal_reason
                    ) VALUES (
                        ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'ACTIVE', 0, ?, ?, NULL
                    )""",
                    (
                        claim_id,
                        project_id,
                        task_id,
                        "a" * 64,
                        "WORKORD-00000000-0000-4000-8000-000000000006",
                        "b" * 64,
                        "WORKAUD-00000000-0000-4000-8000-000000000007",
                        "c" * 64,
                        "INRES-00000000-0000-4000-8000-000000000008",
                        "d" * 64,
                        "DISPBIND-00000000-0000-4000-8000-000000000009",
                        "e" * 64,
                        "BINDAUD-00000000-0000-4000-8000-000000000010",
                        "f" * 64,
                        "originforge.code.bounded-retry",
                        "1" * 64,
                        "code.bounded-retry@1",
                        "2" * 64,
                        "binder.code.bounded-retry@1",
                        "3" * 64,
                        now,
                        now,
                    ),
                )
                conn.commit()
                before = dict(
                    conn.execute(
                        "SELECT * FROM dispatch_claims WHERE claim_id = ?",
                        (claim_id,),
                    ).fetchone()
                )
            finally:
                conn.close()

            store = OriginForgeStore(path)
            with store.session() as upgraded:
                version = upgraded.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                after = dict(
                    upgraded.execute(
                        "SELECT * FROM dispatch_claims WHERE claim_id = ?",
                        (claim_id,),
                    ).fetchone()
                )
                upgraded.execute(
                    """UPDATE dispatch_claims
                       SET status = 'CONSUMED', revision = 1,
                           terminal_reason = 'execution authority consumed'
                       WHERE claim_id = ?""",
                    (claim_id,),
                )
                consumed = upgraded.execute(
                    "SELECT status, revision, terminal_reason FROM dispatch_claims WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()

            self.assertEqual(version, 10)
            self.assertEqual(after, before)
            self.assertEqual(consumed["status"], "CONSUMED")
            self.assertEqual(consumed["revision"], 1)
            self.assertEqual(
                consumed["terminal_reason"],
                "execution authority consumed",
            )


if __name__ == "__main__":
    unittest.main()
