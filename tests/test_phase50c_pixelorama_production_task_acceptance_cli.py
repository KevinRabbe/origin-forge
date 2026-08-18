from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_accept_production_task_delegates_only_execution_identity_and_prints_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    monkeypatch.setattr(pixelorama_admin_cli, "OriginForgeRuntime", open_runtime)
    monkeypatch.setattr(
        pixelorama_admin_cli,
        "GovernedPixeloramaProductionTaskAcceptor",
        FakeAcceptor,
    )

    return_code = pixelorama_admin_cli.main(
        [
            "--project-root",
            str(tmp_path),
            "accept-production-task",
            "DISPEXEC-TEST",
        ]
    )

    assert return_code == 0
    assert observed == {
        "project_root": tmp_path,
        "runtime": runtime,
        "execution_id": "DISPEXEC-TEST",
    }
    assert json.loads(capsys.readouterr().out) == _AcceptanceResult().to_dict()


def test_accept_production_task_fails_closed_on_acceptor_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = object()

    monkeypatch.setattr(pixelorama_admin_cli, "OriginForgeRuntime", lambda _root: runtime)

    class FailingAcceptor:
        def __init__(self, supplied_runtime: object):
            assert supplied_runtime is runtime

        def accept(self, execution_id: str) -> _AcceptanceResult:
            assert execution_id == "DISPEXEC-STALE"
            raise pixelorama_admin_cli.PixeloramaProductionTaskAcceptorError(
                "production task acceptance is stale"
            )

    monkeypatch.setattr(
        pixelorama_admin_cli,
        "GovernedPixeloramaProductionTaskAcceptor",
        FailingAcceptor,
    )

    return_code = pixelorama_admin_cli.main(
        [
            "--project-root",
            str(tmp_path),
            "accept-production-task",
            "DISPEXEC-STALE",
        ]
    )

    assert return_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error": "PixeloramaProductionTaskAcceptorError",
        "detail": "production task acceptance is stale",
    }


@pytest.mark.parametrize(
    "extra_arguments",
    [
        ["--task-id", "TASK-OPERATOR"],
        ["--run-id", "RUN-OPERATOR"],
        ["--artifact-id", "ART-OPERATOR"],
        ["--path", "artifacts/operator.png"],
        ["--verification", "VER-OPERATOR"],
        ["--model", "operator-model"],
        ["--force"],
    ],
)
def test_accept_production_task_rejects_extra_authority_inputs(
    extra_arguments: list[str],
) -> None:
    parser = pixelorama_admin_cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            ["accept-production-task", "DISPEXEC-TEST", *extra_arguments]
        )

    assert exc_info.value.code == 2
