from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .blockbench_models import (
    BlockbenchModelError,
    BlockbenchProjectSpec,
    canonical_hash,
    validate_sha256,
    workspace_relative_path,
)
from .ids import IdKind, new_id, validate_id


class BlenderModelError(ValueError):
    pass


class BlenderOperation(StrEnum):
    EXPORT_GLB = "EXPORT_GLB"


@dataclass(frozen=True)
class BlenderBudget:
    timeout_seconds: int = 120
    max_output_bytes: int = 256 * 1024 * 1024
    max_stdout_bytes: int = 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for value, field, maximum in (
            (self.timeout_seconds, "timeout_seconds", 3600),
            (self.max_output_bytes, "max_output_bytes", 2 * 1024 * 1024 * 1024),
            (self.max_stdout_bytes, "max_stdout_bytes", 16 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 16 * 1024 * 1024),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= maximum
            ):
                raise BlenderModelError(f"{field} is outside the allowed range")

    def to_dict(self) -> dict[str, int]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
        }


def _bounded_line(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(char in value for char in ("\x00", "\n", "\r"))
    ):
        raise BlenderModelError(f"{field} must be one bounded non-empty line")
    return value


def _validate_v0_project(project: BlockbenchProjectSpec) -> None:
    """Require only the geometry semantics implemented by runner schema v1."""
    if project.bones:
        raise BlenderModelError("Blender runner v1 does not accept bones")
    if project.textures:
        raise BlenderModelError("Blender runner v1 does not accept textures")
    if project.animations:
        raise BlenderModelError("Blender runner v1 does not accept animations")
    for cuboid in project.cuboids:
        if cuboid.parent_bone_id is not None:
            raise BlenderModelError("Blender runner v1 cuboids may not have parents")
        if cuboid.rotation.to_list() != [0.0, 0.0, 0.0]:
            raise BlenderModelError("Blender runner v1 accepts axis-aligned cuboids only")
        if cuboid.inflate != 0.0:
            raise BlenderModelError("Blender runner v1 does not accept cuboid inflation")
        if cuboid.uv_offset != (0.0, 0.0) or cuboid.mirror_uv:
            raise BlenderModelError("Blender runner v1 does not accept UV controls")
        if not cuboid.visible:
            raise BlenderModelError("Blender runner v1 requires visible cuboids")


@dataclass(frozen=True)
class BlenderJobRequest:
    operation_id: str
    workspace_id: str
    operation: BlenderOperation
    project: BlockbenchProjectSpec
    output_relative_path: str
    runner_fingerprint: str
    runtime_hash: str
    expected_blender_version: str
    budget: BlenderBudget = BlenderBudget()

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.BLENDER_OPERATION):
            raise BlenderModelError("operation_id must be a BLOP ID")
        if not validate_id(self.workspace_id, IdKind.MODEL3D_WORKSPACE):
            raise BlenderModelError("workspace_id must be a MODEL3D ID")
        if not isinstance(self.operation, BlenderOperation):
            raise BlenderModelError("operation must be a BlenderOperation")
        if not isinstance(self.project, BlockbenchProjectSpec):
            raise BlenderModelError("project must be the canonical v1 3D project spec")
        _validate_v0_project(self.project)
        try:
            output = workspace_relative_path(
                self.output_relative_path, "output_relative_path"
            )
            validate_sha256(self.runner_fingerprint, "runner_fingerprint")
            validate_sha256(self.runtime_hash, "runtime_hash")
        except BlockbenchModelError as exc:
            raise BlenderModelError(str(exc)) from exc
        if not output.startswith("exports/") or not output.lower().endswith(".glb"):
            raise BlenderModelError(
                "output_relative_path must be a GLB path under exports/"
            )
        object.__setattr__(self, "output_relative_path", output)
        _bounded_line(self.expected_blender_version, "expected_blender_version")
        if not isinstance(self.budget, BlenderBudget):
            raise BlenderModelError("budget must be a BlenderBudget")

    @classmethod
    def create(
        cls,
        *,
        project: BlockbenchProjectSpec,
        output_relative_path: str,
        runner_fingerprint: str,
        runtime_hash: str,
        expected_blender_version: str,
        budget: BlenderBudget | None = None,
    ) -> "BlenderJobRequest":
        return cls(
            operation_id=new_id(IdKind.BLENDER_OPERATION),
            workspace_id=new_id(IdKind.MODEL3D_WORKSPACE),
            operation=BlenderOperation.EXPORT_GLB,
            project=project,
            output_relative_path=output_relative_path,
            runner_fingerprint=runner_fingerprint,
            runtime_hash=runtime_hash,
            expected_blender_version=expected_blender_version,
            budget=budget or BlenderBudget(),
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": 1,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "operation": self.operation.value,
            "project": self.project.to_dict(),
            "project_hash": self.project.content_hash,
            "output_relative_path": self.output_relative_path,
            "runner_fingerprint": self.runner_fingerprint,
            "runtime_hash": self.runtime_hash,
            "expected_blender_version": self.expected_blender_version,
            "budget": self.budget.to_dict(),
        }
