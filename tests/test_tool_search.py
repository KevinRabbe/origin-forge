from __future__ import annotations

import unittest

from origin_forge.tool_catalog import (
    AuthorizedToolView,
    ToolCatalogSnapshot,
    ToolDescriptor,
    ToolEffect,
)
from origin_forge.tool_search import (
    ToolAccessDenied,
    ToolDiscoveryEventType,
    ToolSearchBudgetExceeded,
    ToolSearchError,
    ToolSearchSession,
)


def tool(
    tool_id: str,
    description: str,
    *,
    capabilities=(),
    keywords=(),
    effects=(),
):
    return ToolDescriptor.create(
        tool_id=tool_id,
        description=description,
        capabilities=capabilities,
        keywords=keywords,
        effects=effects,
        deterministic=True,
        reversible=not bool(effects),
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
        output_schema={"type": "object"},
    )


class ToolSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.read = tool(
            "repo.read_file",
            "Read UTF-8 content from one contained repository file",
            capabilities=("repo.read",),
            keywords=("read", "file", "source"),
        )
        self.search = tool(
            "repo.search_text",
            "Search tracked repository text for a query",
            capabilities=("repo.search",),
            keywords=("grep", "search", "text"),
        )
        self.write = tool(
            "repo.write_file",
            "Write repository content",
            capabilities=("repo.write",),
            keywords=("write", "file"),
            effects=(ToolEffect.WRITE,),
        )
        self.network = tool(
            "web.search",
            "Search the public internet",
            capabilities=("network.search",),
            keywords=("web", "internet", "search"),
            effects=(ToolEffect.NETWORK,),
        )
        catalog = ToolCatalogSnapshot.create(
            [self.read, self.search, self.write, self.network]
        )
        self.view = AuthorizedToolView.create(
            catalog,
            ["repo.read_file", "repo.search_text", "repo.write_file"],
        )

    def test_search_returns_only_authorized_relevant_tools(self) -> None:
        session = ToolSearchSession(self.view)
        results = session.search_tools("search repository text")
        ids = [item.tool_id for item in results]
        self.assertEqual(ids[0], "repo.search_text")
        self.assertNotIn("web.search", ids)
        self.assertNotIn("input_schema", results[0].to_dict())
        self.assertNotIn("output_schema", results[0].to_dict())

    def test_search_has_no_arbitrary_fallback(self) -> None:
        session = ToolSearchSession(self.view)
        self.assertEqual(session.search_tools("quantum banana orchestra"), ())

    def test_capability_match_dominates_description_only_match(self) -> None:
        session = ToolSearchSession(self.view)
        results = session.search_tools("repo search")
        self.assertEqual(results[0].tool_id, "repo.search_text")
        self.assertGreater(results[0].score, results[-1].score)

    def test_search_limit_is_clamped_to_session_limit(self) -> None:
        session = ToolSearchSession(self.view, max_results_per_search=1)
        results = session.search_tools("repository file", limit=100)
        self.assertEqual(len(results), 1)

    def test_search_query_and_search_count_are_bounded(self) -> None:
        session = ToolSearchSession(
            self.view,
            max_searches=1,
            max_query_chars=16,
            max_query_terms=2,
        )
        with self.assertRaisesRegex(ToolSearchError, "character limit"):
            session.search_tools("x" * 17)
        with self.assertRaisesRegex(ToolSearchError, "term limit"):
            session.search_tools("aa bb cc")
        self.assertEqual(session.search_tools("read file")[0].tool_id, "repo.read_file")
        with self.assertRaises(ToolSearchBudgetExceeded):
            session.search_tools("search text")

    def test_describe_hydrates_full_schema_only_for_authorized_tool(self) -> None:
        session = ToolSearchSession(self.view)
        compact = session.search_tools("read file")[0].to_dict()
        self.assertNotIn("input_schema", compact)
        full = session.describe_tool("repo.read_file")
        self.assertEqual(full["tool_id"], "repo.read_file")
        self.assertEqual(full["input_schema"]["type"], "object")
        self.assertEqual(full["catalog_hash"], self.view.catalog_hash)
        self.assertEqual(full["authority_hash"], self.view.authority_hash)
        self.assertEqual(session.hydrated_tool_ids, ("repo.read_file",))

    def test_guessing_hidden_or_unknown_id_has_same_denial_surface(self) -> None:
        session = ToolSearchSession(self.view)
        prefixes = []
        for tool_id in ("web.search", "totally.not.real"):
            with self.assertRaises(ToolAccessDenied) as raised:
                session.describe_tool(tool_id)
            prefixes.append(str(raised.exception).split(":", 1)[0])
        self.assertEqual(prefixes[0], prefixes[1])
        self.assertEqual(session.hydrated_tool_ids, ())

    def test_hydration_budget_counts_unique_tools_only(self) -> None:
        session = ToolSearchSession(self.view, max_hydrated_tools=1)
        session.describe_tool("repo.read_file")
        session.describe_tool("repo.read_file")
        self.assertEqual(session.hydrated_tool_ids, ("repo.read_file",))
        with self.assertRaises(ToolSearchBudgetExceeded):
            session.describe_tool("repo.search_text")

    def test_describe_call_budget_bounds_repeated_hydration_and_events(self) -> None:
        session = ToolSearchSession(
            self.view,
            max_describes=2,
            max_hydrated_tools=3,
        )
        session.describe_tool("repo.read_file")
        session.describe_tool("repo.read_file")
        self.assertEqual(session.describes_used, 2)
        self.assertEqual(len(session.events), 2)
        with self.assertRaisesRegex(ToolSearchBudgetExceeded, "describe budget"):
            session.describe_tool("repo.read_file")
        self.assertEqual(len(session.events), 2)

    def test_long_description_is_truncated_only_in_search_result(self) -> None:
        long_tool = tool(
            "repo.explain",
            "explain " + "x" * 500,
            capabilities=("repo.explain",),
            keywords=("explain",),
        )
        view = AuthorizedToolView.create(
            ToolCatalogSnapshot.create([long_tool]),
            ["repo.explain"],
        )
        session = ToolSearchSession(view, max_search_description_chars=32)
        result = session.search_tools("explain")[0]
        self.assertLessEqual(len(result.description), 33)
        self.assertTrue(result.description.endswith("…"))
        self.assertGreater(len(session.describe_tool("repo.explain")["description"]), 32)

    def test_discovery_trajectory_is_deterministic_and_contains_no_schemas(self) -> None:
        first = ToolSearchSession(self.view)
        second = ToolSearchSession(self.view)
        first.search_tools("read file")
        first.describe_tool("repo.read_file")
        second.search_tools("read file")
        second.describe_tool("repo.read_file")

        self.assertEqual(first.events, second.events)
        self.assertEqual(
            [event.event_type for event in first.events],
            [ToolDiscoveryEventType.SEARCH, ToolDiscoveryEventType.DESCRIBE],
        )
        event_payload = first.events[0].to_dict()
        self.assertNotIn("input_schema", event_payload)
        self.assertNotIn("output_schema", event_payload)


if __name__ == "__main__":
    unittest.main()
