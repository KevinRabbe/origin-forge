from __future__ import annotations

import unittest

from origin_forge.tool_catalog import (
    AuthorizedToolView,
    ToolCatalogSnapshot,
    ToolDescriptor,
)
from origin_forge.tool_disclosure_metrics import measure_tool_disclosure
from origin_forge.tool_discovery_gateway import ToolDiscoveryGateway
from origin_forge.tool_search import ToolSearchSession


def make_tool(index: int) -> ToolDescriptor:
    return ToolDescriptor.create(
        tool_id=f"repo.tool_{index}",
        description=(
            f"Repository capability {index} for reading and analyzing source files. "
            + "Detailed trusted description. " * 8
        ),
        capabilities=(f"repo.capability_{index}",),
        keywords=("repository", f"capability{index}"),
        effects=(),
        deterministic=True,
        reversible=True,
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "string"},
                "options": {
                    "type": "object",
                    "properties": {
                        f"flag_{n}": {"type": "boolean"} for n in range(10)
                    },
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "metadata": {"type": "object"},
            },
        },
    )


class ToolDisclosureMetricsTests(unittest.TestCase):
    def test_progressive_disclosure_is_measurable_against_full_authorized_catalog(self) -> None:
        tools = [make_tool(index) for index in range(40)]
        catalog = ToolCatalogSnapshot.create(tools)
        view = AuthorizedToolView.create(
            catalog,
            [tool.tool_id for tool in tools],
        )
        gateway = ToolDiscoveryGateway(ToolSearchSession(view))

        gateway.call(
            "search_tools",
            {"query": "repo capability 7", "limit": 3},
        )
        gateway.call(
            "describe_tool",
            {"tool_id": "repo.tool_7"},
        )
        footprint = measure_tool_disclosure(view, gateway)

        self.assertEqual(footprint.authorized_tool_count, 40)
        self.assertEqual(footprint.hydrated_tool_count, 1)
        self.assertEqual(footprint.searches_used, 1)
        self.assertGreater(footprint.full_authorized_schema_bytes, 0)
        self.assertGreater(footprint.meta_tool_schema_bytes, 0)
        self.assertGreater(footprint.discovery_response_bytes, 0)
        self.assertLess(
            footprint.progressive_total_bytes,
            footprint.full_authorized_schema_bytes,
        )
        self.assertGreater(footprint.bytes_avoided, 0)
        self.assertLess(footprint.progressive_to_full_ratio, 1.0)

    def test_metric_rejects_mismatched_authority_view(self) -> None:
        tools = [make_tool(1), make_tool(2)]
        catalog = ToolCatalogSnapshot.create(tools)
        one = AuthorizedToolView.create(catalog, ["repo.tool_1"])
        two = AuthorizedToolView.create(catalog, ["repo.tool_2"])
        gateway = ToolDiscoveryGateway(ToolSearchSession(one))
        with self.assertRaisesRegex(ValueError, "does not match"):
            measure_tool_disclosure(two, gateway)

    def test_empty_authorized_view_has_defined_zero_full_ratio(self) -> None:
        catalog = ToolCatalogSnapshot.create([make_tool(1)])
        view = AuthorizedToolView.create(catalog, [])
        gateway = ToolDiscoveryGateway(ToolSearchSession(view))
        footprint = measure_tool_disclosure(view, gateway)
        self.assertEqual(footprint.authorized_tool_count, 0)
        self.assertEqual(footprint.full_authorized_schema_bytes, 2)
        self.assertGreater(footprint.progressive_total_bytes, 0)
        self.assertGreater(footprint.progressive_to_full_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
