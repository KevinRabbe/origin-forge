from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer_audit import (
    ReviewerAuditFindingCode,
    ReviewerAuditStatus,
    ReviewerReportAuditor,
)
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


def digest(character: str) -> str:
    return "sha256:" + character * 64


class ReviewerAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task_id = new_id(IdKind.TASK)
        payload = {"id": self.task_id, "status": "SUCCEEDED", "objective": "Review me"}
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.record = SpecialistEvidenceRecord(self.ref, payload)
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review frozen evidence",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(self.contract, (self.record,))
        self.finding = ReviewerFinding.create(
            severity=ReviewerSeverity.MEDIUM,
            category=ReviewerCategory.TEST_GAP,
            summary="A test edge may be missing.",
            evidence_refs=(self.ref,),
            recommendation="Create a separate governed test Task if confirmed.",
        )
        self.report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-model",
            model_hash=digest("f"),
            findings=(self.finding,),
        )
        self.auditor = ReviewerReportAuditor()

    def test_exact_report_is_only_structurally_valid_not_semantically_verified(self) -> None:
        audit = self.auditor.audit(self.report, self.package)
        self.assertEqual(audit.status, ReviewerAuditStatus.STRUCTURALLY_VALID)
        self.assertEqual(audit.findings, ())
        self.assertFalse(audit.semantic_findings_verified)
        self.assertEqual(audit.report_id, self.report.report_id)
        self.assertEqual(audit.report_hash, self.report.content_hash)
        self.assertEqual(audit.contract_hash, self.contract.content_hash)
        self.assertEqual(audit.evidence_package_hash, self.package.content_hash)
        self.assertTrue(audit.content_hash.startswith("sha256:"))
        self.assertFalse(audit.to_dict()["semantic_findings_verified"])
        self.assertNotIn("approved", audit.to_dict())
        self.assertNotIn("verified_task", audit.to_dict())

    def test_report_bound_to_different_contract_is_rejected(self) -> None:
        other = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Different review objective",
            evidence_refs=(self.ref,),
        )
        report = ReviewerReport.create(
            contract=other,
            model_id="reviewer-model",
            model_hash=None,
            findings=(self.finding,),
        )
        audit = self.auditor.audit(report, self.package)
        self.assertEqual(audit.status, ReviewerAuditStatus.REJECTED)
        codes = {item.code for item in audit.findings}
        self.assertIn(ReviewerAuditFindingCode.CONTRACT_ID_MISMATCH, codes)
        self.assertIn(ReviewerAuditFindingCode.CONTRACT_HASH_MISMATCH, codes)
        self.assertFalse(audit.semantic_findings_verified)

    def test_finding_evidence_outside_frozen_contract_is_rejected(self) -> None:
        other_task = new_id(IdKind.TASK)
        outside = SpecialistEvidenceRef(
            other_task,
            digest("a"),
            SpecialistEvidenceKind.TASK,
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.EVIDENCE_CONFLICT,
            summary="Outside evidence was cited.",
            evidence_refs=(outside,),
            recommendation="Reject this advisory report binding.",
        )
        report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        audit = self.auditor.audit(report, self.package)
        self.assertEqual(audit.status, ReviewerAuditStatus.REJECTED)
        self.assertEqual(len(audit.findings), 1)
        self.assertEqual(
            audit.findings[0].code,
            ReviewerAuditFindingCode.EVIDENCE_OUTSIDE_CONTRACT,
        )
        self.assertEqual(audit.findings[0].finding_id, finding.finding_id)
        self.assertEqual(audit.findings[0].evidence_ref_id, other_task)

    def test_same_evidence_id_with_changed_hash_is_rejected(self) -> None:
        changed = SpecialistEvidenceRef(
            self.task_id,
            digest("b"),
            SpecialistEvidenceKind.TASK,
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.EVIDENCE_CONFLICT,
            summary="Changed hash.",
            evidence_refs=(changed,),
            recommendation="Use the frozen evidence hash.",
        )
        report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        audit = self.auditor.audit(report, self.package)
        self.assertEqual(audit.status, ReviewerAuditStatus.REJECTED)
        self.assertEqual(
            [item.code for item in audit.findings],
            [ReviewerAuditFindingCode.EVIDENCE_HASH_MISMATCH],
        )

    def test_wrong_contract_role_is_rejected_even_if_report_object_is_constructed(self) -> None:
        researcher = SpecialistContract.create(
            role=SpecialistRole.RESEARCHER,
            parent_task_id=self.task_id,
            objective="Research",
            evidence_refs=(self.ref,),
        )
        package = SpecialistEvidencePackage(researcher, (self.record,))
        audit = self.auditor.audit(self.report, package)
        self.assertEqual(audit.status, ReviewerAuditStatus.REJECTED)
        codes = {item.code for item in audit.findings}
        self.assertIn(ReviewerAuditFindingCode.WRONG_ROLE, codes)
        self.assertIn(ReviewerAuditFindingCode.CONTRACT_ID_MISMATCH, codes)
        self.assertIn(ReviewerAuditFindingCode.CONTRACT_HASH_MISMATCH, codes)

    def test_auditor_has_no_repair_promotion_or_runtime_transition_surface(self) -> None:
        for forbidden in (
            "repair",
            "apply",
            "patch",
            "promote",
            "approve",
            "verify_task",
            "transition_task",
            "merge",
        ):
            self.assertFalse(hasattr(self.auditor, forbidden))


if __name__ == "__main__":
    unittest.main()
