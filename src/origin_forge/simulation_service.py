from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .runtime_observation_models import canonical_bytes
from .simulation_analysis import SimulationSummary, analyze_simulation
from .simulation_engine import ENGINE_ID, ENGINE_VERSION, run_simulation
from .simulation_models import SimulationResult, SimulationSpec
from .state import RunStatus, TaskStatus


class SimulationServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulationServiceResult:
    run_id: str
    spec_artifact_id: str
    result_artifact_id: str
    summary_artifact_id: str
    result_hash: str
    summary: SimulationSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "spec_artifact_id": self.spec_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "summary_artifact_id": self.summary_artifact_id,
            "result_hash": self.result_hash,
            "summary": self.summary.to_dict(),
            "production_task_verified": False,
            "task_status_changed": False,
            "semantic_balance_verified": False,
            "automatic_tuning_authorized": False,
            "canonical_asset_adopted": False,
        }


class SimulationService:
    """Persist deterministic simulation evidence without changing production truth."""

    RUN_ROLE = "SIMULATOR"

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)
        self.workspace_root = runtime.state_dir / "simulations"

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        if path.parent.is_symlink() or path.exists() or path.is_symlink():
            raise SimulationServiceError(
                f"simulation evidence path is not a fresh exact file: {path.name}"
            )
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _prepare_workspace(self, spec: SimulationSpec) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        root = self.workspace_root
        if root.is_symlink():
            raise SimulationServiceError("simulation root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        try:
            root_resolved = root.resolve(strict=True)
            root_resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SimulationServiceError(
                "simulation root is outside protected project state"
            ) from exc

        workspace = root / spec.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise SimulationServiceError("simulation workspace already exists")
        workspace.mkdir()
        (workspace / "request").mkdir()
        (workspace / "evidence").mkdir()
        try:
            workspace.resolve(strict=True).relative_to(root_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SimulationServiceError(
                "simulation workspace is outside protected simulation root"
            ) from exc
        return workspace

    @staticmethod
    def _exact_file(
        workspace: Path,
        path: Path,
        *,
        relative_path: tuple[str, ...],
        expected_bytes: bytes,
        label: str,
    ) -> Path:
        expected = workspace.joinpath(*relative_path)
        if path != expected:
            raise SimulationServiceError(
                f"{label} must use the exact governed simulation path"
            )
        if expected.parent.is_symlink() or expected.is_symlink() or not expected.is_file():
            raise SimulationServiceError(f"{label} is missing or unsafe")
        try:
            workspace_resolved = workspace.resolve(strict=True)
            expected_resolved = expected.resolve(strict=True)
            expected_resolved.relative_to(workspace_resolved)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SimulationServiceError(
                f"{label} is outside the exact simulation workspace"
            ) from exc
        if expected.stat().st_size != len(expected_bytes):
            raise SimulationServiceError(f"{label} bytes drifted")
        if expected.read_bytes() != expected_bytes:
            raise SimulationServiceError(f"{label} content drifted")
        return expected

    def execute(self, task_id: str, spec: SimulationSpec) -> SimulationServiceResult:
        if not validate_id(task_id, IdKind.TASK):
            raise ValueError("task_id must be a TASK ID")
        if not isinstance(spec, SimulationSpec):
            raise TypeError("spec must be a SimulationSpec")
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"simulation requires RUNNING Task; task {task_id} is {task['status']}"
            )

        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)
        try:
            workspace = self._prepare_workspace(spec)
            spec_bytes = canonical_bytes(spec.to_dict())
            spec_path = workspace / "request" / "spec.json"
            self._write_new(spec_path, spec_bytes)

            result = run_simulation(spec)
            if not isinstance(result, SimulationResult):
                raise SimulationServiceError("simulation engine returned an invalid result")
            result.bind_spec(spec)
            summary = analyze_simulation(spec, result)
            result_bytes = canonical_bytes(result.to_dict())
            summary_bytes = canonical_bytes(summary.to_dict())
            result_path = workspace / "evidence" / "result.json"
            summary_path = workspace / "evidence" / "summary.json"
            self._write_new(result_path, result_bytes)
            self._write_new(summary_path, summary_bytes)

            spec_path = self._exact_file(
                workspace,
                spec_path,
                relative_path=("request", "spec.json"),
                expected_bytes=spec_bytes,
                label="simulation specification",
            )
            result_path = self._exact_file(
                workspace,
                result_path,
                relative_path=("evidence", "result.json"),
                expected_bytes=result_bytes,
                label="simulation result",
            )
            summary_path = self._exact_file(
                workspace,
                summary_path,
                relative_path=("evidence", "summary.json"),
                expected_bytes=summary_bytes,
                label="simulation summary",
            )

            tool_versions = (f"simulation-engine:{ENGINE_ID}:{ENGINE_VERSION}",)
            spec_artifact_id = self.lineage.create_artifact(
                artifact_type="SIMULATION_SPEC",
                path_or_uri=str(spec_path),
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            result_artifact_id = self.lineage.create_artifact(
                artifact_type="SIMULATION_RESULT",
                path_or_uri=str(result_path),
                parent_artifact_id=spec_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="CAPTURED",
            )
            summary_artifact_id = self.lineage.create_artifact(
                artifact_type="SIMULATION_SUMMARY",
                path_or_uri=str(summary_path),
                parent_artifact_id=result_artifact_id,
                created_by_run_id=run_id,
                tool_versions=tool_versions,
                status="DERIVED",
            )

            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="simulation-structure",
                verifier="OriginForge.SimulationService",
                status="PASS",
                evidence={
                    "spec_id": spec.spec_id,
                    "spec_hash": spec.content_hash,
                    "session_id": spec.session_id,
                    "engine_id": ENGINE_ID,
                    "engine_version": ENGINE_VERSION,
                    "result_hash": result.content_hash,
                    "summary": summary.to_dict(),
                    "spec_artifact_id": spec_artifact_id,
                    "result_artifact_id": result_artifact_id,
                    "summary_artifact_id": summary_artifact_id,
                    "production_task_verified": False,
                    "semantic_balance_verified": False,
                    "automatic_tuning_authorized": False,
                    "canonical_asset_adopted": False,
                },
                run_id=run_id,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return SimulationServiceResult(
                run_id=run_id,
                spec_artifact_id=spec_artifact_id,
                result_artifact_id=result_artifact_id,
                summary_artifact_id=summary_artifact_id,
                result_hash=result.content_hash,
                summary=summary,
            )
        except Exception as exc:
            self._fail_run(run_id, spec, exc)
            raise

    def _fail_run(self, run_id: str, spec: SimulationSpec, exc: Exception) -> None:
        try:
            run = self.runtime.get_run(run_id)
            if run["status"] != RunStatus.RUNNING.value:
                return
            try:
                self.runtime.record_verification(
                    "RUN",
                    run_id,
                    verification_type="simulation-structure",
                    verifier="OriginForge.SimulationService",
                    status="FAIL",
                    evidence={
                        "spec_id": spec.spec_id,
                        "spec_hash": spec.content_hash,
                        "engine_id": spec.engine_id,
                        "engine_version": spec.engine_version,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2048],
                        "production_task_verified": False,
                        "semantic_balance_verified": False,
                        "automatic_tuning_authorized": False,
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
