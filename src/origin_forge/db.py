from __future__ import annotations

import sqlite3
from pathlib import Path

from .conversation_gate_c_migration import CONVERSATION_GATE_C_MIGRATION
from .conversation_migration import CONVERSATION_GATE_A_MIGRATION
from .migrations import MIGRATIONS as BASE_MIGRATIONS
from .production_blender_adoption_migration import (
    BLENDER_PRODUCTION_ADOPTION_MIGRATION,
)
from .production_blender_dispatch_output_binding_migration import (
    BLENDER_DISPATCH_OUTPUT_BINDING_MIGRATION,
)
from .production_blender_task_acceptance_migration import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_MIGRATION,
)
from .production_design_specification_migration import DESIGN_SPECIFICATION_MIGRATION
from .production_model3d_request_authoring_migration import (
    MODEL3D_REQUEST_AUTHORING_MIGRATION,
)
from .production_model3d_request_publication_migration import (
    MODEL3D_REQUEST_PUBLICATION_MIGRATION,
)
from .production_pixelorama_adoption_migration import (
    PIXELORAMA_PRODUCTION_ADOPTION_MIGRATION,
)
from .production_pixelorama_dispatch_output_binding_migration import (
    PIXELORAMA_DISPATCH_OUTPUT_BINDING_MIGRATION,
)
from .production_pixelorama_task_acceptance_migration import (
    PIXELORAMA_PRODUCTION_TASK_ACCEPTANCE_MIGRATION,
)

MIGRATIONS = (
    *BASE_MIGRATIONS,
    PIXELORAMA_DISPATCH_OUTPUT_BINDING_MIGRATION,
    PIXELORAMA_PRODUCTION_ADOPTION_MIGRATION,
    PIXELORAMA_PRODUCTION_TASK_ACCEPTANCE_MIGRATION,
    BLENDER_DISPATCH_OUTPUT_BINDING_MIGRATION,
    BLENDER_PRODUCTION_ADOPTION_MIGRATION,
    CONVERSATION_GATE_A_MIGRATION,
    CONVERSATION_GATE_C_MIGRATION,
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_MIGRATION,
    DESIGN_SPECIFICATION_MIGRATION,
    MODEL3D_REQUEST_AUTHORING_MIGRATION,
    MODEL3D_REQUEST_PUBLICATION_MIGRATION,
)
SCHEMA_VERSION = MIGRATIONS[-1].version


def _schema_version(connection: sqlite3.Connection) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0]) if row else 0


def _backup_before_upgrade(connection: sqlite3.Connection, backup_path: str | Path) -> None:
    destination_path = Path(backup_path)
    if destination_path.exists() or destination_path.is_symlink():
        return
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(destination_path)
    try:
        connection.backup(destination)
        destination.commit()
    finally:
        destination.close()


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migrate(
    connection: sqlite3.Connection,
    now: str,
    *,
    backup_path: str | Path | None = None,
) -> None:
    current = _schema_version(connection)
    if backup_path is not None and current < SCHEMA_VERSION:
        _backup_before_upgrade(connection, backup_path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
    ).fetchone()
    current = int(row["version"] if isinstance(row, sqlite3.Row) else row[0])

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        with connection:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (migration.version, now),
            )
        current = migration.version

    if current != SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported schema version {current}; expected {SCHEMA_VERSION}"
        )
