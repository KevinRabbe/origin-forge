from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import origin_forge.cli as cli_module
from origin_forge.production_manager_advance_admission import ManagerAdvanceAdmissionStatus
from origin_forge.production_manager_advance_bounded import (
    MAX_MANAGER_ADVANCE_STEPS,
    BoundedManagerAdvanceResult,
    BoundedManagerAdvanceStopReason,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceResult,
    ManagerAdvanceOnceStatus,
)
from origin_forge.production_manager_advance_selection import ManagerAdvanceSelectionStatus
from origin_forge.production_manager_advance_status import ManagerAdvanceStatusProjection


class Phase44AManagerCliTests(unittest.TestCase):
    @staticmethod
    def _status_projection() -> ManagerAdvanceStatusProjection:
        return ManagerAdvanceStatusProjection(
            admission_status=ManagerAdvanceAdmissionStatus.COMPLETE,
            selection_status=ManagerAdvanceSelectionStatus.NONE_AVAILABLE,
            candidate_count=0,
            dispatch_count=0,
            finalize_work_order_count=0,
            finalize_phase34_count=0,
            prepare_count=0,
            recovery_required_count=0,
            terminal_retry_suppression_count=0,
            active_claim_exclusion_count=0,
            selected_task_id=None,
            selected_task_created_at=None,
            selected_action_kind=None,
            selected_preparation_policy_id=None,
            selected_preparation_policy_hash=None,
            selected_preparation_id=None,
            selected_preparation_stage=None,
            selected_dispatch_binding_id=None,
            selected_binding_audit_id=None,
            ambiguous_task_ids=(),
            detail=None,
        )

    @staticmethod
    def _once(status: ManagerAdvanceOnceStatus) -> ManagerAdvanceOnceResult:
        return ManagerAdvanceOnceResult(
            status=status,
            action_kind=None,
            task_id=None,
            task_created_at=None,
            detail=f"{status.value}-detail",
        )

    @classmethod
    def _bounded_noncontinuable(
        cls,
        status: ManagerAdvanceOnceStatus,
    ) -> BoundedManagerAdvanceResult:
        stop_reason = (
            BoundedManagerAdvanceStopReason.NO_ACTIONABLE_WORK
            if status is ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK
            else BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT
        )
        return BoundedManagerAdvanceResult((cls._once(status),), stop_reason)

    @classmethod
    def _bounded_step_limit(cls) -> BoundedManagerAdvanceResult:
        steps = tuple(
            cls._once(ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED)
            for _ in range(MAX_MANAGER_ADVANCE_STEPS)
        )
        return BoundedManagerAdvanceResult(
            steps,
            BoundedManagerAdvanceStopReason.STEP_LIMIT_REACHED,
        )

    def test_manager_parser_has_only_status_and_advance_without_authority_arguments(self) -> None:
        parser = cli_module.build_parser()
        status = parser.parse_args(["manager", "status"])
        advance = parser.parse_args(["manager", "advance"])
        self.assertEqual((status.command, status.manager_command), ("manager", "status"))
        self.assertEqual((advance.command, advance.manager_command), ("manager", "advance"))

        forbidden = (
            "--max-steps",
            "--repeat",
            "--watch",
            "--until-idle",
            "--loop",
            "--interval",
            "--background",
            "--task-id",
            "--preparation-id",
            "--claim-id",
            "--priority",
            "--model",
            "--resource",
            "--action",
        )
        for option in forbidden:
            with self.subTest(option=option), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["manager", "advance", option, "x"])

    def test_manager_status_calls_exact_readonly_projection_once_and_prints_exact_json(self) -> None:
        projection = self._status_projection()
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            stdout = io.StringIO()
            with (
                patch.object(
                    cli_module,
                    "inspect_manager_advance_status_readonly",
                    return_value=projection,
                ) as status,
                patch.object(
                    cli_module,
                    "advance_production_manager_bounded",
                    side_effect=AssertionError("status invoked mutating Manager driver"),
                ) as advance,
                redirect_stdout(stdout),
            ):
                code = cli_module._main(
                    ["--project-root", str(root), "manager", "status"]
                )

            self.assertEqual(code, 0)
            self.assertEqual(status.call_count, 1)
            advance.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue()), projection.to_dict())
            self.assertFalse(root.joinpath(".origin-forge").exists())

    def test_manager_advance_calls_bounded_driver_once_and_prints_exact_json(self) -> None:
        bounded = self._bounded_noncontinuable(ManagerAdvanceOnceStatus.DISPATCH_RETURNED)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            stdout = io.StringIO()
            with (
                patch.object(
                    cli_module,
                    "advance_production_manager_bounded",
                    return_value=bounded,
                ) as advance,
                patch.object(
                    cli_module,
                    "inspect_manager_advance_status_readonly",
                    side_effect=AssertionError("advance performed a status preflight"),
                ) as status,
                redirect_stdout(stdout),
            ):
                code = cli_module._main(
                    ["--project-root", str(root), "manager", "advance"]
                )

            self.assertEqual(code, 0)
            self.assertEqual(advance.call_count, 1)
            status.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue()), bounded.to_dict())
            self.assertFalse(root.joinpath(".origin-forge").exists())

    def test_typed_manager_stop_results_all_return_process_success_without_task_policy(self) -> None:
        results = (
            self._bounded_noncontinuable(ManagerAdvanceOnceStatus.NO_ACTIONABLE_WORK),
            self._bounded_noncontinuable(
                ManagerAdvanceOnceStatus.PREPARATION_FAILED_PRE_PLANNER
            ),
            self._bounded_noncontinuable(ManagerAdvanceOnceStatus.DISPATCH_RAISED),
            self._bounded_noncontinuable(
                ManagerAdvanceOnceStatus.DISPATCH_RECOVERY_REQUIRED
            ),
            self._bounded_step_limit(),
        )
        for bounded in results:
            with self.subTest(stop_reason=bounded.stop_reason, status=bounded.final_result.status):
                stdout = io.StringIO()
                with (
                    patch.object(
                        cli_module,
                        "advance_production_manager_bounded",
                        return_value=bounded,
                    ) as advance,
                    redirect_stdout(stdout),
                ):
                    code = cli_module._main(["manager", "advance"])

                self.assertEqual(code, 0)
                self.assertEqual(advance.call_count, 1)
                self.assertEqual(json.loads(stdout.getvalue()), bounded.to_dict())

    def test_manager_source_imports_only_status_and_bounded_manager_surfaces(self) -> None:
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        manager_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level > 0
            and node.module is not None
            and node.module.startswith("production_manager")
        }
        self.assertEqual(
            manager_imports,
            {
                "production_manager_advance_bounded",
                "production_manager_advance_status",
            },
        )
        self.assertNotIn("advance_production_manager_once", source)
        for forbidden in (
            "recover_preparation_once",
            "prepare_materialization_tick",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "dispatch_manager_tick",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
