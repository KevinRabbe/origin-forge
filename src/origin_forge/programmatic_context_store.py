from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import IdKind, validate_id
from .programmatic_context_benchmark import ContextExperimentReport
from .programmatic_context_models import (
    ContextExecutionTrace,
    ContextOperationCatalog,
    ContextPackage,
    ContextProgram,
    ContextRequest,
)
from .runtime import OriginForgeRuntime
from .runtime_observation_models import canonical_bytes, content_hash


_MAX_OBJECT_BYTES = 18 * 1024 * 1024
_MAX_OBJECTS_PER_CATEGORY = 10_000
_SCHEMA_VERSION = 1
_CATEGORY_KIND = {
    "requests": IdKind.CONTEXT_REQUEST,
    "catalogs": IdKind.CONTEXT_OPERATION_CATALOG,
    "programs": IdKind.CONTEXT_PROGRAM,
    "packages": IdKind.CONTEXT_PACKAGE,
    "executions": IdKind.CONTEXT_EXECUTION,
    "experiments": IdKind.CONTEXT_EXPERIMENT,
}


class ProgrammaticContextStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgrammaticContextStoreError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class ProgrammaticContextStore:
    """Protected immutable persistence for Phase-27 context evidence."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "programmatic-context"

    def _ensure_root(self) -> Path:
        state = self.runtime.state_dir.resolve(strict=True)
        if self.root.is_symlink():
            raise ProgrammaticContextStoreError("programmatic-context root may not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            root = self.root.resolve(strict=True)
            root.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProgrammaticContextStoreError(
                "programmatic-context root escaped protected project state"
            ) from exc
        return root

    def _category_dir(self, category: str, *, create: bool) -> Path:
        if category not in _CATEGORY_KIND:
            raise ProgrammaticContextStoreError("unknown programmatic-context category")
        root = self._ensure_root()
        directory = self.root / category
        if directory.is_symlink():
            raise ProgrammaticContextStoreError(f"{category} directory may not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            return directory
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProgrammaticContextStoreError(f"{category} directory escaped protected root") from exc
        return directory

    @staticmethod
    def _object_id(category: str, value: object) -> str:
        if category == "requests" and isinstance(value, ContextRequest):
            return value.request_id
        if category == "catalogs" and isinstance(value, ContextOperationCatalog):
            return value.catalog_id
        if category == "programs" and isinstance(value, ContextProgram):
            return value.program_id
        if category == "packages" and isinstance(value, ContextPackage):
            return value.package_id
        if category == "executions" and isinstance(value, ContextExecutionTrace):
            return value.execution_id
        if category == "experiments" and isinstance(value, ContextExperimentReport):
            return value.experiment_id
        raise TypeError(f"object type does not belong in programmatic-context/{category}")

    def _exact_path(self, category: str, object_id: str, *, require_file: bool) -> Path:
        kind = _CATEGORY_KIND.get(category)
        if kind is None or not validate_id(object_id, kind):
            raise ProgrammaticContextStoreError("invalid programmatic-context object ID")
        directory = self._category_dir(category, create=False)
        path = directory / f"{object_id}.json"
        if path.is_symlink():
            raise ProgrammaticContextStoreError("programmatic-context object may not be a symlink")
        if require_file and not path.is_file():
            raise ProgrammaticContextStoreError("programmatic-context object does not exist")
        if not path.exists():
            return path
        try:
            root = self.root.resolve(strict=True)
            expected = root / category / f"{object_id}.json"
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProgrammaticContextStoreError("programmatic-context object escaped protected root") from exc
        if resolved != expected:
            raise ProgrammaticContextStoreError("programmatic-context object path is aliased")
        return path

    def _publish(self, category: str, value: object) -> Path:
        directory = self._category_dir(category, create=True)
        object_id = self._object_id(category, value)
        if not validate_id(object_id, _CATEGORY_KIND[category]):
            raise ProgrammaticContextStoreError("object ID has wrong category prefix")
        existing = tuple(directory.glob("*.json"))
        if len(existing) >= _MAX_OBJECTS_PER_CATEGORY:
            raise ProgrammaticContextStoreError(f"{category} object-count limit reached")
        if not hasattr(value, "to_dict") or not hasattr(value, "content_hash"):
            raise TypeError("programmatic-context object lacks canonical serialization")
        payload = value.to_dict()  # type: ignore[attr-defined]
        expected_hash = value.content_hash  # type: ignore[attr-defined]
        if content_hash(payload) != expected_hash:
            raise ProgrammaticContextStoreError("object hash disagrees with canonical payload")
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "object_type": category,
            "object_id": object_id,
            "content_hash": expected_hash,
            "payload": payload,
        }
        data = canonical_bytes(envelope)
        if not data or len(data) > _MAX_OBJECT_BYTES:
            raise ProgrammaticContextStoreError("object byte size is outside bounds")
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            raise ProgrammaticContextStoreError("programmatic-context object already exists")
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProgrammaticContextStoreError("programmatic-context object already exists") from exc
        return self._exact_path(category, object_id, require_file=True)

    def load(self, category: str, object_id: str) -> dict[str, Any]:
        path = self._exact_path(category, object_id, require_file=True)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_OBJECT_BYTES:
            raise ProgrammaticContextStoreError("object byte size is outside bounds")
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProgrammaticContextStoreError("object is not strict UTF-8 JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema_version",
            "object_type",
            "object_id",
            "content_hash",
            "payload",
        }:
            raise ProgrammaticContextStoreError("object envelope schema drifted")
        if (
            envelope["schema_version"] != _SCHEMA_VERSION
            or envelope["object_type"] != category
            or envelope["object_id"] != object_id
            or not isinstance(envelope["payload"], dict)
        ):
            raise ProgrammaticContextStoreError("object envelope binding drifted")
        actual_hash = content_hash(envelope["payload"])
        if envelope["content_hash"] != actual_hash:
            raise ProgrammaticContextStoreError("object content hash drifted")
        if canonical_bytes(envelope) != raw:
            raise ProgrammaticContextStoreError("object bytes are not canonical")
        return envelope

    def list_objects(self, category: str) -> tuple[dict[str, str], ...]:
        directory = self._category_dir(category, create=False)
        if not directory.exists():
            return ()
        paths = sorted(directory.glob("*.json"), key=lambda value: value.name)
        if len(paths) > _MAX_OBJECTS_PER_CATEGORY:
            raise ProgrammaticContextStoreError(f"{category} object-count limit exceeded")
        rows: list[dict[str, str]] = []
        for path in paths:
            if path.is_symlink():
                raise ProgrammaticContextStoreError("listing contains a symlink")
            envelope = self.load(category, path.stem)
            rows.append({"object_id": path.stem, "content_hash": envelope["content_hash"]})
        return tuple(rows)

    def publish_request(self, value: ContextRequest) -> Path:
        return self._publish("requests", value)

    def publish_catalog(self, value: ContextOperationCatalog) -> Path:
        return self._publish("catalogs", value)

    def publish_program(self, value: ContextProgram) -> Path:
        return self._publish("programs", value)

    def publish_package(self, value: ContextPackage) -> Path:
        return self._publish("packages", value)

    def publish_execution(self, value: ContextExecutionTrace) -> Path:
        return self._publish("executions", value)

    def publish_experiment(self, value: ContextExperimentReport) -> Path:
        return self._publish("experiments", value)
