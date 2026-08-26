from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

import origin_forge.blender_admin_cli as blender_admin_cli
from .test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class Phase53CBlenderProductionTaskAcceptanceCliInvalidIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_operator_command_fails_closed_on_malformed_execution_id(self) -> None:
        runtime, binding, _, _, _ = self.fixture._published_inputs()
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            return_code = blender_admin_cli.main(
                [
                    "--project-root",
                    str(runtime.project_root),
                    "accept-production-task",
                    "--execution-id",
                    "not-a-dispatch-execution-id",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 2)
        self.assertEqual(payload["error"], "ValueError")
        self.assertIn("DISPEXEC", str(payload["detail"]))
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
