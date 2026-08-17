from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pixelorama_adoption import (
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from .production_pixelorama_adoption import (
    GovernedPixeloramaProductionOutputAdopter,
    PixeloramaProductionAdoptionError,
)
from .production_pixelorama_dispatch_output_binding_read import (
    PixeloramaDispatchOutputBindingReadError,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.pixelorama_admin_cli",
        description=(
            "Explicit human-operated Pixelorama media adoption. "
            "All publication is create-only and never overwrites an existing project asset."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    adopt = commands.add_parser(
        "adopt-new",
        help="publish one verified isolated Pixelorama output as a new project file",
    )
    adopt.add_argument("source_artifact_id")
    adopt.add_argument("destination_relative_path")
    adopt.add_argument(
        "--max-source-bytes",
        type=int,
        default=512 * 1024 * 1024,
    )

    production_adopt = commands.add_parser(
        "adopt-production-new",
        help="publish one exact terminal production Pixelorama dispatch output as a new project file",
    )
    production_adopt.add_argument("execution_id")
    production_adopt.add_argument("destination_relative_path")
    production_adopt.add_argument(
        "--max-source-bytes",
        type=int,
        default=512 * 1024 * 1024,
    )
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "adopt-new":
            result = GovernedPixeloramaOutputAdopter(
                runtime,
                max_source_bytes=args.max_source_bytes,
            ).adopt_new(
                args.source_artifact_id,
                args.destination_relative_path,
            )
        elif args.command == "adopt-production-new":
            result = GovernedPixeloramaProductionOutputAdopter(
                runtime,
                max_source_bytes=args.max_source_bytes,
            ).adopt_new(
                args.execution_id,
                args.destination_relative_path,
            )
        else:  # pragma: no cover - argparse owns the closed command set.
            raise ValueError("unsupported Pixelorama admin command")
        _print(result.to_dict())
        return 0
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        PixeloramaAdoptionError,
        PixeloramaProductionAdoptionError,
        PixeloramaDispatchOutputBindingReadError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
