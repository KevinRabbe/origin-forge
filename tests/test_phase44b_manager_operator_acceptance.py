from __future__ import annotations

import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import origin_forge.cli as cli_module
import origin_forge.production_manager_dispatch_tick as dispatch_tick_module
import test_phase40_manager_advance_acceptance as phase40
import test_phase42c_manager_recovery_acceptance as phase42
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_interface_cli import build_parser as build_cockpit_parser
from origin_forge.production_manager_advance_bounded import (
    BoundedManagerAdvanceStopReason,
    MAX_MANAGER_ADVANCE_STEPS,
    advance_production_manager_bounded,
)
from origin_forge.production_manager_advance_once import ManagerAdvanceOnceStatus
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import TaskStatus


class Phase44BManagerOperatorAcceptanceTests(unittest.TestCase):
    def test_real_cli_advance_prints_exact_bounded_trace_and_never_drains_newer_task(self) -> None:
        scenario = phase42._scenario(self, steps=2)
        claims_by_id = {}
        completed = []
        bounded_results = []

        def capture_claim(runtime, binding_id, audit_id, revision):
            claim = acquire_dispatch_claim(runtime, binding_id, audit_id, revision)
            claims_by_id[claim.claim_id] = claim
            return claim

        def fake_dispatch(runtime, claim_id, expected_revision):
            self.assertEqual(expected_revision, 0)
            invocation = phase40.Phase40ManagerAdvanceAcceptanceTests._completed_for_claim(
                claims_by_id[claim_id]
            )
            completed.append(invocation)
            return invocation

        def capture_bounded(runtime):
            result = advance_production_manager_bounded(runtime)
            bounded_results.append(result)
            return result

        stdout = io.StringIO()
        with (
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=phase40.Phase40ManagerAdvanceAcceptanceTests._response(),
            ) as generate,
            patch.object(
                dispatch_tick_module,
                "acquire_dispatch_claim",
                side_effect=capture_claim,
            ),
            patch.object(
                dispatch_tick_module,
                "dispatch_claim_once",
                side_effect=fake_dispatch,
            ) as dispatch,
            patch.object(
                cli_module,
                "advance_production_manager_bounded",
                side_effect=capture_bounded,
            ) as cli_advance,
            redirect_stdout(stdout),
        ):
            code = cli_module._main(
                ["--project-root", str(scenario.root), "manager", "advance"]
            )

        self.assertEqual(code, 0)
        self.assertEqual(cli_advance.call_count, 1)
        self.assertEqual(len(bounded_results), 1)
        result = bounded_results[0]
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, result.to_dict())
        self.assertEqual(payload["authority"], "bounded-manager-advance-driver")
        self.assertEqual(payload["max_steps"], MAX_MANAGER_ADVANCE_STEPS)
        self.assertEqual(payload["step_count"], 4)
        self.assertEqual(
            payload["stop_reason"],
            BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT.value,
        )
        self.assertEqual(
            tuple(step["status"] for step in payload["steps"]),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED.value,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED.value,
                ManagerAdvanceOnceStatus.PHASE34_READY.value,
                ManagerAdvanceOnceStatus.DISPATCH_RETURNED.value,
            ),
        )
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(len(completed), 1)

        selected_task_id = payload["steps"][0]["task_id"]
        self.assertIsNotNone(selected_task_id)
        self.assertTrue(
            all(step["task_id"] == selected_task_id for step in payload["steps"])
        )
        self.assertEqual(
            payload["steps"][-1]["claim_id"],
            completed[0].execution.claim_id,
        )
        self.assertEqual(
            payload["steps"][-1]["execution_id"],
            completed[0].execution.execution_id,
        )

        newer_task_id = phase42._other_task_id(self, scenario, selected_task_id)
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(newer["revision"], 0)
        phase42._assert_no_dispatch(self, scenario.runtime, newer_task_id)

    def test_uninitialized_manager_commands_fail_closed_without_creating_project_state(self) -> None:
        for manager_command in ("status", "advance"):
            with self.subTest(manager_command=manager_command), tempfile.TemporaryDirectory() as raw_root:
                root = Path(raw_root)
                state = root / ".origin-forge"
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = cli_module._main(
                        ["--project-root", str(root), "manager", manager_command]
                    )

                self.assertEqual(code, 0)
                self.assertFalse(state.exists())
                payload = json.loads(stdout.getvalue())
                if manager_command == "status":
                    self.assertEqual(payload["admission_status"], "INVALID_STATE")
                    self.assertEqual(payload["selection_status"], "INVALID_STATE")
                    self.assertEqual(payload["candidate_count"], 0)
                    self.assertEqual(
                        payload["authority"],
                        "immutable-manager-advance-status",
                    )
                else:
                    self.assertEqual(payload["step_count"], 1)
                    self.assertEqual(payload["steps"][0]["status"], "INVALID_STATE")
                    self.assertEqual(
                        payload["stop_reason"],
                        BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT.value,
                    )
                    self.assertEqual(payload["max_steps"], MAX_MANAGER_ADVANCE_STEPS)
                    self.assertEqual(
                        payload["authority"],
                        "bounded-manager-advance-driver",
                    )

    def test_packaging_and_cockpit_remain_unchanged_non_manager_surfaces(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(
            config["project"]["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )

        parser = build_cockpit_parser()
        self.assertEqual(parser.prog, "origin-forge-cockpit")
        self.assertEqual(parser.parse_args(["snapshot"]).command, "snapshot")
        self.assertEqual(parser.parse_args(["serve"]).command, "serve")
        for forbidden in ("manager", "advance", "run", "init"):
            with self.subTest(forbidden=forbidden), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args([forbidden])


if __name__ == "__main__":
    unittest.main()
