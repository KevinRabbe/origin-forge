from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .blockbench_models import (
    BlockbenchBridgeRequest,
    BlockbenchModelError,
    canonical_hash,
    validate_sha256,
    workspace_relative_path,
)
from .ids import IdKind, validate_id


_MAX_OUTPUTS = 32
_MAX_DIAGNOSTICS = 64
_MAX_DIAGNOSTIC_CHARS = 2048
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024


class BlockbenchResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class BlockbenchOutputType(StrEnum):
    GLB = "GLB"
    BLOCKBENCH_PROJECT = "BLOCKBENCH_PROJECT"
    PREVIEW_PNG = "PREVIEW_PNG"


@dataclass(frozen=True)
class BlockbenchBridgeOutput:
    output_type: BlockbenchOutputType
    relative_path: str
    content_hash: str
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.output_type, BlockbenchOutputType):
            raise BlockbenchModelError("output_type must be a BlockbenchOutputType")
        path = workspace_relative_path(self.relative_path, "output relative_path")
        if not path.startswith("exports/"):
            raise BlockbenchModelError("bridge output must be under exports/")
        suffix = {
            BlockbenchOutputType.GLB: ".glb",
            BlockbenchOutputType.BLOCKBENCH_PROJECT: ".bbmodel",
            BlockbenchOutputType.PREVIEW_PNG: ".png",
        }[self.output_type]
        if not path.lower().endswith(suffix):
            raise BlockbenchModelError(
                f"{self.output_type.value} output must end with {suffix}"
            )
        object.__setattr__(self, "relative_path", path)
        validate_sha256(self.content_hash, "output content_hash")
        if (
            not isinstance(self.byte_count, int)
            or isinstance(self.byte_count, bool)
            or not 1 <= self.byte_count <= _MAX_OUTPUT_BYTES
        ):
            raise BlockbenchModelError("output byte_count is outside the allowed range")

    def to_dict(self) -> dict[str, object]:
        return {
            "output_type": self.output_type.value,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "byte_count": self.byte_count,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BlockbenchBridgeOutput":
        if not isinstance(value, dict):
            raise BlockbenchModelError("bridge output must be an object")
        expected = {"output_type", "relative_path", "content_hash", "byte_count"}
        if set(value) != expected:
            raise BlockbenchModelError("bridge output fields do not match strict schema")
        try:
            output_type = BlockbenchOutputType(value["output_type"])
        except (TypeError, ValueError) as exc:
            raise BlockbenchModelError("unknown bridge output type") from exc
        return cls(
            output_type=output_type,
            relative_path=value["relative_path"],
            content_hash=value["content_hash"],
            byte_count=value["byte_count"],
        )


@dataclass(frozen=True)
class BlockbenchBridgeResult:
    operation_id: str
    workspace_id: str
    request_hash: str
    status: BlockbenchResultStatus
    blockbench_version: str
    bridge_fingerprint: str
    outputs: tuple[BlockbenchBridgeOutput, ...]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not validate_id(self.operation_id, IdKind.BLOCKBENCH_OPERATION):
            raise BlockbenchModelError("result operation_id must be a BBOP ID")
        if not validate_id(self.workspace_id, IdKind.MODEL3D_WORKSPACE):
            raise BlockbenchModelError("result workspace_id must be a MODEL3D ID")
        validate_sha256(self.request_hash, "result request_hash")
        validate_sha256(self.bridge_fingerprint, "result bridge_fingerprint")
        if not isinstance(self.status, BlockbenchResultStatus):
            raise BlockbenchModelError("result status must be a BlockbenchResultStatus")
        if (
            not isinstance(self.blockbench_version, str)
            or not self.blockbench_version.strip()
            or self.blockbench_version != self.blockbench_version.strip()
            or len(self.blockbench_version) > 128
            or "\x00" in self.blockbench_version
            or "\n" in self.blockbench_version
            or "\r" in self.blockbench_version
        ):
            raise BlockbenchModelError("blockbench_version must be one bounded non-empty line")
        outputs = tuple(self.outputs)
        if len(outputs) > _MAX_OUTPUTS:
            raise BlockbenchModelError("bridge result exceeds output count limit")
        if any(not isinstance(output, BlockbenchBridgeOutput) for output in outputs):
            raise BlockbenchModelError("bridge result outputs contain invalid values")
        paths = [output.relative_path for output in outputs]
        if len(paths) != len(set(paths)):
            raise BlockbenchModelError("bridge result may not repeat an output path")
        if self.status == BlockbenchResultStatus.SUCCEEDED and not outputs:
            raise BlockbenchModelError("successful bridge result must contain output evidence")
        diagnostics = tuple(self.diagnostics)
        if len(diagnostics) > _MAX_DIAGNOSTICS:
            raise BlockbenchModelError("bridge result exceeds diagnostic count limit")
        for diagnostic in diagnostics:
            if (
                not isinstance(diagnostic, str)
                or not diagnostic.strip()
                or len(diagnostic) > _MAX_DIAGNOSTIC_CHARS
                or "\x00" in diagnostic
            ):
                raise BlockbenchModelError("bridge diagnostic is invalid")
        object.__setattr__(
            self,
            "outputs",
            tuple(sorted(outputs, key=lambda output: output.relative_path)),
        )
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": 1,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "blockbench_version": self.blockbench_version,
            "bridge_fingerprint": self.bridge_fingerprint,
            "outputs": [output.to_dict() for output in self.outputs],
            "diagnostics": list(self.diagnostics),
        }

    def bind_to_request(self, request: BlockbenchBridgeRequest) -> None:
        if not isinstance(request, BlockbenchBridgeRequest):
            raise TypeError("request must be a BlockbenchBridgeRequest")
        if self.operation_id != request.operation_id:
            raise BlockbenchModelError("bridge result operation_id does not match request")
        if self.workspace_id != request.workspace_id:
            raise BlockbenchModelError("bridge result workspace_id does not match request")
        if self.request_hash != request.content_hash:
            raise BlockbenchModelError("bridge result request_hash does not match request")
        if self.bridge_fingerprint != request.bridge_fingerprint:
            raise BlockbenchModelError("bridge result fingerprint does not match request")
        if self.blockbench_version != request.expected_blockbench_version:
            raise BlockbenchModelError("bridge result Blockbench version does not match request")
        if self.status == BlockbenchResultStatus.SUCCEEDED:
            matching = [
                output
                for output in self.outputs
                if output.relative_path == request.output_relative_path
            ]
            if len(matching) != 1:
                raise BlockbenchModelError(
                    "successful bridge result must bind the exact declared output"
                )

    @classmethod
    def from_dict(cls, value: Any) -> "BlockbenchBridgeResult":
        if not isinstance(value, dict):
            raise BlockbenchModelError("bridge result must be an object")
        expected = {
            "protocol_version",
            "operation_id",
            "workspace_id",
            "request_hash",
            "status",
            "blockbench_version",
            "bridge_fingerprint",
            "outputs",
            "diagnostics",
        }
        if set(value) != expected:
            raise BlockbenchModelError("bridge result fields do not match strict schema")
        if value["protocol_version"] != 1:
            raise BlockbenchModelError("unsupported bridge result protocol_version")
        try:
            status = BlockbenchResultStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise BlockbenchModelError("unknown bridge result status") from exc
        if not isinstance(value["outputs"], list) or not isinstance(value["diagnostics"], list):
            raise BlockbenchModelError("bridge result outputs/diagnostics must be arrays")
        return cls(
            operation_id=value["operation_id"],
            workspace_id=value["workspace_id"],
            request_hash=value["request_hash"],
            status=status,
            blockbench_version=value["blockbench_version"],
            bridge_fingerprint=value["bridge_fingerprint"],
            outputs=tuple(BlockbenchBridgeOutput.from_dict(item) for item in value["outputs"]),
            diagnostics=tuple(value["diagnostics"]),
        )
