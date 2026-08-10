from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audio_profiles import AudioProfileError, AudioProfileStore
from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime


_AUDIO_ARTIFACT_TYPES = {
    "AUDIO_OPERATION_REQUEST",
    "AUDIO_OPERATION_RESULT",
    "AUDIO_OUTPUT_WAV",
    "ADOPTED_AUDIO_WAV",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.audio_cli",
        description=(
            "Read-only inspection of governed audio profiles and durable audio evidence. "
            "This CLI has no generate, speak, process, adopt, install, download, promotion, "
            "Task mutation, merge, or release command."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="summarize Phase-22 profile and evidence state")
    commands.add_parser("profile-list", help="list immutable governed audio profiles")
    show = commands.add_parser("profile-show", help="show one exact governed audio profile")
    show.add_argument("profile_id")
    show.add_argument("profile_hash")
    artifact = commands.add_parser(
        "artifact-show", help="show one audio Artifact and its verification evidence"
    )
    artifact.add_argument("artifact_id")
    commands.add_parser("operation-runs", help="list durable audio-operation Runs")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _runs(runtime: OriginForgeRuntime) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in runtime.list_runs():
        if run["role"] != "AUDIO_OPERATOR":
            continue
        rows.append(
            {
                "id": run["id"],
                "task_id": run["task_id"],
                "role": run["role"],
                "status": run["status"],
                "model_profile": run["model_profile"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "failure_reason": run["failure_reason"],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        store = AudioProfileStore(runtime)
        lineage = OriginForgeLineage(runtime)
        if args.command == "status":
            by_type: dict[str, int] = {}
            for artifact in lineage.list_artifacts():
                artifact_type = artifact["type"]
                if artifact_type in _AUDIO_ARTIFACT_TYPES:
                    by_type[artifact_type] = by_type.get(artifact_type, 0) + 1
            _print(
                {
                    "status": "OK",
                    "governed_profile_count": len(store.list()),
                    "audio_operation_run_count": len(_runs(runtime)),
                    "artifact_counts": dict(sorted(by_type.items())),
                    "audio_execution_enabled": False,
                    "profile_install_enabled": False,
                    "model_download_enabled": False,
                    "canonical_asset_adoption_enabled": False,
                    "task_mutation_enabled": False,
                }
            )
            return 0
        if args.command == "profile-list":
            _print(
                {
                    "profiles": [
                        {
                            "profile_id": value.profile_id,
                            "profile_hash": value.profile_hash,
                            "byte_count": value.byte_count,
                        }
                        for value in store.list()
                    ]
                }
            )
            return 0
        if args.command == "profile-show":
            _print(store.get(args.profile_id, args.profile_hash).to_dict())
            return 0
        if args.command == "artifact-show":
            if not validate_id(args.artifact_id, IdKind.ARTIFACT):
                raise ValueError("artifact_id must be an ART ID")
            artifact = lineage.get_artifact(args.artifact_id)
            if artifact["type"] not in _AUDIO_ARTIFACT_TYPES:
                raise ValueError("artifact_id does not reference a Phase-22 audio Artifact")
            _print(
                {
                    "artifact": artifact,
                    "verifications": lineage.list_artifact_verifications(args.artifact_id),
                }
            )
            return 0
        if args.command == "operation-runs":
            _print({"runs": _runs(runtime)})
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except (AudioProfileError, KeyError, OSError, RuntimeError, ValueError) as exc:
        _print({"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
