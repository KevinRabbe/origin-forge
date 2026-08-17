from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ids import IdKind, validate_id
from .pixelorama_adoption import (
    GovernedPixeloramaAdoptionResult,
    GovernedPixeloramaOutputAdopter,
    PixeloramaAdoptionError,
)
from .production_pixelorama_adoption_receipt import (
    PRODUCTION_ADOPTION_VERIFICATION_TYPE,
    PRODUCTION_ADOPTION_VERIFIER,
    PixeloramaProductionAdoptionReceiptError,
    PixeloramaProductionAdoptionStatus,
    finalize_pixelorama_production_adoption,
    read_pixelorama_production_adoption_receipt,
    reserve_pixelorama_production_adoption,
)
from .production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from .production_pixelorama_dispatch_output_currentness import (
    inspect_pixelorama_dispatch_output_currentness_readonly,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


class PixeloramaProductionAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernedPixeloramaProductionAdoptionResult:
    execution_id: str
    claim_id: str
    task_id: str
    run_id: str
    source_artifact_id: str
    adopted_artifact_id: str
    verification_id: str
    destination_path: str
    content_hash: str
    byte_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "source_artifact_id": self.source_artifact_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "verification_id": self.verification_id,
            "destination_path": self.destination_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
            "existing_asset_overwritten": False,
            "production_dispatch_output_bound": True,
            "production_task_verified": False,
            "semantic_visual_quality_verified": False,
            "provenance_signed": False,
        }


class GovernedPixeloramaProductionOutputAdopter:
    """Create-only publication of one exact terminal production Pixelorama output."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_source_bytes: int = 512 * 1024 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.publisher = GovernedPixeloramaOutputAdopter(
            runtime,
            max_source_bytes=max_source_bytes,
        )

    def _require_eligible(self, execution_id: str, output_artifact_id: str) -> None:
        currentness = inspect_pixelorama_dispatch_output_currentness_readonly(
            self.runtime,
            execution_id,
        )
        if (
            not currentness.adoption_eligible
            or currentness.output_artifact_id != output_artifact_id
            or currentness.production_task_verified
        ):
            detail = currentness.detail or currentness.status.value
            raise PixeloramaProductionAdoptionError(
                f"Pixelorama production output is not adoption eligible: {detail}"
            )

    def _prepared_source(self, binding):
        try:
            artifact = self.publisher._artifact_row(binding.output_artifact_id)
            source = self.publisher._source_path(artifact)
            content_hash, byte_count = self.publisher._stream_hash(source)
        except (KeyError, OSError, PixeloramaAdoptionError) as exc:
            raise PixeloramaProductionAdoptionError(
                "bound Pixelorama production source cannot be prepared for adoption"
            ) from exc
        if (
            artifact.get("type") != "SPRITESHEET_EXPORT"
            or artifact.get("status") != "PRODUCED"
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("content_hash") != "sha256:" + binding.output_content_hash
            or content_hash != "sha256:" + binding.output_content_hash
            or byte_count != binding.output_byte_count
        ):
            raise PixeloramaProductionAdoptionError(
                "bound Pixelorama production source drifted before adoption"
            )
        return artifact, source, content_hash, byte_count

    def _existing_receipt(self, execution_id: str):
        try:
            return read_pixelorama_production_adoption_receipt(
                self.runtime,
                execution_id,
            )
        except PixeloramaProductionAdoptionReceiptError as exc:
            if str(exc) == "production adoption receipt does not exist":
                return None
            raise PixeloramaProductionAdoptionError(
                "production adoption receipt cannot be read safely"
            ) from exc

    def adopt_new(
        self,
        execution_id: str,
        destination_relative_path: str,
    ) -> GovernedPixeloramaProductionAdoptionResult:
        if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
            raise ValueError("execution_id must be a DISPEXEC ID")
        binding = read_pixelorama_dispatch_output_binding(self.runtime, execution_id)
        self._require_eligible(execution_id, binding.output_artifact_id)
        artifact, source, content_hash, byte_count = self._prepared_source(binding)

        existing = self._existing_receipt(execution_id)
        if existing is not None:
            if existing.status is PixeloramaProductionAdoptionStatus.PUBLISHED:
                raise PixeloramaProductionAdoptionError(
                    "production execution output has already been canonically adopted"
                )
            if existing.destination_path != destination_relative_path:
                raise PixeloramaProductionAdoptionError(
                    "production execution is already reserved for a different destination"
                )
            reserved_destination = self.runtime.project_root / Path(existing.destination_path)
            if reserved_destination.exists() or reserved_destination.is_symlink():
                raise PixeloramaProductionAdoptionError(
                    "production adoption recovery required: destination exists beside PREPARED receipt"
                )

        try:
            destination, portable_destination = self.publisher._destination(
                destination_relative_path
            )
        except PixeloramaAdoptionError as exc:
            raise PixeloramaProductionAdoptionError(str(exc)) from exc
        try:
            receipt = reserve_pixelorama_production_adoption(
                self.runtime,
                binding,
                portable_destination,
                utc_now(),
            )
        except PixeloramaProductionAdoptionReceiptError as exc:
            raise PixeloramaProductionAdoptionError(
                "production adoption reservation failed closed"
            ) from exc
        if receipt.status is PixeloramaProductionAdoptionStatus.PUBLISHED:
            raise PixeloramaProductionAdoptionError(
                "production execution output has already been canonically adopted"
            )

        def require_current_before_link() -> None:
            self._require_eligible(execution_id, binding.output_artifact_id)
            current_receipt = read_pixelorama_production_adoption_receipt(
                self.runtime,
                execution_id,
            )
            if (
                current_receipt.status is not PixeloramaProductionAdoptionStatus.PREPARED
                or current_receipt.output_artifact_id != binding.output_artifact_id
                or current_receipt.destination_path != portable_destination
            ):
                raise PixeloramaProductionAdoptionError(
                    "production adoption reservation drifted before create-only publication"
                )

        try:
            published: GovernedPixeloramaAdoptionResult = (
                self.publisher._publish_verified_new(
                    source_artifact_id=binding.output_artifact_id,
                    artifact=artifact,
                    source=source,
                    content_hash=content_hash,
                    byte_count=byte_count,
                    destination=destination,
                    portable_destination=portable_destination,
                    verification_type=PRODUCTION_ADOPTION_VERIFICATION_TYPE,
                    verifier=PRODUCTION_ADOPTION_VERIFIER,
                    extra_evidence={
                        "production_dispatch_output_bound": True,
                        "dispatch_execution_id": binding.execution_id,
                        "dispatch_claim_id": binding.claim_id,
                        "production_run_id": binding.run_id,
                        "semantic_visual_quality_verified": False,
                        "provenance_signed": False,
                    },
                    pre_publish_check=require_current_before_link,
                )
            )
        except (PixeloramaAdoptionError, PixeloramaProductionAdoptionReceiptError) as exc:
            raise PixeloramaProductionAdoptionError(str(exc)) from exc

        try:
            final_receipt = finalize_pixelorama_production_adoption(
                self.runtime,
                binding,
                destination_path=portable_destination,
                adopted_artifact_id=published.adopted_artifact_id,
                verification_id=published.verification_id,
                published_at=utc_now(),
            )
        except PixeloramaProductionAdoptionReceiptError as exc:
            raise PixeloramaProductionAdoptionError(
                "production adoption was published but receipt finalization requires operator recovery"
            ) from exc
        if (
            final_receipt.status is not PixeloramaProductionAdoptionStatus.PUBLISHED
            or final_receipt.adopted_artifact_id != published.adopted_artifact_id
            or final_receipt.verification_id != published.verification_id
        ):
            raise PixeloramaProductionAdoptionError(
                "production adoption receipt does not match published identities"
            )
        return GovernedPixeloramaProductionAdoptionResult(
            execution_id=binding.execution_id,
            claim_id=binding.claim_id,
            task_id=binding.task_id,
            run_id=binding.run_id,
            source_artifact_id=binding.output_artifact_id,
            adopted_artifact_id=published.adopted_artifact_id,
            verification_id=published.verification_id,
            destination_path=published.destination_path,
            content_hash=published.content_hash,
            byte_count=published.byte_count,
        )
