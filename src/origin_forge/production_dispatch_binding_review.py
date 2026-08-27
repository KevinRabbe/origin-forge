from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_capability_builtin import build_builtin_capability_catalog
from .production_capability_models import CapabilityCatalog
from .production_dispatch_binding import build_builtin_dispatch_binder_registry
from .production_dispatch_phase_resolvers import build_dispatch_input_resolver_registry
from .production_work_order_builtin import build_builtin_dispatch_catalog


class BuiltinBindingReviewStatus(StrEnum):
    BINDABLE = "BINDABLE"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class BuiltinBindingReview:
    adapter_id: str
    status: BuiltinBindingReviewStatus
    blocker: str | None
    reason: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "adapter_id": self.adapter_id,
            "status": self.status.value,
            "blocker": self.blocker,
            "reason": self.reason,
        }


def builtin_binding_review() -> tuple[BuiltinBindingReview, ...]:
    """Return the reviewed Phase-34 built-in binding boundary.

    This inventory is evidence-driven. A Phase-32 adapter is bindable only when
    a reviewed dispatch view and the current binder registry both contain the
    exact adapter/contract relation and every native request input can be
    reconstructed without invention or backend invocation.
    """

    rows = (
        BuiltinBindingReview(
            "originforge.build.integration",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 63 exposes build.integration@1 with an audited Workspace input and bounded sandbox verification; it never grants Task acceptance or release authority",
        ),
        BuiltinBindingReview(
            "originforge.code.bounded-retry",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase-33 exposes code.bounded-retry@1 and Phase-34 reconstructs the exact zero-ref BoundedRetryPolicy.drive input projection",
        ),
        BuiltinBindingReview(
            "originforge.pixelorama.export",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase-48A exposes pixelorama.spritesheet-export@1 and Phase-48B reconstructs the exact one-Artifact metadata-only Pixelorama export request without opening bytes or selecting editor authority",
        ),
        BuiltinBindingReview(
            "originforge.blender.model3d",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase-51B exposes blender.export-glb@1 and reconstructs the exact protected MODEL3D_REQUEST semantic projection without runtime IDs, paths, process authority, or backend invocation",
        ),
        BuiltinBindingReview(
            "originforge.image.generate",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 57 image integration reconstructs the exact local-only workflow projection and promotes ComfyUI through the governed claim/execution/output-binding chain",
        ),
        BuiltinBindingReview(
            "originforge.vision.inspect",
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_COMPLETE_VISION_REQUEST_INPUT",
            "core Artifact metadata alone does not reconstruct the complete governed vision request/model input relation",
        ),
        BuiltinBindingReview(
            "originforge.audio.ffmpeg",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 62 resolves a role-specific protected PCM16 WAV source projection and promotes FFmpeg through the governed claim/execution/output-binding chain",
        ),
        BuiltinBindingReview(
            "originforge.pixelorama.source",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 64 reconstructs the exact typed Pixelorama source/animation request from one current immutable accepted-design input; execution and output-binding recovery remain downstream",
        ),
        BuiltinBindingReview(
            "originforge.audio.piper",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 59 reconstructs the exact Piper speech projection, assembles configured local infrastructure, and persists v25 output evidence with no-replay recovery",
        ),
        BuiltinBindingReview(
            "originforge.runtime.observe",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 60 resolves the exact protected OBS request and persists evidence-only output bindings with no-replay recovery",
        ),
        BuiltinBindingReview(
            "originforge.playtest.cooperative",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase 61 resolves the exact protected PLAYSCEN scenario and persists evidence-only output bindings with no-replay recovery",
        ),
        BuiltinBindingReview(
            "originforge.simulation.deterministic",
            BuiltinBindingReviewStatus.BINDABLE,
            None,
            "Phase-47A exposes simulation.deterministic@1 on the simulation-only Phase-32 view and Phase-47B reconstructs the exact zero-ref SimulationService.execute request projection",
        ),
    )

    phase32 = build_builtin_capability_catalog()
    code_dispatch_catalog = build_builtin_dispatch_catalog(phase32)
    build_phase32 = CapabilityCatalog.create(
        (phase32.capability("build.integration"),),
        (phase32.adapter("originforge.build.integration"),),
    )
    build_dispatch_catalog = build_builtin_dispatch_catalog(build_phase32)
    simulation_phase32 = CapabilityCatalog.create(
        (phase32.capability("simulation.run"),),
        (phase32.adapter("originforge.simulation.deterministic"),),
    )
    simulation_dispatch_catalog = build_builtin_dispatch_catalog(simulation_phase32)
    pixelorama_phase32 = CapabilityCatalog.create(
        (phase32.capability("media.2d.export"),),
        (phase32.adapter("originforge.pixelorama.export"),),
    )
    pixelorama_dispatch_catalog = build_builtin_dispatch_catalog(pixelorama_phase32)
    pixelorama_source_phase32 = CapabilityCatalog.create(
        (phase32.capability("media.2d.source"),),
        (phase32.adapter("originforge.pixelorama.source"),),
    )
    pixelorama_source_dispatch_catalog = build_builtin_dispatch_catalog(
        pixelorama_source_phase32
    )
    blender_phase32 = CapabilityCatalog.create(
        (phase32.capability("media.3d.blender"),),
        (phase32.adapter("originforge.blender.model3d"),),
    )
    blender_dispatch_catalog = build_builtin_dispatch_catalog(blender_phase32)
    image_phase32 = CapabilityCatalog.create(
        (phase32.capability("image.generate"),),
        (phase32.adapter("originforge.image.generate"),),
    )
    image_dispatch_catalog = build_builtin_dispatch_catalog(image_phase32)
    ffmpeg_phase32 = CapabilityCatalog.create(
        (phase32.capability("media.audio.process"),),
        (phase32.adapter("originforge.audio.ffmpeg"),),
    )
    ffmpeg_dispatch_catalog = build_builtin_dispatch_catalog(ffmpeg_phase32)
    piper_phase32 = CapabilityCatalog.create(
        (phase32.capability("media.audio.tts"),),
        (phase32.adapter("originforge.audio.piper"),),
    )
    piper_dispatch_catalog = build_builtin_dispatch_catalog(piper_phase32)
    playtest_phase32 = CapabilityCatalog.create(
        (phase32.capability("runtime.playtest"),),
        (phase32.adapter("originforge.playtest.cooperative"),),
    )
    playtest_dispatch_catalog = build_builtin_dispatch_catalog(playtest_phase32)
    runtime_phase32 = CapabilityCatalog.create(
        (phase32.capability("runtime.observe"),),
        (phase32.adapter("originforge.runtime.observe"),),
    )
    runtime_dispatch_catalog = build_builtin_dispatch_catalog(runtime_phase32)
    resolver_registry = build_dispatch_input_resolver_registry()
    binder_registry = build_builtin_dispatch_binder_registry()

    reviewed_ids = {value.adapter_id for value in rows}
    if reviewed_ids != set(phase32.adapter_ids):
        raise RuntimeError("Phase-34 built-in binding review does not cover exact Phase-32 adapter inventory")

    bindable_ids = {
        value.adapter_id
        for value in rows
        if value.status is BuiltinBindingReviewStatus.BINDABLE
    }
    reviewed_contracts = (
        *code_dispatch_catalog.contracts,
        *build_dispatch_catalog.contracts,
        *simulation_dispatch_catalog.contracts,
        *pixelorama_dispatch_catalog.contracts,
        *pixelorama_source_dispatch_catalog.contracts,
        *blender_dispatch_catalog.contracts,
        *image_dispatch_catalog.contracts,
        *ffmpeg_dispatch_catalog.contracts,
        *piper_dispatch_catalog.contracts,
        *runtime_dispatch_catalog.contracts,
        *playtest_dispatch_catalog.contracts,
    )
    contract_by_adapter = {value.adapter_id: value for value in reviewed_contracts}
    if len(contract_by_adapter) != len(reviewed_contracts):
        raise RuntimeError("Phase-34 reviewed dispatch views contain duplicate adapter authority")
    contract_ids = set(contract_by_adapter)
    binder_ids = {value.adapter_id for value in binder_registry.descriptors}
    if bindable_ids != contract_ids or bindable_ids != binder_ids:
        raise RuntimeError("Phase-34 bindable review drifted from trusted dispatch/binder inventory")

    for descriptor in binder_registry.descriptors:
        contract = contract_by_adapter.get(descriptor.adapter_id)
        if contract is None or descriptor.dispatch_contract_id != contract.contract_id:
            raise RuntimeError("Phase-34 binder contract drifted from reviewed dispatch views")

    resolved_ref_types = {
        claim.ref_type
        for descriptor in resolver_registry.descriptors
        for claim in descriptor.claims
    }
    if not resolved_ref_types:
        raise RuntimeError("Phase-34 trusted resolver inventory unexpectedly empty")

    return tuple(sorted(rows, key=lambda value: value.adapter_id))
