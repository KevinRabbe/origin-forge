from __future__ import annotations

import unittest

from test_production_preparation_planner_resume import PreparationPlannerResumeTests


class Phase41D2DiagnosticTests(unittest.TestCase):
    def test_report_exact_d2_failures_to_github_annotations(self) -> None:
        failures: list[str] = []
        for name in (
            "test_routed_resume_commits_marker_then_calls_planner_once",
            "test_ordinary_failure_after_marker_never_replays",
            "test_concurrent_routed_resume_has_at_most_one_model_call",
            "test_source_orders_durable_marker_before_only_planner_call",
        ):
            result = unittest.TestResult()
            PreparationPlannerResumeTests(name).run(result)
            for _, traceback in result.errors + result.failures:
                compact = " | ".join(line.strip() for line in traceback.splitlines() if line.strip())
                print(f"::error title=Phase41D2 {name}::{compact}")
                failures.append(f"{name}: {compact}")
        self.assertEqual(failures, [], "D2 diagnostic found failures")


if __name__ == "__main__":
    unittest.main()
