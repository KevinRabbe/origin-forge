from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.media_fingerprint_cli import build_parser, main
from origin_forge.runtime import OriginForgeRuntime


class MediaFingerprintCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("media-fingerprint-cli-test")

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
                "fingerprints",
                "comparisons",
                "watermark-plans",
                "watermark-results",
                "provenance-links",
                "fingerprint-show",
                "comparison-show",
                "watermark-plan-show",
                "watermark-result-show",
                "provenance-link-show",
            },
        )
        for forbidden in (
            "fingerprint",
            "hash-file",
            "embed",
            "detect",
            "watermark",
            "adopt",
            "task-complete",
            "task-verify",
            "sign",
            "key",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_reports_phase18_trust_root_and_zero_mutation_authority(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertTrue(value["phase18_is_trust_root"])
        self.assertEqual(
            value["counts"],
            {
                "comparisons": 0,
                "fingerprints": 0,
                "provenance-links": 0,
                "watermark-plans": 0,
                "watermark-results": 0,
            },
        )
        for key, enabled in value.items():
            if key.endswith("_enabled"):
                self.assertFalse(enabled, key)
        self.assertEqual(self.runtime.status(), before)

    def test_invalid_show_id_returns_structured_error(self) -> None:
        code, value = self._call("watermark-result-show", "not-a-result")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
