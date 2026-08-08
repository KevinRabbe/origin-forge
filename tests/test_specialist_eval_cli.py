from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer import ReviewerResult
from origin_forge.reviewer_audit import ReviewerReportAuditor
from origin_forge.reviewer_eval_store import ReviewerEvalStore
from origin_forge.reviewer_evaluation import (
    ExpectedReviewerIssue,
    ReviewerEvalCase,
    build_reviewer_benchmark,
    evaluate_reviewer_case,
)
from origin_forge.reviewer_run import ReviewerRunResult
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_cli import main
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


class SpecialistEvalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("specialist-eval-cli-test")
        self.store = SpecialistStore(self.runtime)
        self.evidence_store = SpecialistEvidenceStore(self.store)
        self.eval_store = ReviewerEvalStore(self.store, self.evidence_store)

        task_id = new_id(IdKind.TASK)
        payload = {"id": task_id, "status": "SUCCEEDED", "objective": "Eval CLI"}
        ref = SpecialistEvidenceRef(
            task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=task_id,
            objective="Evaluate read-only CLI",
            evidence_refs=(ref,),
        )
        package = SpecialistEvidencePackage(
            contract,
            (SpecialistEvidenceRecord(ref, payload),),
        )
        self.store.put_contract(contract)
        self.evidence_store.put(package)
        issue = ExpectedReviewerIssue(
            issue_id="known-gap",
            category=ReviewerCategory.TEST_GAP,
            minimum_severity=ReviewerSeverity.MEDIUM,
            evidence_ref_ids=(task_id,),
            description="Known eval issue",
        )
        self.case = ReviewerEvalCase.create(
            "cli-case",
            package,
            expected_issues=(issue,),
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.MEDIUM,
            category=ReviewerCategory.TEST_GAP,
            summary="Found eval issue.",
            evidence_refs=(ref,),
            recommendation="Use a separate governed Task.",
        )
        report = ReviewerReport.create(
            contract=contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        audit = ReviewerReportAuditor().audit(report, package)
        result = ReviewerRunResult(
            review=ReviewerResult(
                report=report,
                model_id="reviewer-model",
                model_hash=None,
                input_tokens=10,
                output_tokens=5,
                context_hash="sha256:" + "c" * 64,
                response_hash="sha256:" + "d" * 64,
            ),
            audit=audit,
            verification_id=new_id(IdKind.VERIFICATION),
        )
        comparison = evaluate_reviewer_case(self.case, package, result)
        self.benchmark = build_reviewer_benchmark((comparison,))
        self.report_id = self.eval_store.report_id(self.benchmark)
        self.eval_store.put_case(self.case)
        self.eval_store.put_report(self.benchmark)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_eval_case_and_report_are_visible_read_only(self) -> None:
        code, payload = self._call("eval-case-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["eval_cases"], [self.case.case_id])
        code, payload = self._call("eval-case-show", self.case.case_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], self.case.content_hash)
        self.assertEqual(payload["case"]["case_id"], self.case.case_id)

        code, payload = self._call("eval-report-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["eval_reports"], [self.report_id])
        code, payload = self._call("eval-report-show", self.report_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], self.benchmark.content_hash)
        self.assertEqual(payload["overall_verdict"], "IMPROVED")

        code, payload = self._call("eval-report-status", self.report_id)
        self.assertEqual(code, 0)
        self.assertTrue(payload["replayable"])
        self.assertEqual(payload["stale_case_ids"], [])
        self.assertEqual(payload["stale_binding_case_ids"], [])

    def test_stale_eval_report_status_returns_nonzero_without_mutating(self) -> None:
        before_reports = self.eval_store.list_report_ids()
        (self.eval_store.cases_dir / f"{self.case.case_id}.json").unlink()
        code, payload = self._call("eval-report-status", self.report_id)
        self.assertEqual(code, 4)
        self.assertFalse(payload["replayable"])
        self.assertEqual(payload["stale_case_ids"], [self.case.case_id])
        self.assertEqual(self.eval_store.list_report_ids(), before_reports)


if __name__ == "__main__":
    unittest.main()
