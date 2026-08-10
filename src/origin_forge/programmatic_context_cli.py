from __future__ import annotations

import argparse
import json
from pathlib import Path

from .programmatic_context_runtime_adapter import runtime_run_show_descriptor
from .programmatic_context_store import ProgrammaticContextStore
from .runtime import OriginForgeRuntime


_CATEGORY_COMMANDS = {
    "requests": "requests",
    "catalogs": "catalogs",
    "programs": "programs",
    "packages": "packages",
    "executions": "executions",
    "experiments": "experiments",
}
_SHOW_COMMANDS = {
    "request-show": "requests",
    "catalog-show": "catalogs",
    "program-show": "programs",
    "package-show": "packages",
    "execution-show": "executions",
    "experiment-show": "experiments",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.programmatic_context_cli",
        description=(
            "Read-only inspection of Phase-27 programmatic-context evidence. "
            "This CLI cannot create or execute programs or mutate project state."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="summarize immutable programmatic-context evidence")
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
        store = ProgrammaticContextStore(runtime)
        if args.command == "status":
            descriptor = runtime_run_show_descriptor()
            _print(
                {
                    "status": "OK",
                    "counts": {
                        category: len(store.list_objects(category))
                        for category in _CATEGORY_COMMANDS.values()
                    },
                    "builtin_read_adapters": [descriptor.to_dict()],
                    "program_creation_enabled": False,
                    "program_execution_enabled": False,
                    "arbitrary_code_enabled": False,
                    "generic_tool_call_enabled": False,
                    "filesystem_traversal_enabled": False,
                    "sql_enabled": False,
                    "network_enabled": False,
                    "process_launch_enabled": False,
                    "production_task_mutation_enabled": False,
                    "production_activation_enabled": False,
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
