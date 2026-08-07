from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import LATEST_SCHEMA_VERSION, MIGRATIONS

SCHEMA_VERSION = LATEST_SCHEMA_VERSION


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migrate(connection: sqlite3.Connection, now: str) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
    ).fetchone()
    current = int(row["version"])

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
