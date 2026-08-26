from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.production_playtest_dispatch_output_binding_models import (
    PLAYTEST_EXECUTION_OWNER_ID,
    PlaytestDispatchOutputBinding,
    PlaytestDispatchOutputBindingModelError,
)


def _binding(**overrides):
    values = {
        "execution_id": new_id(IdKind.DISPATCH_EXECUTION),
        "claim_id": new_id(IdKind.DISPATCH_CLAIM),
        "task_id": new_id(IdKind.TASK),
        "task_revision": 1,
        "task_content_hash": "a" * 64,
        "work_order_id": new_id(IdKind.PRODUCTION_WORK_ORDER),
        "work_order_hash": "b" * 64,
        "dispatch_binding_id": new_id(IdKind.DISPATCH_BINDING),
        "dispatch_binding_hash": "c" * 64,
        "execution_owner_id": PLAYTEST_EXECUTION_OWNER_ID,
        "run_id": new_id(IdKind.RUN),
        "scenario_artifact_id": new_id(IdKind.ARTIFACT),
        "telemetry_artifact_id": new_id(IdKind.ARTIFACT),
        "summary_artifact_id": new_id(IdKind.ARTIFACT),
        "stdout_artifact_id": new_id(IdKind.ARTIFACT),
        "stderr_artifact_id": new_id(IdKind.ARTIFACT),
        "telemetry_hash": "d" * 64,
        "summary_json": '{"deaths":0}',
        "outcome": "COMPLETED",
        "timed_out": False,
        "exit_code": 0,
        "schema_version": 1,
        "created_at": "2026-08-26T00:00:00Z",
    }
    values.update(overrides)
    return PlaytestDispatchOutputBinding(**values)


class PlaytestDispatchOutputBindingModelTests(unittest.TestCase):
    def test_valid_binding_is_evidence_only(self) -> None:
        self.assertEqual(_binding().execution_owner_id, PLAYTEST_EXECUTION_OWNER_ID)

    def test_invalid_summary_and_owner_are_rejected(self) -> None:
        with self.assertRaises(PlaytestDispatchOutputBindingModelError):
            _binding(summary_json="[]")
        with self.assertRaises(PlaytestDispatchOutputBindingModelError):
            _binding(execution_owner_id="originforge.execution.bounded-retry@1")


if __name__ == "__main__":
    unittest.main()
