from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from .reviewer import IsolatedReviewer, ReviewerError, ReviewerResult
from .reviewer_audit import ReviewerAuditReport, ReviewerAuditStatus, ReviewerReportAuditor
from .runtime import OriginForgeRuntime
from .specialist_evidence import SpecialistEvidencePackage
from .specialist_evidence_store import SpecialistEvidenceStore
from .specialist_store import SpecialistStore
from .state import RunStatus, TaskStatus
from .model import ModelAdapter


class ReviewerRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewerRunResult:
    review: ReviewerResult
    audit: ReviewerAuditReport
    verification_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "review": self.review.to_dict(),
            "audit": self.audit.to_dict(),
            "verification_id": self.verification_id,
            "semantic_findings_verified": False,
            "production_verification_changed": False,
        }


class ReviewerRunCoordinator:
    """Bind one isolated Reviewer invocation to an existing durable Reviewer Run.

    The coordinator persists the frozen input and structurally valid advisory
    report, records provenance on the Reviewer Run, and deliberately leaves Run
    and Task lifecycle transitions to the caller/orchestrator.
    """

    RUN_ROLE = "REVIEWER"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        *,
        store: SpecialistStore | None = None,
        evidence_store: SpecialistEvidenceStore | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store = store or SpecialistStore(runtime)
        if self.store.runtime.project_root != runtime.project_root:
            raise ReviewerRunError("SpecialistStore and runtime must belong to the same project")
        self.evidence_store = evidence_store or SpecialistEvidenceStore(self.store)
        if self.evidence_store.runtime.project_root != runtime.project_root:
            raise ReviewerRunError(
                "SpecialistEvidenceStore and runtime must belong to the same project"
            )
        self.reviewer = IsolatedReviewer(model)
        self.auditor = ReviewerReportAuditor()

    def _validate_run(self, review_run_id: str, review_task_id: str) -> dict[str, object]:
        try:
            run = self.runtime.get_run(review_run_id)
            task = self.runtime.get_task(review_task_id)
        except KeyError as exc:
            raise ReviewerRunError(
                "Reviewer execution requires an existing durable Run and Task"
            ) from exc
        if run["task_id"] != review_task_id:
            raise ReviewerRunError("Reviewer Run does not belong to supplied review Task")
        if run["status"] != RunStatus.RUNNING.value:
            raise ReviewerRunError("Reviewer Run must be RUNNING")
        if task["status"] != TaskStatus.RUNNING.value:
            raise ReviewerRunError("Reviewer Task must be RUNNING")
        if run["role"] != self.RUN_ROLE:
            raise ReviewerRunError("Reviewer Run role must be exactly REVIEWER")
        return run

    def _record_failure(
        self,
        *,
        review_run_id: str,
        package: SpecialistEvidencePackage,
        error: Exception,
    ) -> str:
        return self.runtime.record_verification(
            "RUN",
            review_run_id,
            verification_type="reviewer-structural-capture",
            verifier="origin-forge-reviewer-run",
            status="FAIL",
            evidence={
                "contract_id": package.contract.contract_id,
                "contract_hash": package.contract.content_hash,
                "evidence_package_hash": package.content_hash,
                "error_type": type(error).__name__,
                "error": str(error)[:4096],
                "semantic_findings_verified": False,
                "production_verification_changed": False,
            },
            run_id=review_run_id,
        )

    def _record_success(
        self,
        *,
        review_run_id: str,
        run: dict[str, object],
        package: SpecialistEvidencePackage,
        result: ReviewerResult,
        audit: ReviewerAuditReport,
    ) -> str:
        severity_counts = Counter(item.severity.value for item in result.report.findings)
        category_counts = Counter(item.category.value for item in result.report.findings)
        return self.runtime.record_verification(
            "RUN",
            review_run_id,
            verification_type="reviewer-structural-capture",
            verifier="origin-forge-reviewer-run",
            status="PASS",
            evidence={
                "contract_id": package.contract.contract_id,
                "contract_hash": package.contract.content_hash,
                "evidence_package_hash": package.content_hash,
                "parent_task_id": package.contract.parent_task_id,
                "model_profile": run["model_profile"],
                "model_id": result.model_id,
                "model_hash": result.model_hash,
                "context_hash": result.context_hash,
                "response_hash": result.response_hash,
                "report_id": result.report.report_id,
                "report_hash": result.report.content_hash,
                "overall_risk": result.report.overall_risk.value,
                "audit_id": self.store.audit_id(audit),
                "audit_hash": audit.content_hash,
                "audit_status": audit.status.value,
                "semantic_findings_verified": False,
                "production_verification_changed": False,
            },
            metrics={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "finding_count": len(result.report.findings),
                "severity_counts": dict(sorted(severity_counts.items())),
                "category_counts": dict(sorted(category_counts.items())),
            },
            run_id=review_run_id,
        )

    def execute(
        self,
        package: SpecialistEvidencePackage,
        *,
        review_run_id: str,
        review_task_id: str,
    ) -> ReviewerRunResult:
        if not isinstance(package, SpecialistEvidencePackage):
            raise TypeError("package must be a SpecialistEvidencePackage")
        run = self._validate_run(review_run_id, review_task_id)
        try:
            self.runtime.get_task(package.contract.parent_task_id)
        except KeyError as exc:
            raise ReviewerRunError("Reviewer contract parent Task does not exist") from exc

        # Persist the exact invocation input before the model call. This is
        # evidence capture, not production-state mutation.
        self.store.put_contract(package.contract)
        self.evidence_store.put(package)

        try:
            result = self.reviewer.review(package, run_id=review_run_id)
            audit = self.auditor.audit(result.report, package)
            if audit.status != ReviewerAuditStatus.STRUCTURALLY_VALID:
                raise ReviewerRunError(
                    "Reviewer report failed independent structural audit: "
                    + json.dumps(audit.to_dict(), sort_keys=True)
                )
            self.store.put_review(result.report, audit)
        except Exception as exc:
            self._record_failure(
                review_run_id=review_run_id,
                package=package,
                error=exc,
            )
            raise

        verification_id = self._record_success(
            review_run_id=review_run_id,
            run=run,
            package=package,
            result=result,
            audit=audit,
        )
        return ReviewerRunResult(
            review=result,
            audit=audit,
            verification_id=verification_id,
        )
