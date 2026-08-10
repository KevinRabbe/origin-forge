from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from origin_forge.runtime_observation_models import (
    RuntimeCaptureKind,
    RuntimeCaptureSpec,
    RuntimeExitKind,
    RuntimeObservationRequest,
    RuntimeObservationStatus,
)
from origin_forge.runtime_observer import LocalProcessRuntimeObserver, sha256_file


def test_abnormal_exit_before_capture_preserves_runtime_evidence() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        script = root / "crash-before-capture.py"
        script.write_text("raise SystemExit(7)\n", encoding="utf-8")
        executable = Path(sys.executable).resolve(strict=True)
        executable_hash = sha256_file(executable)
        adapter = LocalProcessRuntimeObserver(
            workspace_root=root / "state" / "runtime-observations",
            executable=executable,
            executable_hash=executable_hash,
            backend_id="local-process",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            fixed_args=(str(script),),
        )
        request = RuntimeObservationRequest.create(
            backend_id="local-process",
            backend_version="1",
            target_id="fixture-game",
            target_version="1",
            executable_hash=executable_hash,
            captures=(
                RuntimeCaptureSpec(
                    capture_id="late-shot",
                    kind=RuntimeCaptureKind.SCREENSHOT,
                    relative_path="captures/late-shot.png",
                    timestamp_ms=1000,
                ),
            ),
        )
        result = adapter.execute(request).result
        assert result.status is RuntimeObservationStatus.SUCCEEDED
        assert result.exit_kind is RuntimeExitKind.FAILED
        assert result.exit_code == 7
        assert result.captures == ()
        result.bind_request(request)
