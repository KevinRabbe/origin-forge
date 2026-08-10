from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_audit import (
    WorkshopDecision,
    WorkshopDecisionOutcome,
    audit_workshop_evaluation,
)
from origin_forge.harness_workshop_evaluation import (
    WorkshopCostTotals,
    WorkshopEvaluationReport,
)
from origin_forge.harness_workshop_models import (
    HarnessComponentKind,
    HarnessImprovementCandidate,
    MetricDirection,
    WorkshopCostCeilings,
    WorkshopEvaluationPlan,
    WorkshopMetricCriterion,
)
from origin_forge.harness_workshop_store import (
    HarnessWorkshopStore,
    HarnessWorkshopStoreError,
)
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import canonical_bytes


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _evidence(kind: EvidenceClass = EvidenceClass.BENCHMARK) -> EvidenceRef:
    return EvidenceRef(
        ref_id=new_id(IdKind.ARTIFACT),
        content_hash=HASH_C,
        evidence_class=kind,
    )


class HarnessWorkshopStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("workshop-store-test")
        self.store = HarnessWorkshopStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _objects(self):
        candidate = HarnessImprovementCandidate.create(
            component_kind=HarnessComponentKind.PROMPT,
            target_component_id="prompt.executor",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["prefer the smallest repair"]},
            hypothesis="The prompt candidate should improve success without regressions.",
            source_evidence=(_evidence(EvidenceClass.TRAJECTORY),),
        )
        plan = WorkshopEvaluationPlan.create(
            candidate=candidate,
            evaluator_protocol="prompt-benchmark-v1",
            evaluation_evidence=(_evidence(),),
            criteria=(
                WorkshopMetricCriterion(
                    "success",
                    MetricDirection.HIGHER_IS_BETTER,
                    minimum_improvement=1,
                    maximum_regression=0,
                ),
            ),
            cost_ceilings=WorkshopCostCeilings(100, 100000, 100000, 100000, 1000),
        )
        costs = WorkshopCostTotals(10, 1000, 200, 1000, 10)
        report = WorkshopEvaluationReport.evaluate(
            candidate=candidate,
            plan=plan,
            baseline_metrics={"success": 80},
            candidate_metrics={"success": 90},
            baseline_cost=costs,
            candidate_cost=costs,
            evaluator_evidence=(_evidence(),),
        )
        audit = audit_workshop_evaluation(
            candidate=candidate,
            plan=plan,
            evaluation=report,
        )
        decision = WorkshopDecision.create(
            candidate=candidate,
            plan=plan,
            audit=audit,
            evaluation=report,
            outcome=WorkshopDecisionOutcome.DEFER,
            rationale="No trusted prompt evaluator adapter exists; evidence is retained without promotion eligibility.",
        )
        return candidate, plan, report, audit, decision

    def test_publish_and_load_all_workshop_objects(self) -> None:
        candidate, plan, report, audit, decision = self._objects()
        published = (
            ("candidates", candidate.candidate_id, candidate.content_hash, self.store.publish_candidate(candidate)),
            ("plans", plan.plan_id, plan.content_hash, self.store.publish_plan(plan)),
            ("reports", report.report_id, report.content_hash, self.store.publish_evaluation(report)),
            ("audits", audit.audit_id, audit.content_hash, self.store.publish_audit(audit)),
            ("decisions", decision.decision_id, decision.content_hash, self.store.publish_decision(decision)),
        )
        for category, object_id, expected_hash, path in published:
            self.assertTrue(path.is_file())
            envelope = self.store.load(category, object_id)
            self.assertEqual(envelope["content_hash"], expected_hash)
            self.assertEqual(envelope["object_id"], object_id)
            self.assertEqual(envelope["object_type"], category)
        self.assertFalse(decision.to_dict()["promotion_eligible"])

    def test_object_is_immutable_no_overwrite_even_for_identical_payload(self) -> None:
        candidate, *_ = self._objects()
        self.store.publish_candidate(candidate)
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "already exists"):
            self.store.publish_candidate(candidate)

    def test_payload_tampering_is_detected_even_when_json_remains_canonical(self) -> None:
        candidate, *_ = self._objects()
        path = self.store.publish_candidate(candidate)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["hypothesis"] = "tampered after publication"
        path.write_bytes(canonical_bytes(envelope))
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "content hash drifted"):
            self.store.load("candidates", candidate.candidate_id)

    def test_noncanonical_rewrite_is_rejected(self) -> None:
        candidate, *_ = self._objects()
        path = self.store.publish_candidate(candidate)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "not canonical"):
            self.store.load("candidates", candidate.candidate_id)

    def test_symlinked_category_is_rejected(self) -> None:
        candidate, *_ = self._objects()
        workshop = self.runtime.state_dir / "workshop"
        workshop.mkdir()
        target = self.runtime.state_dir / "outside-workshop-category"
        target.mkdir()
        (workshop / "candidates").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "may not be a symlink"):
            self.store.publish_candidate(candidate)

    def test_symlinked_object_is_rejected(self) -> None:
        candidate, *_ = self._objects()
        directory = self.runtime.state_dir / "workshop" / "candidates"
        directory.mkdir(parents=True)
        target = self.runtime.state_dir / "outside-workshop-object.json"
        target.write_text("{}", encoding="utf-8")
        (directory / f"{candidate.candidate_id}.json").symlink_to(target)
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "already exists"):
            self.store.publish_candidate(candidate)
        with self.assertRaisesRegex(HarnessWorkshopStoreError, "may not be a symlink"):
            self.store.load("candidates", candidate.candidate_id)

    def test_per_object_byte_limit_fails_closed(self) -> None:
        candidate, *_ = self._objects()
        with patch("origin_forge.harness_workshop_store._MAX_OBJECT_BYTES", 1):
            with self.assertRaisesRegex(HarnessWorkshopStoreError, "byte limit"):
                self.store.publish_candidate(candidate)

    def test_listing_revalidates_each_object(self) -> None:
        candidate, plan, *_ = self._objects()
        self.store.publish_candidate(candidate)
        self.store.publish_plan(plan)
        candidate_rows = self.store.list_objects("candidates")
        self.assertEqual(candidate_rows[0]["object_id"], candidate.candidate_id)
        plan_rows = self.store.list_objects("plans")
        self.assertEqual(plan_rows[0]["content_hash"], plan.content_hash)


if __name__ == "__main__":
    unittest.main()
