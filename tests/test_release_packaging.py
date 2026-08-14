from __future__ import annotations

import shutil
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.config import DEFAULT_CONFIG
from origin_forge.orchestration_cli import build_parser as build_attempt_parser
from origin_forge.orchestration_cli import main as attempt_main
from origin_forge.production_interface_cli import build_parser as build_cockpit_parser
from origin_forge.production_interface_cli import main as cockpit_main
from origin_forge.runtime import OriginForgeRuntime


class ReleasePackagingTests(unittest.TestCase):
    def test_pyproject_exposes_stable_release_entrypoints(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)

        project = config["project"]
        self.assertEqual(config["build-system"]["requires"], ["setuptools>=68"])
        self.assertEqual(project["name"], "origin-forge")
        self.assertEqual(project["version"], "0.2.0.dev0")
        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["license"], {"file": "LICENSE"})
        self.assertEqual(project["requires-python"], ">=3.12")
        self.assertEqual(
            project["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )

        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(license_text.startswith("Apache License\n"))
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)

    def test_attempt_entrypoint_is_one_bounded_context_selected_attempt(self) -> None:
        parser = build_attempt_parser()
        self.assertEqual(parser.prog, "origin-forge-attempt")
        manual = parser.parse_args(["TASK-example", "--file", "src/example.py"])
        self.assertEqual(manual.task_id, "TASK-example")
        self.assertEqual(manual.files, ["src/example.py"])
        self.assertFalse(manual.auto_context)

        automatic = parser.parse_args(["TASK-example", "--auto-context"])
        self.assertEqual(automatic.task_id, "TASK-example")
        self.assertTrue(automatic.auto_context)
        self.assertIsNone(automatic.files)

        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["TASK-example"])

    def test_attempt_help_creates_no_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit_info:
                attempt_main(["--project-root", str(root), "--help"])
            self.assertEqual(exit_info.exception.code, 0)
            self.assertFalse(state.exists())

    def test_attempt_fails_closed_without_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with redirect_stderr(StringIO()):
                result = attempt_main(
                    ["--project-root", str(root), "TASK-example", "--auto-context"]
                )
            self.assertEqual(result, 2)
            self.assertFalse(state.exists())

    def test_attempt_config_only_state_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            config = state / "config.toml"
            config.write_text(DEFAULT_CONFIG, encoding="utf-8")
            database = state / "project.db"
            with redirect_stderr(StringIO()):
                result = attempt_main(
                    ["--project-root", str(root), "TASK-example", "--auto-context"]
                )
            self.assertEqual(result, 2)
            self.assertFalse(database.exists())
            self.assertEqual({path.name for path in state.iterdir()}, {"config.toml"})

    def test_attempt_empty_database_is_not_initialized_or_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(DEFAULT_CONFIG, encoding="utf-8")
            database = state / "project.db"
            database.write_bytes(b"")
            before = database.stat()

            with redirect_stderr(StringIO()):
                result = attempt_main(
                    ["--project-root", str(root), "TASK-example", "--auto-context"]
                )

            after = database.stat()
            self.assertEqual(result, 2)
            self.assertEqual(database.read_bytes(), b"")
            self.assertEqual(
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            )
            self.assertEqual(
                {path.name for path in state.iterdir()},
                {"config.toml", "project.db"},
            )

    def test_attempt_rejects_database_bound_to_another_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            OriginForgeRuntime(source).initialize("source")
            shutil.copytree(source / ".origin-forge", target / ".origin-forge")
            database = target / ".origin-forge" / "project.db"
            before = database.read_bytes()

            with redirect_stderr(StringIO()):
                result = attempt_main(
                    ["--project-root", str(target), "TASK-example", "--auto-context"]
                )

            self.assertEqual(result, 2)
            self.assertEqual(database.read_bytes(), before)

    def test_attempt_rejects_active_journal_without_touching_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("active-journal")
            database = runtime.store.db_path
            before = database.read_bytes()
            wal = Path(str(database) + "-wal")
            wal.write_bytes(b"active")

            with redirect_stderr(StringIO()):
                result = attempt_main(
                    ["--project-root", str(root), "TASK-example", "--auto-context"]
                )

            self.assertEqual(result, 2)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual(wal.read_bytes(), b"active")

    def test_cockpit_entrypoint_remains_read_only_command_set(self) -> None:
        parser = build_cockpit_parser()
        self.assertEqual(parser.prog, "origin-forge-cockpit")
        snapshot = parser.parse_args(["snapshot"])
        self.assertEqual(snapshot.command, "snapshot")
        serve = parser.parse_args(["serve"])
        self.assertEqual(serve.command, "serve")

        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["init"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["run"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["verify"])

    def test_packaged_cockpit_help_creates_no_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit_info:
                cockpit_main(["--project-root", str(root), "--help"])
            self.assertEqual(exit_info.exception.code, 0)
            self.assertFalse(state.exists())

    def test_packaged_cockpit_snapshot_fails_closed_without_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with redirect_stdout(StringIO()):
                result = cockpit_main(["--project-root", str(root), "snapshot"])
            self.assertEqual(result, 2)
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
