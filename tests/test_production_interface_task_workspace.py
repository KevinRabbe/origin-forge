from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_detail
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceTaskWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-task-workspace-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_task_detail_uses_exact_selected_task_for_chat_and_tokens(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        first_task = self.runtime.create_task(flow, "First exact task")
        second_task = self.runtime.create_task(flow, "Second newer task")
        snapshot = build_production_interface_snapshot(self.runtime)
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-first",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:first",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01Z",
                    "input_token_count": 900,
                    "output_token_count": 100,
                },
                {
                    "id": "RUN-second",
                    "task_id": second_task,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:second",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:02Z",
                    "ended_at": "2026-08-21T00:00:03Z",
                    "input_token_count": 7000,
                    "output_token_count": 3000,
                },
            ),
        )

        page = render_detail(enriched, "task", first_task)
        lowered = page.lower()

        self.assertIn('id="task-workspace"', page)
        self.assertIn('aria-label="Selected task workspace"', page)
        self.assertIn('aria-label="Selected task token telemetry"', page)
        self.assertIn("First exact task", page)
        self.assertIn("RUN-first", page)
        self.assertNotIn("RUN-second", page)
        self.assertIn('class="token-total-value">1,000</span>', page)
        self.assertIn('class="token-metric-value">900</span>', page)
        self.assertIn('class="token-metric-value">100</span>', page)
        self.assertIn("Exact Task detail selection.", page)
        self.assertIn("no overview focus heuristic is used here", page)
        self.assertIn("Message composer is intentionally locked", page)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)
        self.assertNotIn("<textarea", lowered)

    def test_non_task_detail_does_not_gain_task_workspace(self) -> None:
        goal = self.runtime.create_goal("goal")
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_detail(snapshot, "goal", goal)

        self.assertNotIn('id="task-workspace"', page)
        self.assertNotIn('aria-label="Selected task token telemetry"', page)


if __name__ == "__main__":
    unittest.main()
