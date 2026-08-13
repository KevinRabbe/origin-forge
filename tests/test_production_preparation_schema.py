from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.service import OriginForgeStore


PROJECT = "PROJECT-00000000-0000-4000-8000-000000000001"
GOAL = "GOAL-00000000-0000-4000-8000-000000000002"
FLOW = "FLOW-00000000-0000-4000-8000-000000000003"
TASK = "TASK-00000000-0000-4000-8000-000000000004"
PLINPUT = "PLINPUT-00000000-0000-4000-8000-000000000005"
PLPROP = "PLPROP-00000000-0000-4000-8000-000000000006"
PLAUD = "PLAUD-00000000-0000-4000-8000-000000000007"
PLMAT = "PLMAT-00000000-0000-4000-8000-000000000008"
PREPPOL = "PREPPOL-00000000-0000-4000-8000-000000000009"
PREP1 = "PREP-00000000-0000-4000-8000-000000000010"
PREP2 = "PREP-00000000-0000-4000-8000-000000000011"
NOW = "2026-08-12T21:30:00Z"


class PreparationSchemaTests(unittest.TestCase):
    def _store(self, temp: str) -> OriginForgeStore:
        store = OriginForgeStore(Path(temp) / "project.db")
        with store.session() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, root_path, created_at, updated_at) VALUES (?, 'p', ?, ?, ?)",
                (PROJECT, str(Path(temp).resolve()), NOW, NOW),
            )
            conn.execute(
                "INSERT INTO goals(id, project_id, objective, status, created_at, updated_at) VALUES (?, ?, 'goal', 'OPEN', ?, ?)",
                (GOAL, PROJECT, NOW, NOW),
            )
            conn.execute(
                "INSERT INTO flows(id, goal_id, status, revision, created_at, updated_at) VALUES (?, ?, 'QUEUED', 0, ?, ?)",
                (FLOW, GOAL, NOW, NOW),
            )
            conn.execute(
                """INSERT INTO tasks(
                       id, flow_id, objective, status, revision, attempt_count,
                       created_at, updated_at
                   ) VALUES (?, ?, 'task', 'QUEUED', 0, 0, ?, ?)""",
                (TASK, FLOW, NOW, NOW),
            )
            conn.execute(
                """INSERT INTO planning_inputs(
                       planning_input_id, project_id, goal_id, goal_revision,
                       schema_version, content_hash, payload_json, created_at
                   ) VALUES (?, ?, ?, 0, 1, ?, '{}', ?)""",
                (PLINPUT, PROJECT, GOAL, "1" * 64, NOW),
            )
            conn.execute(
                """INSERT INTO plan_proposals(
                       proposal_id, planning_input_id, schema_version,
                       content_hash, payload_json, created_at
                   ) VALUES (?, ?, 1, ?, '{}', ?)""",
                (PLPROP, PLINPUT, "2" * 64, NOW),
            )
            conn.execute(
                """INSERT INTO plan_audits(
                       audit_id, planning_input_id, proposal_id, status,
                       schema_version, content_hash, payload_json, created_at
                   ) VALUES (?, ?, ?, 'PASS', 1, ?, '{}', ?)""",
                (PLAUD, PLINPUT, PLPROP, "3" * 64, NOW),
            )
            conn.execute(
                """INSERT INTO plan_materializations(
                       materialization_id, planning_input_id, proposal_id, audit_id,
                       goal_id, flow_id, schema_version, content_hash, payload_json,
                       created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, '{}', ?)""",
                (PLMAT, PLINPUT, PLPROP, PLAUD, GOAL, FLOW, "4" * 64, NOW),
            )
        return store

    def _insert_claimed(
        self,
        conn: sqlite3.Connection,
        preparation_id: str,
        *,
        status: str = "ACTIVE",
        terminal_reason: str | None = None,
        planner_dependency_plan_hash: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO task_preparations(
                   preparation_id, project_id,
                   preparation_policy_id, preparation_policy_hash,
                   materialization_id, materialization_hash,
                   planning_input_id, planning_input_hash,
                   task_id, queued_task_revision, queued_task_hash,
                   planner_dependency_plan_hash,
                   stage, status, revision, created_at, updated_at, terminal_reason
               ) VALUES (
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?,
                   'CLAIMED', ?, 0, ?, ?, ?
               )""",
            (
                preparation_id,
                PROJECT,
                PREPPOL,
                "5" * 64,
                PLMAT,
                "4" * 64,
                PLINPUT,
                "1" * 64,
                TASK,
                "6" * 64,
                planner_dependency_plan_hash,
                status,
                NOW,
                NOW,
                terminal_reason,
            ),
        )

    def test_database_allows_only_one_active_preparation_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                self._insert_claimed(conn, PREP1)
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(conn, PREP2)

                conn.execute(
                    """UPDATE task_preparations
                       SET status = 'FAILED_PRE_PLANNER', revision = 1,
                           terminal_reason = 'deterministic pre-planner failure'
                       WHERE preparation_id = ?""",
                    (PREP1,),
                )
                self._insert_claimed(conn, PREP2)

                active = conn.execute(
                    "SELECT preparation_id FROM task_preparations WHERE task_id = ? AND status = 'ACTIVE'",
                    (TASK,),
                ).fetchall()
                self.assertEqual([row["preparation_id"] for row in active], [PREP2])

    def test_claimed_stage_rejects_future_planner_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(
                        conn,
                        PREP1,
                        planner_dependency_plan_hash="7" * 64,
                    )

    def test_ready_and_failure_statuses_are_stage_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(temp)
            with store.session() as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_claimed(conn, PREP1, status="READY")

                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """INSERT INTO task_preparations(
                               preparation_id, project_id,
                               preparation_policy_id, preparation_policy_hash,
                               materialization_id, materialization_hash,
                               planning_input_id, planning_input_hash,
                               task_id, queued_task_revision, queued_task_hash,
                               ready_task_revision, ready_task_hash,
                               route_decision_id, route_decision_hash,
                               planner_dependency_plan_hash,
                               stage, status, revision, created_at, updated_at,
                               terminal_reason
                           ) VALUES (
                               ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?,
                               1, ?, ?, ?, ?,
                               'PLANNER_STARTED', 'FAILED_PRE_PLANNER', 3, ?, ?, ?
                           )""",
                        (
                            PREP1,
                            PROJECT,
                            PREPPOL,
                            "5" * 64,
                            PLMAT,
                            "4" * 64,
                            PLINPUT,
                            "1" * 64,
                            TASK,
                            "6" * 64,
                            "7" * 64,
                            "CAPROUTE-00000000-0000-4000-8000-000000000012",
                            "8" * 64,
                            "9" * 64,
                            NOW,
                            NOW,
                            "model boundary already crossed",
                        ),
                    )


if __name__ == "__main__":
    unittest.main()