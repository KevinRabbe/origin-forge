from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from ..model import ModelRequest, ModelResponse


class LlamaCppError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlamaCppSettings:
    base_url: str = "http://127.0.0.1:8080"
    model: str = "local-model"
    api_key: str = "no-key"
    timeout_seconds: float = 300.0
    max_tokens: int = 4096
    temperature: float = 0.2
    allow_remote: bool = False
    model_hash: str | None = None


class LlamaCppAdapter:
    """Minimal llama.cpp chat-completions adapter for a bounded local worker."""

    _LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "local-model",
        api_key: str = "no-key",
        timeout_seconds: float = 300.0,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        allow_remote: bool = False,
        model_hash: str | None = None,
    ):
        self.settings = LlamaCppSettings(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
            allow_remote=allow_remote,
            model_hash=model_hash,
        )
        self._validate_settings()

    @property
    def model_id(self) -> str:
        return self.settings.model

    def _validate_settings(self) -> None:
        parsed = urlparse(self.settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("llama.cpp base_url must be an http(s) URL")
        if not self.settings.allow_remote and parsed.hostname not in self._LOOPBACK_HOSTS:
            raise ValueError(
                "remote model endpoints are disabled; set allow_remote=True explicitly"
            )
        if self.settings.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.settings.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0 <= self.settings.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

    def _payload(self, request: ModelRequest) -> dict:
        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {
                    "role": "user",
                    "content": json.dumps(request.context, separators=(",", ":"), sort_keys=True),
                },
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "schema": request.response_schema,
            },
        }

    def generate(self, request: ModelRequest) -> ModelResponse:
        body = json.dumps(self._payload(request)).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.settings.base_url}/v1/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self.settings.timeout_seconds
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlamaCppError(
                f"llama.cpp returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LlamaCppError(f"llama.cpp request failed: {exc.reason}") from exc

        try:
            value = json.loads(raw)
            content = value["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LlamaCppError("llama.cpp returned an invalid chat completion response") from exc
        if not isinstance(content, str):
            raise LlamaCppError("llama.cpp chat completion content is not text")

        usage = value.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        return ModelResponse(
            text=content,
            model_id=str(value.get("model") or self.settings.model),
            model_hash=self.settings.model_hash,
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        )
