from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_capability_read import (
    ProductionCapabilityReadError,
    capability_read_status,
    inspect_task_route,
    read_capability_catalog,
    read_capability_policy,
    read_capability_route,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin-forge-capabilities",
        description="Read-only governed production capability routing inspection.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show non-creating capability evidence status")
    catalog = commands.add_parser("catalog-show", help="show one immutable capability catalog")
    catalog.add_argument("catalog_id")
    policy = commands.add_parser("policy-show", help="show one immutable routing policy")
    policy.add_argument("policy_id")
    route = commands.add_parser("route-show", help="show one immutable route decision")
    route.add_argument("route_decision_id")
    task_route = commands.add_parser(
        "task-route", help="derive one static route through immutable read boundaries"
    )
    task_route.add_argument("task_id")
    task_route.add_argument("catalog_id")
    task_route.add_argument("policy_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "status":
            _print(capability_read_status(runtime))
            return 0
        if args.command == "catalog-show":
            value = read_capability_catalog(runtime, args.catalog_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "policy-show":
            value = read_capability_policy(runtime, args.policy_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "route-show":
            value = read_capability_route(runtime, args.route_decision_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "task-route":
            value = inspect_task_route(
                runtime,
                args.task_id,
                args.catalog_id,
                args.policy_id,
            )
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, ProductionCapabilityReadError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
