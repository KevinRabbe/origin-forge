from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .pixelorama_models import SpriteProjectSpec
from .pixelorama_png import PngError, PngInspection, inspect_rgba8_png


class RasterFindingCode(StrEnum):
    INVALID_PNG = "INVALID_PNG"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    FULLY_TRANSPARENT = "FULLY_TRANSPARENT"
    TRANSPARENCY_REQUIRED = "TRANSPARENCY_REQUIRED"
    SPRITESHEET_GEOMETRY_MISMATCH = "SPRITESHEET_GEOMETRY_MISMATCH"


@dataclass(frozen=True)
class RasterFinding:
    code: RasterFindingCode
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True)
class RasterValidationResult:
    passed: bool
    findings: tuple[RasterFinding, ...]
    inspection: PngInspection | None

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "findings": [value.to_dict() for value in self.findings],
            "inspection": None if self.inspection is None else self.inspection.to_dict(),
            "production_verification_changed": False,
        }


def validate_frame_png(data: bytes, spec: SpriteProjectSpec) -> RasterValidationResult:
    if not isinstance(spec, SpriteProjectSpec):
        raise TypeError("spec must be a SpriteProjectSpec")
    findings: list[RasterFinding] = []
    try:
        inspection = inspect_rgba8_png(data)
    except PngError as exc:
        return RasterValidationResult(
            False,
            (RasterFinding(RasterFindingCode.INVALID_PNG, str(exc)[:2048]),),
            None,
        )
    if inspection.width != spec.width or inspection.height != spec.height:
        findings.append(
            RasterFinding(
                RasterFindingCode.DIMENSION_MISMATCH,
                f"frame dimensions {inspection.width}x{inspection.height} != expected {spec.width}x{spec.height}",
            )
        )
    if inspection.fully_transparent:
        findings.append(
            RasterFinding(
                RasterFindingCode.FULLY_TRANSPARENT,
                "frame contains no non-transparent pixels",
            )
        )
    if spec.transparency_required and inspection.fully_opaque:
        findings.append(
            RasterFinding(
                RasterFindingCode.TRANSPARENCY_REQUIRED,
                "frame is fully opaque although the sprite requires transparency",
            )
        )
    return RasterValidationResult(not findings, tuple(findings), inspection)


def validate_spritesheet_png(
    data: bytes,
    spec: SpriteProjectSpec,
    *,
    columns: int,
) -> RasterValidationResult:
    if not isinstance(spec, SpriteProjectSpec):
        raise TypeError("spec must be a SpriteProjectSpec")
    if not isinstance(columns, int) or isinstance(columns, bool) or columns <= 0:
        raise ValueError("columns must be a positive integer")
    findings: list[RasterFinding] = []
    try:
        inspection = inspect_rgba8_png(data)
    except PngError as exc:
        return RasterValidationResult(
            False,
            (RasterFinding(RasterFindingCode.INVALID_PNG, str(exc)[:2048]),),
            None,
        )
    frame_count = len(spec.frames)
    rows = (frame_count + columns - 1) // columns
    expected_width = spec.width * columns
    expected_height = spec.height * rows
    if inspection.width != expected_width or inspection.height != expected_height:
        findings.append(
            RasterFinding(
                RasterFindingCode.SPRITESHEET_GEOMETRY_MISMATCH,
                f"spritesheet dimensions {inspection.width}x{inspection.height} != expected {expected_width}x{expected_height} for {frame_count} frames in {columns} columns",
            )
        )
    if inspection.fully_transparent:
        findings.append(
            RasterFinding(
                RasterFindingCode.FULLY_TRANSPARENT,
                "spritesheet contains no non-transparent pixels",
            )
        )
    if spec.transparency_required and inspection.fully_opaque:
        findings.append(
            RasterFinding(
                RasterFindingCode.TRANSPARENCY_REQUIRED,
                "spritesheet is fully opaque although the sprite requires transparency",
            )
        )
    return RasterValidationResult(not findings, tuple(findings), inspection)
