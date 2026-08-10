from __future__ import annotations

from dataclasses import dataclass

from .image_png import decode_truecolor8_png
from .runtime_observation_models import VisualBaselineRef


class RuntimeVisualError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeVisualDiff:
    baseline_id: str
    width: int
    height: int
    total_pixels: int
    changed_pixels: int
    max_channel_delta: int
    total_channel_delta: int
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_id": self.baseline_id,
            "width": self.width,
            "height": self.height,
            "total_pixels": self.total_pixels,
            "changed_pixels": self.changed_pixels,
            "max_channel_delta": self.max_channel_delta,
            "total_channel_delta": self.total_channel_delta,
            "passed": self.passed,
        }


def compare_png_to_baseline(
    baseline_png: bytes,
    observed_png: bytes,
    baseline: VisualBaselineRef,
) -> RuntimeVisualDiff:
    if not isinstance(baseline, VisualBaselineRef):
        raise TypeError("baseline must be a VisualBaselineRef")
    baseline_plane = decode_truecolor8_png(baseline_png).plane
    observed_plane = decode_truecolor8_png(observed_png).plane
    if baseline_plane.width != baseline.width or baseline_plane.height != baseline.height:
        raise RuntimeVisualError("baseline PNG dimensions drifted from frozen baseline")
    if baseline_plane.rgba_hash != baseline.pixel_hash:
        raise RuntimeVisualError("baseline PNG pixel hash drifted from frozen baseline")
    if (
        observed_plane.width != baseline_plane.width
        or observed_plane.height != baseline_plane.height
    ):
        raise RuntimeVisualError("observed capture dimensions differ from visual baseline")

    changed_pixels = 0
    max_channel_delta = 0
    total_channel_delta = 0
    baseline_bytes = baseline_plane.rgba_bytes
    observed_bytes = observed_plane.rgba_bytes
    for pixel_start in range(0, len(baseline_bytes), 4):
        pixel_changed = False
        for channel in range(4):
            delta = abs(
                baseline_bytes[pixel_start + channel]
                - observed_bytes[pixel_start + channel]
            )
            if delta:
                pixel_changed = True
                total_channel_delta += delta
                max_channel_delta = max(max_channel_delta, delta)
        if pixel_changed:
            changed_pixels += 1

    passed = (
        changed_pixels <= baseline.max_changed_pixels
        and max_channel_delta <= baseline.max_channel_delta
        and total_channel_delta <= baseline.max_total_channel_delta
    )
    return RuntimeVisualDiff(
        baseline_id=baseline.baseline_id,
        width=baseline.width,
        height=baseline.height,
        total_pixels=baseline.width * baseline.height,
        changed_pixels=changed_pixels,
        max_channel_delta=max_channel_delta,
        total_channel_delta=total_channel_delta,
        passed=passed,
    )