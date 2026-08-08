from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reviewer_run import ReviewerRunCoordinator
from .runtime import OriginForgeRuntime
from .specialist_evidence_store import SpecialistEvidenceStore, SpecialistEvidenceStoreError
from .specialist_store import SpecialistStore, SpecialistStoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.specialist_cli",
        description=(
            "Read-only inspection of isolated specialist contracts, frozen evidence, "
            "Reviewer reports, audits, and durable Reviewer Runs."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="show specialist catalog counts and Reviewer Run status")
    commands.add_parser("contract-list", help="list immutable specialist contracts")
    contract_show = commands.add_parser("contract-show", help="show one specialist contract")
    contract_show.add_argument("contract_id")

    commands.add_parser("evidence-list", help="list frozen evidence packages by contract ID")
    evidence_show = commands.add_parser("evidence-show", help="show one frozen evidence package")
    evidence_show.add_argument("contract_id")

    commands.add_parser("report-list", help="list structurally trusted Reviewer reports")
    report_show = commands.add_parser("report-show", help="show one Reviewer report")
    report_show.add_argument("report_id")

    commands.add_parser("audit-list", help="list independent Reviewer structural audits")
    audit_show = commands.add_parser("audit-show", help="show one Reviewer structural audit")
    audit_show.add_argument("audit_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _reviewer_runs(runtime: OriginForgeRuntime) -> list[dict[str, object]]:
    return [
        {
            "run_id": row["id"],
            "task_id": row["task_id"],
            "status": row["status"],
            "model_profile": row["model_profile"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }
        for row in runtime.list_runs()
        if row["role"] == ReviewerRunCoordinator.RUN_ROLE
    ]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    store = SpecialistStore(runtime)
    evidence_store = SpecialistEvidenceStore(store)

    try:
        if args.command == "status":
            _print(
                {
                    "contracts": len(store.list_contract_ids()),
                    "evidence_packages": len(evidence_store.list_contract_ids()),
                    "reports": len(store.list_report_ids()),
                    "audits": len(store.list_audit_ids()),
                    "reviewer_runs": _reviewer_runs(runtime),
                    "model_execution_enabled": False,
                    "production_mutation_enabled": False,
                    "automatic_blocking_gate_enabled": False,
                }
            )
            return 0

        if args.command == "contract-list":
            _print({"contracts": list(store.list_contract_ids())})
            return 0
        if args.command == "contract-show":
            _print(store.load_contract(args.contract_id).to_dict())
            return 0

        if args.command == "evidence-list":
            _print({"evidence_packages": list(evidence_store.list_contract_ids())})
            return 0
        if args.command == "evidence-show":
            _print(evidence_store.load(args.contract_id).to_dict())
            return 0

        if args.command == "report-list":
            _print({"reports": list(store.list_report_ids())})
            return 0
        if args.command == "report-show":
            _print(store.load_report(args.report_id).to_dict())
            return 0

        if args.command == "audit-list":
            _print({"audits": list(store.list_audit_ids())})
            return 0
        if args.command == "audit-show":
            _print(store.load_audit(args.audit_id).to_dict())
            return 0

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (SpecialistStoreError, SpecialistEvidenceStoreError, OSError, ValueError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
