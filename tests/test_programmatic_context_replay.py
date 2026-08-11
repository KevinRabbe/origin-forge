from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id
from origin_forge.programmatic_context_interpreter import (
    ContextAdapterRegistry,
    ContextProgramInterpreter,
)
from origin_forge.programmatic_context_models import (
    ContextInstruction,
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextProgram,
    ContextProgramBudget,
    ContextReplayClass,
    ContextRequest,
)
from origin_forge.programmatic_context_replay import (
    ContextReplayVerificationError,
    verify_deterministic_replay,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _descriptor(replay_class: ContextReplayClass) -> ContextOperationDescriptor:
    return ContextOperationDescriptor(
        operation_id="context.replay",
        version="1",
        adapter_fingerprint=HASH_A,
        input_schema_hash=HASH_B,
        output_schema_hash=HASH_C,
        max_calls=1,
        max_response_bytes=4096,
        replay_class=replay_class,
    )


class ProgrammaticContextReplayTests(unittest.TestCase):
    def _setup_execution(self, replay_class: ContextReplayClass, value: str):
        descriptor = _descriptor(replay_class)
        catalog = ContextOperationCatalog.create((descriptor,))
        request = ContextRequest.create(
            project_id=new_id(IdKind.PROJECT),
            objective="Verify exact deterministic programmatic-context replay evidence.",
        )
        program = ContextProgram.create(
            request=request,
            catalog=catalog,
            budget=ContextProgramBudget(),
            instructions=(ContextInstruction(0, "result", "context.replay", "1", ()),),
            output_bindings=("result",),
        )
        registry = ContextAdapterRegistry()
        registry.register(
            descriptor,
            lambda _args: {"value": value},
            validate_input=lambda _args: None,
            validate_output=lambda _value: None,
        )
        result = ContextProgramInterpreter(registry).execute(
            request=request,
            catalog=catalog,
            program=program,
        )
        return descriptor, catalog, request, program, result

    @staticmethod
    def _reexecute(descriptor, catalog, request, program, value: str):
        registry = ContextAdapterRegistry()
        registry.register(
            descriptor,
            lambda _args: {"value": value},
            validate_input=lambda _args: None,
            validate_output=lambda _value: None,
        )
        return ContextProgramInterpreter(registry).execute(
            request=request,
            catalog=catalog,
            program=program,
        )

    def test_deterministic_exact_replay_passes(self) -> None:
        descriptor, catalog, request, program, original = self._setup_execution(
            ContextReplayClass.DETERMINISTIC,
            "stable",
        )
        replay = self._reexecute(descriptor, catalog, request, program, "stable")
        verify_deterministic_replay(
            catalog=catalog,
            original_trace=original.trace,
            original_package=original.package,
            replay=replay,
        )
        self.assertNotEqual(original.trace.execution_id, replay.trace.execution_id)
        self.assertNotEqual(original.package.package_id, replay.package.package_id)

    def test_deterministic_output_drift_fails(self) -> None:
        descriptor, catalog, request, program, original = self._setup_execution(
            ContextReplayClass.DETERMINISTIC,
            "stable",
        )
        replay = self._reexecute(descriptor, catalog, request, program, "changed")
        with self.assertRaisesRegex(ContextReplayVerificationError, "drifted at step"):
            verify_deterministic_replay(
                catalog=catalog,
                original_trace=original.trace,
                original_package=original.package,
                replay=replay,
            )

    def test_revision_bound_adapter_refuses_exact_replay_claim(self) -> None:
        descriptor, catalog, request, program, original = self._setup_execution(
            ContextReplayClass.REVISION_BOUND,
            "same-visible-value",
        )
        replay = self._reexecute(
            descriptor,
            catalog,
            request,
            program,
            "same-visible-value",
        )
        with self.assertRaisesRegex(ContextReplayVerificationError, "not authorized"):
            verify_deterministic_replay(
                catalog=catalog,
                original_trace=original.trace,
                original_package=original.package,
                replay=replay,
            )

    def test_catalog_drift_is_rejected_before_step_comparison(self) -> None:
        descriptor, catalog, request, program, original = self._setup_execution(
            ContextReplayClass.DETERMINISTIC,
            "stable",
        )
        replay = self._reexecute(descriptor, catalog, request, program, "stable")
        changed_descriptor = ContextOperationDescriptor(
            operation_id=descriptor.operation_id,
            version=descriptor.version,
            adapter_fingerprint="sha256:" + "d" * 64,
            input_schema_hash=descriptor.input_schema_hash,
            output_schema_hash=descriptor.output_schema_hash,
            max_calls=descriptor.max_calls,
            max_response_bytes=descriptor.max_response_bytes,
            replay_class=descriptor.replay_class,
        )
        changed_catalog = ContextOperationCatalog.create((changed_descriptor,))
        with self.assertRaisesRegex(ContextReplayVerificationError, "exact operation catalog"):
            verify_deterministic_replay(
                catalog=changed_catalog,
                original_trace=original.trace,
                original_package=original.package,
                replay=replay,
            )


if __name__ == "__main__":
    unittest.main()
