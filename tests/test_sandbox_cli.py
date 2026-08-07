from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from origin_forge.cli import main
from origin_forge.sandbox import SandboxGuarantees, SandboxResult
from origin_forge.sandbox_verification import (
    CommandVerificationResult,
    WorkspaceVerificationResult,
)


class SandboxCliTests(unittest.TestCase):
    def test_status_reports_safe_unconfigured_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(["--project-root", str(root), "init", "--name", "sandbox-cli"]),
                    0,
                )
            output = StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", str(root), "sandbox", "status"])
            self.assertEqual(code, 1)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["backend"], "unconfigured")
            self.assertFalse(payload["available"])
            self.assertFalse(payload["guarantees"]["filesystem_isolated"])

    def test_verify_uses_configured_backend_and_existing_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with redirect_stdout(StringIO()):
                main(["--project-root", str(root), "init", "--name", "sandbox-cli"])

            backend = Mock()
            backend.backend_id = "fake"
            backend.guarantees = SandboxGuarantees(True, True, True, True)
            verification = WorkspaceVerificationResult(
                "WSPACE-test",
                True,
                (
                    CommandVerificationResult(
                        "test",
                        "unit",
                        "VERIFY-test",
                        True,
                        SandboxResult(0, "ok", "", False, 4),
                    ),
                ),
            )
            verifier = Mock()
            verifier.verify.return_value = verification

            output = StringIO()
            with patch("origin_forge.cli.create_sandbox_backend", return_value=backend), patch(
                "origin_forge.cli.SandboxedWorkspaceVerifier", return_value=verifier
            ), redirect_stdout(output):
                code = main(
                    [
                        "--project-root",
                        str(root),
                        "sandbox",
                        "verify",
                        "WSPACE-test",
                    ]
                )
            self.assertEqual(code, 0)
            verifier.verify.assert_called_once_with("WSPACE-test")
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["results"][0]["command_name"], "unit")


if __name__ == "__main__":
    unittest.main()
