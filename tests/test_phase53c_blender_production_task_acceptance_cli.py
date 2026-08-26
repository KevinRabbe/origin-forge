from __future__ import annotations

import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

import origin_forge.blender_admin_cli as blender_admin_cli
from origin_forge.production_blender_task_acceptance import (
    BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
    publish_blender_production_task_acceptance,
)
from origin_forge.production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
    inspect_blender_production_task_acceptance_currentness_readonly,
)
from origin_forge.runtime import OriginForgeRuntime
from .test_phase53a_blender_production_task_acceptance import (
    Phase53ABlenderProductionTaskAcceptanceTests,
)


class Phase53CBlenderProductionTaskAcceptanceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase53ABlenderProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_blender_task_pass_without_terminalizing_task"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _ready(self):
        return self.fixture._published_inputs()

    def _invoke(self, project_root, *arguments: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            return_code = blender_admin_cli.main(
                ["--project-root", str(project_root), *arguments]
            )
        return return_code, json.loads(stdout.getvalue())

    def test_operator_command_accepts_exact_task_reopens_and_replays_idempotently(self) -> None:
        runtime, binding, adoption, _, task_revision = self._ready()

        first_code, first = self._invoke(
            runtime.project_root,
            "accept-production-task",
            "--execution-id",
            binding.execution_id,
            "--actor-id",
            "operator.phase53c",
        )
        second_code, second = self._invoke(
            runtime.project_root,
            "accept-production-task",
            "--execution-id",
            binding.execution_id,
            "--actor-id",
            "ignored.on.exact.replay",
        )

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertEqual(second, first)
        self.assertEqual(first["execution_id"], binding.execution_id)
        self.assertEqual(first["task_id"], binding.task_id)
        self.assertEqual(first["adopted_artifact_id"], adoption.adopted_artifact_id)
        self.assertEqual(first["task_revision_at_acceptance"], task_revision)
        self.assertEqual(first["task_revision"], task_revision + 1)
        self.assertEqual(first["task_status"], "SUCCEEDED")
        self.assertEqual(first["acceptance_authority"], "HUMAN_OPERATOR")
        self.assertTrue(first["canonical_asset_adopted"])
        self.assertTrue(first["production_task_verified"])
        self.assertTrue(first["semantic_geometry_verified"])
        self.assertFalse(first["provenance_signed"])
        self.assertFalse(first["release_authorized"])

        reopened = OriginForgeRuntime(runtime.project_root)
        currentness = inspect_blender_production_task_acceptance_currentness_readonly(
            reopened,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        self.assertEqual(currentness.task_id, first["task_id"])
        self.assertEqual(currentness.task_verification_id, first["task_verification_id"])
        self.assertEqual(currentness.task_revision, first["task_revision"])
        with reopened.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM state_events
                       WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                             AND event_type = 'TASK_STATUS_CHANGED'
                             AND old_state = 'RUNNING' AND new_state = 'SUCCEEDED'""",
                    (binding.task_id,),
                ).fetchone()[0],
                1,
            )

    def test_operator_command_recovers_existing_pass_without_duplicate_acceptance(self) -> None:
        runtime, binding, adoption, dispatch_binding, task_revision = self._ready()
        receipt = publish_blender_production_task_acceptance(
            runtime,
            binding,
            adoption,
            dispatch_binding,
            task_revision_at_acceptance=task_revision,
            actor_id="operator.phase53c.before-crash",
        )
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

        code, payload = self._invoke(
            runtime.project_root,
            "accept-production-task",
            "--execution-id",
            binding.execution_id,
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["task_verification_id"], receipt.task_verification_id)
        self.assertEqual(payload["task_status"], "SUCCEEDED")
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM verifications
                       WHERE target_type = 'TASK' AND target_id = ?
                             AND verification_type = ?""",
                    (
                        binding.task_id,
                        BLENDER_PRODUCTION_TASK_ACCEPTANCE_VERIFICATION_TYPE,
                    ),
                ).fetchone()[0],
                1,
            )

    def test_operator_command_fails_closed_on_live_adopted_byte_drift(self) -> None:
        runtime, binding, adoption, _, _ = self._ready()
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"phase53c-drift")

        code, payload = self._invoke(
            runtime.project_root,
            "accept-production-task",
            "--execution-id",
            binding.execution_id,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "BlenderProductionTaskAcceptorError")
        self.assertIn("destination bytes drifted", str(payload["detail"]))
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )

    def test_operator_command_fails_closed_on_incomplete_child(self) -> None:
        runtime, binding, _, _, _ = self._ready()
        parent = runtime.get_task(binding.task_id)
        runtime.create_task(
            parent["flow_id"],
            "unfinished child blocks Phase 53C operator acceptance",
            parent_task_id=binding.task_id,
        )

        code, payload = self._invoke(
            runtime.project_root,
            "accept-production-task",
            "--execution-id",
            binding.execution_id,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "BlenderProductionTaskAcceptorError")
        self.assertIn("child Tasks incompatible", str(payload["detail"]))
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")
        with runtime.store.session() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blender_production_task_acceptances"
                ).fetchone()[0],
                0,
            )

    def test_accept_command_rejects_authority_widening_arguments(self) -> None:
        forbidden_arguments = (
            ("--task-id", "TASK-forged"),
            ("--task-revision", "99"),
            ("--artifact-id", "ART-forged"),
            ("--destination", "assets/forged.glb"),
            ("--run-id", "RUN-forged"),
            ("--request-id", "REQ-forged"),
            ("--verification-id", "VER-forged"),
            ("--force",),
            ("--release",),
            ("--retry-count", "3"),
        )
        for extra in forbidden_arguments:
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    blender_admin_cli.build_parser().parse_args(
                        [
                            "--project-root",
                            "/tmp/project",
                            "accept-production-task",
                            "--execution-id",
                            "DISPEXEC-forged",
                            *extra,
                        ]
                    )
                self.assertEqual(raised.exception.code, 2)

    def test_accept_command_requires_execution_id(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                blender_admin_cli.build_parser().parse_args(
                    ["--project-root", "/tmp/project", "accept-production-task"]
                )
        self.assertEqual(raised.exception.code, 2)

    def test_cli_acceptance_surface_delegates_only_to_phase53_acceptor(self) -> None:
        source = inspect.getsource(blender_admin_cli)
        self.assertIn("GovernedBlenderProductionTaskAcceptor(runtime).accept", source)
        for forbidden in (
            "BlenderExportService",
            "ModelAdapter",
            "Specialist",
            "ConversationProcessor",
            "ManagerService",
            "subprocess",
            "release_authorized=True",
            "provenance_signed=True",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
