from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.simulation_engine import SimulationEngineError
from origin_forge.simulation_models import (
    STATE_MAX,
    SimulationInvariant,
    SimulationRule,
    SimulationSpec,
)
from origin_forge.simulation_service import SimulationService, SimulationServiceError
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


class SimulationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("simulation-service-test")
        goal = self.runtime.create_goal("Simulate game system")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(flow, "Run deterministic simulation")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _spec() -> SimulationSpec:
        return SimulationSpec.create(
            seed=101,
            initial_state=(("gold", 0), ("stock", 2)),
            rules=(
                SimulationRule("income", 0, 1_000_000, produce=(("gold", 2),)),
                SimulationRule(
                    "purchase",
                    1,
                    1_000_000,
                    consume=(("stock", 1),),
                    produce=(("gold", 1),),
                ),
            ),
            invariants=(SimulationInvariant("gold-cap", "gold", maximum=5),),
            replicates=2,
            max_steps=3,
            stall_steps=3,
        )

    @staticmethod
    def _assert_task_observation_only(before, after) -> None:
        if after["status"] != TaskStatus.RUNNING.value:
            raise AssertionError("simulation changed production Task status")
        if after["revision"] != before["revision"]:
            raise AssertionError("simulation changed production Task revision")
        if after["attempt_count"] != before["attempt_count"] + 1:
            raise AssertionError("simulation did not record exactly one Run attempt")
        if after["assigned_run_id"] is not None:
            raise AssertionError("finished simulation left Task assigned")

    def test_success_persists_lineage_without_task_authority(self) -> None:
        before = self.runtime.get_task(self.task)
        result = SimulationService(self.runtime).execute(self.task, self._spec())
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])
        self.assertFalse(result.to_dict()["production_task_verified"])
        self.assertFalse(result.to_dict()["semantic_balance_verified"])
        self.assertFalse(result.to_dict()["automatic_tuning_authorized"])

        run = self.runtime.get_run(result.run_id)
        self.assertEqual(run["role"], SimulationService.RUN_ROLE)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        verification = self.runtime.list_verifications("RUN", result.run_id)
        self.assertEqual(len(verification), 1)
        self.assertEqual(verification[0]["verification_type"], "simulation-structure")
        evidence = json.loads(verification[0]["evidence_json"])
        self.assertEqual(evidence["result_hash"], result.result_hash)
        self.assertFalse(evidence["production_task_verified"])
        self.assertFalse(evidence["semantic_balance_verified"])
        self.assertFalse(evidence["automatic_tuning_authorized"])

        lineage = OriginForgeLineage(self.runtime)
        artifacts = {artifact["id"]: artifact for artifact in lineage.list_artifacts()}
        expected = {
            result.spec_artifact_id: "SIMULATION_SPEC",
            result.result_artifact_id: "SIMULATION_RESULT",
            result.summary_artifact_id: "SIMULATION_SUMMARY",
        }
        for artifact_id, artifact_type in expected.items():
            self.assertEqual(artifacts[artifact_id]["type"], artifact_type)
            lineage.local_artifact_path(artifact_id)

    def test_negative_simulation_findings_do_not_fail_service_or_task(self) -> None:
        spec = SimulationSpec.create(
            seed=102,
            initial_state=(("value", 0),),
            rules=(SimulationRule("never", 0, 0, produce=(("value", 1),)),),
            invariants=(SimulationInvariant("must-progress", "value", minimum=1),),
            max_steps=10,
            stall_steps=2,
        )
        before = self.runtime.get_task(self.task)
        result = SimulationService(self.runtime).execute(self.task, spec)
        self.assertEqual(result.summary.stalled_replicates, 1)
        self.assertEqual(result.summary.violation_count, 3)
        self.assertEqual(self.runtime.get_run(result.run_id)["status"], RunStatus.SUCCEEDED.value)
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_engine_failure_marks_only_simulator_run_failed(self) -> None:
        spec = SimulationSpec.create(
            seed=103,
            initial_state=(("value", STATE_MAX),),
            rules=(SimulationRule("overflow", 0, 1_000_000, produce=(("value", 1),)),),
            max_steps=1,
            stall_steps=1,
        )
        before = self.runtime.get_task(self.task)
        with self.assertRaisesRegex(SimulationEngineError, "overflow"):
            SimulationService(self.runtime).execute(self.task, spec)
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])
        runs = [
            run
            for run in self.runtime.list_runs(self.task)
            if run["role"] == SimulationService.RUN_ROLE
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], RunStatus.FAILED.value)
        self.assertEqual(self.runtime.list_verifications("TASK", self.task), [])

    def test_preexisting_workspace_is_rejected_before_artifact_persistence(self) -> None:
        spec = self._spec()
        workspace = self.runtime.state_dir / "simulations" / spec.workspace_id
        workspace.mkdir(parents=True)
        with self.assertRaisesRegex(SimulationServiceError, "already exists"):
            SimulationService(self.runtime).execute(self.task, spec)
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_symlink_workspace_is_rejected_before_artifact_persistence(self) -> None:
        spec = self._spec()
        simulation_root = self.runtime.state_dir / "simulations"
        simulation_root.mkdir()
        target = self.runtime.state_dir / "simulation-escape-target"
        target.mkdir()
        (simulation_root / spec.workspace_id).symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(SimulationServiceError, "already exists"):
            SimulationService(self.runtime).execute(self.task, spec)
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_spoofed_engine_identity_fails_before_artifact_persistence(self) -> None:
        spec = SimulationSpec.create(
            seed=104,
            initial_state=(("value", 0),),
            rules=(SimulationRule("income", 0, 1_000_000, produce=(("value", 1),)),),
            max_steps=1,
            stall_steps=1,
            engine_id="spoofed-engine",
            engine_version="9",
        )
        with self.assertRaisesRegex(SimulationEngineError, "engine identity"):
            SimulationService(self.runtime).execute(self.task, spec)
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_evidence_byte_limit_fails_before_artifact_persistence(self) -> None:
        before = self.runtime.get_task(self.task)
        with patch("origin_forge.simulation_service.MAX_SIMULATION_EVIDENCE_BYTES", 1):
            with self.assertRaisesRegex(SimulationServiceError, "byte limit"):
                SimulationService(self.runtime).execute(self.task, self._spec())
        self._assert_task_observation_only(before, self.runtime.get_task(self.task))
        self.assertEqual(OriginForgeLineage(self.runtime).list_artifacts(), [])

    def test_service_exposes_no_production_mutation_or_release_authority(self) -> None:
        service = SimulationService(self.runtime)
        for forbidden in (
            "transition_task",
            "verify_task",
            "complete_task",
            "tune",
            "mutate_config",
            "adopt",
            "sign",
            "merge",
            "release",
            "shell",
            "script",
        ):
            self.assertFalse(hasattr(service, forbidden))


if __name__ == "__main__":
    unittest.main()
