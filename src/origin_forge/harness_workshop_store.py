from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .harness_workshop_audit import WorkshopDecision, WorkshopEvaluationAudit
from .harness_workshop_evaluation import WorkshopEvaluationReport
from .harness_workshop_models import (
    HarnessImprovementCandidate,
    HarnessWorkshopModelError,
    WorkshopEvaluationPlan,
)
from .harness_workshop_skill_adapter import SkillWorkshopEvaluation
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime
from .runtime_observation_models import canonical_bytes, content_hash


_MAX_OBJECT_BYTES = 512 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_SCHEMA_VERSION = 1

_CATEGORY_KIND = {
    "candidates": IdKind.IMPROVEMENT_CANDIDATE,
    "plans": IdKind.WORKSHOP_EVALUATION_PLAN,
    "reports": IdKind.WORKSHOP_EVALUATION_REPORT,
    "audits": IdKind.WORKSHOP_EVALUATION_AUDIT,
    "decisions": IdKind.WORKSHOP_DECISION,
}


class HarnessWorkshopStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessWorkshopStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class HarnessWorkshopStore:
    """Protected immutable persistence for Phase-26 workshop evidence."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "workshop"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise HarnessWorkshopStoreError("workshop root may not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HarnessWorkshopStoreError(
                "workshop root is outside protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise HarnessWorkshopStoreError("unknown workshop object category")
        root = self._ensure_root()
        directory = self.root / category
        if directory.is_symlink():
            raise HarnessWorkshopStoreError(
                f"workshop {category} directory may not be a symlink"
            )
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HarnessWorkshopStoreError(
                f"workshop {category} directory escaped protected root"
            ) from exc
        return directory

    @staticmethod
    def _object_id(
        category: str,
        value: HarnessImprovementCandidate
        | WorkshopEvaluationPlan
        | WorkshopEvaluationReport
        | SkillWorkshopEvaluation
        | WorkshopEvaluationAudit
        | WorkshopDecision,
    ) -> str:
        if category == "candidates" and isinstance(value, HarnessImprovementCandidate):
            return value.candidate_id
        if category == "plans" and isinstance(value, WorkshopEvaluationPlan):
            return value.plan_id
        if category == "reports" and isinstance(value, SkillWorkshopEvaluation):
            return value.report.report_id
        if category == "reports" and isinstance(value, WorkshopEvaluationReport):
            return value.report_id
        if category == "audits" and isinstance(value, WorkshopEvaluationAudit):
            return value.audit_id
        if category == "decisions" and isinstance(value, WorkshopDecision):
            return value.decision_id
        raise TypeError(f"object type does not belong in workshop/{category}")

    def _publish(
        self,
        category: str,
        value: HarnessImprovementCandidate
        | WorkshopEvaluationPlan
        | WorkshopEvaluationReport
        | SkillWorkshopEvaluation
        | WorkshopEvaluationAudit
        | WorkshopDecision,
    ) -> Path:
        directory = self._category_dir(category, create=True)
        object_id = self._object_id(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise HarnessWorkshopStoreError("workshop object ID has wrong category prefix")
        existing = tuple(directory.glob("*.json"))
        if len(existing) >= _MAX_OBJECTS_PER_CATEGORY:
            raise HarnessWorkshopStoreError(
                f"workshop {category} object-count limit reached"
            )
        payload = value.to_dict()
        expected_hash = value.content_hash
        if content_hash(payload) != expected_hash:
            raise HarnessWorkshopStoreError(
                "workshop object content hash disagrees with canonical payload"
            )
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": expected_hash,
            "payload": payload,
        }
        data = canonical_bytes(envelope)
        if len(data) > _MAX_OBJECT_BYTES:
            raise HarnessWorkshopStoreError("workshop object exceeds byte limit")
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise HarnessWorkshopStoreError("workshop object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise HarnessWorkshopStoreError("workshop object already exists") from exc
        return self._exact_path(category, object_id, require_file=True)

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise HarnessWorkshopStoreError("invalid workshop object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise HarnessWorkshopStoreError("workshop object may not be a symlink")
        if require_file and not path.is_file():
            raise HarnessWorkshopStoreError("workshop object does not exist")
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HarnessWorkshopStoreError(
                "workshop object escaped protected root"
            ) from exc
        if resolved != path:
            # Both are absolute after resolve only when the input was absolute; compare
            # the canonical expected path instead of permitting aliasing.
            expected = self.root.resolve(strict=True) / category / f"{object_id}.json"
            if resolved != expected:
                raise HarnessWorkshopStoreError("workshop object path is aliased")
        return path

    def load(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise HarnessWorkshopStoreError("workshop object size is outside bounds")
        try:
            raw = path.read_bytes()
            envelope = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_strict_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessWorkshopStoreError("workshop object is not strict UTF-8 JSON") from exc
        if not isinstance(envelope, dict):
            raise HarnessWorkshopStoreError("workshop object envelope must be an object")
        if set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise HarnessWorkshopStoreError("workshop object envelope schema drifted")
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise HarnessWorkshopStoreError("workshop object envelope binding drifted")
        actual_hash = content_hash(envelope["payload"])
        if envelope["content_hash"] != actual_hash:
            raise HarnessWorkshopStoreError("workshop object content hash drifted")
        if canonical_bytes(envelope) != raw:
            raise HarnessWorkshopStoreError("workshop object bytes are not canonical")
        return envelope

    def list_objects(self, category: str) -> tuple[dict[str, Any], ...]:
        directory = self._category_dir(category, create=False)
        if not directory.exists():
            return ()
        paths = sorted(directory.glob("*.json"), key=lambda value: value.name)
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise HarnessWorkshopStoreError(
                f"workshop {category} object-count limit exceeded"
            )
        rows: list[dict[str, Any]] = []
        for path in paths:
            if path.is_symlink():
                raise HarnessWorkshopStoreError("workshop listing contains a symlink")
            object_id = path.stem
            envelope = self.load(category, object_id)
            rows.append(
                {
                    "object_id": object_id,
                    "content_hash": envelope["content_hash"],
                }
            )
        return tuple(rows)

    def publish_candidate(self, value: HarnessImprovementCandidate) -> Path:
        return self._publish("candidates", value)

    def publish_plan(self, value: WorkshopEvaluationPlan) -> Path:
        return self._publish("plans", value)

    def publish_evaluation(
        self, value: WorkshopEvaluationReport | SkillWorkshopEvaluation
    ) -> Path:
        return self._publish("reports", value)

    def publish_audit(self, value: WorkshopEvaluationAudit) -> Path:
        return self._publish("audits", value)

    def publish_decision(self, value: WorkshopDecision) -> Path:
        return self._publish("decisions", value)
