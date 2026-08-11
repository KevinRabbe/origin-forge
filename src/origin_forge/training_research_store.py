from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime
from .runtime_observation_models import canonical_bytes, content_hash
from .training_research_models import (
    TrainingDatasetManifest,
    TrainingEligibilityAudit,
    TrainingExperimentPlan,
    TrainingExperimentReport,
    TrainingResearchModelError,
    TrainingTrajectory,
)


_SCHEMA_VERSION = 1
_MAX_OBJECT_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 100_000
_CATEGORY_KIND = {
    "trajectories": IdKind.TRAINING_TRAJECTORY,
    "eligibility-audits": IdKind.TRAINING_ELIGIBILITY_AUDIT,
    "datasets": IdKind.TRAINING_DATASET,
    "experiment-plans": IdKind.TRAINING_EXPERIMENT_PLAN,
    "experiment-reports": IdKind.TRAINING_EXPERIMENT_REPORT,
}


class TrainingResearchStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrainingResearchStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class TrainingResearchStore:
    """Protected immutable persistence for Phase-29 research evidence."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "training-research"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise TrainingResearchStoreError("training-research root may not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TrainingResearchStoreError(
                "training-research root escaped protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise TrainingResearchStoreError("unknown training-research category")
        root = self._ensure_root()
        directory = self.root / category
        if directory.is_symlink():
            raise TrainingResearchStoreError(f"{category} directory may not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TrainingResearchStoreError(f"{category} directory escaped protected root") from exc
        return directory

    @staticmethod
    def _object_id(category: str, value: object) -> str:
        if category == "trajectories" and isinstance(value, TrainingTrajectory):
            return value.trajectory_id
        if category == "eligibility-audits" and isinstance(value, TrainingEligibilityAudit):
            return value.audit_id
        if category == "datasets" and isinstance(value, TrainingDatasetManifest):
            return value.dataset_id
        if category == "experiment-plans" and isinstance(value, TrainingExperimentPlan):
            return value.plan_id
        if category == "experiment-reports" and isinstance(value, TrainingExperimentReport):
            return value.report_id
        raise TypeError(f"object type does not belong in training-research/{category}")

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise TrainingResearchStoreError("invalid training-research object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise TrainingResearchStoreError("training-research object may not be a symlink")
        if require_file and not path.is_file():
            raise TrainingResearchStoreError("training-research object does not exist")
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TrainingResearchStoreError("training-research object escaped protected root") from exc
        if resolved != expected:
            raise TrainingResearchStoreError("training-research object path is aliased")
        return path

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id = self._object_id(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise TrainingResearchStoreError("object ID has wrong category prefix")
        existing = tuple(directory.glob("*.json"))
        if len(existing) >= _MAX_OBJECTS_PER_CATEGORY:
            raise TrainingResearchStoreError(f"{category} object-count limit reached")
        if not hasattr(value, "to_dict") or not hasattr(value, "content_hash"):
            raise TypeError("training-research object lacks canonical serialization")
        payload = value.to_dict()  # type: ignore[attr-defined]
        expected_hash = value.content_hash  # type: ignore[attr-defined]
        if content_hash(payload) != expected_hash:
            raise TrainingResearchStoreError("object hash disagrees with canonical payload")
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": expected_hash,
            "payload": payload,
        }
        data = canonical_bytes(envelope)
        if not data or len(data) > _MAX_OBJECT_BYTES:
            raise TrainingResearchStoreError("object byte size is outside bounds")
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise TrainingResearchStoreError("training-research object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise TrainingResearchStoreError("training-research object already exists") from exc
        return self._exact_path(category, object_id, require_file=True)

    def load(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise TrainingResearchStoreError("object byte size is outside bounds")
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrainingResearchStoreError("object is not strict UTF-8 JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise TrainingResearchStoreError("object envelope schema drifted")
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise TrainingResearchStoreError("object envelope binding drifted")
        actual_hash = content_hash(envelope["payload"])
        if envelope["content_hash"] != actual_hash:
            raise TrainingResearchStoreError("object content hash drifted")
        if canonical_bytes(envelope) != raw:
            raise TrainingResearchStoreError("object bytes are not canonical")
        return envelope

    def list_objects(self, category: str) -> tuple[dict[str, str], ...]:
        directory = self._category_dir(category, create=False)
        if not directory.exists():
            return ()
        paths = sorted(directory.glob("*.json"), key=lambda value: value.name)
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise TrainingResearchStoreError(f"{category} object-count limit exceeded")
        rows: list[dict[str, str]] = []
        for path in paths:
            if path.is_symlink():
                raise TrainingResearchStoreError("listing contains a symlink")
            envelope = self.load(category, path.stem)
            rows.append({"object_id": path.stem, "content_hash": envelope["content_hash"]})
        return tuple(rows)

    def publish_trajectory(self, value: TrainingTrajectory) -> Path:
        return self._publish("trajectories", value)

    def publish_eligibility_audit(
        self,
        value: TrainingEligibilityAudit,
        *,
        trajectory: TrainingTrajectory,
    ) -> Path:
        value.bind(trajectory)
        return self._publish("eligibility-audits", value)

    def publish_dataset(
        self,
        value: TrainingDatasetManifest,
        *,
        trajectories: Iterable[TrainingTrajectory],
        audits: Iterable[TrainingEligibilityAudit],
    ) -> Path:
        trajectory_values = tuple(trajectories)
        audit_values = tuple(audits)
        expected = TrainingDatasetManifest.create(
            trajectories=trajectory_values,
            audits=audit_values,
            policy_id=value.policy_id,
            policy_version=value.policy_version,
            policy_fingerprint=value.policy_fingerprint,
            split_salt_hash=value.split_salt_hash,
        )
        if expected.entries != value.entries:
            raise TrainingResearchModelError(
                "dataset entries do not match revalidated trajectory/audit evidence"
            )
        return self._publish("datasets", value)

    def publish_experiment_plan(
        self,
        value: TrainingExperimentPlan,
        *,
        dataset: TrainingDatasetManifest,
    ) -> Path:
        value.bind_dataset(dataset)
        return self._publish("experiment-plans", value)

    def publish_experiment_report(
        self,
        value: TrainingExperimentReport,
        *,
        plan: TrainingExperimentPlan,
    ) -> Path:
        value.bind_plan(plan)
        return self._publish("experiment-reports", value)
