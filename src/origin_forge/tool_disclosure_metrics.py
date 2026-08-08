from __future__ import annotations

import json
from dataclasses import dataclass

from .tool_catalog import AuthorizedToolView
from .tool_discovery_gateway import ToolDiscoveryGateway


@dataclass(frozen=True)
class ToolDisclosureFootprint:
    catalog_hash: str
    authority_hash: str
    authorized_tool_count: int
    hydrated_tool_count: int
    searches_used: int
    full_authorized_schema_bytes: int
    meta_tool_schema_bytes: int
    discovery_response_bytes: int
    progressive_total_bytes: int
    bytes_avoided: int
    progressive_to_full_ratio: float

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_hash": self.catalog_hash,
            "authority_hash": self.authority_hash,
            "authorized_tool_count": self.authorized_tool_count,
            "hydrated_tool_count": self.hydrated_tool_count,
            "searches_used": self.searches_used,
            "full_authorized_schema_bytes": self.full_authorized_schema_bytes,
            "meta_tool_schema_bytes": self.meta_tool_schema_bytes,
            "discovery_response_bytes": self.discovery_response_bytes,
            "progressive_total_bytes": self.progressive_total_bytes,
            "bytes_avoided": self.bytes_avoided,
            "progressive_to_full_ratio": self.progressive_to_full_ratio,
        }


def _json_bytes(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def measure_tool_disclosure(
    view: AuthorizedToolView,
    gateway: ToolDiscoveryGateway,
) -> ToolDisclosureFootprint:
    """Measure UTF-8 JSON footprint; this intentionally does not claim token counts."""

    if gateway.session.view.authority_hash != view.authority_hash:
        raise ValueError("gateway authority view does not match metric view")
    full_bytes = _json_bytes(
        [descriptor.canonical_dict() for descriptor in view.descriptors]
    )
    meta_bytes = _json_bytes(gateway.meta_tool_schemas())
    status = gateway.status()
    progressive = meta_bytes + status.response_bytes_used
    avoided = full_bytes - progressive
    ratio = progressive / full_bytes if full_bytes else 0.0
    return ToolDisclosureFootprint(
        catalog_hash=view.catalog_hash,
        authority_hash=view.authority_hash,
        authorized_tool_count=len(view.descriptors),
        hydrated_tool_count=len(status.hydrated_tool_ids),
        searches_used=status.searches_used,
        full_authorized_schema_bytes=full_bytes,
        meta_tool_schema_bytes=meta_bytes,
        discovery_response_bytes=status.response_bytes_used,
        progressive_total_bytes=progressive,
        bytes_avoided=avoided,
        progressive_to_full_ratio=ratio,
    )
