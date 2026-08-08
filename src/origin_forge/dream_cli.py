from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dream_generation import DreamGenerationBuilder
from .dream_models import DreamBudget
from .dream_planner import DreamPlanningCoordinator
from .dream_store import DreamStore
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.dream_cli",
        description=(
            "Plan and inspect proposal-only offline Dream consolidation. "
            "This CLI does not promote memory, modify Skills/policy/source, or run a generative Dream model."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser(
        "plan",
        help="freeze completed Run evidence and persist deterministic proposal-only Dream findings",
    )
    plan.add_argument("--run", action="append", required=True, dest="run_ids")
    plan.add_argument("--parent-generation")
    plan.add_argument("--window-start")
    plan.add_argument("--window-end")
    plan.add_argument("--max-runs", type=int, default=100)
    plan.add_argument("--max-evidence-bytes", type=int, default=4 * 1024 * 1024)
    plan.add_argument("--max-candidates", type=int, default=128)

    commands.add_parser("manifest-list", help="list stored immutable Dream input manifests")
    manifest_show = commands.add_parser("manifest-show", help="show one stored Dream input manifest")
    manifest_show.add_argument("manifest_id")

    commands.add_parser("candidate-list", help="list stored proposal-only Dream candidates")
    candidate_show = commands.add_parser("candidate-show", help="show one stored Dream candidate")
    candidate_show.add_argument("candidate_id")

    commands.add_parser("audit-list", help="list content-addressed Dream audit reports")
    audit_show = commands.add_parser("audit-show", help="show one stored Dream audit report")
    audit_show.add_argument("audit_id")

    commands.add_parser("memory-list", help="list stored immutable derived-memory entries")
    memory_show = commands.add_parser("memory-show", help="show one stored derived-memory entry")
    memory_show.add_argument("entry_id")

    commands.add_parser("generation-list", help="list immutable memory generations")
    generation_show = commands.add_parser("generation-show", help="show one immutable memory generation")
    generation_show.add_argument("generation_id")
    active = commands.add_parser(
        "active-memory",
        help="revalidate one generation ancestry and show its currently active derived-memory refs",
    )
    active.add_argument("generation_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    store = DreamStore(runtime)

    try:
        if args.command == "plan":
            budget = DreamBudget(
                max_runs=args.max_runs,
                max_total_evidence_bytes=args.max_evidence_bytes,
                max_candidates=args.max_candidates,
            )
            result = DreamPlanningCoordinator(runtime, store).plan(
                args.run_ids,
                parent_generation_id=args.parent_generation,
                budget=budget,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            _print(
                {
                    "manifest_id": result.manifest.manifest_id,
                    "manifest_hash": result.manifest.content_hash,
                    "plan_hash": result.content_hash,
                    "evidence_record_count": len(result.evidence_records),
                    "active_memory_entry_count": len(result.active_memory_entries),
                    "preprocess_finding_count": len(result.preprocess_report.findings),
                    "candidate_ids": [item.candidate_id for item in result.candidates],
                    "audit_ids": [store.audit_report_id(item) for item in result.audits],
                    "memory_generation_created": False,
                    "model_invoked": False,
                }
            )
            return 0

        if args.command == "manifest-list":
            _print({"manifests": list(store.list_manifest_ids())})
            return 0
        if args.command == "manifest-show":
            _print(store.load_manifest(args.manifest_id).to_dict())
            return 0

        if args.command == "candidate-list":
            _print({"candidates": list(store.list_candidate_ids())})
            return 0
        if args.command == "candidate-show":
            _print(store.load_candidate(args.candidate_id).to_dict())
            return 0

        if args.command == "audit-list":
            _print({"audits": list(store.list_audit_ids())})
            return 0
        if args.command == "audit-show":
            _print(store.load_audit(args.audit_id).to_dict())
            return 0

        if args.command == "memory-list":
            _print({"memory_entries": list(store.list_memory_entry_ids())})
            return 0
        if args.command == "memory-show":
            _print(store.load_memory_entry(args.entry_id).to_dict())
            return 0

        if args.command == "generation-list":
            _print({"generations": list(store.list_generation_ids())})
            return 0
        if args.command == "generation-show":
            _print(store.load_generation(args.generation_id).to_dict())
            return 0
        if args.command == "active-memory":
            snapshot = DreamGenerationBuilder(runtime, store).active_memory(args.generation_id)
            _print(
                {
                    "generation_id": args.generation_id,
                    "snapshot_hash": snapshot.content_hash,
                    "active_memory_refs": [item.to_dict() for item in snapshot.entries],
                }
            )
            return 0

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (OSError, RuntimeError, ValueError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
