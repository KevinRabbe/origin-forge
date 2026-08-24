from __future__ import annotations

import inspect
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from origin_forge.design_specification_admin_cli import build_parser, main as cli_main
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_design_specification_acceptor import (
    GovernedDesignSpecificationAcceptanceError,
    GovernedDesignSpecificationAcceptor,
)
from origin_forge.production_design_specification_currentness import (
    AcceptedDesignError,
    bridge_accepted_design_to_planning_input,
    inspect_accepted_design,
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
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import GoalStatus


def _response() -> str:
    return json.dumps(
        {
            "summary": "Freeze an accepted design before production planning.",
            "requirements": [
                {
                    "key": "authority",
                    "statement": "Keep semantic acceptance explicitly human-operated.",
                    "acceptance_criteria": [
                        "Only the exact current audited design can be accepted."
                    ],
                    "constraints": [
                        "Acceptance cannot itself execute the downstream planner."
                    ],
                }
            ],
            "deliverables": [
                {
                    "key": "implementation",
                    "objective": "Plan bounded implementation from accepted design evidence.",
                    "acceptance_criteria": [
                        "The Phase-31 input binds the exact DESIGNACC hash."
                    ],
                    "constraints": ["Preserve existing Phase-31 authority."],
                    "required_capabilities": ["code.change"],
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class GovernedDesignSpecificationAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase56c-test")
        self.goal_id = self.runtime.create_goal(
            "Create one governed representative feature",
            success_criteria=("Planning consumes only human-accepted current design.",),
            constraints=("No model may synthesize semantic acceptance.",),
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
        self.acceptor = GovernedDesignSpecificationAcceptor(self.runtime)

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

    def _candidate(self, *, publish_audit: bool = True):
        design_input = self._freeze()
        result = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        ).propose(design_input.design_input_id)
        audit = audit_design_specification(design_input, result.specification)
        self.assertIs(audit.status, DesignSpecificationAuditStatus.PASS)
        if publish_audit:
            self.evidence.publish_audit(audit)
        return design_input, result.specification, audit

    def _second_candidate(self, design_input):
        result = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        ).propose(design_input.design_input_id)
        audit = audit_design_specification(design_input, result.specification)
        self.evidence.publish_audit(audit)
        return result.specification, audit

    def _counts(self) -> tuple[int, int, int]:
        with self.runtime.store.session() as conn:
            acceptance_count = conn.execute(
                "SELECT COUNT(*) FROM design_specification_acceptances"
            ).fetchone()[0]
            planning_input_count = conn.execute(
                "SELECT COUNT(*) FROM planning_inputs"
            ).fetchone()[0]
            proposal_count = conn.execute(
                "SELECT COUNT(*) FROM plan_proposals"
            ).fetchone()[0]
        return acceptance_count, planning_input_count, proposal_count

    def test_accept_publishes_exact_human_acceptance_then_bridge_consumes_it(self) -> None:
        design_input, specification, audit = self._candidate()
        model_calls = self.model.call_count

        result = self.acceptor.accept(specification.design_specification_id)

        self.assertEqual(result.acceptance_authority, "HUMAN_OPERATOR")
        self.assertEqual(result.design_input_id, design_input.design_input_id)
        self.assertEqual(result.design_input_hash, design_input.content_hash)
        self.assertEqual(
            result.design_specification_id, specification.design_specification_id
        )
        self.assertEqual(result.design_specification_hash, specification.content_hash)
        self.assertEqual(result.audit_id, audit.audit_id)
        self.assertEqual(result.audit_hash, audit.content_hash)
        self.assertTrue(result.current)
        self.assertIsNone(result.stale_reason)
        self.assertEqual(self.model.call_count, model_calls)
        self.assertEqual(self._counts(), (1, 0, 0))

        planning_input = bridge_accepted_design_to_planning_input(
            self.runtime,
            result.acceptance_id,
        )
        refs = {ref.ref_id: ref.content_hash for ref in planning_input.verified_state_refs}
        self.assertEqual(refs[result.acceptance_id], inspect_accepted_design(
            self.runtime, result.acceptance_id
        ).acceptance.content_hash)
        self.assertEqual(refs[self.catalog.catalog_id], self.catalog.content_hash)
        self.assertEqual(refs[self.policy.routing_policy_id], self.policy.content_hash)
        self.assertEqual(planning_input.goal_id, design_input.goal_id)
        self.assertEqual(planning_input.goal_revision, design_input.goal_revision)
        self.assertEqual(planning_input.goal_content_hash, design_input.goal_content_hash)
        self.assertEqual(planning_input.active_design_rule_refs, design_input.active_design_rule_refs)
        self.assertEqual(
            planning_input.project_intelligence_hash,
            design_input.project_intelligence_hash,
        )
        self.assertEqual(planning_input.model_policy_hash, design_input.model_policy_hash)
        self.assertEqual(planning_input.resource_policy_hash, design_input.resource_policy_hash)
        self.assertEqual(self.model.call_count, model_calls)
        self.assertEqual(self._counts(), (1, 1, 0))

    def test_exact_acceptance_retry_is_idempotent(self) -> None:
        _, specification, _ = self._candidate()
        first = self.acceptor.accept(specification.design_specification_id)
        second = self.acceptor.accept(specification.design_specification_id)

        self.assertEqual(second, first)
        self.assertEqual(self._counts(), (1, 0, 0))

    def test_missing_audit_fails_before_acceptance(self) -> None:
        _, specification, _ = self._candidate(publish_audit=False)

        with self.assertRaisesRegex(
            GovernedDesignSpecificationAcceptanceError,
            "exactly one durable structural audit",
        ):
            self.acceptor.accept(specification.design_specification_id)
        self.assertEqual(self._counts(), (0, 0, 0))

    def test_goal_drift_blocks_new_acceptance(self) -> None:
        _, specification, _ = self._candidate()
        self.runtime.transition_goal(
            self.goal_id,
            GoalStatus.ACTIVE,
            expected_revision=0,
        )

        with self.assertRaisesRegex(
            GovernedDesignSpecificationAcceptanceError,
            "source evidence is not current",
        ):
            self.acceptor.accept(specification.design_specification_id)
        self.assertEqual(self._counts(), (0, 0, 0))

    def test_existing_acceptance_becomes_historical_stale_after_goal_drift(self) -> None:
        _, specification, _ = self._candidate()
        accepted = self.acceptor.accept(specification.design_specification_id)
        self.runtime.transition_goal(
            self.goal_id,
            GoalStatus.ACTIVE,
            expected_revision=0,
        )

        inspection = inspect_accepted_design(self.runtime, accepted.acceptance_id)
        self.assertFalse(inspection.current)
        self.assertEqual(inspection.stale_reason, "Goal binding is stale")
        with self.assertRaisesRegex(AcceptedDesignError, "accepted design is stale"):
            bridge_accepted_design_to_planning_input(
                self.runtime,
                accepted.acceptance_id,
            )
        with self.assertRaisesRegex(
            GovernedDesignSpecificationAcceptanceError,
            "source evidence is not current",
        ):
            self.acceptor.accept(specification.design_specification_id)
        self.assertEqual(self._counts(), (1, 0, 0))

    def test_competing_candidate_cannot_replace_accepted_candidate(self) -> None:
        design_input, first_specification, _ = self._candidate()
        second_specification, _ = self._second_candidate(design_input)
        accepted = self.acceptor.accept(first_specification.design_specification_id)

        with self.assertRaisesRegex(
            GovernedDesignSpecificationAcceptanceError,
            "already owns acceptance",
        ):
            self.acceptor.accept(second_specification.design_specification_id)

        inspection = inspect_accepted_design(self.runtime, accepted.acceptance_id)
        self.assertEqual(
            inspection.specification.design_specification_id,
            first_specification.design_specification_id,
        )
        self.assertEqual(self._counts(), (1, 0, 0))

    def test_missing_capability_authority_fails_without_recreating_store(self) -> None:
        _, specification, _ = self._candidate()
        capability_root = self.capabilities.root
        shutil.rmtree(capability_root)
        self.assertFalse(capability_root.exists())

        with self.assertRaisesRegex(
            GovernedDesignSpecificationAcceptanceError,
            "source evidence is not current",
        ):
            self.acceptor.accept(specification.design_specification_id)

        self.assertFalse(capability_root.exists())
        self.assertEqual(self._counts(), (0, 0, 0))

    def test_public_mutation_surface_has_no_authority_or_hash_overrides(self) -> None:
        signature = inspect.signature(GovernedDesignSpecificationAcceptor.accept)
        self.assertEqual(
            tuple(signature.parameters),
            ("self", "design_specification_id"),
        )
        _, specification, _ = self._candidate()
        args = build_parser().parse_args(
            [
                "--project-root",
                str(self.root),
                "accept-design-specification",
                "--design-specification-id",
                specification.design_specification_id,
            ]
        )
        self.assertEqual(
            set(vars(args)),
            {"project_root", "command", "design_specification_id"},
        )
        source = inspect.getsource(build_parser)
        for forbidden in (
            "--acceptance-authority",
            "--design-input-id",
            "--design-input-hash",
            "--audit-id",
            "--audit-hash",
            "--goal-id",
            "--force",
            "--bypass",
            "--release",
            "--private-key",
        ):
            self.assertNotIn(forbidden, source)

    def test_module_cli_delegates_acceptance_only_and_does_not_plan(self) -> None:
        _, specification, _ = self._candidate()
        model_calls = self.model.call_count
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli_main(
                [
                    "--project-root",
                    str(self.root),
                    "accept-design-specification",
                    "--design-specification-id",
                    specification.design_specification_id,
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertEqual(
            payload["design_specification_id"],
            specification.design_specification_id,
        )
        self.assertTrue(payload["current"])
        self.assertEqual(self.model.call_count, model_calls)
        self.assertEqual(self._counts(), (1, 0, 0))

    def test_invalid_identity_fails_without_mutation(self) -> None:
        with self.assertRaisesRegex(ValueError, "DESIGNSPEC"):
            self.acceptor.accept("DESIGNACC-not-a-spec")
        self.assertEqual(self._counts(), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
