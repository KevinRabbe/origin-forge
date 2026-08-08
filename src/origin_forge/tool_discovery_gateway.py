from __future__ import annotations

import json
from dataclasses import dataclass

from .tool_search import ToolSearchError, ToolSearchSession


TOOL_DISCOVERY_PROTOCOL_ID = "tool-discovery-v1"
_MAX_REQUEST_BYTES = 8 * 1024
_DEFAULT_MAX_RESPONSE_BYTES = 128 * 1024


class ToolDiscoveryGatewayError(RuntimeError):
    pass


class ToolDiscoveryOutputBudgetExceeded(ToolDiscoveryGatewayError):
    pass


SEARCH_TOOLS_SCHEMA: dict[str, object] = {
    "name": "search_tools",
    "description": (
        "Search only the tools already authorized for this Executor. Returns compact metadata; "
        "search does not grant new authority and does not return full tool schemas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 1024},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


DESCRIBE_TOOL_SCHEMA: dict[str, object] = {
    "name": "describe_tool",
    "description": (
        "Hydrate the full contract for one tool already authorized for this Executor. "
        "Unknown and unauthorized IDs use the same denial surface."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "minLength": 1, "maxLength": 96},
        },
        "required": ["tool_id"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ToolDiscoveryGatewayStatus:
    protocol_id: str
    catalog_hash: str
    authority_hash: str
    searches_used: int
    hydrated_tool_ids: tuple[str, ...]
    response_bytes_used: int
    response_bytes_limit: int

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "catalog_hash": self.catalog_hash,
            "authority_hash": self.authority_hash,
            "searches_used": self.searches_used,
            "hydrated_tool_ids": list(self.hydrated_tool_ids),
            "response_bytes_used": self.response_bytes_used,
            "response_bytes_limit": self.response_bytes_limit,
        }


class ToolDiscoveryGateway:
    """Strict two-operation model boundary for progressive tool disclosure."""

    def __init__(
        self,
        session: ToolSearchSession,
        *,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ):
        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")
        self.session = session
        self.max_response_bytes = max_response_bytes
        self._response_bytes = 0

    @staticmethod
    def meta_tool_schemas() -> tuple[dict[str, object], ...]:
        # Round-trip through JSON so callers cannot mutate process-global schema
        # constants and alter another Executor's model-facing contract.
        return (
            json.loads(json.dumps(SEARCH_TOOLS_SCHEMA)),
            json.loads(json.dumps(DESCRIBE_TOOL_SCHEMA)),
        )

    @staticmethod
    def _request_size(operation: str, arguments: dict[str, object]) -> int:
        try:
            data = json.dumps(
                {"operation": operation, "arguments": arguments},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolDiscoveryGatewayError(
                "tool discovery arguments must be finite JSON data"
            ) from exc
        if len(data) > _MAX_REQUEST_BYTES:
            raise ToolDiscoveryGatewayError(
                f"tool discovery request exceeds byte limit ({len(data)} > {_MAX_REQUEST_BYTES})"
            )
        return len(data)

    def _emit(self, payload: dict[str, object]) -> dict[str, object]:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        next_total = self._response_bytes + len(data)
        if next_total > self.max_response_bytes:
            raise ToolDiscoveryOutputBudgetExceeded(
                "tool discovery response budget exhausted "
                f"({next_total} > {self.max_response_bytes} bytes)"
            )
        self._response_bytes = next_total
        return payload

    @staticmethod
    def _strict_arguments(
        arguments: object,
        *,
        required: set[str],
        optional: set[str] = frozenset(),
    ) -> dict[str, object]:
        if not isinstance(arguments, dict):
            raise ToolDiscoveryGatewayError("tool discovery arguments must be an object")
        keys = set(arguments)
        allowed = required | optional
        if not required.issubset(keys) or not keys.issubset(allowed):
            raise ToolDiscoveryGatewayError(
                "tool discovery arguments do not match the operation contract"
            )
        return arguments

    def call(self, operation: str, arguments: object) -> dict[str, object]:
        if operation not in {"search_tools", "describe_tool"}:
            raise ToolDiscoveryGatewayError(
                f"unsupported tool discovery operation: {operation}"
            )

        if operation == "search_tools":
            args = self._strict_arguments(
                arguments,
                required={"query"},
                optional={"limit"},
            )
            self._request_size(operation, args)
            query = args["query"]
            if not isinstance(query, str):
                raise ToolDiscoveryGatewayError("search_tools.query must be a string")
            limit = args.get("limit")
            if limit is not None and (
                not isinstance(limit, int) or isinstance(limit, bool)
            ):
                raise ToolDiscoveryGatewayError("search_tools.limit must be an integer")
            try:
                results = self.session.search_tools(query, limit=limit)
            except ToolSearchError:
                raise
            return self._emit(
                {
                    "protocol_id": TOOL_DISCOVERY_PROTOCOL_ID,
                    "catalog_hash": self.session.view.catalog_hash,
                    "authority_hash": self.session.view.authority_hash,
                    "results": [item.to_dict() for item in results],
                }
            )

        args = self._strict_arguments(arguments, required={"tool_id"})
        self._request_size(operation, args)
        tool_id = args["tool_id"]
        if not isinstance(tool_id, str):
            raise ToolDiscoveryGatewayError("describe_tool.tool_id must be a string")
        try:
            descriptor = self.session.describe_tool(tool_id)
        except ToolSearchError:
            raise
        return self._emit(
            {
                "protocol_id": TOOL_DISCOVERY_PROTOCOL_ID,
                "tool": descriptor,
            }
        )

    def status(self) -> ToolDiscoveryGatewayStatus:
        return ToolDiscoveryGatewayStatus(
            protocol_id=TOOL_DISCOVERY_PROTOCOL_ID,
            catalog_hash=self.session.view.catalog_hash,
            authority_hash=self.session.view.authority_hash,
            searches_used=self.session.searches_used,
            hydrated_tool_ids=self.session.hydrated_tool_ids,
            response_bytes_used=self._response_bytes,
            response_bytes_limit=self.max_response_bytes,
        )
