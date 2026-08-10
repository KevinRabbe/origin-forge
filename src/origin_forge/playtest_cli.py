from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime


_PLAYTEST_ARTIFACT_TYPES = {
    "PLAYTEST_SCENARIO",
    "PLAYTEST_TELEMETRY",
    "PLAYTEST_SUMMARY",
    "PLAYTEST_STDOUT_LOG",
    "PLAYTEST_STDERR_LOG",
}
_RUN_ROLE = "PLAYTESTER"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.playtest_cli",
        description=(
            "Read-only inspection of durable Phase-24 playtest evidence. "
            "This CLI has no play/run, raw input, scenario mutation, Task mutation, "
            "adoption, signing, merge, or release command."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="summarize durable playtest evidence")
    commands.add_parser("sessions", help="list durable PLAYTESTER Runs")
    run = commands.add_parser("run-show", help="show one PLAYTESTER Run and evidence")
    run.add_argument("run_id")
    artifact = commands.add_parser(
        "artifact-show", help="show one Phase-24 Artifact and verification evidence"
    )
    artifact.add_argument("artifact_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _runs(runtime: OriginForgeRuntime) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in runtime.list_runs():
        if run["role"] != _RUN_ROLE:
            continue
        rows.append(
            {
                "id": run["id"],
                "task_id": run["task_id"],
                "role": run["role"],
                "status": run["status"],
                "started_at": run["started_at"],
                "ended_at": run["ended_at"],
                "failure_reason": run["failure_reason"],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        lineage = OriginForgeLineage(runtime)
        if args.command == "status":
            by_type: dict[str, int] = {}
            for artifact in lineage.list_artifacts():
                artifact_type = artifact["type"]
                if artifact_type in _PLAYTEST_ARTIFACT_TYPES:
                    by_type[artifact_type] = by_type.get(artifact_type, 0) + 1
            _print(
                {
                    "status": "OK",
                    "playtest_run_count": len(_runs(runtime)),
                    "artifact_counts": dict(sorted(by_type.items())),
                    "playtest_execution_enabled": False,
                    "raw_os_input_enabled": False,
                    "scenario_mutation_enabled": False,
                    "task_mutation_enabled": False,
                    "semantic_game_quality_authority_enabled": False,
                    "canonical_asset_adoption_enabled": False,
                }
            )
            return 0
        if args.command == "sessions":
            _print({"runs": _runs(runtime)})
            return 0
        if args.command == "run-show":
            if not validate_id(args.run_id, IdKind.RUN):
                raise ValueError("run_id must be a RUN ID")
            run = runtime.get_run(args.run_id)
            if run["role"] != _RUN_ROLE:
                raise ValueError("run_id does not reference a Phase-24 PLAYTESTER Run")
            _print(
                {
                    "run": run,
                    "verifications": runtime.list_verifications("RUN", args.run_id),
                }
            )
            return 0
        if args.command == "artifact-show":
            if not validate_id(args.artifact_id, IdKind.ARTIFACT):
                raise ValueError("artifact_id must be an ART ID")
            artifact = lineage.get_artifact(args.artifact_id)
            if artifact["type"] not in _PLAYTEST_ARTIFACT_TYPES:
                raise ValueError(
                    "artifact_id does not reference a Phase-24 playtest Artifact"
                )
            _print(
                {
                    "artifact": artifact,
                    "verifications": lineage.list_artifact_verifications(args.artifact_id),
                }
            )
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        _print({"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
