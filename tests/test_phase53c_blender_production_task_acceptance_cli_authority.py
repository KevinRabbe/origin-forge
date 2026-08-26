from __future__ import annotations

import inspect
import io
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import origin_forge.blender_admin_cli as blender_admin_cli
import origin_forge.production_blender_task_acceptor as acceptor_module
from .test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class Phase53CBlenderProductionTaskAcceptanceCliAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _accept(self, project_root: Path, execution_id: str) -> int:
        with redirect_stdout(io.StringIO()):
            return blender_admin_cli.main(
                [
                    "--project-root",
                    str(project_root),
                    "accept-production-task",
                    "--execution-id",
                    execution_id,
                ]
            )

    def test_successful_operator_acceptance_and_replay_do_not_mutate_adopted_glb(self) -> None:
        runtime, binding, adoption, _, _ = self.fixture._published_inputs()
        destination = runtime.project_root / adoption.destination_path
        before = destination.read_bytes()

        self.assertEqual(self._accept(runtime.project_root, binding.execution_id), 0)
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(self._accept(runtime.project_root, binding.execution_id), 0)
        self.assertEqual(destination.read_bytes(), before)

    def test_module_only_acceptance_surface_keeps_unrelated_authorities_and_packaging_out(self) -> None:
        source = (
            inspect.getsource(blender_admin_cli)
            + "\n"
            + inspect.getsource(acceptor_module)
        ).lower()
        for forbidden in (
            "pixelorama",
            "conversation",
            "production_interface",
            "blenderexportservice",
            "modeladapter",
            "subprocess",
        ):
            self.assertNotIn(forbidden, source)

        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
        scripts = project.get("scripts", {})
        self.assertNotIn("origin_forge.blender_admin_cli:main", scripts.values())


if __name__ == "__main__":
    unittest.main()
