from __future__ import annotations

# Keep the accepted Phase-34 core implementation byte-identical and expand only
# this public compatibility surface with reviewed non-code binders.
from .production_dispatch_binding_core import *  # noqa: F401,F403
from .production_dispatch_binding_core import (
    CodeBoundedRetryInputBinder,
    DispatchInputBinder,
    DispatchInputBinderRegistry,
    _binding_with_id,
    _frozen_binding_audit_matches,
    _require_bundle_revalidates,
)
from .production_dispatch_binding_blender import BlenderExportGLBInputBinder
from .production_dispatch_binding_image import ImageGenerationInputBinder
from .production_dispatch_binding_pixelorama import PixeloramaSpritesheetExportInputBinder
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder


def builtin_dispatch_binders() -> tuple[DispatchInputBinder, ...]:
    """Return exactly the reviewed production input binders through Phase 51B."""

    return (
        CodeBoundedRetryInputBinder(),
        DeterministicSimulationInputBinder(),
        PixeloramaSpritesheetExportInputBinder(),
        BlenderExportGLBInputBinder(),
        ImageGenerationInputBinder(),
    )


def build_builtin_dispatch_binder_registry() -> DispatchInputBinderRegistry:
    return DispatchInputBinderRegistry(builtin_dispatch_binders())
