from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.task_readiness as task_readiness_module
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus
from origin_forge.task_dependencies import add_task_dependency
from origin_forge.task_readiness import (
    DependencyReadinessStatus,
    DependencyReasonKind,
    resolve_task_dependency_readiness,
)


class TaskReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("readiness-test")
        goal = self.runtime.create_goal("Resolve dependency eligibility")
        self.flow = self.runtime.create_flow(goal)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, objective: str) -> str:
        return self.runtime.create_task(self.flow, objective)

    def _succeed(self, task_id: str) -> None:
        revision = self.runtime.transition_task(task_id, TaskStatus.READY, expected_revision=0)
        revision = self.runtime.transition_task(
            task_id,
            TaskStatus.RUNNING,
            expected_revision=revision,
        )
        self.runtime.record_verification(
            "TASK",
            task_id,
            verification_type="test",
            verifier="readiness-test",
            status="PASS",
        )
        self.runtime.transition_task(
            task_id,
            TaskStatus.SUCCEEDED,
            expected_revision=revision,
        )

    def _fail(self, task_id: str) -> None:
        revision = self.runtime.transition_task(task_id, TaskStatus.READY, expected_revision=0)
        revision = self.runtime.transition_task(
            task_id,
            TaskStatus.RUNNING,
            expected_revision=revision,
        )
        self.runtime.transition_task(
            task_id,
            TaskStatus.FAILED,
            expected_revision=revision,
        )

    def test_root_task_is_dependency_ready_without_state_transition(self) -> None:
        task = self._task("Root")
        before = self.runtime.get_task(task)
        result = resolve_task_dependency_readiness(self.runtime.store, task)
        after = self.runtime.get_task(task)

        self.assertEqual(result.status, DependencyReadinessStatus.READY)
        self.assertEqual(result.task_status, TaskStatus.QUEUED)
        self.assertEqual(result.dependency_count, 0)
        self.assertEqual(result.satisfied_dependency_count, 0)
        self.assertEqual(result.reasons, ())
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])

    def test_dependent_waits_until_required_task_succeeds_with_pass(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)

        waiting = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(waiting.status, DependencyReadinessStatus.WAITING_ON_DEPENDENCIES)
        self.assertEqual(waiting.satisfied_dependency_count, 0)
        self.assertEqual(len(waiting.reasons), 1)
        self.assertEqual(waiting.reasons[0].required_task_id, required)
        self.assertEqual(waiting.reasons[0].required_task_status, TaskStatus.QUEUED)
        self.assertEqual(waiting.reasons[0].reason_kind, DependencyReasonKind.WAITING)

        self._succeed(required)
        ready = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(ready.status, DependencyReadinessStatus.READY)
        self.assertEqual(ready.dependency_count, 1)
        self.assertEqual(ready.satisfied_dependency_count, 1)
        self.assertEqual(ready.reasons, ())
        self.assertEqual(self.runtime.get_task(dependent)["status"], TaskStatus.QUEUED.value)

    def test_failed_prerequisite_produces_blocked_evidence_without_mutation(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)
        self._fail(required)

        before = self.runtime.get_task(dependent)
        result = resolve_task_dependency_readiness(self.runtime.store, dependent)
        after = self.runtime.get_task(dependent)

        self.assertEqual(result.status, DependencyReadinessStatus.BLOCKED_BY_FAILED_DEPENDENCY)
        self.assertEqual(result.reasons[0].reason_kind, DependencyReasonKind.FAILED)
        self.assertEqual(result.reasons[0].required_task_status, TaskStatus.FAILED)
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["revision"], after["revision"])

    def test_multi_parent_requires_every_prerequisite(self) -> None:
        a = self._task("A")
        b = self._task("B")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, b)
        add_task_dependency(self.runtime.store, dependent, a)

        self._succeed(a)
        partial = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(partial.status, DependencyReadinessStatus.WAITING_ON_DEPENDENCIES)
        self.assertEqual(partial.dependency_count, 2)
        self.assertEqual(partial.satisfied_dependency_count, 1)
        self.assertEqual([reason.required_task_id for reason in partial.reasons], [b])

        self._succeed(b)
        ready = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(ready.status, DependencyReadinessStatus.READY)
        self.assertEqual(ready.satisfied_dependency_count, 2)

    def test_succeeded_dependency_without_pass_is_invalid_fail_closed_evidence(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'SUCCEEDED' WHERE id = ?",
                (required,),
            )

        result = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(result.status, DependencyReadinessStatus.INVALID_DEPENDENCY_STATE)
        self.assertEqual(
            result.reasons[0].reason_kind,
            DependencyReasonKind.MISSING_PASS_VERIFICATION,
        )
        self.assertEqual(result.reasons[0].required_verification_status, "MISSING_PASS")

    def test_readiness_reconstructs_identically_after_restart(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)
        before = resolve_task_dependency_readiness(self.runtime.store, dependent).to_dict()

        restarted = OriginForgeRuntime(self.root)
        after = resolve_task_dependency_readiness(restarted.store, dependent).to_dict()
        self.assertEqual(after, before)

    def test_running_task_with_satisfied_dependencies_is_active(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)
        self._succeed(required)
        revision = self.runtime.transition_task(dependent, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(dependent, TaskStatus.RUNNING, expected_revision=revision)

        result = resolve_task_dependency_readiness(self.runtime.store, dependent)
        self.assertEqual(result.status, DependencyReadinessStatus.ACTIVE)
        self.assertEqual(result.task_status, TaskStatus.RUNNING)

    def test_terminal_task_is_not_requeued_by_readiness_inspection(self) -> None:
        task = self._task("Terminal")
        self.runtime.transition_task(task, TaskStatus.CANCELLED, expected_revision=0)
        result = resolve_task_dependency_readiness(self.runtime.store, task)
        self.assertEqual(result.status, DependencyReadinessStatus.TERMINAL)
        self.assertEqual(result.task_status, TaskStatus.CANCELLED)
        self.assertEqual(self.runtime.get_task(task)["status"], TaskStatus.CANCELLED.value)

    def test_resolver_source_has_no_write_or_model_authority(self) -> None:
        source = inspect.getsource(task_readiness_module)
        for forbidden in (
            "UPDATE ",
            "INSERT ",
            "DELETE ",
            "transition_task",
            "start_run",
            "model_client",
            "subprocess",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
