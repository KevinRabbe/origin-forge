from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Mapping

from .ids import IdKind, new_id
from .programmatic_context_models import (
    ContextArgumentKind,
    ContextExecutionTrace,
    ContextOperationCatalog,
    ContextOperationDescriptor,
    ContextPackage,
    ContextProgram,
    ContextRequest,
    ContextStepTrace,
    ProgrammaticContextModelError,
    canonical_json,
)
from .runtime_observation_models import canonical_bytes, content_hash


class ContextProgramExecutionError(RuntimeError):
    pass


ContextAdapter = Callable[[Mapping[str, object]], object]
ContextValidator = Callable[[Mapping[str, object]], None]
ContextOutputValidator = Callable[[object], None]


@dataclass(frozen=True)
class RegisteredContextAdapter:
    descriptor: ContextOperationDescriptor
    invoke: ContextAdapter
    validate_input: ContextValidator
    validate_output: ContextOutputValidator


class ContextAdapterRegistry:
    """Infrastructure-owned registry for exact read-only program adapters."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], RegisteredContextAdapter] = {}

    def register(
        self,
        descriptor: ContextOperationDescriptor,
        invoke: ContextAdapter,
        *,
        validate_input: ContextValidator,
        validate_output: ContextOutputValidator,
    ) -> None:
        if not isinstance(descriptor, ContextOperationDescriptor):
            raise TypeError("descriptor must be a ContextOperationDescriptor")
        if not callable(invoke) or not callable(validate_input) or not callable(validate_output):
            raise TypeError("context adapter and validators must be callable")
        if descriptor.key in self._adapters:
            raise ContextProgramExecutionError(
                f"context adapter already registered: {descriptor.operation_id}@{descriptor.version}"
            )
        self._adapters[descriptor.key] = RegisteredContextAdapter(
            descriptor,
            invoke,
            validate_input,
            validate_output,
        )

    def resolve(self, descriptor: ContextOperationDescriptor) -> RegisteredContextAdapter:
        try:
            registered = self._adapters[descriptor.key]
        except KeyError as exc:
            raise ContextProgramExecutionError(
                f"no registered context adapter: {descriptor.operation_id}@{descriptor.version}"
            ) from exc
        if registered.descriptor != descriptor:
            raise ContextProgramExecutionError(
                f"registered adapter descriptor drifted for {descriptor.operation_id}@{descriptor.version}"
            )
        return registered

    def snapshot(self) -> tuple[ContextOperationDescriptor, ...]:
        return tuple(
            self._adapters[key].descriptor
            for key in sorted(self._adapters)
        )


@dataclass(frozen=True)
class ContextExecutionResult:
    package: ContextPackage
    trace: ContextExecutionTrace

    @property
    def production_task_verified(self) -> bool:
        return False

    @property
    def production_mutation_authorized(self) -> bool:
        return False


class ContextProgramInterpreter:
    """Execute finite straight-line programs over exact read-only adapters only."""

    def __init__(self, registry: ContextAdapterRegistry):
        if not isinstance(registry, ContextAdapterRegistry):
            raise TypeError("registry must be a ContextAdapterRegistry")
        self.registry = registry

    @staticmethod
    def _canonical_value(value: object, *, byte_limit: int) -> tuple[object, bytes]:
        text = canonical_json(value, byte_limit=byte_limit)
        data = text.encode("utf-8")
        return json.loads(text), data

    def execute(
        self,
        *,
        request: ContextRequest,
        catalog: ContextOperationCatalog,
        program: ContextProgram,
    ) -> ContextExecutionResult:
        if not isinstance(request, ContextRequest):
            raise TypeError("request must be a ContextRequest")
        if not isinstance(catalog, ContextOperationCatalog):
            raise TypeError("catalog must be a ContextOperationCatalog")
        if not isinstance(program, ContextProgram):
            raise TypeError("program must be a ContextProgram")

        try:
            program.bind(request, catalog)
        except ProgrammaticContextModelError as exc:
            raise ContextProgramExecutionError("program binding failed") from exc

        bindings: dict[str, object] = {}
        traces: list[ContextStepTrace] = []
        total_result_bytes = 0

        for instruction in program.instructions:
            descriptor = catalog.descriptor(
                instruction.operation_id,
                instruction.operation_version,
            )
            registered = self.registry.resolve(descriptor)

            arguments: dict[str, object] = {}
            for argument in instruction.arguments:
                if argument.kind is ContextArgumentKind.LITERAL:
                    assert argument.literal_json is not None
                    arguments[argument.name] = json.loads(argument.literal_json)
                else:
                    assert argument.reference is not None
                    try:
                        referenced = bindings[argument.reference]
                    except KeyError as exc:
                        raise ContextProgramExecutionError(
                            "program referenced an unavailable binding"
                        ) from exc
                    # Copy through canonical JSON so adapters never receive a mutable alias
                    # to interpreter-owned evidence from an earlier step.
                    arguments[argument.name] = json.loads(canonical_bytes(referenced))

            input_bytes = canonical_bytes(arguments)
            try:
                registered.validate_input(arguments)
            except Exception as exc:
                raise ContextProgramExecutionError(
                    f"context adapter input validation failed at step {instruction.index}"
                ) from exc

            try:
                raw_output = registered.invoke(arguments)
            except Exception as exc:
                raise ContextProgramExecutionError(
                    f"context adapter failed at step {instruction.index}"
                ) from exc

            try:
                registered.validate_output(raw_output)
            except Exception as exc:
                raise ContextProgramExecutionError(
                    f"context adapter output validation failed at step {instruction.index}"
                ) from exc

            try:
                output, output_bytes = self._canonical_value(
                    raw_output,
                    byte_limit=descriptor.max_response_bytes,
                )
            except ProgrammaticContextModelError as exc:
                raise ContextProgramExecutionError(
                    f"context adapter returned invalid bounded JSON at step {instruction.index}"
                ) from exc

            total_result_bytes += len(output_bytes)
            if total_result_bytes > program.budget.max_result_bytes:
                raise ContextProgramExecutionError(
                    "program exceeded aggregate result-byte budget"
                )

            bindings[instruction.binding] = output
            traces.append(
                ContextStepTrace(
                    index=instruction.index,
                    binding=instruction.binding,
                    operation_id=descriptor.operation_id,
                    operation_version=descriptor.version,
                    adapter_fingerprint=descriptor.adapter_fingerprint,
                    input_hash=content_hash(arguments),
                    output_hash=content_hash(output),
                    output_bytes=len(output_bytes),
                )
            )

        final_values = {
            binding: bindings[binding]
            for binding in program.output_bindings
        }
        values_json = canonical_json(
            final_values,
            byte_limit=program.budget.max_context_bytes,
        )
        package = ContextPackage(
            package_id=new_id(IdKind.CONTEXT_PACKAGE),
            request_id=request.request_id,
            request_hash=request.content_hash,
            program_id=program.program_id,
            program_hash=program.content_hash,
            catalog_id=catalog.catalog_id,
            catalog_hash=catalog.content_hash,
            values_json=values_json,
        )
        trace = ContextExecutionTrace(
            execution_id=new_id(IdKind.CONTEXT_EXECUTION),
            request_id=request.request_id,
            request_hash=request.content_hash,
            program_id=program.program_id,
            program_hash=program.content_hash,
            catalog_id=catalog.catalog_id,
            catalog_hash=catalog.content_hash,
            steps=tuple(traces),
            total_result_bytes=total_result_bytes,
            package_id=package.package_id,
            package_hash=package.content_hash,
        )
        return ContextExecutionResult(package, trace)
