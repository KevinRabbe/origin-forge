from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ids import IdKind, validate_id
from .lineage import OriginForgeLineage
from .path_policy import portable_relative_path
from .production_blender_adoption_receipt import (
    BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE,
    BLENDER_PRODUCTION_ADOPTION_VERIFIER,
    BlenderProductionAdoptionReceiptError,
    BlenderProductionAdoptionStatus,
    expected_blender_production_adoption_evidence,
    finalize_blender_production_adoption,
    read_blender_production_adoption_receipt,
    reserve_blender_production_adoption,
)
from .production_blender_dispatch_output_binding import (
    BlenderDispatchOutputBinding,
    BlenderDispatchOutputBindingError,
    materialize_bound_blender_result,
    read_blender_dispatch_output_binding,
)
from .production_blender_dispatch_output_currentness import (
    inspect_blender_dispatch_output_currentness_readonly,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


class BlenderProductionAdoptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernedBlenderProductionAdoptionResult:
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
            "semantic_geometry_verified": False,
            "provenance_signed": False,
        }


class GovernedBlenderProductionOutputAdopter:
    """Create-only publication of one exact terminal production Blender GLB."""

    PROTECTED_ROOTS = {".git", ".origin-forge"}

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_source_bytes: int = 512 * 1024 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if (
            not isinstance(max_source_bytes, int)
            or isinstance(max_source_bytes, bool)
            or max_source_bytes <= 0
            or max_source_bytes > 8 * 1024 * 1024 * 1024
        ):
            raise ValueError("max_source_bytes must be between 1 and 8 GiB")
        self.runtime = runtime
        self.lineage = OriginForgeLineage(runtime)
        self.max_source_bytes = max_source_bytes

    def _require_eligible(
        self,
        execution_id: str,
        *,
        output_artifact_id: str | None = None,
    ) -> None:
        currentness = inspect_blender_dispatch_output_currentness_readonly(
            self.runtime,
            execution_id,
        )
        if (
            not currentness.adoption_eligible
            or (
                output_artifact_id is not None
                and currentness.output_artifact_id != output_artifact_id
            )
            or currentness.production_task_verified
            or currentness.semantic_geometry_verified
        ):
            detail = currentness.detail or currentness.status.value
            raise BlenderProductionAdoptionError(
                f"Blender production output is not adoption eligible: {detail}"
            )

    @staticmethod
    def _tool_versions(artifact: dict[str, object]) -> tuple[str, ...]:
        raw = artifact.get("tool_versions_json")
        if not isinstance(raw, str):
            raise BlenderProductionAdoptionError(
                "bound Blender source Artifact tool_versions_json is invalid"
            )
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BlenderProductionAdoptionError(
                "bound Blender source Artifact tool_versions_json is invalid"
            ) from exc
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise BlenderProductionAdoptionError(
                "bound Blender source Artifact tool_versions_json is invalid"
            )
        return tuple(values)

    def _prepared_source(
        self,
        binding: BlenderDispatchOutputBinding,
    ) -> tuple[dict[str, object], Path, tuple[str, ...]]:
        try:
            materialized = materialize_bound_blender_result(self.runtime, binding)
            artifact = self.lineage.get_artifact(binding.output_artifact_id)
            source = self.lineage.local_artifact_path(binding.output_artifact_id)
            materialized_path = materialized.operation.output_path.resolve(strict=True)
        except (
            BlenderDispatchOutputBindingError,
            KeyError,
            OSError,
            RuntimeError,
        ) as exc:
            raise BlenderProductionAdoptionError(
                "bound Blender production source cannot be prepared for adoption"
            ) from exc
        content_hash = "sha256:" + binding.output_content_hash
        if (
            source != materialized_path
            or artifact.get("type") != "BLENDER_GLB_EXPORT"
            or artifact.get("status") != "PRODUCED"
            or artifact.get("parent_artifact_id") != binding.result_artifact_id
            or artifact.get("created_by_run_id") != binding.run_id
            or artifact.get("content_hash") != content_hash
        ):
            raise BlenderProductionAdoptionError(
                "bound Blender production source drifted before adoption"
            )
        return artifact, source, self._tool_versions(artifact)

    def _stream_hash(self, source: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        total = 0
        try:
            with source.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_source_bytes:
                        raise BlenderProductionAdoptionError(
                            f"source Artifact exceeds adoption byte limit ({total} > {self.max_source_bytes})"
                        )
                    digest.update(chunk)
        except OSError as exc:
            raise BlenderProductionAdoptionError(
                "bound Blender production source cannot be reread"
            ) from exc
        return "sha256:" + digest.hexdigest(), total

    def _destination(self, relative_path: str) -> tuple[Path, str]:
        try:
            relative = portable_relative_path(relative_path)
        except ValueError as exc:
            if "protected" in str(exc).casefold():
                raise BlenderProductionAdoptionError(
                    "Blender adoption destination may not target protected project state"
                ) from exc
            raise BlenderProductionAdoptionError(
                "invalid Blender adoption destination path"
            ) from exc
        if not relative.parts:
            raise BlenderProductionAdoptionError(
                "Blender adoption destination path may not be empty"
            )
        if relative.parts[0].casefold() in self.PROTECTED_ROOTS:
            raise BlenderProductionAdoptionError(
                "Blender adoption destination may not target a protected project root"
            )
        project_root = self.runtime.project_root.resolve()
        destination = self.runtime.project_root / relative
        if destination.is_symlink() or destination.exists():
            raise BlenderProductionAdoptionError(
                "Blender production adoption is create-only and refuses existing destinations"
            )
        current = project_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise BlenderProductionAdoptionError(
                    "Blender adoption destination contains a symlink"
                )
        return destination, relative.as_posix()

    def _prepare_destination_parent(self, destination: Path) -> None:
        project_root = self.runtime.project_root.resolve()
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.resolve().relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BlenderProductionAdoptionError(
                "Blender adoption destination escapes project root"
            ) from exc
        relative_parent = destination.parent.resolve().relative_to(project_root)
        current = project_root
        for part in relative_parent.parts:
            current = current / part
            if current.is_symlink():
                raise BlenderProductionAdoptionError(
                    "Blender adoption destination contains a symlink"
                )
        if destination.is_symlink() or destination.exists():
            raise BlenderProductionAdoptionError(
                "Blender production adoption is create-only and refuses existing destinations"
            )

    def _existing_receipt(self, execution_id: str):
        try:
            return read_blender_production_adoption_receipt(
                self.runtime,
                execution_id,
            )
        except BlenderProductionAdoptionReceiptError as exc:
            if str(exc) == "Blender production adoption receipt does not exist":
                return None
            raise BlenderProductionAdoptionError(
                "Blender production adoption receipt cannot be read safely"
            ) from exc

    def _publish_new(
        self,
        *,
        binding: BlenderDispatchOutputBinding,
        source: Path,
        destination: Path,
        expected_hash: str,
        expected_byte_count: int,
        portable_destination: str,
        pre_publish_check,
    ) -> None:
        temp = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            copied = 0
            digest = hashlib.sha256()
            with source.open("rb") as src, temp.open("xb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > self.max_source_bytes:
                        raise BlenderProductionAdoptionError(
                            "source Artifact grew beyond adoption byte limit while copying"
                        )
                    digest.update(chunk)
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            copied_hash = "sha256:" + digest.hexdigest()
            if copied != expected_byte_count or copied_hash != expected_hash:
                raise BlenderProductionAdoptionError(
                    "bound Blender source changed while adoption copy was being created"
                )
            pre_publish_check()
            try:
                os.link(temp, destination)
            except FileExistsError as exc:
                raise BlenderProductionAdoptionError(
                    "Blender adoption destination appeared concurrently; refusing overwrite"
                ) from exc
        except OSError as exc:
            raise BlenderProductionAdoptionError(
                "Blender production adoption publication failed closed"
            ) from exc
        finally:
            temp.unlink(missing_ok=True)

        try:
            published_hash, published_size = self._stream_hash(destination)
        except BlenderProductionAdoptionError:
            raise
        if published_hash != expected_hash or published_size != expected_byte_count:
            raise BlenderProductionAdoptionError(
                "published Blender destination bytes are not the exact bound output"
            )

    def adopt_new(
        self,
        execution_id: str,
        destination_relative_path: str,
    ) -> GovernedBlenderProductionAdoptionResult:
        if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
            raise ValueError("execution_id must be a DISPEXEC ID")

        self._require_eligible(execution_id)
        try:
            binding = read_blender_dispatch_output_binding(self.runtime, execution_id)
        except BlenderDispatchOutputBindingError as exc:
            raise BlenderProductionAdoptionError(
                "Blender dispatch-output binding cannot be read safely"
            ) from exc
        self._require_eligible(
            execution_id,
            output_artifact_id=binding.output_artifact_id,
        )
        artifact, source, tool_versions = self._prepared_source(binding)
        expected_hash, expected_byte_count = self._stream_hash(source)
        if (
            expected_hash != "sha256:" + binding.output_content_hash
            or expected_byte_count != binding.output_byte_count
        ):
            raise BlenderProductionAdoptionError(
                "bound Blender production source drifted before reservation"
            )

        existing = self._existing_receipt(execution_id)
        if existing is not None:
            if existing.status is BlenderProductionAdoptionStatus.PUBLISHED:
                raise BlenderProductionAdoptionError(
                    "Blender production execution output has already been canonically adopted"
                )
            if existing.destination_path != destination_relative_path:
                raise BlenderProductionAdoptionError(
                    "Blender production execution is already reserved for a different destination"
                )
            reserved_destination = self.runtime.project_root / Path(
                existing.destination_path
            )
            if reserved_destination.exists() or reserved_destination.is_symlink():
                raise BlenderProductionAdoptionError(
                    "Blender production adoption recovery required: destination exists beside PREPARED receipt"
                )

        destination, portable_destination = self._destination(
            destination_relative_path
        )
        try:
            receipt = reserve_blender_production_adoption(
                self.runtime,
                binding,
                portable_destination,
                utc_now(),
            )
        except BlenderProductionAdoptionReceiptError as exc:
            raise BlenderProductionAdoptionError(
                "Blender production adoption reservation failed closed"
            ) from exc
        if receipt.status is BlenderProductionAdoptionStatus.PUBLISHED:
            raise BlenderProductionAdoptionError(
                "Blender production execution output has already been canonically adopted"
            )

        self._prepare_destination_parent(destination)

        def require_current_before_link() -> None:
            self._require_eligible(
                execution_id,
                output_artifact_id=binding.output_artifact_id,
            )
            try:
                current_binding = read_blender_dispatch_output_binding(
                    self.runtime,
                    execution_id,
                )
                if current_binding != binding:
                    raise BlenderProductionAdoptionError(
                        "Blender dispatch-output binding drifted before create-only publication"
                    )
                materialize_bound_blender_result(self.runtime, binding)
                current_receipt = read_blender_production_adoption_receipt(
                    self.runtime,
                    execution_id,
                )
            except BlenderProductionAdoptionReceiptError as exc:
                raise BlenderProductionAdoptionError(
                    "Blender production adoption reservation cannot be revalidated"
                ) from exc
            except BlenderDispatchOutputBindingError as exc:
                raise BlenderProductionAdoptionError(
                    "bound Blender source cannot be revalidated before publication"
                ) from exc
            if (
                current_receipt.status is not BlenderProductionAdoptionStatus.PREPARED
                or current_receipt.output_artifact_id != binding.output_artifact_id
                or current_receipt.destination_path != portable_destination
            ):
                raise BlenderProductionAdoptionError(
                    "Blender production adoption reservation drifted before create-only publication"
                )

        self._publish_new(
            binding=binding,
            source=source,
            destination=destination,
            expected_hash=expected_hash,
            expected_byte_count=expected_byte_count,
            portable_destination=portable_destination,
            pre_publish_check=require_current_before_link,
        )

        adopted_artifact_id = self.lineage.create_artifact(
            artifact_type="BLENDER_GLB_EXPORT",
            path_or_uri=str(destination),
            parent_artifact_id=binding.output_artifact_id,
            created_by_run_id=binding.run_id,
            tool_versions=tool_versions,
            status="ADOPTED",
        )
        adopted = self.lineage.get_artifact(adopted_artifact_id)
        if (
            adopted["path_or_uri"] != portable_destination
            or adopted["content_hash"] != expected_hash
        ):
            raise BlenderProductionAdoptionError(
                "adopted Blender Artifact did not preserve exact destination bytes"
            )
        verification_id = self.lineage.record_artifact_verification(
            adopted_artifact_id,
            verification_type=BLENDER_PRODUCTION_ADOPTION_VERIFICATION_TYPE,
            verifier=BLENDER_PRODUCTION_ADOPTION_VERIFIER,
            status="PASS",
            evidence=expected_blender_production_adoption_evidence(
                binding,
                portable_destination,
            ),
            run_id=binding.run_id,
        )
        try:
            final_receipt = finalize_blender_production_adoption(
                self.runtime,
                binding,
                destination_path=portable_destination,
                adopted_artifact_id=adopted_artifact_id,
                verification_id=verification_id,
                published_at=utc_now(),
            )
        except BlenderProductionAdoptionReceiptError as exc:
            raise BlenderProductionAdoptionError(
                "Blender production adoption was published but receipt finalization requires operator recovery"
            ) from exc
        if (
            final_receipt.status is not BlenderProductionAdoptionStatus.PUBLISHED
            or final_receipt.adopted_artifact_id != adopted_artifact_id
            or final_receipt.verification_id != verification_id
        ):
            raise BlenderProductionAdoptionError(
                "Blender production adoption receipt does not match published identities"
            )
        return GovernedBlenderProductionAdoptionResult(
            execution_id=binding.execution_id,
            claim_id=binding.claim_id,
            task_id=binding.task_id,
            run_id=binding.run_id,
            source_artifact_id=binding.output_artifact_id,
            adopted_artifact_id=adopted_artifact_id,
            verification_id=verification_id,
            destination_path=portable_destination,
            content_hash=expected_hash,
            byte_count=expected_byte_count,
        )
