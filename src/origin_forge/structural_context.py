from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .repository import ContextBudgetExceeded, RepositoryAccessError, RepositoryReader
from .runtime import OriginForgeRuntime


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class StructuralContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class StructuralSettings:
    max_scan_files: int = 2000
    max_scan_bytes: int = 8 * 1024 * 1024
    max_files: int = 16
    max_total_bytes: int = 768 * 1024
    git_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_scan_files <= 0:
            raise ValueError("max_scan_files must be positive")
        if self.max_scan_bytes <= 0:
            raise ValueError("max_scan_bytes must be positive")
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.git_timeout_seconds <= 0:
            raise ValueError("git_timeout_seconds must be positive")


@dataclass(frozen=True)
class StructuralCandidate:
    path: str
    score: int
    reasons: tuple[str, ...]
    byte_count: int


@dataclass(frozen=True)
class StructuralExpansionResult:
    task_id: str
    paths: tuple[str, ...]
    added: tuple[StructuralCandidate, ...]
    indexed_files: int
    indexed_bytes: int
    parse_failures: int


@dataclass(frozen=True)
class _PythonFile:
    path: str
    module: str
    byte_count: int
    definitions: frozenset[str]
    imports: frozenset[str]


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


def _module_for_path(path: str) -> str:
    candidate = Path(path)
    parts = list(candidate.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_test_path(path: str) -> bool:
    candidate = Path(path)
    return (
        any(part in {"test", "tests"} for part in candidate.parts[:-1])
        or candidate.name.startswith("test_")
        or candidate.name.endswith("_test.py")
    )


def _paired_stem(path: str) -> str | None:
    stem = Path(path).stem
    if stem.startswith("test_"):
        return stem.removeprefix("test_") or None
    if stem.endswith("_test"):
        return stem.removesuffix("_test") or None
    return stem


class PythonStructuralContext:
    """Expand selected context using deterministic Python structure.

    The index is built only from tracked UTF-8 Python files in the supplied
    RepositoryReader root. It never reads the user's live checkout when the
    caller provides a Workspace-local RepositoryReader.
    """

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader,
        *,
        settings: StructuralSettings | None = None,
    ):
        self.runtime = runtime
        self.repository = repository
        self.settings = settings or StructuralSettings()

    @staticmethod
    def _json_strings(raw: str, field: str) -> tuple[str, ...]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StructuralContextError(f"durable Task {field} is invalid JSON") from exc
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise StructuralContextError(f"durable Task {field} is not an array of strings")
        return tuple(value)

    def _task_terms(self, task_id: str) -> frozenset[str]:
        task = self.runtime.get_task(task_id)
        text = "\n".join(
            (
                task["objective"],
                *self._json_strings(task["acceptance_criteria_json"], "acceptance_criteria_json"),
                *self._json_strings(task["constraints_json"], "constraints_json"),
                *self._json_strings(task["required_capabilities_json"], "required_capabilities_json"),
            )
        )
        return frozenset(_tokens(text))

    def _tracked_python_paths(self) -> tuple[str, ...]:
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
            raise StructuralContextError(f"cannot enumerate tracked repository files: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")
            raise StructuralContextError(
                f"git ls-files failed ({result.returncode}): {detail[:1000]}"
            )
        try:
            paths = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
        except UnicodeDecodeError as exc:
            raise StructuralContextError("tracked repository path is not UTF-8") from exc
        return tuple(
            path
            for path in sorted(dict.fromkeys(paths))
            if path.casefold().endswith(".py")
        )

    @staticmethod
    def _definitions(tree: ast.AST) -> frozenset[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
        return frozenset(names)

    @staticmethod
    def _import_names(tree: ast.AST, *, module: str, is_package: bool) -> frozenset[str]:
        imports: set[str] = set()
        package = module if is_package else module.rpartition(".")[0]
        package_parts = package.split(".") if package else []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
                continue
            if not isinstance(node, ast.ImportFrom):
                continue

            if node.level:
                remove = node.level - 1
                if remove > len(package_parts):
                    continue
                base_parts = package_parts[: len(package_parts) - remove]
            else:
                base_parts = []

            if node.module:
                imported_module = node.module.split(".")
                if node.level:
                    base_parts = [*base_parts, *imported_module]
                else:
                    base_parts = imported_module

            base = ".".join(base_parts)
            if base:
                imports.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                child = ".".join([*base_parts, alias.name])
                if child:
                    imports.add(child)
        return frozenset(imports)

    def _index(self) -> tuple[tuple[_PythonFile, ...], int, int]:
        indexed: list[_PythonFile] = []
        indexed_bytes = 0
        considered = 0
        parse_failures = 0

        for path in self._tracked_python_paths():
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
            if indexed_bytes + size > self.settings.max_scan_bytes:
                continue
            try:
                source = self.repository.read_text(path)
            except (RepositoryAccessError, ContextBudgetExceeded):
                continue
            try:
                tree = ast.parse(source.content, filename=source.path)
            except (SyntaxError, ValueError):
                parse_failures += 1
                continue

            module = _module_for_path(source.path)
            indexed.append(
                _PythonFile(
                    source.path,
                    module,
                    source.byte_count,
                    self._definitions(tree),
                    self._import_names(
                        tree,
                        module=module,
                        is_package=Path(source.path).name == "__init__.py",
                    ),
                )
            )
            indexed_bytes += source.byte_count

        return tuple(indexed), parse_failures, indexed_bytes

    @staticmethod
    def _internal_import_paths(
        item: _PythonFile,
        module_to_path: dict[str, str],
    ) -> frozenset[str]:
        result: set[str] = set()
        for imported in item.imports:
            candidate = imported
            while candidate:
                path = module_to_path.get(candidate)
                if path is not None:
                    result.add(path)
                    break
                candidate = candidate.rpartition(".")[0]
        return frozenset(result)

    @staticmethod
    def _test_pairs(indexed: tuple[_PythonFile, ...]) -> dict[str, frozenset[str]]:
        by_stem: dict[str, list[_PythonFile]] = {}
        for item in indexed:
            stem = _paired_stem(item.path)
            if stem:
                by_stem.setdefault(stem.casefold(), []).append(item)

        pairs: dict[str, set[str]] = {item.path: set() for item in indexed}
        for group in by_stem.values():
            tests = [item for item in group if _is_test_path(item.path)]
            sources = [item for item in group if not _is_test_path(item.path)]
            for test in tests:
                for source in sources:
                    pairs[test.path].add(source.path)
                    pairs[source.path].add(test.path)
        return {path: frozenset(values) for path, values in pairs.items()}

    def expand(
        self,
        task_id: str,
        seed_paths: Iterable[str],
    ) -> StructuralExpansionResult:
        seeds: list[str] = []
        seed_bytes = 0
        for raw in seed_paths:
            try:
                source = self.repository.read_text(raw)
            except (RepositoryAccessError, ContextBudgetExceeded) as exc:
                raise StructuralContextError(f"invalid structural seed {raw}: {exc}") from exc
            if source.path in seeds:
                continue
            if len(seeds) >= self.settings.max_files:
                raise StructuralContextError("seed paths exceed structural file budget")
            if seed_bytes + source.byte_count > self.settings.max_total_bytes:
                raise StructuralContextError("seed paths exceed structural byte budget")
            seeds.append(source.path)
            seed_bytes += source.byte_count
        if not seeds:
            raise StructuralContextError("structural context expansion requires at least one seed path")

        indexed, parse_failures, indexed_bytes = self._index()
        by_path = {item.path: item for item in indexed}
        module_to_path = {item.module: item.path for item in indexed if item.module}
        import_edges = {
            item.path: self._internal_import_paths(item, module_to_path)
            for item in indexed
        }
        reverse_edges: dict[str, set[str]] = {item.path: set() for item in indexed}
        for importer, dependencies in import_edges.items():
            for dependency in dependencies:
                reverse_edges.setdefault(dependency, set()).add(importer)
        test_pairs = self._test_pairs(indexed)
        task_terms = self._task_terms(task_id)
        seed_set = set(seeds)

        scores: dict[str, int] = {}
        reasons: dict[str, set[str]] = {}

        def add(path: str, score: int, reason: str) -> None:
            if path in seed_set or path not in by_path:
                return
            scores[path] = scores.get(path, 0) + score
            reasons.setdefault(path, set()).add(reason)

        for seed in seeds:
            for paired in test_pairs.get(seed, ()):
                add(paired, 100, f"test-pair:{seed}")
            for dependency in import_edges.get(seed, ()):
                add(dependency, 80, f"imported-by:{seed}")
            for importer in reverse_edges.get(seed, ()):
                add(importer, 70, f"imports:{seed}")

        for item in indexed:
            if item.path in seed_set:
                continue
            definition_terms: set[str] = set()
            matched_symbols: list[str] = []
            for definition in item.definitions:
                tokens = set(_tokens(definition))
                if task_terms.intersection(tokens):
                    matched_symbols.append(definition)
                    definition_terms.update(task_terms.intersection(tokens))
            if matched_symbols:
                add(
                    item.path,
                    30 + 10 * len(definition_terms),
                    "task-symbol:" + ",".join(sorted(matched_symbols)),
                )

        ranked = sorted(
            scores,
            key=lambda path: (-scores[path], path),
        )
        selected = list(seeds)
        selected_bytes = seed_bytes
        added: list[StructuralCandidate] = []
        for path in ranked:
            if len(selected) >= self.settings.max_files:
                break
            item = by_path[path]
            if selected_bytes + item.byte_count > self.settings.max_total_bytes:
                continue
            candidate = StructuralCandidate(
                path,
                scores[path],
                tuple(sorted(reasons[path])),
                item.byte_count,
            )
            selected.append(path)
            selected_bytes += item.byte_count
            added.append(candidate)

        return StructuralExpansionResult(
            task_id,
            tuple(selected),
            tuple(added),
            len(indexed),
            indexed_bytes,
            parse_failures,
        )
