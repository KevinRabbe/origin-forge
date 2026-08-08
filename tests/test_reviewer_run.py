from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.model import ModelResponse
from origin_forge.reviewer_run import ReviewerRunCoordinator, ReviewerRunError
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_evidence_store import SpecialistEvidenceStore
from origin_forge.specialist_models import (
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)
from origin_forge.specialist_store import SpecialistStore
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class FakeReviewerModel:
    def __init__(self, payload: object, *, input_tokens=120, output_tokens=30):
        self.payload = payload
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = []

    @property
    def model_id(self) -> str:
        return "reviewer-run-model"

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps(self.payload),
            model_id=self.model_id,
            model_hash="sha256:" + "e" * 64,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class ReviewerRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("reviewer-run-test")
        self.store = SpecialistStore(self.runtime)
        self.evidence_store = SpecialistEvidenceStore(self.store)

        # Production Task being reviewed. It remains completely independent of
        # the review Task/Run lifecycle.
        goal = self.runtime.create_goal("Production goal")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.parent_task = self.runtime.create_task(flow, "Production task")
        revision = self.runtime.transition_task(
            self.parent_task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.parent_task, TaskStatus.RUNNING, expected_revision=revision
        )

        payload = {
            "id": self.parent_task,
            "status": self.runtime.get_task(self.parent_task)["status"],
            "objective": self.runtime.get_task(self.parent_task)["objective"],
        }
        self.ref = SpecialistEvidenceRef(
            self.parent_task,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.record = SpecialistEvidenceRecord(self.ref, payload)
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.parent_task,
            objective="Independently review bounded production evidence",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(self.contract, (self.record,))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _review_run(self, *, role="REVIEWER") -> tuple[str, str]:
        goal = self.runtime.create_goal("Review evidence")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Run isolated Reviewer")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        run = self.runtime.start_run(task, role=role, model_profile="reviewer-strong")
        return task, run

    def _payload(self):
        return {
            "findings": [
                {
                    "severity": "HIGH",
                    "category": "TEST_GAP",
                    "summary": "The bounded evidence does not demonstrate one edge case.",
                    "evidence_ref_ids": [self.parent_task],
                    "recommendation": "Create a separate governed test Task if this gap matters.",
                }
            ]
        }

    def test_success_persists_exact_input_report_audit_and_structural_run_evidence(self) -> None:
        review_task, review_run = self._review_run()
        model = FakeReviewerModel(self._payload())
        coordinator = ReviewerRunCoordinator(
            self.runtime,
            model,
            store=self.store,
            evidence_store=self.evidence_store,
        )
        parent_before = dict(self.runtime.get_task(self.parent_task))

        result = coordinator.execute(
            self.package,
            review_run_id=review_run,
            review_task_id=review_task,
        )

        self.assertEqual(self.store.load_contract(self.contract.contract_id), self.contract)
        self.assertEqual(self.evidence_store.load(self.contract.contract_id), self.package)
        self.assertEqual(self.store.load_report(result.review.report.report_id), result.review.report)
        self.assertEqual(
            self.store.load_audit(self.store.audit_id(result.audit)),
            result.audit,
        )
        self.assertTrue(result.verification_id.startswith("VERIFY-"))
        records = self.runtime.list_verifications("RUN", review_run)
        self.assertEqual(len(records), 1)
        verification = records[0]
        self.assertEqual(verification["id"], result.verification_id)
        self.assertEqual(verification["verification_type"], "reviewer-structural-capture")
        self.assertEqual(verification["status"], "PASS")
        evidence = json.loads(verification["evidence_json"])
        metrics = json.loads(verification["metrics_json"])
        self.assertEqual(evidence["contract_id"], self.contract.contract_id)
        self.assertEqual(evidence["contract_hash"], self.contract.content_hash)
        self.assertEqual(evidence["evidence_package_hash"], self.package.content_hash)
        self.assertEqual(evidence["parent_task_id"], self.parent_task)
        self.assertEqual(evidence["model_profile"], "reviewer-strong")
        self.assertEqual(evidence["model_id"], "reviewer-run-model")
        self.assertEqual(evidence["report_id"], result.review.report.report_id)
        self.assertEqual(evidence["report_hash"], result.review.report.content_hash)
        self.assertEqual(evidence["overall_risk"], "HIGH")
        self.assertEqual(evidence["audit_status"], "STRUCTURALLY_VALID")
        self.assertFalse(evidence["semantic_findings_verified"])
        self.assertFalse(evidence["production_verification_changed"])
        self.assertEqual(metrics["input_tokens"], 120)
        self.assertEqual(metrics["output_tokens"], 30)
        self.assertEqual(metrics["finding_count"], 1)
        self.assertEqual(metrics["severity_counts"], {"HIGH": 1})
        self.assertEqual(metrics["category_counts"], {"TEST_GAP": 1})
        self.assertFalse(result.to_dict()["semantic_findings_verified"])
        self.assertFalse(result.to_dict()["production_verification_changed"])

        # Coordinator does not own lifecycle completion and cannot change the
        # production Task being reviewed.
        self.assertEqual(self.runtime.get_run(review_run)["status"], RunStatus.RUNNING.value)
        self.assertEqual(self.runtime.get_task(review_task)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(dict(self.runtime.get_task(self.parent_task)), parent_before)
        self.assertEqual(len(model.requests), 1)

    def test_wrong_run_role_fails_before_persistence_or_model_call(self) -> None:
        review_task, review_run = self._review_run(role="EXECUTOR")
        model = FakeReviewerModel(self._payload())
        coordinator = ReviewerRunCoordinator(self.runtime, model, store=self.store)
        with self.assertRaisesRegex(ReviewerRunError, "exactly REVIEWER"):
            coordinator.execute(
                self.package,
                review_run_id=review_run,
                review_task_id=review_task,
            )
        self.assertEqual(model.requests, [])
        self.assertEqual(self.store.list_contract_ids(), ())
        self.assertEqual(self.runtime.list_verifications("RUN", review_run), [])

    def test_run_must_belong_to_supplied_review_task(self) -> None:
        first_task, first_run = self._review_run()
        second_task, _ = self._review_run()
        model = FakeReviewerModel(self._payload())
        coordinator = ReviewerRunCoordinator(self.runtime, model, store=self.store)
        with self.assertRaisesRegex(ReviewerRunError, "does not belong"):
            coordinator.execute(
                self.package,
                review_run_id=first_run,
                review_task_id=second_task,
            )
        self.assertEqual(model.requests, [])
        self.assertEqual(self.store.list_contract_ids(), ())

    def test_model_failure_keeps_frozen_input_but_not_trusted_report_and_records_failure(self) -> None:
        review_task, review_run = self._review_run()
        model = FakeReviewerModel({"findings": []}, input_tokens=None)
        coordinator = ReviewerRunCoordinator(
            self.runtime,
            model,
            store=self.store,
            evidence_store=self.evidence_store,
        )
        with self.assertRaisesRegex(Exception, "input_tokens"):
            coordinator.execute(
                self.package,
                review_run_id=review_run,
                review_task_id=review_task,
            )
        self.assertEqual(self.store.load_contract(self.contract.contract_id), self.contract)
        self.assertEqual(self.evidence_store.load(self.contract.contract_id), self.package)
        self.assertEqual(self.store.list_report_ids(), ())
        self.assertEqual(self.store.list_audit_ids(), ())
        records = self.runtime.list_verifications("RUN", review_run)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "FAIL")
        evidence = json.loads(records[0]["evidence_json"])
        self.assertEqual(evidence["contract_id"], self.contract.contract_id)
        self.assertEqual(evidence["evidence_package_hash"], self.package.content_hash)
        self.assertFalse(evidence["semantic_findings_verified"])
        self.assertFalse(evidence["production_verification_changed"])
        self.assertEqual(self.runtime.get_run(review_run)["status"], RunStatus.RUNNING.value)

    def test_missing_parent_task_fails_before_input_persistence(self) -> None:
        missing_task = new_id(IdKind.TASK)
        payload = {"id": missing_task, "status": "SUCCEEDED"}
        ref = SpecialistEvidenceRef(
            missing_task,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=missing_task,
            objective="Review missing parent",
            evidence_refs=(ref,),
        )
        package = SpecialistEvidencePackage(
            contract,
            (SpecialistEvidenceRecord(ref, payload),),
        )
        review_task, review_run = self._review_run()
        coordinator = ReviewerRunCoordinator(
            self.runtime,
            FakeReviewerModel({"findings": []}),
            store=self.store,
        )
        with self.assertRaisesRegex(ReviewerRunError, "parent Task does not exist"):
            coordinator.execute(
                package,
                review_run_id=review_run,
                review_task_id=review_task,
            )
        self.assertEqual(self.store.list_contract_ids(), ())

    def test_coordinator_has_no_run_task_or_production_mutation_surface(self) -> None:
        coordinator = ReviewerRunCoordinator(
            self.runtime,
            FakeReviewerModel({"findings": []}),
            store=self.store,
        )
        for forbidden in (
            "finish_run",
            "transition_task",
            "verify_task",
            "apply",
            "patch",
            "write_source",
            "merge",
            "promote",
            "delegate",
        ):
            self.assertFalse(hasattr(coordinator, forbidden))


if __name__ == "__main__":
    unittest.main()
