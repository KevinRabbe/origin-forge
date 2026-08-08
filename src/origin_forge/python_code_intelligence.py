from __future__ import annotations

import ast
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Sequence

from .code_intelligence import (
    CodeDiagnostic,
    CodeIntelligenceCapabilities,
    CodeIntelligenceError,
    CodeLocation,
    CodeSymbol,
    DiagnosticSeverity,
    SymbolKind,
    TextPosition,
    TextRange,
)
from .repository import ContextBudgetExceeded, RepositoryAccessError, RepositoryReader


_IDENTIFIER_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)


@dataclass(frozen=True)
class PythonIntelligenceSettings:
    max_scan_files: int = 2000
    max_scan_bytes: int = 8 * 1024 * 1024
    git_timeout_seconds: float = 10.0
    max_git_output_bytes: int = 2 * 1024 * 1024
    max_git_stderr_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if self.max_scan_files <= 0:
            raise ValueError("max_scan_files must be positive")
        if self.max_scan_bytes <= 0:
            raise ValueError("max_scan_bytes must be positive")
        if self.git_timeout_seconds <= 0:
            raise ValueError("git_timeout_seconds must be positive")
        if self.max_git_output_bytes <= 0:
            raise ValueError("max_git_output_bytes must be positive")
        if self.max_git_stderr_bytes <= 0:
            raise ValueError("max_git_stderr_bytes must be positive")


@dataclass(frozen=True)
class _ParsedFile:
    path: str
    content: str
    tree: ast.AST
    symbols: tuple[CodeSymbol, ...]
    byte_count: int


class _BoundedCapture:
    def __init__(self, limit: int, *, kill_on_overflow: bool = False):
        self.limit = limit
        self.kill_on_overflow = kill_on_overflow
        self.data = bytearray()
        self.overflow = False

    def consume(self, stream, process: subprocess.Popen) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = self.limit - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                self.overflow = True
                if self.kill_on_overflow:
                    try:
                        process.kill()
                    except OSError:
                        pass


def _bounded_limit(limit: int, *, maximum: int = 1000) -> int:
    if limit <= 0:
        raise ValueError("limit must be positive")
    return min(limit, maximum)


def _byte_column_to_character(line: str, byte_column: int) -> int:
    encoded = line.encode("utf-8")
    prefix = encoded[: min(max(byte_column, 0), len(encoded))]
    try:
        return len(prefix.decode("utf-8"))
    except UnicodeDecodeError:
        return len(prefix.decode("utf-8", errors="ignore"))


def _node_range(content: str, node: ast.AST) -> TextRange:
    lines = content.splitlines()
    start_line = max(int(getattr(node, "lineno", 1)) - 1, 0)
    end_line = max(int(getattr(node, "end_lineno", start_line + 1)) - 1, start_line)
    start_text = lines[start_line] if start_line < len(lines) else ""
    end_text = lines[end_line] if end_line < len(lines) else ""
    start = TextPosition(
        start_line,
        _byte_column_to_character(start_text, int(getattr(node, "col_offset", 0))),
    )
    end = TextPosition(
        end_line,
        _byte_column_to_character(
            end_text,
            int(getattr(node, "end_col_offset", getattr(node, "col_offset", 0))),
        ),
    )
    if end < start:
        end = start
    return TextRange(start, end)


def _definition_name_range(content: str, node: ast.AST, name: str) -> TextRange:
    lines = content.splitlines()
    line_index = max(int(getattr(node, "lineno", 1)) - 1, 0)
    line = lines[line_index] if line_index < len(lines) else ""
    start_hint = _byte_column_to_character(line, int(getattr(node, "col_offset", 0)))
    match = re.search(rf"\b{re.escape(name)}\b", line[start_hint:])
    if match is None:
        return _node_range(content, node)
    start = start_hint + match.start()
    end = start_hint + match.end()
    return TextRange(TextPosition(line_index, start), TextPosition(line_index, end))


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self, path: str, content: str):
        self.path = path
        self.content = content
        self.scope: list[tuple[str, SymbolKind]] = []
        self.symbols: list[CodeSymbol] = []

    def _append(self, node: ast.AST, name: str, kind: SymbolKind) -> None:
        self.symbols.append(
            CodeSymbol(
                name,
                kind,
                CodeLocation(self.path, _definition_name_range(self.content, node, name)),
                self.scope[-1][0] if self.scope else None,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._append(node, node.name, SymbolKind.CLASS)
        self.scope.append((node.name, SymbolKind.CLASS))
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        immediate_class = bool(self.scope and self.scope[-1][1] == SymbolKind.CLASS)
        kind = SymbolKind.METHOD if immediate_class else SymbolKind.FUNCTION
        self._append(node, node.name, kind)
        self.scope.append((node.name, kind))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


class PythonAstCodeIntelligence:
    """Bounded read-only Python code intelligence over a Git snapshot.

    This provider executes no project code. It enumerates tracked Python files
    under hard process/output/scan bounds, reads them through RepositoryReader,
    and derives symbols, definitions, references, and syntax diagnostics from
    Python's AST.
    """

    provider_id = "python-ast"
    capabilities = CodeIntelligenceCapabilities(
        workspace_symbols=True,
        definitions=True,
        references=True,
        diagnostics=True,
    )

    def __init__(
        self,
        repository: RepositoryReader,
        *,
        settings: PythonIntelligenceSettings | None = None,
    ):
        self.repository = repository
        self.settings = settings or PythonIntelligenceSettings()

    def available(self) -> bool:
        return (self.repository.project_root / ".git").exists()

    def _tracked_python_paths(self) -> tuple[str, ...]:
        try:
            process = subprocess.Popen(
                ["git", "ls-files", "-z", "--cached", "--", "*.py"],
                cwd=self.repository.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise CodeIntelligenceError(f"cannot enumerate tracked files: {exc}") from exc
        assert process.stdout is not None and process.stderr is not None

        stdout = _BoundedCapture(self.settings.max_git_output_bytes, kill_on_overflow=True)
        stderr = _BoundedCapture(self.settings.max_git_stderr_bytes)
        out_thread = threading.Thread(
            target=stdout.consume, args=(process.stdout, process), daemon=True
        )
        err_thread = threading.Thread(
            target=stderr.consume, args=(process.stderr, process), daemon=True
        )
        out_thread.start()
        err_thread.start()
        try:
            try:
                returncode = process.wait(timeout=self.settings.git_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                try:
                    process.kill()
                except OSError:
                    pass
                process.wait()
                raise CodeIntelligenceError("git ls-files exceeded code-intelligence timeout") from exc
        finally:
            out_thread.join(timeout=1.0)
            err_thread.join(timeout=1.0)
            process.stdout.close()
            process.stderr.close()

        if stdout.overflow:
            raise CodeIntelligenceError(
                "git ls-files output exceeds code-intelligence byte limit "
                f"({self.settings.max_git_output_bytes} bytes)"
            )
        if returncode != 0:
            detail = bytes(stderr.data).decode("utf-8", errors="replace")
            if stderr.overflow:
                detail += "…"
            raise CodeIntelligenceError(
                f"git ls-files failed ({returncode}): {detail[:1000]}"
            )

        paths: list[str] = []
        for item in bytes(stdout.data).split(b"\0"):
            if not item:
                continue
            try:
                path = item.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CodeIntelligenceError("tracked repository path is not UTF-8") from exc
            if not path.casefold().endswith(".py"):
                continue
            paths.append(path)
            if len(paths) >= self.settings.max_scan_files:
                break
        return tuple(sorted(dict.fromkeys(paths)))

    def _parse_path(self, path: str) -> _ParsedFile | None:
        raw = self.repository.project_root / path
        if raw.is_symlink():
            return None
        try:
            source = self.repository.read_text(path)
        except (RepositoryAccessError, ContextBudgetExceeded):
            return None
        try:
            tree = ast.parse(source.content, filename=source.path)
        except (SyntaxError, ValueError):
            return None
        collector = _SymbolCollector(source.path, source.content)
        collector.visit(tree)
        return _ParsedFile(
            source.path,
            source.content,
            tree,
            tuple(collector.symbols),
            source.byte_count,
        )

    def _index(self) -> tuple[_ParsedFile, ...]:
        parsed: list[_ParsedFile] = []
        consumed = 0
        considered = 0
        for path in self._tracked_python_paths():
            if considered >= self.settings.max_scan_files:
                break
            considered += 1
            raw = self.repository.project_root / path
            if raw.is_symlink():
                continue
            try:
                size = raw.stat().st_size
            except OSError:
                continue
            if size > self.repository.max_file_bytes:
                continue
            if consumed + size > self.settings.max_scan_bytes:
                continue
            consumed += size
            item = self._parse_path(path)
            if item is not None:
                parsed.append(item)
        return tuple(parsed)

    @staticmethod
    def _symbol_at(content: str, position: TextPosition) -> str | None:
        lines = content.splitlines()
        if position.line >= len(lines):
            return None
        line = lines[position.line]
        if position.character > len(line):
            return None
        for match in _IDENTIFIER_RE.finditer(line):
            if match.start() <= position.character < match.end():
                return match.group(0)
            if position.character == match.end() and match.end() > match.start():
                return match.group(0)
        return None

    def _target_symbol(self, path: str, position: TextPosition) -> str | None:
        try:
            source = self.repository.read_text(path)
        except (RepositoryAccessError, ContextBudgetExceeded) as exc:
            raise CodeIntelligenceError(f"cannot inspect {path}: {exc}") from exc
        return self._symbol_at(source.content, position)

    def workspace_symbols(self, query: str, *, limit: int = 50) -> Sequence[CodeSymbol]:
        limit = _bounded_limit(limit)
        needle = query.casefold().strip()
        result: list[CodeSymbol] = []
        for item in self._index():
            for symbol in item.symbols:
                if needle and needle not in symbol.name.casefold():
                    continue
                result.append(symbol)
        result.sort(
            key=lambda symbol: (
                0 if symbol.name.casefold() == needle and needle else 1,
                symbol.name.casefold(),
                symbol.location.path,
                symbol.location.range.start,
            )
        )
        return tuple(result[:limit])

    def definitions(
        self,
        path: str,
        position: TextPosition,
        *,
        limit: int = 20,
    ) -> Sequence[CodeLocation]:
        limit = _bounded_limit(limit)
        name = self._target_symbol(path, position)
        if name is None:
            return ()
        locations: list[CodeLocation] = []
        for item in self._index():
            for symbol in item.symbols:
                if symbol.name == name:
                    locations.append(symbol.location)
        locations.sort(key=lambda location: (location.path, location.range.start))
        return tuple(locations[:limit])

    def references(
        self,
        path: str,
        position: TextPosition,
        *,
        include_declaration: bool = True,
        limit: int = 100,
    ) -> Sequence[CodeLocation]:
        limit = _bounded_limit(limit)
        name = self._target_symbol(path, position)
        if name is None:
            return ()
        locations: list[CodeLocation] = []
        for item in self._index():
            for symbol in item.symbols:
                if symbol.name == name and include_declaration:
                    locations.append(symbol.location)
            for node in ast.walk(item.tree):
                if isinstance(node, ast.Name) and node.id == name:
                    locations.append(CodeLocation(item.path, _node_range(item.content, node)))

        unique = {
            (location.path, location.range.start, location.range.end): location
            for location in locations
        }
        ordered = sorted(
            unique.values(),
            key=lambda location: (location.path, location.range.start, location.range.end),
        )
        return tuple(ordered[:limit])

    def diagnostics(
        self,
        paths: Sequence[str],
        *,
        limit_per_file: int = 100,
    ) -> Sequence[CodeDiagnostic]:
        _bounded_limit(limit_per_file)
        result: list[CodeDiagnostic] = []
        for path in dict.fromkeys(paths):
            try:
                source = self.repository.read_text(path)
            except (RepositoryAccessError, ContextBudgetExceeded) as exc:
                raise CodeIntelligenceError(f"cannot inspect {path}: {exc}") from exc
            if not source.path.casefold().endswith(".py"):
                continue
            try:
                ast.parse(source.content, filename=source.path)
            except SyntaxError as exc:
                line = max((exc.lineno or 1) - 1, 0)
                character = max((exc.offset or 1) - 1, 0)
                end_line = max((exc.end_lineno or exc.lineno or 1) - 1, line)
                end_character = max((exc.end_offset or exc.offset or 1) - 1, 0)
                if end_line == line:
                    end_character = max(end_character, character)
                result.append(
                    CodeDiagnostic(
                        source.path,
                        TextRange(
                            TextPosition(line, character),
                            TextPosition(end_line, end_character),
                        ),
                        DiagnosticSeverity.ERROR,
                        exc.msg,
                        self.provider_id,
                        "SyntaxError",
                    )
                )
        return tuple(result)
