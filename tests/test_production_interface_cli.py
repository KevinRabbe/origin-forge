from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge.production_interface_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class _FakeServer:
    server_address = ("127.0.0.1", 43210)

    def __init__(self) -> None:
        self.served = False
        self.closed = False

    def serve_forever(self) -> None:
        self.served = True

    def server_close(self) -> None:
        self.closed = True


class ProductionInterfaceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        runtime = OriginForgeRuntime(self.root)
        runtime.initialize("production-interface-cli-test")
        runtime.create_goal("inspect me")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_snapshot_prints_content_addressed_read_only_projection(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), "snapshot"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["total_counts"]["goals"], 1)
        self.assertTrue(payload["authority"]["read_only"])
        self.assertFalse(payload["authority"]["task_mutation"])
        self.assertTrue(payload["content_hash"].startswith("sha256:"))

    def test_serve_uses_fixed_loopback_server_without_host_override(self) -> None:
        fake = _FakeServer()
        output = io.StringIO()
        with patch(
            "origin_forge.production_interface_cli.create_production_interface_server",
            return_value=fake,
        ) as create_server, redirect_stdout(output):
            code = main(
                [
                    "--project-root",
                    str(self.root),
                    "serve",
                    "--port",
                    "43210",
                ]
            )
        self.assertEqual(code, 0)
        create_server.assert_called_once()
        self.assertEqual(create_server.call_args.kwargs["port"], 43210)
        self.assertTrue(fake.served)
        self.assertTrue(fake.closed)
        self.assertIn("http://127.0.0.1:43210/", output.getvalue())

    def test_command_surface_contains_only_snapshot_and_serve(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"  # type: ignore[attr-defined]
        )
        self.assertEqual(set(subparsers.choices), {"snapshot", "serve"})  # type: ignore[attr-defined]
        with self.assertRaises(SystemExit):
            parser.parse_args(["serve", "--host", "0.0.0.0"])
        for forbidden in (
            "create",
            "update",
            "delete",
            "run",
            "verify",
            "adopt",
            "sign",
            "merge",
            "release",
            "train",
        ):
            with self.assertRaises(SystemExit):
                parser.parse_args([forbidden])


if __name__ == "__main__":
    unittest.main()
