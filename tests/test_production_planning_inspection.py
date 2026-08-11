from __future__ import annotations

import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_planning_inspection as inspection_module
from origin_forge.production_planning_evidence import (
    ProductionPlanningEvidenceStore,
    freeze_planning_input,
)
from origin_forge.production_planning_inspection import (
    ProductionPlanningInspectionError,
    inspect_flow_dependency_graph,
    inspect_plan_audit,
    inspect_plan_materialization,
    inspect_plan_proposal,
    inspect_planning_input,
    inspect_production_planning_status,
    inspect_task_dependency_readiness,
)
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_read_guard import ProductionReadGuardError
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.task_readiness import DependencyReadinessStatus


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stat_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class ProductionPlanningInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("planning-inspection-test")
        self.goal = self.runtime.create_goal(
            "Inspect a governed production plan",
            success_criteria=("Plan is reconstructable.",),
        )
        self.evidence = ProductionPlanningEvidenceStore(self.runtime)
        self.planning_input = freeze_planning_input(
            self.runtime,
            self.goal,
            project_intelligence_hash=_sha("project-intelligence"),
            capability_catalog_hash=_sha("catalog"),
            capability_ids=("code", "runtime-observation"),
            model_policy_hash=_sha("model-policy"),
            resource_policy_hash=_sha("resource-policy"),
        )
        self.proposal = PlanProposal.create(
            planning_input=self.planning_input,
            summary="Implement and observe the requested behavior.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement the behavior.",
                    acceptance_criteria=("Implementation tests pass.",),
                    constraints=("Keep the change bounded.",),
                    required_capabilities=("code",),
                    priority=50,
                    max_attempts=2,
                ),
                PlanStep(
                    step_key="runtime",
                    objective="Observe runtime behavior.",
                    acceptance_criteria=("Runtime evidence is captured.",),
                    required_capabilities=("runtime-observation",),
                    priority=40,
                    depends_on=("code",),
                ),
            ),
        )
        self.audit = audit_plan(self.planning_input, self.proposal)
        self.evidence.publish_input(self.planning_input)
        self.evidence.publish_proposal(self.proposal)
        self.evidence.publish_audit(self.audit)
        self.materialization = self.evidence.materialize(
            planning_input_id=self.planning_input.planning_input_id,
            proposal_id=self.proposal.proposal_id,
            audit_id=self.audit.audit_id,
        )
        self.bindings = {
            binding.step_key: binding.task_id
            for binding in self.materialization.task_bindings
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_status_and_typed_evidence_reads_revalidate_without_database_mutation(self) -> None:
        database = self.runtime.store.db_path
        before_bytes = database.read_bytes()
        before_stat = _stat_identity(database)

        status = inspect_production_planning_status(self.runtime)
        self.assertEqual(status.project_id, self.runtime.project_id())
        self.assertEqual(status.planning_input_count, 1)
        self.assertEqual(status.proposal_count, 1)
        self.assertEqual(status.audit_count, 1)
        self.assertEqual(status.materialization_count, 1)
        self.assertEqual(status.dependency_edge_count, 1)

        self.assertEqual(
            inspect_planning_input(self.runtime, self.planning_input.planning_input_id),
            self.planning_input,
        )
        self.assertEqual(
            inspect_plan_proposal(self.runtime, self.proposal.proposal_id),
            self.proposal,
        )
        self.assertEqual(
            inspect_plan_audit(self.runtime, self.audit.audit_id),
            self.audit,
        )
        self.assertEqual(
            inspect_plan_materialization(
                self.runtime,
                self.materialization.materialization_id,
            ),
            self.materialization,
        )

        self.assertEqual(database.read_bytes(), before_bytes)
        self.assertEqual(_stat_identity(database), before_stat)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(database) + suffix).exists())

    def test_graph_and_readiness_use_same_immutable_database_snapshot_boundary(self) -> None:
        graph = inspect_flow_dependency_graph(self.runtime, self.materialization.flow_id)
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(graph.edges[0].task_id, self.bindings["runtime"])
        self.assertEqual(graph.edges[0].required_task_id, self.bindings["code"])
        self.assertLess(
            graph.topological_task_ids.index(self.bindings["code"]),
            graph.topological_task_ids.index(self.bindings["runtime"]),
        )

        readiness = inspect_task_dependency_readiness(
            self.runtime,
            self.bindings["runtime"],
        )
        self.assertEqual(
            readiness.status,
            DependencyReadinessStatus.WAITING_ON_DEPENDENCIES,
        )
        self.assertEqual(readiness.reasons[0].required_task_id, self.bindings["code"])

    def test_materialization_inspection_detects_relational_task_contract_drift(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET objective = 'tampered objective' WHERE id = ?",
                (self.bindings["code"],),
            )

        with self.assertRaisesRegex(
            ProductionPlanningInspectionError,
            "objective/parent drifted",
        ):
            inspect_plan_materialization(
                self.runtime,
                self.materialization.materialization_id,
            )

    def test_materialization_inspection_detects_dependency_graph_drift(self) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                "DELETE FROM task_dependencies WHERE task_id = ? AND required_task_id = ?",
                (self.bindings["runtime"], self.bindings["code"]),
            )

        with self.assertRaisesRegex(
            ProductionPlanningInspectionError,
            "dependency graph drifted",
        ):
            inspect_plan_materialization(
                self.runtime,
                self.materialization.materialization_id,
            )

    def test_unknown_cross_project_style_ids_fail_closed(self) -> None:
        for callback, object_id in (
            (inspect_planning_input, "PLINPUT-not-real"),
            (inspect_plan_proposal, "PLPROP-not-real"),
            (inspect_plan_audit, "PLAUD-not-real"),
            (inspect_plan_materialization, "PLMAT-not-real"),
            (inspect_flow_dependency_graph, "FLOW-not-real"),
            (inspect_task_dependency_readiness, "TASK-not-real"),
        ):
            with self.assertRaises(KeyError):
                callback(self.runtime, object_id)

    def test_uninitialized_inspection_creates_no_origin_forge_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            state = root / ".origin-forge"
            with self.assertRaises(ProductionReadGuardError):
                inspect_production_planning_status(runtime)
            self.assertFalse(state.exists())

    def test_inspection_source_has_no_store_writer_model_or_materialization_authority(self) -> None:
        source = inspect.getsource(inspection_module)
        for forbidden in (
            ".store.session(",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            ".materialize(",
            ".generate(",
            "create_run(",
            "create_flow(",
            "create_task(",
            "transition_task(",
            "subprocess",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
