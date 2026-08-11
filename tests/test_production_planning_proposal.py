from __future__ import annotations

import hashlib
import json
import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_planning_models import PlanningInput
from origin_forge.production_planning_proposal import (
    PlanProposalParseError,
    parse_plan_proposal,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _input() -> PlanningInput:
    return PlanningInput.create(
        project_id=new_id(IdKind.PROJECT),
        goal_id=new_id(IdKind.GOAL),
        goal_revision=0,
        goal_content_hash=_sha("goal"),
        project_intelligence_hash=_sha("project-intelligence"),
        capability_catalog_hash=_sha("catalog"),
        capability_ids=("code", "runtime-observation"),
        model_policy_hash=_sha("model-policy"),
        resource_policy_hash=_sha("resource-policy"),
    )


def _valid_value() -> dict[str, object]:
    return {
        "summary": "Implement then observe the requested behavior.",
        "steps": [
            {
                "step_key": "code",
                "objective": "Implement the behavior.",
                "acceptance_criteria": ["Implementation tests pass."],
                "constraints": [],
                "required_capabilities": ["code"],
                "priority": 50,
                "budget_hint": {"attempts": 2},
                "depends_on": [],
            },
            {
                "step_key": "runtime",
                "objective": "Observe the behavior at runtime.",
                "acceptance_criteria": ["Runtime evidence is captured."],
                "constraints": [],
                "required_capabilities": ["runtime-observation"],
                "priority": 40,
                "budget_hint": {"attempts": 1},
                "depends_on": ["code"],
            },
        ],
    }


class ProductionPlanningProposalTests(unittest.TestCase):
    def test_valid_proposal_is_bound_to_infrastructure_input(self) -> None:
        planning_input = _input()
        proposal = parse_plan_proposal(
            json.dumps(_valid_value()),
            planning_input=planning_input,
        )

        self.assertTrue(validate_id(proposal.proposal_id, IdKind.PLAN_PROPOSAL))
        self.assertEqual(proposal.planning_input_id, planning_input.planning_input_id)
        self.assertEqual(proposal.planning_input_hash, planning_input.content_hash)
        self.assertEqual(proposal.topological_step_keys, ("code", "runtime"))
        self.assertEqual(proposal.edge_count, 1)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        planning_input = _input()
        raw = '{"summary":"one","summary":"two","steps":[]}'
        with self.assertRaisesRegex(PlanProposalParseError, "duplicate JSON key"):
            parse_plan_proposal(raw, planning_input=planning_input)

    def test_model_cannot_supply_canonical_task_or_authority_fields(self) -> None:
        planning_input = _input()
        value = _valid_value()
        value["steps"][0]["task_id"] = new_id(IdKind.TASK)
        with self.assertRaisesRegex(PlanProposalParseError, "unsupported fields"):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

        value = _valid_value()
        value["approve"] = True
        with self.assertRaisesRegex(
            PlanProposalParseError,
            "exactly summary and steps",
        ):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

    def test_unknown_capability_and_cycles_fail_governed_validation(self) -> None:
        planning_input = _input()
        value = _valid_value()
        value["steps"][0]["required_capabilities"] = ["shell-root"]
        with self.assertRaisesRegex(
            PlanProposalParseError,
            "failed governed validation",
        ):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

        value = _valid_value()
        value["steps"][0]["depends_on"] = ["runtime"]
        with self.assertRaisesRegex(
            PlanProposalParseError,
            "failed governed validation",
        ):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

    def test_priority_and_budget_require_exact_integers(self) -> None:
        planning_input = _input()
        value = _valid_value()
        value["steps"][0]["priority"] = True
        with self.assertRaisesRegex(PlanProposalParseError, "priority is invalid"):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

        value = _valid_value()
        value["steps"][0]["budget_hint"] = {"attempts": False}
        with self.assertRaisesRegex(PlanProposalParseError, "budget_hint is invalid"):
            parse_plan_proposal(json.dumps(value), planning_input=planning_input)

    def test_proposal_bytes_are_bounded_before_json_parsing(self) -> None:
        planning_input = _input()
        oversized = "{" + (" " * (256 * 1024)) + "}"
        with self.assertRaisesRegex(PlanProposalParseError, "exceeds byte limit"):
            parse_plan_proposal(oversized, planning_input=planning_input)

    def test_pathological_json_integer_is_normalized_to_proposal_error(self) -> None:
        planning_input = _input()
        raw = '{"summary":"x","steps":[{"step_key":"a","objective":"A","acceptance_criteria":["ok"],"constraints":[],"required_capabilities":["code"],"priority":' + ("9" * 10000) + ',"budget_hint":{"attempts":1},"depends_on":[]}]}'
        with self.assertRaises(PlanProposalParseError):
            parse_plan_proposal(raw, planning_input=planning_input)


if __name__ == "__main__":
    unittest.main()
