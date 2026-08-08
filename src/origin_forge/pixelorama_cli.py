from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pixelorama_bridge import (
    PixeloramaBridgeIntegrityError,
    PixeloramaBridgeProfile,
    PixeloramaBridgeUnavailable,
)
from .pixelorama_models import BridgeOperation
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.pixelorama_cli",
        description=(
            "Read-only inspection of a configured trusted Pixelorama bridge. "
            "This surface never launches the editor or mutates project state."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="verify one trusted Pixelorama bridge installation")
    status.add_argument("--bridge-id", required=True)
    status.add_argument("--bridge-version", required=True)
    status.add_argument("--bridge-fingerprint", required=True)
    status.add_argument("--pixelorama-executable", type=Path, required=True)
    status.add_argument("--bridge-package", type=Path, required=True)
    status.add_argument(
        "--allow-operation",
        action="append",
        choices=[value.value for value in BridgeOperation],
        required=True,
    )
    status.add_argument("--launcher-arg", action="append", default=[])
    status.add_argument("--timeout-seconds", type=int, default=60)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        profile = PixeloramaBridgeProfile(
            bridge_id=args.bridge_id,
            bridge_version=args.bridge_version,
            bridge_fingerprint=args.bridge_fingerprint,
            pixelorama_executable=args.pixelorama_executable,
            bridge_package=args.bridge_package,
            allowed_operations=tuple(
                BridgeOperation(value) for value in args.allow_operation
            ),
            launcher_args=tuple(args.launcher_arg),
            timeout_seconds=args.timeout_seconds,
        )
        executable, package = profile.verify_installation()
        _print(
            {
                "status": "AVAILABLE",
                "bridge_id": profile.bridge_id,
                "bridge_version": profile.bridge_version,
                "bridge_fingerprint": profile.bridge_fingerprint,
                "protocol_version": profile.protocol_version,
                "pixelorama_executable": str(executable),
                "bridge_package": str(package),
                "allowed_operations": [
                    value.value for value in profile.allowed_operations
                ],
                "editor_launched": False,
                "media_workspace_created": False,
                "project_state_changed": False,
                "model_execution_enabled": False,
                "plugin_install_enabled": False,
            }
        )
        return 0
    except (
        PixeloramaBridgeIntegrityError,
        PixeloramaBridgeUnavailable,
        OSError,
        ValueError,
    ) as exc:
        _print({"status": "UNAVAILABLE", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
