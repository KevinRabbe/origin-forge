from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_capability_builtin import build_builtin_capability_catalog
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
    the current Phase-33 dispatch catalog and the current Phase-34 binder
    registry both contain the exact adapter/contract relation and every native
    request input can be reconstructed without invention or backend invocation.
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
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_COMPLETE_TYPED_PIXELORAMA_INPUT",
            "34C admits no exact Pixelorama project/profile resolver, so the Phase-33 dispatch contract remains intentionally absent",
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
            BuiltinBindingReviewStatus.DEFERRED,
            "NO_DIRECT_SIMULATION_SPEC_READER",
            "34C found SIMSPEC data inside simulation workspaces/artifacts with no direct exact SIMSPEC reader",
        ),
    )

    phase32 = build_builtin_capability_catalog()
    dispatch_catalog = build_builtin_dispatch_catalog(phase32)
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
    contract_ids = {value.adapter_id for value in dispatch_catalog.contracts}
    binder_ids = {value.adapter_id for value in binder_registry.descriptors}
    if bindable_ids != contract_ids or bindable_ids != binder_ids:
        raise RuntimeError("Phase-34 bindable review drifted from trusted dispatch/binder inventory")

    for descriptor in binder_registry.descriptors:
        contract = dispatch_catalog.contract_for_adapter(descriptor.adapter_id)
        if descriptor.dispatch_contract_id != contract.contract_id:
            raise RuntimeError("Phase-34 binder contract drifted from Phase-33 dispatch catalog")

    resolved_ref_types = {
        claim.ref_type
        for descriptor in resolver_registry.descriptors
        for claim in descriptor.claims
    }
    if not resolved_ref_types:
        raise RuntimeError("Phase-34 trusted resolver inventory unexpectedly empty")

    return tuple(sorted(rows, key=lambda value: value.adapter_id))
