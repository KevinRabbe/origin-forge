from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_detail, render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceRunTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-run-timing-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _two_tasks(self):
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        first = self.runtime.create_task(flow, "First timed task")
        second = self.runtime.create_task(flow, "Second timed task")
        return first, second, build_production_interface_snapshot(self.runtime)

    def test_overview_shows_recorded_elapsed_time_without_throughput_claim(self) -> None:
        first, second, snapshot = self._two_tasks()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-timed-complete",
                    "task_id": first,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:a",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01.250000Z",
                    "input_token_count": 1200,
                    "output_token_count": 300,
                },
                {
                    "id": "RUN-timed-open",
                    "task_id": second,
                    "role": "PRODUCER",
                    "model_profile": "local-secondary",
                    "model_hash": "sha256:b",
                    "status": "RUNNING",
                    "started_at": "2026-08-21T00:00:02Z",
                    "ended_at": None,
                    "input_token_count": 400,
                    "output_token_count": None,
                },
            ),
        )

        page = render_overview(enriched)
        lowered = page.lower()

        self.assertIn('id="run-timing"', page)
        self.assertIn('aria-label="Run timing telemetry"', page)
        self.assertIn('href="#run-timing"', page)
        self.assertIn("RUN-timed-complete", page)
        self.assertIn("RUN-timed-open", page)
        self.assertIn("1.25 s", page)
        self.assertIn("Open — no end timestamp", page)
        self.assertIn("1,500", page)
        self.assertIn("400 known · partial", page)
        self.assertIn("not wall-clock time", page)
        self.assertIn("No generation throughput is inferred", page)
        self.assertNotIn("tokens/s", lowered)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)

    def test_overview_marks_bounded_and_invalid_timing_conservatively(self) -> None:
        first, _, snapshot = self._two_tasks()
        truncated = dict(snapshot.truncated)
        truncated["runs"] = True
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-inverted",
                    "task_id": first,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:a",
                    "status": "FAILED",
                    "started_at": "2026-08-21T00:00:05Z",
                    "ended_at": "2026-08-21T00:00:04Z",
                    "input_token_count": 10,
                    "output_token_count": 5,
                },
                {
                    "id": "RUN-malformed",
                    "task_id": first,
                    "role": "VERIFIER",
                    "model_profile": "local-verifier",
                    "model_hash": "sha256:b",
                    "status": "FAILED",
                    "started_at": "not-a-time",
                    "ended_at": "also-not-a-time",
                    "input_token_count": 20,
                    "output_token_count": 10,
                },
            ),
            truncated=truncated,
        )

        page = render_overview(enriched)

        self.assertIn("Visible Runs only", page)
        self.assertIn("timing totals are visible-snapshot-only and not project-wide", page)
        self.assertIn('class="run-timing-metric"><strong>2</strong><span>Unreported durations</span>', page)
        self.assertIn("Unreported", page)
        self.assertNotIn("-1.00 s", page)

    def test_task_detail_timing_is_scoped_to_exact_selected_task(self) -> None:
        first, second, snapshot = self._two_tasks()
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": "RUN-first-time",
                    "task_id": first,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:first",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:02Z",
                    "input_token_count": 100,
                    "output_token_count": 50,
                },
                {
                    "id": "RUN-second-time",
                    "task_id": second,
                    "role": "PRODUCER",
                    "model_profile": "local-primary",
                    "model_hash": "sha256:second",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:10Z",
                    "input_token_count": 1000,
                    "output_token_count": 500,
                },
            ),
        )

        page = render_detail(enriched, "task", first)

        self.assertIn("Task Run timing", page)
        self.assertIn("Exact Task Runs", page)
        self.assertIn("RUN-first-time", page)
        self.assertNotIn("RUN-second-time", page)
        self.assertIn("2.00 s", page)
        self.assertNotIn("10.00 s", page)
        self.assertIn("150", page)


if __name__ == "__main__":
    unittest.main()
