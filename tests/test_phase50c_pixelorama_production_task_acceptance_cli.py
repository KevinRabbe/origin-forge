from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge import pixelorama_admin_cli


class _AcceptanceResult:
    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": "DISPEXEC-TEST",
            "task_id": "TASK-TEST",
            "task_status": "SUCCEEDED",
            "production_task_verified": True,
            "acceptance_authority": "HUMAN_OPERATOR",
            "release_authorized": False,
        }


class Phase50CPixeloramaProductionTaskAcceptanceCliTests(unittest.TestCase):
    def test_accept_production_task_delegates_only_execution_identity_and_prints_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = object()
            observed: dict[str, object] = {}

            def open_runtime(project_root: Path) -> object:
                observed["project_root"] = project_root
                return runtime

            class FakeAcceptor:
                def __init__(self, supplied_runtime: object):
                    observed["runtime"] = supplied_runtime

                def accept(self, execution_id: str) -> _AcceptanceResult:
                    observed["execution_id"] = execution_id
                    return _AcceptanceResult()

            output = io.StringIO()
            with (
                patch.object(pixelorama_admin_cli, "OriginForgeRuntime", open_runtime),
                patch.object(
                    pixelorama_admin_cli,
                    "GovernedPixeloramaProductionTaskAcceptor",
                    FakeAcceptor,
                ),
                redirect_stdout(output),
            ):
                return_code = pixelorama_admin_cli.main(
                    [
                        "--project-root",
                        str(root),
                        "accept-production-task",
                        "DISPEXEC-TEST",
                    ]
                )

            self.assertEqual(return_code, 0)
            self.assertEqual(
                observed,
                {
                    "project_root": root,
                    "runtime": runtime,
                    "execution_id": "DISPEXEC-TEST",
                },
            )
            self.assertEqual(
                json.loads(output.getvalue()),
                _AcceptanceResult().to_dict(),
            )

    def test_accept_production_task_fails_closed_on_acceptor_error(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = object()

            class FailingAcceptor:
                def __init__(self, supplied_runtime: object):
                    self.assert_runtime(supplied_runtime)

                @staticmethod
                def assert_runtime(supplied_runtime: object) -> None:
                    if supplied_runtime is not runtime:
                        raise AssertionError("unexpected runtime")

                def accept(self, execution_id: str) -> _AcceptanceResult:
                    if execution_id != "DISPEXEC-STALE":
                        raise AssertionError("unexpected execution id")
                    raise pixelorama_admin_cli.PixeloramaProductionTaskAcceptorError(
                        "production task acceptance is stale"
                    )

            output = io.StringIO()
            with (
                patch.object(
                    pixelorama_admin_cli,
                    "OriginForgeRuntime",
                    lambda _root: runtime,
                ),
                patch.object(
                    pixelorama_admin_cli,
                    "GovernedPixeloramaProductionTaskAcceptor",
                    FailingAcceptor,
                ),
                redirect_stdout(output),
            ):
                return_code = pixelorama_admin_cli.main(
                    [
                        "--project-root",
                        str(root),
                        "accept-production-task",
                        "DISPEXEC-STALE",
                    ]
                )

            self.assertEqual(return_code, 2)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "error": "PixeloramaProductionTaskAcceptorError",
                    "detail": "production task acceptance is stale",
                },
            )

    def test_accept_production_task_rejects_extra_authority_inputs(self) -> None:
        parser = pixelorama_admin_cli.build_parser()
        forbidden_arguments = (
            ("--task-id", "TASK-OPERATOR"),
            ("--run-id", "RUN-OPERATOR"),
            ("--artifact-id", "ART-OPERATOR"),
            ("--path", "artifacts/operator.png"),
            ("--verification", "VER-OPERATOR"),
            ("--model", "operator-model"),
            ("--force",),
        )

        for extra_arguments in forbidden_arguments:
            with self.subTest(extra_arguments=extra_arguments):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as exc_info:
                        parser.parse_args(
                            [
                                "accept-production-task",
                                "DISPEXEC-TEST",
                                *extra_arguments,
                            ]
                        )
                self.assertEqual(exc_info.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
