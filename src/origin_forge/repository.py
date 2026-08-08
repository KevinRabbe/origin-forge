from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .path_policy import is_protected_root, portable_path_key, portable_relative_path


class RepositoryAccessError(RuntimeError):
    pass


class ContextBudgetExceeded(RepositoryAccessError):
    pass


@dataclass(frozen=True)
class SourceFile:
    path: str
    content_hash: str
    content: str
    byte_count: int


class RepositoryReader:
    """Read-only, project-contained repository access for model context."""

    def __init__(self, project_root: str | Path, *, max_file_bytes: int = 256 * 1024):
        self.project_root = Path(project_root).resolve()
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.max_file_bytes = max_file_bytes

    @staticmethod
    def _portable_input(path: str | Path) -> str:
        return path.as_posix() if isinstance(path, Path) else path

    def _resolve(self, path: str | Path, *, must_exist: bool = True) -> Path:
        try:
            portable = portable_relative_path(self._portable_input(path))
        except (TypeError, ValueError) as exc:
            raise RepositoryAccessError(str(exc)) from exc
        candidate = Path(*portable.parts)

        try:
            resolved = (self.project_root / candidate).resolve()
        except (OSError, RuntimeError) as exc:
            raise RepositoryAccessError(
                f"cannot resolve repository path: {portable.as_posix()}"
            ) from exc
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise RepositoryAccessError("repository path escapes project root") from exc
        if relative.parts and is_protected_root(relative.parts[0]):
            raise RepositoryAccessError(
                f"repository path resolves into protected root: {relative.parts[0]}"
            )

        if must_exist and not resolved.is_file():
            raise RepositoryAccessError(
                f"repository file does not exist: {portable.as_posix()}"
            )
        return resolved

    @staticmethod
    def _hash_bytes(data: bytes) -> str:
        return f"sha256:{hashlib.sha256(data).hexdigest()}"

    def exists(self, path: str | Path) -> bool:
        resolved = self._resolve(path, must_exist=False)
        return resolved.exists()

    def hash_file(self, path: str | Path) -> str:
        resolved = self._resolve(path)
        data = resolved.read_bytes()
        return self._hash_bytes(data)

    def read_text(self, path: str | Path) -> SourceFile:
        resolved = self._resolve(path)
        display_path = self._portable_input(path)
        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise ContextBudgetExceeded(
                f"file exceeds context file limit ({size} > {self.max_file_bytes} bytes): {display_path}"
            )
        data = resolved.read_bytes()
        if len(data) > self.max_file_bytes:
            raise ContextBudgetExceeded(
                f"file exceeds context file limit ({len(data)} > {self.max_file_bytes} bytes): {display_path}"
            )
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryAccessError(
                f"repository file is not UTF-8 text: {display_path}"
            ) from exc
        relative = resolved.relative_to(self.project_root).as_posix()
        return SourceFile(relative, self._hash_bytes(data), content, len(data))

    def snapshot(
        self,
        paths: Iterable[str | Path],
        *,
        max_total_bytes: int = 1024 * 1024,
    ) -> tuple[SourceFile, ...]:
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")

        result: list[SourceFile] = []
        seen: dict[str, str] = {}
        total = 0
        for path in paths:
            source = self.read_text(path)
            key = portable_path_key(source.path)
            previous = seen.get(key)
            if previous is not None:
                if previous == source.path:
                    continue
                raise RepositoryAccessError(
                    f"repository context contains case-colliding files: {previous} and {source.path}"
                )
            total += source.byte_count
            if total > max_total_bytes:
                raise ContextBudgetExceeded(
                    f"repository context exceeds total limit ({total} > {max_total_bytes} bytes)"
                )
            seen[key] = source.path
            result.append(source)
        return tuple(result)
