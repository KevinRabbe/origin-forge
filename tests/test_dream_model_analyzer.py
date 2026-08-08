from __future__ import annotations

import hashlib
import json
import unittest

from origin_forge.dream_evidence import DreamEvidenceRecord
from origin_forge.dream_model_analyzer import (
    BoundedModelDreamAnalyzer,
    DREAM_ANALYZER_INSTRUCTIONS,
    DreamModelAnalyzerError,
)
from origin_forge.dream_models import (
    DreamBudget,
    DreamCandidateType,
    DreamDownstreamGate,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
)
from origin_forge.dream_preprocess import EvidenceSnapshot, preprocess_memory
from origin_forge.dream_roles import DreamAnalysisPackage
from origin_forge.ids import IdKind, new_id
from origin_forge.model import ModelResponse


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class FakeModel:
    def __init__(self, payload: object):
        self.payload = payload
        self.requests = []

    @property
    def model_id(self) -> str:
        return "dream-test-model"

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps(self.payload),
            model_id=self.model_id,
            model_hash="sha256:test-model",
            input_tokens=123,
            output_tokens=45,
        )


class DreamModelAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_id = new_id(IdKind.RUN)
        self.task_id = new_id(IdKind.TASK)
        payload = {
            "id": self.run_id,
            "status": "FAILED",
            "failure_reason": "tests failed",
        }
        self.run_ref = EvidenceRef(
            self.run_id,
            canonical_hash(payload),
            EvidenceClass.TRAJECTORY,
        )
        self.record = DreamEvidenceRecord(self.run_ref, "RUN", payload)
        self.manifest = DreamInputManifest.create(run_refs=(self.run_ref,))
        report = preprocess_memory((), EvidenceSnapshot.create((self.run_ref,)))
        self.package = DreamAnalysisPackage(self.manifest, report, ())

    def _valid_payload(self, *, candidate_type="SKILL", evidence_ids=None):
        return {
            "candidates": [
                {
                    "candidate_type": candidate_type,
                    "summary": "Repeated failures suggest a reusable debugging procedure.",
                    "proposed_action": "Benchmark a candidate Skill through governed Skill Evaluation.",
                    "evidence_ref_ids": evidence_ids or [self.run_id],
                    "contradiction_ref_ids": [],
                }
            ]
        }

    def test_valid_model_candidate_is_proposal_only_and_gate_is_infrastructure_owned(self) -> None:
        model = FakeModel(self._valid_payload())
        result = BoundedModelDreamAnalyzer(model).analyze(
            self.package,
            (self.record,),
            run_id=self.run_id,
            task_id=self.task_id,
        )
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.candidate_type, DreamCandidateType.SKILL)
        self.assertEqual(candidate.required_gate, DreamDownstreamGate.SKILL_EVALUATION)
        self.assertEqual(candidate.evidence_refs, (self.run_ref,))
        self.assertIsNone(candidate.target_memory_generation_id)
        self.assertEqual(result.model_id, "dream-test-model")
        self.assertEqual(result.input_tokens, 123)
        self.assertEqual(result.output_tokens, 45)
        self.assertTrue(result.context_hash.startswith("sha256:"))
        self.assertTrue(result.response_hash.startswith("sha256:"))
        self.assertEqual(len(model.requests), 1)
        request = model.requests[0]
        self.assertEqual(request.run_id, self.run_id)
        self.assertEqual(request.task_id, self.task_id)
        self.assertEqual(request.instructions, DREAM_ANALYZER_INSTRUCTIONS)
        self.assertNotIn(
            "required_gate",
            request.response_schema["properties"]["candidates"]["items"]["properties"],
        )

    def test_model_adapter_contract_is_enforced(self) -> None:
        class GenerateOnly:
            def generate(self, request):
                return ModelResponse(text='{"candidates":[]}', model_id="invalid")

        with self.assertRaisesRegex(TypeError, "ModelAdapter"):
            BoundedModelDreamAnalyzer(GenerateOnly())

    def test_model_cannot_supply_required_gate_or_other_extra_fields(self) -> None:
        payload = self._valid_payload()
        payload["candidates"][0]["required_gate"] = "DETERMINISTIC_VALIDATION"
        with self.assertRaisesRegex(DreamModelAnalyzerError, "strict response contract"):
            BoundedModelDreamAnalyzer(FakeModel(payload)).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_model_cannot_emit_deterministic_only_data_quality_type(self) -> None:
        payload = self._valid_payload(candidate_type="DATA_QUALITY")
        with self.assertRaisesRegex(DreamModelAnalyzerError, "not available to model analyzers"):
            BoundedModelDreamAnalyzer(FakeModel(payload)).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_unknown_evidence_id_is_rejected(self) -> None:
        payload = self._valid_payload(evidence_ids=[new_id(IdKind.RUN)])
        with self.assertRaisesRegex(DreamModelAnalyzerError, "outside frozen manifest"):
            BoundedModelDreamAnalyzer(FakeModel(payload)).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_model_candidate_count_is_frozen_by_manifest_budget(self) -> None:
        item = self._valid_payload()["candidates"][0]
        payload = {"candidates": [dict(item), dict(item)]}
        manifest = DreamInputManifest.create(
            run_refs=(self.run_ref,),
            budget=DreamBudget(max_candidates=1),
        )
        report = preprocess_memory((), EvidenceSnapshot.create((self.run_ref,)))
        package = DreamAnalysisPackage(manifest, report, ())
        with self.assertRaisesRegex(DreamModelAnalyzerError, "candidate count exceeds"):
            BoundedModelDreamAnalyzer(FakeModel(payload)).analyze(
                package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_non_json_and_response_byte_overflow_fail_closed(self) -> None:
        class RawModel:
            def __init__(self, text):
                self.text = text

            @property
            def model_id(self) -> str:
                return "raw"

            def generate(self, request):
                return ModelResponse(text=self.text, model_id=self.model_id)

        with self.assertRaisesRegex(DreamModelAnalyzerError, "one JSON object"):
            BoundedModelDreamAnalyzer(RawModel("not-json")).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )
        with self.assertRaisesRegex(DreamModelAnalyzerError, "response exceeds byte limit"):
            BoundedModelDreamAnalyzer(
                RawModel(json.dumps({"candidates": []}) + " " * 100),
                max_response_bytes=32,
            ).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_context_byte_limit_fails_before_model_call(self) -> None:
        model = FakeModel({"candidates": []})
        with self.assertRaisesRegex(DreamModelAnalyzerError, "context exceeds byte limit"):
            BoundedModelDreamAnalyzer(model, max_context_bytes=32).analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )
        self.assertEqual(model.requests, [])

    def test_evidence_record_must_exactly_match_frozen_manifest_ref(self) -> None:
        changed_payload = {
            "id": self.run_id,
            "status": "FAILED",
            "failure_reason": "different",
        }
        changed_ref = EvidenceRef(
            self.run_id,
            canonical_hash(changed_payload),
            EvidenceClass.TRAJECTORY,
        )
        changed_record = DreamEvidenceRecord(changed_ref, "RUN", changed_payload)
        with self.assertRaisesRegex(DreamModelAnalyzerError, "not an exact frozen manifest ref"):
            BoundedModelDreamAnalyzer(FakeModel({"candidates": []})).analyze(
                self.package,
                (changed_record,),
                run_id=self.run_id,
                task_id=self.task_id,
            )

    def test_invalid_run_or_task_identity_fails_before_model_call(self) -> None:
        model = FakeModel({"candidates": []})
        analyzer = BoundedModelDreamAnalyzer(model)
        with self.assertRaisesRegex(DreamModelAnalyzerError, "run_id must be a RUN ID"):
            analyzer.analyze(
                self.package,
                (self.record,),
                run_id="not-run",
                task_id=self.task_id,
            )
        with self.assertRaisesRegex(DreamModelAnalyzerError, "task_id must be a TASK ID"):
            analyzer.analyze(
                self.package,
                (self.record,),
                run_id=self.run_id,
                task_id="not-task",
            )
        self.assertEqual(model.requests, [])

    def test_model_analyzer_exposes_no_apply_promote_or_generation_surface(self) -> None:
        analyzer = BoundedModelDreamAnalyzer(FakeModel({"candidates": []}))
        for forbidden in (
            "apply",
            "promote",
            "write",
            "merge",
            "build_generation",
            "change_policy",
        ):
            self.assertFalse(hasattr(analyzer, forbidden))


if __name__ == "__main__":
    unittest.main()
