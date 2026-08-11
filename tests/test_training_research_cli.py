from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.training_research_cli import build_parser, main
from origin_forge.training_research_policy import (
    RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
    RUNTIME_REDACTED_PRODUCER_ID,
    RUNTIME_REDACTED_PRODUCER_VERSION,
    V1_ELIGIBILITY_POLICY_FINGERPRINT,
    V1_ELIGIBILITY_POLICY_ID,
    V1_ELIGIBILITY_POLICY_VERSION,
)


class TrainingResearchCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("training-research-cli-test")

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
                "trajectories",
                "eligibility-audits",
                "datasets",
                "experiment-plans",
                "experiment-reports",
                "trajectory-show",
                "eligibility-audit-show",
                "dataset-show",
                "experiment-plan-show",
                "experiment-report-show",
            },
        )
        for forbidden in (
            "train",
            "finetune",
            "distill",
            "dataset-build",
            "ingest",
            "download-model",
            "load-checkpoint",
            "activate",
            "route",
            "task-complete",
            "task-verify",
            "promote",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_reports_trusted_policy_and_zero_execution_authority(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(
            value["counts"],
            {
                "datasets": 0,
                "eligibility-audits": 0,
                "experiment-plans": 0,
                "experiment-reports": 0,
                "trajectories": 0,
            },
        )
        self.assertEqual(
            value["trusted_trajectory_producer"],
            {
                "producer_id": RUNTIME_REDACTED_PRODUCER_ID,
                "producer_version": RUNTIME_REDACTED_PRODUCER_VERSION,
                "producer_fingerprint": RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
            },
        )
        self.assertEqual(
            value["dataset_eligibility_policy"],
            {
                "policy_id": V1_ELIGIBILITY_POLICY_ID,
                "policy_version": V1_ELIGIBILITY_POLICY_VERSION,
                "policy_fingerprint": V1_ELIGIBILITY_POLICY_FINGERPRINT,
            },
        )
        for key, enabled in value.items():
            if key.endswith("_enabled"):
                self.assertFalse(enabled, key)
        self.assertEqual(self.runtime.status(), before)

    def test_invalid_show_id_returns_structured_error(self) -> None:
        code, value = self._call("experiment-report-show", "not-a-report")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
