from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .conversation_gate_c_migration import CONVERSATION_GATE_C_MIGRATION
from .conversation_migration import CONVERSATION_GATE_A_MIGRATION
from .migration_hash_migration import MIGRATION_HASH_MIGRATION
from .migrations import MIGRATIONS as BASE_MIGRATIONS
from .production_audio_dispatch_output_binding_migration import (
    AUDIO_DISPATCH_OUTPUT_BINDING_MIGRATION,
)
from .production_audio_dispatch_output_binding_owner_migration import (
    AUDIO_DISPATCH_OUTPUT_BINDING_OWNER_MIGRATION,
)
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
from .production_image_dispatch_output_binding_migration import (
    IMAGE_DISPATCH_OUTPUT_BINDING_MIGRATION,
)
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
from .production_playtest_dispatch_output_binding_migration import (
    PLAYTEST_DISPATCH_OUTPUT_BINDING_MIGRATION,
)
from .production_runtime_dispatch_output_binding_migration import (
    RUNTIME_DISPATCH_OUTPUT_BINDING_MIGRATION,
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
    IMAGE_DISPATCH_OUTPUT_BINDING_MIGRATION,
    AUDIO_DISPATCH_OUTPUT_BINDING_MIGRATION,
    RUNTIME_DISPATCH_OUTPUT_BINDING_MIGRATION,
    PLAYTEST_DISPATCH_OUTPUT_BINDING_MIGRATION,
    MIGRATION_HASH_MIGRATION,
    AUDIO_DISPATCH_OUTPUT_BINDING_OWNER_MIGRATION,
)
SCHEMA_VERSION = MIGRATIONS[-1].version


def _migration_hash(version: int) -> str:
    migration = next((item for item in MIGRATIONS if item.version == version), None)
    if migration is None:
        raise RuntimeError(f"unknown migration version {version}")
    digest = hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_database_backup(
    backup_path: str | Path, *, expected_schema_version: int = SCHEMA_VERSION
) -> dict[str, object]:
    """Verify an upgrade backup without migrating or changing it."""
    path = Path(backup_path)
    result: dict[str, object] = {
        "path": str(path),
        "valid": False,
        "schema_version": None,
        "expected_schema_version": expected_schema_version,
    }
    if path.is_symlink() or not path.is_file():
        result["reason"] = "backup is missing, not a regular file, or is an alias"
        return result
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5.0)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            result["reason"] = f"SQLite integrity check: {integrity[0] if integrity else 'no result'}"
            return result
        current = _schema_version(connection)
        result["schema_version"] = current
        if current > expected_schema_version:
            result["reason"] = (
                f"backup schema version {current} is newer than expected {expected_schema_version}"
            )
            return result
        result["valid"] = True
        result["reason"] = "SQLite integrity and schema checks passed"
        return result
    except sqlite3.Error as exc:
        result["reason"] = f"backup cannot be inspected read-only: {exc}"
        return result
    finally:
        if connection is not None:
            connection.close()


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


def _has_migration_hash_column(connection: sqlite3.Connection) -> bool:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
    }
    return "migration_hash" in columns


def _validate_and_backfill_migration_hashes(connection: sqlite3.Connection) -> None:
    if not _has_migration_hash_column(connection):
        return
    rows = connection.execute(
        "SELECT version, migration_hash FROM schema_migrations ORDER BY version"
    ).fetchall()
    known_versions = {migration.version for migration in MIGRATIONS}
    for version, stored_hash in rows:
        if version not in known_versions:
            raise RuntimeError(f"schema migration version {version} is not known")
        expected_hash = _migration_hash(version)
        if stored_hash is not None and stored_hash != expected_hash:
            raise RuntimeError(f"schema migration hash drifted for version {version}")
    with connection:
        for version, stored_hash in rows:
            if stored_hash is None:
                connection.execute(
                    "UPDATE schema_migrations SET migration_hash = ? WHERE version = ?",
                    (_migration_hash(version), version),
                )


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
    schema_table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone() is not None
    current = _schema_version(connection)
    _validate_and_backfill_migration_hashes(connection)
    if backup_path is not None and schema_table_exists and current < SCHEMA_VERSION:
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
            if _has_migration_hash_column(connection):
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at, migration_hash) VALUES (?, ?, ?)",
                    (migration.version, now, _migration_hash(migration.version)),
                )
            else:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (migration.version, now),
                )
        current = migration.version

    _validate_and_backfill_migration_hashes(connection)

    if current != SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported schema version {current}; expected {SCHEMA_VERSION}"
        )
