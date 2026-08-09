from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .adapters.comfyui import (
    ComfyBinding,
    ComfyWorkflowBindings,
    ComfyWorkflowTemplate,
)
from .image_vision_models import ImageOperation, canonical_bytes, canonical_hash, validate_sha256
from .runtime import OriginForgeRuntime


_MAX_TEMPLATE_BYTES = 8 * 1024 * 1024
_MAX_TEMPLATES = 256


class ImageWorkflowError(RuntimeError):
    pass


def _binding_dict(value: ComfyBinding | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {"node_id": value.node_id, "input_name": value.input_name}


def _bindings_dict(value: ComfyWorkflowBindings) -> dict[str, object]:
    return {
        "positive_prompt": _binding_dict(value.positive_prompt),
        "negative_prompt": _binding_dict(value.negative_prompt),
        "seed": _binding_dict(value.seed),
        "steps": _binding_dict(value.steps),
        "guidance": _binding_dict(value.guidance),
        "width": _binding_dict(value.width),
        "height": _binding_dict(value.height),
        "output_prefix": _binding_dict(value.output_prefix),
    }


class GovernedComfyWorkflowTemplate(ComfyWorkflowTemplate):
    """ComfyUI template whose identity includes every trusted mutation/read binding."""

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "workflow_id": self.workflow_id,
            "backend_id": "comfyui",
            "backend_version": self.backend_version,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "operation": self.operation.value,
            "output_node_id": self.output_node_id,
            "bindings": _bindings_dict(self.bindings),
            "api_workflow": self.workflow,
        }

    @property
    def workflow_hash(self) -> str:
        return canonical_hash(self.semantic_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.semantic_dict()
        value["workflow_hash"] = self.workflow_hash
        return value


@dataclass(frozen=True)
class StoredImageWorkflow:
    workflow_id: str
    workflow_hash: str
    path: Path
    byte_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_hash": self.workflow_hash,
            "path": self.path.as_posix(),
            "byte_count": self.byte_count,
        }


class ImageWorkflowStore:
    """Protected immutable registry for reviewed image workflow templates."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_template_bytes: int = _MAX_TEMPLATE_BYTES,
        max_templates: int = _MAX_TEMPLATES,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if (
            not isinstance(max_template_bytes, int)
            or isinstance(max_template_bytes, bool)
            or not 1 <= max_template_bytes <= _MAX_TEMPLATE_BYTES
        ):
            raise ValueError("max_template_bytes is outside the allowed range")
        if (
            not isinstance(max_templates, int)
            or isinstance(max_templates, bool)
            or not 1 <= max_templates <= _MAX_TEMPLATES
        ):
            raise ValueError("max_templates is outside the allowed range")
        self.runtime = runtime
        self.root = runtime.state_dir / "image-workflows"
        self.max_template_bytes = max_template_bytes
        self.max_templates = max_templates

    def _root(self, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.root.is_symlink():
            raise ImageWorkflowError("image workflow store root may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            return self.root
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImageWorkflowError(
                "image workflow store root escapes protected project state"
            ) from exc
        if not resolved.is_dir():
            raise ImageWorkflowError("image workflow store root must be a directory")
        return resolved

    @staticmethod
    def _object_name(workflow_id: str, workflow_hash: str) -> str:
        validate_sha256(workflow_hash, "workflow_hash")
        digest = workflow_hash.removeprefix("sha256:")
        return f"{workflow_id}--{digest}.json"

    def _catalog(self) -> tuple[Path, ...]:
        root = self._root(create=False)
        if not root.exists():
            return ()
        entries: list[Path] = []
        for path in root.iterdir():
            if path.is_symlink():
                raise ImageWorkflowError("image workflow store contains a symlink")
            if not path.is_file() or path.suffix != ".json":
                raise ImageWorkflowError("image workflow store contains an undeclared entry")
            entries.append(path)
            if len(entries) > self.max_templates:
                raise ImageWorkflowError("image workflow catalog exceeds item limit")
        return tuple(sorted(entries, key=lambda value: value.name))

    def put(self, template: GovernedComfyWorkflowTemplate) -> StoredImageWorkflow:
        if not isinstance(template, GovernedComfyWorkflowTemplate):
            raise TypeError("template must be a GovernedComfyWorkflowTemplate")
        root = self._root(create=True)
        catalog = self._catalog()
        name = self._object_name(template.workflow_id, template.workflow_hash)
        target = root / name
        data = canonical_bytes(template.to_dict())
        if len(data) > self.max_template_bytes:
            raise ImageWorkflowError("image workflow template exceeds byte limit")
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise ImageWorkflowError("image workflow target is unsafe")
            existing = target.read_bytes()
            if existing != data:
                raise ImageWorkflowError(
                    "image workflow content-addressed target contains different bytes"
                )
            return StoredImageWorkflow(
                template.workflow_id,
                template.workflow_hash,
                target,
                len(data),
            )
        if len(catalog) >= self.max_templates:
            raise ImageWorkflowError("image workflow catalog is full")
        temp = root / f".{name}.{os.getpid()}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                    raise ImageWorkflowError(
                        "competing image workflow publication produced different bytes"
                    )
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return StoredImageWorkflow(
            template.workflow_id,
            template.workflow_hash,
            target,
            len(data),
        )

    @staticmethod
    def _parse_binding(value: object, field: str, *, optional: bool = False) -> ComfyBinding | None:
        if value is None and optional:
            return None
        if not isinstance(value, dict) or set(value) != {"node_id", "input_name"}:
            raise ImageWorkflowError(f"stored {field} binding is invalid")
        try:
            return ComfyBinding(value["node_id"], value["input_name"])
        except (TypeError, ValueError) as exc:
            raise ImageWorkflowError(f"stored {field} binding is invalid") from exc

    @classmethod
    def _parse(cls, value: object) -> GovernedComfyWorkflowTemplate:
        if not isinstance(value, dict):
            raise ImageWorkflowError("stored image workflow must be an object")
        expected = {
            "schema_version",
            "workflow_id",
            "backend_id",
            "backend_version",
            "model_id",
            "model_hash",
            "operation",
            "output_node_id",
            "bindings",
            "api_workflow",
            "workflow_hash",
        }
        if set(value) != expected or value.get("schema_version") != 1:
            raise ImageWorkflowError("stored image workflow has unknown or missing fields")
        if value.get("backend_id") != "comfyui":
            raise ImageWorkflowError("stored image workflow backend is not comfyui")
        bindings = value.get("bindings")
        if not isinstance(bindings, dict) or set(bindings) != {
            "positive_prompt",
            "negative_prompt",
            "seed",
            "steps",
            "guidance",
            "width",
            "height",
            "output_prefix",
        }:
            raise ImageWorkflowError("stored image workflow bindings are invalid")
        try:
            operation = ImageOperation(value["operation"])
            template = GovernedComfyWorkflowTemplate(
                workflow_id=value["workflow_id"],
                backend_version=value["backend_version"],
                model_id=value["model_id"],
                model_hash=value["model_hash"],
                workflow=value["api_workflow"],
                bindings=ComfyWorkflowBindings(
                    positive_prompt=cls._parse_binding(bindings["positive_prompt"], "positive_prompt"),
                    negative_prompt=cls._parse_binding(
                        bindings["negative_prompt"], "negative_prompt", optional=True
                    ),
                    seed=cls._parse_binding(bindings["seed"], "seed"),
                    steps=cls._parse_binding(bindings["steps"], "steps"),
                    guidance=cls._parse_binding(bindings["guidance"], "guidance"),
                    width=cls._parse_binding(bindings["width"], "width"),
                    height=cls._parse_binding(bindings["height"], "height"),
                    output_prefix=cls._parse_binding(bindings["output_prefix"], "output_prefix"),
                ),
                output_node_id=value["output_node_id"],
                operation=operation,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ImageWorkflowError("stored image workflow is invalid") from exc
        if value["workflow_hash"] != template.workflow_hash:
            raise ImageWorkflowError("stored image workflow hash mismatch")
        return template

    def get(
        self,
        workflow_id: str,
        workflow_hash: str,
    ) -> GovernedComfyWorkflowTemplate:
        name = self._object_name(workflow_id, workflow_hash)
        root = self._root(create=False)
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise KeyError((workflow_id, workflow_hash))
        if path.stat().st_size > self.max_template_bytes:
            raise ImageWorkflowError("stored image workflow exceeds byte limit")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageWorkflowError("stored image workflow is not valid UTF-8 JSON") from exc
        template = self._parse(value)
        if template.workflow_id != workflow_id or template.workflow_hash != workflow_hash:
            raise ImageWorkflowError("stored image workflow identity mismatch")
        return template

    def list(self) -> tuple[StoredImageWorkflow, ...]:
        result: list[StoredImageWorkflow] = []
        for path in self._catalog():
            if path.stat().st_size > self.max_template_bytes:
                raise ImageWorkflowError("stored image workflow exceeds byte limit")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                template = self._parse(value)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ImageWorkflowError("stored image workflow is invalid") from exc
            expected_name = self._object_name(template.workflow_id, template.workflow_hash)
            if path.name != expected_name:
                raise ImageWorkflowError("stored image workflow filename/identity mismatch")
            result.append(
                StoredImageWorkflow(
                    template.workflow_id,
                    template.workflow_hash,
                    path,
                    path.stat().st_size,
                )
            )
        return tuple(result)
