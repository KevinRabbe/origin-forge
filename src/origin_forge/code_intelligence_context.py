from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Iterable

from .code_intelligence import CodeIntelligenceError, CodeIntelligenceProvider, CodeSymbol
from .repository import ContextBudgetExceeded, RepositoryAccessError, RepositoryReader
from .runtime import OriginForgeRuntime


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class CodeIntelligenceContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodeIntelligenceContextSettings:
    max_queries: int = 8
    max_symbols_per_query: int = 20
    max_files: int = 16
    max_total_bytes: int = 768 * 1024
    git_timeout_seconds: float = 10.0
    max_git_output_bytes: int = 512 * 1024

    def __post_init__(self) -> None:
        if self.max_queries <= 0:
            raise ValueError("max_queries must be positive")
        if self.max_symbols_per_query <= 0:
            raise ValueError("max_symbols_per_query must be positive")
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.git_timeout_seconds <= 0:
            raise ValueError("git_timeout_seconds must be positive")
        if self.max_git_output_bytes <= 0:
            raise ValueError("max_git_output_bytes must be positive")


@dataclass(frozen=True)
class SemanticContextCandidate:
    path: str
    score: int
    reasons: tuple[str, ...]
    byte_count: int


@dataclass(frozen=True)
class SemanticContextResult:
    task_id: str
    paths: tuple[str, ...]
    added: tuple[SemanticContextCandidate, ...]
    query_terms: tuple[str, ...]


def _tokens(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in _TOKEN_RE.finditer(value):
        token = match.group(0)
        for camel in _CAMEL_RE.split(token):
            for part in camel.replace("_", " ").split():
                normalized = part.casefold()
                if len(normalized) >= 2:
                    result.append(normalized)
    return tuple(result)


class CodeIntelligenceContextExpander:
    """Expand Workspace context using bounded provider-neutral symbol evidence."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader,
        provider: CodeIntelligenceProvider,
        *,
        settings: CodeIntelligenceContextSettings | None = None,
    ):
        self.runtime = runtime
        self.repository = repository
        self.provider = provider
        self.settings = settings or CodeIntelligenceContextSettings()

    @staticmethod
    def _json_strings(raw: str, field: str) -> tuple[str, ...]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CodeIntelligenceContextError(
                f"durable Task {field} is invalid JSON"
            ) from exc
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise CodeIntelligenceContextError(
                f"durable Task {field} is not an array of strings"
            )
        return tuple(value)

    def _query_terms(self, task_id: str) -> tuple[str, ...]:
        task = self.runtime.get_task(task_id)
        text = "\n".join(
            (
                task["objective"],
                *self._json_strings(
                    task["acceptance_criteria_json"],
                    "acceptance_criteria_json",
                ),
                *self._json_strings(task["constraints_json"], "constraints_json"),
                *self._json_strings(
                    task["required_capabilities_json"],
                    "required_capabilities_json",
                ),
            )
        )
        unique = sorted(set(_tokens(text)), key=lambda term: (-len(term), term))
        return tuple(unique[: self.settings.max_queries])

    def _tracked_subset(self, paths: Iterable[str]) -> frozenset[str]:
        unique = tuple(dict.fromkeys(paths))
        if not unique:
            return frozenset()
        maximum = self.settings.max_files + (
            self.settings.max_queries * self.settings.max_symbols_per_query
        )
        if len(unique) > maximum:
            raise CodeIntelligenceContextError(
                f"semantic tracked-path check exceeds limit ({len(unique)} > {maximum})"
            )

        # Every path is already repository-contained before reaching this
        # helper. Git's literal pathspec magic prevents wildcard-like filename
        # characters from widening one candidate into a repository scan.
        pathspecs = [f":(literal){path}" for path in unique]
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z", "--cached", "--", *pathspecs],
                cwd=self.repository.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.settings.git_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodeIntelligenceContextError(
                f"cannot verify tracked semantic paths: {exc}"
            ) from exc
        if len(result.stdout) > self.settings.max_git_output_bytes:
            raise CodeIntelligenceContextError(
                "tracked semantic path output exceeds byte limit "
                f"({len(result.stdout)} > {self.settings.max_git_output_bytes})"
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")
            raise CodeIntelligenceContextError(
                f"git ls-files failed ({result.returncode}): {detail[:1000]}"
            )
        try:
            tracked = frozenset(
                item.decode("utf-8")
                for item in result.stdout.split(b"\0")
                if item
            )
        except UnicodeDecodeError as exc:
            raise CodeIntelligenceContextError(
                "tracked semantic path is not UTF-8"
            ) from exc
        unexpected = tracked.difference(unique)
        if unexpected:
            raise CodeIntelligenceContextError(
                f"Git returned unexpected semantic paths: {sorted(unexpected)[:3]}"
            )
        return tracked

    @staticmethod
    def _symbol_score(term: str, symbol: CodeSymbol) -> int:
        name = symbol.name.casefold()
        symbol_terms = set(_tokens(symbol.name))
        score = 0
        if term == name:
            score += 100
        elif term in symbol_terms:
            score += 80
        elif term in name:
            score += 30
        if symbol.container_name:
            container_terms = set(_tokens(symbol.container_name))
            if term in container_terms:
                score += 15
        return score

    def expand(
        self,
        task_id: str,
        seed_paths: Iterable[str],
    ) -> SemanticContextResult:
        if not self.provider.available():
            raise CodeIntelligenceContextError(
                f"code-intelligence provider is unavailable: {self.provider.provider_id}"
            )
        if not self.provider.capabilities.workspace_symbols:
            raise CodeIntelligenceContextError(
                f"provider {self.provider.provider_id} does not support workspace symbols"
            )

        seeds: list[str] = []
        selected_bytes = 0
        for raw in seed_paths:
            try:
                source = self.repository.read_text(raw)
            except (RepositoryAccessError, ContextBudgetExceeded) as exc:
                raise CodeIntelligenceContextError(
                    f"invalid semantic context seed {raw}: {exc}"
                ) from exc
            if source.path in seeds:
                continue
            if len(seeds) >= self.settings.max_files:
                raise CodeIntelligenceContextError(
                    "seed paths exceed semantic context file budget"
                )
            if selected_bytes + source.byte_count > self.settings.max_total_bytes:
                raise CodeIntelligenceContextError(
                    "seed paths exceed semantic context byte budget"
                )
            seeds.append(source.path)
            selected_bytes += source.byte_count

        if not seeds:
            raise CodeIntelligenceContextError(
                "semantic context expansion requires at least one seed path"
            )
        tracked_seeds = self._tracked_subset(seeds)
        missing_seeds = set(seeds).difference(tracked_seeds)
        if missing_seeds:
            raise CodeIntelligenceContextError(
                f"semantic context seed is not tracked: {sorted(missing_seeds)[0]}"
            )

        query_terms = self._query_terms(task_id)
        seed_set = set(seeds)
        scores: dict[str, int] = {}
        reasons: dict[str, set[str]] = {}

        for term in query_terms:
            try:
                symbols = self.provider.workspace_symbols(
                    term,
                    limit=self.settings.max_symbols_per_query,
                )
            except (CodeIntelligenceError, TimeoutError, OSError) as exc:
                raise CodeIntelligenceContextError(
                    f"code-intelligence query failed for {term!r}: {exc}"
                ) from exc
            for index, symbol in enumerate(symbols):
                if index >= self.settings.max_symbols_per_query:
                    break
                path = symbol.location.path
                if path in seed_set:
                    continue
                try:
                    if not self.repository.exists(path):
                        continue
                except RepositoryAccessError as exc:
                    raise CodeIntelligenceContextError(
                        f"unsafe semantic symbol path {path!r}: {exc}"
                    ) from exc
                score = self._symbol_score(term, symbol)
                if score <= 0:
                    continue
                scores[path] = scores.get(path, 0) + score
                reasons.setdefault(path, set()).add(
                    f"symbol:{term}:{symbol.name}"
                )

        tracked_candidates = self._tracked_subset(scores)
        ranked = sorted(
            (path for path in scores if path in tracked_candidates),
            key=lambda path: (-scores[path], path),
        )
        selected = list(seeds)
        added: list[SemanticContextCandidate] = []
        for path in ranked:
            if len(selected) >= self.settings.max_files:
                break
            try:
                source = self.repository.read_text(path)
            except (RepositoryAccessError, ContextBudgetExceeded):
                continue
            if selected_bytes + source.byte_count > self.settings.max_total_bytes:
                continue
            selected.append(source.path)
            selected_bytes += source.byte_count
            added.append(
                SemanticContextCandidate(
                    source.path,
                    scores[path],
                    tuple(sorted(reasons[path])),
                    source.byte_count,
                )
            )

        return SemanticContextResult(
            task_id,
            tuple(selected),
            tuple(added),
            query_terms,
        )
