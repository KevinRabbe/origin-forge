from __future__ import annotations

import ast
import inspect
import json
import tempfile
import threading
import unittest

import origin_forge.production_task_activation as activation_module
from origin_forge.production_capability_routing import task_routing_hash
from origin_forge.production_task_activation import (
    TaskActivationError,
    activate_dependency_ready_task,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision, utc_now
from origin_forge.state import TaskStatus


class ProductionTaskActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("task-activation")
        self.goal_id = self.runtime.create_goal("activate ready tasks")
        self.flow_id = self.runtime.create_flow(self.goal_id)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, objective: str) -> str:
        return self.runtime.create_task(self.flow_id, objective)

    def _dependency(self, task_id: str, required_task_id: str) -> None:
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO task_dependencies(
                       task_id, required_task_id, dependency_type, created_at
                   ) VALUES (?, ?, 'REQUIRES_SUCCESS', ?)""",
                (task_id, required_task_id, utc_now()),
            )

    def _routing_hash(self, task_id: str) -> str:
        with self.runtime.store.session() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.assertIsNotNone(row)
            return task_routing_hash(row)

    def test_root_queued_task_activates_exactly_once_and_records_one_event(self) -> None:
        task_id = self._task("root ready task")
        before_hash = self._routing_hash(task_id)
        result = activate_dependency_ready_task(self.runtime, task_id, 0)

        task = self.runtime.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.READY.value)
        self.assertEqual(task["revision"], 1)
        self.assertEqual(result.previous_revision, 0)
        self.assertEqual(result.new_revision, 1)
        self.assertEqual(result.previous_task_content_hash, before_hash)
        self.assertEqual(result.new_task_content_hash, self._routing_hash(task_id))
        self.assertNotEqual(result.previous_task_content_hash, result.new_task_content_hash)
        self.assertEqual(result.dependency_count, 0)
        self.assertEqual(result.satisfied_dependency_count, 0)

        with self.runtime.store.session() as conn:
            rows = conn.execute(
                """SELECT * FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND event_type = 'TASK_STATUS_CHANGED'
                   ORDER BY created_at, id""",
                (task_id,),
            ).fetchall()
        activation_events = [
            row
            for row in rows
            if json.loads(row["metadata_json"]).get("reason")
            == "DEPENDENCY_READY_ACTIVATION"
        ]
        self.assertEqual(len(activation_events), 1)
        event = activation_events[0]
        self.assertEqual(event["old_state"], TaskStatus.QUEUED.value)
        self.assertEqual(event["new_state"], TaskStatus.READY.value)
        self.assertEqual(event["revision"], 1)
        self.assertEqual(event["actor_type"], "SYSTEM")

        with self.assertRaises((TaskActivationError, StaleRevision)):
            activate_dependency_ready_task(self.runtime, task_id, 0)
        self.assertEqual(self.runtime.get_task(task_id)["revision"], 1)

    def test_stale_revision_fails_before_mutation(self) -> None:
        task_id = self._task("stale activation")
        before = self.runtime.get_task(task_id)
        with self.assertRaises(StaleRevision):
            activate_dependency_ready_task(self.runtime, task_id, 7)
        self.assertEqual(self.runtime.get_task(task_id), before)
        with self.runtime.store.session() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND metadata_json LIKE '%DEPENDENCY_READY_ACTIVATION%'""",
                (task_id,),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_waiting_dependency_cannot_activate(self) -> None:
        required = self._task("unfinished prerequisite")
        dependent = self._task("waiting dependent")
        self._dependency(dependent, required)
        before = self.runtime.get_task(dependent)
        with self.assertRaisesRegex(TaskActivationError, "WAITING_ON_DEPENDENCIES"):
            activate_dependency_ready_task(self.runtime, dependent, 0)
        self.assertEqual(self.runtime.get_task(dependent), before)

    def test_failed_dependency_cannot_activate(self) -> None:
        required = self._task("failed prerequisite")
        dependent = self._task("blocked dependent")
        self._dependency(dependent, required)
        self.runtime.transition_task(required, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(required, TaskStatus.RUNNING, expected_revision=1)
        self.runtime.transition_task(required, TaskStatus.FAILED, expected_revision=2)
        with self.assertRaisesRegex(
            TaskActivationError,
            "BLOCKED_BY_FAILED_DEPENDENCY",
        ):
            activate_dependency_ready_task(self.runtime, dependent, 0)
        self.assertEqual(self.runtime.get_task(dependent)["status"], TaskStatus.QUEUED.value)

    def test_succeeded_dependency_without_pass_is_invalid_and_cannot_activate(self) -> None:
        required = self._task("invalid succeeded prerequisite")
        dependent = self._task("invalid dependent")
        self._dependency(dependent, required)
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'SUCCEEDED' WHERE id = ?",
                (required,),
            )
        with self.assertRaisesRegex(
            TaskActivationError,
            "INVALID_DEPENDENCY_STATE",
        ):
            activate_dependency_ready_task(self.runtime, dependent, 0)
        self.assertEqual(self.runtime.get_task(dependent)["revision"], 0)

    def test_satisfied_dependency_activates_with_same_transaction_readiness_evidence(self) -> None:
        required = self._task("satisfied prerequisite")
        dependent = self._task("ready dependent")
        self._dependency(dependent, required)
        self.runtime.transition_task(required, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(required, TaskStatus.RUNNING, expected_revision=1)
        run_id = self.runtime.start_run(required, role="EXECUTOR")
        self.runtime.finish_run(run_id, TaskStatus.SUCCEEDED.value)
        self.runtime.record_verification(
            "TASK",
            required,
            verification_type="test",
            verifier="test",
            status="PASS",
            run_id=run_id,
        )
        self.runtime.transition_task(required, TaskStatus.SUCCEEDED, expected_revision=2)

        result = activate_dependency_ready_task(self.runtime, dependent, 0)
        self.assertEqual(result.dependency_count, 1)
        self.assertEqual(result.satisfied_dependency_count, 1)
        self.assertEqual(self.runtime.get_task(dependent)["status"], TaskStatus.READY.value)

    def test_concurrent_activation_attempts_produce_one_winner_and_one_event(self) -> None:
        task_id = self._task("concurrent activation")
        barrier = threading.Barrier(2)
        successes: list[object] = []
        failures: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            try:
                result = activate_dependency_ready_task(self.runtime, task_id, 0)
            except BaseException as exc:  # test captures exact loser behavior
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    successes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], (TaskActivationError, StaleRevision))
        self.assertEqual(self.runtime.get_task(task_id)["revision"], 1)

        with self.runtime.store.session() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM state_events
                   WHERE aggregate_type = 'TASK' AND aggregate_id = ?
                     AND metadata_json LIKE '%DEPENDENCY_READY_ACTIVATION%'""",
                (task_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_activation_api_has_only_task_and_expected_revision_authority(self) -> None:
        signature = inspect.signature(activate_dependency_ready_task)
        self.assertEqual(
            tuple(signature.parameters),
            ("runtime", "task_id", "expected_revision"),
        )
        source = inspect.getsource(activation_module)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("importlib", source)
        tree = ast.parse(source)
        forbidden = {
            "drive",
            "generate",
            "dispatch",
            "start_run",
            "create_run",
            "finish_run",
            "record_verification",
            "create_workspace",
            "publish_binding",
            "publish_audit",
            "acquire",
            "lease",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
