from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .playtest_models import (
    PlaytestOutcome,
    PlaytestScenario,
    PlaytestTelemetry,
    PlaytestTelemetryEvent,
    PlaytestTelemetryKind,
)
from .runtime_observation_models import canonical_bytes
from .runtime_observer import _WindowsProcessJob, sha256_file

_MAX_TELEMETRY_BYTES = 8 * 1024 * 1024


class PlaytestHarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlaytestHarnessExecution:
    scenario: PlaytestScenario
    telemetry: PlaytestTelemetry
    workspace_path: Path
    stdout_path: Path
    stderr_path: Path
    stdout_hash: str
    stderr_hash: str
    stdout_bytes: int
    stderr_bytes: int
    process_duration_ms: int
    exit_code: int | None
    timed_out: bool


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise PlaytestHarnessError(f"playtest path already exists: {path.name}")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _drain_bounded(
    stream: BinaryIO,
    target: bytearray,
    limit: int,
    overflow: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                return
            remaining = max(0, limit - len(target))
            if remaining:
                target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        try:
            process.terminate()
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 0.5
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 0.5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _exact_mapping(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PlaytestHarnessError(f"{label} must be a JSON object")
    if set(value) != expected:
        raise PlaytestHarnessError(f"{label} fields differ from frozen schema")
    return value


def _parse_telemetry(data: bytes) -> PlaytestTelemetry:
    if not data or len(data) > _MAX_TELEMETRY_BYTES:
        raise PlaytestHarnessError("telemetry JSON is outside byte bounds")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlaytestHarnessError("telemetry output is not valid UTF-8 JSON") from exc
    root = _exact_mapping(
        value,
        {
            "session_id",
            "scenario_hash",
            "harness_id",
            "harness_version",
            "harness_hash",
            "target_id",
            "target_version",
            "outcome",
            "duration_ms",
            "events",
        },
        "telemetry",
    )
    events_value = root["events"]
    if not isinstance(events_value, list):
        raise PlaytestHarnessError("telemetry events must be a JSON list")
    events: list[PlaytestTelemetryEvent] = []
    for index, raw_event in enumerate(events_value):
        event = _exact_mapping(
            raw_event,
            {"sequence", "at_ms", "kind", "subject_id", "value"},
            f"telemetry event {index}",
        )
        try:
            kind = PlaytestTelemetryKind(event["kind"])
        except (ValueError, TypeError) as exc:
            raise PlaytestHarnessError(f"telemetry event {index} has unknown kind") from exc
        events.append(
            PlaytestTelemetryEvent(
                sequence=event["sequence"],
                at_ms=event["at_ms"],
                kind=kind,
                subject_id=event["subject_id"],
                value=event["value"],
            )
        )
    try:
        outcome = PlaytestOutcome(root["outcome"])
    except (ValueError, TypeError) as exc:
        raise PlaytestHarnessError("telemetry outcome is invalid") from exc
    return PlaytestTelemetry(
        session_id=root["session_id"],
        scenario_hash=root["scenario_hash"],
        harness_id=root["harness_id"],
        harness_version=root["harness_version"],
        harness_hash=root["harness_hash"],
        target_id=root["target_id"],
        target_version=root["target_version"],
        outcome=outcome,
        duration_ms=root["duration_ms"],
        events=tuple(events),
    )


class CooperativePlaytestHarness:
    """Run one preconfigured semantic-input playtest harness.

    The adapter owns the executable, fixed argv, target identity, and harness
    identity. A scenario can select only controls from its frozen semantic
    whitelist; it cannot select executables, raw OS input codes, shell text,
    environment variables, scripts, or follow-up commands.
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        executable: Path,
        executable_hash: str,
        harness_id: str,
        harness_version: str,
        target_id: str,
        target_version: str,
        fixed_args: tuple[str, ...] = (),
    ):
        self.workspace_root = Path(workspace_root)
        self.executable = Path(executable)
        self.executable_hash = executable_hash
        self.harness_id = harness_id
        self.harness_version = harness_version
        self.target_id = target_id
        self.target_version = target_version
        args = tuple(fixed_args)
        if len(args) > 32:
            raise PlaytestHarnessError("fixed harness argv exceeds count limit")
        for value in args:
            if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
                raise PlaytestHarnessError("fixed harness argv contains invalid token")
        self.fixed_args = args
        if sha256_file(self.executable) != executable_hash:
            raise PlaytestHarnessError("configured harness executable hash does not match bytes")

    def _bind(self, scenario: PlaytestScenario) -> None:
        expected = (
            self.harness_id,
            self.harness_version,
            self.executable_hash,
            self.target_id,
            self.target_version,
        )
        actual = (
            scenario.harness_id,
            scenario.harness_version,
            scenario.harness_hash,
            scenario.target_id,
            scenario.target_version,
        )
        if actual != expected:
            raise PlaytestHarnessError("scenario does not match trusted harness identity")

    def _workspace(self, scenario: PlaytestScenario) -> Path:
        root = self.workspace_root
        if root.is_symlink():
            raise PlaytestHarnessError("playtest workspace root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        workspace = root / scenario.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise PlaytestHarnessError("playtest workspace already exists")
        workspace.mkdir()
        for name in ("request", "runtime", "logs"):
            (workspace / name).mkdir()
        (workspace / "runtime" / "home").mkdir()
        (workspace / "runtime" / "tmp").mkdir()
        return workspace

    def _synthetic_telemetry(
        self,
        scenario: PlaytestScenario,
        outcome: PlaytestOutcome,
        duration_ms: int,
    ) -> PlaytestTelemetry:
        return PlaytestTelemetry(
            session_id=scenario.session_id,
            scenario_hash=scenario.content_hash,
            harness_id=scenario.harness_id,
            harness_version=scenario.harness_version,
            harness_hash=scenario.harness_hash,
            target_id=scenario.target_id,
            target_version=scenario.target_version,
            outcome=outcome,
            duration_ms=min(max(duration_ms, 0), scenario.max_duration_ms),
            events=(),
        )

    def execute(self, scenario: PlaytestScenario) -> PlaytestHarnessExecution:
        if not isinstance(scenario, PlaytestScenario):
            raise TypeError("scenario must be a PlaytestScenario")
        self._bind(scenario)
        if sha256_file(self.executable) != self.executable_hash:
            raise PlaytestHarnessError("harness executable bytes drifted since adapter construction")
        workspace = self._workspace(scenario)
        scenario_path = workspace / "request" / "scenario.json"
        telemetry_path = workspace / "runtime" / "telemetry.json"
        stdout_path = workspace / "logs" / "stdout.log"
        stderr_path = workspace / "logs" / "stderr.log"
        _write_new(scenario_path, canonical_bytes(scenario.to_dict()))

        env = {
            "HOME": str(workspace / "runtime" / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": str(workspace / "runtime" / "tmp"),
            "ORIGIN_FORGE_PLAYTEST_SESSION_ID": scenario.session_id,
            "ORIGIN_FORGE_PLAYTEST_SCENARIO_HASH": scenario.content_hash,
            "ORIGIN_FORGE_PLAYTEST_SCENARIO": str(scenario_path),
            "ORIGIN_FORGE_PLAYTEST_TELEMETRY": str(telemetry_path),
        }
        popen_options = {
            "cwd": workspace,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        else:
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            [str(self.executable), *self.fixed_args], **popen_options
        )
        process_job = _WindowsProcessJob(process) if os.name == "nt" else None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        out_thread = threading.Thread(
            target=_drain_bounded,
            args=(process.stdout, stdout, scenario.max_log_bytes, overflow),
            daemon=True,
        )
        err_thread = threading.Thread(
            target=_drain_bounded,
            args=(process.stderr, stderr, scenario.max_log_bytes, overflow),
            daemon=True,
        )
        out_thread.start()
        err_thread.start()
        started = time.monotonic()
        deadline = started + scenario.max_duration_ms / 1000.0
        timed_out = False
        while process.poll() is None:
            if overflow.is_set():
                _terminate_group(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_group(process)
                break
            time.sleep(0.01)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _terminate_group(process)
            process.wait(timeout=2)
        _terminate_group(process)
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)
        process_duration_ms = max(0, int((time.monotonic() - started) * 1000))

        stdout_bytes = bytes(stdout)
        stderr_bytes = bytes(stderr)
        _write_new(stdout_path, stdout_bytes)
        _write_new(stderr_path, stderr_bytes)
        if overflow.is_set():
            raise PlaytestHarnessError("playtest log byte budget exceeded")

        if timed_out:
            telemetry = self._synthetic_telemetry(
                scenario, PlaytestOutcome.TIMEOUT, scenario.max_duration_ms
            )
            exit_code = None
        else:
            exit_code = process.returncode
            if exit_code is None:
                raise PlaytestHarnessError("playtest harness has no exit code after wait")
            if telemetry_path.exists():
                if telemetry_path.is_symlink() or not telemetry_path.is_file():
                    raise PlaytestHarnessError("telemetry output is unsafe")
                size = telemetry_path.stat().st_size
                if size <= 0 or size > _MAX_TELEMETRY_BYTES:
                    raise PlaytestHarnessError("telemetry output exceeds byte limit")
                data = telemetry_path.read_bytes()
                if len(data) != size:
                    raise PlaytestHarnessError("telemetry output changed while being read")
                telemetry = _parse_telemetry(data)
                telemetry.bind_scenario(scenario)
            elif exit_code == 0:
                raise PlaytestHarnessError("successful harness omitted telemetry output")
            else:
                telemetry = self._synthetic_telemetry(
                    scenario,
                    PlaytestOutcome.FAILED,
                    min(process_duration_ms, scenario.max_duration_ms),
                )

            expected_outcome = (
                PlaytestOutcome.COMPLETED if exit_code == 0 else PlaytestOutcome.FAILED
            )
            if telemetry.outcome is not expected_outcome:
                raise PlaytestHarnessError("telemetry outcome disagrees with harness exit state")

        for path in workspace.rglob("*"):
            if path.is_symlink():
                raise PlaytestHarnessError("playtest workspace contains a symlink")
        try:
            return PlaytestHarnessExecution(
                scenario=scenario,
                telemetry=telemetry,
                workspace_path=workspace,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_hash=_hash_bytes(stdout_bytes),
                stderr_hash=_hash_bytes(stderr_bytes),
                stdout_bytes=len(stdout_bytes),
                stderr_bytes=len(stderr_bytes),
                process_duration_ms=process_duration_ms,
                exit_code=exit_code,
                timed_out=timed_out,
            )
        finally:
            if process_job is not None:
                process_job.close()
