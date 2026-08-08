from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .context_discovery import DiscoveryResult, TaskContextDiscoverer
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


class WorkspaceContextSelector:
    """Compose bounded context selection for one immutable Workspace snapshot.

    The selector owns only selection policy. It receives an already-scoped
    RepositoryReader and never creates a Workspace, invokes a model, or mutates
    repository files.
    """

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        repository: RepositoryReader,
    ):
        self.runtime = runtime
        self.repository = repository

    def select(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str] | None = None,
        auto_context: bool = False,
        seed_paths: Iterable[str] = (),
        structural_context: bool = False,
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

        return ContextSelectionResult(
            task_id=task_id,
            paths=paths,
            mode=mode,
            lexical=lexical,
            structural=structural,
        )
