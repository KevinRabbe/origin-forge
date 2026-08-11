from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import OriginForgeRuntime
from .training_research_policy import (
    RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
    RUNTIME_REDACTED_PRODUCER_ID,
    RUNTIME_REDACTED_PRODUCER_VERSION,
    V1_ELIGIBILITY_POLICY_FINGERPRINT,
    V1_ELIGIBILITY_POLICY_ID,
    V1_ELIGIBILITY_POLICY_VERSION,
)
from .training_research_store import TrainingResearchStore


_CATEGORY_COMMANDS = {
    "trajectories": "trajectories",
    "eligibility-audits": "eligibility-audits",
    "datasets": "datasets",
    "experiment-plans": "experiment-plans",
    "experiment-reports": "experiment-reports",
}
_SHOW_COMMANDS = {
    "trajectory-show": "trajectories",
    "eligibility-audit-show": "eligibility-audits",
    "dataset-show": "datasets",
    "experiment-plan-show": "experiment-plans",
    "experiment-report-show": "experiment-reports",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.training_research_cli",
        description=(
            "Read-only inspection of Phase-29 offline training research evidence. "
            "This CLI cannot build datasets, execute training, load checkpoints, "
            "change model profiles/routing, or mutate production state."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="summarize immutable Phase-29 research evidence")
    for command in _CATEGORY_COMMANDS:
        commands.add_parser(command, help=f"list {command}")
    for command in _SHOW_COMMANDS:
        show = commands.add_parser(command, help=f"show one {command[:-5]}")
        show.add_argument("object_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        store = TrainingResearchStore(runtime)
        if args.command == "status":
            _print(
                {
                    "status": "OK",
                    "counts": {
                        category: len(store.list_objects(category))
                        for category in _CATEGORY_COMMANDS.values()
                    },
                    "trusted_trajectory_producer": {
                        "producer_id": RUNTIME_REDACTED_PRODUCER_ID,
                        "producer_version": RUNTIME_REDACTED_PRODUCER_VERSION,
                        "producer_fingerprint": RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
                    },
                    "dataset_eligibility_policy": {
                        "policy_id": V1_ELIGIBILITY_POLICY_ID,
                        "policy_version": V1_ELIGIBILITY_POLICY_VERSION,
                        "policy_fingerprint": V1_ELIGIBILITY_POLICY_FINGERPRINT,
                    },
                    "dataset_build_enabled": False,
                    "arbitrary_path_ingestion_enabled": False,
                    "training_execution_enabled": False,
                    "model_download_enabled": False,
                    "checkpoint_load_enabled": False,
                    "model_profile_mutation_enabled": False,
                    "routing_activation_enabled": False,
                    "secret_export_enabled": False,
                    "production_task_mutation_enabled": False,
                    "phase26_promotion_enabled": False,
                    "provenance_signing_enabled": False,
                    "merge_release_enabled": False,
                }
            )
            return 0
        category = _CATEGORY_COMMANDS.get(args.command)
        if category is not None:
            _print({"objects": list(store.list_objects(category))})
            return 0
        category = _SHOW_COMMANDS.get(args.command)
        if category is not None:
            _print(store.load(category, args.object_id))
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        _print({"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
