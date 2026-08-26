from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_runtime import (
    RuntimeObservationDispatchValidator,
)
from origin_forge.production_work_order_validators import DispatchValidatorError


def _ref() -> WorkOrderInputRef:
    return WorkOrderInputRef(
        WorkOrderRefType.RUNTIME_OBSERVATION_REQUEST,
        new_id(IdKind.RUNTIME_OBSERVATION),
        "a" * 64,
        "runtime_observation_request",
    )


class RuntimeObservationWorkOrderTests(unittest.TestCase):
    def test_validator_accepts_only_one_exact_request_ref(self) -> None:
        validator = RuntimeObservationDispatchValidator()
        self.assertEqual(validator.validate({"operation": "OBSERVE"}, (_ref(),)), {"operation": "OBSERVE"})
        with self.assertRaisesRegex(DispatchValidatorError, "exactly one"):
            validator.validate({"operation": "OBSERVE"}, ())

    def test_validator_rejects_mutating_or_malformed_intent(self) -> None:
        validator = RuntimeObservationDispatchValidator()
        for payload in ({"operation": "RUN"}, {"operation": "OBSERVE", "command": "shell"}):
            with self.subTest(payload=payload), self.assertRaises(DispatchValidatorError):
                validator.validate(payload, (_ref(),))


if __name__ == "__main__":
    unittest.main()
