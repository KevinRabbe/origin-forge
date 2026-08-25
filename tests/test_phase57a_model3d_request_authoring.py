from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_design_specification_acceptor import (
    GovernedDesignSpecificationAcceptor,
)
from origin_forge.production_design_specification_currentness import (
    bridge_accepted_design_to_planning_input,
)
from origin_forge.production_design_specification_evidence import (
    DesignSpecificationEvidenceStore,
)
from origin_forge.production_design_specification_models import (
    DesignSpecificationAuditStatus,
    audit_design_specification,
)
from origin_forge.production_design_specifier import (
    BoundedDesignSpecifier,
    DeterministicDesignSpecifierAdapter,
    freeze_governed_design_input,
)
from origin_forge.production_model3d_request_authoring import (
    BoundedModel3DRequestAuthor,
    DeterministicModel3DRequestAuthorAdapter,
    Model3DRequestAuthorError,
    audit_model3d_request_proposal,
)
from origin_forge.production_model3d_request_authoring_evidence import (
    Model3DRequestAuthoringEvidenceError,
    Model3DRequestAuthoringEvidenceStore,
    freeze_model3d_request_input,
    inspect_model3d_request_input,
    resolve_model3d_request_lineage,
)
from origin_forge.production_model3d_request_authoring_models import (
    Model3DRequestAuditStatus,
)
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import (
    PlanAuditStatus,
    PlanProposal,
    PlanStep,
    PlanningInput,
    audit_plan,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import GoalStatus, RunStatus


def _design_response() -> str:
    return json.dumps(
        {
            "summary": "Define a governed low-poly Blender production asset.",
            "requirements": [
                {
                    "key": "shape",
                    "statement": "Produce one bounded semantic 3D asset.",
                    "acceptance_criteria": ["The asset has deterministic geometry."],
                    "constraints": ["No downstream execution authority is implied."],
                }
            ],
            "deliverables": [
                {
                    "key": "model",
                    "objective": "Produce the accepted semantic Blender asset.",
                    "acceptance_criteria": ["The model is exportable as GLB."],
                    "constraints": ["Use the governed Blender capability."],
                    "required_capabilities": ["media.3d.blender"],
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _semantic_value() -> dict[str, object]:
    return {
        "operation": "EXPORT_GLB",
        "project": {
            "schema_version": 1,
            "project_name": "governed-hero",
            "bones": [
                {
                    "bone_id": "root",
                    "name": "Root",
                    "pivot": [0, 0, 0],
                    "rotation": [0, 0, 0],
                    "parent_bone_id": None,
                }
            ],
            "cuboids": [
                {
                    "element_id": "body",
                    "name": "Body",
                    "from": [-1, 0, -1],
                    "to": [1, 2, 1],
                    "origin": [0, 1, 0],
                    "rotation": [0, 0, 0],
                    "parent_bone_id": "root",
                    "inflate": 0,
                    "uv_offset": [0, 0],
                    "mirror_uv": False,
                    "visible": True,
                }
            ],
            "textures": [],
            "animations": [],
        },
    }


def _semantic_response() -> str:
    return json.dumps(_semantic_value(), separators=(",", ":"), sort_keys=True)


class Phase57AModel3DRequestAuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase57a-test")
        self.goal_id = self.runtime.create_goal(
            "Create one governed Blender production asset",
            success_criteria=("A governed 3D asset can be produced.",),
            constraints=("Semantic request publication remains human-gated.",),
        )

        self.capabilities = ProductionCapabilityStore(self.runtime)
        self.catalog = build_builtin_capability_catalog()
        self.capabilities.publish_catalog(self.catalog)
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.blender.model3d",),
            allowed_capability_ids=("design.specify", "media.3d.blender"),
        )
        self.capabilities.publish_policy(self.policy, self.catalog)

        self.design_model = DeterministicDesignSpecifierAdapter(_design_response())
        self.design_evidence = DesignSpecificationEvidenceStore(self.runtime)
        design_input = freeze_governed_design_input(
            self.runtime,
            self.goal_id,
            capability_store=self.capabilities,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.policy.routing_policy_id,
            model=self.design_model,
        )
        design_result = BoundedDesignSpecifier(
            self.runtime,
            self.design_model,
            capability_store=self.capabilities,
            evidence_store=self.design_evidence,
        ).propose(design_input.design_input_id)
        design_audit = audit_design_specification(
            design_input, design_result.specification
        )
        self.assertIs(design_audit.status, DesignSpecificationAuditStatus.PASS)
        self.design_evidence.publish_audit(design_audit)
        acceptance = GovernedDesignSpecificationAcceptor(self.runtime).accept(
            design_result.specification.design_specification_id
        )
        self.assertTrue(acceptance.current)
        self.acceptance_id = acceptance.acceptance_id

        self.planning_input = bridge_accepted_design_to_planning_input(
            self.runtime, self.acceptance_id
        )
        self.planning_evidence = ProductionPlanningEvidenceStore(self.runtime)
        self.plan_proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Materialize the accepted Blender production Task.",
            steps=(
                PlanStep(
                    step_key="model",
                    objective="Produce the accepted semantic Blender asset.",
                    acceptance_criteria=("The model is exportable as GLB.",),
                    constraints=("Use the governed Blender capability.",),
                    required_capabilities=("media.3d.blender",),
                    priority=0,
                    max_attempts=1,
                ),
            ),
        )
        self.planning_evidence.publish_proposal(self.plan_proposal)
        self.plan_audit = audit_plan(self.planning_input, self.plan_proposal)
        self.assertIs(self.plan_audit.status, PlanAuditStatus.PASS)
        self.planning_evidence.publish_audit(self.plan_audit)
        materialization = self.planning_evidence.materialize(
            self.planning_input.planning_input_id,
            self.plan_proposal.proposal_id,
            self.plan_audit.audit_id,
        )
        self.materialization = materialization
        self.task_id = materialization.task_bindings[0].task_id
        self.evidence = Model3DRequestAuthoringEvidenceStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_freeze_reconstructs_exact_phase31_and_accepted_design_lineage(self) -> None:
        design_calls = self.design_model.call_count
        first = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        second = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        lineage = resolve_model3d_request_lineage(self.runtime, self.task_id)
        inspection = inspect_model3d_request_input(
            self.runtime, first.request_input_id, evidence_store=self.evidence
        )

        self.assertEqual(second, first)
        self.assertTrue(inspection.current)
        self.assertIsNone(inspection.stale_reason)
        self.assertEqual(first.task_id, self.task_id)
        self.assertEqual(first.materialization_id, self.materialization.materialization_id)
        self.assertEqual(first.planning_input_id, self.planning_input.planning_input_id)
        self.assertEqual(first.planning_proposal_id, self.plan_proposal.proposal_id)
        self.assertEqual(first.planning_audit_id, self.plan_audit.audit_id)
        self.assertEqual(first.design_acceptance_id, self.acceptance_id)
        self.assertEqual(
            first.design_specification_id,
            lineage.accepted_design.specification.design_specification_id,
        )
        self.assertEqual(self.design_model.call_count, design_calls)
        self.assertFalse((self.runtime.state_dir / "model3d-requests").exists())

    def test_proposal_and_pass_audit_are_durable_without_request_publication(self) -> None:
        request_input = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        model = DeterministicModel3DRequestAuthorAdapter(_semantic_response())
        author = BoundedModel3DRequestAuthor(
            self.runtime, model, evidence_store=self.evidence
        )

        result = author.propose(request_input.request_input_id)
        first_audit = audit_model3d_request_proposal(
            self.runtime, result.proposal.proposal_id, evidence_store=self.evidence
        )
        second_audit = audit_model3d_request_proposal(
            self.runtime, result.proposal.proposal_id, evidence_store=self.evidence
        )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(first_audit, second_audit)
        self.assertIs(first_audit.status, Model3DRequestAuditStatus.PASS)
        self.assertEqual(first_audit.request_input_hash, request_input.content_hash)
        self.assertEqual(first_audit.proposal_hash, result.proposal.content_hash)
        self.assertEqual(first_audit.response_hash, result.proposal.response_hash)
        self.assertEqual(first_audit.project_hash, result.proposal.project.content_hash)
        self.assertFalse((self.runtime.state_dir / "model3d-requests").exists())
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM model3d_request_proposals").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM model3d_request_audits").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE role = 'MODEL3D_REQUEST_AUTHOR'"
                ).fetchone()[0],
                1,
            )

    def test_authority_bearing_model_field_is_rejected_before_durable_proposal(self) -> None:
        request_input = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        value = _semantic_value()
        value["request_id"] = "MODEL3DREQ-00000000-0000-4000-8000-000000000001"
        model = DeterministicModel3DRequestAuthorAdapter(
            json.dumps(value, separators=(",", ":"), sort_keys=True)
        )
        author = BoundedModel3DRequestAuthor(
            self.runtime, model, evidence_store=self.evidence
        )

        with self.assertRaisesRegex(
            Model3DRequestAuthorError, "unknown or missing fields"
        ):
            author.propose(request_input.request_input_id)

        self.assertEqual(model.call_count, 1)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM model3d_request_proposals").fetchone()[0],
                0,
            )
            run = conn.execute(
                "SELECT status FROM runs WHERE role = 'MODEL3D_REQUEST_AUTHOR'"
            ).fetchone()
        self.assertEqual(run["status"], RunStatus.FAILED.value)
        self.assertFalse((self.runtime.state_dir / "model3d-requests").exists())

    def test_stale_accepted_design_blocks_model_replay(self) -> None:
        request_input = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        self.runtime.transition_goal(self.goal_id, GoalStatus.ACTIVE, expected_revision=0)
        inspection = inspect_model3d_request_input(
            self.runtime, request_input.request_input_id, evidence_store=self.evidence
        )
        model = DeterministicModel3DRequestAuthorAdapter(_semantic_response())
        author = BoundedModel3DRequestAuthor(
            self.runtime, model, evidence_store=self.evidence
        )

        self.assertFalse(inspection.current)
        with self.assertRaisesRegex(Model3DRequestAuthorError, "M3DREQIN is stale"):
            author.propose(request_input.request_input_id)
        self.assertEqual(model.call_count, 0)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM model3d_request_proposals").fetchone()[0],
                0,
            )

    def test_planning_input_substitution_is_rejected_by_exact_materialization_relation(self) -> None:
        canonical = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        wrong_planning_input = PlanningInput.create(
            project_id=self.planning_input.project_id,
            goal_id=self.planning_input.goal_id,
            goal_revision=self.planning_input.goal_revision,
            goal_content_hash=self.planning_input.goal_content_hash,
            verified_state_refs=self.planning_input.verified_state_refs,
            active_design_rule_refs=self.planning_input.active_design_rule_refs,
            project_intelligence_hash=self.planning_input.project_intelligence_hash,
            capability_catalog_hash=self.planning_input.capability_catalog_hash,
            capability_ids=self.planning_input.capability_ids,
            model_policy_hash=self.planning_input.model_policy_hash,
            resource_policy_hash=self.planning_input.resource_policy_hash,
        )
        self.planning_evidence.publish_input(wrong_planning_input)
        substituted = replace(
            canonical,
            request_input_id="M3DREQIN-00000000-0000-4000-8000-000000000001",
            planning_input_id=wrong_planning_input.planning_input_id,
            planning_input_hash=wrong_planning_input.content_hash,
        )

        with self.assertRaisesRegex(
            Model3DRequestAuthoringEvidenceError, "publication relation failed"
        ):
            self.evidence.publish_input(substituted)

    def test_v22_evidence_is_immutable(self) -> None:
        request_input = freeze_model3d_request_input(
            self.runtime, self.task_id, evidence_store=self.evidence
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    "UPDATE model3d_request_inputs SET task_content_hash = ? WHERE request_input_id = ?",
                    ("0" * 64, request_input.request_input_id),
                )


if __name__ == "__main__":
    unittest.main()
