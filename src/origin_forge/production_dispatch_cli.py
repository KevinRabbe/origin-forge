from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_dispatch_binding import build_builtin_dispatch_binder_registry
from .production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from .production_dispatch_read import (
    ProductionDispatchReadError,
    inspect_dispatch_binding_currentness_readonly,
    production_dispatch_read_status,
    read_dispatch_binding,
    read_dispatch_binding_audit,
    read_input_resolution,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin-forge-dispatch",
        description="Read-only governed dispatch input/binding inspection.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show non-creating Phase-34 evidence status")

    resolution = commands.add_parser(
        "input-resolution-show",
        help="show one immutable revalidated input-resolution bundle",
    )
    resolution.add_argument("input_resolution_id")

    binding = commands.add_parser(
        "binding-show",
        help="show one immutable revalidated dispatch binding",
    )
    binding.add_argument("dispatch_binding_id")

    audit = commands.add_parser(
        "binding-audit-show",
        help="show one immutable frozen binding audit",
    )
    audit.add_argument("binding_audit_id")

    currentness = commands.add_parser(
        "binding-currentness",
        help="inspect live eligibility without production mutation",
    )
    currentness.add_argument("input_resolution_id")
    currentness.add_argument("dispatch_binding_id")
    currentness.add_argument("binding_audit_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "status":
            _print(production_dispatch_read_status(runtime))
            return 0
        if args.command == "input-resolution-show":
            value = read_input_resolution(runtime, args.input_resolution_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "binding-show":
            value = read_dispatch_binding(runtime, args.dispatch_binding_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "binding-audit-show":
            value = read_dispatch_binding_audit(runtime, args.binding_audit_id)
            _print({**value.to_dict(), "content_hash": value.content_hash})
            return 0
        if args.command == "binding-currentness":
            value = inspect_dispatch_binding_currentness_readonly(
                runtime,
                args.input_resolution_id,
                args.dispatch_binding_id,
                args.binding_audit_id,
                build_dispatch_input_resolver_registry(),
                build_builtin_dispatch_binder_registry(),
            )
            _print(value.to_dict())
            return 0
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ProductionDispatchReadError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
