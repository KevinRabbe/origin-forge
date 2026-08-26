from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_binding_audio import (
    PIPER_BINDER_ID,
    PiperAudioInputBinder,
)
from origin_forge.production_work_order_audio import (
    PIPER_ADAPTER_ID,
    PIPER_CONTRACT_ID,
    PIPER_REQUEST_TYPE_ID,
    PiperSpeechDispatchValidator,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_validators import DispatchValidatorError


def _ref() -> WorkOrderInputRef:
    return WorkOrderInputRef(
        WorkOrderRefType.AUDIO_PROFILE,
        new_id(IdKind.AUDIO_PROFILE),
        "a" * 64,
        "audio_profile",
    )


def _payload() -> dict[str, object]:
    return {
        "operation": "SYNTHESIZE_SPEECH",
        "text": "A bounded test voice line.",
        "max_duration_ms": 10_000,
        "timeout_seconds": 30,
        "output_relative_path": "exports/voice.wav",
    }


class PiperWorkOrderContractTests(unittest.TestCase):
    def test_exact_public_relation_is_frozen(self) -> None:
        descriptor = PiperAudioInputBinder().descriptor
        self.assertEqual(descriptor.binder_id, PIPER_BINDER_ID)
        self.assertEqual(descriptor.adapter_id, PIPER_ADAPTER_ID)
        self.assertEqual(descriptor.dispatch_contract_id, PIPER_CONTRACT_ID)
        self.assertEqual(descriptor.request_type_id, PIPER_REQUEST_TYPE_ID)
        self.assertEqual(descriptor.accepted_input_roles, ("audio_profile",))

    def test_validator_requires_one_profile_and_normalizes_exact_text(self) -> None:
        validator = PiperSpeechDispatchValidator()
        normalized = validator.validate(_payload(), (_ref(),))
        self.assertEqual(normalized["text"], "A bounded test voice line.")
        with self.assertRaisesRegex(DispatchValidatorError, "exactly one"):
            validator.validate(_payload(), ())

    def test_validator_rejects_authority_or_path_drift(self) -> None:
        validator = PiperSpeechDispatchValidator()
        for field, value in (
            ("operation", "PROCESS_AUDIO"),
            ("output_relative_path", "../voice.wav"),
            ("output_relative_path", "exports/voice.mp3"),
            ("text", "\x00hidden"),
        ):
            payload = _payload()
            payload[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(DispatchValidatorError):
                validator.validate(payload, (_ref(),))


if __name__ == "__main__":
    unittest.main()
