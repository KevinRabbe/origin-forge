from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import SCHEMA_VERSION
from .runtime import OriginForgeRuntime


class ProductionReadGuardError(RuntimeError):
    pass


def existing_config_path(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    state = root / ".origin-forge"
    config = state / "config.toml"
    if state.is_symlink() or not state.is_dir():
        raise ProductionReadGuardError("Origin Forge state directory is missing or aliased")
    if config.is_symlink() or not config.is_file():
        raise ProductionReadGuardError("Origin Forge config is missing or aliased")
    try:
        resolved_state = state.resolve(strict=True)
        resolved_config = config.resolve(strict=True)
        resolved_config.relative_to(resolved_state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionReadGuardError("Origin Forge config escaped protected state") from exc
    return resolved_config


def ensure_production_runtime_readable(runtime: OriginForgeRuntime) -> None:
    """Fail closed unless existing runtime state can be inspected without migration.

    The preflight deliberately uses a SQLite read-only URI and never calls
    OriginForgeStore.open()/session(), because those normal runtime paths may
    create the database or apply migrations. Phase 30 may inspect only a project
    that has already been initialized and migrated by an authoritative runtime
    path.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    existing_config_path(runtime.project_root)
    state = runtime.state_dir
    database = runtime.store.db_path
    if database.is_symlink() or not database.is_file():
        raise ProductionReadGuardError("Origin Forge database is missing or aliased")
    try:
        resolved_state = state.resolve(strict=True)
        resolved_database = database.resolve(strict=True)
        resolved_database.relative_to(resolved_state)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionReadGuardError("Origin Forge database escaped protected state") from exc

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            resolved_database.as_uri() + "?mode=ro",
            uri=True,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ProductionReadGuardError(
                "Origin Forge database schema is unavailable to read-only inspection"
            ) from exc
        version = 0 if row is None else int(row["version"])
        if version != SCHEMA_VERSION:
            raise ProductionReadGuardError(
                f"Origin Forge schema {version} is not current; authoritative migration to {SCHEMA_VERSION} is required before cockpit inspection"
            )
        project = connection.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise ProductionReadGuardError(
                "project is not initialized for this repository root"
            )
    except sqlite3.Error as exc:
        raise ProductionReadGuardError(
            "Origin Forge database cannot be opened read-only"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
