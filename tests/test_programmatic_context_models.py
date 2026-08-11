from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_models import (
    ContextArgument,
    ContextInstruction,
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextOperationEffect,
    ContextProgram,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
    ProgrammaticContextModelError,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _descriptor(*, operation_id: str = "context.lookup", max_calls: int = 2) -> ContextOperationDescriptor:
    return ContextOperationDescriptor(
        operation_id=operation_id,
        version="1",
        adapter_fingerprint=HASH_A,
        input_schema_hash=HASH_B,
        output_schema_hash=HASH_C,
        max_calls=max_calls,
        max_response_bytes=4096,
        replay_class=ContextReplayClass.DETERMINISTIC,
    )


class ProgrammaticContextModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ContextRequest.create(
            project_id=new_id(IdKind.PROJECT),
            objective="Collect the smallest exact evidence package needed for the next model call.",
        )
        self.catalog = ContextOperationCatalog.create((_descriptor(),))

    def test_program_is_exactly_bound_and_content_addressed(self) -> None:
        program = ContextProgram.create(
            request=self.request,
            catalog=self.catalog,
            budget=ContextProgramBudget(max_instructions=2, max_invocations=2),
            instructions=(
                ContextInstruction(
                    0,
                    "first",
                    "context.lookup",
                    "1",
                    (ContextArgument.literal("id", "RUN-1"),),
                ),
                ContextInstruction(
                    1,
                    "second",
                    "context.lookup",
                    "1",
                    (ContextArgument.ref("prior", "first"),),
                ),
            ),
            output_bindings=("second",),
        )
        program.bind(self.request, self.catalog)
        self.assertTrue(program.content_hash.startswith("sha256:"))
        self.assertFalse(program.to_dict()["arbitrary_code_authorized"])
        self.assertFalse(program.to_dict()["production_mutation_authorized"])

        changed_request = replace(self.request, objective="A different objective changes the request hash.")
        with self.assertRaisesRegex(ProgrammaticContextModelError, "exact request and catalog"):
            program.bind(changed_request, self.catalog)

    def test_forward_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProgrammaticContextModelError, "earlier binding"):
            ContextProgram.create(
                request=self.request,
                catalog=self.catalog,
                budget=ContextProgramBudget(),
                instructions=(
                    ContextInstruction(
                        0,
                        "first",
                        "context.lookup",
                        "1",
                        (ContextArgument.ref("value", "later"),),
                    ),
                    ContextInstruction(
                        1,
                        "later",
                        "context.lookup",
                        "1",
                        (),
                    ),
                ),
                output_bindings=("later",),
            )

    def test_rebinding_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProgrammaticContextModelError, "rebind"):
            ContextProgram.create(
                request=self.request,
                catalog=self.catalog,
                budget=ContextProgramBudget(),
                instructions=(
                    ContextInstruction(0, "same", "context.lookup", "1", ()),
                    ContextInstruction(1, "same", "context.lookup", "1", ()),
                ),
                output_bindings=("same",),
            )

    def test_instruction_indexes_must_be_contiguous(self) -> None:
        with self.assertRaisesRegex(ProgrammaticContextModelError, "contiguous"):
            ContextProgram.create(
                request=self.request,
                catalog=self.catalog,
                budget=ContextProgramBudget(),
                instructions=(ContextInstruction(1, "result", "context.lookup", "1", ()),),
                output_bindings=("result",),
            )

    def test_unknown_or_overused_operation_fails_catalog_binding(self) -> None:
        unknown = ContextProgram.create(
            request=self.request,
            catalog=self.catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "missing.operation", "1", ()),),
            output_bindings=("result",),
        )
        with self.assertRaisesRegex(ProgrammaticContextModelError, "not in frozen catalog"):
            unknown.bind(self.request, self.catalog)

        one_call_catalog = ContextOperationCatalog.create((_descriptor(max_calls=1),))
        too_many = ContextProgram.create(
            request=self.request,
            catalog=one_call_catalog,
            budget=ContextProgramBudget(max_instructions=2, max_invocations=2),
            instructions=(
                ContextInstruction(0, "a", "context.lookup", "1", ()),
                ContextInstruction(1, "b", "context.lookup", "1", ()),
            ),
            output_bindings=("b",),
        )
        with self.assertRaisesRegex(ProgrammaticContextModelError, "call limit"):
            too_many.bind(self.request, one_call_catalog)

    def test_v1_forbids_non_read_only_operation_effect(self) -> None:
        with self.assertRaises((ValueError, TypeError)):
            replace(_descriptor(), effect="WRITE")
        self.assertIs(_descriptor().effect, ContextOperationEffect.READ_ONLY)

    def test_literal_float_and_noncanonical_literal_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProgrammaticContextModelError, "floating-point"):
            ContextArgument.literal("threshold", 0.5)
        with self.assertRaisesRegex(ProgrammaticContextModelError, "canonical"):
            ContextArgument(
                name="data",
                kind=__import__(
                    "origin_forge.programmatic_context_models",
                    fromlist=["ContextArgumentKind"],
                ).ContextArgumentKind.LITERAL,
                literal_json='{ "x": 1 }',
            )


if __name__ == "__main__":
    unittest.main()
