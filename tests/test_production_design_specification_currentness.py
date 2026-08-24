from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_design_specification_currentness import (
    AcceptedDesignError,
    DesignRecoveryStage,
    DesignSpecificationAcceptance,
    _planning_verified_refs,
    bridge_accepted_design_to_planning_input,
    inspect_accepted_design,
    inspect_design_recovery,
)
from origin_forge.production_design_specification_evidence import (
    DesignSpecificationEvidenceStore,
)
from origin_forge.production_design_specification_models import (
    DesignSpecificationAuditStatus,
    DesignSpecificationInput,
    audit_design_specification,
)
from origin_forge.production_design_specifier import (
    BoundedDesignSpecifier,
    DeterministicDesignSpecifierAdapter,
    freeze_governed_design_input,
)
from origin_forge.production_planning_models import PlanningEvidenceRef
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import utc_now
from origin_forge.state import GoalStatus


def _response() -> str:
    return json.dumps(
        {
            "summary": "Define exact accepted design evidence before planning.",
            "requirements": [
                {
                    "key": "intent",
                    "statement": "Preserve the governed Goal intent.",
                    "acceptance_criteria": ["The design is traceable to current source evidence."],
                    "constraints": ["Do not grant downstream execution authority."],
                }
            ],
            "deliverables": [
                {
                    "key": "implementation",
                    "objective": "Plan bounded implementation work.",
                    "acceptance_criteria": ["Downstream Tasks remain separately governed."],
                    "constraints": ["Preserve Phase-31 authority."],
                    "required_capabilities": ["code.change"],
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class AcceptedDesignCurrentnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase56b-test")
        self.goal_id = self.runtime.create_goal(
            "Create one governed representative feature",
            success_criteria=("Planning consumes only accepted current design.",),
            constraints=("Never synthesize human acceptance.",),
        )
        self.capabilities = ProductionCapabilityStore(self.runtime)
        self.catalog = build_builtin_capability_catalog()
        self.capabilities.publish_catalog(self.catalog)
        self.policy = CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("design.specify", "code.change"),
        )
        self.capabilities.publish_policy(self.policy, self.catalog)
        self.model = DeterministicDesignSpecifierAdapter(_response())
        self.evidence = DesignSpecificationEvidenceStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _freeze(self):
        return freeze_governed_design_input(
            self.runtime,
            self.goal_id,
            capability_store=self.capabilities,
            catalog_id=self.catalog.catalog_id,
            routing_policy_id=self.policy.routing_policy_id,
            model=self.model,
        )

    def _pass_candidate(self):
        design_input = self._freeze()
        result = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        ).propose(design_input.design_input_id)
        audit = audit_design_specification(design_input, result.specification)
        self.assertIs(audit.status, DesignSpecificationAuditStatus.PASS)
        self.evidence.publish_audit(audit)
        return design_input, result.specification, audit

    def _insert_acceptance(
        self,
        design_input,
        specification,
        audit,
        *,
        stored_hash: str | None = None,
    ) -> DesignSpecificationAcceptance:
        acceptance = DesignSpecificationAcceptance(
            acceptance_id=new_id(IdKind.DESIGN_SPECIFICATION_ACCEPTANCE),
            project_id=self.runtime.project_id(),
            goal_id=self.goal_id,
            design_input_id=design_input.design_input_id,
            design_input_hash=design_input.content_hash,
            design_specification_id=specification.design_specification_id,
            design_specification_hash=specification.content_hash,
            audit_id=audit.audit_id,
            audit_hash=audit.content_hash,
            acceptance_authority="HUMAN_OPERATOR",
            schema_version=1,
            accepted_at=utc_now(),
        )
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO design_specification_acceptances(
                       acceptance_id, project_id, goal_id,
                       design_input_id, design_input_hash,
                       design_specification_id, design_specification_hash,
                       audit_id, audit_hash, acceptance_authority,
                       schema_version, content_hash, accepted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    acceptance.acceptance_id,
                    acceptance.project_id,
                    acceptance.goal_id,
                    acceptance.design_input_id,
                    acceptance.design_input_hash,
                    acceptance.design_specification_id,
                    acceptance.design_specification_hash,
                    acceptance.audit_id,
                    acceptance.audit_hash,
                    acceptance.acceptance_authority,
                    acceptance.schema_version,
                    stored_hash or acceptance.content_hash,
                    acceptance.accepted_at,
                ),
            )
        return acceptance

    def test_read_only_acceptance_validation_and_recovery_never_replay_model(self) -> None:
        design_input, specification, audit = self._pass_candidate()
        acceptance = self._insert_acceptance(design_input, specification, audit)
        calls = self.model.call_count
        before = self.runtime.store.db_path.read_bytes()

        first = inspect_accepted_design(self.runtime, acceptance.acceptance_id)
        second = inspect_accepted_design(self.runtime, acceptance.acceptance_id)
        recovery_one = inspect_design_recovery(self.runtime, design_input.design_input_id)
        recovery_two = inspect_design_recovery(self.runtime, design_input.design_input_id)

        after = self.runtime.store.db_path.read_bytes()
        self.assertTrue(first.current)
        self.assertIsNone(first.stale_reason)
        self.assertEqual(second, first)
        self.assertEqual(recovery_one, recovery_two)
        self.assertIs(recovery_one.stage, DesignRecoveryStage.ACCEPTANCE_DURABLE)
        self.assertEqual(recovery_one.acceptance_id, acceptance.acceptance_id)
        self.assertEqual(self.model.call_count, calls)
        self.assertEqual(after, before)

    def test_canonical_acceptance_hash_tamper_fails_closed(self) -> None:
        design_input, specification, audit = self._pass_candidate()
        acceptance = self._insert_acceptance(
            design_input,
            specification,
            audit,
            stored_hash="0" * 64,
        )
        with self.assertRaisesRegex(AcceptedDesignError, "canonical hash drifted"):
            inspect_accepted_design(self.runtime, acceptance.acceptance_id)

    def test_goal_drift_makes_acceptance_stale_and_blocks_bridge(self) -> None:
        design_input, specification, audit = self._pass_candidate()
        acceptance = self._insert_acceptance(design_input, specification, audit)
        self.runtime.transition_goal(self.goal_id, GoalStatus.ACTIVE, expected_revision=0)

        inspection = inspect_accepted_design(self.runtime, acceptance.acceptance_id)
        self.assertFalse(inspection.current)
        self.assertEqual(inspection.stale_reason, "Goal binding is stale")
        with self.assertRaisesRegex(AcceptedDesignError, "accepted design is stale"):
            bridge_accepted_design_to_planning_input(
                self.runtime, acceptance.acceptance_id
            )
        with self.runtime.store.session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM planning_inputs").fetchone()[0]
        self.assertEqual(count, 0)

    def test_bridge_is_idempotent_and_stops_before_planner_execution(self) -> None:
        design_input, specification, audit = self._pass_candidate()
        acceptance = self._insert_acceptance(design_input, specification, audit)
        calls = self.model.call_count

        first = bridge_accepted_design_to_planning_input(
            self.runtime, acceptance.acceptance_id
        )
        second = bridge_accepted_design_to_planning_input(
            self.runtime, acceptance.acceptance_id
        )

        self.assertEqual(second, first)
        refs = {ref.ref_id: ref.content_hash for ref in first.verified_state_refs}
        self.assertEqual(
            refs,
            {
                acceptance.acceptance_id: acceptance.content_hash,
                self.catalog.catalog_id: self.catalog.content_hash,
                self.policy.routing_policy_id: self.policy.content_hash,
            },
        )
        self.assertEqual(first.active_design_rule_refs, design_input.active_design_rule_refs)
        self.assertEqual(
            first.project_intelligence_hash, design_input.project_intelligence_hash
        )
        self.assertEqual(first.capability_catalog_hash, self.catalog.content_hash)
        self.assertEqual(first.capability_ids, design_input.capability_ids)
        self.assertEqual(first.model_policy_hash, design_input.model_policy_hash)
        self.assertEqual(first.resource_policy_hash, design_input.resource_policy_hash)
        self.assertEqual(self.model.call_count, calls)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM planning_inputs").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE role = 'PLANNER'"
                ).fetchone()[0],
                0,
            )

    def test_maximal_design_input_does_not_overflow_phase31_evidence_bound(self) -> None:
        semantic_refs = tuple(
            PlanningEvidenceRef(f"VERIFY-synthetic-{index:03d}", f"{index % 10}" * 64)
            for index in range(126)
        )
        maximal = DesignSpecificationInput(
            design_input_id=new_id(IdKind.DESIGN_SPECIFICATION_INPUT),
            project_id=self.runtime.project_id(),
            goal_id=self.goal_id,
            goal_revision=0,
            goal_content_hash="a" * 64,
            verified_state_refs=(
                *semantic_refs,
                PlanningEvidenceRef(self.catalog.catalog_id, self.catalog.content_hash),
                PlanningEvidenceRef(
                    self.policy.routing_policy_id, self.policy.content_hash
                ),
            ),
            active_design_rule_refs=(),
            project_intelligence_hash="b" * 64,
            capability_catalog_hash=self.catalog.content_hash,
            capability_ids=tuple(sorted(self.policy.allowed_capability_ids)),
            model_policy_hash="c" * 64,
            resource_policy_hash="d" * 64,
        )
        self.assertEqual(len(maximal.verified_state_refs), 128)
        acceptance = DesignSpecificationAcceptance(
            acceptance_id=new_id(IdKind.DESIGN_SPECIFICATION_ACCEPTANCE),
            project_id=self.runtime.project_id(),
            goal_id=self.goal_id,
            design_input_id=maximal.design_input_id,
            design_input_hash=maximal.content_hash,
            design_specification_id=new_id(IdKind.DESIGN_SPECIFICATION),
            design_specification_hash="e" * 64,
            audit_id=new_id(IdKind.DESIGN_SPECIFICATION_AUDIT),
            audit_hash="f" * 64,
            acceptance_authority="HUMAN_OPERATOR",
            schema_version=1,
            accepted_at=utc_now(),
        )

        refs = _planning_verified_refs(self.evidence, maximal, acceptance)

        self.assertEqual(len(refs), 3)
        self.assertEqual(
            {ref.ref_id for ref in refs},
            {
                acceptance.acceptance_id,
                self.catalog.catalog_id,
                self.policy.routing_policy_id,
            },
        )
        self.assertFalse(
            {ref.ref_id for ref in refs}.intersection(
                {ref.ref_id for ref in semantic_refs}
            )
        )

    def test_recovery_reports_durable_competing_candidates_without_generation(self) -> None:
        design_input = self._freeze()
        producer = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        )
        first = producer.propose(design_input.design_input_id)
        second = producer.propose(design_input.design_input_id)
        audit = audit_design_specification(design_input, first.specification)
        self.evidence.publish_audit(audit)
        calls = self.model.call_count

        recovery = inspect_design_recovery(self.runtime, design_input.design_input_id)
        again = inspect_design_recovery(self.runtime, design_input.design_input_id)

        self.assertIs(recovery.stage, DesignRecoveryStage.PASS_AUDIT_DURABLE)
        self.assertEqual(len(recovery.candidates), 2)
        self.assertEqual(
            {candidate.design_specification_id for candidate in recovery.candidates},
            {
                first.specification.design_specification_id,
                second.specification.design_specification_id,
            },
        )
        self.assertIsNone(recovery.acceptance_id)
        self.assertEqual(again, recovery)
        self.assertEqual(self.model.call_count, calls)

    def test_bridge_surface_accepts_no_caller_hash_or_planner_authority(self) -> None:
        parameters = tuple(
            inspect.signature(bridge_accepted_design_to_planning_input).parameters
        )
        self.assertEqual(parameters, ("runtime", "acceptance_id"))


if __name__ == "__main__":
    unittest.main()
