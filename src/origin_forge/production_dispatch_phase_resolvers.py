from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .audio_profiles import AudioProfileError, AudioProfileStore
from .model3d_requests import Model3DRequestError, Model3DRequestReader
from .production_dispatch_resolution_models import (
    InputResolverDescriptor,
    ResolvedWorkOrderInput,
    ResolverClaim,
)
from .production_dispatch_resolvers import (
    DispatchInputResolutionError,
    WorkOrderInputResolver,
    WorkOrderInputResolverRegistry,
    ArtifactInputResolver,
    DesignRuleInputResolver,
    ProjectEntityInputResolver,
    VerificationInputResolver,
)
from .production_work_order_models import WorkOrderInputRef, WorkOrderRefType, content_hash
from .runtime import OriginForgeRuntime


class PhaseSpecificResolverReviewStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    DEFERRED_NO_TYPED_READER = "DEFERRED_NO_TYPED_READER"
    DEFERRED_NO_TYPED_ID = "DEFERRED_NO_TYPED_ID"
    DEFERRED_NO_EXACT_CLAIM = "DEFERRED_NO_EXACT_CLAIM"


@dataclass(frozen=True)
class PhaseSpecificResolverReview:
    evidence_family: str
    status: PhaseSpecificResolverReviewStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_family": self.evidence_family,
            "status": self.status.value,
            "reason": self.reason,
        }


class AudioProfileInputResolver:
    """Resolve one exact immutable AUDPROF object without backend invocation."""

    _CLAIM = ResolverClaim(
        WorkOrderRefType.AUDIO_PROFILE,
        "AUDPROF-",
        "AUDIO_PROFILE",
        "audio_profile",
    )
    _PROJECTION_CONTRACT = {
        "source": "GovernedAudioProfile.to_dict",
        "hash_semantics": "WorkOrder digest equals AudioProfile.profile_hash digest",
        "revision": None,
        "artifact_bytes": False,
        "executable_path": False,
        "backend_invocation": False,
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.phase.audio-profile@1",
        content_hash(
            {
                "implementation_id": "origin-forge-dispatch-audio-profile-resolver@1",
                "claim": _CLAIM.to_dict(),
                "projection_contract": _PROJECTION_CONTRACT,
            }
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        if not isinstance(ref, WorkOrderInputRef):
            raise TypeError("ref must be a WorkOrderInputRef")
        if (
            ref.ref_type is not WorkOrderRefType.AUDIO_PROFILE
            or not ref.ref_id.startswith("AUDPROF-")
            or ref.role != "audio_profile"
        ):
            raise DispatchInputResolutionError(
                "WorkOrder ref does not match audio-profile resolver claim"
            )
        if ref.revision is not None:
            raise DispatchInputResolutionError(
                "Audio Profile refs are not revision-numbered"
            )

        exact_profile_hash = f"sha256:{ref.content_hash}"
        try:
            profile = AudioProfileStore(runtime).get(ref.ref_id, exact_profile_hash)
        except KeyError as exc:
            raise DispatchInputResolutionError(
                "Audio Profile ref is not available under the exact ID/hash in the current project"
            ) from exc
        except (AudioProfileError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Audio Profile ref failed canonical protected-store revalidation"
            ) from exc
        if profile.profile_hash != exact_profile_hash:
            raise DispatchInputResolutionError("Audio Profile content hash drifted")

        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="AUDIO_PROFILE",
            resolution_class="PROTECTED_AUDIO_PROFILE",
            projection=profile.to_dict(),
        )


class Model3DRequestInputResolver:
    """Resolve one exact immutable MODEL3DREQ object without runtime allocation."""

    _CLAIM = ResolverClaim(
        WorkOrderRefType.MODEL3D_REQUEST,
        "MODEL3DREQ-",
        "MODEL3D_REQUEST",
        "model3d_request",
    )
    _PROJECTION_CONTRACT = {
        "source": "Model3DProductionRequest.to_dict",
        "hash_semantics": "WorkOrder digest equals request_hash digest",
        "revision": None,
        "workspace_scan": False,
        "runtime_allocation": False,
        "executable_probe": False,
        "backend_invocation": False,
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.phase.model3d-request@1",
        content_hash(
            {
                "implementation_id": "origin-forge-dispatch-model3d-request-resolver@1",
                "claim": _CLAIM.to_dict(),
                "projection_contract": _PROJECTION_CONTRACT,
            }
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        if not isinstance(ref, WorkOrderInputRef):
            raise TypeError("ref must be a WorkOrderInputRef")
        if (
            ref.ref_type is not WorkOrderRefType.MODEL3D_REQUEST
            or not ref.ref_id.startswith("MODEL3DREQ-")
            or ref.role != "model3d_request"
        ):
            raise DispatchInputResolutionError(
                "WorkOrder ref does not match MODEL3D request resolver claim"
            )
        if ref.revision is not None:
            raise DispatchInputResolutionError(
                "MODEL3D request refs are not revision-numbered"
            )

        exact_request_hash = f"sha256:{ref.content_hash}"
        try:
            request = Model3DRequestReader(runtime).get(ref.ref_id, exact_request_hash)
        except KeyError as exc:
            raise DispatchInputResolutionError(
                "MODEL3D request is not available under the exact ID/hash in the current project"
            ) from exc
        except (Model3DRequestError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "MODEL3D request failed canonical protected-store revalidation"
            ) from exc
        if request.request_hash != exact_request_hash:
            raise DispatchInputResolutionError("MODEL3D request content hash drifted")

        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="MODEL3D_REQUEST",
            resolution_class="PROTECTED_MODEL3D_REQUEST",
            projection=request.to_dict(),
        )


def phase_specific_resolver_review() -> tuple[PhaseSpecificResolverReview, ...]:
    """Freeze the evidence-driven resolver inclusion/defer boundary.

    A family is supported only when an exact typed ref can reach a canonical,
    project-local, non-creating reader without scanning or path invention.
    """

    rows = (
        PhaseSpecificResolverReview(
            "audio-profile",
            PhaseSpecificResolverReviewStatus.SUPPORTED,
            "AUDPROF is content-addressed and AudioProfileStore.get performs exact non-creating canonical/symlink-safe revalidation",
        ),
        PhaseSpecificResolverReview(
            "media-profile",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_TYPED_ID,
            "Phase 33 names MEDIA_PROFILE but the current infrastructure has no typed durable media-profile ID/store",
        ),
        PhaseSpecificResolverReview(
            "simulation-spec",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_TYPED_READER,
            "SIMSPEC data is persisted inside simulation workspaces/artifacts without a direct exact SIMSPEC reader; resolver scanning is forbidden",
        ),
        PhaseSpecificResolverReview(
            "playtest-scenario",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_TYPED_READER,
            "PLAYSCEN data is persisted inside playtest workspaces/artifacts without a direct exact PLAYSCEN reader; resolver scanning is forbidden",
        ),
        PhaseSpecificResolverReview(
            "image-workflow",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_TYPED_ID,
            "governed image workflow templates use bounded workflow tokens rather than an infrastructure typed-ID prefix claim",
        ),
        PhaseSpecificResolverReview(
            "model3d-request",
            PhaseSpecificResolverReviewStatus.SUPPORTED,
            "MODEL3DREQ is immutable/content-addressed and Model3DRequestReader.get performs exact non-creating canonical/symlink-safe revalidation",
        ),
        PhaseSpecificResolverReview(
            "runtime-observation-request",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_TYPED_READER,
            "OBS request data is operation/workspace-bound and has no direct exact OBS reader; resolver scanning is forbidden",
        ),
        PhaseSpecificResolverReview(
            "phase-specific-evidence",
            PhaseSpecificResolverReviewStatus.DEFERRED_NO_EXACT_CLAIM,
            "PHASE_SPECIFIC_EVIDENCE is not a wildcard escape hatch; no reviewed v1 family has both an exact prefix/role claim and a required non-creating generic reader",
        ),
    )
    return tuple(sorted(rows, key=lambda value: value.evidence_family))


def phase_specific_input_resolvers() -> tuple[WorkOrderInputResolver, ...]:
    return (AudioProfileInputResolver(), Model3DRequestInputResolver())


def build_dispatch_input_resolver_registry() -> WorkOrderInputResolverRegistry:
    """Build the current trusted Phase-34/51 resolver inventory."""

    return WorkOrderInputResolverRegistry(
        (
            ArtifactInputResolver(),
            VerificationInputResolver(),
            ProjectEntityInputResolver(),
            DesignRuleInputResolver(),
            *phase_specific_input_resolvers(),
        )
    )
