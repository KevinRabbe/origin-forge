from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskDependencyType
from origin_forge.task_dependencies import (
    TaskDependencyError,
    add_task_dependency,
    flow_dependency_graph,
    list_task_dependencies,
    list_task_dependents,
)


class TaskDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("dependency-test")
        self.goal = self.runtime.create_goal("Build a governed dependency graph")
        self.flow = self.runtime.create_flow(self.goal)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, objective: str, *, flow_id: str | None = None) -> str:
        return self.runtime.create_task(flow_id or self.flow, objective)

    def test_dependency_edges_are_structured_deterministic_and_evented(self) -> None:
        code = self._task("Implement code")
        art = self._task("Create art")
        integration = self._task("Integrate feature")

        edge_art = add_task_dependency(self.runtime.store, integration, art)
        edge_code = add_task_dependency(self.runtime.store, integration, code)

        self.assertEqual(edge_art.dependency_type, TaskDependencyType.REQUIRES_SUCCESS)
        self.assertEqual(edge_code.dependency_type, TaskDependencyType.REQUIRES_SUCCESS)
        self.assertEqual(
            [edge.required_task_id for edge in list_task_dependencies(self.runtime.store, integration)],
            sorted((art, code)),
        )
        self.assertEqual(
            [edge.task_id for edge in list_task_dependents(self.runtime.store, code)],
            [integration],
        )

        graph = flow_dependency_graph(self.runtime.store, self.flow)
        self.assertEqual(graph.task_ids, tuple(sorted((code, art, integration))))
        self.assertEqual(
            [(edge.task_id, edge.required_task_id) for edge in graph.edges],
            sorted(((integration, art), (integration, code))),
        )
        self.assertEqual(graph.max_depth, 2)
        self.assertEqual(graph.topological_task_ids[-1], integration)
        self.assertLess(graph.topological_task_ids.index(code), graph.topological_task_ids.index(integration))
        self.assertLess(graph.topological_task_ids.index(art), graph.topological_task_ids.index(integration))

        history = self.runtime.store.event_history(
            "TASK_DEPENDENCY",
            f"{integration}|{code}",
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["event_type"], "TASK_DEPENDENCY_CREATED")
        self.assertEqual(history[0]["new_state"], TaskDependencyType.REQUIRES_SUCCESS.value)

    def test_self_cross_flow_duplicate_and_cycle_fail_closed(self) -> None:
        a = self._task("A")
        b = self._task("B")
        c = self._task("C")
        other_flow = self.runtime.create_flow(self.goal)
        other = self._task("Other", flow_id=other_flow)

        with self.assertRaisesRegex(TaskDependencyError, "depend on itself"):
            add_task_dependency(self.runtime.store, a, a)
        with self.assertRaisesRegex(TaskDependencyError, "same flow"):
            add_task_dependency(self.runtime.store, a, other)

        add_task_dependency(self.runtime.store, b, a)
        with self.assertRaisesRegex(TaskDependencyError, "already exists"):
            add_task_dependency(self.runtime.store, b, a)

        add_task_dependency(self.runtime.store, c, b)
        with self.assertRaisesRegex(TaskDependencyError, "create a cycle"):
            add_task_dependency(self.runtime.store, a, c)

        graph = flow_dependency_graph(self.runtime.store, self.flow)
        self.assertEqual(len(graph.edges), 2)
        self.assertEqual(graph.max_depth, 3)
        self.assertLess(graph.topological_task_ids.index(a), graph.topological_task_ids.index(b))
        self.assertLess(graph.topological_task_ids.index(b), graph.topological_task_ids.index(c))

    def test_dependencies_persist_across_runtime_restart(self) -> None:
        required = self._task("Required")
        dependent = self._task("Dependent")
        add_task_dependency(self.runtime.store, dependent, required)
        before = flow_dependency_graph(self.runtime.store, self.flow).to_dict()

        restarted = OriginForgeRuntime(self.root)
        self.assertEqual(restarted.project_id(), self.runtime.project_id())
        after = flow_dependency_graph(restarted.store, self.flow).to_dict()
        self.assertEqual(after, before)

    def test_database_constraints_defend_against_direct_bypass(self) -> None:
        a = self._task("A")
        b = self._task("B")
        c = self._task("C")
        other_flow = self.runtime.create_flow(self.goal)
        other = self._task("Other", flow_id=other_flow)

        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    """INSERT INTO task_dependencies(
                           task_id, required_task_id, dependency_type, created_at
                       ) VALUES (?, ?, 'REQUIRES_SUCCESS', '2026-08-11T00:00:00Z')""",
                    (a, a),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    """INSERT INTO task_dependencies(
                           task_id, required_task_id, dependency_type, created_at
                       ) VALUES (?, ?, 'REQUIRES_SUCCESS', '2026-08-11T00:00:00Z')""",
                    (a, other),
                )

        add_task_dependency(self.runtime.store, b, a)
        add_task_dependency(self.runtime.store, c, b)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    """INSERT INTO task_dependencies(
                           task_id, required_task_id, dependency_type, created_at
                       ) VALUES (?, ?, 'REQUIRES_SUCCESS', '2026-08-11T00:00:00Z')""",
                    (a, c),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.runtime.store.session() as conn:
                conn.execute(
                    """INSERT INTO task_dependencies(
                           task_id, required_task_id, dependency_type, created_at
                       ) VALUES (?, ?, 'UNKNOWN', '2026-08-11T00:00:00Z')""",
                    (c, a),
                )

    def test_missing_task_references_fail_before_publication(self) -> None:
        task = self._task("Task")
        with self.assertRaises(KeyError):
            add_task_dependency(self.runtime.store, task, "TASK-not-real")
        with self.assertRaises(KeyError):
            list_task_dependencies(self.runtime.store, "TASK-not-real")
        with self.assertRaises(KeyError):
            list_task_dependents(self.runtime.store, "TASK-not-real")


if __name__ == "__main__":
    unittest.main()
