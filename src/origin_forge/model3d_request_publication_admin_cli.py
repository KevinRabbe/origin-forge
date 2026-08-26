from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_model3d_request_publication import (
    Model3DRequestPublicationError,
    approve_model3d_request_publication,
    publish_approved_model3d_request,
    read_model3d_request_approval,
    read_model3d_request_publication,
)
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.model3d_request_publication_admin_cli",
        description=(
            "Explicit HUMAN_OPERATOR publication of one exact audited Blender semantic proposal. "
            "This module does not dispatch Blender or accept its output."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    approve = commands.add_parser(
        "approve", help="approve one exact PASS-audited M3DREQPROP proposal"
    )
    approve.add_argument("--proposal-id", required=True)
    approve.add_argument("--audit-id")
    approve.add_argument("--operator-id")

    publish = commands.add_parser(
        "publish", help="publish one exact approval-frozen MODEL3DREQ request"
    )
    publish.add_argument("--approval-id", required=True)

    inspect = commands.add_parser("inspect", help="read one exact approval or publication")
    inspect_group = inspect.add_mutually_exclusive_group(required=True)
    inspect_group.add_argument("--approval-id")
    inspect_group.add_argument("--publication-id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "approve":
            value = approve_model3d_request_publication(
                runtime,
                args.proposal_id,
                audit_id=args.audit_id,
                operator_id=args.operator_id,
            )
        elif args.command == "publish":
            value = publish_approved_model3d_request(runtime, args.approval_id)
        elif args.approval_id is not None:
            value = read_model3d_request_approval(runtime, args.approval_id)
        else:
            value = read_model3d_request_publication(runtime, args.publication_id)
        _print(value.to_dict())
        return 0
    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (Model3DRequestPublicationError, OSError, ValueError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
