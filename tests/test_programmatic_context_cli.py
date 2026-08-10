from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.programmatic_context_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class ProgrammaticContextCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("programmatic-context-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str) -> tuple[int, object]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_command_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = next(action for action in parser._actions if action.dest == "command")
        commands = set(subparsers.choices)
        self.assertEqual(
            commands,
            {
                "status",
                "requests",
                "catalogs",
                "programs",
                "packages",
                "executions",
                "experiments",
                "request-show",
                "catalog-show",
                "program-show",
                "package-show",
                "execution-show",
                "experiment-show",
            },
        )
        for forbidden in (
            "create",
            "run",
            "execute",
            "eval",
            "python",
            "shell",
            "sql",
            "call-tool",
            "activate",
            "promote",
            "task-complete",
            "task-verify",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_reports_only_read_authority(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(
            value["counts"],
            {
                "catalogs": 0,
                "executions": 0,
                "experiments": 0,
                "packages": 0,
                "programs": 0,
                "requests": 0,
            },
        )
        self.assertEqual(len(value["builtin_read_adapters"]), 1)
        self.assertEqual(
            value["builtin_read_adapters"][0]["operation_id"],
            "runtime.run_show",
        )
        self.assertEqual(value["builtin_read_adapters"][0]["effect"], "READ_ONLY")
        for key, enabled in value.items():
            if key.endswith("_enabled"):
                self.assertFalse(enabled, key)
        self.assertEqual(self.runtime.status(), before)

    def test_invalid_show_id_returns_structured_error(self) -> None:
        code, value = self._call("program-show", "not-a-program")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
