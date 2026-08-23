from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cli as legacy_cli
from .production_goal_bootstrap import (
    GoalBootstrapOperatorError,
    bootstrap_goal,
    goal_bootstrap_status,
)
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .service import StaleRevision


def _print(value: object, *, stream=None) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True, default=str),
        file=stream or sys.stdout,
    )


def _special_command(argv: list[str]) -> bool:
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--project-root":
            index += 2
            continue
        if value.startswith("--project-root="):
            index += 1
            continue
        break
    return argv[index : index + 2] in (
        ["goal", "bootstrap"],
        ["goal", "bootstrap-status"],
    )


def _build_special_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="origin-forge")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    goal = sub.add_parser("goal", help="manage goals").add_subparsers(
        dest="goal_command", required=True
    )
    bootstrap = goal.add_parser(
        "bootstrap",
        help="explicitly advance one Goal through governed Phase-45 bootstrap",
    )
    bootstrap.add_argument("goal_id")
    status = goal.add_parser(
        "bootstrap-status",
        help="show read-only governed bootstrap status for one Goal",
    )
    status.add_argument("goal_id")
    return parser


def _run_special(argv: list[str]) -> int:
    args = _build_special_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    if args.goal_command == "bootstrap":
        result = bootstrap_goal(runtime, args.goal_id)
        _print(result.to_dict())
        return 0 if result.ready else 4 if result.terminal else 0
    if args.goal_command == "bootstrap-status":
        _print(goal_bootstrap_status(runtime, args.goal_id).to_dict())
        return 0
    raise AssertionError("unhandled Phase-45E command")


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not _special_command(values):
        return legacy_cli.main(values)
    try:
        return _run_special(values)
    except GoalBootstrapOperatorError as exc:
        _print({"error": "INVALID_INPUT", "message": str(exc)}, stream=sys.stderr)
        return 7
    except StaleRevision as exc:
        _print({"error": "INVALID_STATE", "message": str(exc)}, stream=sys.stderr)
        return 4
    except RuntimeInvariantError as exc:
        _print({"error": "INVARIANT_VIOLATION", "message": str(exc)}, stream=sys.stderr)
        return 5
    except ValueError as exc:
        _print({"error": "INVALID_INPUT", "message": str(exc)}, stream=sys.stderr)
        return 7
