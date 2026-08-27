from __future__ import annotations

from .production_dispatch_binding_audio import (
    FfmpegAudioInputBinder,
    PiperAudioInputBinder,
)
from .production_dispatch_binding_blender import BlenderExportGLBInputBinder
from .production_dispatch_binding_core import (
    CodeBoundedRetryInputBinder,
    DispatchBindingError,  # noqa: F401
    DispatchInputBinder,
    DispatchInputBinderRegistry,
    _binding_with_id,  # noqa: F401
    _frozen_binding_audit_matches,  # noqa: F401
    _require_bundle_revalidates,  # noqa: F401
    audit_dispatch_binding_frozen,  # noqa: F401
    create_dispatch_binding,  # noqa: F401
    create_input_resolution_bundle,  # noqa: F401
    inspect_dispatch_binding_currentness,  # noqa: F401
)
from .production_dispatch_binding_image import ImageGenerationInputBinder
from .production_dispatch_binding_pixelorama import (
    PixeloramaSpritesheetExportInputBinder,
)
from .production_dispatch_binding_playtest import CooperativePlaytestInputBinder
from .production_dispatch_binding_runtime import RuntimeObservationInputBinder
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder


def builtin_dispatch_binders() -> tuple[DispatchInputBinder, ...]:
    """Return exactly the reviewed production input binders through Phase 51B."""

    return (
        CodeBoundedRetryInputBinder(),
        DeterministicSimulationInputBinder(),
        PixeloramaSpritesheetExportInputBinder(),
        BlenderExportGLBInputBinder(),
        ImageGenerationInputBinder(),
        FfmpegAudioInputBinder(),
        PiperAudioInputBinder(),
        RuntimeObservationInputBinder(),
        CooperativePlaytestInputBinder(),
    )


def build_builtin_dispatch_binder_registry() -> DispatchInputBinderRegistry:
    return DispatchInputBinderRegistry(builtin_dispatch_binders())
