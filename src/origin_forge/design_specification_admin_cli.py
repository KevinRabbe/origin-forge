from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_design_specification_acceptor import (
    GovernedDesignSpecificationAcceptanceError,
    GovernedDesignSpecificationAcceptor,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.design_specification_admin_cli",
        description=(
            "Explicit HUMAN_OPERATOR acceptance of one exact governed design specification. "
            "Acceptance grants no Planner execution, Task materialization, signing, or release authority."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    accept = commands.add_parser(
        "accept-design-specification",
        help="accept one exact PASS-audited current DESIGNSPEC candidate",
    )
    accept.add_argument("--design-specification-id", required=True)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "accept-design-specification":
            result = GovernedDesignSpecificationAcceptor(runtime).accept(
                args.design_specification_id
            )
        else:  # pragma: no cover - argparse owns the command set.
            raise ValueError("unsupported design specification admin command")
        _print(result.to_dict())
        return 0
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        GovernedDesignSpecificationAcceptanceError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
