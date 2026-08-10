from __future__ import annotations

import argparse
import json
from pathlib import Path

from .harness_workshop_evaluators import trusted_workshop_protocols
from .harness_workshop_store import HarnessWorkshopStore
from .runtime import OriginForgeRuntime


_CATEGORY_COMMANDS = {
    "candidates": "candidates",
    "plans": "plans",
    "reports": "reports",
    "audits": "audits",
    "decisions": "decisions",
}
_SHOW_COMMANDS = {
    "candidate-show": "candidates",
    "plan-show": "plans",
    "report-show": "reports",
    "audit-show": "audits",
    "decision-show": "decisions",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.harness_workshop_cli",
        description=(
            "Read-only inspection of Phase-26 Skill & Harness Workshop evidence. "
            "This CLI cannot create/evaluate/promote/activate components or mutate Tasks."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="summarize immutable workshop evidence")
    for command in _CATEGORY_COMMANDS:
        commands.add_parser(command, help=f"list workshop {command}")
    for command in _SHOW_COMMANDS:
        show = commands.add_parser(command, help=f"show one workshop {command[:-5]}")
        show.add_argument("object_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        store = HarnessWorkshopStore(runtime)
        if args.command == "status":
            counts = {
                category: len(store.list_objects(category))
                for category in _CATEGORY_COMMANDS.values()
            }
            _print(
                {
                    "status": "OK",
                    "counts": counts,
                    "trusted_evaluator_protocols": trusted_workshop_protocols(),
                    "candidate_creation_enabled": False,
                    "evaluation_execution_enabled": False,
                    "promotion_execution_enabled": False,
                    "production_activation_enabled": False,
                    "skill_install_enabled": False,
                    "prompt_mutation_enabled": False,
                    "routing_mutation_enabled": False,
                    "context_mutation_enabled": False,
                    "task_mutation_enabled": False,
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
