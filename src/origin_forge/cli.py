from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import OriginForgeStore

STATE_DIR = ".origin-forge"
DB_NAME = "project.db"


def _db_path(project_root: Path) -> Path:
    return project_root / STATE_DIR / DB_NAME


def _store(project_root: Path) -> OriginForgeStore:
    return OriginForgeStore(_db_path(project_root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="origin-forge")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser(
        "init", help="initialize Origin Forge state for a project"
    )
    init_parser.add_argument("--name", help="project name (default: directory name)")

    sub.add_parser("status", help="show durable runtime status")
    sub.add_parser("recover", help="inspect interrupted RUNNING records")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    store = _store(root)

    if args.command == "init":
        project_id = store.initialize_project(args.name or root.name, root)
        print(
            json.dumps(
                {"project_id": project_id, "database": str(store.db_path)}, indent=2
            )
        )
        return 0

    if args.command == "status":
        print(json.dumps(store.status_summary(), indent=2, sort_keys=True))
        return 0

    if args.command == "recover":
        findings = [finding.__dict__ for finding in store.recovery_findings()]
        print(json.dumps({"findings": findings}, indent=2, sort_keys=True))
        return 1 if findings else 0

    raise AssertionError(f"unhandled command {args.command}")
