from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .conversation_blender_task_acceptance_actions import (
    ConversationBlenderTaskAcceptanceActionError,
    project_conversation_blender_task_acceptance_actions_readonly,
)
from .conversation_live import ConversationLiveError, read_conversation_live_state
from .ids import IdKind, validate_id
from .production_blender_task_acceptance_currentness import (
    BlenderProductionTaskAcceptanceCurrentnessStatus,
)
from .production_blender_task_acceptor import (
    BlenderProductionTaskAcceptorError,
    GovernedBlenderProductionTaskAcceptanceResult,
    GovernedBlenderProductionTaskAcceptor,
)
from .runtime import OriginForgeRuntime


LOCAL_GUI_BLENDER_ACCEPTANCE_ACTOR_ID = "operator.local-gui.blender-task-acceptance"
_MAX_FAILURE_DETAIL_CHARS = 240


class ConversationBlenderTaskAcceptanceOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    RECOVERED = "RECOVERED"
    REPLAYED = "REPLAYED"


class ConversationBlenderTaskAcceptanceFailureCode(StrEnum):
    INVALID_CONVERSATION_ID = "INVALID_CONVERSATION_ID"
    INVALID_EXECUTION_ID = "INVALID_EXECUTION_ID"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    EXECUTION_NOT_LINKED = "EXECUTION_NOT_LINKED"
    STALE_OR_CONFLICTING = "STALE_OR_CONFLICTING"
    ACCEPTANCE_FAILED = "ACCEPTANCE_FAILED"


def _bounded_detail(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("failure detail must be non-empty text")
    value = value[:_MAX_FAILURE_DETAIL_CHARS]
    if any(ord(character) < 0x20 and character not in "\t\n\r" for character in value):
        raise ValueError("failure detail contains control characters")
    return value


class ConversationBlenderTaskAcceptanceRejected(RuntimeError):
    def __init__(
        self,
        code: ConversationBlenderTaskAcceptanceFailureCode,
        detail: str,
    ) -> None:
        if not isinstance(code, ConversationBlenderTaskAcceptanceFailureCode):
            raise TypeError("code must be a ConversationBlenderTaskAcceptanceFailureCode")
        self.code = code
        self.detail = _bounded_detail(detail)
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ConversationBlenderTaskAcceptanceResult:
    conversation_session_id: str
    outcome: ConversationBlenderTaskAcceptanceOutcome
    execution_id: str
    task_id: str
    adopted_artifact_id: str
    adoption_verification_id: str
    task_verification_id: str
    accepted_content_hash: str
    accepted_byte_count: int
    accepted_destination_path: str
    task_revision_at_acceptance: int
    task_revision: int
    task_status: str
    accepted_at: str
    production_task_verified: bool = True
    semantic_geometry_verified: bool = True
    canonical_asset_adopted: bool = True
    provenance_signed: bool = False
    release_authorized: bool = False

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.conversation_session_id, IdKind.CONVERSATION_SESSION, "conversation_session_id"),
            (self.execution_id, IdKind.DISPATCH_EXECUTION, "execution_id"),
            (self.task_id, IdKind.TASK, "task_id"),
            (self.adopted_artifact_id, IdKind.ARTIFACT, "adopted_artifact_id"),
            (self.adoption_verification_id, IdKind.VERIFICATION, "adoption_verification_id"),
            (self.task_verification_id, IdKind.VERIFICATION, "task_verification_id"),
        ):
            if not isinstance(value, str) or not validate_id(value, kind):
                raise ValueError(f"{label} must be a valid {kind.value} ID")
        if not isinstance(self.outcome, ConversationBlenderTaskAcceptanceOutcome):
            raise TypeError("outcome must be a ConversationBlenderTaskAcceptanceOutcome")
        if (
            not isinstance(self.accepted_content_hash, str)
            or not self.accepted_content_hash.startswith("sha256:")
            or len(self.accepted_content_hash) != 71
        ):
            raise ValueError("accepted_content_hash must be a canonical SHA-256 hash")
        if type(self.accepted_byte_count) is not int or self.accepted_byte_count <= 0:
            raise ValueError("accepted_byte_count must be a positive integer")
        if not isinstance(self.accepted_destination_path, str) or not self.accepted_destination_path:
            raise ValueError("accepted_destination_path must be non-empty text")
        if (
            type(self.task_revision_at_acceptance) is not int
            or self.task_revision_at_acceptance < 0
            or type(self.task_revision) is not int
            or self.task_revision < 0
        ):
            raise ValueError("Task revisions must be non-negative integers")
        if self.task_status != "SUCCEEDED":
            raise ValueError("accepted Task status must be SUCCEEDED")
        if not isinstance(self.accepted_at, str) or not self.accepted_at:
            raise ValueError("accepted_at must be non-empty text")
        if (
            self.production_task_verified is not True
            or self.semantic_geometry_verified is not True
            or self.canonical_asset_adopted is not True
            or self.provenance_signed is not False
            or self.release_authorized is not False
        ):
            raise ValueError("accepted authority flags are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "conversation_session_id": self.conversation_session_id,
            "outcome": self.outcome.value,
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "adoption_verification_id": self.adoption_verification_id,
            "task_verification_id": self.task_verification_id,
            "accepted_content_hash": self.accepted_content_hash,
            "accepted_byte_count": self.accepted_byte_count,
            "accepted_destination_path": self.accepted_destination_path,
            "task_revision_at_acceptance": self.task_revision_at_acceptance,
            "task_revision": self.task_revision,
            "task_status": self.task_status,
            "accepted_at": self.accepted_at,
            "production_task_verified": self.production_task_verified,
            "semantic_geometry_verified": self.semantic_geometry_verified,
            "canonical_asset_adopted": self.canonical_asset_adopted,
            "provenance_signed": self.provenance_signed,
            "release_authorized": self.release_authorized,
        }


def _reject(
    code: ConversationBlenderTaskAcceptanceFailureCode,
    detail: str,
) -> None:
    raise ConversationBlenderTaskAcceptanceRejected(code, detail)


def _outcome_for_status(
    status: BlenderProductionTaskAcceptanceCurrentnessStatus,
) -> ConversationBlenderTaskAcceptanceOutcome:
    if status is BlenderProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED:
        return ConversationBlenderTaskAcceptanceOutcome.ACCEPTED
    if (
        status
        is BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION
    ):
        return ConversationBlenderTaskAcceptanceOutcome.RECOVERED
    if status is BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED:
        return ConversationBlenderTaskAcceptanceOutcome.REPLAYED
    _reject(
        ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
        "Blender acceptance authority is stale or conflicting.",
    )
    raise AssertionError("unreachable")


def _project_result(
    conversation_session_id: str,
    outcome: ConversationBlenderTaskAcceptanceOutcome,
    accepted: GovernedBlenderProductionTaskAcceptanceResult,
) -> ConversationBlenderTaskAcceptanceResult:
    return ConversationBlenderTaskAcceptanceResult(
        conversation_session_id=conversation_session_id,
        outcome=outcome,
        execution_id=accepted.execution_id,
        task_id=accepted.task_id,
        adopted_artifact_id=accepted.adopted_artifact_id,
        adoption_verification_id=accepted.adoption_verification_id,
        task_verification_id=accepted.task_verification_id,
        accepted_content_hash=accepted.accepted_content_hash,
        accepted_byte_count=accepted.accepted_byte_count,
        accepted_destination_path=accepted.accepted_destination_path,
        task_revision_at_acceptance=accepted.task_revision_at_acceptance,
        task_revision=accepted.task_revision,
        task_status=accepted.task_status,
        accepted_at=accepted.accepted_at,
    )


def accept_conversation_blender_task(
    runtime: OriginForgeRuntime,
    conversation_session_id: str,
    execution_id: str,
) -> ConversationBlenderTaskAcceptanceResult:
    """Accept only one exact Blender execution already linked to bounded conversation state."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(conversation_session_id, str) or not validate_id(
        conversation_session_id, IdKind.CONVERSATION_SESSION
    ):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.INVALID_CONVERSATION_ID,
            "conversation_session_id must be a canonical CONV ID.",
        )
    if not isinstance(execution_id, str) or not validate_id(
        execution_id, IdKind.DISPATCH_EXECUTION
    ):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.INVALID_EXECUTION_ID,
            "execution_id must be a canonical DISPEXEC ID.",
        )

    try:
        live_state = read_conversation_live_state(runtime, conversation_session_id)
    except KeyError:
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.CONVERSATION_NOT_FOUND,
            "The selected conversation does not exist in this project.",
        )
    except (ConversationLiveError, RuntimeError, ValueError, OSError):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
            "The selected conversation cannot be reconstructed safely.",
        )

    try:
        projected = project_conversation_blender_task_acceptance_actions_readonly(
            runtime,
            live_state,
        )
    except (ConversationBlenderTaskAcceptanceActionError, RuntimeError, KeyError, ValueError, OSError):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
            "Blender acceptance actions cannot be reconstructed safely.",
        )

    matches = tuple(
        action for action in projected.actions if action.execution_id == execution_id
    )
    if len(matches) != 1:
        if projected.actions_truncated or projected.task_references_truncated or any(
            action.execution_id is None for action in projected.actions
        ):
            _reject(
                ConversationBlenderTaskAcceptanceFailureCode.STALE_OR_CONFLICTING,
                "The bounded conversation action relation is incomplete or ambiguous.",
            )
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.EXECUTION_NOT_LINKED,
            "The requested Blender execution is not an exact action for this conversation.",
        )
    action = matches[0]
    outcome = _outcome_for_status(action.status)

    try:
        accepted = GovernedBlenderProductionTaskAcceptor(runtime).accept(
            execution_id,
            actor_id=LOCAL_GUI_BLENDER_ACCEPTANCE_ACTOR_ID,
        )
    except (BlenderProductionTaskAcceptorError, RuntimeError, KeyError, ValueError, OSError):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.ACCEPTANCE_FAILED,
            "Governed Blender Task acceptance did not complete safely.",
        )

    if (
        accepted.execution_id != execution_id
        or accepted.task_id != action.task_id
        or accepted.adopted_artifact_id != action.adopted_artifact_id
        or accepted.accepted_destination_path != action.adopted_destination_path
        or accepted.accepted_content_hash != action.accepted_content_hash
        or accepted.accepted_byte_count != action.accepted_byte_count
    ):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.ACCEPTANCE_FAILED,
            "Governed Blender Task acceptance returned a conflicting production identity.",
        )
    if outcome in {
        ConversationBlenderTaskAcceptanceOutcome.ACCEPTED,
        ConversationBlenderTaskAcceptanceOutcome.RECOVERED,
    } and (
        action.task_revision is None
        or accepted.task_revision_at_acceptance != action.task_revision
        or accepted.task_revision != action.task_revision + 1
    ):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.ACCEPTANCE_FAILED,
            "Governed Blender Task acceptance returned an unexpected Task revision.",
        )
    if outcome is ConversationBlenderTaskAcceptanceOutcome.REPLAYED and (
        action.task_revision is None or accepted.task_revision != action.task_revision
    ):
        _reject(
            ConversationBlenderTaskAcceptanceFailureCode.ACCEPTANCE_FAILED,
            "Governed Blender Task replay returned an unexpected Task revision.",
        )

    return _project_result(conversation_session_id, outcome, accepted)
