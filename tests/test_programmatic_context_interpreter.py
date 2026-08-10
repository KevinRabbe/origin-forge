from __future__ import annotations

import unittest
from dataclasses import replace

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
    ContextOperationDescriptor,
    ContextProgram,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def _descriptor(
    operation_id: str,
    fingerprint: str,
    *,
    max_calls: int = 4,
    max_response_bytes: int = 4096,
) -> ContextOperationDescriptor:
    return ContextOperationDescriptor(
        operation_id=operation_id,
        version="1",
        adapter_fingerprint=fingerprint,
        input_schema_hash=HASH_B,
        output_schema_hash=HASH_C,
        max_calls=max_calls,
        max_response_bytes=max_response_bytes,
        replay_class=ContextReplayClass.DETERMINISTIC,
    )


def _mapping_input(value) -> None:
    if not isinstance(value, dict):
        raise ValueError("input must be mapping")


def _mapping_output(value) -> None:
    if not isinstance(value, dict):
        raise ValueError("output must be mapping")


class ProgrammaticContextInterpreterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = _descriptor("context.lookup", HASH_A)
        self.select = _descriptor("context.select", HASH_D)
        self.catalog = ContextOperationCatalog.create((self.lookup, self.select))
        self.request = ContextRequest.create(
            project_id=new_id(IdKind.PROJECT),
            objective="Build one exact read-only context package.",
        )
        self.registry = ContextAdapterRegistry()
        self.registry.register(
            self.lookup,
            lambda args: {"id": args.get("id"), "facts": ["alpha", "beta"]},
            validate_input=_mapping_input,
            validate_output=_mapping_output,
        )
        self.registry.register(
            self.select,
            lambda args: {"selected": args["source"]["facts"][: args["limit"]]},
            validate_input=_mapping_input,
            validate_output=_mapping_output,
        )
        self.interpreter = ContextProgramInterpreter(self.registry)

    def _program(self, *, budget: ContextProgramBudget | None = None) -> ContextProgram:
        return ContextProgram.create(
            request=self.request,
            catalog=self.catalog,
            budget=budget or ContextProgramBudget(max_instructions=4, max_invocations=4),
            instructions=(
                ContextInstruction(
                    0,
                    "lookup",
                    "context.lookup",
                    "1",
                    (ContextArgument.literal("id", "RUN-123"),),
                ),
                ContextInstruction(
                    1,
                    "selected",
                    "context.select",
                    "1",
                    (
                        ContextArgument.literal("limit", 1),
                        ContextArgument.ref("source", "lookup"),
                    ),
                ),
            ),
            output_bindings=("selected",),
        )

    def test_executes_exact_read_only_program_and_emits_reconstructable_trace(self) -> None:
        program = self._program()
        result = self.interpreter.execute(
            request=self.request,
            catalog=self.catalog,
            program=program,
        )
        self.assertEqual(result.package.values, {"selected": {"selected": ["alpha"]}})
        self.assertEqual(len(result.trace.steps), 2)
        self.assertEqual(result.trace.steps[0].adapter_fingerprint, HASH_A)
        self.assertEqual(result.trace.steps[1].adapter_fingerprint, HASH_D)
        self.assertEqual(result.trace.package_hash, result.package.content_hash)
        self.assertFalse(result.production_task_verified)
        self.assertFalse(result.production_mutation_authorized)
        self.assertFalse(result.package.to_dict()["production_task_verified"])

    def test_intermediate_binding_is_not_disclosed_unless_declared_output(self) -> None:
        result = self.interpreter.execute(
            request=self.request,
            catalog=self.catalog,
            program=self._program(),
        )
        self.assertNotIn("lookup", result.package.values)
        self.assertIn("selected", result.package.values)

    def test_registry_descriptor_drift_fails_closed(self) -> None:
        drifted_catalog = ContextOperationCatalog.create(
            (replace(self.lookup, adapter_fingerprint=HASH_D), self.select)
        )
        program = ContextProgram.create(
            request=self.request,
            catalog=drifted_catalog,
            budget=ContextProgramBudget(),
            instructions=(
                ContextInstruction(0, "result", "context.lookup", "1", ()),
            ),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "descriptor drifted"):
            self.interpreter.execute(
                request=self.request,
                catalog=drifted_catalog,
                program=program,
            )

    def test_unregistered_operation_cannot_execute(self) -> None:
        descriptor = _descriptor("context.other", HASH_C)
        catalog = ContextOperationCatalog.create((descriptor,))
        program = ContextProgram.create(
            request=self.request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.other", "1", ()),),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "no registered context adapter"):
            self.interpreter.execute(request=self.request, catalog=catalog, program=program)

    def test_adapter_exception_is_infrastructure_failure_not_partial_success(self) -> None:
        registry = ContextAdapterRegistry()

        def fail(_args):
            raise RuntimeError("backend unavailable")

        registry.register(
            self.lookup,
            fail,
            validate_input=_mapping_input,
            validate_output=_mapping_output,
        )
        program = ContextProgram.create(
            request=self.request,
            catalog=ContextOperationCatalog.create((self.lookup,)),
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.lookup", "1", ()),),
            output_bindings=("result",),
        )
        # Recreate program against exact catalog used for execution.
        catalog = ContextOperationCatalog.create((self.lookup,))
        program = ContextProgram.create(
            request=self.request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.lookup", "1", ()),),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "adapter failed"):
            ContextProgramInterpreter(registry).execute(
                request=self.request,
                catalog=catalog,
                program=program,
            )

    def test_per_operation_response_limit_is_active(self) -> None:
        tiny = _descriptor("context.tiny", HASH_C, max_response_bytes=8)
        catalog = ContextOperationCatalog.create((tiny,))
        registry = ContextAdapterRegistry()
        registry.register(
            tiny,
            lambda _args: {"value": "far-too-large"},
            validate_input=_mapping_input,
            validate_output=_mapping_output,
        )
        program = ContextProgram.create(
            request=self.request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.tiny", "1", ()),),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "invalid bounded JSON"):
            ContextProgramInterpreter(registry).execute(
                request=self.request,
                catalog=catalog,
                program=program,
            )

    def test_aggregate_result_budget_is_active(self) -> None:
        program = self._program(
            budget=ContextProgramBudget(
                max_instructions=4,
                max_invocations=4,
                max_result_bytes=20,
                max_context_bytes=4096,
            )
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "aggregate result-byte"):
            self.interpreter.execute(
                request=self.request,
                catalog=self.catalog,
                program=program,
            )

    def test_adapter_float_output_is_rejected_even_if_validator_accepts_it(self) -> None:
        descriptor = _descriptor("context.float", HASH_C)
        catalog = ContextOperationCatalog.create((descriptor,))
        registry = ContextAdapterRegistry()
        registry.register(
            descriptor,
            lambda _args: {"score": 0.5},
            validate_input=_mapping_input,
            validate_output=_mapping_output,
        )
        program = ContextProgram.create(
            request=self.request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.float", "1", ()),),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ContextProgramExecutionError, "invalid bounded JSON"):
            ContextProgramInterpreter(registry).execute(
                request=self.request,
                catalog=catalog,
                program=program,
            )


if __name__ == "__main__":
    unittest.main()
