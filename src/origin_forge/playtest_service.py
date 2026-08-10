from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .playtest_analysis import PlaytestSummary, analyze_playtest
from .playtest_harness import PlaytestHarnessExecution
from .playtest_models import PlaytestScenario, canonical_bytes
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .state import RunStatus, TaskStatus


class PlaytestServiceError(RuntimeError):
    pass


class PlaytestBackend(Protocol):
    def execute(self, scenario: PlaytestScenario) -> PlaytestHarnessExecution: ...


@dataclass(frozen=True)
class PlaytestServiceResult:
    run_id: str
    scenario_artifact_id: str
    telemetry_artifact_id: str
    summary_artifact_id: str
    stdout_artifact_id: str
    stderr_artifact_id: str
    telemetry_hash: str
    summary: PlaytestSummary
    outcome: str
    timed_out: bool
    exit_code: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "scenario_artifact_id": self.scenario_artifact_id,
            "telemetry_artifact_id": self.telemetry_artifact_id,
            "summary_artifact_id": self.summary_artifact_id,
            "stdout_artifact_id": self.stdout_artifact_id,
            "stderr_artifact_id": self.stderr_artifact_id,
            "telemetry_hash": self.telemetry_hash,
            "summary": self.summary.to_dict(),
            "outcome": self.outcome,
            "timed_out": self.timed_out,
            "exit_code": self.exit_code,
            "production_task_verified": False,
            "task_status_changed": False,
            "semantic_game_quality_verified": False,
            "canonical_asset_adopted": False,
        }


class PlaytestService:
    """Persist synthetic-player evidence without changing production Task truth."""

    RUN_ROLE = "PLAYTESTER"

    def __init__(self, runtime: OriginForgeRuntime, backend: PlaytestBackend):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not hasattr(backend, "execute"):
            raise TypeError("backend must provide execute(scenario)")
        self.runtime = runtime
        self.backend = backend
        self.lineage = OriginForgeLineage(runtime)
        self.workspace_root = runtime.state_dir / "playtests"

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise PlaytestServiceError(f"playtest evidence path already exists: {path.name}")
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _trusted_workspace(self, scenario: PlaytestScenario, returned: Path) -> Path:
        state = self.runtime.state_dir.resolve()
        root = self.workspace_root
        expected = root / scenario.workspace_id
        returned = Path(returned)
        if root.is_symlink() or expected.is_symlink() or returned.is_symlink():
            raise PlaytestServiceError("playtest workspace may not use symlinks")
        try:
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state)
            expected_resolved = expected.resolve(strict=True)
            expected_resolved.relative_to(root_resolved)
            returned_resolved = returned.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlaytestServiceError(
                "playtest workspace is not an existing protected project path"
            ) from exc
        if returned_resolved != expected_resolved:
            raise PlaytestServiceError(
                "playtest backend returned a workspace outside the exact PLAYWS ID"
            )
        return expected

    @staticmethod
    def _read_bound_file(
        path: Path,
        *,
        content_hash: str,
        byte_count: int,
        max_bytes: int,
        label: str,
    ) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise PlaytestServiceError(f"{label} is missing or unsafe")
        if not isinstance(byte_count, int) or byte_count < 0 or byte_count > max_bytes:
            raise PlaytestServiceError(f"{label} exceeds byte budget")
        size = path.stat().st_size
        if size != byte_count or size > max_bytes:
            raise PlaytestServiceError(f"{label} bytes drifted")
        data = path.read_bytes()
        if len(data) != size:
            raise PlaytestServiceError(f"{label} changed while being read")
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != content_hash:
            raise PlaytestServiceError(f"{label} hash drifted")
        return data

    def execute(self, task_id: str, scenario: PlaytestScenario) -> PlaytestServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(scenario, PlaytestScenario):
            raise TypeError("scenario must be a PlaytestScenario")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"playtesting requires RUNNING Task; task {task_id} is {task['status']}"
            )

        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)
        try:
            execution = self.backend.execute(scenario)
            if execution.scenario.content_hash != scenario.content_hash:
                raise PlaytestServiceError("backend returned a different playtest scenario")
            execution.telemetry.bind_scenario(scenario)
            workspace = self._trusted_workspace(scenario, execution.workspace_path)

            scenario_path = workspace / "request" / "scenario.json"
            scenario_bytes = canonical_bytes(scenario.to_dict())
            if scenario_path.is_symlink() or not scenario_path.is_file():
                raise PlaytestServiceError("playtest backend omitted scenario evidence")
            if scenario_path.stat().st_size != len(scenario_bytes):
                raise PlaytestServiceError("persisted playtest scenario bytes drifted")
            if scenario_path.read_bytes() != scenario_bytes:
                raise PlaytestServiceError("persisted playtest scenario bytes drifted")

            self._read_bound_file(
                execution.stdout_path,
                content_hash=execution.stdout_hash,
                byte_count=execution.stdout_bytes,
                max_bytes=scenario.max_log_bytes,
                label="playtest stdout log",
            )
            self._read_bound_file(
                execution.stderr_path,
                content_hash=execution.stderr_hash,
                byte_count=execution.stderr_bytes,
                max_bytes=scenario.max_log_bytes,
                label="playtest stderr log",
            )
            summary = analyze_playtest(scenario, execution.telemetry)
            evidence_dir = workspace / "evidence"
            evidence_dir.mkdir()
            telemetry_path = evidence_dir / "telemetry.json"
            summary_path = evidence_dir / "summary.json"
            self._write_new(telemetry_path, canonical_bytes(execution.telemetry.to_dict()))
            self._write_new(summary_path, canonical_bytes(summary.to_dict()))

            tool_versions = (
                f"playtest-harness:{scenario.harness_id}:{scenario.harness_version}",
                f"playtest-target:{scenario.target_id}:{scenario.target_version}",
                f"playtest-executable:{scenario.harness_hash}",
            )
            scenario_artifact_id = self.lineage.create_artifact(
                artifact_type="PLAYTEST_SCENARIO",
                path_or_uri=str(scenario_path),
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            telemetry_artifact_id = self.lineage.create_artifact(
                artifact_type="PLAYTEST_TELEMETRY",
                path_or_uri=str(telemetry_path),
                parent_artifact_id=scenario_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            summary_artifact_id = self.lineage.create_artifact(
                artifact_type="PLAYTEST_SUMMARY",
                path_or_uri=str(summary_path),
                parent_artifact_id=telemetry_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="DERIVED",
            )
            stdout_artifact_id = self.lineage.create_artifact(
                artifact_type="PLAYTEST_STDOUT_LOG",
                path_or_uri=str(execution.stdout_path),
                parent_artifact_id=telemetry_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            stderr_artifact_id = self.lineage.create_artifact(
                artifact_type="PLAYTEST_STDERR_LOG",
                path_or_uri=str(execution.stderr_path),
                parent_artifact_id=telemetry_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )

            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="playtest-structure",
                verifier="OriginForge.PlaytestService",
                status="PASS",
                evidence={
                    "scenario_id": scenario.scenario_id,
                    "scenario_hash": scenario.content_hash,
                    "session_id": scenario.session_id,
                    "telemetry_hash": execution.telemetry.content_hash,
                    "outcome": execution.telemetry.outcome.value,
                    "timed_out": execution.timed_out,
                    "exit_code": execution.exit_code,
                    "process_duration_ms": execution.process_duration_ms,
                    "summary": summary.to_dict(),
                    "scenario_artifact_id": scenario_artifact_id,
                    "telemetry_artifact_id": telemetry_artifact_id,
                    "summary_artifact_id": summary_artifact_id,
                    "stdout_artifact_id": stdout_artifact_id,
                    "stderr_artifact_id": stderr_artifact_id,
                    "production_task_verified": False,
                    "semantic_game_quality_verified": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return PlaytestServiceResult(
                run_id=run_id,
                scenario_artifact_id=scenario_artifact_id,
                telemetry_artifact_id=telemetry_artifact_id,
                summary_artifact_id=summary_artifact_id,
                stdout_artifact_id=stdout_artifact_id,
                stderr_artifact_id=stderr_artifact_id,
                telemetry_hash=execution.telemetry.content_hash,
                summary=summary,
                outcome=execution.telemetry.outcome.value,
                timed_out=execution.timed_out,
                exit_code=execution.exit_code,
            )
        except Exception as exc:
            self._fail_run(run_id, scenario, exc)
            raise

    def _fail_run(self, run_id: str, scenario: PlaytestScenario, exc: Exception) -> None:
        try:
            run = self.runtime.get_run(run_id)
            if run["status"] != RunStatus.RUNNING.value:
                return
            try:
                self.runtime.record_verification(
                    "RUN",
                    run_id,
                    verification_type="playtest-structure",
                    verifier="OriginForge.PlaytestService",
                    status="FAIL",
                    evidence={
                        "scenario_id": scenario.scenario_id,
                        "scenario_hash": scenario.content_hash,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "production_task_verified": False,
                        "semantic_game_quality_verified": False,
                        "canonical_asset_adopted": False,
                    },
                    run_id=run_id,
                )
            finally:
                self.runtime.finish_run(
                    run_id,
                    RunStatus.FAILED,
                    failure_reason=f"{type(exc).__name__}: {str(exc)[:2048]}",
                )
        except Exception:
            pass
