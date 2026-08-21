from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceTaskSwitcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-task-switcher-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _snapshot_with_tasks(self):
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        first_task = self.runtime.create_task(flow, "Most recent work")
        second_task = self.runtime.create_task(flow, "Older work")
        snapshot = build_production_interface_snapshot(self.runtime)
        tasks = tuple(
            {
                **row,
                "updated_at": (
                    "2026-08-21T10:00:00Z"
                    if row["id"] == first_task
                    else "2026-08-21T09:00:00Z"
                ),
            }
            for row in snapshot.tasks
        )
        return replace(snapshot, tasks=tasks), first_task, second_task

    def test_recent_task_rail_uses_durable_task_order_and_visible_token_usage(self) -> None:
        snapshot, first_task, second_task = self._snapshot_with_tasks()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-recent-a",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-a",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T10:00:00Z",
                    "ended_at": "2026-08-21T10:00:01Z",
                    "input_token_count": 100,
                    "output_token_count": 50,
                },
                {
                    "id": "RUN-recent-b",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-a",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T10:00:02Z",
                    "ended_at": "2026-08-21T10:00:03Z",
                    "input_token_count": 200,
                    "output_token_count": None,
                },
                {
                    "id": "RUN-older",
                    "task_id": second_task,
                    "role": "VERIFIER",
                    "model_profile": "local-b",
                    "model_hash": "sha256:b",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T09:00:00Z",
                    "ended_at": "2026-08-21T09:00:01Z",
                    "input_token_count": 10,
                    "output_token_count": 40,
                },
            ),
            total_counts={**snapshot.total_counts, "runs": 3},
            truncated={**snapshot.truncated, "runs": False},
        )

        page = render_overview(enriched)
        rail = page.split('<aside class="task-switcher"', 1)[1].split("</aside>", 1)[0]
        lowered = page.lower()

        self.assertIn('aria-label="Recent Tasks"', page)
        self.assertIn('aria-label="Task workspace links"', rail)
        self.assertIn("Tasks are work records, not persisted conversations", rail)
        self.assertLess(rail.index(first_task), rail.index(second_task))
        self.assertIn(f'href="/task/{first_task}"', rail)
        self.assertIn(f'href="/task/{second_task}"', rail)
        self.assertEqual(rail.count('<span class="task-switcher-focus">Focus</span>'), 1)
        first_item = rail.split(f'href="/task/{first_task}"', 1)[1].split("</a>", 1)[0]
        second_item = rail.split(f'href="/task/{second_task}"', 1)[1].split("</a>", 1)[0]
        self.assertIn("Most recent work", first_item)
        self.assertIn("350 tokens", first_item)
        self.assertIn("2 Run(s)", first_item)
        self.assertIn("partial counters", first_item)
        self.assertIn("Older work", second_item)
        self.assertIn("50 tokens", second_item)
        self.assertIn("1 Run(s)", second_item)
        self.assertIn("complete counters", second_item)
        self.assertIn("All 2 project Task records are visible", rail)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)
        self.assertNotIn("<textarea", lowered)

    def test_truncated_task_projection_is_not_presented_as_complete_history(self) -> None:
        snapshot, _, _ = self._snapshot_with_tasks()
        enriched = replace(
            snapshot,
            total_counts={**snapshot.total_counts, "tasks": 7},
            truncated={**snapshot.truncated, "tasks": True},
        )

        page = render_overview(enriched)
        rail = page.split('<aside class="task-switcher"', 1)[1].split("</aside>", 1)[0]

        self.assertIn("Bounded Task view: 2 of 7 Task records are visible", rail)
        self.assertIn("This rail is not complete project history", rail)


if __name__ == "__main__":
    unittest.main()
