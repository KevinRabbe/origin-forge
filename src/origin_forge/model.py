from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelRequest:
    run_id: str
    task_id: str | None
    instructions: str
    context: dict[str, Any]
    response_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model_id: str
    model_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    @property
    def model_id(self) -> str: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...
