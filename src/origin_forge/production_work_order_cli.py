from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_work_order_builtin import build_builtin_dispatch_validator_registry
from .production_work_order_read import (
    ProductionWorkOrderReadError,
    inspect_work_order_currentness_readonly,
    read_dispatch_catalog,
    read_work_order,
    read_work_order_audit,
    work_order_read_status,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin-forge-work-orders",
        description="Read-only governed production WorkOrder inspection.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show non-creating WorkOrder evidence status")

    catalog = commands.add_parser(
        "dispatch-catalog-show",
        help="show one immutable dispatch-contract catalog",
    )
    catalog.add_argument("dispatch_catalog_id")

    contract = commands.add_parser(
        "contract-show",
        help="show one contract from an immutable dispatch catalog",
    )
    contract.add_argument("dispatch_catalog_id")
    contract.add_argument("contract_id")

    work_order = commands.add_parser(
        "work-order-show",
        help="show one immutable revalidated WorkOrder",
    )
    work_order.add_argument("work_order_id")

    audit = commands.add_parser(
        "work-order-audit-show",
        help="show one immutable independently revalidated WorkOrder audit",
    )
    audit.add_argument("audit_id")

    currentness = commands.add_parser(
        "work-order-currentness",
        help="inspect current Task/route/dependency eligibility without mutation",
    )
    currentness.add_argument("work_order_id")
    currentness.add_argument("audit_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    registry = build_builtin_dispatch_validator_registry()
    try:
        if args.command == "status":
            _print(work_order_read_status(runtime))
            return 0
        if args.command == "dispatch-catalog-show":
            catalog_value = read_dispatch_catalog(
                runtime,
                args.dispatch_catalog_id,
                registry,
            )
            _print({**catalog_value.to_dict(), "content_hash": catalog_value.content_hash})
            return 0
        if args.command == "contract-show":
            catalog = read_dispatch_catalog(
                runtime,
                args.dispatch_catalog_id,
                registry,
            )
            contract_value = catalog.contract(args.contract_id)
            _print({**contract_value.to_dict(), "content_hash": contract_value.content_hash})
            return 0
        if args.command == "work-order-show":
            work_order_value = read_work_order(runtime, args.work_order_id, registry)
            _print({**work_order_value.to_dict(), "content_hash": work_order_value.content_hash})
            return 0
        if args.command == "work-order-audit-show":
            audit_value = read_work_order_audit(runtime, args.audit_id, registry)
            _print({**audit_value.to_dict(), "content_hash": audit_value.content_hash})
            return 0
        if args.command == "work-order-currentness":
            currentness_value = inspect_work_order_currentness_readonly(
                runtime,
                args.work_order_id,
                args.audit_id,
                registry,
            )
            _print(currentness_value.to_dict())
            return 0
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ProductionWorkOrderReadError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
