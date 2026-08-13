from __future__ import annotations

import traceback
import unittest
from unittest.mock import patch

import test_production_preparation_planner_resume as d2_tests
from test_production_preparation_planner_resume import PreparationPlannerResumeTests


class Phase41D2DiagnosticTests(unittest.TestCase):
    def test_report_exact_d2_failures_to_github_annotations(self) -> None:
        failures: list[str] = []
        escaped: list[str] = []
        real_resume = d2_tests.resume_routed_preparation_planner_once

        def traced_resume(*args, **kwargs):
            try:
                return real_resume(*args, **kwargs)
            except BaseException:
                compact = " | ".join(
                    line.strip()
                    for line in traceback.format_exc().splitlines()
                    if line.strip()
                )
                escaped.append(compact)
                raise

        for name in (
            "test_routed_resume_commits_marker_then_calls_planner_once",
            "test_ordinary_failure_after_marker_never_replays",
            "test_concurrent_routed_resume_has_at_most_one_model_call",
            "test_source_orders_durable_marker_before_only_planner_call",
        ):
            result = unittest.TestResult()
            with patch.object(
                d2_tests,
                "resume_routed_preparation_planner_once",
                side_effect=traced_resume,
            ):
                PreparationPlannerResumeTests(name).run(result)
            for _, tb in result.errors + result.failures:
                compact = " | ".join(
                    line.strip() for line in tb.splitlines() if line.strip()
                )
                print(f"::error title=Phase41D2 {name}::{compact}")
                failures.append(f"{name}: {compact}")
        for index, compact in enumerate(escaped, start=1):
            print(f"::error title=Phase41D2 escaped worker {index}::{compact}")
        self.assertEqual(failures, [], "D2 diagnostic found failures")


if __name__ == "__main__":
    unittest.main()
