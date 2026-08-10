from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.audio_piper import (
    BoundedPiperSubprocessRunner,
    PiperAudioAdapter,
    PiperAudioIntegrityError,
    PiperAudioProcessError,
    PiperProcessOutcome,
    piper_runtime_tree_hash,
)
from origin_forge.audio_models import AudioOperation, AudioOperationRequest, canonical_bytes
from origin_forge.audio_profiles import AudioProfileKind, GovernedAudioProfile
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.runtime import OriginForgeRuntime


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _FakePiperRunner:
    def __init__(
        self,
        *,
        synthesis_outcome: PiperProcessOutcome | None = None,
        invalid_output: bool = False,
        version: bytes = b"1.6.0\n",
    ):
        self.calls: list[tuple[tuple[str, ...], bytes]] = []
        self.synthesis_outcome = synthesis_outcome
        self.invalid_output = invalid_output
        self.version = version

    def run(
        self,
        argv,
        *,
        cwd,
        stdin_bytes,
        timeout_seconds,
        max_stdout_bytes,
        max_stderr_bytes,
    ):
        values = tuple(argv)
        self.calls.append((values, stdin_bytes))
        if values[1:] == ("--version",):
            return PiperProcessOutcome(0, self.version, b"")
        if self.synthesis_outcome is not None:
            return self.synthesis_outcome
        output = Path(values[values.index("--output-file") + 1])
        if self.invalid_output:
            output.write_bytes(b"not-wav")
        else:
            pcm = b"".join(
                struct.pack("<h", value) for value in (0, 200, -200, 100, -100, 0)
            )
            output.write_bytes(
                encode_pcm16_wav(channels=1, sample_rate=22_050, pcm_bytes=pcm)
            )
        return PiperProcessOutcome(0, str(output).encode("utf-8") + b"\n", b"")


class PiperAudioAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root / "project")
        self.runtime.initialize("piper-audio-test")

        self.runtime_root = self.root / "piper-runtime"
        (self.runtime_root / "bin").mkdir(parents=True)
        (self.runtime_root / "lib").mkdir()
        (self.runtime_root / "espeak-ng-data").mkdir()
        self.executable = self.runtime_root / "bin" / "piper"
        self.executable.write_bytes(b"frozen piper 1.6.0 executable")
        (self.runtime_root / "lib" / "libpiper.so").write_bytes(b"frozen libpiper")
        (self.runtime_root / "lib" / "libonnxruntime.so").write_bytes(b"frozen onnxruntime")
        (self.runtime_root / "espeak-ng-data" / "en_dict").write_bytes(b"frozen espeak data")

        self.model_path = self.root / "en_US-joe-medium.onnx"
        self.model_path.write_bytes(b"frozen voice model")
        self.config_path = self.root / "en_US-joe-medium.onnx.json"
        self.config_path.write_text(
            json.dumps({"audio": {"sample_rate": 22_050}}),
            encoding="utf-8",
        )
        self.license_path = self.root / "MODEL_CARD"
        self.license_path.write_text("CC0-1.0 voice dataset evidence\n", encoding="utf-8")

        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            runtime_hash=piper_runtime_tree_hash(self.runtime_root),
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en_US-joe-medium",
            model_hash=_sha256(self.model_path.read_bytes()),
            model_config_hash=_sha256(self.config_path.read_bytes()),
            license_id="CC0-1.0",
            license_hash=_sha256(self.license_path.read_bytes()),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _adapter(self, runner=None) -> PiperAudioAdapter:
        return PiperAudioAdapter(
            self.runtime,
            self.profile,
            runtime_root=self.runtime_root,
            executable=self.executable,
            espeak_data_path=self.runtime_root / "espeak-ng-data",
            model_path=self.model_path,
            model_config_path=self.config_path,
            license_path=self.license_path,
            runner=runner,
        )

    def _request(self) -> AudioOperationRequest:
        return AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            profile_id=self.profile.profile_id,
            profile_hash=self.profile.profile_hash,
            model_id=self.profile.model_id,
            model_hash=self.profile.model_hash,
            text="Origin Forge bounded speech synthesis.",
            target_sample_rate=22_050,
            target_channels=1,
            max_duration_ms=5_000,
            timeout_seconds=5,
            output_relative_path="exports/speech.wav",
        )

    def test_fixed_policy_argv_stdin_and_output_are_independently_validated(self) -> None:
        runner = _FakePiperRunner()
        adapter = self._adapter(runner)
        request = self._request()
        execution = adapter.execute(request, {})
        execution.result.bind_request(request)

        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(
            runner.calls[0],
            ((str(self.executable), "--version"), b""),
        )
        argv, stdin_bytes = runner.calls[1]
        self.assertEqual(argv[0], str(self.executable))
        self.assertEqual(argv[argv.index("--speaker") + 1], "0")
        self.assertEqual(argv[argv.index("--noise_scale") + 1], "0")
        self.assertEqual(argv[argv.index("--noise_w") + 1], "0")
        self.assertEqual(argv[argv.index("--length_scale") + 1], "1")
        self.assertEqual(
            argv[argv.index("--espeak_data") + 1],
            str(self.runtime_root / "espeak-ng-data"),
        )
        self.assertTrue(argv[argv.index("--model") + 1].endswith("inputs/voice.onnx"))
        self.assertTrue(argv[argv.index("--config") + 1].endswith("inputs/voice.onnx.json"))
        self.assertTrue(argv[argv.index("--output-file") + 1].endswith("runtime/piper-output.wav"))
        self.assertEqual(stdin_bytes, request.text.encode("utf-8") + b"\n")

        output_path = execution.workspace_path / "exports" / "speech.wav"
        output = inspect_pcm16_wav(output_path.read_bytes())
        self.assertEqual(output.sample_rate, 22_050)
        self.assertEqual(output.channels, 1)
        self.assertEqual(output.content_hash, execution.result.outputs[0].content_hash)
        self.assertEqual(output.pcm_hash, execution.result.outputs[0].pcm_hash)
        self.assertEqual(
            (execution.workspace_path / "request" / "request.json").read_bytes(),
            canonical_bytes(request.to_dict()),
        )
        self.assertEqual(
            _sha256((execution.workspace_path / "inputs" / "voice.onnx").read_bytes()),
            self.profile.model_hash,
        )
        self.assertEqual(
            _sha256((execution.workspace_path / "inputs" / "voice.LICENSE").read_bytes()),
            self.profile.license_hash,
        )

    def test_runtime_tree_and_runtime_version_are_governed(self) -> None:
        runner = _FakePiperRunner()
        (self.runtime_root / "lib" / "libpiper.so").write_bytes(b"drift")
        with self.assertRaisesRegex(PiperAudioIntegrityError, "runtime tree hash"):
            self._adapter(runner).execute(self._request(), {})
        self.assertEqual(runner.calls, [])

        (self.runtime_root / "lib" / "libpiper.so").write_bytes(b"frozen libpiper")
        bad_version = _FakePiperRunner(version=b"1.5.0\n")
        with self.assertRaisesRegex(PiperAudioIntegrityError, "version"):
            self._adapter(bad_version).execute(self._request(), {})
        self.assertEqual(len(bad_version.calls), 1)

    def test_runtime_tree_rejects_symlink_members(self) -> None:
        target = self.root / "outside-runtime-file"
        target.write_bytes(b"outside")
        link = self.runtime_root / "lib" / "escape.so"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(PiperAudioIntegrityError, "may not contain symlinks"):
            piper_runtime_tree_hash(self.runtime_root)

    def test_model_config_and_license_drift_fail_before_process(self) -> None:
        cases = (
            (self.model_path, b"changed model", "voice model hash"),
            (self.config_path, b'{"audio":{"sample_rate":16000}}', "voice config hash"),
            (self.license_path, b"changed license", "voice license hash"),
        )
        originals = {
            self.model_path: self.model_path.read_bytes(),
            self.config_path: self.config_path.read_bytes(),
            self.license_path: self.license_path.read_bytes(),
        }
        for path, changed, pattern in cases:
            for restore_path, data in originals.items():
                restore_path.write_bytes(data)
            path.write_bytes(changed)
            runner = _FakePiperRunner()
            with self.assertRaisesRegex(PiperAudioIntegrityError, pattern):
                self._adapter(runner).execute(self._request(), {})
            self.assertEqual(runner.calls, [])
        for path, data in originals.items():
            path.write_bytes(data)

    def test_config_sample_rate_is_bound_before_process(self) -> None:
        changed = json.dumps({"audio": {"sample_rate": 16_000}}).encode("utf-8")
        self.config_path.write_bytes(changed)
        profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            runtime_hash=piper_runtime_tree_hash(self.runtime_root),
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en_US-joe-medium",
            model_hash=_sha256(self.model_path.read_bytes()),
            model_config_hash=_sha256(changed),
            license_id="CC0-1.0",
            license_hash=_sha256(self.license_path.read_bytes()),
        )
        runner = _FakePiperRunner()
        adapter = PiperAudioAdapter(
            self.runtime,
            profile,
            runtime_root=self.runtime_root,
            executable=self.executable,
            espeak_data_path=self.runtime_root / "espeak-ng-data",
            model_path=self.model_path,
            model_config_path=self.config_path,
            license_path=self.license_path,
            runner=runner,
        )
        request = AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            model_id=profile.model_id,
            model_hash=profile.model_hash,
            text="sample rate mismatch",
            target_sample_rate=22_050,
            target_channels=1,
        )
        with self.assertRaisesRegex(PiperAudioIntegrityError, "config sample rate"):
            adapter.execute(request, {})
        self.assertEqual(runner.calls, [])

    def test_request_must_bind_exact_profile_and_voice_before_process(self) -> None:
        runner = _FakePiperRunner()
        request = AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            profile_id=self.profile.profile_id,
            profile_hash="sha256:" + "f" * 64,
            model_id=self.profile.model_id,
            model_hash=self.profile.model_hash,
            text="wrong profile",
            target_sample_rate=22_050,
            target_channels=1,
        )
        with self.assertRaisesRegex(PiperAudioIntegrityError, "governed Piper profile"):
            self._adapter(runner).execute(request, {})
        self.assertEqual(runner.calls, [])

        runner = _FakePiperRunner()
        request = AudioOperationRequest.create(
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            profile_id=self.profile.profile_id,
            profile_hash=self.profile.profile_hash,
            model_id=self.profile.model_id,
            model_hash="sha256:" + "e" * 64,
            text="wrong voice",
            target_sample_rate=22_050,
            target_channels=1,
        )
        with self.assertRaisesRegex(PiperAudioIntegrityError, "governed Piper voice"):
            self._adapter(runner).execute(request, {})
        self.assertEqual(runner.calls, [])

    def test_source_audio_is_never_accepted_for_speech(self) -> None:
        runner = _FakePiperRunner()
        with self.assertRaisesRegex(PiperAudioIntegrityError, "no source audio bytes"):
            self._adapter(runner).execute(self._request(), {"source": b"unexpected"})
        self.assertEqual(runner.calls, [])

    def test_process_failure_timeout_output_limit_and_invalid_wav_fail_closed(self) -> None:
        cases = (
            (PiperProcessOutcome(2, b"", b"synthesis failed"), "exited with 2"),
            (PiperProcessOutcome(-9, b"", b"", timed_out=True), "timed out"),
            (
                PiperProcessOutcome(-9, b"", b"", output_limit_exceeded=True),
                "exceeded stdout/stderr budget",
            ),
        )
        for index, (outcome, pattern) in enumerate(cases):
            runtime = OriginForgeRuntime(self.root / f"failure-{index}")
            runtime.initialize("piper-failure-test")
            adapter = PiperAudioAdapter(
                runtime,
                self.profile,
                runtime_root=self.runtime_root,
                executable=self.executable,
                espeak_data_path=self.runtime_root / "espeak-ng-data",
                model_path=self.model_path,
                model_config_path=self.config_path,
                license_path=self.license_path,
                runner=_FakePiperRunner(synthesis_outcome=outcome),
            )
            with self.assertRaisesRegex(PiperAudioProcessError, pattern):
                adapter.execute(self._request(), {})

        invalid_runtime = OriginForgeRuntime(self.root / "invalid-wav")
        invalid_runtime.initialize("piper-invalid-wav-test")
        adapter = PiperAudioAdapter(
            invalid_runtime,
            self.profile,
            runtime_root=self.runtime_root,
            executable=self.executable,
            espeak_data_path=self.runtime_root / "espeak-ng-data",
            model_path=self.model_path,
            model_config_path=self.config_path,
            license_path=self.license_path,
            runner=_FakePiperRunner(invalid_output=True),
        )
        with self.assertRaisesRegex(PiperAudioIntegrityError, "not accepted PCM16 WAV"):
            adapter.execute(self._request(), {})

    def test_adapter_exposes_no_download_install_task_merge_or_release_surface(self) -> None:
        names = set(dir(self._adapter(_FakePiperRunner())))
        for forbidden in (
            "download",
            "install",
            "complete_task",
            "verify_task",
            "merge",
            "release",
            "adopt",
            "promote",
        ):
            self.assertNotIn(forbidden, names)


class BoundedPiperSubprocessRunnerTests(unittest.TestCase):
    def test_bounded_runner_delivers_exact_stdin_without_shell(self) -> None:
        runner = BoundedPiperSubprocessRunner()
        outcome = runner.run(
            (
                sys.executable,
                "-c",
                "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)",
            ),
            cwd=Path.cwd(),
            stdin_bytes=b"bounded input\n",
            timeout_seconds=5,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
        )
        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(outcome.stdout, b"bounded input\n")
        self.assertFalse(outcome.output_limit_exceeded)

    def test_stdout_overflow_kills_process_and_reports_limit(self) -> None:
        runner = BoundedPiperSubprocessRunner()
        outcome = runner.run(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*100000); sys.stdout.flush()",
            ),
            cwd=Path.cwd(),
            stdin_bytes=b"x\n",
            timeout_seconds=5,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
        )
        self.assertTrue(outcome.output_limit_exceeded)
        self.assertLessEqual(len(outcome.stdout), 1024)


if __name__ == "__main__":
    unittest.main()
