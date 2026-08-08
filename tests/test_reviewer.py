from __future__ import annotations

import json
import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.model import ModelResponse
from origin_forge.reviewer import (
    REVIEWER_INSTRUCTIONS,
    IsolatedReviewer,
    ReviewerError,
)
from origin_forge.specialist_evidence import (
    SpecialistEvidenceError,
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_models import (
    ReviewerCategory,
    ReviewerSeverity,
    SpecialistBudget,
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)


def digest(character: str = "a") -> str:
    return "sha256:" + character * 64


class FakeReviewerModel:
    def __init__(
        self,
        payload: object,
        *,
        input_tokens: int | None = 100,
        output_tokens: int | None = 25,
    ):
        self.payload = payload
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = []

    @property
    def model_id(self) -> str:
        return "reviewer-test-model"

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps(self.payload),
            model_id=self.model_id,
            model_hash=digest("f"),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class ReviewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task_id = new_id(IdKind.TASK)
        payload = {
            "id": self.task_id,
            "status": "SUCCEEDED",
            "objective": "Preserve authority boundaries",
        }
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.record = SpecialistEvidenceRecord(self.ref, payload)
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review the completed change for evidence-backed risks",
            evidence_refs=(self.ref,),
            acceptance_questions=("Any authority regression?",),
        )
        self.package = SpecialistEvidencePackage(self.contract, (self.record,))
        self.run_id = new_id(IdKind.RUN)

    def _valid_response(self, *, evidence_ids=None):
        return {
            "findings": [
                {
                    "severity": "HIGH",
                    "category": "REGRESSION_RISK",
                    "summary": "The evidence should be checked for an authority regression.",
                    "evidence_ref_ids": evidence_ids or [self.task_id],
                    "recommendation": "Route any repair through a separate governed Task.",
                }
            ]
        }

    def test_frozen_evidence_package_requires_exact_contract_refs(self) -> None:
        self.assertEqual(self.package.records, (self.record,))
        self.assertTrue(self.package.content_hash.startswith("sha256:"))
        other_task = new_id(IdKind.TASK)
        other_payload = {"id": other_task, "status": "FAILED"}
        other_ref = SpecialistEvidenceRef(
            other_task,
            canonical_hash(other_payload),
            SpecialistEvidenceKind.TASK,
        )
        with self.assertRaisesRegex(SpecialistEvidenceError, "exactly match"):
            SpecialistEvidencePackage(
                self.contract,
                (SpecialistEvidenceRecord(other_ref, other_payload),),
            )

    def test_evidence_record_rejects_payload_hash_or_id_drift(self) -> None:
        with self.assertRaisesRegex(SpecialistEvidenceError, "ID does not match"):
            SpecialistEvidenceRecord(
                self.ref,
                {"id": new_id(IdKind.TASK), "status": "SUCCEEDED"},
            )
        with self.assertRaisesRegex(SpecialistEvidenceError, "hash does not match"):
            SpecialistEvidenceRecord(
                self.ref,
                {"id": self.task_id, "status": "FAILED", "objective": "changed"},
            )

    def test_valid_review_is_advisory_and_infrastructure_owns_identity_and_risk(self) -> None:
        model = FakeReviewerModel(self._valid_response())
        result = IsolatedReviewer(model).review(self.package, run_id=self.run_id)
        self.assertEqual(len(result.report.findings), 1)
        finding = result.report.findings[0]
        self.assertTrue(finding.finding_id.startswith("SPFIND-"))
        self.assertTrue(result.report.report_id.startswith("SPREP-"))
        self.assertEqual(finding.severity, ReviewerSeverity.HIGH)
        self.assertEqual(finding.category, ReviewerCategory.REGRESSION_RISK)
        self.assertEqual(finding.evidence_refs, (self.ref,))
        self.assertEqual(result.report.overall_risk, ReviewerSeverity.HIGH)
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 25)
        self.assertFalse(result.to_dict()["production_verification_changed"])
        self.assertEqual(len(model.requests), 1)
        request = model.requests[0]
        self.assertEqual(request.run_id, self.run_id)
        self.assertEqual(request.task_id, self.task_id)
        self.assertEqual(request.instructions, REVIEWER_INSTRUCTIONS)
        properties = request.response_schema["properties"]["findings"]["items"]["properties"]
        for forbidden in (
            "finding_id",
            "overall_risk",
            "passed",
            "verified",
            "approved",
            "patch",
            "command",
            "tool_call",
        ):
            self.assertNotIn(forbidden, properties)

    def test_empty_review_is_info_not_task_pass(self) -> None:
        result = IsolatedReviewer(FakeReviewerModel({"findings": []})).review(
            self.package,
            run_id=self.run_id,
        )
        self.assertEqual(result.report.findings, ())
        self.assertEqual(result.report.overall_risk, ReviewerSeverity.INFO)
        self.assertFalse(result.to_dict()["production_verification_changed"])

    def test_extra_authority_field_fails_strict_response_contract(self) -> None:
        payload = self._valid_response()
        payload["findings"][0]["approved"] = True
        with self.assertRaisesRegex(ReviewerError, "strict response contract"):
            IsolatedReviewer(FakeReviewerModel(payload)).review(
                self.package,
                run_id=self.run_id,
            )

    def test_unknown_or_duplicate_evidence_ids_fail_closed(self) -> None:
        unknown = new_id(IdKind.TASK)
        with self.assertRaisesRegex(ReviewerError, "outside frozen contract"):
            IsolatedReviewer(FakeReviewerModel(self._valid_response(evidence_ids=[unknown]))).review(
                self.package,
                run_id=self.run_id,
            )
        with self.assertRaisesRegex(ReviewerError, "duplicate evidence IDs"):
            IsolatedReviewer(
                FakeReviewerModel(self._valid_response(evidence_ids=[self.task_id, self.task_id]))
            ).review(
                self.package,
                run_id=self.run_id,
            )

    def test_model_call_budget_zero_fails_before_model_call(self) -> None:
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review",
            evidence_refs=(self.ref,),
            budget=SpecialistBudget(max_model_calls=0),
        )
        package = SpecialistEvidencePackage(contract, (self.record,))
        model = FakeReviewerModel({"findings": []})
        with self.assertRaisesRegex(ReviewerError, "disabled by the frozen contract budget"):
            IsolatedReviewer(model).review(package, run_id=self.run_id)
        self.assertEqual(model.requests, [])

    def test_missing_or_overflowing_token_accounting_fails_closed(self) -> None:
        with self.assertRaisesRegex(ReviewerError, "must report non-negative input_tokens"):
            IsolatedReviewer(
                FakeReviewerModel({"findings": []}, input_tokens=None)
            ).review(self.package, run_id=self.run_id)

        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review",
            evidence_refs=(self.ref,),
            budget=SpecialistBudget(max_input_tokens=10),
        )
        package = SpecialistEvidencePackage(contract, (self.record,))
        with self.assertRaisesRegex(ReviewerError, "input_tokens exceeds frozen budget"):
            IsolatedReviewer(
                FakeReviewerModel({"findings": []}, input_tokens=11)
            ).review(package, run_id=self.run_id)

    def test_finding_and_response_budgets_fail_closed(self) -> None:
        item = self._valid_response()["findings"][0]
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review",
            evidence_refs=(self.ref,),
            budget=SpecialistBudget(max_findings=1),
        )
        package = SpecialistEvidencePackage(contract, (self.record,))
        with self.assertRaisesRegex(ReviewerError, "finding count exceeds"):
            IsolatedReviewer(FakeReviewerModel({"findings": [dict(item), dict(item)]})).review(
                package,
                run_id=self.run_id,
            )

        small = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review",
            evidence_refs=(self.ref,),
            budget=SpecialistBudget(max_report_bytes=16),
        )
        small_package = SpecialistEvidencePackage(small, (self.record,))
        with self.assertRaisesRegex(ReviewerError, "response exceeds frozen report byte budget"):
            IsolatedReviewer(FakeReviewerModel({"findings": []})).review(
                small_package,
                run_id=self.run_id,
            )

    def test_non_json_invalid_run_and_wrong_role_fail_closed(self) -> None:
        class RawModel:
            @property
            def model_id(self):
                return "raw-reviewer"

            def generate(self, request):
                return ModelResponse(
                    text="not-json",
                    model_id=self.model_id,
                    model_hash=None,
                    input_tokens=1,
                    output_tokens=1,
                )

        with self.assertRaisesRegex(ReviewerError, "exactly one JSON object"):
            IsolatedReviewer(RawModel()).review(self.package, run_id=self.run_id)
        with self.assertRaisesRegex(ReviewerError, "run_id must be a RUN ID"):
            IsolatedReviewer(FakeReviewerModel({"findings": []})).review(
                self.package,
                run_id="not-run",
            )

        researcher = SpecialistContract.create(
            role=SpecialistRole.RESEARCHER,
            parent_task_id=self.task_id,
            objective="Research",
            evidence_refs=(self.ref,),
        )
        with self.assertRaisesRegex(ReviewerError, "REVIEWER contract"):
            IsolatedReviewer(FakeReviewerModel({"findings": []})).review(
                SpecialistEvidencePackage(researcher, (self.record,)),
                run_id=self.run_id,
            )

    def test_reviewer_has_no_production_mutation_surface(self) -> None:
        reviewer = IsolatedReviewer(FakeReviewerModel({"findings": []}))
        for forbidden in (
            "apply",
            "patch",
            "write",
            "run_command",
            "verify_task",
            "transition_task",
            "merge",
            "delegate",
            "spawn_agent",
        ):
            self.assertFalse(hasattr(reviewer, forbidden))


if __name__ == "__main__":
    unittest.main()
