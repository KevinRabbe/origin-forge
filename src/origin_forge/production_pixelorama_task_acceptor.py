from __future__ import annotations

from dataclasses import dataclass

from .ids import IdKind, validate_id
from .production_pixelorama_adoption_receipt import (
    read_pixelorama_production_adoption_receipt,
)
from .production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from .production_pixelorama_task_acceptance import (
    PixeloramaProductionTaskAcceptanceReceipt,
    publish_pixelorama_production_task_acceptance,
    read_pixelorama_production_task_acceptance,
)
from .production_pixelorama_task_acceptance_currentness import (
    PixeloramaProductionTaskAcceptanceCurrentness,
    PixeloramaProductionTaskAcceptanceCurrentnessStatus,
    inspect_pixelorama_production_task_acceptance_currentness_readonly,
)
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .service import StaleRevision
from .state import TaskStatus


class PixeloramaProductionTaskAcceptorError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernedPixeloramaProductionTaskAcceptanceResult:
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

    def to_dict(self) -> dict[str, object]:
        return {
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
            "production_task_verified": True,
            "semantic_visual_quality_verified": True,
            "acceptance_authority": "HUMAN_OPERATOR",
            "canonical_asset_adopted": True,
            "provenance_signed": False,
            "release_authorized": False,
        }


def _result_from_receipt(
    receipt: PixeloramaProductionTaskAcceptanceReceipt,
    currentness: PixeloramaProductionTaskAcceptanceCurrentness,
) -> GovernedPixeloramaProductionTaskAcceptanceResult:
    if (
        currentness.status
        is not PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
        or currentness.task_revision is None
    ):
        raise PixeloramaProductionTaskAcceptorError(
            "production Task acceptance result requires exact SUCCEEDED currentness"
        )
    return GovernedPixeloramaProductionTaskAcceptanceResult(
        execution_id=receipt.execution_id,
        task_id=receipt.task_id,
        adopted_artifact_id=receipt.adopted_artifact_id,
        adoption_verification_id=receipt.adoption_verification_id,
        task_verification_id=receipt.task_verification_id,
        accepted_content_hash=receipt.accepted_content_hash,
        accepted_byte_count=receipt.accepted_byte_count,
        accepted_destination_path=receipt.accepted_destination_path,
        task_revision_at_acceptance=receipt.task_revision_at_acceptance,
        task_revision=currentness.task_revision,
        task_status=TaskStatus.SUCCEEDED.value,
        accepted_at=receipt.accepted_at,
    )


class GovernedPixeloramaProductionTaskAcceptor:
    """Explicitly accept one exact Phase-49 Pixelorama production result."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    def inspect(
        self,
        execution_id: str,
    ) -> PixeloramaProductionTaskAcceptanceCurrentness:
        return inspect_pixelorama_production_task_acceptance_currentness_readonly(
            self.runtime,
            execution_id,
        )

    def accept(
        self,
        execution_id: str,
        *,
        actor_id: str | None = None,
    ) -> GovernedPixeloramaProductionTaskAcceptanceResult:
        if not isinstance(execution_id, str) or not validate_id(
            execution_id, IdKind.DISPATCH_EXECUTION
        ):
            raise ValueError("execution_id must be a DISPEXEC ID")

        currentness = self.inspect(execution_id)
        if (
            currentness.status
            is PixeloramaProductionTaskAcceptanceCurrentnessStatus.STALE_OR_CONFLICTING
        ):
            raise PixeloramaProductionTaskAcceptorError(
                "Pixelorama production Task is not acceptance current: "
                + (currentness.detail or currentness.status.value)
            )

        if (
            currentness.status
            is PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
        ):
            receipt = read_pixelorama_production_task_acceptance(
                self.runtime,
                execution_id,
            )
            return _result_from_receipt(receipt, currentness)

        if (
            currentness.status
            not in {
                PixeloramaProductionTaskAcceptanceCurrentnessStatus.NOT_ACCEPTED,
                PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION,
            }
            or currentness.task_revision is None
        ):
            raise PixeloramaProductionTaskAcceptorError(
                "Pixelorama production Task is not eligible for explicit acceptance"
            )

        binding = read_pixelorama_dispatch_output_binding(self.runtime, execution_id)
        adoption = read_pixelorama_production_adoption_receipt(
            self.runtime,
            execution_id,
        )
        receipt = publish_pixelorama_production_task_acceptance(
            self.runtime,
            binding,
            adoption,
            task_revision_at_acceptance=currentness.task_revision,
            actor_id=actor_id,
        )

        pending = self.inspect(execution_id)
        if (
            pending.status
            is not PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_PENDING_TASK_TRANSITION
            or pending.task_verification_id != receipt.task_verification_id
            or pending.task_revision != receipt.task_revision_at_acceptance
        ):
            raise PixeloramaProductionTaskAcceptorError(
                "durable production Task acceptance did not remain current before terminalization: "
                + (pending.detail or pending.status.value)
            )

        try:
            self.runtime.transition_task(
                binding.task_id,
                TaskStatus.SUCCEEDED,
                expected_revision=receipt.task_revision_at_acceptance,
            )
        except StaleRevision as exc:
            raced = self.inspect(execution_id)
            if (
                raced.status
                is PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
            ):
                canonical = read_pixelorama_production_task_acceptance(
                    self.runtime,
                    execution_id,
                )
                return _result_from_receipt(canonical, raced)
            raise PixeloramaProductionTaskAcceptorError(
                "production Task changed concurrently after acceptance publication"
            ) from exc
        except RuntimeInvariantError as exc:
            raise PixeloramaProductionTaskAcceptorError(str(exc)) from exc

        completed = self.inspect(execution_id)
        if (
            completed.status
            is not PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
        ):
            raise PixeloramaProductionTaskAcceptorError(
                "production Task terminalization did not produce exact accepted SUCCEEDED currentness: "
                + (completed.detail or completed.status.value)
            )
        canonical = read_pixelorama_production_task_acceptance(
            self.runtime,
            execution_id,
        )
        return _result_from_receipt(canonical, completed)
