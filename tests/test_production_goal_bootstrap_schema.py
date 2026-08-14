from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.service import OriginForgeStore


PROJECT = "PROJECT-00000000-0000-4000-8000-000000000001"
GOAL = "GOAL-00000000-0000-4000-8000-000000000002"
BOOT1 = "GOALBOOT-00000000-0000-4000-8000-000000000003"
BOOT2 = "GOALBOOT-00000000-0000-4000-8000-000000000004"
NOW = "2026-08-14T18:15:00Z"


class GoalBootstrapSchemaTests(unittest.TestCase):
    def _store(self, temp: str) -> OriginForgeStore:
        store = OriginForgeStore(Path(temp) / "project.db")
        with store.session() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, root_path, created_at, updated_at) VALUES (?, 'p', ?, ?, ?)",
                (PROJECT, str(Path(temp).resolve()), NOW, NOW),
            )
            conn.execute(
                """INSERT INTO goals(
                       id, project_id, objective, status, revision,
                       created_at, updated_at
                   ) VALUES (?, ?, 'goal', 'OPEN', 0, ?, ?)""",
                (GOAL, PROJECT, NOW, NOW),
            )
        return store

    def _insert_claimed(
        self,
        conn: sqlite3.Connection,
        bootstrap_id: str,
        *,
        status: str = "ACTIVE",
        terminal_reason: str | None = None,
        planning_input_id: str | None = None,
        planning_input_hash: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO goal_bootstraps(
                   bootstrap_id, project_id, goal_id, goal_revision,
                   goal_content_hash, bootstrap_owner_id,
                   bootstrap_owner_fingerprint, bootstrap_contract_version,
                   planning_input_id, planning_input_hash,
                   stage, status, revision, created_at, updated_at, terminal_reason
               ) VALUES (
                   ?, ?, ?, 0, ?, ?, ?, '1', ?, ?,
                   'CLAIMED', ?, 0, ?, ?, ?
               )""",
            (
                bootstrap_id,
                PROJECT,
                GOAL,
                "1" * 64,
                "originforge.bootstrap.goal-planner@1",
                "2" * 64,
                planning_input_id,
                planning_input_hash,
                status,
                NOW,
                NOW,
                terminal_reason,
            ),
        )

    def test_database_allows_only_one_current_bootstrap_per_exact_goal_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                self._insert_claimed(conn, BOOT1)
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(conn, BOOT2)

                conn.execute(
                    """UPDATE goal_bootstraps
                       SET status = 'INTERRUPTED', revision = 1,
                           terminal_reason = 'operator-reviewed interruption'
                       WHERE bootstrap_id = ?""",
                    (BOOT1,),
                )
                self._insert_claimed(conn, BOOT2)
                current = conn.execute(
                    """SELECT bootstrap_id FROM goal_bootstraps
                       WHERE goal_id = ? AND goal_revision = 0
                         AND status IN ('ACTIVE', 'READY')""",
                    (GOAL,),
                ).fetchall()
                self.assertEqual(
                    [row["bootstrap_id"] for row in current],
                    [BOOT2],
                )

    def test_claimed_stage_rejects_future_planning_input_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(
                        conn,
                        BOOT1,
                        planning_input_id="PLINPUT-00000000-0000-4000-8000-000000000005",
                        planning_input_hash="3" * 64,
                    )

    def test_active_and_terminal_reason_shapes_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(
                        conn,
                        BOOT1,
                        status="ACTIVE",
                        terminal_reason="not terminal",
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(
                        conn,
                        BOOT1,
                        status="INTERRUPTED",
                        terminal_reason=None,
                    )

    def test_failed_pre_planner_cannot_be_stored_after_model_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """INSERT INTO goal_bootstraps(
                               bootstrap_id, project_id, goal_id, goal_revision,
                               goal_content_hash, bootstrap_owner_id,
                               bootstrap_owner_fingerprint, bootstrap_contract_version,
                               capability_catalog_id, capability_catalog_hash,
                               capability_routing_policy_id, capability_routing_policy_hash,
                               dispatch_contract_catalog_id, dispatch_contract_catalog_hash,
                               planning_input_id, planning_input_hash,
                               planner_dependency_plan_hash,
                               stage, status, revision, created_at, updated_at,
                               terminal_reason
                           ) VALUES (
                               ?, ?, ?, 0, ?, ?, ?, '1',
                               ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               'PLANNER_STARTED', 'FAILED_PRE_PLANNER', 3, ?, ?, ?
                           )""",
                        (
                            BOOT1,
                            PROJECT,
                            GOAL,
                            "1" * 64,
                            "originforge.bootstrap.goal-planner@1",
                            "2" * 64,
                            "CAPCAT-00000000-0000-4000-8000-000000000005",
                            "3" * 64,
                            "CAPPOL-00000000-0000-4000-8000-000000000006",
                            "4" * 64,
                            "DISPCAT-00000000-0000-4000-8000-000000000007",
                            "5" * 64,
                            "PLINPUT-00000000-0000-4000-8000-000000000008",
                            "6" * 64,
                            "7" * 64,
                            NOW,
                            NOW,
                            "model boundary already crossed",
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
