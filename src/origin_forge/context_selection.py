from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .code_intelligence import CodeIntelligenceProvider
from .code_intelligence_context import (
    CodeIntelligenceContextExpander,
    SemanticContextResult,
)
from .context_discovery import DiscoveryResult, TaskContextDiscoverer
from .python_code_intelligence import PythonAstCodeIntelligence
from .repository import RepositoryReader
from .runtime import OriginForgeRuntime
from .structural_context import PythonStructuralContext, StructuralExpansionResult


class ContextSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextSelectionResult:
    task_id: str
    paths: tuple[str, ...]
    mode: str
    lexical: DiscoveryResult | None = None
    structural: StructuralExpansionResult | None = None
    semantic: SemanticContextResult | None = None


class WorkspaceContextSelector:
    """Compose bounded context selection for one immutable Workspace snapshot.

    The selector owns only selection policy. It receives an already-scoped
    RepositoryReader and never creates a Workspace, invokes a model, or mutates
    repository files. Semantic expansion uses a caller-supplied read-only
    provider when present; otherwise the deterministic Python AST provider is
    used. No provider is queried unless `semantic_context=True`.
    """

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader,
        *,
        code_intelligence_provider: CodeIntelligenceProvider | None = None,
    ):
        self.runtime = runtime
        self.repository = repository
        self.code_intelligence_provider = code_intelligence_provider

    def select(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str] | None = None,
        auto_context: bool = False,
        seed_paths: Iterable[str] = (),
        structural_context: bool = False,
        semantic_context: bool = False,
    ) -> ContextSelectionResult:
        explicit = tuple(selected_paths or ())
        seeds = tuple(seed_paths)

        if auto_context and explicit:
            raise ContextSelectionError(
                "auto_context cannot be combined with selected_paths"
            )
        if not auto_context and not explicit:
            raise ContextSelectionError(
                "context selection requires selected_paths or auto_context=True"
            )
        if seeds and not auto_context:
            raise ContextSelectionError("seed_paths require auto_context=True")

        lexical: DiscoveryResult | None = None
        if auto_context:
            lexical = TaskContextDiscoverer(
                self.runtime,
                self.repository,
            ).discover(
                task_id,
                seed_paths=seeds,
            )
            paths = lexical.paths
            mode = "AUTO"
        else:
            paths = explicit
            mode = "MANUAL"

        structural: StructuralExpansionResult | None = None
        if structural_context and paths:
            structural = PythonStructuralContext(
                self.runtime,
                self.repository,
            ).expand(task_id, paths)
            paths = structural.paths
            mode += "+STRUCTURAL"

        semantic: SemanticContextResult | None = None
        if semantic_context and paths:
            provider = self.code_intelligence_provider or PythonAstCodeIntelligence(
                self.repository
            )
            semantic = CodeIntelligenceContextExpander(
                self.runtime,
                self.repository,
                provider,
            ).expand(task_id, paths)
            paths = semantic.paths
            mode += "+SEMANTIC"

        return ContextSelectionResult(
            task_id=task_id,
            paths=paths,
            mode=mode,
            lexical=lexical,
            structural=structural,
            semantic=semantic,
        )
