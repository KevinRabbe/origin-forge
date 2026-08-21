from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceProjectTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-project-token-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _snapshot_with_tasks(self):
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        first_task = self.runtime.create_task(flow, "High token task")
        second_task = self.runtime.create_task(flow, "Lower token task")
        return build_production_interface_snapshot(self.runtime), first_task, second_task

    def test_overview_aggregates_reported_tokens_without_imputing_missing_counters(self) -> None:
        snapshot, first_task, second_task = self._snapshot_with_tasks()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-token-a",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-a",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01Z",
                    "input_token_count": 100,
                    "output_token_count": 50,
                },
                {
                    "id": "RUN-token-b",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-a",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:02Z",
                    "ended_at": "2026-08-21T00:00:03Z",
                    "input_token_count": 200,
                    "output_token_count": None,
                },
                {
                    "id": "RUN-token-c",
                    "task_id": second_task,
                    "role": "VERIFIER",
                    "model_profile": "local-b",
                    "model_hash": "sha256:b",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:04Z",
                    "ended_at": "2026-08-21T00:00:05Z",
                    "input_token_count": 10,
                    "output_token_count": 40,
                },
            ),
            total_counts={**snapshot.total_counts, "runs": 3},
            truncated={**snapshot.truncated, "runs": False},
        )

        page = render_overview(enriched)
        section = page.split('<section id="project-tokens"', 1)[1].split(
            '<section class="lifecycle-panel"', 1
        )[0]
        lowered = page.lower()

        self.assertIn('aria-label="Project token telemetry"', page)
        self.assertIn('<a href="#project-tokens">Tokens</a>', page)
        self.assertIn(
            '<div class="project-token-metric project-token-total"><strong>400</strong><span>Reported tokens</span>',
            section,
        )
        self.assertIn('<strong>310</strong><span>Input tokens</span>', section)
        self.assertIn('<strong>90</strong><span>Output tokens</span>', section)
        self.assertIn('<strong>3</strong><span>Visible Runs</span>', section)
        self.assertIn('<strong>2/3</strong><span>Fully reported Runs</span>', section)
        self.assertIn('<strong>1</strong><span>Missing counters</span>', section)
        self.assertIn("all 3 project Runs are visible", section)
        self.assertIn("1 input/output token counter(s) are unreported", section)
        self.assertIn("missing values are never imputed", section)
        self.assertLess(section.index(first_task), section.index(second_task))
        self.assertIn("local-a", section)
        self.assertIn("350 tokens", section)
        self.assertIn("local-b", section)
        self.assertIn("50 tokens", section)
        self.assertIn("No currency conversion or latency estimate is inferred", section)
        self.assertNotIn("€", section)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)
        self.assertNotIn("<textarea", lowered)

    def test_truncated_runs_are_never_presented_as_project_wide_token_total(self) -> None:
        snapshot, first_task, _ = self._snapshot_with_tasks()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-visible",
                    "task_id": first_task,
                    "role": "PRODUCER",
                    "model_profile": "local-a",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01Z",
                    "input_token_count": 100,
                    "output_token_count": 50,
                },
            ),
            total_counts={**snapshot.total_counts, "runs": 5},
            truncated={**snapshot.truncated, "runs": True},
        )

        page = render_overview(enriched)
        section = page.split('<section id="project-tokens"', 1)[1].split(
            '<section class="lifecycle-panel"', 1
        )[0]

        self.assertIn("Visible Runs only", section)
        self.assertIn("1 of 5 project Runs are visible", section)
        self.assertIn("Reported token totals below are not project-wide", section)
        self.assertIn(
            '<div class="project-token-metric project-token-total"><strong>150</strong><span>Reported tokens</span>',
            section,
        )


if __name__ == "__main__":
    unittest.main()
