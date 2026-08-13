from __future__ import annotations

import unittest

from test_production_preparation_planner_boundary import PreparationPlannerBoundaryTests


class Phase41D1DiagnosticTests(unittest.TestCase):
    def test_report_exact_d1_failures_to_github_annotations(self) -> None:
        failures: list[str] = []
        for name in (
            "test_exact_routed_boundary_reconstructs_without_mutation_or_model_call",
            "test_stale_expected_revision_fails_without_crossing_planner_boundary",
            "test_task_drift_invalidates_routed_boundary",
            "test_route_hash_drift_invalidates_routed_boundary",
            "test_source_contains_no_planner_checkpoint_or_execution_authority",
        ):
            result = unittest.TestResult()
            PreparationPlannerBoundaryTests(name).run(result)
            for _, traceback in result.errors + result.failures:
                compact = " | ".join(line.strip() for line in traceback.splitlines() if line.strip())
                print(f"::error title=Phase41D1 {name}::{compact}")
                failures.append(f"{name}: {compact}")
        self.assertEqual(failures, [], "D1 diagnostic found failures")


if __name__ == "__main__":
    unittest.main()
