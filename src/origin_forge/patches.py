from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .path_policy import portable_path_key, portable_relative_path
from .repository import RepositoryReader


class PatchValidationError(ValueError):
    pass


class FileOperation(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class FileChange:
    operation: FileOperation
    path: str
    expected_hash: str | None
    content: str | None


@dataclass(frozen=True)
class PatchProposal:
    summary: str
    changes: tuple[FileChange, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "changes": [
                {
                    "operation": change.operation.value,
                    "path": change.path,
                    "expected_hash": change.expected_hash,
                    "content": change.content,
                }
                for change in self.changes
            ],
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


PATCH_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "changes"],
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "notes": {"type": "array", "items": {"type": "string"}},
        "changes": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "required": ["operation", "path", "expected_hash", "content"],
                "additionalProperties": False,
                "properties": {
                    "operation": {"enum": ["CREATE", "UPDATE", "DELETE"]},
                    "path": {"type": "string", "minLength": 1},
                    "expected_hash": {"type": ["string", "null"]},
                    "content": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def _validate_path(raw: Any) -> str:
    if not isinstance(raw, str):
        raise PatchValidationError("change path must be a non-empty string")
    try:
        return portable_relative_path(raw).as_posix()
    except ValueError as exc:
        raise PatchValidationError(str(exc)) from exc


def _validate_proposal_path_identity(proposal: PatchProposal) -> None:
    seen: dict[str, str] = {}
    for change in proposal.changes:
        canonical = _validate_path(change.path)
        if canonical != change.path:
            raise PatchValidationError(
                f"patch path is not canonical: {change.path!r} != {canonical!r}"
            )
        key = portable_path_key(canonical)
        previous = seen.get(key)
        if previous is not None:
            raise PatchValidationError(
                f"duplicate/case-colliding file change: {previous} and {canonical}"
            )
        seen[key] = canonical


def parse_patch_proposal(
    raw: str,
    *,
    max_changes: int = 64,
    max_content_bytes: int = 1024 * 1024,
) -> PatchProposal:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PatchValidationError(f"model response is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise PatchValidationError("patch proposal must be a JSON object")

    allowed_keys = {"summary", "changes", "notes"}
    unknown = set(value) - allowed_keys
    if unknown:
        raise PatchValidationError(f"unknown patch proposal fields: {sorted(unknown)}")

    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PatchValidationError("patch proposal summary is required")

    changes_raw = value.get("changes")
    if not isinstance(changes_raw, list):
        raise PatchValidationError("patch proposal changes must be an array")
    if len(changes_raw) > max_changes:
        raise PatchValidationError(f"too many file changes ({len(changes_raw)} > {max_changes})")

    notes_raw = value.get("notes", [])
    if not isinstance(notes_raw, list) or any(not isinstance(note, str) for note in notes_raw):
        raise PatchValidationError("patch proposal notes must be an array of strings")

    changes: list[FileChange] = []
    seen_paths: dict[str, str] = {}
    total_content = 0
    for item in changes_raw:
        if not isinstance(item, dict):
            raise PatchValidationError("each file change must be an object")
        expected_keys = {"operation", "path", "expected_hash", "content"}
        if set(item) != expected_keys:
            raise PatchValidationError(
                "each file change must contain exactly operation, path, expected_hash, content"
            )
        try:
            operation = FileOperation(item["operation"])
        except (ValueError, TypeError) as exc:
            raise PatchValidationError(f"invalid file operation: {item.get('operation')}") from exc
        path = _validate_path(item["path"])
        key = portable_path_key(path)
        previous = seen_paths.get(key)
        if previous is not None:
            raise PatchValidationError(
                f"duplicate/case-colliding file change: {previous} and {path}"
            )
        seen_paths[key] = path

        expected_hash = item["expected_hash"]
        content = item["content"]
        if expected_hash is not None and (
            not isinstance(expected_hash, str) or not expected_hash.startswith("sha256:")
        ):
            raise PatchValidationError(f"invalid expected_hash for {path}")
        if content is not None and not isinstance(content, str):
            raise PatchValidationError(f"content must be string or null for {path}")

        if operation == FileOperation.CREATE:
            if expected_hash is not None or content is None:
                raise PatchValidationError(
                    f"CREATE requires expected_hash=null and text content: {path}"
                )
        elif operation == FileOperation.UPDATE:
            if expected_hash is None or content is None:
                raise PatchValidationError(
                    f"UPDATE requires expected_hash and text content: {path}"
                )
        elif operation == FileOperation.DELETE:
            if expected_hash is None or content is not None:
                raise PatchValidationError(
                    f"DELETE requires expected_hash and content=null: {path}"
                )

        if content is not None:
            total_content += len(content.encode("utf-8"))
            if total_content > max_content_bytes:
                raise PatchValidationError(
                    f"patch content exceeds limit ({total_content} > {max_content_bytes} bytes)"
                )
        changes.append(FileChange(operation, path, expected_hash, content))

    return PatchProposal(summary.strip(), tuple(changes), tuple(notes_raw))


def validate_patch_preconditions(
    proposal: PatchProposal, repository: RepositoryReader
) -> None:
    _validate_proposal_path_identity(proposal)
    for change in proposal.changes:
        exists = repository.exists(change.path)
        if change.operation == FileOperation.CREATE:
            if exists:
                raise PatchValidationError(f"CREATE target already exists: {change.path}")
            continue
        if not exists:
            raise PatchValidationError(f"{change.operation.value} target is missing: {change.path}")
        actual_hash = repository.hash_file(change.path)
        if actual_hash != change.expected_hash:
            raise PatchValidationError(
                f"stale precondition for {change.path}: {actual_hash} != {change.expected_hash}"
            )
