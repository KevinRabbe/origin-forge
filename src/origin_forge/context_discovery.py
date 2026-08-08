from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .repository import ContextBudgetExceeded, RepositoryAccessError, RepositoryReader, SourceFile
from .runtime import OriginForgeRuntime


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "code",
        "do",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "should",
        "task",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


class ContextDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoverySettings:
    max_files: int = 12
    max_total_bytes: int = 512 * 1024
    max_scan_files: int = 2000
    max_scan_bytes: int = 8 * 1024 * 1024
    git_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.max_scan_files <= 0:
            raise ValueError("max_scan_files must be positive")
        if self.max_scan_bytes <= 0:
            raise ValueError("max_scan_bytes must be positive")
        if self.git_timeout_seconds <= 0:
            raise ValueError("git_timeout_seconds must be positive")


@dataclass(frozen=True)
class DiscoveryCandidate:
    path: str
    score: float
    byte_count: int
    matched_terms: tuple[str, ...]
    seeded: bool = False


@dataclass(frozen=True)
class DiscoveryResult:
    task_id: str
    query_terms: tuple[str, ...]
    selected: tuple[DiscoveryCandidate, ...]
    scanned_files: int
    scanned_bytes: int

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(candidate.path for candidate in self.selected)


@dataclass(frozen=True)
class _IndexedSource:
    source: SourceFile
    path_tokens: frozenset[str]
    content_counts: Counter[str]


def _tokens(value: str) -> list[str]:
    result: list[str] = []
    for match in _TOKEN_RE.finditer(value):
        token = match.group(0)
        for camel_part in _CAMEL_RE.split(token):
            for part in camel_part.replace("_", " ").split():
                normalized = part.casefold()
                if len(normalized) >= 2 and normalized not in _STOPWORDS:
                    result.append(normalized)
    return result


def _path_tokens(path: str) -> frozenset[str]:
    candidate = Path(path)
    without_suffix = candidate.with_suffix("").as_posix() if candidate.suffix else candidate.as_posix()
    return frozenset(_tokens(without_suffix))


class TaskContextDiscoverer:
    """Deterministically rank tracked text files for one durable Task."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader,
        *,
        settings: DiscoverySettings | None = None,
    ):
        self.runtime = runtime
        self.repository = repository
        self.settings = settings or DiscoverySettings()

    @staticmethod
    def _json_strings(raw: str) -> tuple[str, ...]:
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ContextDiscoveryError("durable Task JSON field is not an array of strings")
        return tuple(value)

    def _query_terms(self, task_id: str) -> tuple[str, ...]:
        task = self.runtime.get_task(task_id)
        text = "\n".join(
            (
                task["objective"],
                *self._json_strings(task["acceptance_criteria_json"]),
                *self._json_strings(task["constraints_json"]),
                *self._json_strings(task["required_capabilities_json"]),
            )
        )
        seen: set[str] = set()
        ordered: list[str] = []
        for token in _tokens(text):
            if token not in seen:
                seen.add(token)
                ordered.append(token)
        return tuple(ordered)

    def _tracked_paths(self) -> tuple[str, ...]:
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z", "--cached", "--"],
                cwd=self.repository.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.settings.git_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContextDiscoveryError(f"cannot enumerate tracked repository files: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")
            raise ContextDiscoveryError(
                f"git ls-files failed ({result.returncode}): {detail[:1000]}"
            )
        try:
            paths = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
        except UnicodeDecodeError as exc:
            raise ContextDiscoveryError("tracked repository path is not UTF-8") from exc
        return tuple(sorted(dict.fromkeys(paths)))

    def _ordered_scan_paths(self, query_terms: tuple[str, ...]) -> tuple[str, ...]:
        query = set(query_terms)
        ranked: list[tuple[int, str]] = []
        for path in self._tracked_paths():
            matches = len(query.intersection(_path_tokens(path)))
            ranked.append((matches, path))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(path for _, path in ranked)

    def _index(
        self, query_terms: tuple[str, ...]
    ) -> tuple[tuple[_IndexedSource, ...], int, int]:
        indexed: list[_IndexedSource] = []
        scanned_bytes = 0
        considered = 0
        for path in self._ordered_scan_paths(query_terms):
            if considered >= self.settings.max_scan_files:
                break
            considered += 1
            raw_path = self.repository.project_root / path
            if raw_path.is_symlink():
                continue
            try:
                size = raw_path.stat().st_size
            except OSError:
                continue
            if size > self.repository.max_file_bytes:
                continue
            if scanned_bytes + size > self.settings.max_scan_bytes:
                continue
            try:
                source = self.repository.read_text(path)
            except (RepositoryAccessError, ContextBudgetExceeded):
                continue
            scanned_bytes += source.byte_count
            indexed.append(
                _IndexedSource(
                    source,
                    _path_tokens(source.path),
                    Counter(_tokens(source.content)),
                )
            )
        return tuple(indexed), len(indexed), scanned_bytes

    @staticmethod
    def _score(
        item: _IndexedSource,
        query_terms: tuple[str, ...],
        document_frequency: Counter[str],
        document_count: int,
    ) -> tuple[float, tuple[str, ...]]:
        score = 0.0
        matched: list[str] = []
        stem = Path(item.source.path).stem.casefold()
        for term in query_terms:
            tf = item.content_counts.get(term, 0)
            path_match = term in item.path_tokens
            filename_match = term == stem
            if not tf and not path_match and not filename_match:
                continue
            matched.append(term)
            df = document_frequency.get(term, 0)
            idf = math.log((document_count + 1) / (df + 1)) + 1.0
            if tf:
                score += (1.0 + math.log(tf)) * idf
            if path_match:
                score += 6.0 * idf
            if filename_match:
                score += 8.0 * idf
        return score, tuple(matched)

    def discover(
        self,
        task_id: str,
        *,
        seed_paths: Iterable[str] = (),
    ) -> DiscoveryResult:
        query_terms = self._query_terms(task_id)
        indexed, scanned_files, scanned_bytes = self._index(query_terms)
        by_path = {item.source.path: item for item in indexed}

        document_frequency: Counter[str] = Counter()
        for item in indexed:
            present = set(item.content_counts) | set(item.path_tokens)
            for term in query_terms:
                if term in present:
                    document_frequency[term] += 1

        ranked: list[DiscoveryCandidate] = []
        for item in indexed:
            score, matched = self._score(
                item,
                query_terms,
                document_frequency,
                len(indexed),
            )
            if score > 0:
                ranked.append(
                    DiscoveryCandidate(
                        item.source.path,
                        score,
                        item.source.byte_count,
                        matched,
                    )
                )
        ranked.sort(key=lambda candidate: (-candidate.score, candidate.path))

        selected: list[DiscoveryCandidate] = []
        selected_paths: set[str] = set()
        selected_bytes = 0

        for seed in seed_paths:
            try:
                source = self.repository.read_text(seed)
            except (RepositoryAccessError, ContextBudgetExceeded) as exc:
                raise ContextDiscoveryError(f"invalid seed path {seed}: {exc}") from exc
            if source.path in selected_paths:
                continue
            if len(selected) >= self.settings.max_files:
                raise ContextDiscoveryError("seed paths exceed selected-file budget")
            if selected_bytes + source.byte_count > self.settings.max_total_bytes:
                raise ContextDiscoveryError("seed paths exceed selected-byte budget")
            item = by_path.get(source.path)
            matched: tuple[str, ...] = ()
            score = 0.0
            if item is not None:
                score, matched = self._score(
                    item,
                    query_terms,
                    document_frequency,
                    len(indexed),
                )
            selected.append(
                DiscoveryCandidate(
                    source.path,
                    score,
                    source.byte_count,
                    matched,
                    seeded=True,
                )
            )
            selected_paths.add(source.path)
            selected_bytes += source.byte_count

        for candidate in ranked:
            if candidate.path in selected_paths:
                continue
            if len(selected) >= self.settings.max_files:
                break
            if selected_bytes + candidate.byte_count > self.settings.max_total_bytes:
                continue
            selected.append(candidate)
            selected_paths.add(candidate.path)
            selected_bytes += candidate.byte_count

        return DiscoveryResult(
            task_id,
            query_terms,
            tuple(selected),
            scanned_files,
            scanned_bytes,
        )
