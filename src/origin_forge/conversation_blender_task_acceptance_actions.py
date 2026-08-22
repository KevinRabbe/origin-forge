from __future__ import annotations

from dataclasses import dataclass

from .conversation_live import ConversationLiveState
from .ids import IdKind, validate_id
from .production_blender_adoption_receipt import (
    BlenderProductionAdoptionReceiptError,
    BlenderProductionAdoptionStatus,
    read_blender_production_adoption_receipt,
)
from .production_blender_dispatch_output_binding import (
    BlenderDispatchOutputBindingError,
    read_blender_dispatch_output_binding,
)
from .production_blender_dispatch_output_discovery import (
    BlenderDispatchOutputDiscoveryError,
    discover_blender_dispatch_output_executions_for_task_readonly,
)
from .production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
    inspect_blender_production_task_acceptance_currentness_readonly,
)
from .production_dispatch_read import DispatchReadError, read_dispatch_binding
from .runtime import OriginForgeRuntime


MAX_CONVERSATION_BLENDER_ACCEPTANCE_ACTIONS = 8
_MAX_DETAIL_CHARS = 240


class ConversationBlenderTaskAcceptanceActionError(RuntimeError):
    pass


def _safe_detail(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConversationBlenderTaskAcceptanceActionError("action detail is invalid")
    value = value[:_MAX_DETAIL_CHARS]
    if any(ord(character) < 0x20 and character not in "\t\n\r" for character in value):
        raise ConversationBlenderTaskAcceptanceActionError("action detail is invalid")
    return value


@dataclass(frozen=True)
class BlenderTaskAcceptanceActionView:
    conversation_session_id: str
    task_id: str
    execution_id: str | None
    status: BlenderProductionTaskAcceptanceCurrentnessStatus
    acceptance_eligible: bool
    accepted: bool
    adopted_artifact_id: str | None
    adopted_destination_path: str | None
    accepted_content_hash: str | None
    accepted_byte_count: int | None
    model3d_request_id: str | None
    task_verification_id: str | None
    task_revision: int | None
    detail: str | None

    def __post_init__(self) -> None:
        if not validate_id(self.conversation_session_id, IdKind.CONVERSATION_SESSION):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action conversation_session_id is invalid"
            )
        if not validate_id(self.task_id, IdKind.TASK):
            raise ConversationBlenderTaskAcceptanceActionError("action task_id is invalid")
        if self.execution_id is not None and not validate_id(
            self.execution_id, IdKind.DISPATCH_EXECUTION
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action execution_id is invalid"
            )
        if type(self.acceptance_eligible) is not bool or type(self.accepted) is not bool:
            raise ConversationBlenderTaskAcceptanceActionError(
                "action acceptance flags are invalid"
            )
        if self.adopted_artifact_id is not None and not validate_id(
            self.adopted_artifact_id, IdKind.ARTIFACT
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action adopted_artifact_id is invalid"
            )
        if self.model3d_request_id is not None and not validate_id(
            self.model3d_request_id, IdKind.MODEL3D_REQUEST
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action model3d_request_id is invalid"
            )
        if self.task_verification_id is not None and not validate_id(
            self.task_verification_id, IdKind.VERIFICATION
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action task_verification_id is invalid"
            )
        if self.adopted_destination_path is not None and (
            not isinstance(self.adopted_destination_path, str)
            or not self.adopted_destination_path
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action adopted_destination_path is invalid"
            )
        if self.accepted_content_hash is not None and (
            not isinstance(self.accepted_content_hash, str)
            or not self.accepted_content_hash.startswith("sha256:")
            or len(self.accepted_content_hash) != 71
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action accepted_content_hash is invalid"
            )
        if self.accepted_byte_count is not None and (
            type(self.accepted_byte_count) is not int or self.accepted_byte_count <= 0
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action accepted_byte_count is invalid"
            )
        if self.task_revision is not None and (
            type(self.task_revision) is not int or self.task_revision < 0
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action task_revision is invalid"
            )
        _safe_detail(self.detail)

    def to_dict(self) -> dict[str, object]:
        return {
            "conversation_session_id": self.conversation_session_id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "acceptance_eligible": self.acceptance_eligible,
            "accepted": self.accepted,
            "adopted_artifact_id": self.adopted_artifact_id,
            "adopted_destination_path": self.adopted_destination_path,
            "accepted_content_hash": self.accepted_content_hash,
            "accepted_byte_count": self.accepted_byte_count,
            "model3d_request_id": self.model3d_request_id,
            "task_verification_id": self.task_verification_id,
            "task_revision": self.task_revision,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ConversationBlenderTaskAcceptanceActions:
    conversation_session_id: str
    actions: tuple[BlenderTaskAcceptanceActionView, ...]
    actions_truncated: bool
    task_references_truncated: bool

    def __post_init__(self) -> None:
        if not validate_id(self.conversation_session_id, IdKind.CONVERSATION_SESSION):
            raise ConversationBlenderTaskAcceptanceActionError(
                "action collection conversation_session_id is invalid"
            )
        if len(self.actions) > MAX_CONVERSATION_BLENDER_ACCEPTANCE_ACTIONS:
            raise ConversationBlenderTaskAcceptanceActionError(
                "action collection exceeds fixed action bound"
            )
        if type(self.actions_truncated) is not bool or type(
            self.task_references_truncated
        ) is not bool:
            raise ConversationBlenderTaskAcceptanceActionError(
                "action collection truncation flags are invalid"
            )
        for action in self.actions:
            if action.conversation_session_id != self.conversation_session_id:
                raise ConversationBlenderTaskAcceptanceActionError(
                    "action belongs to another conversation"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "conversation_session_id": self.conversation_session_id,
            "actions": [action.to_dict() for action in self.actions],
            "actions_truncated": self.actions_truncated,
            "task_references_truncated": self.task_references_truncated,
        }


def _conflicting_view(
    live_state: ConversationLiveState,
    task_id: str,
    *,
    execution_id: str | None = None,
    adopted_artifact_id: str | None = None,
    task_verification_id: str | None = None,
    task_revision: int | None = None,
    detail: str,
) -> BlenderTaskAcceptanceActionView:
    return BlenderTaskAcceptanceActionView(
        conversation_session_id=live_state.session.id,
        task_id=task_id,
        execution_id=execution_id,
        status=BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING,
        acceptance_eligible=False,
        accepted=False,
        adopted_artifact_id=adopted_artifact_id,
        adopted_destination_path=None,
        accepted_content_hash=None,
        accepted_byte_count=None,
        model3d_request_id=None,
        task_verification_id=task_verification_id,
        task_revision=task_revision,
        detail=_safe_detail(detail),
    )


def _status_detail(
    status: BlenderProductionTaskAcceptanceCurrentnessStatus,
) -> str | None:
    if status is BlenderProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED:
        return None
    if status is BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION:
        return "Acceptance is durable; the Task transition requires an explicit operator recovery action."
    if status is BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED:
        return "The exact Blender production Task is already accepted and succeeded."
    return "Blender acceptance authority is stale or conflicting and is not actionable."


def _exact_view(
    runtime: OriginForgeRuntime,
    live_state: ConversationLiveState,
    task_id: str,
    execution_id: str,
) -> BlenderTaskAcceptanceActionView:
    currentness = inspect_blender_production_task_acceptance_currentness_readonly(
        runtime, execution_id
    )
    if currentness.task_id is not None and currentness.task_id != task_id:
        return _conflicting_view(
            live_state,
            task_id,
            execution_id=execution_id,
            detail="Blender execution identity conflicts with the conversation Task relation.",
        )
    if currentness.status is BlenderProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING:
        return _conflicting_view(
            live_state,
            task_id,
            execution_id=execution_id,
            adopted_artifact_id=currentness.adopted_artifact_id,
            task_verification_id=currentness.task_verification_id,
            task_revision=currentness.task_revision,
            detail=_status_detail(currentness.status) or "Blender acceptance authority is stale.",
        )

    try:
        binding = read_blender_dispatch_output_binding(runtime, execution_id)
        adoption = read_blender_production_adoption_receipt(runtime, execution_id)
        dispatch_binding = read_dispatch_binding(runtime, binding.dispatch_binding_id)
        projection = dispatch_binding.request_projection
        model3d_request_id = (
            projection.get("model3d_request_id") if isinstance(projection, dict) else None
        )
        if (
            binding.task_id != task_id
            or adoption.status is not BlenderProductionAdoptionStatus.PUBLISHED
            or adoption.adopted_artifact_id is None
            or adoption.execution_id != execution_id
            or not isinstance(model3d_request_id, str)
            or not validate_id(model3d_request_id, IdKind.MODEL3D_REQUEST)
        ):
            raise ConversationBlenderTaskAcceptanceActionError(
                "exact Blender action relation drifted during projection"
            )
    except (
        BlenderDispatchOutputBindingError,
        BlenderProductionAdoptionReceiptError,
        DispatchReadError,
        ConversationBlenderTaskAcceptanceActionError,
        KeyError,
        ValueError,
        RuntimeError,
        OSError,
    ):
        return _conflicting_view(
            live_state,
            task_id,
            execution_id=execution_id,
            adopted_artifact_id=currentness.adopted_artifact_id,
            task_verification_id=currentness.task_verification_id,
            task_revision=currentness.task_revision,
            detail="Blender acceptance relation changed while the read-only action view was rebuilt.",
        )

    return BlenderTaskAcceptanceActionView(
        conversation_session_id=live_state.session.id,
        task_id=task_id,
        execution_id=execution_id,
        status=currentness.status,
        acceptance_eligible=currentness.acceptance_eligible,
        accepted=currentness.accepted,
        adopted_artifact_id=adoption.adopted_artifact_id,
        adopted_destination_path=adoption.destination_path,
        accepted_content_hash="sha256:" + binding.output_content_hash,
        accepted_byte_count=binding.output_byte_count,
        model3d_request_id=model3d_request_id,
        task_verification_id=currentness.task_verification_id,
        task_revision=currentness.task_revision,
        detail=_safe_detail(_status_detail(currentness.status)),
    )


def project_conversation_blender_task_acceptance_actions_readonly(
    runtime: OriginForgeRuntime,
    live_state: ConversationLiveState,
) -> ConversationBlenderTaskAcceptanceActions:
    """Compose bounded Phase-53 action status only from durable conversation Task refs."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(live_state, ConversationLiveState):
        raise TypeError("live_state must be a ConversationLiveState")
    if live_state.session.project_id != runtime.project_id():
        raise ConversationBlenderTaskAcceptanceActionError(
            "conversation belongs to another project"
        )

    actions: list[BlenderTaskAcceptanceActionView] = []
    actions_truncated = False
    for task in live_state.task_telemetry:
        task_id = task.task_id
        try:
            execution_ids = discover_blender_dispatch_output_executions_for_task_readonly(
                runtime, task_id
            )
        except BlenderDispatchOutputDiscoveryError:
            candidate = _conflicting_view(
                live_state,
                task_id,
                detail="Blender production relation cannot be reconstructed safely.",
            )
        else:
            if not execution_ids:
                continue
            if len(execution_ids) != 1:
                candidate = _conflicting_view(
                    live_state,
                    task_id,
                    detail="Multiple Blender production executions are linked to this conversation Task.",
                )
            else:
                try:
                    candidate = _exact_view(
                        runtime, live_state, task_id, execution_ids[0]
                    )
                except (RuntimeError, KeyError, ValueError, OSError):
                    candidate = _conflicting_view(
                        live_state,
                        task_id,
                        execution_id=execution_ids[0],
                        detail="Blender acceptance currentness cannot be reconstructed safely.",
                    )

        if len(actions) >= MAX_CONVERSATION_BLENDER_ACCEPTANCE_ACTIONS:
            actions_truncated = True
            break
        actions.append(candidate)

    return ConversationBlenderTaskAcceptanceActions(
        conversation_session_id=live_state.session.id,
        actions=tuple(actions),
        actions_truncated=actions_truncated,
        task_references_truncated=live_state.task_references_truncated,
    )
