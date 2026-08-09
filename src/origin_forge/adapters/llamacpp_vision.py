from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from ..image_vision_models import (
    VISION_REPORT_SCHEMA,
    ImageVisionModelError,
    VisionInspectionRequest,
    VisionReport,
    canonical_bytes,
    parse_vision_report,
    validate_sha256,
)
from ..pixelorama_png import PngError, inspect_rgba8_png


class LlamaCppVisionError(RuntimeError):
    pass


# The pinned llama.cpp grammar parser rejects large finite repetitions. The
# canonical Origin Forge schema intentionally remains provider-neutral and the
# deterministic parser remains the final acceptance authority. For this
# backend, use a stricter transport-only subset whose entire practical shape is
# compatible with a bounded completion budget rather than allowing the model to
# consume the budget inside one very large field or finding list.
_LLAMA_CPP_TRANSPORT_TEXT_LIMIT = 256
_LLAMA_CPP_TRANSPORT_FINDING_LIMIT = 4
_LLAMA_CPP_MIN_OUTPUT_TOKENS = 1024


def _llamacpp_transport_schema() -> dict[str, object]:
    schema = deepcopy(VISION_REPORT_SCHEMA)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise RuntimeError("VISION_REPORT_SCHEMA properties are invalid")
    summary = properties.get("summary")
    findings = properties.get("findings")
    if not isinstance(summary, dict) or not isinstance(findings, dict):
        raise RuntimeError("VISION_REPORT_SCHEMA fields are invalid")
    summary["maxLength"] = _LLAMA_CPP_TRANSPORT_TEXT_LIMIT
    findings["maxItems"] = _LLAMA_CPP_TRANSPORT_FINDING_LIMIT
    items = findings.get("items")
    if not isinstance(items, dict):
        raise RuntimeError("VISION_REPORT_SCHEMA finding items are invalid")
    item_properties = items.get("properties")
    if not isinstance(item_properties, dict):
        raise RuntimeError("VISION_REPORT_SCHEMA finding properties are invalid")
    description = item_properties.get("description")
    if not isinstance(description, dict):
        raise RuntimeError("VISION_REPORT_SCHEMA description field is invalid")
    description["maxLength"] = _LLAMA_CPP_TRANSPORT_TEXT_LIMIT
    return schema


LLAMA_CPP_VISION_REPORT_SCHEMA = _llamacpp_transport_schema()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class LlamaCppVisionSettings:
    base_url: str = "http://127.0.0.1:8080"
    model: str = "local-vision-model"
    model_hash: str = "sha256:" + "0" * 64
    api_key: str = "no-key"
    timeout_seconds: float = 300.0
    temperature: float = 0.0
    allow_remote: bool = False
    max_response_bytes: int = 4 * 1024 * 1024
    max_total_image_bytes: int = 32 * 1024 * 1024


class LlamaCppVisionAdapter:
    """Bounded multimodal llama.cpp adapter for advisory raster inspection.

    This adapter never interprets model output as verification authority. It validates
    exact frozen PNG inputs, sends them to the OpenAI-compatible multimodal endpoint,
    and converts the schema-constrained response into an advisory ``VisionReport``.
    """

    _LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "local-vision-model",
        model_hash: str = "sha256:" + "0" * 64,
        api_key: str = "no-key",
        timeout_seconds: float = 300.0,
        temperature: float = 0.0,
        allow_remote: bool = False,
        max_response_bytes: int = 4 * 1024 * 1024,
        max_total_image_bytes: int = 32 * 1024 * 1024,
    ):
        self.settings = LlamaCppVisionSettings(
            base_url=base_url.rstrip("/"),
            model=model,
            model_hash=model_hash,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            allow_remote=allow_remote,
            max_response_bytes=max_response_bytes,
            max_total_image_bytes=max_total_image_bytes,
        )
        self._validate_settings()

    @property
    def model_id(self) -> str:
        return self.settings.model

    @property
    def model_hash(self) -> str:
        return self.settings.model_hash

    def _validate_settings(self) -> None:
        parsed = urlparse(self.settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("llama.cpp vision base_url must be an http(s) URL")
        if not self.settings.allow_remote and parsed.hostname not in self._LOOPBACK_HOSTS:
            raise ValueError(
                "remote vision endpoints are disabled; set allow_remote=True explicitly"
            )
        validate_sha256(self.settings.model_hash, "vision model_hash")
        if self.settings.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= self.settings.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.settings.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if self.settings.max_total_image_bytes <= 0:
            raise ValueError("max_total_image_bytes must be positive")

    @staticmethod
    def _validate_image_bytes(
        request: VisionInspectionRequest,
        image_bytes_by_id: Mapping[str, bytes],
        *,
        max_total_image_bytes: int,
    ) -> tuple[tuple[str, bytes], ...]:
        expected_ids = {value.image_id for value in request.images}
        if set(image_bytes_by_id) != expected_ids:
            raise LlamaCppVisionError(
                "vision image byte set must exactly match the frozen request"
            )
        ordered: list[tuple[str, bytes]] = []
        total = 0
        refs = {value.image_id: value for value in request.images}
        for image_id in sorted(expected_ids):
            data = image_bytes_by_id[image_id]
            if not isinstance(data, bytes):
                raise LlamaCppVisionError("vision image payloads must be bytes")
            total += len(data)
            if total > max_total_image_bytes:
                raise LlamaCppVisionError("vision image inputs exceed total byte limit")
            ref = refs[image_id]
            if len(data) != ref.byte_count:
                raise LlamaCppVisionError(
                    f"vision image {image_id} byte count does not match frozen evidence"
                )
            content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
            if content_hash != ref.content_hash:
                raise LlamaCppVisionError(
                    f"vision image {image_id} content hash does not match frozen evidence"
                )
            try:
                inspection = inspect_rgba8_png(data)
            except PngError as exc:
                raise LlamaCppVisionError(
                    f"vision image {image_id} is not an accepted RGBA8 PNG: {exc}"
                ) from exc
            if (
                inspection.width != ref.width
                or inspection.height != ref.height
                or inspection.pixel_hash != ref.pixel_hash
            ):
                raise LlamaCppVisionError(
                    f"vision image {image_id} raster evidence does not match frozen request"
                )
            ordered.append((image_id, data))
        return tuple(ordered)

    def _payload(
        self,
        request: VisionInspectionRequest,
        images: tuple[tuple[str, bytes], ...],
    ) -> dict[str, object]:
        instruction = (
            "You are an isolated Origin Forge visual inspector. "
            "Return only the requested JSON object. Findings are advisory evidence only; "
            "do not claim verification, acceptance, adoption, Task completion, merge, or release authority. "
            "Reference only the supplied image_id values."
        )
        context = {
            "inspection_id": request.inspection_id,
            "objective": request.objective,
            "criteria": list(request.criteria),
            "image_ids": [image_id for image_id, _ in images],
        }
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": canonical_bytes(context).decode("utf-8"),
            }
        ]
        for image_id, data in images:
            content.append({"type": "text", "text": f"image_id={image_id}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,"
                        + base64.b64encode(data).decode("ascii")
                    },
                }
            )
        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": content},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
            "response_format": {
                "type": "json_object",
                "schema": LLAMA_CPP_VISION_REPORT_SCHEMA,
            },
        }

    def inspect(
        self,
        request: VisionInspectionRequest,
        image_bytes_by_id: Mapping[str, bytes],
    ) -> VisionReport:
        if not isinstance(request, VisionInspectionRequest):
            raise TypeError("request must be a VisionInspectionRequest")
        if request.expected_model_id != self.settings.model:
            raise LlamaCppVisionError("vision request model_id does not match configured model")
        if request.expected_model_hash != self.settings.model_hash:
            raise LlamaCppVisionError("vision request model_hash does not match configured model")
        if request.max_output_tokens < _LLAMA_CPP_MIN_OUTPUT_TOKENS:
            raise LlamaCppVisionError(
                "llama.cpp vision requires max_output_tokens >= "
                f"{_LLAMA_CPP_MIN_OUTPUT_TOKENS} for its bounded transport schema"
            )
        images = self._validate_image_bytes(
            request,
            image_bytes_by_id,
            max_total_image_bytes=self.settings.max_total_image_bytes,
        )
        body = json.dumps(self._payload(request, images), separators=(",", ":")).encode(
            "utf-8"
        )
        http_request = urllib.request.Request(
            f"{self.settings.base_url}/v1/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        try:
            with opener.open(
                http_request, timeout=self.settings.timeout_seconds
            ) as response:
                raw = response.read(self.settings.max_response_bytes + 1)
                if len(raw) > self.settings.max_response_bytes:
                    raise LlamaCppVisionError(
                        f"llama.cpp vision response exceeds {self.settings.max_response_bytes} bytes"
                    )
        except urllib.error.HTTPError as exc:
            detail = exc.read(min(self.settings.max_response_bytes, 4096)).decode(
                "utf-8", errors="replace"
            )
            raise LlamaCppVisionError(
                f"llama.cpp vision returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LlamaCppVisionError(
                f"llama.cpp vision request failed: {exc.reason}"
            ) from exc

        try:
            value = json.loads(raw)
            choice = value["choices"][0]
            content = choice["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LlamaCppVisionError(
                "llama.cpp vision returned an invalid chat completion response"
            ) from exc
        if not isinstance(content, str):
            raise LlamaCppVisionError("llama.cpp vision completion content is not text")
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise LlamaCppVisionError(
                "llama.cpp vision completion exhausted the frozen output-token budget"
            )
        if finish_reason not in {None, "stop"}:
            raise LlamaCppVisionError(
                f"llama.cpp vision returned unsupported finish_reason: {finish_reason!r}"
            )
        returned_model = value.get("model") or self.settings.model
        if returned_model != self.settings.model:
            raise LlamaCppVisionError("llama.cpp vision returned unexpected model identity")
        usage = value.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        try:
            return parse_vision_report(
                content,
                request=request,
                model_id=self.settings.model,
                model_hash=self.settings.model_hash,
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            )
        except ImageVisionModelError as exc:
            raise LlamaCppVisionError(f"invalid advisory vision report: {exc}") from exc
