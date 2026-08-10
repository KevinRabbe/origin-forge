from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import canonical_bytes, content_hash, validate_sha256


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_BINDING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MAX_OBJECT_NODES = 4096
_MAX_OBJECT_DEPTH = 12
_MAX_LITERAL_BYTES = 64 * 1024
_MAX_OBJECTIVE_CHARS = 4096
_MAX_SOURCE_REFS = 128
_MAX_OPERATIONS = 128
_MAX_INSTRUCTIONS_HARD = 256
_MAX_INVOCATIONS_HARD = 256
_MAX_RESULT_BYTES_HARD = 16 * 1024 * 1024
_MAX_CONTEXT_BYTES_HARD = 16 * 1024 * 1024


class ProgrammaticContextModelError(ValueError):
    pass


class ContextOperationEffect(StrEnum):
    READ_ONLY = "READ_ONLY"


class ContextReplayClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    REVISION_BOUND = "REVISION_BOUND"


class ContextArgumentKind(StrEnum):
    LITERAL = "LITERAL"
    REFERENCE = "REFERENCE"


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ProgrammaticContextModelError(f"{label} must be a bounded identity token")
    return value


def _binding(value: str, label: str = "binding") -> str:
    if not isinstance(value, str) or not _BINDING_RE.fullmatch(value):
        raise ProgrammaticContextModelError(f"{label} must be a bounded binding name")
    return value


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProgrammaticContextModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _validate_json(value: object, *, depth: int = 0, nodes: list[int]) -> None:
    nodes[0] += 1
    if nodes[0] > _MAX_OBJECT_NODES:
        raise ProgrammaticContextModelError("JSON value exceeds node limit")
    if depth > _MAX_OBJECT_DEPTH:
        raise ProgrammaticContextModelError("JSON value exceeds depth limit")
    if value is None or type(value) in (bool, int, str):
        return
    if isinstance(value, float):
        raise ProgrammaticContextModelError("floating-point program data is forbidden in v1")
    if isinstance(value, list):
        if len(value) > 512:
            raise ProgrammaticContextModelError("JSON list exceeds item limit")
        for item in value:
            _validate_json(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict):
        if len(value) > 512:
            raise ProgrammaticContextModelError("JSON object exceeds key limit")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise ProgrammaticContextModelError("JSON object keys must be bounded text")
            _validate_json(item, depth=depth + 1, nodes=nodes)
        return
    raise ProgrammaticContextModelError("program data must contain only exact JSON types")


def canonical_json(value: object, *, byte_limit: int = _MAX_LITERAL_BYTES) -> str:
    _validate_json(value, nodes=[0])
    try:
        data = canonical_bytes(value)
    except ValueError as exc:
        raise ProgrammaticContextModelError("program data is not canonical JSON") from exc
    if len(data) > byte_limit:
        raise ProgrammaticContextModelError(
            f"program data exceeds byte limit ({len(data)} > {byte_limit})"
        )
    return data.decode("utf-8")


@dataclass(frozen=True)
class ContextEvidenceRef:
    ref_id: str
    content_hash: str
    revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _token(self.ref_id, "evidence ref_id"))
        validate_sha256(self.content_hash, "evidence content_hash")
        if self.revision is not None:
            _exact_int(self.revision, "evidence revision", 0, 2_147_483_647)

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.ref_id, self.content_hash, -1 if self.revision is None else self.revision)

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ContextRequest:
    request_id: str
    project_id: str
    objective: str
    source_refs: tuple[ContextEvidenceRef, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.request_id, IdKind.CONTEXT_REQUEST):
            raise ProgrammaticContextModelError("request_id must be a CTXREQ ID")
        if not validate_id(self.project_id, IdKind.PROJECT):
            raise ProgrammaticContextModelError("project_id must be a PROJECT ID")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ProgrammaticContextModelError("objective must be non-empty text")
        objective = self.objective.strip()
        if len(objective) > _MAX_OBJECTIVE_CHARS:
            raise ProgrammaticContextModelError("objective exceeds character limit")
        object.__setattr__(self, "objective", objective)
        refs = tuple(self.source_refs)
        if len(refs) > _MAX_SOURCE_REFS or not all(isinstance(v, ContextEvidenceRef) for v in refs):
            raise ProgrammaticContextModelError("source_refs are outside bounds")
        keys = [v.key for v in refs]
        if len(keys) != len(set(keys)):
            raise ProgrammaticContextModelError("source_refs contain duplicates")
        object.__setattr__(self, "source_refs", tuple(sorted(refs, key=lambda v: v.key)))

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        objective: str,
        source_refs: Iterable[ContextEvidenceRef] = (),
    ) -> "ContextRequest":
        return cls(new_id(IdKind.CONTEXT_REQUEST), project_id, objective, tuple(source_refs))

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "project_id": self.project_id,
            "objective": self.objective,
            "source_refs": [v.to_dict() for v in self.source_refs],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ContextOperationDescriptor:
    operation_id: str
    version: str
    adapter_fingerprint: str
    input_schema_hash: str
    output_schema_hash: str
    max_calls: int
    max_response_bytes: int
    replay_class: ContextReplayClass
    effect: ContextOperationEffect = ContextOperationEffect.READ_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _token(self.operation_id, "operation_id"))
        object.__setattr__(self, "version", _token(self.version, "operation version"))
        for field in ("adapter_fingerprint", "input_schema_hash", "output_schema_hash"):
            validate_sha256(getattr(self, field), field)
        _exact_int(self.max_calls, "max_calls", 1, _MAX_INVOCATIONS_HARD)
        _exact_int(self.max_response_bytes, "max_response_bytes", 1, _MAX_RESULT_BYTES_HARD)
        if not isinstance(self.replay_class, ContextReplayClass):
            raise ProgrammaticContextModelError("replay_class is invalid")
        if self.effect is not ContextOperationEffect.READ_ONLY:
            raise ProgrammaticContextModelError("v1 context operations must be READ_ONLY")

    @property
    def key(self) -> tuple[str, str]:
        return (self.operation_id, self.version)

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "version": self.version,
            "adapter_fingerprint": self.adapter_fingerprint,
            "input_schema_hash": self.input_schema_hash,
            "output_schema_hash": self.output_schema_hash,
            "max_calls": self.max_calls,
            "max_response_bytes": self.max_response_bytes,
            "replay_class": self.replay_class.value,
            "effect": self.effect.value,
        }


@dataclass(frozen=True)
class ContextOperationCatalog:
    catalog_id: str
    operations: tuple[ContextOperationDescriptor, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.catalog_id, IdKind.CONTEXT_OPERATION_CATALOG):
            raise ProgrammaticContextModelError("catalog_id must be a CTXCAT ID")
        operations = tuple(self.operations)
        if not operations or len(operations) > _MAX_OPERATIONS:
            raise ProgrammaticContextModelError("catalog must contain bounded operations")
        if not all(isinstance(v, ContextOperationDescriptor) for v in operations):
            raise ProgrammaticContextModelError("catalog operations are invalid")
        keys = [v.key for v in operations]
        if len(keys) != len(set(keys)):
            raise ProgrammaticContextModelError("catalog contains duplicate operation versions")
        object.__setattr__(self, "operations", tuple(sorted(operations, key=lambda v: v.key)))

    @classmethod
    def create(cls, operations: Iterable[ContextOperationDescriptor]) -> "ContextOperationCatalog":
        return cls(new_id(IdKind.CONTEXT_OPERATION_CATALOG), tuple(operations))

    def descriptor(self, operation_id: str, version: str) -> ContextOperationDescriptor:
        key = (operation_id, version)
        for value in self.operations:
            if value.key == key:
                return value
        raise ProgrammaticContextModelError(f"operation is not in frozen catalog: {operation_id}@{version}")

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_id": self.catalog_id,
            "operations": [v.to_dict() for v in self.operations],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ContextProgramBudget:
    max_instructions: int = 32
    max_invocations: int = 32
    max_result_bytes: int = 2 * 1024 * 1024
    max_context_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        _exact_int(self.max_instructions, "max_instructions", 1, _MAX_INSTRUCTIONS_HARD)
        _exact_int(self.max_invocations, "max_invocations", 1, _MAX_INVOCATIONS_HARD)
        _exact_int(self.max_result_bytes, "max_result_bytes", 1, _MAX_RESULT_BYTES_HARD)
        _exact_int(self.max_context_bytes, "max_context_bytes", 1, _MAX_CONTEXT_BYTES_HARD)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_instructions": self.max_instructions,
            "max_invocations": self.max_invocations,
            "max_result_bytes": self.max_result_bytes,
            "max_context_bytes": self.max_context_bytes,
        }


@dataclass(frozen=True)
class ContextArgument:
    name: str
    kind: ContextArgumentKind
    literal_json: str | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _token(self.name, "argument name"))
        if not isinstance(self.kind, ContextArgumentKind):
            raise ProgrammaticContextModelError("argument kind is invalid")
        if self.kind is ContextArgumentKind.LITERAL:
            if self.reference is not None or not isinstance(self.literal_json, str):
                raise ProgrammaticContextModelError("literal argument must contain only literal_json")
            try:
                value = json.loads(self.literal_json)
            except json.JSONDecodeError as exc:
                raise ProgrammaticContextModelError("literal_json is invalid") from exc
            if canonical_json(value) != self.literal_json:
                raise ProgrammaticContextModelError("literal_json must be canonical")
        else:
            if self.literal_json is not None or self.reference is None:
                raise ProgrammaticContextModelError("reference argument must contain only reference")
            object.__setattr__(self, "reference", _binding(self.reference, "argument reference"))

    @classmethod
    def literal(cls, name: str, value: object) -> "ContextArgument":
        return cls(name, ContextArgumentKind.LITERAL, literal_json=canonical_json(value))

    @classmethod
    def ref(cls, name: str, binding: str) -> "ContextArgument":
        return cls(name, ContextArgumentKind.REFERENCE, reference=binding)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "literal": json.loads(self.literal_json) if self.literal_json is not None else None,
            "reference": self.reference,
        }


@dataclass(frozen=True)
class ContextInstruction:
    index: int
    binding: str
    operation_id: str
    operation_version: str
    arguments: tuple[ContextArgument, ...]

    def __post_init__(self) -> None:
        _exact_int(self.index, "instruction index", 0, _MAX_INSTRUCTIONS_HARD - 1)
        object.__setattr__(self, "binding", _binding(self.binding))
        object.__setattr__(self, "operation_id", _token(self.operation_id, "operation_id"))
        object.__setattr__(self, "operation_version", _token(self.operation_version, "operation_version"))
        args = tuple(self.arguments)
        if len(args) > 64 or not all(isinstance(v, ContextArgument) for v in args):
            raise ProgrammaticContextModelError("instruction arguments are outside bounds")
        names = [v.name for v in args]
        if len(names) != len(set(names)):
            raise ProgrammaticContextModelError("instruction contains duplicate argument names")
        object.__setattr__(self, "arguments", tuple(sorted(args, key=lambda v: v.name)))

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "binding": self.binding,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "arguments": [v.to_dict() for v in self.arguments],
        }


@dataclass(frozen=True)
class ContextProgram:
    program_id: str
    request_id: str
    request_hash: str
    catalog_id: str
    catalog_hash: str
    budget: ContextProgramBudget
    instructions: tuple[ContextInstruction, ...]
    output_bindings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.program_id, IdKind.CONTEXT_PROGRAM):
            raise ProgrammaticContextModelError("program_id must be a CTXPROG ID")
        if not validate_id(self.request_id, IdKind.CONTEXT_REQUEST):
            raise ProgrammaticContextModelError("request_id must be a CTXREQ ID")
        if not validate_id(self.catalog_id, IdKind.CONTEXT_OPERATION_CATALOG):
            raise ProgrammaticContextModelError("catalog_id must be a CTXCAT ID")
        validate_sha256(self.request_hash, "request_hash")
        validate_sha256(self.catalog_hash, "catalog_hash")
        if not isinstance(self.budget, ContextProgramBudget):
            raise ProgrammaticContextModelError("budget is invalid")
        instructions = tuple(self.instructions)
        if not instructions or len(instructions) > self.budget.max_instructions:
            raise ProgrammaticContextModelError("program instruction count is outside budget")
        if len(instructions) > self.budget.max_invocations:
            raise ProgrammaticContextModelError("program invocation count is outside budget")
        if not all(isinstance(v, ContextInstruction) for v in instructions):
            raise ProgrammaticContextModelError("program instructions are invalid")
        if tuple(v.index for v in instructions) != tuple(range(len(instructions))):
            raise ProgrammaticContextModelError("instruction indexes must be contiguous from zero")
        seen: set[str] = set()
        for instruction in instructions:
            if instruction.binding in seen:
                raise ProgrammaticContextModelError("program may not rebind a binding name")
            for argument in instruction.arguments:
                if argument.kind is ContextArgumentKind.REFERENCE and argument.reference not in seen:
                    raise ProgrammaticContextModelError(
                        "program references must target an earlier binding"
                    )
            seen.add(instruction.binding)
        outputs = tuple(_binding(v, "output binding") for v in self.output_bindings)
        if not outputs or len(outputs) != len(set(outputs)):
            raise ProgrammaticContextModelError("output_bindings must be unique and non-empty")
        if any(v not in seen for v in outputs):
            raise ProgrammaticContextModelError("output binding does not exist")
        object.__setattr__(self, "instructions", instructions)
        object.__setattr__(self, "output_bindings", outputs)

    @classmethod
    def create(
        cls,
        *,
        request: ContextRequest,
        catalog: ContextOperationCatalog,
        budget: ContextProgramBudget,
        instructions: Iterable[ContextInstruction],
        output_bindings: Iterable[str],
    ) -> "ContextProgram":
        if not isinstance(request, ContextRequest) or not isinstance(catalog, ContextOperationCatalog):
            raise TypeError("request and catalog must use Phase-27 model types")
        return cls(
            new_id(IdKind.CONTEXT_PROGRAM),
            request.request_id,
            request.content_hash,
            catalog.catalog_id,
            catalog.content_hash,
            budget,
            tuple(instructions),
            tuple(output_bindings),
        )

    def bind(self, request: ContextRequest, catalog: ContextOperationCatalog) -> None:
        if (
            self.request_id != request.request_id
            or self.request_hash != request.content_hash
            or self.catalog_id != catalog.catalog_id
            or self.catalog_hash != catalog.content_hash
        ):
            raise ProgrammaticContextModelError("program does not bind exact request and catalog")
        counts: dict[tuple[str, str], int] = {}
        for instruction in self.instructions:
            descriptor = catalog.descriptor(instruction.operation_id, instruction.operation_version)
            counts[descriptor.key] = counts.get(descriptor.key, 0) + 1
            if counts[descriptor.key] > descriptor.max_calls:
                raise ProgrammaticContextModelError(
                    f"program exceeds operation call limit for {descriptor.operation_id}@{descriptor.version}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "budget": self.budget.to_dict(),
            "instructions": [v.to_dict() for v in self.instructions],
            "output_bindings": list(self.output_bindings),
            "arbitrary_code_authorized": False,
            "production_mutation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ContextStepTrace:
    index: int
    binding: str
    operation_id: str
    operation_version: str
    adapter_fingerprint: str
    input_hash: str
    output_hash: str
    output_bytes: int

    def __post_init__(self) -> None:
        _exact_int(self.index, "trace index", 0, _MAX_INSTRUCTIONS_HARD - 1)
        object.__setattr__(self, "binding", _binding(self.binding))
        object.__setattr__(self, "operation_id", _token(self.operation_id, "operation_id"))
        object.__setattr__(self, "operation_version", _token(self.operation_version, "operation_version"))
        validate_sha256(self.adapter_fingerprint, "adapter_fingerprint")
        validate_sha256(self.input_hash, "input_hash")
        validate_sha256(self.output_hash, "output_hash")
        _exact_int(self.output_bytes, "output_bytes", 0, _MAX_RESULT_BYTES_HARD)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "binding": self.binding,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "adapter_fingerprint": self.adapter_fingerprint,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "output_bytes": self.output_bytes,
        }


@dataclass(frozen=True)
class ContextPackage:
    package_id: str
    request_id: str
    request_hash: str
    program_id: str
    program_hash: str
    catalog_id: str
    catalog_hash: str
    values_json: str

    def __post_init__(self) -> None:
        if not validate_id(self.package_id, IdKind.CONTEXT_PACKAGE):
            raise ProgrammaticContextModelError("package_id must be a CTXPKG ID")
        if not validate_id(self.request_id, IdKind.CONTEXT_REQUEST):
            raise ProgrammaticContextModelError("package request_id is invalid")
        if not validate_id(self.program_id, IdKind.CONTEXT_PROGRAM):
            raise ProgrammaticContextModelError("package program_id is invalid")
        if not validate_id(self.catalog_id, IdKind.CONTEXT_OPERATION_CATALOG):
            raise ProgrammaticContextModelError("package catalog_id is invalid")
        for field in ("request_hash", "program_hash", "catalog_hash"):
            validate_sha256(getattr(self, field), field)
        try:
            values = json.loads(self.values_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProgrammaticContextModelError("package values_json is invalid") from exc
        if not isinstance(values, dict) or canonical_json(values, byte_limit=_MAX_CONTEXT_BYTES_HARD) != self.values_json:
            raise ProgrammaticContextModelError("package values_json must be a canonical JSON object")

    @property
    def values(self) -> dict[str, object]:
        return json.loads(self.values_json)

    @property
    def byte_size(self) -> int:
        return len(self.values_json.encode("utf-8"))

    def to_dict(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "program_id": self.program_id,
            "program_hash": self.program_hash,
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "values": self.values,
            "production_task_verified": False,
            "production_mutation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ContextExecutionTrace:
    execution_id: str
    request_id: str
    request_hash: str
    program_id: str
    program_hash: str
    catalog_id: str
    catalog_hash: str
    steps: tuple[ContextStepTrace, ...]
    total_result_bytes: int
    package_id: str
    package_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.execution_id, IdKind.CONTEXT_EXECUTION):
            raise ProgrammaticContextModelError("execution_id must be a CTXEXEC ID")
        if not validate_id(self.request_id, IdKind.CONTEXT_REQUEST):
            raise ProgrammaticContextModelError("trace request_id is invalid")
        if not validate_id(self.program_id, IdKind.CONTEXT_PROGRAM):
            raise ProgrammaticContextModelError("trace program_id is invalid")
        if not validate_id(self.catalog_id, IdKind.CONTEXT_OPERATION_CATALOG):
            raise ProgrammaticContextModelError("trace catalog_id is invalid")
        if not validate_id(self.package_id, IdKind.CONTEXT_PACKAGE):
            raise ProgrammaticContextModelError("trace package_id is invalid")
        for field in ("request_hash", "program_hash", "catalog_hash", "package_hash"):
            validate_sha256(getattr(self, field), field)
        steps = tuple(self.steps)
        if tuple(v.index for v in steps) != tuple(range(len(steps))):
            raise ProgrammaticContextModelError("trace step indexes must be contiguous")
        _exact_int(self.total_result_bytes, "total_result_bytes", 0, _MAX_RESULT_BYTES_HARD)
        if sum(v.output_bytes for v in steps) != self.total_result_bytes:
            raise ProgrammaticContextModelError("trace total_result_bytes is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "program_id": self.program_id,
            "program_hash": self.program_hash,
            "catalog_id": self.catalog_id,
            "catalog_hash": self.catalog_hash,
            "steps": [v.to_dict() for v in self.steps],
            "total_result_bytes": self.total_result_bytes,
            "package_id": self.package_id,
            "package_hash": self.package_hash,
            "production_task_verified": False,
            "production_mutation_authorized": False,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
