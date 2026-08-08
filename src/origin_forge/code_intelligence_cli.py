from __future__ import annotations

import argparse
import json
from pathlib import Path

from .code_intelligence_factory import create_configured_lsp_backend
from .config import load_config
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.code_intelligence_cli"
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list operator-approved LSP server IDs")
    status = sub.add_parser(
        "status",
        help="probe one configured LSP server's local Podman image",
    )
    status.add_argument("server_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    config = load_config(runtime.project_root)

    if args.command == "list":
        print(
            json.dumps(
                {
                    "servers": [
                        {
                            "server_id": server.server_id,
                            "backend": server.backend,
                            "network_allowed": server.network,
                        }
                        for server in config.lsp_servers
                    ]
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "status":
        try:
            backend = create_configured_lsp_backend(runtime, args.server_id)
        except (KeyError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "server_id": args.server_id,
                        "available": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        available = backend.available()
        print(
            json.dumps(
                {
                    "server_id": args.server_id,
                    "available": available,
                    "provenance": backend.provenance,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if available else 3

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
