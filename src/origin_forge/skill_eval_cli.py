from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import OriginForgeRuntime
from .skill_eval_replay import SkillEvalReplayInspector
from .skill_eval_store import SkillEvalStore, SkillEvalStoreError
from .skill_evaluation import SkillEvalCase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m origin_forge.skill_eval_cli")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("case-list", help="list immutable Skill eval case IDs")
    show_case = commands.add_parser("case-show", help="show one immutable Skill eval case")
    show_case.add_argument("case_id")

    add_case = commands.add_parser("case-add", help="create one immutable operator-owned eval case")
    add_case.add_argument("case_id")
    add_case.add_argument("--objective", required=True)
    add_case.add_argument("--acceptance", action="append", default=[])
    add_case.add_argument("--constraint", action="append", default=[])
    add_case.add_argument("--capability", action="append", default=[])
    add_case.add_argument("--context", action="append", default=[])
    add_case.add_argument("--tag", action="append", default=[])

    commands.add_parser("report-list", help="list content-addressed Skill benchmark reports")
    show_report = commands.add_parser("report-show", help="show one stored benchmark envelope")
    show_report.add_argument("report_id")
    report_status = commands.add_parser(
        "report-status",
        help="check report integrity and whether live cases/Skills are still replayable",
    )
    report_status.add_argument("report_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    store = SkillEvalStore(runtime)
    inspector = SkillEvalReplayInspector(runtime, store=store)

    try:
        if args.command == "case-list":
            _print({"cases": list(store.list_case_ids())})
            return 0

        if args.command == "case-show":
            case = store.load_case(args.case_id)
            _print({"case": case.canonical_dict(), "case_hash": case.content_hash})
            return 0

        if args.command == "case-add":
            case = SkillEvalCase(
                case_id=args.case_id,
                objective=args.objective,
                acceptance_criteria=tuple(args.acceptance),
                constraints=tuple(args.constraint),
                required_capabilities=tuple(args.capability),
                context_paths=tuple(args.context),
                tags=tuple(args.tag),
            )
            path = store.put_case(case)
            _print(
                {
                    "case_id": case.case_id,
                    "case_hash": case.content_hash,
                    "path": str(path),
                }
            )
            return 0

        if args.command == "report-list":
            _print({"reports": list(inspector.list_report_ids())})
            return 0

        if args.command == "report-show":
            _print(inspector.load_report_envelope(args.report_id))
            return 0

        if args.command == "report-status":
            status = inspector.inspect(args.report_id)
            _print(
                {
                    "report_id": status.report_id,
                    "content_hash": status.content_hash,
                    "suite_hash": status.suite_hash,
                    "replayable": status.replayable,
                    "stale_case_ids": list(status.stale_case_ids),
                    "stale_skill_refs": list(status.stale_skill_refs),
                }
            )
            return 0 if status.replayable else 4

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (ValueError, SkillEvalStoreError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
