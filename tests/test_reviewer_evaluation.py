from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer import ReviewerResult
from origin_forge.reviewer_audit import ReviewerReportAuditor
from origin_forge.reviewer_evaluation import (
    ExpectedReviewerIssue,
    ReviewerComparisonVerdict,
    ReviewerEvalCase,
    ReviewerEvaluationError,
    build_reviewer_benchmark,
    evaluate_reviewer_case,
)
from origin_forge.reviewer_run import ReviewerRunResult
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
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


class ReviewerEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task_id = new_id(IdKind.TASK)
        payload = {"id": self.task_id, "status": "SUCCEEDED", "objective": "Evaluate"}
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review eval fixture",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(
            self.contract,
            (SpecialistEvidenceRecord(self.ref, payload),),
        )

    def _result(self, findings=(), *, input_tokens=100, output_tokens=25):
        report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-eval-model",
            model_hash="sha256:" + "f" * 64,
            findings=findings,
        )
        audit = ReviewerReportAuditor().audit(report, self.package)
        review = ReviewerResult(
            report=report,
            model_id="reviewer-eval-model",
            model_hash="sha256:" + "f" * 64,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_hash="sha256:" + "c" * 64,
            response_hash="sha256:" + "d" * 64,
        )
        return ReviewerRunResult(
            review=review,
            audit=audit,
            verification_id=new_id(IdKind.VERIFICATION),
        )

    def _issue(
        self,
        *,
        issue_id="issue-1",
        category=ReviewerCategory.TEST_GAP,
        severity=ReviewerSeverity.HIGH,
    ):
        return ExpectedReviewerIssue(
            issue_id=issue_id,
            category=category,
            minimum_severity=severity,
            evidence_ref_ids=(self.task_id,),
            description="Known labeled issue",
        )

    def _finding(
        self,
        *,
        category=ReviewerCategory.TEST_GAP,
        severity=ReviewerSeverity.HIGH,
    ):
        return ReviewerFinding.create(
            severity=severity,
            category=category,
            summary="Detected labeled issue.",
            evidence_refs=(self.ref,),
            recommendation="Route a separate governed repair Task.",
        )

    def test_exact_detection_improves_over_no_specialist_baseline(self) -> None:
        case = ReviewerEvalCase.create(
            "detect-test-gap",
            self.package,
            expected_issues=(self._issue(),),
        )
        comparison = evaluate_reviewer_case(
            case,
            self.package,
            self._result((self._finding(),)),
            duration_ms=250,
            resource_cost_units=1.5,
            downstream_repair_success=True,
        )
        self.assertEqual(comparison.verdict, ReviewerComparisonVerdict.IMPROVED)
        self.assertEqual(comparison.baseline.metrics.true_positives, 0)
        self.assertEqual(comparison.baseline.metrics.false_negatives, 1)
        self.assertEqual(comparison.reviewer.metrics.true_positives, 1)
        self.assertEqual(comparison.reviewer.metrics.false_positives, 0)
        self.assertEqual(comparison.reviewer.metrics.false_negatives, 0)
        self.assertEqual(comparison.reviewer.metrics.precision, 1.0)
        self.assertEqual(comparison.reviewer.metrics.recall, 1.0)
        self.assertEqual(comparison.reviewer.metrics.f1, 1.0)
        self.assertEqual(comparison.reviewer.model_calls, 1)
        self.assertEqual(comparison.reviewer.input_tokens, 100)
        self.assertEqual(comparison.reviewer.output_tokens, 25)
        self.assertEqual(comparison.reviewer.duration_ms, 250)
        self.assertGreater(comparison.reviewer.context_bytes, 0)
        self.assertEqual(comparison.reviewer.resource_cost_units, 1.5)
        self.assertTrue(comparison.reviewer.downstream_repair_success)

    def test_clean_case_empty_report_is_equivalent_and_false_positive_regresses(self) -> None:
        case = ReviewerEvalCase.create("clean-case", self.package)
        empty = evaluate_reviewer_case(case, self.package, self._result(()))
        self.assertEqual(empty.verdict, ReviewerComparisonVerdict.EQUIVALENT)
        self.assertEqual(empty.reviewer.metrics.precision, 1.0)
        self.assertEqual(empty.reviewer.metrics.recall, 1.0)
        self.assertEqual(empty.reviewer.metrics.false_positives, 0)

        noisy = evaluate_reviewer_case(
            case,
            self.package,
            self._result((self._finding(),)),
        )
        self.assertEqual(noisy.verdict, ReviewerComparisonVerdict.REGRESSED)
        self.assertEqual(noisy.reviewer.metrics.true_positives, 0)
        self.assertEqual(noisy.reviewer.metrics.false_positives, 1)
        self.assertEqual(noisy.reviewer.metrics.precision, 0.0)

    def test_wrong_category_is_false_positive_and_known_issue_remains_missed(self) -> None:
        case = ReviewerEvalCase.create(
            "wrong-category",
            self.package,
            expected_issues=(self._issue(),),
        )
        comparison = evaluate_reviewer_case(
            case,
            self.package,
            self._result(
                (self._finding(category=ReviewerCategory.MAINTAINABILITY),)
            ),
        )
        self.assertEqual(comparison.verdict, ReviewerComparisonVerdict.REGRESSED)
        self.assertEqual(comparison.reviewer.metrics.true_positives, 0)
        self.assertEqual(comparison.reviewer.metrics.false_positives, 1)
        self.assertEqual(comparison.reviewer.metrics.false_negatives, 1)

    def test_under_severity_does_not_count_as_correct_detection(self) -> None:
        case = ReviewerEvalCase.create(
            "under-severity",
            self.package,
            expected_issues=(self._issue(severity=ReviewerSeverity.CRITICAL),),
        )
        comparison = evaluate_reviewer_case(
            case,
            self.package,
            self._result((self._finding(severity=ReviewerSeverity.HIGH),)),
        )
        self.assertEqual(comparison.verdict, ReviewerComparisonVerdict.REGRESSED)
        self.assertEqual(comparison.reviewer.metrics.true_positives, 0)
        self.assertEqual(comparison.reviewer.metrics.false_positives, 1)
        self.assertEqual(comparison.reviewer.metrics.false_negatives, 1)
        self.assertEqual(comparison.reviewer.metrics.critical_misses, 1)
        self.assertEqual(comparison.reviewer.metrics.severity_underestimates, 1)

    def test_critical_issue_detection_reduces_critical_miss(self) -> None:
        issue = self._issue(severity=ReviewerSeverity.CRITICAL)
        case = ReviewerEvalCase.create(
            "critical",
            self.package,
            expected_issues=(issue,),
        )
        comparison = evaluate_reviewer_case(
            case,
            self.package,
            self._result((self._finding(severity=ReviewerSeverity.CRITICAL),)),
        )
        self.assertEqual(comparison.baseline.metrics.critical_misses, 1)
        self.assertEqual(comparison.reviewer.metrics.critical_misses, 0)
        self.assertEqual(comparison.verdict, ReviewerComparisonVerdict.IMPROVED)

    def test_expected_issue_signatures_must_be_unique(self) -> None:
        with self.assertRaisesRegex(
            ReviewerEvaluationError,
            "signatures must be unique",
        ):
            ReviewerEvalCase.create(
                "duplicate-signature",
                self.package,
                expected_issues=(
                    self._issue(issue_id="one"),
                    self._issue(issue_id="two"),
                ),
            )

    def test_expected_issue_must_reference_evidence_inside_package(self) -> None:
        outside = new_id(IdKind.TASK)
        issue = ExpectedReviewerIssue(
            issue_id="outside",
            category=ReviewerCategory.TEST_GAP,
            minimum_severity=ReviewerSeverity.MEDIUM,
            evidence_ref_ids=(outside,),
            description="Bad eval label",
        )
        case = ReviewerEvalCase.create(
            "outside-label",
            self.package,
            expected_issues=(issue,),
        )
        with self.assertRaisesRegex(ReviewerEvaluationError, "outside eval package"):
            evaluate_reviewer_case(case, self.package, self._result(()))

    def test_case_binding_prevents_scoring_against_different_frozen_package(self) -> None:
        case = ReviewerEvalCase.create("binding", self.package)
        other_task = new_id(IdKind.TASK)
        payload = {"id": other_task, "status": "SUCCEEDED"}
        ref = SpecialistEvidenceRef(
            other_task,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=other_task,
            objective="Other",
            evidence_refs=(ref,),
        )
        other = SpecialistEvidencePackage(
            contract,
            (SpecialistEvidenceRecord(ref, payload),),
        )
        with self.assertRaisesRegex(ReviewerEvaluationError, "exact frozen package"):
            evaluate_reviewer_case(case, other, self._result(()))

    def test_benchmark_is_regression_dominant_and_aggregates_repair_outcomes(self) -> None:
        issue_case = ReviewerEvalCase.create(
            "issue-case",
            self.package,
            expected_issues=(self._issue(),),
        )
        improved = evaluate_reviewer_case(
            issue_case,
            self.package,
            self._result((self._finding(),)),
            downstream_repair_success=True,
        )
        clean_case = ReviewerEvalCase.create("clean-case", self.package)
        regressed = evaluate_reviewer_case(
            clean_case,
            self.package,
            self._result((self._finding(),)),
            downstream_repair_success=False,
        )
        benchmark = build_reviewer_benchmark((improved, regressed))
        self.assertEqual(benchmark.overall_verdict, ReviewerComparisonVerdict.REGRESSED)
        self.assertEqual(benchmark.total_true_positives, 1)
        self.assertEqual(benchmark.total_false_positives, 1)
        self.assertEqual(benchmark.total_false_negatives, 0)
        self.assertEqual(benchmark.repair_outcomes_known, 2)
        self.assertEqual(benchmark.repair_success_rate, 0.5)
        self.assertTrue(benchmark.content_hash.startswith("sha256:"))
        self.assertEqual(benchmark.to_dict()["content_hash"], benchmark.content_hash)

    def test_benchmark_requires_unique_cases_and_at_least_one_case(self) -> None:
        with self.assertRaisesRegex(ReviewerEvaluationError, "at least one case"):
            build_reviewer_benchmark(())
        case = ReviewerEvalCase.create("same", self.package)
        comparison = evaluate_reviewer_case(case, self.package, self._result(()))
        with self.assertRaisesRegex(ReviewerEvaluationError, "duplicate case IDs"):
            build_reviewer_benchmark((comparison, comparison))


if __name__ == "__main__":
    unittest.main()
