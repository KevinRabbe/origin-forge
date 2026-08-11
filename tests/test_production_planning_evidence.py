from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_planning_evidence import (
    ProductionPlanningEvidenceError,
    ProductionPlanningEvidenceStore,
    freeze_planning_input,
)
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import GoalStatus, TaskStatus
from origin_forge.task_dependencies import flow_dependency_graph


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class ProductionPlanningEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("planning-evidence-test")
        self.goal = self.runtime.create_goal(
            "Build a cross-domain feature",
            success_criteria=("Feature is verified.",),
            constraints=("Keep production authority explicit.",),
        )
        self.evidence = ProductionPlanningEvidenceStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _freeze(self):
        return freeze_planning_input(
            self.runtime,
            self.goal,
            project_intelligence_hash=_sha("project-intelligence"),
            capability_catalog_hash=_sha("catalog"),
            capability_ids=("code", "runtime-observation"),
            model_policy_hash=_sha("model-policy"),
            resource_policy_hash=_sha("resource-policy"),
        )

    @staticmethod
    def _proposal(planning_input):
        return PlanProposal.create(
            planning_input=planning_input,
            summary="Implement the feature and capture runtime evidence.",
            steps=(
                PlanStep(
                    step_key="runtime",
                    objective="Capture runtime evidence.",
                    acceptance_criteria=("Runtime evidence is captured.",),
                    required_capabilities=("runtime-observation",),
                    priority=40,
                    depends_on=("code",),
                ),
                PlanStep(
                    step_key="code",
                    objective="Implement the feature.",
                    acceptance_criteria=("Implementation tests pass.",),
                    constraints=("Stay within the requested feature.",),
                    required_capabilities=("code",),
                    priority=50,
                    max_attempts=2,
                ),
            ),
        )

    def _publish_plan(self):
        planning_input = self._freeze()
        proposal = self._proposal(planning_input)
        audit = audit_plan(planning_input, proposal)
        self.evidence.publish_input(planning_input)
        self.evidence.publish_proposal(proposal)
        self.evidence.publish_audit(audit)
        return planning_input, proposal, audit

    def test_evidence_round_trips_with_exact_hash_revalidation(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        self.assertEqual(self.evidence.load_input(planning_input.planning_input_id), planning_input)
        self.assertEqual(self.evidence.load_proposal(proposal.proposal_id), proposal)
        self.assertEqual(self.evidence.load_audit(audit.audit_id), audit)

        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "already exists"):
            self.evidence.publish_input(planning_input)
        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "already exists"):
            self.evidence.publish_proposal(proposal)
        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "already exists"):
            self.evidence.publish_audit(audit)

    def test_materialization_atomically_allocates_canonical_flow_tasks_and_dependencies(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        materialization = self.evidence.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )

        self.assertTrue(
            validate_id(materialization.materialization_id, IdKind.PLAN_MATERIALIZATION)
        )
        self.assertTrue(validate_id(materialization.flow_id, IdKind.FLOW))
        self.assertEqual(materialization.goal_id, self.goal)
        bindings = {value.step_key: value.task_id for value in materialization.task_bindings}
        self.assertEqual(set(bindings), {"code", "runtime"})
        self.assertTrue(all(validate_id(value, IdKind.TASK) for value in bindings.values()))

        flow = self.runtime.get_flow(materialization.flow_id)
        self.assertEqual(flow["goal_id"], self.goal)
        self.assertEqual(flow["controller"], "production-planning-v1")

        code = self.runtime.get_task(bindings["code"])
        runtime = self.runtime.get_task(bindings["runtime"])
        self.assertEqual(code["status"], TaskStatus.QUEUED.value)
        self.assertEqual(runtime["status"], TaskStatus.QUEUED.value)
        self.assertEqual(json.loads(code["required_capabilities_json"]), ["code"])
        self.assertEqual(json.loads(code["budget_json"]), {"attempts": 2})
        self.assertEqual(
            json.loads(runtime["required_capabilities_json"]),
            ["runtime-observation"],
        )

        graph = flow_dependency_graph(self.runtime.store, materialization.flow_id)
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(graph.edges[0].task_id, bindings["runtime"])
        self.assertEqual(graph.edges[0].required_task_id, bindings["code"])
        self.assertLess(
            graph.topological_task_ids.index(bindings["code"]),
            graph.topological_task_ids.index(bindings["runtime"]),
        )

        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT content_hash, payload_json FROM plan_materializations WHERE materialization_id = ?",
                (materialization.materialization_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["content_hash"], materialization.content_hash)
        self.assertEqual(json.loads(row["payload_json"]), materialization.to_dict())

    def test_duplicate_materialization_is_rejected_without_extra_flow(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        first = self.evidence.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=audit.audit_id,
        )
        flow_count = self.runtime.count_flows(self.goal)
        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "already materialized"):
            self.evidence.materialize(
                planning_input_id=planning_input.planning_input_id,
                proposal_id=proposal.proposal_id,
                audit_id=audit.audit_id,
            )
        self.assertEqual(self.runtime.count_flows(self.goal), flow_count)
        self.assertEqual(self.runtime.get_flow(first.flow_id)["id"], first.flow_id)

    def test_stale_goal_binding_cannot_materialize(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        self.runtime.transition_goal(self.goal, GoalStatus.ACTIVE, expected_revision=0)
        self.assertEqual(self.runtime.count_flows(self.goal), 0)

        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "became stale"):
            self.evidence.materialize(
                planning_input_id=planning_input.planning_input_id,
                proposal_id=proposal.proposal_id,
                audit_id=audit.audit_id,
            )
        self.assertEqual(self.runtime.count_flows(self.goal), 0)

    def test_tampered_audit_fails_revalidation_before_materialization(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE plan_audits SET content_hash = ? WHERE audit_id = ?",
                ("0" * 64, audit.audit_id),
            )

        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "content hash drifted"):
            self.evidence.load_audit(audit.audit_id)
        with self.assertRaisesRegex(ProductionPlanningEvidenceError, "content hash drifted"):
            self.evidence.materialize(
                planning_input_id=planning_input.planning_input_id,
                proposal_id=proposal.proposal_id,
                audit_id=audit.audit_id,
            )
        self.assertEqual(self.runtime.count_flows(self.goal), 0)

    def test_injected_mid_transaction_event_failure_rolls_back_everything(self) -> None:
        planning_input, proposal, audit = self._publish_plan()
        original_new_id = new_id
        repeated_event_id = original_new_id(IdKind.EVENT)

        def colliding_event_ids(kind: IdKind) -> str:
            if kind is IdKind.EVENT:
                return repeated_event_id
            return original_new_id(kind)

        with patch(
            "origin_forge.production_planning_evidence.new_id",
            side_effect=colliding_event_ids,
        ):
            with self.assertRaisesRegex(ProductionPlanningEvidenceError, "atomic plan materialization failed"):
                self.evidence.materialize(
                    planning_input_id=planning_input.planning_input_id,
                    proposal_id=proposal.proposal_id,
                    audit_id=audit.audit_id,
                )

        self.assertEqual(self.runtime.count_flows(self.goal), 0)
        with self.runtime.store.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM task_dependencies").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM plan_materializations").fetchone()[0], 0)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM state_events WHERE aggregate_type IN ('FLOW', 'TASK', 'TASK_DEPENDENCY')"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
