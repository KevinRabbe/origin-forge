from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-workspace-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task_snapshot(self):
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "Build the local workspace")
        return task, build_production_interface_snapshot(self.runtime)

    def test_workspace_aggregates_exact_run_token_counters_for_focus_task(self) -> None:
        task, snapshot = self._task_snapshot()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-token-a",
                    "task_id": task,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:model-a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01Z",
                    "input_token_count": 1200,
                    "output_token_count": 300,
                },
                {
                    "id": "RUN-token-b",
                    "task_id": task,
                    "role": "VERIFIER",
                    "model_profile": "local-verifier",
                    "model_hash": "sha256:model-b",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:02Z",
                    "ended_at": "2026-08-21T00:00:03Z",
                    "input_token_count": 800,
                    "output_token_count": 200,
                },
            ),
        )
        page = render_overview(enriched)
        lowered = page.lower()

        self.assertIn('id="workspace"', page)
        self.assertIn('aria-label="Chat workspace"', page)
        self.assertIn('aria-label="Task token telemetry"', page)
        self.assertIn('href="#workspace"', page)
        self.assertIn(f'href="/task/{task}"', page)
        self.assertIn('href="/run/RUN-token-a"', page)
        self.assertIn('href="/run/RUN-token-b"', page)
        self.assertIn("Build the local workspace", page)
        self.assertIn('class="token-total-value">2,500</span>', page)
        self.assertIn('class="token-metric-value">2,000</span>', page)
        self.assertIn('class="token-metric-value">500</span>', page)
        self.assertIn("All Run input/output token counters in this snapshot are reported.", page)
        self.assertIn("Message composer is intentionally locked", page)
        self.assertIn("This is not a persisted chat transcript", page)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)
        self.assertNotIn("<textarea", lowered)

    def test_workspace_never_imputes_unreported_run_tokens(self) -> None:
        task, snapshot = self._task_snapshot()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-token-partial",
                    "task_id": task,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:model",
                    "status": "RUNNING",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": None,
                    "input_token_count": 1024,
                    "output_token_count": None,
                },
            ),
        )
        page = render_overview(enriched)

        self.assertIn("Partial total: one or more Run token counters are unreported.", page)
        self.assertIn("Reported values are never imputed.", page)
        self.assertIn("Output Unreported", page)
        self.assertIn("Total Unreported", page)
        self.assertIn('class="token-total-value">1,024</span>', page)

    def test_workspace_empty_state_remains_read_only(self) -> None:
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_overview(snapshot)
        lowered = page.lower()

        self.assertIn('aria-label="Chat workspace"', page)
        self.assertIn("no Task is visible in this snapshot", page)
        self.assertIn("Message composer is intentionally locked", page)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)


if __name__ == "__main__":
    unittest.main()
