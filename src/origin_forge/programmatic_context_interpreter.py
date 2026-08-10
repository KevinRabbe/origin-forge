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


_MAX_ADAPTER_INPUT_BYTES = 64 * 1024
_MAX_JSON_INT = 9_223_372_036_854_775_807
_MAX_JSON_NODES = 4096
_MAX_JSON_DEPTH = 12


class ContextProgramExecutionError(RuntimeError):
    pass


ContextAdapter = Callable[[Mapping[str, object]], object]
ContextValidator = Callable[[Mapping[str, object]], None]
ContextOutputValidator = Callable[[object], None]


def _preflight_json(
    value: object,
    *,
    byte_limit: int,
    depth: int = 0,
    nodes: list[int] | None = None,
    text_bytes: list[int] | None = None,
) -> None:
    """Reject pathological JSON scalars before json.dumps can amplify work."""

    if nodes is None:
        nodes = [0]
    if text_bytes is None:
        text_bytes = [0]
    nodes[0] += 1
    if nodes[0] > _MAX_JSON_NODES:
        raise ContextProgramExecutionError("context JSON exceeds node limit")
    if depth > _MAX_JSON_DEPTH:
        raise ContextProgramExecutionError("context JSON exceeds depth limit")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -_MAX_JSON_INT <= value <= _MAX_JSON_INT:
            raise ContextProgramExecutionError("context JSON integer exceeds signed-64-bit bound")
        return
    if isinstance(value, float):
        raise ContextProgramExecutionError("context JSON may not contain floating-point values")
    if isinstance(value, str):
        text_bytes[0] += len(value.encode("utf-8"))
        if text_bytes[0] > byte_limit:
            raise ContextProgramExecutionError("context JSON text exceeds byte budget")
        return
    if isinstance(value, list):
        for item in value:
            _preflight_json(
                item,
                byte_limit=byte_limit,
                depth=depth + 1,
                nodes=nodes,
                text_bytes=text_bytes,
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContextProgramExecutionError("context JSON keys must be strings")
            text_bytes[0] += len(key.encode("utf-8"))
            if text_bytes[0] > byte_limit:
                raise ContextProgramExecutionError("context JSON text exceeds byte budget")
            _preflight_json(
                item,
                byte_limit=byte_limit,
                depth=depth + 1,
                nodes=nodes,
                text_bytes=text_bytes,
            )
        return
    raise ContextProgramExecutionError("context data must contain only exact JSON types")


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
        _preflight_json(value, byte_limit=byte_limit)
        try:
            text = canonical_json(value, byte_limit=byte_limit)
        except ProgrammaticContextModelError as exc:
            raise ContextProgramExecutionError("context JSON failed bounded canonicalization") from exc
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
        total_input_bytes = 0
        aggregate_input_limit = min(program.budget.max_result_bytes, 2 * 1024 * 1024)

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
                    # Copy through bounded canonical JSON so adapters never receive a
                    # mutable alias or an unbounded amplification of earlier evidence.
                    referenced_copy, _ = self._canonical_value(
                        referenced,
                        byte_limit=min(descriptor.max_response_bytes, _MAX_ADAPTER_INPUT_BYTES),
                    )
                    arguments[argument.name] = referenced_copy

            per_call_input_limit = min(descriptor.max_response_bytes, _MAX_ADAPTER_INPUT_BYTES)
            try:
                _, input_bytes = self._canonical_value(
                    arguments,
                    byte_limit=per_call_input_limit,
                )
            except ContextProgramExecutionError as exc:
                raise ContextProgramExecutionError(
                    f"context adapter input exceeded bounded JSON contract at step {instruction.index}"
                ) from exc
            total_input_bytes += len(input_bytes)
            if total_input_bytes > aggregate_input_limit:
                raise ContextProgramExecutionError(
                    "program exceeded aggregate adapter-input byte budget"
                )

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
                output, output_bytes = self._canonical_value(
                    raw_output,
                    byte_limit=descriptor.max_response_bytes,
                )
            except ContextProgramExecutionError as exc:
                raise ContextProgramExecutionError(
                    f"context adapter returned invalid bounded JSON at step {instruction.index}"
                ) from exc

            try:
                registered.validate_output(output)
            except Exception as exc:
                raise ContextProgramExecutionError(
                    f"context adapter output validation failed at step {instruction.index}"
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
        try:
            final_value, _ = self._canonical_value(
                final_values,
                byte_limit=program.budget.max_context_bytes,
            )
            values_json = canonical_json(
                final_value,
                byte_limit=program.budget.max_context_bytes,
            )
        except ContextProgramExecutionError as exc:
            raise ContextProgramExecutionError("final context package exceeded bounded JSON contract") from exc
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
