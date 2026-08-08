from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .reviewer_audit import ReviewerAuditStatus
from .reviewer_run import ReviewerRunResult
from .specialist_evidence import SpecialistEvidencePackage
from .specialist_models import ReviewerCategory, ReviewerSeverity


_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROTOCOL_ID = "paired-isolated-reviewer-v1"
_MAX_EXPECTED_ISSUES = 64
_MAX_DESCRIPTION_CHARS = 4096


class ReviewerEvaluationError(RuntimeError):
    pass


class ReviewerComparisonVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


_SEVERITY_ORDER = {
    ReviewerSeverity.INFO: 0,
    ReviewerSeverity.LOW: 1,
    ReviewerSeverity.MEDIUM: 2,
    ReviewerSeverity.HIGH: 3,
    ReviewerSeverity.CRITICAL: 4,
}


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewerEvaluationError("Reviewer evaluation data must be finite JSON") from exc


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return empty if denominator == 0 else numerator / denominator


@dataclass(frozen=True)
class ExpectedReviewerIssue:
    issue_id: str
    category: ReviewerCategory
    minimum_severity: ReviewerSeverity
    evidence_ref_ids: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        if not _CASE_ID_RE.fullmatch(self.issue_id):
            raise ReviewerEvaluationError(f"invalid Reviewer expected issue_id: {self.issue_id!r}")
        if not isinstance(self.category, ReviewerCategory):
            raise ReviewerEvaluationError("expected issue category must be ReviewerCategory")
        if not isinstance(self.minimum_severity, ReviewerSeverity):
            raise ReviewerEvaluationError("expected issue minimum_severity must be ReviewerSeverity")
        refs = tuple(self.evidence_ref_ids)
        if not refs or any(not isinstance(item, str) or not item for item in refs):
            raise ReviewerEvaluationError("expected issue requires evidence_ref_ids")
        if len(refs) != len(set(refs)):
            raise ReviewerEvaluationError("expected issue evidence_ref_ids contains duplicates")
        object.__setattr__(self, "evidence_ref_ids", tuple(sorted(refs)))
        if not isinstance(self.description, str) or not self.description.strip():
            raise ReviewerEvaluationError("expected issue description must be non-empty")
        if len(self.description) > _MAX_DESCRIPTION_CHARS:
            raise ReviewerEvaluationError("expected issue description exceeds character limit")

    @property
    def signature(self) -> tuple[str, tuple[str, ...]]:
        return self.category.value, self.evidence_ref_ids

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "category": self.category.value,
            "minimum_severity": self.minimum_severity.value,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "description": self.description,
        }


@dataclass(frozen=True)
class ReviewerEvalCase:
    case_id: str
    contract_id: str
    contract_hash: str
    evidence_package_hash: str
    expected_issues: tuple[ExpectedReviewerIssue, ...] = ()
    max_false_positives: int = 0
    minimum_precision: float = 1.0

    def __post_init__(self) -> None:
        if not _CASE_ID_RE.fullmatch(self.case_id):
            raise ReviewerEvaluationError(f"invalid Reviewer eval case_id: {self.case_id!r}")
        if not all(isinstance(value, str) and value for value in (
            self.contract_id,
            self.contract_hash,
            self.evidence_package_hash,
        )):
            raise ReviewerEvaluationError("Reviewer eval case bindings must be non-empty strings")
        issues = tuple(self.expected_issues)
        if len(issues) > _MAX_EXPECTED_ISSUES:
            raise ReviewerEvaluationError("Reviewer eval expected issues exceeds count limit")
        if any(not isinstance(item, ExpectedReviewerIssue) for item in issues):
            raise ReviewerEvaluationError(
                "expected_issues must contain ExpectedReviewerIssue values"
            )
        ids = [item.issue_id for item in issues]
        signatures = [item.signature for item in issues]
        if len(ids) != len(set(ids)):
            raise ReviewerEvaluationError("Reviewer eval expected issue IDs contain duplicates")
        if len(signatures) != len(set(signatures)):
            raise ReviewerEvaluationError(
                "Reviewer eval expected issue signatures must be unique"
            )
        object.__setattr__(self, "expected_issues", tuple(sorted(issues, key=lambda item: item.issue_id)))
        if (
            not isinstance(self.max_false_positives, int)
            or isinstance(self.max_false_positives, bool)
            or self.max_false_positives < 0
        ):
            raise ReviewerEvaluationError("max_false_positives must be a non-negative integer")
        if (
            not isinstance(self.minimum_precision, (int, float))
            or isinstance(self.minimum_precision, bool)
            or not math.isfinite(float(self.minimum_precision))
            or not 0.0 <= float(self.minimum_precision) <= 1.0
        ):
            raise ReviewerEvaluationError("minimum_precision must be between 0 and 1")

    @classmethod
    def create(
        cls,
        case_id: str,
        package: SpecialistEvidencePackage,
        *,
        expected_issues: Iterable[ExpectedReviewerIssue] = (),
        max_false_positives: int = 0,
        minimum_precision: float = 1.0,
    ) -> "ReviewerEvalCase":
        return cls(
            case_id=case_id,
            contract_id=package.contract.contract_id,
            contract_hash=package.contract.content_hash,
            evidence_package_hash=package.content_hash,
            expected_issues=tuple(expected_issues),
            max_false_positives=max_false_positives,
            minimum_precision=minimum_precision,
        )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "evidence_package_hash": self.evidence_package_hash,
            "expected_issues": [item.to_dict() for item in self.expected_issues],
            "max_false_positives": self.max_false_positives,
            "minimum_precision": float(self.minimum_precision),
        }

    @property
    def content_hash(self) -> str:
        return _hash(self.canonical_dict())


@dataclass(frozen=True)
class ReviewerDetectionMetrics:
    expected_issues: int
    true_positives: int
    false_positives: int
    false_negatives: int
    critical_misses: int
    severity_underestimates: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_issues": self.expected_issues,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "critical_misses": self.critical_misses,
            "severity_underestimates": self.severity_underestimates,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass(frozen=True)
class ReviewerVariantSummary:
    variant_id: str
    metrics: ReviewerDetectionMetrics
    model_calls: int
    input_tokens: int
    output_tokens: int
    duration_ms: int
    context_bytes: int
    resource_cost_units: float | None = None
    downstream_repair_success: bool | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.model_calls, "model_calls"),
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
            (self.duration_ms, "duration_ms"),
            (self.context_bytes, "context_bytes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ReviewerEvaluationError(f"Reviewer variant {name} must be non-negative")
        if self.resource_cost_units is not None and (
            not isinstance(self.resource_cost_units, (int, float))
            or isinstance(self.resource_cost_units, bool)
            or not math.isfinite(float(self.resource_cost_units))
            or float(self.resource_cost_units) < 0.0
        ):
            raise ReviewerEvaluationError("resource_cost_units must be finite and non-negative")
        if self.downstream_repair_success is not None and not isinstance(
            self.downstream_repair_success, bool
        ):
            raise ReviewerEvaluationError("downstream_repair_success must be bool or null")

    def to_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "metrics": self.metrics.to_dict(),
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "context_bytes": self.context_bytes,
            "resource_cost_units": self.resource_cost_units,
            "downstream_repair_success": self.downstream_repair_success,
        }


@dataclass(frozen=True)
class ReviewerCaseComparison:
    case_id: str
    case_hash: str
    baseline: ReviewerVariantSummary
    reviewer: ReviewerVariantSummary
    verdict: ReviewerComparisonVerdict

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "case_hash": self.case_hash,
            "baseline": self.baseline.to_dict(),
            "reviewer": self.reviewer.to_dict(),
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True)
class ReviewerBenchmarkReport:
    protocol_id: str
    comparisons: tuple[ReviewerCaseComparison, ...]
    overall_verdict: ReviewerComparisonVerdict

    @property
    def total_true_positives(self) -> int:
        return sum(item.reviewer.metrics.true_positives for item in self.comparisons)

    @property
    def total_false_positives(self) -> int:
        return sum(item.reviewer.metrics.false_positives for item in self.comparisons)

    @property
    def total_false_negatives(self) -> int:
        return sum(item.reviewer.metrics.false_negatives for item in self.comparisons)

    @property
    def total_critical_misses(self) -> int:
        return sum(item.reviewer.metrics.critical_misses for item in self.comparisons)

    @property
    def repair_outcomes_known(self) -> int:
        return sum(
            item.reviewer.downstream_repair_success is not None for item in self.comparisons
        )

    @property
    def repair_success_rate(self) -> float | None:
        values = [
            item.reviewer.downstream_repair_success
            for item in self.comparisons
            if item.reviewer.downstream_repair_success is not None
        ]
        if not values:
            return None
        return sum(bool(value) for value in values) / len(values)

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value = {
            "protocol_id": self.protocol_id,
            "overall_verdict": self.overall_verdict.value,
            "total_true_positives": self.total_true_positives,
            "total_false_positives": self.total_false_positives,
            "total_false_negatives": self.total_false_negatives,
            "total_critical_misses": self.total_critical_misses,
            "repair_outcomes_known": self.repair_outcomes_known,
            "repair_success_rate": self.repair_success_rate,
            "comparisons": [item.to_dict() for item in self.comparisons],
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value


def _metrics_for_findings(case: ReviewerEvalCase, findings) -> ReviewerDetectionMetrics:
    expected_by_signature = {item.signature: item for item in case.expected_issues}
    matched: set[str] = set()
    false_positives = 0
    severity_underestimates = 0

    for finding in findings:
        signature = (
            finding.category.value,
            tuple(sorted(item.ref_id for item in finding.evidence_refs)),
        )
        expected = expected_by_signature.get(signature)
        if expected is None or expected.issue_id in matched:
            false_positives += 1
            continue
        if _SEVERITY_ORDER[finding.severity] < _SEVERITY_ORDER[expected.minimum_severity]:
            severity_underestimates += 1
            false_positives += 1
            continue
        matched.add(expected.issue_id)

    true_positives = len(matched)
    false_negatives = len(case.expected_issues) - true_positives
    critical_misses = sum(
        item.minimum_severity == ReviewerSeverity.CRITICAL and item.issue_id not in matched
        for item in case.expected_issues
    )
    precision = _ratio(
        true_positives,
        true_positives + false_positives,
        empty=1.0,
    )
    recall = _ratio(true_positives, len(case.expected_issues), empty=1.0)
    f1 = (
        0.0
        if precision + recall == 0.0
        else 2.0 * precision * recall / (precision + recall)
    )
    return ReviewerDetectionMetrics(
        expected_issues=len(case.expected_issues),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        critical_misses=critical_misses,
        severity_underestimates=severity_underestimates,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _verdict(
    case: ReviewerEvalCase,
    baseline: ReviewerDetectionMetrics,
    reviewer: ReviewerDetectionMetrics,
) -> ReviewerComparisonVerdict:
    if reviewer.false_positives > case.max_false_positives:
        return ReviewerComparisonVerdict.REGRESSED
    if reviewer.precision < float(case.minimum_precision):
        return ReviewerComparisonVerdict.REGRESSED
    if reviewer.critical_misses > baseline.critical_misses:
        return ReviewerComparisonVerdict.REGRESSED
    if (
        reviewer.true_positives > baseline.true_positives
        or reviewer.critical_misses < baseline.critical_misses
    ):
        return ReviewerComparisonVerdict.IMPROVED
    if (
        reviewer.true_positives == baseline.true_positives
        and reviewer.false_positives == baseline.false_positives
        and reviewer.false_negatives == baseline.false_negatives
        and reviewer.critical_misses == baseline.critical_misses
    ):
        return ReviewerComparisonVerdict.EQUIVALENT
    return ReviewerComparisonVerdict.INCONCLUSIVE


def evaluate_reviewer_case(
    case: ReviewerEvalCase,
    package: SpecialistEvidencePackage,
    result: ReviewerRunResult,
    *,
    duration_ms: int = 0,
    resource_cost_units: float | None = None,
    downstream_repair_success: bool | None = None,
) -> ReviewerCaseComparison:
    if not isinstance(case, ReviewerEvalCase):
        raise TypeError("case must be a ReviewerEvalCase")
    if not isinstance(package, SpecialistEvidencePackage):
        raise TypeError("package must be a SpecialistEvidencePackage")
    if not isinstance(result, ReviewerRunResult):
        raise TypeError("result must be a ReviewerRunResult")
    if (
        case.contract_id != package.contract.contract_id
        or case.contract_hash != package.contract.content_hash
        or case.evidence_package_hash != package.content_hash
    ):
        raise ReviewerEvaluationError("Reviewer eval case does not bind exact frozen package")
    if result.audit.status != ReviewerAuditStatus.STRUCTURALLY_VALID:
        raise ReviewerEvaluationError("Reviewer evaluation requires structurally valid audit")
    if result.audit.report_id != result.review.report.report_id:
        raise ReviewerEvaluationError("Reviewer audit does not bind evaluated report ID")
    if result.audit.report_hash != result.review.report.content_hash:
        raise ReviewerEvaluationError("Reviewer audit does not bind evaluated report hash")
    if result.audit.contract_id != case.contract_id or result.audit.contract_hash != case.contract_hash:
        raise ReviewerEvaluationError("Reviewer audit does not bind eval contract")
    if result.audit.evidence_package_hash != case.evidence_package_hash:
        raise ReviewerEvaluationError("Reviewer audit does not bind eval evidence package")

    allowed_refs = {item.ref_id for item in package.contract.evidence_refs}
    for issue in case.expected_issues:
        if not set(issue.evidence_ref_ids).issubset(allowed_refs):
            raise ReviewerEvaluationError(
                f"expected issue {issue.issue_id} cites evidence outside eval package"
            )

    baseline_metrics = _metrics_for_findings(case, ())
    reviewer_metrics = _metrics_for_findings(case, result.review.report.findings)
    context_bytes = len(_canonical_bytes(package.to_dict()))
    baseline = ReviewerVariantSummary(
        variant_id="baseline-no-specialist",
        metrics=baseline_metrics,
        model_calls=0,
        input_tokens=0,
        output_tokens=0,
        duration_ms=0,
        context_bytes=0,
        resource_cost_units=0.0,
        downstream_repair_success=None,
    )
    reviewer = ReviewerVariantSummary(
        variant_id="isolated-reviewer",
        metrics=reviewer_metrics,
        model_calls=1,
        input_tokens=result.review.input_tokens,
        output_tokens=result.review.output_tokens,
        duration_ms=duration_ms,
        context_bytes=context_bytes,
        resource_cost_units=resource_cost_units,
        downstream_repair_success=downstream_repair_success,
    )
    return ReviewerCaseComparison(
        case_id=case.case_id,
        case_hash=case.content_hash,
        baseline=baseline,
        reviewer=reviewer,
        verdict=_verdict(case, baseline_metrics, reviewer_metrics),
    )


def build_reviewer_benchmark(
    comparisons: Iterable[ReviewerCaseComparison],
) -> ReviewerBenchmarkReport:
    values = tuple(comparisons)
    if not values:
        raise ReviewerEvaluationError("Reviewer benchmark requires at least one case")
    if any(not isinstance(item, ReviewerCaseComparison) for item in values):
        raise TypeError("comparisons must contain ReviewerCaseComparison values")
    case_ids = [item.case_id for item in values]
    if len(case_ids) != len(set(case_ids)):
        raise ReviewerEvaluationError("Reviewer benchmark contains duplicate case IDs")
    ordered = tuple(sorted(values, key=lambda item: item.case_id))
    verdicts = {item.verdict for item in ordered}
    if ReviewerComparisonVerdict.REGRESSED in verdicts:
        overall = ReviewerComparisonVerdict.REGRESSED
    elif ReviewerComparisonVerdict.INCONCLUSIVE in verdicts:
        overall = ReviewerComparisonVerdict.INCONCLUSIVE
    elif ReviewerComparisonVerdict.IMPROVED in verdicts:
        overall = ReviewerComparisonVerdict.IMPROVED
    else:
        overall = ReviewerComparisonVerdict.EQUIVALENT
    return ReviewerBenchmarkReport(
        protocol_id=_PROTOCOL_ID,
        comparisons=ordered,
        overall_verdict=overall,
    )
