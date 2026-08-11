from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_read_guard as guard_module
import origin_forge.production_runtime_read as runtime_read_module
from origin_forge.config import DEFAULT_CONFIG
from origin_forge.db import SCHEMA_VERSION
from origin_forge.model_resource_read import inspect_model_resources
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.production_read_guard import (
    ProductionReadGuardError,
    ensure_production_runtime_readable,
    production_read_connection,
)
from origin_forge.production_runtime_read import ProductionRuntimeReadService
from origin_forge.runtime import OriginForgeRuntime


class ProductionReadGuardTests(unittest.TestCase):
    def test_uninitialized_inspection_creates_no_origin_forge_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            state = root / ".origin-forge"
            self.assertFalse(state.exists())

            with self.assertRaises(ProductionReadGuardError):
                ensure_production_runtime_readable(runtime)
            self.assertFalse(state.exists())

            with self.assertRaises(ProductionReadGuardError):
                build_production_interface_snapshot(runtime)
            self.assertFalse(state.exists())

            with self.assertRaises(ProductionReadGuardError):
                inspect_model_resources(root)
            self.assertFalse(state.exists())

    def test_config_only_state_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(DEFAULT_CONFIG, encoding="utf-8")
            runtime = OriginForgeRuntime(root)
            database = state / "project.db"
            self.assertFalse(database.exists())

            with self.assertRaisesRegex(ProductionReadGuardError, "database is missing"):
                ensure_production_runtime_readable(runtime)

            self.assertFalse(database.exists())
            self.assertEqual(
                {path.name for path in state.iterdir()},
                {"config.toml"},
            )

    def test_stale_schema_is_not_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(DEFAULT_CONFIG, encoding="utf-8")
            database = state / "project.db"
            with sqlite3.connect(database) as conn:
                conn.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION - 1, "2026-08-11T00:00:00Z"),
                )
            before = database.read_bytes()
            runtime = OriginForgeRuntime(root)

            with self.assertRaisesRegex(ProductionReadGuardError, "authoritative migration"):
                ensure_production_runtime_readable(runtime)

            self.assertEqual(database.read_bytes(), before)
            with sqlite3.connect(database) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertEqual(tables, {"schema_migrations"})

    def test_active_journal_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("production-read-active-journal")
            database = runtime.store.db_path
            wal = Path(str(database) + "-wal")
            wal.write_bytes(b"")
            try:
                with self.assertRaisesRegex(ProductionReadGuardError, "active journal"):
                    ensure_production_runtime_readable(runtime)
            finally:
                wal.unlink(missing_ok=True)

    def test_initialized_reads_create_no_sqlite_sidecars_or_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("production-read-initialized")
            runtime.create_goal("inspect without mutation")
            state = runtime.state_dir
            database = runtime.store.db_path
            config = state / "config.toml"
            before_names = {path.name for path in state.iterdir()}
            before_db = database.stat()
            before_config = config.read_bytes()

            ensure_production_runtime_readable(runtime)
            with production_read_connection(runtime) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                    1,
                )
            reader = ProductionRuntimeReadService(runtime)
            self.assertEqual(reader.count_goals(), 1)
            self.assertEqual(len(reader.list_goals(limit=2)), 1)

            after_db = database.stat()
            self.assertEqual({path.name for path in state.iterdir()}, before_names)
            self.assertEqual(config.read_bytes(), before_config)
            self.assertEqual(
                (after_db.st_dev, after_db.st_ino, after_db.st_size, after_db.st_mtime_ns),
                (before_db.st_dev, before_db.st_ino, before_db.st_size, before_db.st_mtime_ns),
            )
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(database) + suffix).exists())

    def test_reader_source_has_no_normal_store_or_migration_surface(self) -> None:
        reader_source = inspect.getsource(runtime_read_module)
        for forbidden in (
            ".store",
            "migrate(",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "journal_mode",
            ".commit(",
            ".rollback(",
        ):
            self.assertNotIn(forbidden, reader_source)

        guard_source = inspect.getsource(guard_module)
        self.assertIn("immutable=1", guard_source)
        self.assertNotIn("journal_mode", guard_source)
        self.assertNotIn("migrate(", guard_source)


if __name__ == "__main__":
    unittest.main()
