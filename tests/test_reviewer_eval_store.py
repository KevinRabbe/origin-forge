from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer import ReviewerResult
from origin_forge.reviewer_audit import ReviewerReportAuditor
from origin_forge.reviewer_eval_store import ReviewerEvalStore, ReviewerEvalStoreError
from origin_forge.reviewer_evaluation import (
    ExpectedReviewerIssue,
    ReviewerEvalCase,
    build_reviewer_benchmark,
    evaluate_reviewer_case,
)
from origin_forge.reviewer_run import ReviewerRunResult
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_evidence_store import SpecialistEvidenceStore
from origin_forge.specialist_models import (
    ReviewerCategory,
    ReviewerFinding,
    ReviewerReport,
    ReviewerSeverity,
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)
from origin_forge.specialist_store import SpecialistStore


class ReviewerEvalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("reviewer-eval-store-test")
        self.store = SpecialistStore(self.runtime)
        self.evidence_store = SpecialistEvidenceStore(self.store)
        self.eval_store = ReviewerEvalStore(self.store, self.evidence_store)

        self.task_id = new_id(IdKind.TASK)
        payload = {"id": self.task_id, "status": "SUCCEEDED", "objective": "Eval"}
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Evaluate Reviewer",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(
            self.contract,
            (SpecialistEvidenceRecord(self.ref, payload),),
        )
        self.store.put_contract(self.contract)
        self.evidence_store.put(self.package)

        self.issue = ExpectedReviewerIssue(
            issue_id="known-gap",
            category=ReviewerCategory.TEST_GAP,
            minimum_severity=ReviewerSeverity.HIGH,
            evidence_ref_ids=(self.task_id,),
            description="Known missing edge-case coverage",
        )
        self.case = ReviewerEvalCase.create(
            "case-known-gap",
            self.package,
            expected_issues=(self.issue,),
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.TEST_GAP,
            summary="Detected missing coverage.",
            evidence_refs=(self.ref,),
            recommendation="Create a separate governed test Task.",
        )
        report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-eval-model",
            model_hash="sha256:" + "f" * 64,
            findings=(finding,),
        )
        audit = ReviewerReportAuditor().audit(report, self.package)
        result = ReviewerRunResult(
            review=ReviewerResult(
                report=report,
                model_id="reviewer-eval-model",
                model_hash="sha256:" + "f" * 64,
                input_tokens=100,
                output_tokens=25,
                context_hash="sha256:" + "c" * 64,
                response_hash="sha256:" + "d" * 64,
            ),
            audit=audit,
            verification_id=new_id(IdKind.VERIFICATION),
        )
        self.comparison = evaluate_reviewer_case(
            self.case,
            self.package,
            result,
            duration_ms=50,
        )
        self.benchmark = build_reviewer_benchmark((self.comparison,))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_case_and_content_addressed_report_round_trip(self) -> None:
        case_path = self.eval_store.put_case(self.case)
        report_path = self.eval_store.put_report(self.benchmark)
        report_id = self.eval_store.report_id(self.benchmark)
        self.assertTrue(case_path.is_file())
        self.assertTrue(report_path.is_file())
        self.assertEqual(self.eval_store.load_case(self.case.case_id), self.case)
        loaded = self.eval_store.load_report(report_id)
        self.assertEqual(loaded.content_hash, self.benchmark.content_hash)
        self.assertEqual(loaded.payload, self.benchmark.to_dict())
        self.assertEqual(self.eval_store.list_case_ids(), (self.case.case_id,))
        self.assertEqual(self.eval_store.list_report_ids(), (report_id,))
        status = self.eval_store.inspect_replay(report_id)
        self.assertTrue(status.replayable)
        self.assertEqual(status.stale_case_ids, ())
        self.assertEqual(status.stale_binding_case_ids, ())

        # Rewrites of identical immutable objects are idempotent.
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)
        self.assertEqual(self.eval_store.list_report_ids(), (report_id,))

    def test_case_requires_current_trusted_contract_and_evidence_bindings(self) -> None:
        other_store = SpecialistStore(self.runtime)
        empty_evidence = SpecialistEvidenceStore(other_store)
        isolated = ReviewerEvalStore(other_store, empty_evidence)
        # Remove frozen package to make the binding unavailable.
        package_path = self.evidence_store.directory / f"{self.contract.contract_id}.json"
        package_path.unlink()
        with self.assertRaisesRegex(ReviewerEvalStoreError, "bindings are unavailable"):
            isolated.put_case(self.case)

    def test_case_id_is_immutable(self) -> None:
        self.eval_store.put_case(self.case)
        changed = ReviewerEvalCase(
            case_id=self.case.case_id,
            contract_id=self.case.contract_id,
            contract_hash=self.case.contract_hash,
            evidence_package_hash=self.case.evidence_package_hash,
            expected_issues=(),
            max_false_positives=0,
            minimum_precision=1.0,
        )
        with self.assertRaisesRegex(ReviewerEvalStoreError, "immutable and already exists"):
            self.eval_store.put_case(changed)

    def test_report_requires_stored_exact_cases(self) -> None:
        with self.assertRaises(KeyError):
            self.eval_store.put_report(self.benchmark)
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)

    def test_case_and_report_tampering_is_detected(self) -> None:
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)
        case_path = self.eval_store.cases_dir / f"{self.case.case_id}.json"
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        raw["payload"]["minimum_precision"] = 0.5
        case_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ReviewerEvalStoreError, "content hash mismatch"):
            self.eval_store.load_case(self.case.case_id)

        report_id = self.eval_store.report_id(self.benchmark)
        report_path = self.eval_store.reports_dir / f"{report_id}.json"
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        raw["payload"]["total_true_positives"] = 999
        report_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ReviewerEvalStoreError, "content hash mismatch"):
            self.eval_store.load_report(report_id)

    def test_replay_detects_missing_case(self) -> None:
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)
        report_id = self.eval_store.report_id(self.benchmark)
        (self.eval_store.cases_dir / f"{self.case.case_id}.json").unlink()
        status = self.eval_store.inspect_replay(report_id)
        self.assertFalse(status.replayable)
        self.assertEqual(status.stale_case_ids, (self.case.case_id,))
        self.assertEqual(status.stale_binding_case_ids, ())

    def test_replay_detects_missing_or_changed_frozen_binding(self) -> None:
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)
        report_id = self.eval_store.report_id(self.benchmark)
        (self.evidence_store.directory / f"{self.contract.contract_id}.json").unlink()
        status = self.eval_store.inspect_replay(report_id)
        self.assertFalse(status.replayable)
        self.assertEqual(status.stale_case_ids, ())
        self.assertEqual(status.stale_binding_case_ids, (self.case.case_id,))

    def test_eval_store_has_no_promotion_or_production_integration_surface(self) -> None:
        for forbidden in (
            "promote",
            "enable_default_reviewer",
            "change_policy",
            "transition_task",
            "apply",
            "patch",
            "merge",
        ):
            self.assertFalse(hasattr(self.eval_store, forbidden))


if __name__ == "__main__":
    unittest.main()
