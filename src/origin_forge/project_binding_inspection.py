from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .project_intelligence import ProjectIntelligenceService
from .project_models import BindingType


class BindingInspectionStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    UNPINNED = "UNPINNED"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID_PATH = "INVALID_PATH"
    TOO_LARGE = "TOO_LARGE"


@dataclass(frozen=True)
class BindingInspection:
    binding_id: str
    binding_type: str
    target_ref: str
    expected_hash: str | None
    current_hash: str | None
    status: BindingInspectionStatus
    bytes_read: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "binding_type": self.binding_type,
            "target_ref": self.target_ref,
            "expected_hash": self.expected_hash,
            "current_hash": self.current_hash,
            "status": self.status.value,
            "bytes_read": self.bytes_read,
            "canonical_binding_changed": False,
        }


class BindingInspector:
    """Read-only freshness inspection for file-backed Entity bindings."""

    def __init__(self, intelligence: ProjectIntelligenceService, *, max_file_bytes: int = 16 * 1024 * 1024):
        if not isinstance(intelligence, ProjectIntelligenceService):
            raise TypeError("intelligence must be a ProjectIntelligenceService")
        if not isinstance(max_file_bytes, int) or isinstance(max_file_bytes, bool) or max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be a positive integer")
        self.intelligence = intelligence
        self.max_file_bytes = max_file_bytes

    def _safe_path(self, target_ref: str) -> Path | None:
        root = self.intelligence.runtime.project_root.resolve()
        candidate = root / target_ref
        current = root
        for part in Path(target_ref).parts:
            current = current / part
            if current.is_symlink():
                return None
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate

    def inspect(self, binding_id: str) -> BindingInspection:
        binding = self.intelligence.get_binding(binding_id)
        binding_type = binding["binding_type"]
        expected_hash = binding["target_hash"]
        target_ref = binding["target_ref"]
        if binding_type != BindingType.FILE.value:
            return BindingInspection(
                binding_id,
                binding_type,
                target_ref,
                expected_hash,
                None,
                BindingInspectionStatus.UNSUPPORTED,
            )
        if expected_hash is None:
            return BindingInspection(
                binding_id,
                binding_type,
                target_ref,
                None,
                None,
                BindingInspectionStatus.UNPINNED,
            )
        path = self._safe_path(target_ref)
        if path is None:
            return BindingInspection(
                binding_id,
                binding_type,
                target_ref,
                expected_hash,
                None,
                BindingInspectionStatus.INVALID_PATH,
            )
        if not path.exists():
            return BindingInspection(
                binding_id,
                binding_type,
                target_ref,
                expected_hash,
                None,
                BindingInspectionStatus.MISSING,
            )
        if not path.is_file():
            return BindingInspection(
                binding_id,
                binding_type,
                target_ref,
                expected_hash,
                None,
                BindingInspectionStatus.INVALID_PATH,
            )
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(min(1024 * 1024, self.max_file_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_file_bytes:
                    return BindingInspection(
                        binding_id,
                        binding_type,
                        target_ref,
                        expected_hash,
                        None,
                        BindingInspectionStatus.TOO_LARGE,
                        total,
                    )
                digest.update(chunk)
        current_hash = "sha256:" + digest.hexdigest()
        status = (
            BindingInspectionStatus.CURRENT
            if current_hash == expected_hash
            else BindingInspectionStatus.STALE
        )
        return BindingInspection(
            binding_id,
            binding_type,
            target_ref,
            expected_hash,
            current_hash,
            status,
            total,
        )
