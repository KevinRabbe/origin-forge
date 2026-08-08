from __future__ import annotations

import unittest

from origin_forge.tool_catalog import (
    AuthorizedToolView,
    ToolCatalogSnapshot,
    ToolDescriptor,
    ToolEffect,
)
from origin_forge.tool_discovery_gateway import (
    ToolDiscoveryGateway,
    ToolDiscoveryGatewayError,
    ToolDiscoveryOutputBudgetExceeded,
)
from origin_forge.tool_search import ToolAccessDenied, ToolSearchSession


def tool(tool_id: str, *, description: str, capability: str, effects=()):
    return ToolDescriptor.create(
        tool_id=tool_id,
        description=description,
        capabilities=(capability,),
        keywords=("file", "repository"),
        effects=effects,
        deterministic=True,
        reversible=not bool(effects),
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        output_schema={"type": "object"},
    )


class ToolDiscoveryGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        read = tool(
            "repo.read_file",
            description="Read one repository file",
            capability="repo.read",
        )
        write = tool(
            "repo.write_file",
            description="Write one repository file",
            capability="repo.write",
            effects=(ToolEffect.WRITE,),
        )
        hidden = tool(
            "web.search",
            description="Search the internet",
            capability="network.search",
            effects=(ToolEffect.NETWORK,),
        )
        catalog = ToolCatalogSnapshot.create([read, write, hidden])
        view = AuthorizedToolView.create(
            catalog,
            ["repo.read_file", "repo.write_file"],
        )
        self.session = ToolSearchSession(view)
        self.gateway = ToolDiscoveryGateway(self.session)

    def test_only_two_constant_meta_tools_are_exposed(self) -> None:
        schemas = self.gateway.meta_tool_schemas()
        self.assertEqual(
            [item["name"] for item in schemas],
            ["search_tools", "describe_tool"],
        )
        serialized = str(schemas)
        self.assertNotIn("call_tool", serialized)
        self.assertNotIn("repo.read_file", serialized)
        self.assertNotIn("repo.write_file", serialized)

    def test_meta_tool_schema_copies_cannot_mutate_global_contract(self) -> None:
        first = self.gateway.meta_tool_schemas()
        first[0]["name"] = "tampered"
        second = self.gateway.meta_tool_schemas()
        self.assertEqual(second[0]["name"], "search_tools")

    def test_search_response_is_compact_and_fingerprinted(self) -> None:
        payload = self.gateway.call(
            "search_tools",
            {"query": "read repository file", "limit": 3},
        )
        self.assertEqual(payload["protocol_id"], "tool-discovery-v1")
        self.assertEqual(payload["catalog_hash"], self.session.view.catalog_hash)
        self.assertEqual(payload["authority_hash"], self.session.view.authority_hash)
        self.assertEqual(payload["results"][0]["tool_id"], "repo.read_file")
        self.assertNotIn("input_schema", payload["results"][0])
        self.assertNotIn("output_schema", payload["results"][0])

    def test_describe_response_hydrates_one_authorized_contract(self) -> None:
        payload = self.gateway.call(
            "describe_tool",
            {"tool_id": "repo.read_file"},
        )
        tool_payload = payload["tool"]
        self.assertEqual(tool_payload["tool_id"], "repo.read_file")
        self.assertEqual(tool_payload["input_schema"]["type"], "object")
        self.assertEqual(
            tool_payload["authority_hash"],
            self.session.view.authority_hash,
        )

    def test_unknown_operation_and_extra_arguments_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ToolDiscoveryGatewayError,
            "unsupported tool discovery operation",
        ):
            self.gateway.call("call_tool", {"tool_id": "repo.read_file"})
        with self.assertRaisesRegex(
            ToolDiscoveryGatewayError,
            "do not match",
        ):
            self.gateway.call(
                "search_tools",
                {"query": "read file", "unexpected": True},
            )
        with self.assertRaisesRegex(
            ToolDiscoveryGatewayError,
            "must be an integer",
        ):
            self.gateway.call(
                "search_tools",
                {"query": "read file", "limit": "5"},
            )

    def test_hidden_tool_remains_hidden_through_gateway(self) -> None:
        search = self.gateway.call(
            "search_tools",
            {"query": "internet network search"},
        )
        self.assertEqual(search["results"], [])
        with self.assertRaises(ToolAccessDenied):
            self.gateway.call(
                "describe_tool",
                {"tool_id": "web.search"},
            )

    def test_cumulative_response_bytes_are_bounded(self) -> None:
        gateway = ToolDiscoveryGateway(
            self.session,
            max_response_bytes=400,
        )
        with self.assertRaises(ToolDiscoveryOutputBudgetExceeded):
            for _ in range(20):
                gateway.call("search_tools", {"query": "read file"})
        self.assertLessEqual(
            gateway.status().response_bytes_used,
            gateway.status().response_bytes_limit,
        )

    def test_status_contains_only_discovery_provenance_and_budgets(self) -> None:
        self.gateway.call("search_tools", {"query": "read file"})
        self.gateway.call("describe_tool", {"tool_id": "repo.read_file"})
        status = self.gateway.status().to_dict()
        self.assertEqual(status["protocol_id"], "tool-discovery-v1")
        self.assertEqual(status["hydrated_tool_ids"], ["repo.read_file"])
        self.assertGreater(status["response_bytes_used"], 0)
        self.assertNotIn("input_schema", status)
        self.assertNotIn("output_schema", status)


if __name__ == "__main__":
    unittest.main()
