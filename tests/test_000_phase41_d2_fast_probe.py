from __future__ import annotations

import os

from test_production_preparation_planner_resume import PreparationPlannerResumeTests
from origin_forge.production_preparation_planner_boundary import resolve_routed_preparation_planner_boundary

case = PreparationPlannerResumeTests("test_routed_resume_commits_marker_then_calls_planner_once")
case.setUp()
try:
    boundary = resolve_routed_preparation_planner_boundary(
        case.runtime,
        case.routed.preparation_id,
        case.routed.revision,
    )
    snapshot = boundary.receipt
    policy = boundary.policy
    plan = boundary.dependencies.plan
    checks = {
        "snapshot_policy_id": snapshot.preparation_policy_id == policy.preparation_policy_id,
        "snapshot_policy_hash": snapshot.preparation_policy_hash == policy.content_hash,
        "plan_policy_id": plan.preparation_policy_id == policy.preparation_policy_id,
        "plan_policy_hash": plan.preparation_policy_hash == policy.content_hash,
        "plan_owner_id": plan.preparation_owner_id == policy.preparation_owner_id,
        "plan_owner_fingerprint": plan.preparation_owner_fingerprint == policy.preparation_owner_fingerprint,
        "plan_request_version": plan.planner_request_version == policy.planner_request_version,
        "plan_contract_id": plan.planner_contract_id == policy.planner_contract_id,
        "plan_roles": plan.model_strategy_roles == policy.model_strategy_roles,
    }
    print(f"::error title=Phase41D2 relation checks::{checks}", flush=True)
    print(
        "::error title=Phase41D2 relation values::"
        f"plan_request={plan.planner_request_version!r} policy_request={policy.planner_request_version!r}; "
        f"plan_contract={plan.planner_contract_id!r} policy_contract={policy.planner_contract_id!r}; "
        f"plan_roles={plan.model_strategy_roles!r} policy_roles={policy.model_strategy_roles!r}",
        flush=True,
    )
finally:
    case.tearDown()
os._exit(97)
