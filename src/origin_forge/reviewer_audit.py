from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .specialist_evidence import SpecialistEvidencePackage
from .specialist_models import ReviewerReport, SpecialistRole


class ReviewerAuditError(RuntimeError):
    pass


class ReviewerAuditStatus(StrEnum):
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    REJECTED = "REJECTED"


class ReviewerAuditFindingCode(StrEnum):
    WRONG_ROLE = "WRONG_ROLE"
    CONTRACT_ID_MISMATCH = "CONTRACT_ID_MISMATCH"
    CONTRACT_HASH_MISMATCH = "CONTRACT_HASH_MISMATCH"
    EVIDENCE_OUTSIDE_CONTRACT = "EVIDENCE_OUTSIDE_CONTRACT"
    EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"
    EVIDENCE_KIND_MISMATCH = "EVIDENCE_KIND_MISMATCH"


@dataclass(frozen=True)
class ReviewerAuditFinding:
    code: ReviewerAuditFindingCode
    message: str
    finding_id: str | None = None
    evidence_ref_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ReviewerAuditFindingCode):
            raise ReviewerAuditError("audit finding code must be a ReviewerAuditFindingCode")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ReviewerAuditError("audit finding message must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "finding_id": self.finding_id,
            "evidence_ref_id": self.evidence_ref_id,
        }


@dataclass(frozen=True)
class ReviewerAuditReport:
    report_id: str
    report_hash: str
    contract_id: str
    contract_hash: str
    evidence_package_hash: str
    status: ReviewerAuditStatus
    findings: tuple[ReviewerAuditFinding, ...]
    semantic_findings_verified: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReviewerAuditStatus):
            raise ReviewerAuditError("audit status must be a ReviewerAuditStatus")
        values = tuple(self.findings)
        if any(not isinstance(item, ReviewerAuditFinding) for item in values):
            raise ReviewerAuditError("audit findings must contain ReviewerAuditFinding values")
        object.__setattr__(self, "findings", values)
        if self.semantic_findings_verified is not False:
            raise ReviewerAuditError("structural Reviewer audit cannot verify semantic findings")
        expected = ReviewerAuditStatus.STRUCTURALLY_VALID if not values else ReviewerAuditStatus.REJECTED
        if self.status != expected:
            raise ReviewerAuditError("audit status must be derived from structural findings")

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(
            {
                "report_id": self.report_id,
                "report_hash": self.report_hash,
                "contract_id": self.contract_id,
                "contract_hash": self.contract_hash,
                "evidence_package_hash": self.evidence_package_hash,
                "status": self.status.value,
                "findings": [item.to_dict() for item in self.findings],
                "semantic_findings_verified": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "report_hash": self.report_hash,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "evidence_package_hash": self.evidence_package_hash,
            "status": self.status.value,
            "findings": [item.to_dict() for item in self.findings],
            "semantic_findings_verified": False,
            "content_hash": self.content_hash,
        }


class ReviewerReportAuditor:
    """Read-only structural audit of a Reviewer report against frozen evidence."""

    def audit(
        self,
        report: ReviewerReport,
        package: SpecialistEvidencePackage,
    ) -> ReviewerAuditReport:
        if not isinstance(report, ReviewerReport):
            raise TypeError("report must be a ReviewerReport")
        if not isinstance(package, SpecialistEvidencePackage):
            raise TypeError("package must be a SpecialistEvidencePackage")

        findings: list[ReviewerAuditFinding] = []
        contract = package.contract
        if contract.role != SpecialistRole.REVIEWER:
            findings.append(
                ReviewerAuditFinding(
                    ReviewerAuditFindingCode.WRONG_ROLE,
                    "frozen specialist contract role is not REVIEWER",
                )
            )
        if report.contract_id != contract.contract_id:
            findings.append(
                ReviewerAuditFinding(
                    ReviewerAuditFindingCode.CONTRACT_ID_MISMATCH,
                    "Reviewer report contract ID does not match frozen package",
                )
            )
        if report.contract_hash != contract.content_hash:
            findings.append(
                ReviewerAuditFinding(
                    ReviewerAuditFindingCode.CONTRACT_HASH_MISMATCH,
                    "Reviewer report contract hash does not match frozen package",
                )
            )

        contract_refs = {item.ref_id: item for item in contract.evidence_refs}
        for review_finding in report.findings:
            for cited in review_finding.evidence_refs:
                frozen = contract_refs.get(cited.ref_id)
                if frozen is None:
                    findings.append(
                        ReviewerAuditFinding(
                            ReviewerAuditFindingCode.EVIDENCE_OUTSIDE_CONTRACT,
                            "Reviewer finding cites evidence outside the frozen contract",
                            finding_id=review_finding.finding_id,
                            evidence_ref_id=cited.ref_id,
                        )
                    )
                    continue
                if cited.content_hash != frozen.content_hash:
                    findings.append(
                        ReviewerAuditFinding(
                            ReviewerAuditFindingCode.EVIDENCE_HASH_MISMATCH,
                            "Reviewer finding evidence hash differs from frozen contract",
                            finding_id=review_finding.finding_id,
                            evidence_ref_id=cited.ref_id,
                        )
                    )
                if cited.evidence_kind != frozen.evidence_kind:
                    findings.append(
                        ReviewerAuditFinding(
                            ReviewerAuditFindingCode.EVIDENCE_KIND_MISMATCH,
                            "Reviewer finding evidence kind differs from frozen contract",
                            finding_id=review_finding.finding_id,
                            evidence_ref_id=cited.ref_id,
                        )
                    )

        return ReviewerAuditReport(
            report_id=report.report_id,
            report_hash=report.content_hash,
            contract_id=contract.contract_id,
            contract_hash=contract.content_hash,
            evidence_package_hash=package.content_hash,
            status=(
                ReviewerAuditStatus.STRUCTURALLY_VALID
                if not findings
                else ReviewerAuditStatus.REJECTED
            ),
            findings=tuple(findings),
            semantic_findings_verified=False,
        )
