from __future__ import annotations

import json
import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.model import ModelResponse
from origin_forge.reviewer import IsolatedReviewer
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_models import (
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)


class CapturingModel:
    def __init__(self):
        self.requests = []

    @property
    def model_id(self) -> str:
        return "context-isolation-model"

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps({"findings": []}),
            model_id=self.model_id,
            model_hash=None,
            input_tokens=1,
            output_tokens=1,
        )


class ReviewerContextIsolationTests(unittest.TestCase):
    def test_model_context_is_exact_frozen_package_and_contains_no_executor_session_state(self) -> None:
        task_id = new_id(IdKind.TASK)
        payload = {
            "id": task_id,
            "status": "SUCCEEDED",
            "objective": "Review exact snapshot",
        }
        ref = SpecialistEvidenceRef(
            task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=task_id,
            objective="Independent review",
            evidence_refs=(ref,),
        )
        package = SpecialistEvidencePackage(
            contract,
            (SpecialistEvidenceRecord(ref, payload),),
        )
        model = CapturingModel()
        IsolatedReviewer(model).review(package, run_id=new_id(IdKind.RUN))

        self.assertEqual(len(model.requests), 1)
        request = model.requests[0]
        self.assertEqual(request.context, package.to_dict())
        self.assertEqual(set(request.context), {"contract", "records", "content_hash"})
        serialized = json.dumps(request.context, sort_keys=True).lower()
        for forbidden in (
            "scratchpad",
            "chain_of_thought",
            "executor_context",
            "previous_model_response",
            "workspace_handle",
            "delegate_to",
            "spawn_agent",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
