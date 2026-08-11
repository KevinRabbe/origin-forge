from __future__ import annotations

import argparse
import json
from pathlib import Path

from .production_interface_server import create_production_interface_server
from .production_interface_snapshot import build_production_interface_snapshot
from .runtime import OriginForgeRuntime, RuntimeInvariantError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="origin-forge-cockpit",
        description="Read-only Origin Forge production cockpit.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("snapshot", help="print one bounded read-only cockpit snapshot")
    serve = commands.add_parser("serve", help="serve the read-only cockpit on loopback")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        if args.command == "snapshot":
            snapshot = build_production_interface_snapshot(runtime)
            payload = dict(snapshot.to_dict())
            payload["content_hash"] = snapshot.content_hash
            _print(payload)
            return 0
        if args.command == "serve":
            server = create_production_interface_server(runtime, port=args.port)
            host, port = server.server_address[:2]
            print(f"Origin Forge read-only cockpit: http://{host}:{port}/")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
            finally:
                server.server_close()
            return 0
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, RuntimeInvariantError) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
