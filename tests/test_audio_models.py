from __future__ import annotations

import unittest

from origin_forge.audio_models import (
    AudioModelError,
    AudioOperation,
    AudioOperationRequest,
    AudioOperationResult,
    AudioOutputEvidence,
    AudioResultStatus,
    AudioSourceRef,
)
from origin_forge.ids import IdKind, new_id


PROFILE_HASH = "sha256:" + "1" * 64
MODEL_HASH = "sha256:" + "2" * 64
SOURCE_HASH = "sha256:" + "3" * 64
PCM_HASH = "sha256:" + "4" * 64
OUTPUT_HASH = "sha256:" + "5" * 64
OUTPUT_PCM_HASH = "sha256:" + "6" * 64


def _source(source_id: str = "source") -> AudioSourceRef:
    return AudioSourceRef(
        source_id=source_id,
        relative_path=f"inputs/{source_id}.wav",
        content_hash=SOURCE_HASH,
        pcm_hash=PCM_HASH,
        byte_count=100,
        frame_count=20,
        sample_rate=48_000,
        channels=1,
    )


def _output(path: str = "exports/output.wav") -> AudioOutputEvidence:
    return AudioOutputEvidence(
        relative_path=path,
        content_hash=OUTPUT_HASH,
        pcm_hash=OUTPUT_PCM_HASH,
        byte_count=120,
        frame_count=24,
        sample_rate=48_000,
        channels=1,
        peak_abs_sample=100,
        clipped_sample_count=0,
        nonzero_sample_count=20,
    )


class AudioModelTests(unittest.TestCase):
    def test_process_request_requires_exact_single_source_and_has_stable_hash(self) -> None:
        profile_id = new_id(IdKind.AUDIO_PROFILE)
        first = AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            profile_id=profile_id,
            profile_hash=PROFILE_HASH,
            inputs=(_source("b"),),
        )
        second = AudioOperationRequest(
            operation_id=first.operation_id,
            workspace_id=first.workspace_id,
            operation=first.operation,
            backend_id=first.backend_id,
            backend_version=first.backend_version,
            profile_id=first.profile_id,
            profile_hash=first.profile_hash,
            model_id=first.model_id,
            model_hash=first.model_hash,
            inputs=first.inputs,
            prompt=first.prompt,
            text=first.text,
            seed=first.seed,
            target_sample_rate=first.target_sample_rate,
            target_channels=first.target_channels,
            max_duration_ms=first.max_duration_ms,
            timeout_seconds=first.timeout_seconds,
            output_relative_path=first.output_relative_path,
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.inputs[0].source_id, "b")

        with self.assertRaisesRegex(AudioModelError, "exactly one input"):
            AudioOperationRequest.create(
                operation=AudioOperation.PROCESS_AUDIO,
                backend_id="ffmpeg",
                backend_version="8.1.2",
                profile_id=profile_id,
                profile_hash=PROFILE_HASH,
            )

    def test_speech_requires_text_and_exact_voice_identity(self) -> None:
        profile_id = new_id(IdKind.AUDIO_PROFILE)
        request = AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.4.2",
            profile_id=profile_id,
            profile_hash=PROFILE_HASH,
            model_id="voice-en-test",
            model_hash=MODEL_HASH,
            text="Hello Origin Forge",
        )
        self.assertEqual(request.text, "Hello Origin Forge")
        self.assertIsNone(request.prompt)

        with self.assertRaisesRegex(AudioModelError, "voice/model identity"):
            AudioOperationRequest.create(
                operation=AudioOperation.SYNTHESIZE_SPEECH,
                backend_id="piper",
                backend_version="1.4.2",
                profile_id=profile_id,
                profile_hash=PROFILE_HASH,
                text="Hello",
            )

    def test_sfx_and_music_require_prompt_and_seed(self) -> None:
        profile_id = new_id(IdKind.AUDIO_PROFILE)
        for operation in (
            AudioOperation.SYNTHESIZE_SFX,
            AudioOperation.GENERATE_MUSIC,
        ):
            request = AudioOperationRequest.create(
                operation=operation,
                backend_id="deterministic-audio",
                backend_version="1",
                profile_id=profile_id,
                profile_hash=PROFILE_HASH,
                prompt="short mechanical pulse",
                seed=7,
            )
            self.assertEqual(request.seed, 7)
            with self.assertRaisesRegex(AudioModelError, "prompt \+ seed"):
                AudioOperationRequest.create(
                    operation=operation,
                    backend_id="deterministic-audio",
                    backend_version="1",
                    profile_id=profile_id,
                    profile_hash=PROFILE_HASH,
                    prompt="short mechanical pulse",
                )

    def test_paths_are_workspace_relative_wav_and_output_is_below_exports(self) -> None:
        profile_id = new_id(IdKind.AUDIO_PROFILE)
        with self.assertRaises(AudioModelError):
            AudioOperationRequest.create(
                operation=AudioOperation.PROCESS_AUDIO,
                backend_id="ffmpeg",
                backend_version="8.1.2",
                profile_id=profile_id,
                profile_hash=PROFILE_HASH,
                inputs=(_source(),),
                output_relative_path="../escape.wav",
            )
        with self.assertRaisesRegex(AudioModelError, "below exports"):
            AudioOperationRequest.create(
                operation=AudioOperation.PROCESS_AUDIO,
                backend_id="ffmpeg",
                backend_version="8.1.2",
                profile_id=profile_id,
                profile_hash=PROFILE_HASH,
                inputs=(_source(),),
                output_relative_path="runtime/output.wav",
            )

    def test_result_must_bind_request_and_exact_output_contract(self) -> None:
        request = AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            profile_id=new_id(IdKind.AUDIO_PROFILE),
            profile_hash=PROFILE_HASH,
            inputs=(_source(),),
        )
        result = AudioOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=AudioResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            profile_id=request.profile_id,
            profile_hash=request.profile_hash,
            model_id=None,
            model_hash=None,
            outputs=(_output(),),
        )
        result.bind_request(request)
        self.assertTrue(result.content_hash.startswith("sha256:"))

        drifted = AudioOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=AudioResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            profile_id=request.profile_id,
            profile_hash=request.profile_hash,
            model_id=None,
            model_hash=None,
            outputs=(_output("exports/other.wav"),),
        )
        with self.assertRaisesRegex(AudioModelError, "output path"):
            drifted.bind_request(request)

    def test_failed_result_may_not_claim_output(self) -> None:
        with self.assertRaisesRegex(AudioModelError, "may not claim outputs"):
            AudioOperationResult(
                operation_id=new_id(IdKind.AUDIO_OPERATION),
                workspace_id=new_id(IdKind.AUDIO_WORKSPACE),
                request_hash=PROFILE_HASH,
                status=AudioResultStatus.FAILED,
                backend_id="ffmpeg",
                backend_version="8.1.2",
                profile_id=new_id(IdKind.AUDIO_PROFILE),
                profile_hash=PROFILE_HASH,
                model_id=None,
                model_hash=None,
                outputs=(_output(),),
                detail="failed",
            )


if __name__ == "__main__":
    unittest.main()
