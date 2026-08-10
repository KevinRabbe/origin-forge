from __future__ import annotations

import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from origin_forge.runtime_observation_models import (
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeExitKind,
    RuntimeObservationRequest,
    RuntimeObservationStatus,
)
from origin_forge.runtime_observer import (
    LocalProcessRuntimeObserver,
    RuntimeObserverError,
    sha256_file,
)


PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP4z8DwHwAFAAH/VscvDQAAAABJRU5ErkJggg=="


class RuntimeObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.executable = Path(sys.executable).resolve(strict=True)
        self.executable_hash = sha256_file(self.executable)
        self.workspace_root = self.root / "state" / "runtime-observations"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _script(self, body: str) -> Path:
        path = self.root / f"target-{len(list(self.root.glob('target-*.py')))}.py"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def _adapter(self, script: Path) -> LocalProcessRuntimeObserver:
        return LocalProcessRuntimeObserver(
            workspace_root=self.workspace_root,
            executable=self.executable,
            executable_hash=self.executable_hash,
            backend_id="local-process",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            fixed_args=(str(script),),
        )

    def _request(self, captures=(), *, timeout_seconds: int = 5, max_log_bytes: int = 4096):
        return RuntimeObservationRequest.create(
            backend_id="local-process",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            executable_hash=self.executable_hash,
            timeout_seconds=timeout_seconds,
            max_log_bytes=max_log_bytes,
            captures=captures,
        )

    def test_real_no_shell_process_captures_logs_crash_and_timed_frames(self) -> None:
        script = self._script(
            f"""
            import base64
            import os
            from pathlib import Path

            root = Path(os.environ['ORIGIN_FORGE_CAPTURE_DIR'])
            png = base64.b64decode({PNG_BASE64!r})
            for name in ('shot.png', 'video/0001.png', 'video/0002.png'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
            print('runtime-stdout')
            print('runtime-stderr', file=__import__('sys').stderr)
            raise SystemExit(3)
            """
        )
        captures = (
            RuntimeCaptureSpec(
                "shot",
                RuntimeCaptureKind.SCREENSHOT,
                "captures/shot.png",
                100,
            ),
            RuntimeCaptureSpec(
                "frame-1",
                RuntimeCaptureKind.VIDEO_FRAME,
                "captures/video/0001.png",
                200,
            ),
            RuntimeCaptureSpec(
                "frame-2",
                RuntimeCaptureKind.VIDEO_FRAME,
                "captures/video/0002.png",
                300,
            ),
        )
        request = self._request(captures)
        execution = self._adapter(script).execute(request)
        result = execution.result
        self.assertEqual(result.status, RuntimeObservationStatus.SUCCEEDED)
        self.assertEqual(result.exit_kind, RuntimeExitKind.FAILED)
        self.assertEqual(result.exit_code, 3)
        self.assertEqual(len(result.captures), 3)
        self.assertEqual(result.captures[0].width, 1)
        self.assertEqual(result.captures[0].height, 1)
        self.assertGreaterEqual(result.performance.duration_ms, 0)
        self.assertGreaterEqual(result.performance.peak_rss_kib, 0)
        self.assertEqual(
            (execution.workspace_path / "logs" / "stdout.log").read_text(encoding="utf-8").strip(),
            "runtime-stdout",
        )
        self.assertEqual(
            (execution.workspace_path / "logs" / "stderr.log").read_text(encoding="utf-8").strip(),
            "runtime-stderr",
        )
        result.bind_request(request)

    def test_timeout_is_runtime_evidence_not_observer_failure(self) -> None:
        script = self._script(
            """
            import time
            print('before-timeout', flush=True)
            time.sleep(5)
            """
        )
        request = self._request(timeout_seconds=1)
        result = self._adapter(script).execute(request).result
        self.assertEqual(result.status, RuntimeObservationStatus.SUCCEEDED)
        self.assertEqual(result.exit_kind, RuntimeExitKind.TIMEOUT)
        self.assertIsNone(result.exit_code)
        self.assertGreaterEqual(result.performance.duration_ms, 900)

    def test_undeclared_capture_fails_closed(self) -> None:
        script = self._script(
            f"""
            import base64
            import os
            from pathlib import Path
            root = Path(os.environ['ORIGIN_FORGE_CAPTURE_DIR'])
            root.mkdir(parents=True, exist_ok=True)
            png = base64.b64decode({PNG_BASE64!r})
            (root / 'shot.png').write_bytes(png)
            (root / 'extra.png').write_bytes(png)
            """
        )
        request = self._request(
            (
                RuntimeCaptureSpec(
                    "shot",
                    RuntimeCaptureKind.SCREENSHOT,
                    "captures/shot.png",
                    0,
                ),
            )
        )
        with self.assertRaisesRegex(RuntimeObserverError, "capture set mismatch"):
            self._adapter(script).execute(request)

    def test_sparse_oversized_capture_is_rejected_before_read(self) -> None:
        script = self._script(
            """
            import os
            from pathlib import Path
            path = Path(os.environ['ORIGIN_FORGE_CAPTURE_DIR']) / 'shot.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('wb') as handle:
                handle.truncate(128 * 1024 * 1024 + 1)
            """
        )
        request = self._request(
            (
                RuntimeCaptureSpec(
                    "shot",
                    RuntimeCaptureKind.SCREENSHOT,
                    "captures/shot.png",
                    0,
                ),
            )
        )
        with self.assertRaisesRegex(RuntimeObserverError, "bounded PNG byte limit"):
            self._adapter(script).execute(request)

    def test_direct_child_exit_cleans_process_group_descendants(self) -> None:
        script = self._script(
            """
            import subprocess
            import sys
            subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            print('parent-exits', flush=True)
            """
        )
        started = time.monotonic()
        execution = self._adapter(script).execute(self._request())
        elapsed = time.monotonic() - started
        self.assertEqual(execution.result.exit_kind, RuntimeExitKind.EXITED)
        self.assertEqual(execution.result.exit_code, 0)
        self.assertLess(elapsed, 5.0)
        self.assertIn(
            b"parent-exits",
            (execution.workspace_path / "logs" / "stdout.log").read_bytes(),
        )

    def test_log_budget_blocks_without_unbounded_capture(self) -> None:
        script = self._script(
            """
            import sys
            sys.stdout.write('x' * 200000)
            sys.stdout.flush()
            """
        )
        request = self._request(max_log_bytes=1024)
        execution = self._adapter(script).execute(request)
        self.assertEqual(execution.result.status, RuntimeObservationStatus.BLOCKED)
        self.assertLessEqual(execution.result.stdout.byte_count, 1024)


if __name__ == "__main__":
    unittest.main()
