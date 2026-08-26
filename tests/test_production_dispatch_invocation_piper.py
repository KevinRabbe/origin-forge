from __future__ import annotations

import unittest

from origin_forge.audio_models import AudioOperation
from origin_forge.audio_profiles import AudioProfileKind, GovernedAudioProfile
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_invocation_piper import (
    PiperInvocationError,
    PiperInvocationRequest,
)
from origin_forge.production_work_order_models import content_hash


def _profile() -> GovernedAudioProfile:
    digest = "sha256:" + "a" * 64
    return GovernedAudioProfile.create(
        kind=AudioProfileKind.PIPER_TTS,
        operation=AudioOperation.SYNTHESIZE_SPEECH,
        backend_id="piper",
        backend_version="1.6.0",
        runtime_hash=digest,
        target_sample_rate=22_050,
        target_channels=1,
        model_id="voice-en",
        model_hash=digest,
        model_config_hash=digest,
        license_id="voice-license",
        license_hash=digest,
    )


def _request(profile: GovernedAudioProfile) -> PiperInvocationRequest:
    projection = {
        "task_id": new_id(IdKind.TASK),
        "profile_id": profile.profile_id,
        "profile_hash": profile.profile_hash.removeprefix("sha256:"),
        "operation": "SYNTHESIZE_SPEECH",
        "text": "A bounded voice line.",
        "max_duration_ms": 10_000,
        "timeout_seconds": 30,
        "output_relative_path": "exports/voice.wav",
    }
    return PiperInvocationRequest(
        task_id=projection["task_id"],
        profile_id=projection["profile_id"],
        profile_hash=projection["profile_hash"],
        text=projection["text"],
        max_duration_ms=projection["max_duration_ms"],
        timeout_seconds=projection["timeout_seconds"],
        output_relative_path=projection["output_relative_path"],
        request_content_hash=content_hash(projection),
    )


class PiperInvocationRequestTests(unittest.TestCase):
    def test_request_reconstructs_and_allocates_operation_only_from_profile(self) -> None:
        profile = _profile()
        request = _request(profile)
        operation = request.to_operation_request(profile)
        self.assertEqual(operation.operation, AudioOperation.SYNTHESIZE_SPEECH)
        self.assertEqual(operation.profile_hash, profile.profile_hash)
        self.assertEqual(operation.output_relative_path, "exports/voice.wav")

    def test_projection_hash_and_profile_drift_fail_closed(self) -> None:
        profile = _profile()
        request = _request(profile)
        projection = request.projection_dict()
        projection["text"] = "different"
        with self.assertRaises(PiperInvocationError):
            PiperInvocationRequest.from_projection(projection, request.request_content_hash)
        other = _profile()
        with self.assertRaises(PiperInvocationError):
            request.to_operation_request(other)


if __name__ == "__main__":
    unittest.main()
