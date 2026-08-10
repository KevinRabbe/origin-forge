from __future__ import annotations

import json
from typing import Any

from .programmatic_context_models import (
    ContextArgument,
    ContextArgumentKind,
    ContextInstruction,
    ContextOperationCatalog,
    ContextProgram,
    ContextProgramBudget,
    ContextRequest,
    ProgrammaticContextModelError,
)


_MAX_PROPOSAL_BYTES = 256 * 1024


class ContextProgramProposalError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextProgramProposalError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded_raw_json(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        if len(raw) > _MAX_PROPOSAL_BYTES:
            raise ContextProgramProposalError("program proposal exceeds byte limit")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContextProgramProposalError("program proposal must be UTF-8 JSON") from exc
    if not isinstance(raw, str):
        raise TypeError("program proposal must be str or bytes")
    if len(raw.encode("utf-8")) > _MAX_PROPOSAL_BYTES:
        raise ContextProgramProposalError("program proposal exceeds byte limit")
    return raw


def parse_context_program_proposal(
    raw: str | bytes,
    *,
    request: ContextRequest,
    catalog: ContextOperationCatalog,
    budget: ContextProgramBudget,
) -> ContextProgram:
    """Parse model-proposed inert program data under infrastructure-owned bindings."""

    if not isinstance(request, ContextRequest):
        raise TypeError("request must be a ContextRequest")
    if not isinstance(catalog, ContextOperationCatalog):
        raise TypeError("catalog must be a ContextOperationCatalog")
    if not isinstance(budget, ContextProgramBudget):
        raise TypeError("budget must be a ContextProgramBudget")

    text = _bounded_raw_json(raw)
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except ContextProgramProposalError:
        raise
    except json.JSONDecodeError as exc:
        raise ContextProgramProposalError("program proposal is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"instructions", "output_bindings"}:
        raise ContextProgramProposalError(
            "program proposal must contain exactly instructions and output_bindings"
        )
    instructions_raw = value["instructions"]
    outputs_raw = value["output_bindings"]
    if not isinstance(instructions_raw, list) or not isinstance(outputs_raw, list):
        raise ContextProgramProposalError("program proposal arrays are invalid")
    if not instructions_raw or len(instructions_raw) > budget.max_instructions:
        raise ContextProgramProposalError("program proposal instruction count is outside budget")
    if len(instructions_raw) > budget.max_invocations:
        raise ContextProgramProposalError("program proposal invocation count is outside budget")
    if not outputs_raw or any(not isinstance(v, str) for v in outputs_raw):
        raise ContextProgramProposalError("program proposal output_bindings are invalid")

    instructions: list[ContextInstruction] = []
    try:
        for index, item in enumerate(instructions_raw):
            if not isinstance(item, dict) or set(item) != {
                "binding",
                "operation_id",
                "operation_version",
                "arguments",
            }:
                raise ContextProgramProposalError(
                    f"instruction {index} has unsupported fields"
                )
            if not all(
                isinstance(item[field], str)
                for field in ("binding", "operation_id", "operation_version")
            ):
                raise ContextProgramProposalError(
                    f"instruction {index} identity fields are invalid"
                )
            arguments_raw = item["arguments"]
            if not isinstance(arguments_raw, list) or len(arguments_raw) > 64:
                raise ContextProgramProposalError(
                    f"instruction {index} arguments are outside bounds"
                )
            arguments: list[ContextArgument] = []
            for argument_index, argument in enumerate(arguments_raw):
                if not isinstance(argument, dict) or "kind" not in argument or "name" not in argument:
                    raise ContextProgramProposalError(
                        f"instruction {index} argument {argument_index} is invalid"
                    )
                kind_raw = argument["kind"]
                name = argument["name"]
                if not isinstance(kind_raw, str) or not isinstance(name, str):
                    raise ContextProgramProposalError(
                        f"instruction {index} argument {argument_index} identity is invalid"
                    )
                try:
                    kind = ContextArgumentKind(kind_raw)
                except ValueError as exc:
                    raise ContextProgramProposalError(
                        f"instruction {index} argument {argument_index} kind is invalid"
                    ) from exc
                if kind is ContextArgumentKind.LITERAL:
                    if set(argument) != {"kind", "name", "literal"}:
                        raise ContextProgramProposalError(
                            f"instruction {index} literal argument fields are invalid"
                        )
                    arguments.append(ContextArgument.literal(name, argument["literal"]))
                else:
                    if set(argument) != {"kind", "name", "reference"} or not isinstance(
                        argument["reference"], str
                    ):
                        raise ContextProgramProposalError(
                            f"instruction {index} reference argument fields are invalid"
                        )
                    arguments.append(ContextArgument.ref(name, argument["reference"]))
            instructions.append(
                ContextInstruction(
                    index=index,
                    binding=item["binding"],
                    operation_id=item["operation_id"],
                    operation_version=item["operation_version"],
                    arguments=tuple(arguments),
                )
            )
        program = ContextProgram.create(
            request=request,
            catalog=catalog,
            budget=budget,
            instructions=tuple(instructions),
            output_bindings=tuple(outputs_raw),
        )
        program.bind(request, catalog)
        return program
    except ContextProgramProposalError:
        raise
    except (ProgrammaticContextModelError, TypeError, ValueError) as exc:
        raise ContextProgramProposalError("program proposal failed governed validation") from exc
