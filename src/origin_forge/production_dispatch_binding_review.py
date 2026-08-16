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
    a reviewed Phase-33 dispatch view and the current Phase-34 binder registry
    both contain the exact adapter/contract relation and every native request
    input can be reconstructed without invention or backend invocation.
    """

    rows = (
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
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_DIRECT_MODEL3D_REQUEST_READER",
            "34C found 3D request/project evidence workspace-bound without a direct protected ID-addressed reader",
        ),
        BuiltinBindingReview(
            "originforge.image.generate",
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_TYPED_IMAGE_WORKFLOW_REF",
            "governed image workflows use bounded workflow tokens rather than a typed infrastructure ref that 34C can resolve exactly",
        ),
        BuiltinBindingReview(
            "originforge.vision.inspect",
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_COMPLETE_VISION_REQUEST_INPUT",
            "core Artifact metadata alone does not reconstruct the complete governed vision request/model input relation",
        ),
        BuiltinBindingReview(
            "originforge.audio.ffmpeg",
            BuiltinBindingReviewStatus.DEFERRED,
            "AUDIO_SOURCE_STRUCTURE_NOT_RESOLVED",
            "Artifact plus AUDIO_PROFILE resolution is insufficient: AudioSourceRef also requires exact PCM hash, byte/frame counts, sample rate, and channels not present in the generic Artifact projection",
        ),
        BuiltinBindingReview(
            "originforge.audio.piper",
            BuiltinBindingReviewStatus.DEFERRED,
            "AUDIO_NATIVE_REQUEST_IDENTITY_INCOMPLETE",
            "AUDIO_PROFILE is resolvable, but AudioOperationRequest still requires execution-owned operation/workspace identity and Phase-33 has no complete audio request payload contract",
        ),
        BuiltinBindingReview(
            "originforge.runtime.observe",
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_DIRECT_RUNTIME_OBSERVATION_REQUEST_READER",
            "34C found runtime-observation request data operation/workspace-bound with no direct exact OBS reader",
        ),
        BuiltinBindingReview(
            "originforge.playtest.cooperative",
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_DIRECT_PLAYTEST_SCENARIO_READER",
            "34C found PLAYSCEN data inside playtest workspaces/artifacts with no direct exact PLAYSCEN reader",
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
        *simulation_dispatch_catalog.contracts,
        *pixelorama_dispatch_catalog.contracts,
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
            raise RuntimeError("Phase-34 binder contract drifted from reviewed Phase-33 dispatch views")

    resolved_ref_types = {
        claim.ref_type
        for descriptor in resolver_registry.descriptors
        for claim in descriptor.claims
    }
    if not resolved_ref_types:
        raise RuntimeError("Phase-34 trusted resolver inventory unexpectedly empty")

    return tuple(sorted(rows, key=lambda value: value.adapter_id))
