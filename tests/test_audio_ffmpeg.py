from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from origin_forge.adapters.audio_ffmpeg import (
    BoundedSubprocessRunner,
    FfmpegAudioAdapter,
    FfmpegAudioIntegrityError,
    FfmpegAudioProcessError,
    ProcessOutcome,
)
from origin_forge.audio_models import (
    AudioOperation,
    AudioOperationRequest,
    AudioSourceRef,
)
from origin_forge.audio_profiles import (
    AudioProfileKind,
    GovernedAudioProfile,
)
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.runtime import OriginForgeRuntime


class _FakeRunner:
    def __init__(self, *, processing_outcome: ProcessOutcome | None = None, invalid_output: bool = False):
        self.calls: list[tuple[str, ...]] = []
        self.processing_outcome = processing_outcome
        self.invalid_output = invalid_output

    def run(
        self,
        argv,
        *,
        cwd,
        timeout_seconds,
        max_stdout_bytes,
        max_stderr_bytes,
    ):
        values = tuple(argv)
        self.calls.append(values)
        if values[1:] == ("-version",):
            return ProcessOutcome(
                returncode=0,
                stdout=b"ffmpeg version 8.1.2 Copyright test\n",
                stderr=b"",
            )
        if self.processing_outcome is not None:
            return self.processing_outcome
        output = Path(values[-1])
        if self.invalid_output:
            output.write_bytes(b"not-wav")
        else:
            rate = int(values[values.index("-ar") + 1])
            channels = int(values[values.index("-ac") + 1])
            pcm = b"".join(struct.pack("<h", value) for value in (0, 100, -100, 0))
            if channels == 2:
                pcm = b"".join(
                    struct.pack("<hh", value, value) for value in (0, 100, -100, 0)
                )
            output.write_bytes(
                encode_pcm16_wav(
                    channels=channels,
                    sample_rate=rate,
                    pcm_bytes=pcm,
                )
            )
        return ProcessOutcome(returncode=0, stdout=b"", stderr=b"")


class FfmpegAudioAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("ffmpeg-audio-test")
        self.executable = self.root / "ffmpeg-test-bin"
        self.executable.write_bytes(b"frozen fake ffmpeg binary")
        self.executable_hash = "sha256:" + hashlib.sha256(
            self.executable.read_bytes()
        ).hexdigest()
        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.FFMPEG_PCM16,
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            runtime_hash=self.executable_hash,
            target_sample_rate=8_000,
            target_channels=1,
        )
        self.source = encode_pcm16_wav(
            channels=1,
            sample_rate=16_000,
            pcm_bytes=b"".join(
                struct.pack("<h", value) for value in (1, 2, 3, 4, 5, 6, 7, 8)
            ),
        )
        inspection = inspect_pcm16_wav(self.source)
        self.source_ref = AudioSourceRef(
            source_id="source",
            relative_path="inputs/source.wav",
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _request(self) -> AudioOperationRequest:
        return AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            profile_id=self.profile.profile_id,
            profile_hash=self.profile.profile_hash,
            inputs=(self.source_ref,),
            target_sample_rate=8_000,
            target_channels=1,
            max_duration_ms=1_000,
            timeout_seconds=5,
            output_relative_path="exports/processed.wav",
        )

    def test_fixed_argv_processes_exact_source_and_independently_validates_output(self) -> None:
        runner = _FakeRunner()
        adapter = FfmpegAudioAdapter(
            self.runtime,
            self.profile,
            executable=self.executable,
            runner=runner,
        )
        request = self._request()
        execution = adapter.execute(request, {"source": self.source})
        execution.result.bind_request(request)

        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0], (str(self.executable), "-version"))
        argv = runner.calls[1]
        self.assertEqual(argv[0], str(self.executable))
        self.assertIn("-nostdin", argv)
        self.assertIn("+bitexact", argv)
        self.assertEqual(argv[argv.index("-map") + 1], "0:a:0")
        self.assertEqual(argv[argv.index("-map_metadata") + 1], "-1")
        self.assertEqual(argv[argv.index("-ac") + 1], "1")
        self.assertEqual(argv[argv.index("-ar") + 1], "8000")
        self.assertEqual(argv[argv.index("-c:a") + 1], "pcm_s16le")
        self.assertEqual(argv[argv.index("-f") + 1], "wav")
        self.assertIn("-n", argv)
        self.assertNotIn("shell", argv)

        output_path = execution.workspace_path / "exports" / "processed.wav"
        output = inspect_pcm16_wav(output_path.read_bytes())
        self.assertEqual(output.sample_rate, 8_000)
        self.assertEqual(output.channels, 1)
        self.assertEqual(output.content_hash, execution.result.outputs[0].content_hash)
        self.assertEqual(output.pcm_hash, execution.result.outputs[0].pcm_hash)
        self.assertEqual(
            (execution.workspace_path / "request" / "request.json").read_bytes(),
            __import__("origin_forge.audio_models", fromlist=["canonical_bytes"]).canonical_bytes(
                request.to_dict()
            ),
        )

    def test_source_drift_fails_before_any_process_call(self) -> None:
        runner = _FakeRunner()
        adapter = FfmpegAudioAdapter(
            self.runtime,
            self.profile,
            executable=self.executable,
            runner=runner,
        )
        with self.assertRaisesRegex(FfmpegAudioIntegrityError, "source audio bytes"):
            adapter.execute(self._request(), {"source": self.source + b"drift"})
        self.assertEqual(runner.calls, [])

    def test_executable_hash_and_version_are_governed(self) -> None:
        runner = _FakeRunner()
        self.executable.write_bytes(b"drift")
        adapter = FfmpegAudioAdapter(
            self.runtime,
            self.profile,
            executable=self.executable,
            runner=runner,
        )
        with self.assertRaisesRegex(FfmpegAudioIntegrityError, "executable hash"):
            adapter.execute(self._request(), {"source": self.source})
        self.assertEqual(runner.calls, [])

        self.executable.write_bytes(b"frozen fake ffmpeg binary")

        class BadVersionRunner(_FakeRunner):
            def run(self, argv, **kwargs):
                values = tuple(argv)
                self.calls.append(values)
                if values[1:] == ("-version",):
                    return ProcessOutcome(0, b"ffmpeg version 7.0\n", b"")
                return super().run(argv, **kwargs)

        bad = BadVersionRunner()
        adapter = FfmpegAudioAdapter(
            self.runtime,
            self.profile,
            executable=self.executable,
            runner=bad,
        )
        with self.assertRaisesRegex(FfmpegAudioIntegrityError, "version"):
            adapter.execute(self._request(), {"source": self.source})

    def test_process_failure_timeout_output_limit_and_invalid_wav_fail_closed(self) -> None:
        cases = (
            (
                ProcessOutcome(2, b"", b"codec failed"),
                "exited with 2",
            ),
            (
                ProcessOutcome(-9, b"", b"", timed_out=True),
                "timed out",
            ),
            (
                ProcessOutcome(-9, b"", b"", output_limit_exceeded=True),
                "exceeded stdout/stderr budget",
            ),
        )
        for outcome, pattern in cases:
            runtime_root = self.root / pattern.replace("/", "_").replace(" ", "_")
            runtime = OriginForgeRuntime(runtime_root)
            runtime.initialize("ffmpeg-failure-test")
            executable = runtime_root / "ffmpeg"
            executable.write_bytes(self.executable.read_bytes())
            runner = _FakeRunner(processing_outcome=outcome)
            adapter = FfmpegAudioAdapter(
                runtime,
                self.profile,
                executable=executable,
                runner=runner,
            )
            with self.assertRaisesRegex(FfmpegAudioProcessError, pattern):
                adapter.execute(self._request(), {"source": self.source})

        invalid_runtime = OriginForgeRuntime(self.root / "invalid-wav")
        invalid_runtime.initialize("invalid-wav-test")
        invalid_executable = self.root / "invalid-wav" / "ffmpeg"
        invalid_executable.write_bytes(self.executable.read_bytes())
        adapter = FfmpegAudioAdapter(
            invalid_runtime,
            self.profile,
            executable=invalid_executable,
            runner=_FakeRunner(invalid_output=True),
        )
        with self.assertRaisesRegex(FfmpegAudioIntegrityError, "not accepted PCM16 WAV"):
            adapter.execute(self._request(), {"source": self.source})

    def test_request_must_bind_governed_profile_before_process(self) -> None:
        runner = _FakeRunner()
        adapter = FfmpegAudioAdapter(
            self.runtime,
            self.profile,
            executable=self.executable,
            runner=runner,
        )
        request = AudioOperationRequest.create(
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            profile_id=self.profile.profile_id,
            profile_hash="sha256:" + "f" * 64,
            inputs=(self.source_ref,),
            target_sample_rate=8_000,
            target_channels=1,
        )
        with self.assertRaisesRegex(FfmpegAudioIntegrityError, "governed FFmpeg profile"):
            adapter.execute(request, {"source": self.source})
        self.assertEqual(runner.calls, [])


class BoundedSubprocessRunnerTests(unittest.TestCase):
    def test_stdout_overflow_kills_process_and_reports_limit(self) -> None:
        runner = BoundedSubprocessRunner()
        outcome = runner.run(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'x'*100000); sys.stdout.flush()",
            ),
            cwd=Path.cwd(),
            timeout_seconds=5,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
        )
        self.assertTrue(outcome.output_limit_exceeded)
        self.assertLessEqual(len(outcome.stdout), 1024)

    def test_timeout_kills_process(self) -> None:
        runner = BoundedSubprocessRunner()
        outcome = runner.run(
            (sys.executable, "-c", "import time; time.sleep(2)"),
            cwd=Path.cwd(),
            timeout_seconds=1,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
        )
        self.assertTrue(outcome.timed_out)


if __name__ == "__main__":
    unittest.main()
