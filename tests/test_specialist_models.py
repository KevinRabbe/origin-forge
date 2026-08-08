from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.specialist_models import (
    ReviewerCategory,
    ReviewerFinding,
    ReviewerReport,
    ReviewerSeverity,
    SpecialistBudget,
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistModelError,
    SpecialistRole,
)


def digest(character: str) -> str:
    return "sha256:" + character * 64


def task_ref(character: str = "1") -> SpecialistEvidenceRef:
    return SpecialistEvidenceRef(
        new_id(IdKind.TASK),
        digest(character),
        SpecialistEvidenceKind.TASK,
    )


def verification_ref(character: str = "2") -> SpecialistEvidenceRef:
    return SpecialistEvidenceRef(
        new_id(IdKind.VERIFICATION),
        digest(character),
        SpecialistEvidenceKind.VERIFICATION,
    )


class SpecialistModelTests(unittest.TestCase):
    def test_evidence_kind_owns_required_infrastructure_id_type(self) -> None:
        ref = task_ref()
        self.assertEqual(ref.evidence_kind, SpecialistEvidenceKind.TASK)
        with self.assertRaisesRegex(SpecialistModelError, "does not match TASK"):
            SpecialistEvidenceRef(
                new_id(IdKind.RUN),
                digest("a"),
                SpecialistEvidenceKind.TASK,
            )
        with self.assertRaisesRegex(SpecialistModelError, "content_hash"):
            SpecialistEvidenceRef(
                new_id(IdKind.TASK),
                "not-a-hash",
                SpecialistEvidenceKind.TASK,
            )

    def test_contract_semantics_are_normalized_and_opaque_id_is_not_hashed(self) -> None:
        parent_task = new_id(IdKind.TASK)
        first = task_ref("1")
        second = verification_ref("2")
        a = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=parent_task,
            objective="Review the verified change",
            evidence_refs=(second, first),
            acceptance_questions=("Any regression risk?", "Any missing tests?"),
        )
        b = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=parent_task,
            objective="Review the verified change",
            evidence_refs=(first, second),
            acceptance_questions=("Any missing tests?", "Any regression risk?"),
        )
        self.assertNotEqual(a.contract_id, b.contract_id)
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.evidence_refs, b.evidence_refs)
        self.assertEqual(a.acceptance_questions, b.acceptance_questions)

    def test_contract_rejects_duplicate_or_empty_evidence(self) -> None:
        parent_task = new_id(IdKind.TASK)
        ref = task_ref()
        with self.assertRaisesRegex(SpecialistModelError, "requires evidence_refs"):
            SpecialistContract.create(
                role=SpecialistRole.REVIEWER,
                parent_task_id=parent_task,
                objective="Review",
                evidence_refs=(),
            )
        with self.assertRaisesRegex(SpecialistModelError, "duplicate IDs"):
            SpecialistContract.create(
                role=SpecialistRole.REVIEWER,
                parent_task_id=parent_task,
                objective="Review",
                evidence_refs=(ref, ref),
            )

    def test_budget_is_hard_bounded_and_v0_allows_at_most_one_model_call(self) -> None:
        self.assertEqual(SpecialistBudget().max_model_calls, 1)
        SpecialistBudget(max_model_calls=0)
        with self.assertRaisesRegex(SpecialistModelError, "at most one model call"):
            SpecialistBudget(max_model_calls=2)
        with self.assertRaisesRegex(SpecialistModelError, "byte budgets must be positive"):
            SpecialistBudget(max_report_bytes=0)

    def test_reviewer_finding_has_infrastructure_owned_id_and_semantic_hash(self) -> None:
        ref = task_ref()
        a = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.REGRESSION_RISK,
            summary="The change may regress callers.",
            evidence_refs=(ref,),
            recommendation="Inspect callers before release.",
        )
        b = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.REGRESSION_RISK,
            summary="The change may regress callers.",
            evidence_refs=(ref,),
            recommendation="Inspect callers before release.",
        )
        self.assertNotEqual(a.finding_id, b.finding_id)
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertTrue(a.finding_id.startswith("SPFIND-"))

    def test_report_risk_is_computed_from_findings_not_supplied(self) -> None:
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=new_id(IdKind.TASK),
            objective="Review",
            evidence_refs=(task_ref(),),
        )
        low = ReviewerFinding.create(
            severity=ReviewerSeverity.LOW,
            category=ReviewerCategory.MAINTAINABILITY,
            summary="Minor duplication.",
            evidence_refs=contract.evidence_refs,
            recommendation="Consider refactoring later.",
        )
        critical = ReviewerFinding.create(
            severity=ReviewerSeverity.CRITICAL,
            category=ReviewerCategory.SECURITY,
            summary="Potential authority bypass.",
            evidence_refs=contract.evidence_refs,
            recommendation="Block integration until independently verified.",
        )
        report = ReviewerReport.create(
            contract=contract,
            model_id="reviewer-model",
            model_hash=digest("f"),
            findings=(low, critical),
        )
        self.assertEqual(report.overall_risk, ReviewerSeverity.CRITICAL)
        self.assertEqual(report.to_dict()["overall_risk"], "CRITICAL")
        self.assertTrue(report.report_id.startswith("SPREP-"))
        self.assertEqual(report.contract_hash, contract.content_hash)

    def test_empty_reviewer_report_is_advisory_info_not_pass_authority(self) -> None:
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=new_id(IdKind.TASK),
            objective="Review",
            evidence_refs=(task_ref(),),
        )
        report = ReviewerReport.create(
            contract=contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(),
        )
        self.assertEqual(report.overall_risk, ReviewerSeverity.INFO)
        self.assertNotIn("passed", report.to_dict())
        self.assertNotIn("verified", report.to_dict())
        self.assertNotIn("approved", report.to_dict())

    def test_duplicate_semantic_findings_are_rejected(self) -> None:
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=new_id(IdKind.TASK),
            objective="Review",
            evidence_refs=(task_ref(),),
        )
        first = ReviewerFinding.create(
            severity=ReviewerSeverity.MEDIUM,
            category=ReviewerCategory.TEST_GAP,
            summary="Missing edge-case coverage.",
            evidence_refs=contract.evidence_refs,
            recommendation="Add a normal governed test task.",
        )
        second = ReviewerFinding.create(
            severity=ReviewerSeverity.MEDIUM,
            category=ReviewerCategory.TEST_GAP,
            summary="Missing edge-case coverage.",
            evidence_refs=contract.evidence_refs,
            recommendation="Add a normal governed test task.",
        )
        with self.assertRaisesRegex(SpecialistModelError, "duplicate semantic findings"):
            ReviewerReport.create(
                contract=contract,
                model_id="reviewer-model",
                model_hash=None,
                findings=(first, second),
            )

    def test_reviewer_report_requires_reviewer_contract(self) -> None:
        contract = SpecialistContract.create(
            role=SpecialistRole.RESEARCHER,
            parent_task_id=new_id(IdKind.TASK),
            objective="Research",
            evidence_refs=(task_ref(),),
        )
        with self.assertRaisesRegex(SpecialistModelError, "REVIEWER contract"):
            ReviewerReport.create(
                contract=contract,
                model_id="reviewer-model",
                model_hash=None,
                findings=(),
            )


if __name__ == "__main__":
    unittest.main()
