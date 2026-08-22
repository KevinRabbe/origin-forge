from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_blender_adoption import (
    BlenderProductionAdoptionError,
    GovernedBlenderProductionOutputAdopter,
)
from .production_blender_task_acceptor import (
    BlenderProductionTaskAcceptorError,
    GovernedBlenderProductionTaskAcceptor,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.blender_admin_cli",
        description=(
            "Explicit human-operated adoption and acceptance of governed Blender production outputs. "
            "Publication is create-only and never overwrites an existing project asset."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    adopt = commands.add_parser(
        "adopt-production-new",
        help="publish one exact terminal production Blender GLB as a new project file",
    )
    adopt.add_argument("--execution-id", required=True)
    adopt.add_argument("--destination", required=True)
    adopt.add_argument(
        "--max-source-bytes",
        type=int,
        default=512 * 1024 * 1024,
    )

    accept_task = commands.add_parser(
        "accept-production-task",
        help="explicitly accept one exact governed Blender production Task",
    )
    accept_task.add_argument("--execution-id", required=True)
    accept_task.add_argument("--actor-id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "adopt-production-new":
            result = GovernedBlenderProductionOutputAdopter(
                runtime,
                max_source_bytes=args.max_source_bytes,
            ).adopt_new(
                args.execution_id,
                args.destination,
            )
        elif args.command == "accept-production-task":
            result = GovernedBlenderProductionTaskAcceptor(runtime).accept(
                args.execution_id,
                actor_id=args.actor_id,
            )
        else:  # pragma: no cover - argparse owns the command set.
            raise ValueError("unsupported Blender admin command")
        _print(result.to_dict())
        return 0
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        BlenderProductionAdoptionError,
        BlenderProductionTaskAcceptorError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
