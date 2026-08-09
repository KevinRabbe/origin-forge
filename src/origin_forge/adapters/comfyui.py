from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import urlparse
from uuid import UUID

from ..image_png import decode_truecolor8_png
from ..image_vision_models import (
    ImageOperation,
    ImageOperationRequest,
    ImageOperationResult,
    ImageOutputEvidence,
    ImageResultStatus,
    canonical_bytes,
    canonical_hash,
    validate_sha256,
)
from ..pixelorama_png import PngError, encode_rgba8_png, inspect_rgba8_png
from ..runtime import OriginForgeRuntime


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_WORKFLOW_BYTES = 4 * 1024 * 1024


class ComfyUiError(RuntimeError):
    pass


class ComfyUiUnavailable(ComfyUiError):
    pass


class ComfyUiIntegrityError(ComfyUiError):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _token(value: str, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded portable token")
    return value


@dataclass(frozen=True)
class ComfyBinding:
    node_id: str
    input_name: str

    def __post_init__(self) -> None:
        _token(self.node_id, "Comfy binding node_id")
        _token(self.input_name, "Comfy binding input_name")


@dataclass(frozen=True)
class ComfyWorkflowBindings:
    positive_prompt: ComfyBinding
    seed: ComfyBinding
    steps: ComfyBinding
    guidance: ComfyBinding
    width: ComfyBinding
    height: ComfyBinding
    output_prefix: ComfyBinding
    negative_prompt: ComfyBinding | None = None

    def __post_init__(self) -> None:
        required = (
            self.positive_prompt,
            self.seed,
            self.steps,
            self.guidance,
            self.width,
            self.height,
            self.output_prefix,
        )
        if any(not isinstance(value, ComfyBinding) for value in required):
            raise TypeError("Comfy workflow bindings must be ComfyBinding values")
        if self.negative_prompt is not None and not isinstance(
            self.negative_prompt, ComfyBinding
        ):
            raise TypeError("negative_prompt binding must be a ComfyBinding or None")


@dataclass(frozen=True)
class ComfyWorkflowTemplate:
    workflow_id: str
    backend_version: str
    model_id: str
    model_hash: str
    workflow: Mapping[str, object]
    bindings: ComfyWorkflowBindings
    output_node_id: str
    operation: ImageOperation = ImageOperation.GENERATE

    def __post_init__(self) -> None:
        _token(self.workflow_id, "workflow_id")
        if (
            not isinstance(self.backend_version, str)
            or not self.backend_version.strip()
            or len(self.backend_version) > 128
            or "\x00" in self.backend_version
        ):
            raise ValueError("backend_version must be bounded non-empty text")
        if not isinstance(self.model_id, str) or not self.model_id.strip() or len(self.model_id) > 256:
            raise ValueError("model_id must be bounded non-empty text")
        validate_sha256(self.model_hash, "Comfy workflow model_hash")
        if not isinstance(self.operation, ImageOperation):
            raise TypeError("operation must be an ImageOperation")
        if self.operation is not ImageOperation.GENERATE:
            raise ValueError("initial ComfyUI template surface supports GENERATE only")
        if not isinstance(self.bindings, ComfyWorkflowBindings):
            raise TypeError("bindings must be ComfyWorkflowBindings")
        _token(self.output_node_id, "output_node_id")
        if not isinstance(self.workflow, Mapping) or not self.workflow:
            raise ValueError("workflow must be a non-empty mapping")
        try:
            frozen = json.loads(canonical_bytes(dict(self.workflow)).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("workflow must be canonical JSON data") from exc
        if len(canonical_bytes(frozen)) > _MAX_WORKFLOW_BYTES:
            raise ValueError("workflow exceeds byte limit")
        if not isinstance(frozen, dict):
            raise ValueError("workflow must serialize to a JSON object")
        for node_id, node in frozen.items():
            _token(node_id, "workflow node_id")
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                raise ValueError("every workflow node must be an object with inputs")
            if not isinstance(node.get("class_type"), str) or not node["class_type"].strip():
                raise ValueError("every workflow node must declare class_type")
        if self.output_node_id not in frozen:
            raise ValueError("output_node_id is not present in workflow")
        for binding in self._all_bindings():
            node = frozen.get(binding.node_id)
            if not isinstance(node, dict):
                raise ValueError(f"workflow binding node is missing: {binding.node_id}")
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or binding.input_name not in inputs:
                raise ValueError(
                    f"workflow binding input is missing: {binding.node_id}.{binding.input_name}"
                )
        object.__setattr__(self, "workflow", frozen)

    def _all_bindings(self) -> tuple[ComfyBinding, ...]:
        values = [
            self.bindings.positive_prompt,
            self.bindings.seed,
            self.bindings.steps,
            self.bindings.guidance,
            self.bindings.width,
            self.bindings.height,
            self.bindings.output_prefix,
        ]
        if self.bindings.negative_prompt is not None:
            values.append(self.bindings.negative_prompt)
        return tuple(values)

    @property
    def workflow_hash(self) -> str:
        return canonical_hash(self.workflow)

    @staticmethod
    def _set(workflow: dict[str, object], binding: ComfyBinding, value: object) -> None:
        node = workflow[binding.node_id]
        assert isinstance(node, dict)
        inputs = node["inputs"]
        assert isinstance(inputs, dict)
        inputs[binding.input_name] = value

    def render(self, request: ImageOperationRequest) -> dict[str, object]:
        if request.operation is not self.operation:
            raise ComfyUiIntegrityError("request operation does not match trusted workflow")
        if request.workflow_id != self.workflow_id or request.workflow_hash != self.workflow_hash:
            raise ComfyUiIntegrityError("request does not bind trusted workflow identity")
        if request.backend_version != self.backend_version:
            raise ComfyUiIntegrityError("request backend version does not match workflow")
        if request.model_id != self.model_id or request.model_hash != self.model_hash:
            raise ComfyUiIntegrityError("request model identity does not match workflow")
        workflow = deepcopy(dict(self.workflow))
        self._set(workflow, self.bindings.positive_prompt, request.prompt)
        if self.bindings.negative_prompt is not None:
            self._set(workflow, self.bindings.negative_prompt, request.negative_prompt)
        elif request.negative_prompt:
            raise ComfyUiIntegrityError(
                "request supplies negative prompt but trusted workflow has no binding"
            )
        self._set(workflow, self.bindings.seed, request.seed)
        self._set(workflow, self.bindings.steps, request.steps)
        self._set(workflow, self.bindings.guidance, request.guidance_scale)
        self._set(workflow, self.bindings.width, request.width)
        self._set(workflow, self.bindings.height, request.height)
        self._set(
            workflow,
            self.bindings.output_prefix,
            f"origin_forge_{request.operation_id.removeprefix('IMGOP-')}",
        )
        return workflow


@dataclass(frozen=True)
class ComfyUiProfile:
    base_url: str = "http://127.0.0.1:8188"
    expected_version: str = "0.0.0"
    allow_remote: bool = False
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: float = 0.1
    max_json_bytes: int = 4 * 1024 * 1024
    max_image_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ComfyUI base_url must be an http(s) URL")
        if not self.allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "remote ComfyUI endpoints are disabled; set allow_remote=True explicitly"
            )
        if (
            not isinstance(self.expected_version, str)
            or not self.expected_version.strip()
            or len(self.expected_version) > 128
            or "\x00" in self.expected_version
        ):
            raise ValueError("expected_version must be bounded non-empty text")
        for value, field in (
            (self.request_timeout_seconds, "request_timeout_seconds"),
            (self.poll_interval_seconds, "poll_interval_seconds"),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field} must be positive")
        for value, field, maximum in (
            (self.max_json_bytes, "max_json_bytes", 16 * 1024 * 1024),
            (self.max_image_bytes, "max_image_bytes", 128 * 1024 * 1024),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise ValueError(f"{field} is outside the allowed range")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


@dataclass(frozen=True)
class ComfyUiExecution:
    request: ImageOperationRequest
    result: ImageOperationResult
    workspace_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.request.operation_id,
            "workspace_id": self.request.workspace_id,
            "request_hash": self.request.content_hash,
            "result_hash": self.result.content_hash,
            "status": self.result.status.value,
            "backend_id": self.result.backend_id,
            "backend_version": self.result.backend_version,
            "workflow_hash": self.result.workflow_hash,
            "model_id": self.result.model_id,
            "model_hash": self.result.model_hash,
            "production_verification_changed": False,
            "canonical_asset_adopted": False,
        }


class ComfyUiAdapter:
    """Run one trusted ComfyUI workflow through the bounded local HTTP API."""

    BACKEND_ID = "comfyui"

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        profile: ComfyUiProfile,
        template: ComfyWorkflowTemplate,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(profile, ComfyUiProfile):
            raise TypeError("profile must be a ComfyUiProfile")
        if not isinstance(template, ComfyWorkflowTemplate):
            raise TypeError("template must be a ComfyWorkflowTemplate")
        if profile.expected_version != template.backend_version:
            raise ValueError("ComfyUI profile/template versions must match")
        self.runtime = runtime
        self.profile = profile
        self.template = template
        self.workspace_root = runtime.state_dir / "image-workspaces"
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def _read_response(self, response, maximum: int, label: str) -> bytes:
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise ComfyUiIntegrityError(f"{label} exceeds byte limit")
        return raw

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        maximum: int | None = None,
    ) -> object:
        data = None if payload is None else canonical_bytes(payload)
        request = urllib.request.Request(
            f"{self.profile.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        limit = maximum or self.profile.max_json_bytes
        try:
            with self._opener.open(
                request, timeout=self.profile.request_timeout_seconds
            ) as response:
                raw = self._read_response(response, limit, "ComfyUI JSON response")
        except urllib.error.HTTPError as exc:
            detail = exc.read(min(limit, 4096)).decode("utf-8", errors="replace")
            raise ComfyUiUnavailable(
                f"ComfyUI returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ComfyUiUnavailable(f"ComfyUI request failed: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ComfyUiIntegrityError("ComfyUI returned invalid JSON") from exc

    def _request_bytes(self, path: str, maximum: int) -> bytes:
        request = urllib.request.Request(
            f"{self.profile.base_url}{path}", method="GET"
        )
        try:
            with self._opener.open(
                request, timeout=self.profile.request_timeout_seconds
            ) as response:
                return self._read_response(response, maximum, "ComfyUI image response")
        except urllib.error.HTTPError as exc:
            raise ComfyUiUnavailable(
                f"ComfyUI image request returned HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ComfyUiUnavailable(
                f"ComfyUI image request failed: {exc.reason}"
            ) from exc

    def _verify_server_version(self) -> None:
        value = self._request_json("GET", "/system_stats")
        try:
            version = value["system"]["comfyui_version"]
        except (KeyError, TypeError) as exc:
            raise ComfyUiIntegrityError(
                "ComfyUI system_stats omitted comfyui_version"
            ) from exc
        if version != self.profile.expected_version:
            raise ComfyUiIntegrityError(
                f"ComfyUI version mismatch ({version!r} != {self.profile.expected_version!r})"
            )

    def _workspace(self, request: ImageOperationRequest) -> Path:
        state = self.runtime.state_dir.resolve()
        if self.workspace_root.is_symlink():
            raise ComfyUiIntegrityError("image workspace root may not be a symlink")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_root.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ComfyUiIntegrityError(
                "image workspace root escapes protected project state"
            ) from exc
        workspace = self.workspace_root / request.workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise ComfyUiIntegrityError(
                f"image workspace already exists: {request.workspace_id}"
            )
        workspace.mkdir()
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir()
        return workspace

    @staticmethod
    def _write_request(workspace: Path, request: ImageOperationRequest) -> None:
        path = workspace / "request" / "request.json"
        with path.open("xb") as handle:
            handle.write(canonical_bytes(request.to_dict()))

    @staticmethod
    def _uuid_from_id(value: str) -> str:
        try:
            return str(UUID(value.rsplit("-", 5)[-5] + "-" + "-".join(value.rsplit("-", 5)[-4:])))
        except (ValueError, IndexError) as exc:
            # IDs are already validated by ImageOperationRequest; keep this failure explicit.
            raise ComfyUiIntegrityError("failed to derive ComfyUI UUID from operation ID") from exc

    @staticmethod
    def _suffix_uuid(value: str) -> str:
        prefix, _, suffix = value.partition("-")
        if not prefix or not suffix:
            raise ComfyUiIntegrityError("invalid infrastructure ID for ComfyUI prompt")
        try:
            return str(UUID(suffix))
        except ValueError as exc:
            raise ComfyUiIntegrityError("invalid UUID suffix for ComfyUI prompt") from exc

    def _queue(self, request: ImageOperationRequest, workflow: dict[str, object]) -> str:
        prompt_id = self._suffix_uuid(request.operation_id)
        client_id = self._suffix_uuid(request.workspace_id)
        value = self._request_json(
            "POST",
            "/prompt",
            payload={
                "prompt": workflow,
                "client_id": client_id,
                "prompt_id": prompt_id,
            },
        )
        if not isinstance(value, dict) or value.get("prompt_id") != prompt_id:
            raise ComfyUiIntegrityError("ComfyUI did not bind queued prompt_id")
        node_errors = value.get("node_errors", {})
        if not isinstance(node_errors, dict) or node_errors:
            raise ComfyUiIntegrityError("ComfyUI reported workflow validation errors")
        return prompt_id

    def _wait_history(self, prompt_id: str, request: ImageOperationRequest) -> dict[str, object]:
        deadline = time.monotonic() + request.budget.timeout_seconds
        encoded = urllib.parse.quote(prompt_id, safe="")
        while True:
            value = self._request_json(
                "GET",
                f"/history/{encoded}",
                maximum=min(request.budget.max_history_bytes, self.profile.max_json_bytes),
            )
            if not isinstance(value, dict):
                raise ComfyUiIntegrityError("ComfyUI history response must be an object")
            entry = value.get(prompt_id)
            if entry is not None:
                if not isinstance(entry, dict):
                    raise ComfyUiIntegrityError("ComfyUI history entry must be an object")
                return entry
            if time.monotonic() >= deadline:
                raise ComfyUiUnavailable("ComfyUI operation exceeded timeout")
            time.sleep(self.profile.poll_interval_seconds)

    @staticmethod
    def _history_images(entry: dict[str, object], output_node_id: str) -> tuple[dict[str, str], ...]:
        outputs = entry.get("outputs")
        if not isinstance(outputs, dict):
            raise ComfyUiIntegrityError("ComfyUI history omitted outputs")
        node = outputs.get(output_node_id)
        if not isinstance(node, dict):
            raise ComfyUiIntegrityError("ComfyUI history omitted trusted output node")
        images = node.get("images")
        if not isinstance(images, list):
            raise ComfyUiIntegrityError("ComfyUI trusted output node omitted images")
        normalized: list[dict[str, str]] = []
        for item in images:
            if not isinstance(item, dict):
                raise ComfyUiIntegrityError("ComfyUI image metadata must be an object")
            filename = item.get("filename")
            subfolder = item.get("subfolder", "")
            folder_type = item.get("type")
            if not isinstance(filename, str) or not filename or len(filename) > 512:
                raise ComfyUiIntegrityError("ComfyUI output filename is invalid")
            if filename != PurePosixPath(filename).name or "\\" in filename or ".." in filename:
                raise ComfyUiIntegrityError("ComfyUI output filename is not a safe basename")
            if not isinstance(subfolder, str) or len(subfolder) > 1024 or "\\" in subfolder:
                raise ComfyUiIntegrityError("ComfyUI output subfolder is invalid")
            if subfolder:
                parts = PurePosixPath(subfolder).parts
                if PurePosixPath(subfolder).is_absolute() or any(part in {"", ".", ".."} for part in parts):
                    raise ComfyUiIntegrityError("ComfyUI output subfolder is not portable")
            if folder_type != "output":
                raise ComfyUiIntegrityError("ComfyUI output must come from output storage")
            normalized.append(
                {"filename": filename, "subfolder": subfolder, "type": "output"}
            )
        return tuple(normalized)

    def _download_outputs(
        self,
        workspace: Path,
        request: ImageOperationRequest,
        images: tuple[dict[str, str], ...],
    ) -> tuple[ImageOutputEvidence, ...]:
        if len(images) != len(request.output_relative_paths):
            raise ComfyUiIntegrityError("ComfyUI output count does not match request")
        evidence: list[ImageOutputEvidence] = []
        retrieved_total = 0
        normalized_total = 0
        exports_root = (workspace / "exports").resolve(strict=True)
        for metadata, relative_path in zip(images, request.output_relative_paths, strict=True):
            query = urllib.parse.urlencode(metadata)
            maximum = min(self.profile.max_image_bytes, request.budget.max_output_bytes)
            backend_data = self._request_bytes(f"/view?{query}", maximum)
            retrieved_total += len(backend_data)
            if retrieved_total > request.budget.max_output_bytes:
                raise ComfyUiIntegrityError("ComfyUI outputs exceed retrieval byte budget")
            try:
                decoded = decode_truecolor8_png(backend_data)
            except PngError as exc:
                raise ComfyUiIntegrityError(
                    f"ComfyUI returned invalid RGB/RGBA truecolor PNG output: {exc}"
                ) from exc
            if decoded.plane.width != request.width or decoded.plane.height != request.height:
                raise ComfyUiIntegrityError(
                    "ComfyUI output dimensions do not match frozen request"
                )
            data = encode_rgba8_png(decoded.plane)
            normalized_total += len(data)
            if normalized_total > request.budget.max_output_bytes:
                raise ComfyUiIntegrityError(
                    "normalized ComfyUI outputs exceed operation byte budget"
                )
            inspection = inspect_rgba8_png(data)
            target = workspace / Path(relative_path)
            if target.exists() or target.is_symlink():
                raise ComfyUiIntegrityError("declared image output already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.parent.is_symlink():
                raise ComfyUiIntegrityError("declared image output parent may not be a symlink")
            try:
                target.parent.resolve(strict=True).relative_to(exports_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ComfyUiIntegrityError("declared image output escaped workspace") from exc
            with target.open("xb") as handle:
                handle.write(data)
            resolved = target.resolve(strict=True)
            try:
                resolved.relative_to(exports_root)
            except ValueError as exc:
                raise ComfyUiIntegrityError("written image output escaped workspace") from exc
            content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
            evidence.append(
                ImageOutputEvidence(
                    relative_path=relative_path,
                    content_hash=content_hash,
                    pixel_hash=inspection.pixel_hash,
                    byte_count=len(data),
                    width=inspection.width,
                    height=inspection.height,
                )
            )
        actual = {
            path.relative_to(workspace).as_posix()
            for path in (workspace / "exports").rglob("*")
            if path.is_file()
        }
        if actual != set(request.output_relative_paths):
            raise ComfyUiIntegrityError("image workspace contains undeclared exports")
        return tuple(evidence)

    def execute(self, request: ImageOperationRequest) -> ComfyUiExecution:
        if not isinstance(request, ImageOperationRequest):
            raise TypeError("request must be an ImageOperationRequest")
        if request.backend_id != self.BACKEND_ID:
            raise ComfyUiIntegrityError("request backend_id is not comfyui")
        if request.backend_version != self.profile.expected_version:
            raise ComfyUiIntegrityError("request backend version does not match profile")
        if request.operation is not ImageOperation.GENERATE:
            raise ComfyUiIntegrityError(
                "initial ComfyUI adapter authorizes GENERATE only; EDIT remains separate"
            )
        if request.input_images:
            raise ComfyUiIntegrityError("initial ComfyUI generation adapter accepts no inputs")
        workflow = self.template.render(request)
        self._verify_server_version()
        workspace = self._workspace(request)
        self._write_request(workspace, request)
        prompt_id = self._queue(request, workflow)
        entry = self._wait_history(prompt_id, request)
        images = self._history_images(entry, self.template.output_node_id)
        outputs = self._download_outputs(workspace, request, images)
        result = ImageOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=ImageResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            workflow_hash=request.workflow_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=outputs,
        )
        result.bind_request(request)
        return ComfyUiExecution(request=request, result=result, workspace_path=workspace)
