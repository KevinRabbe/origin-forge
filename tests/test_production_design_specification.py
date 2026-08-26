from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.db import SCHEMA_VERSION
from origin_forge.ids import IdKind, validate_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_design_specification_evidence import (
    DesignSpecificationEvidenceError,
    DesignSpecificationEvidenceStore,
)
from origin_forge.production_design_specification_models import (
    DesignSpecificationAuditStatus,
    audit_design_specification,
)
from origin_forge.production_design_specifier import (
    BoundedDesignSpecifier,
    DesignSpecifierError,
    DeterministicDesignSpecifierAdapter,
    freeze_governed_design_input,
    parse_design_specification,
)
from origin_forge.runs import create_run
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import GoalStatus, RunStatus


def _response(*, capability: str = "code.change") -> str:
    return json.dumps(
        {
            "summary": "Define the bounded production design before Task planning.",
            "requirements": [
                {
                    "key": "intent",
                    "statement": "Preserve the requested product intent.",
                    "acceptance_criteria": ["The design remains traceable to the Goal."],
                    "constraints": ["Do not rewrite canonical semantic truth."],
                }
            ],
            "deliverables": [
                {
                    "key": "implementation",
                    "objective": "Implement the accepted design through governed production.",
                    "acceptance_criteria": ["Downstream work has explicit acceptance criteria."],
                    "constraints": ["Use existing production authority boundaries."],
                    "required_capabilities": [capability],
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class GovernedDesignSpecificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase56a-test")
        self.goal_id = self.runtime.create_goal(
            "Create a governed representative feature",
            success_criteria=("The feature can be planned from accepted design evidence.",),
            constraints=("Preserve explicit authority boundaries.",),
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
        self.model = DeterministicDesignSpecifierAdapter(
            _response(), input_tokens=17, output_tokens=23
        )
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

    def test_schema_v21_reserves_immutable_design_evidence_family(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 26)
        with self.runtime.store.session() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
                if row["name"].startswith("design_specification")
            }
        for table in (
            "design_specification_inputs",
            "design_specifications",
            "design_specification_audits",
            "design_specification_acceptances",
        ):
            self.assertIn(table, tables)
        self.assertIn("design_specification_inputs_immutable_update", triggers)
        self.assertIn("design_specifications_immutable_update", triggers)
        self.assertIn("design_specification_audits_immutable_update", triggers)
        self.assertIn("design_specification_acceptances_immutable_update", triggers)

    def test_input_derives_exact_goal_semantic_capability_and_policy_evidence(self) -> None:
        value = self._freeze()
        self.assertTrue(
            validate_id(value.design_input_id, IdKind.DESIGN_SPECIFICATION_INPUT)
        )
        self.assertEqual(value.project_id, self.runtime.project_id())
        self.assertEqual(value.goal_id, self.goal_id)
        self.assertEqual(value.goal_revision, 0)
        self.assertEqual(value.capability_catalog_hash, self.catalog.content_hash)
        self.assertEqual(value.capability_ids, ("code.change", "design.specify"))
        refs = {ref.ref_id: ref.content_hash for ref in value.verified_state_refs}
        self.assertEqual(refs[self.catalog.catalog_id], self.catalog.content_hash)
        self.assertEqual(refs[self.policy.routing_policy_id], self.policy.content_hash)
        self.assertEqual(self.evidence.load_input(value.design_input_id), value)

        # Exact same immutable identity replay is idempotent, not a second row.
        self.evidence.publish_input(value, capability_store=self.capabilities)
        with self.runtime.store.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM design_specification_inputs WHERE design_input_id = ?",
                (value.design_input_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_one_shot_taskless_run_publishes_candidate_but_not_audit_or_acceptance(self) -> None:
        design_input = self._freeze()
        producer = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        )
        result = producer.propose(design_input.design_input_id)
        self.assertEqual(self.model.call_count, 1)
        self.assertTrue(
            validate_id(result.specification.design_specification_id, IdKind.DESIGN_SPECIFICATION)
        )
        self.assertEqual(
            self.evidence.load_specification(result.specification.design_specification_id),
            result.specification,
        )
        run = self.runtime.get_run(result.run_id)
        self.assertIsNone(run["task_id"])
        self.assertEqual(run["role"], "DESIGN_SPECIFIER")
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)

        with self.runtime.store.session() as conn:
            verification = conn.execute(
                "SELECT * FROM verifications WHERE id = ? AND target_type = 'RUN' AND target_id = ?",
                (result.verification_id, result.run_id),
            ).fetchone()
            self.assertIsNotNone(verification)
            generation_evidence = json.loads(verification["evidence_json"])
            generation_metrics = json.loads(verification["metrics_json"])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM design_specification_audits").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM design_specification_acceptances").fetchone()[0],
                0,
            )
        self.assertFalse(generation_evidence["accepted"])
        self.assertFalse(generation_evidence["audited"])
        self.assertEqual(generation_metrics["model_calls"], 1)
        self.assertEqual(generation_metrics["response_bytes"], len(_response().encode("utf-8")))

    def test_independent_audit_round_trips_and_database_rows_are_immutable(self) -> None:
        design_input = self._freeze()
        result = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        ).propose(design_input.design_input_id)
        audit = audit_design_specification(design_input, result.specification)
        self.evidence.publish_audit(audit)
        self.assertEqual(audit.status, DesignSpecificationAuditStatus.PASS)
        self.assertEqual(self.evidence.load_audit(audit.audit_id), audit)

        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    "UPDATE design_specifications SET content_hash = ? WHERE design_specification_id = ?",
                    ("0" * 64, result.specification.design_specification_id),
                )
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM design_specification_acceptances").fetchone()[0],
                0,
            )

    def test_semantic_goal_drift_fails_before_model_call(self) -> None:
        design_input = self._freeze()
        self.runtime.transition_goal(self.goal_id, GoalStatus.ACTIVE, expected_revision=0)
        producer = BoundedDesignSpecifier(
            self.runtime,
            self.model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        )
        with self.assertRaisesRegex(DesignSpecificationEvidenceError, "Goal binding"):
            producer.propose(design_input.design_input_id)
        self.assertEqual(self.model.call_count, 0)
        with self.runtime.store.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM runs WHERE role = 'DESIGN_SPECIFIER'").fetchone()[0],
                0,
            )

    def test_model_policy_drift_fails_before_run(self) -> None:
        design_input = self._freeze()
        changed_model = DeterministicDesignSpecifierAdapter(
            _response(), fixture_model_id="different-design-fixture"
        )
        producer = BoundedDesignSpecifier(
            self.runtime,
            changed_model,
            capability_store=self.capabilities,
            evidence_store=self.evidence,
        )
        with self.assertRaisesRegex(DesignSpecifierError, "model policy binding"):
            producer.propose(design_input.design_input_id)
        self.assertEqual(changed_model.call_count, 0)

    def test_strict_parser_rejects_duplicate_unknown_authority_and_capability_fields(self) -> None:
        design_input = self._freeze()
        governed_run = create_run(
            self.runtime.store,
            None,
            role="DESIGN_SPECIFIER",
            model_profile=self.model.model_id,
        )
        duplicate = (
            '{"summary":"a","summary":"b","requirements":[],"deliverables":[]}'
        )
        with self.assertRaisesRegex(DesignSpecifierError, "duplicate JSON key"):
            parse_design_specification(
                duplicate,
                design_input=design_input,
                run_id=governed_run,
                model_id=self.model.model_id,
                model_hash=None,
            )

        authority = json.loads(_response())
        authority["accepted"] = True
        with self.assertRaisesRegex(DesignSpecifierError, "schema drifted"):
            parse_design_specification(
                json.dumps(authority),
                design_input=design_input,
                run_id=governed_run,
                model_id=self.model.model_id,
                model_hash=None,
            )

        with self.assertRaisesRegex(DesignSpecifierError, "unknown capabilities"):
            parse_design_specification(
                _response(capability="media.3d.blender"),
                design_input=design_input,
                run_id=governed_run,
                model_id=self.model.model_id,
                model_hash=None,
            )


if __name__ == "__main__":
    unittest.main()
