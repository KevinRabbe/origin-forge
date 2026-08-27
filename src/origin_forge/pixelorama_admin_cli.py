from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pixelorama_adoption import (
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from .pixelorama_source import (
    PixeloramaSourceImportError,
    import_pixelorama_source,
    inspect_pixelorama_source,
    inspect_pixelorama_source_history,
    replace_pixelorama_source,
)
from .production_pixelorama_adoption import (
    GovernedPixeloramaProductionOutputAdopter,
    PixeloramaProductionAdoptionError,
)
from .production_pixelorama_dispatch_output_binding_read import (
    PixeloramaDispatchOutputBindingReadError,
)
from .production_pixelorama_provenance_signer import (
    GovernedPixeloramaProductionProvenanceSigner,
    PixeloramaProductionProvenanceSigningError,
)
from .production_pixelorama_task_acceptor import (
    GovernedPixeloramaProductionTaskAcceptor,
    PixeloramaProductionTaskAcceptorError,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.pixelorama_admin_cli",
        description=(
            "Explicit human-operated Pixelorama media adoption, acceptance, and provenance signing. "
            "Publication is create-only and never overwrites an existing project asset; provenance "
            "signing grants no release authority."
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

    production_accept = commands.add_parser(
        "accept-production-task",
        help="accept one current governed Pixelorama production task",
    )
    production_accept.add_argument("execution_id")

    sign_provenance = commands.add_parser(
        "sign-production-provenance",
        help="cryptographically sign one exact terminally accepted Pixelorama production Artifact",
    )
    sign_provenance.add_argument("--execution-id", required=True)
    sign_provenance.add_argument("--certificate-id", required=True)
    sign_provenance.add_argument(
        "--operational-private-key",
        required=True,
        type=Path,
        dest="operational_private_key",
    )

    source_import = commands.add_parser(
        "source-import",
        help="register an existing project-contained .pxo source as governed evidence",
    )
    source_import.add_argument("source_path")

    source_inspect = commands.add_parser(
        "source-inspect",
        help="inspect one governed Pixelorama source without mutation",
    )
    source_inspect.add_argument("artifact_id")

    source_history = commands.add_parser(
        "source-history",
        help="inspect the immutable Pixelorama source revision chain",
    )
    source_history.add_argument("artifact_id")

    source_replace = commands.add_parser(
        "source-replace",
        help="register a new immutable .pxo source revision linked to a prior source",
    )
    source_replace.add_argument("previous_artifact_id")
    source_replace.add_argument("source_path")
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
        elif args.command == "accept-production-task":
            result = GovernedPixeloramaProductionTaskAcceptor(runtime).accept(
                args.execution_id
            )
        elif args.command == "sign-production-provenance":
            result = GovernedPixeloramaProductionProvenanceSigner(runtime).sign(
                args.execution_id,
                args.certificate_id,
                operational_private_key_handle=args.operational_private_key,
            )
        elif args.command == "source-import":
            result = import_pixelorama_source(runtime, args.source_path)
        elif args.command == "source-inspect":
            result = inspect_pixelorama_source(runtime, args.artifact_id)
        elif args.command == "source-history":
            result = inspect_pixelorama_source_history(runtime, args.artifact_id)
        elif args.command == "source-replace":
            result = replace_pixelorama_source(
                runtime,
                args.previous_artifact_id,
                args.source_path,
            )
        else:  # pragma: no cover - argparse owns the closed command set.
            raise ValueError("unsupported Pixelorama admin command")
        _print(result if isinstance(result, dict) else result.to_dict())
        return 0
    except PixeloramaProductionProvenanceSigningError as exc:
        _print({"error": exc.code.value, "detail": str(exc)})
        return 2
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        PixeloramaAdoptionError,
        PixeloramaProductionAdoptionError,
        PixeloramaDispatchOutputBindingReadError,
        PixeloramaProductionTaskAcceptorError,
        PixeloramaSourceImportError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
