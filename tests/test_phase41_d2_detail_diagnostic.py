from __future__ import annotations

import unittest

from test_production_preparation_planner_resume import PreparationPlannerResumeTests
from origin_forge.production_preparation_planner_resume import (
    PreparationPlannerResumeStatus,
    resume_routed_preparation_planner_once,
)


class Phase41D2DetailDiagnosticTests(unittest.TestCase):
    def test_emit_happy_path_detail(self) -> None:
        case = PreparationPlannerResumeTests("test_routed_resume_commits_marker_then_calls_planner_once")
        case.setUp()
        try:
            result = resume_routed_preparation_planner_once(
                case.runtime,
                case.routed.preparation_id,
                case.routed.revision,
            )
            if result.status is not PreparationPlannerResumeStatus.PLANNER_RETURNED:
                detail = result.detail or "<no detail>"
                print(f"::error title=Phase41D2 happy-path detail::{result.status.value}: {detail}")
                self.fail(f"{result.status.value}: {detail}")
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
