from __future__ import annotations

import unittest

from origin_forge.tool_catalog import (
    AuthorizedToolView,
    ToolCatalogError,
    ToolCatalogSnapshot,
    ToolDescriptor,
    ToolEffect,
)


def descriptor(
    tool_id: str,
    *,
    description: str | None = None,
    capability: str = "repo.read",
    effects=(),
    input_schema=None,
):
    return ToolDescriptor.create(
        tool_id=tool_id,
        description=description or f"Tool {tool_id} description",
        capabilities=(capability,),
        keywords=("repository", "file"),
        effects=effects,
        deterministic=True,
        reversible=True,
        input_schema=input_schema
        if input_schema is not None
        else {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
        permissions=("workspace.read",),
        required_resources=("filesystem",),
        timeout_seconds=5.0,
        verification_method="RepositoryReader containment",
    )


class ToolCatalogTests(unittest.TestCase):
    def test_descriptor_is_content_addressed_and_schema_is_detached_from_input(self) -> None:
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }
        tool = descriptor("repo.read_file", input_schema=schema)
        before_hash = tool.content_hash
        schema["properties"]["path"]["type"] = "integer"

        self.assertEqual(tool.input_schema["properties"]["path"]["type"], "string")
        self.assertEqual(tool.content_hash, before_hash)
        self.assertEqual(tool.ref.split("#", 1)[0], "repo.read_file")

    def test_descriptor_hash_changes_when_contract_changes(self) -> None:
        first = descriptor("repo.read_file")
        second = descriptor(
            "repo.read_file",
            description="Read one repository file with a changed contract description",
        )
        self.assertNotEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.ref, second.ref)

    def test_catalog_hash_is_deterministic_independent_of_registration_order(self) -> None:
        first = descriptor("repo.read_file")
        second = descriptor("repo.search_text", capability="repo.search")
        left = ToolCatalogSnapshot.create([first, second])
        right = ToolCatalogSnapshot.create([second, first])

        self.assertEqual(left.descriptors, right.descriptors)
        self.assertEqual(left.content_hash, right.content_hash)
        self.assertEqual(left.refs, right.refs)

    def test_catalog_rejects_duplicate_ids_and_count_overflow(self) -> None:
        tool = descriptor("repo.read_file")
        with self.assertRaisesRegex(ToolCatalogError, "duplicate tool IDs"):
            ToolCatalogSnapshot.create([tool, tool])
        with self.assertRaisesRegex(ToolCatalogError, "catalog exceeds limit"):
            ToolCatalogSnapshot.create(
                [tool, descriptor("repo.search_text", capability="repo.search")],
                max_tools=1,
            )

    def test_authorized_view_contains_only_explicit_ids(self) -> None:
        read = descriptor("repo.read_file")
        write = descriptor(
            "repo.write_file",
            capability="repo.write",
            effects=(ToolEffect.WRITE,),
        )
        catalog = ToolCatalogSnapshot.create([read, write])
        view = AuthorizedToolView.create(catalog, ["repo.read_file"])

        self.assertEqual(view.tool_ids, ("repo.read_file",))
        self.assertEqual(view.get("repo.read_file"), read)
        with self.assertRaises(KeyError):
            view.get("repo.write_file")
        self.assertEqual(view.catalog_hash, catalog.content_hash)
        self.assertTrue(view.authority_hash.startswith("sha256:"))

    def test_authority_hash_changes_with_allowed_set(self) -> None:
        read = descriptor("repo.read_file")
        search = descriptor("repo.search_text", capability="repo.search")
        catalog = ToolCatalogSnapshot.create([read, search])
        one = AuthorizedToolView.create(catalog, ["repo.read_file"])
        two = AuthorizedToolView.create(
            catalog,
            ["repo.read_file", "repo.search_text"],
        )
        self.assertNotEqual(one.authority_hash, two.authority_hash)

    def test_authority_rejects_unknown_ids_before_search_exists(self) -> None:
        catalog = ToolCatalogSnapshot.create([descriptor("repo.read_file")])
        with self.assertRaisesRegex(ToolCatalogError, "unknown tool"):
            AuthorizedToolView.create(catalog, ["repo.not_real"])

    def test_schema_shape_size_and_identity_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(ToolCatalogError, "invalid tool_id"):
            descriptor("Repo Read")
        with self.assertRaisesRegex(ToolCatalogError, "non-finite"):
            descriptor(
                "repo.read_file",
                input_schema={"maximum": float("inf")},
            )

        deep: object = {"type": "string"}
        for _ in range(20):
            deep = {"nested": deep}
        with self.assertRaisesRegex(ToolCatalogError, "depth limit"):
            descriptor("repo.read_file", input_schema=deep)

    def test_effects_are_explicit_and_sorted(self) -> None:
        tool = descriptor(
            "net.write",
            capability="network.write",
            effects=(ToolEffect.WRITE, ToolEffect.NETWORK),
        )
        self.assertEqual(
            tuple(effect.value for effect in tool.effects),
            ("NETWORK", "WRITE"),
        )
        compact = tool.compact_dict()
        self.assertEqual(compact["effects"], ["NETWORK", "WRITE"])
        self.assertNotIn("input_schema", compact)
        self.assertNotIn("output_schema", compact)


if __name__ == "__main__":
    unittest.main()
