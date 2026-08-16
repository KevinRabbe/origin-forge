from __future__ import annotations

# Phase 48B keeps the accepted Phase-34 core implementation byte-identical and
# expands only this public compatibility surface with the reviewed Pixelorama
# spritesheet-export binder alongside the existing code and simulation binders.
from .production_dispatch_binding_core import *  # noqa: F401,F403
from .production_dispatch_binding_core import (
    CodeBoundedRetryInputBinder,
    DispatchInputBinder,
    DispatchInputBinderRegistry,
    _binding_with_id,
    _frozen_binding_audit_matches,
    _require_bundle_revalidates,
)
from .production_dispatch_binding_pixelorama import PixeloramaSpritesheetExportInputBinder
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder


def builtin_dispatch_binders() -> tuple[DispatchInputBinder, ...]:
    """Return exactly the three reviewed production input binders through Phase 48B."""

    return (
        CodeBoundedRetryInputBinder(),
        DeterministicSimulationInputBinder(),
        PixeloramaSpritesheetExportInputBinder(),
    )


def build_builtin_dispatch_binder_registry() -> DispatchInputBinderRegistry:
    return DispatchInputBinderRegistry(builtin_dispatch_binders())
