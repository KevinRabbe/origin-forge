from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .repository import RepositoryReader, SourceFile
from .runtime import OriginForgeRuntime


@dataclass(frozen=True)
class ContextFile:
    path: str
    content_hash: str
    content: str
    byte_count: int

    @classmethod
    def from_source(cls, source: SourceFile) -> "ContextFile":
        return cls(source.path, source.content_hash, source.content, source.byte_count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "content": self.content,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True)
class ContextPackage:
    task_id: str
    task_revision: int
    objective: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    files: tuple[ContextFile, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": {
                "id": self.task_id,
                "revision": self.task_revision,
                "objective": self.objective,
                "acceptance_criteria": list(self.acceptance_criteria),
                "constraints": list(self.constraints),
                "required_capabilities": list(self.required_capabilities),
            },
            "files": [file.to_dict() for file in self.files],
        }


class ContextBuilder:
    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader | None = None,
        *,
        max_total_bytes: int = 1024 * 1024,
    ):
        self.runtime = runtime
        self.repository = repository or RepositoryReader(runtime.project_root)
        self.max_total_bytes = max_total_bytes

    @staticmethod
    def _json_list(raw: str) -> tuple[str, ...]:
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("durable task JSON field is not an array of strings")
        return tuple(value)

    def build(self, task_id: str, selected_paths: Iterable[str]) -> ContextPackage:
        task = self.runtime.get_task(task_id)
        sources = self.repository.snapshot(
            selected_paths, max_total_bytes=self.max_total_bytes
        )
        return ContextPackage(
            task_id=task_id,
            task_revision=int(task["revision"]),
            objective=task["objective"],
            acceptance_criteria=self._json_list(task["acceptance_criteria_json"]),
            constraints=self._json_list(task["constraints_json"]),
            required_capabilities=self._json_list(task["required_capabilities_json"]),
            files=tuple(ContextFile.from_source(source) for source in sources),
        )
