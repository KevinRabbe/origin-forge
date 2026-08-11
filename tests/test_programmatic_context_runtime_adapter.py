from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_interpreter import (
    ContextAdapterRegistry,
    ContextProgramExecutionError,
    ContextProgramInterpreter,
)
from origin_forge.programmatic_context_models import (
    ContextArgument,
    ContextInstruction,
    ContextOperationCatalog,
    ContextProgram,
    ContextProgramBudget,
    ContextRequest,
)
from origin_forge.programmatic_context_runtime_adapter import (
    RUN_SHOW_OPERATION_ID,
    RUN_SHOW_OPERATION_VERSION,
    register_runtime_run_show_adapter,
)
from origin_forge.runs import create_run, finish_run
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import RunStatus, TaskStatus


class ProgrammaticContextRuntimeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("programmatic-context-runtime-test")
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(flow, "work")
        rev = self.runtime.transition_task(self.task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(self.task, TaskStatus.RUNNING, expected_revision=rev)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _execute(self, run_id: str):
        registry = ContextAdapterRegistry()
        descriptor = register_runtime_run_show_adapter(self.runtime, registry)
        catalog = ContextOperationCatalog.create((descriptor,))
        request = ContextRequest.create(
            project_id=self.runtime.project_id(),
            objective="Inspect the exact terminal Run through a governed read adapter.",
        )
        program = ContextProgram.create(
            request=request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(
                ContextInstruction(
                    0,
                    "run",
                    RUN_SHOW_OPERATION_ID,
                    RUN_SHOW_OPERATION_VERSION,
                    (ContextArgument.literal("run_id", run_id),),
                ),
            ),
            output_bindings=("run",),
        )
        return ContextProgramInterpreter(registry).execute(
            request=request,
            catalog=catalog,
            program=program,
        )

    def test_real_terminal_run_is_project_scoped_and_explicitly_projected(self) -> None:
        run_id = self.runtime.start_run(self.task, role="EXECUTOR", model_profile="local-test")
        self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
        result = self._execute(run_id)
        run = result.package.values["run"]
        self.assertEqual(run["id"], run_id)
        self.assertEqual(run["task_id"], self.task)
        self.assertEqual(run["status"], RunStatus.SUCCEEDED.value)
        self.assertEqual(run["role"], "EXECUTOR")
        self.assertEqual(run["model_profile"], "local-test")
        self.assertEqual(run["skills"], [])
        self.assertEqual(run["allowed_tools"], [])
        self.assertEqual(run["resource_metrics"], {})
        self.assertNotIn("rowid", run)
        self.assertNotIn("project_id", run)
        self.assertEqual(len(result.trace.steps), 1)
        self.assertFalse(result.package.to_dict()["production_mutation_authorized"])

    def test_running_run_is_not_disclosed_as_replayable_context(self) -> None:
        run_id = self.runtime.start_run(self.task, role="EXECUTOR")
        with self.assertRaisesRegex(ContextProgramExecutionError, "adapter failed"):
            self._execute(run_id)

    def test_taskless_infrastructure_run_is_rejected_without_project_ownership_chain(self) -> None:
        # Direct low-level construction is used only to prove the adapter rejects a
        # Run that OriginForgeRuntime.get_run cannot project-scope through a Task.
        run_id = create_run(self.runtime.store, None, role="INFRASTRUCTURE")
        finish_run(self.runtime.store, run_id, RunStatus.SUCCEEDED)
        with self.assertRaisesRegex(ContextProgramExecutionError, "adapter failed"):
            self._execute(run_id)

    def test_invalid_run_id_fails_input_validation_before_adapter_lookup(self) -> None:
        registry = ContextAdapterRegistry()
        descriptor = register_runtime_run_show_adapter(self.runtime, registry)
        catalog = ContextOperationCatalog.create((descriptor,))
        request = ContextRequest.create(
            project_id=self.runtime.project_id(),
            objective="Reject invalid IDs before durable-state lookup.",
        )
        program = ContextProgram.create(
            request=request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(
                ContextInstruction(
                    0,
                    "run",
                    RUN_SHOW_OPERATION_ID,
                    RUN_SHOW_OPERATION_VERSION,
                    (ContextArgument.literal("run_id", new_id(IdKind.TASK)),),
                ),
            ),
            output_bindings=("run",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "input validation"):
            ContextProgramInterpreter(registry).execute(
                request=request,
                catalog=catalog,
                program=program,
            )


if __name__ == "__main__":
    unittest.main()
