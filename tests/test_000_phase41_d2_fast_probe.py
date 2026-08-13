from __future__ import annotations

import sys

from test_production_preparation_planner_resume import PreparationPlannerResumeTests
from origin_forge.production_preparation_planner_resume import (
    PreparationPlannerResumeStatus,
    resume_routed_preparation_planner_once,
)

case = PreparationPlannerResumeTests("test_routed_resume_commits_marker_then_calls_planner_once")
case.setUp()
try:
    result = resume_routed_preparation_planner_once(
        case.runtime,
        case.routed.preparation_id,
        case.routed.revision,
    )
    detail = result.detail or "<no detail>"
    print(
        f"::error title=Phase41D2 fast detail::{result.status.value}: {detail}",
        flush=True,
    )
finally:
    case.tearDown()
raise SystemExit(97)
