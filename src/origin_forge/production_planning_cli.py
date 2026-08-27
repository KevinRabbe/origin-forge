from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_planning_inspection import (
    inspect_flow_dependency_graph,
    inspect_plan_audit,
    inspect_plan_materialization,
    inspect_plan_proposal,
    inspect_planning_input,
    inspect_production_planning_status,
    inspect_task_dependency_readiness,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin-forge-plan",
        description="Read-only Origin Forge production planning inspection.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show bounded planning/dependency counts")

    input_show = commands.add_parser("input-show", help="show one frozen PlanningInput")
    input_show.add_argument("planning_input_id")

    proposal_show = commands.add_parser("proposal-show", help="show one PlanProposal")
    proposal_show.add_argument("proposal_id")

    audit_show = commands.add_parser("audit-show", help="show one independently recomputed PlanAudit")
    audit_show.add_argument("audit_id")

    materialization_show = commands.add_parser(
        "materialization-show",
        help="show one relationally revalidated plan materialization",
    )
    materialization_show.add_argument("materialization_id")

    graph = commands.add_parser("graph", help="show one canonical Flow dependency graph")
    graph.add_argument("flow_id")

    readiness = commands.add_parser(
        "readiness",
        help="show deterministic dependency readiness for one Task",
    )
    readiness.add_argument("task_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "status":
            _print(inspect_production_planning_status(runtime).to_dict())
            return 0
        if args.command == "input-show":
            input_value = inspect_planning_input(runtime, args.planning_input_id)
            _print({**input_value.to_dict(), "content_hash": input_value.content_hash})
            return 0
        if args.command == "proposal-show":
            proposal_value = inspect_plan_proposal(runtime, args.proposal_id)
            _print({**proposal_value.to_dict(), "content_hash": proposal_value.content_hash})
            return 0
        if args.command == "audit-show":
            audit_value = inspect_plan_audit(runtime, args.audit_id)
            _print({**audit_value.to_dict(), "content_hash": audit_value.content_hash})
            return 0
        if args.command == "materialization-show":
            materialization_value = inspect_plan_materialization(
                runtime, args.materialization_id
            )
            _print(
                {
                    **materialization_value.to_dict(),
                    "content_hash": materialization_value.content_hash,
                }
            )
            return 0
        if args.command == "graph":
            _print(inspect_flow_dependency_graph(runtime, args.flow_id).to_dict())
            return 0
        if args.command == "readiness":
            _print(inspect_task_dependency_readiness(runtime, args.task_id).to_dict())
            return 0
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
