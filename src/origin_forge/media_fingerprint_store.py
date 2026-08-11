from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .media_fingerprint_models import (
    FingerprintComparison,
    MediaFingerprint,
    WatermarkPlan,
)
from .media_fingerprint_provenance import FingerprintProvenanceLink
from .media_watermark_models import WatermarkResult
from .runtime import OriginForgeRuntime
from .runtime_observation_models import canonical_bytes, content_hash


_SCHEMA_VERSION = 1
_MAX_OBJECT_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_CATEGORY_KIND = {
    "fingerprints": IdKind.MEDIA_FINGERPRINT,
    "comparisons": IdKind.FINGERPRINT_COMPARISON,
    "watermark-plans": IdKind.WATERMARK_PLAN,
    "watermark-results": IdKind.WATERMARK_RESULT,
    "provenance-links": IdKind.FINGERPRINT_PROVENANCE_LINK,
}


class MediaFingerprintStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MediaFingerprintStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class MediaFingerprintStore:
    """Immutable protected evidence store for Phase-28 fingerprints/marks."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "media-fingerprints"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise MediaFingerprintStoreError("media-fingerprint root may not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MediaFingerprintStoreError("media-fingerprint root escaped protected state") from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise MediaFingerprintStoreError("unknown media-fingerprint category")
        root = self._ensure_root()
        directory = self.root / category
        if directory.is_symlink():
            raise MediaFingerprintStoreError(f"{category} directory may not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MediaFingerprintStoreError(f"{category} directory escaped protected root") from exc
        return directory

    @staticmethod
    def _object_id(category: str, value: object) -> str:
        if category == "fingerprints" and isinstance(value, MediaFingerprint):
            return value.fingerprint_id
        if category == "comparisons" and isinstance(value, FingerprintComparison):
            return value.comparison_id
        if category == "watermark-plans" and isinstance(value, WatermarkPlan):
            return value.plan_id
        if category == "watermark-results" and isinstance(value, WatermarkResult):
            return value.result_id
        if category == "provenance-links" and isinstance(value, FingerprintProvenanceLink):
            return value.link_id
        raise TypeError(f"object type does not belong in media-fingerprints/{category}")

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise MediaFingerprintStoreError("invalid media-fingerprint object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise MediaFingerprintStoreError("media-fingerprint object may not be a symlink")
        if require_file and not path.is_file():
            raise MediaFingerprintStoreError("media-fingerprint object does not exist")
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MediaFingerprintStoreError("media-fingerprint object escaped protected root") from exc
        if resolved != expected:
            raise MediaFingerprintStoreError("media-fingerprint object path is aliased")
        return path

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id = self._object_id(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise MediaFingerprintStoreError("object ID has wrong category prefix")
        existing = tuple(directory.glob("*.json"))
        if len(existing) >= _MAX_OBJECTS_PER_CATEGORY:
            raise MediaFingerprintStoreError(f"{category} object-count limit reached")
        payload = value.to_dict()  # type: ignore[attr-defined]
        expected_hash = value.content_hash  # type: ignore[attr-defined]
        if content_hash(payload) != expected_hash:
            raise MediaFingerprintStoreError("object hash disagrees with canonical payload")
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": expected_hash,
            "payload": payload,
        }
        data = canonical_bytes(envelope)
        if not data or len(data) > _MAX_OBJECT_BYTES:
            raise MediaFingerprintStoreError("object byte size is outside bounds")
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise MediaFingerprintStoreError("media-fingerprint object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise MediaFingerprintStoreError("media-fingerprint object already exists") from exc
        return self._exact_path(category, object_id, require_file=True)

    def load(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise MediaFingerprintStoreError("object byte size is outside bounds")
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MediaFingerprintStoreError("object is not strict UTF-8 JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise MediaFingerprintStoreError("object envelope schema drifted")
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise MediaFingerprintStoreError("object envelope binding drifted")
        actual_hash = content_hash(envelope["payload"])
        if envelope["content_hash"] != actual_hash:
            raise MediaFingerprintStoreError("object content hash drifted")
        if canonical_bytes(envelope) != raw:
            raise MediaFingerprintStoreError("object bytes are not canonical")
        return envelope

    def list_objects(self, category: str) -> tuple[dict[str, str], ...]:
        directory = self._category_dir(category, create=False)
        if not directory.exists():
            return ()
        paths = sorted(directory.glob("*.json"), key=lambda value: value.name)
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise MediaFingerprintStoreError(f"{category} object-count limit exceeded")
        rows: list[dict[str, str]] = []
        for path in paths:
            if path.is_symlink():
                raise MediaFingerprintStoreError("listing contains a symlink")
            envelope = self.load(category, path.stem)
            rows.append({"object_id": path.stem, "content_hash": envelope["content_hash"]})
        return tuple(rows)

    def publish_fingerprint(self, value: MediaFingerprint) -> Path:
        return self._publish("fingerprints", value)

    def publish_comparison(self, value: FingerprintComparison) -> Path:
        return self._publish("comparisons", value)

    def publish_watermark_plan(self, value: WatermarkPlan) -> Path:
        return self._publish("watermark-plans", value)

    def publish_watermark_result(self, value: WatermarkResult) -> Path:
        return self._publish("watermark-results", value)

    def publish_provenance_link(self, value: FingerprintProvenanceLink) -> Path:
        return self._publish("provenance-links", value)
