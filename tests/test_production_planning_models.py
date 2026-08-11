from __future__ import annotations

import hashlib
import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_planning_models import (
    PlanAuditStatus,
    PlanProposal,
    PlanStep,
    PlanningEvidenceRef,
    PlanningInput,
    ProductionPlanningModelError,
    audit_plan,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _input(*, capabilities: tuple[str, ...] = ("code", "runtime-observation")) -> PlanningInput:
    return PlanningInput.create(
        project_id=new_id(IdKind.PROJECT),
        goal_id=new_id(IdKind.GOAL),
        goal_revision=3,
        goal_content_hash=_sha("goal"),
        verified_state_refs=(
            PlanningEvidenceRef("TASK-frozen", _sha("task"), revision=2),
        ),
        active_design_rule_refs=(
            PlanningEvidenceRef("RULE-frozen", _sha("rule"), revision=1),
        ),
        project_intelligence_hash=_sha("project-intelligence"),
        capability_catalog_hash=_sha("capability-catalog"),
        capability_ids=capabilities,
        model_policy_hash=_sha("model-policy"),
        resource_policy_hash=_sha("resource-policy"),
    )


class ProductionPlanningModelTests(unittest.TestCase):
    def test_phase31_ids_are_infrastructure_owned(self) -> None:
        for kind in (
            IdKind.PLANNING_INPUT,
            IdKind.PLAN_PROPOSAL,
            IdKind.PLAN_AUDIT,
            IdKind.PLAN_MATERIALIZATION,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))

    def test_planning_input_is_content_addressed_and_normalized(self) -> None:
        planning_input = _input(capabilities=("runtime-observation", "code"))
        self.assertTrue(validate_id(planning_input.planning_input_id, IdKind.PLANNING_INPUT))
        self.assertEqual(planning_input.capability_ids, ("code", "runtime-observation"))
        self.assertEqual(len(planning_input.content_hash), 64)
        self.assertEqual(
            planning_input.to_dict()["verified_state_refs"][0]["ref_id"],
            "TASK-frozen",
        )

    def test_plan_proposal_has_deterministic_dag_evidence(self) -> None:
        planning_input = _input()
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Implement and verify behavior.",
            steps=(
                PlanStep(
                    step_key="runtime",
                    objective="Observe runtime behavior.",
                    acceptance_criteria=("Runtime evidence is captured.",),
                    required_capabilities=("runtime-observation",),
                    priority=20,
                    depends_on=("code",),
                ),
                PlanStep(
                    step_key="code",
                    objective="Implement behavior.",
                    acceptance_criteria=("Implementation tests pass.",),
                    required_capabilities=("code",),
                    priority=50,
                ),
            ),
        )

        self.assertTrue(validate_id(proposal.proposal_id, IdKind.PLAN_PROPOSAL))
        self.assertEqual(tuple(step.step_key for step in proposal.steps), ("code", "runtime"))
        self.assertEqual(proposal.topological_step_keys, ("code", "runtime"))
        self.assertEqual(proposal.edge_count, 1)
        self.assertEqual(proposal.max_depth, 2)
        self.assertEqual(len(proposal.content_hash), 64)

        audit = audit_plan(planning_input, proposal)
        self.assertEqual(audit.status, PlanAuditStatus.PASS)
        self.assertEqual(audit.task_count, 2)
        self.assertEqual(audit.edge_count, 1)
        self.assertEqual(audit.max_depth, 2)
        self.assertEqual(audit.topological_step_keys, ("code", "runtime"))
        self.assertIsNone(audit.failure_reason)

    def test_plan_rejects_unknown_dependency_and_cycles(self) -> None:
        planning_input = _input()
        with self.assertRaises(ProductionPlanningModelError):
            PlanProposal.create(
                planning_input=planning_input,
                summary="Invalid missing dependency.",
                steps=(
                    PlanStep(
                        step_key="code",
                        objective="Implement behavior.",
                        acceptance_criteria=("Tests pass.",),
                        required_capabilities=("code",),
                        depends_on=("missing",),
                    ),
                ),
            )

        with self.assertRaises(ProductionPlanningModelError):
            PlanProposal.create(
                planning_input=planning_input,
                summary="Invalid cycle.",
                steps=(
                    PlanStep(
                        step_key="a",
                        objective="A.",
                        acceptance_criteria=("A passes.",),
                        required_capabilities=("code",),
                        depends_on=("b",),
                    ),
                    PlanStep(
                        step_key="b",
                        objective="B.",
                        acceptance_criteria=("B passes.",),
                        required_capabilities=("code",),
                        depends_on=("a",),
                    ),
                ),
            )

    def test_exact_input_binding_rejects_unknown_capability(self) -> None:
        planning_input = _input(capabilities=("code",))
        proposal = PlanProposal(
            proposal_id=new_id(IdKind.PLAN_PROPOSAL),
            planning_input_id=planning_input.planning_input_id,
            planning_input_hash=planning_input.content_hash,
            summary="Structurally valid but unauthorized capability.",
            steps=(
                PlanStep(
                    step_key="audio",
                    objective="Create audio.",
                    acceptance_criteria=("Audio evidence exists.",),
                    required_capabilities=("audio",),
                ),
            ),
        )
        with self.assertRaises(ProductionPlanningModelError):
            proposal.bind(planning_input)

        audit = audit_plan(planning_input, proposal)
        self.assertEqual(audit.status, PlanAuditStatus.FAIL)
        self.assertEqual(
            audit.failure_reason,
            "proposal failed exact planning-input binding",
        )

    def test_step_contract_rejects_nonexact_attempt_values(self) -> None:
        with self.assertRaises(ProductionPlanningModelError):
            PlanStep(
                step_key="valid",
                objective="Invalid attempts.",
                acceptance_criteria=("Never accepted.",),
                max_attempts=True,
            )


if __name__ == "__main__":
    unittest.main()
