from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import EXTERNAL_TOOL_IDS, ExternalToolConfig, load_config
from .db import SCHEMA_VERSION


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str


def _check(name: str, ok: bool, message: str) -> DoctorCheck:
    return DoctorCheck(name, "PASS" if ok else "FAIL", message)


def _tool_check(tool_id: str, tool_config: ExternalToolConfig) -> DoctorCheck:
    configured = tool_config.path(tool_id)
    if configured is None:
        return DoctorCheck(
            f"tool:{tool_id}",
            "SKIP",
            "not configured; capability is unavailable unless its adapter supplies a safe fallback",
        )
    path = Path(configured)
    if path.is_symlink() or not path.is_file():
        return DoctorCheck(
            f"tool:{tool_id}",
            "FAIL",
            f"configured path is missing, not a regular file, or is an alias: {path}",
        )
    return DoctorCheck(
        f"tool:{tool_id}",
        "PASS",
        f"configured absolute path is available (takes precedence for this capability): {path}",
    )


def inspect_project(project_root: str | Path) -> dict[str, object]:
    """Inspect project readiness without creating state or running migrations."""
    root = Path(project_root).resolve()
    state = root / ".origin-forge"
    config_path = state / "config.toml"
    database = state / "project.db"
    checks: list[DoctorCheck] = []

    checks.append(_check("project_root", root.is_dir(), f"project root: {root}"))
    checks.append(_check("state_directory", state.is_dir() and not state.is_symlink(), f"state directory: {state}"))
    checks.append(_check("config", config_path.is_file() and not config_path.is_symlink(), f"config: {config_path}"))

    if state.is_dir() and not state.is_symlink() and config_path.is_file() and not config_path.is_symlink():
        try:
            config = load_config(root)
        except (OSError, ValueError) as exc:
            checks.append(_check("config_parse", False, f"configuration is invalid: {exc}"))
        else:
            checks.append(_check("config_parse", True, f"configuration version {config.version}"))
            checks.extend(_tool_check(tool_id, config.external_tools) for tool_id in EXTERNAL_TOOL_IDS)

    journals = tuple(Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal"))
    active_journals = [str(path.name) for path in journals if path.exists() or path.is_symlink()]
    checks.append(_check("database_quiescent", not active_journals, "no active SQLite journal files" if not active_journals else f"active journal files: {', '.join(active_journals)}"))

    schema_version: int | None = None
    if database.is_file() and not database.is_symlink():
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5.0)
            row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
            schema_version = int(row[0]) if row else 0
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            integrity_ok = bool(integrity and integrity[0] == "ok")
            checks.append(_check("sqlite_integrity", integrity_ok, "SQLite integrity check passed" if integrity_ok else f"SQLite integrity check: {integrity[0] if integrity else 'no result'}"))
            project = connection.execute("SELECT 1 FROM projects WHERE root_path = ?", (str(root),)).fetchone()
            checks.append(_check("project_binding", project is not None, "repository root is bound to a project" if project else "repository root is not initialized"))
        except sqlite3.Error as exc:
            checks.append(_check("database_read", False, f"database cannot be inspected read-only: {exc}"))
        finally:
            if connection is not None:
                connection.close()
    else:
        checks.append(_check("database", False, f"database is missing or aliased: {database}"))

    if schema_version is not None:
        checks.append(_check("schema", schema_version == SCHEMA_VERSION, f"schema version {schema_version}; expected {SCHEMA_VERSION}"))

    failures = [item for item in checks if item.status == "FAIL"]
    return {
        "project_root": str(root),
        "ready": not failures,
        "schema_version": schema_version,
        "expected_schema_version": SCHEMA_VERSION,
        "checks": [asdict(item) for item in checks],
    }
