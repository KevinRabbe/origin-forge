from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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

    _BLOCKED_ROOTS = frozenset({".git", ".origin-forge"})

    def __init__(self, project_root: str | Path, *, max_file_bytes: int = 256 * 1024):
        self.project_root = Path(project_root).resolve()
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.max_file_bytes = max_file_bytes

    def _resolve(self, path: str | Path, *, must_exist: bool = True) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            raise RepositoryAccessError("repository paths must be relative")
        if not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise RepositoryAccessError("repository path is invalid")
        if candidate.parts[0] in self._BLOCKED_ROOTS:
            raise RepositoryAccessError(
                f"repository path enters protected root: {candidate.parts[0]}"
            )

        resolved = (self.project_root / candidate).resolve()
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise RepositoryAccessError("repository path escapes project root") from exc
        if relative.parts and relative.parts[0] in self._BLOCKED_ROOTS:
            raise RepositoryAccessError(
                f"repository path resolves into protected root: {relative.parts[0]}"
            )

        if must_exist and not resolved.is_file():
            raise RepositoryAccessError(f"repository file does not exist: {candidate.as_posix()}")
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
        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise ContextBudgetExceeded(
                f"file exceeds context file limit ({size} > {self.max_file_bytes} bytes): {Path(path).as_posix()}"
            )
        data = resolved.read_bytes()
        if len(data) > self.max_file_bytes:
            raise ContextBudgetExceeded(
                f"file exceeds context file limit ({len(data)} > {self.max_file_bytes} bytes): {Path(path).as_posix()}"
            )
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryAccessError(
                f"repository file is not UTF-8 text: {Path(path).as_posix()}"
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
        seen: set[str] = set()
        total = 0
        for path in paths:
            source = self.read_text(path)
            if source.path in seen:
                continue
            total += source.byte_count
            if total > max_total_bytes:
                raise ContextBudgetExceeded(
                    f"repository context exceeds total limit ({total} > {max_total_bytes} bytes)"
                )
            seen.add(source.path)
            result.append(source)
        return tuple(result)
