from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.project_intelligence_read as read_module
from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_intelligence_read import ProjectIntelligenceReadService
from origin_forge.project_models import (
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
    RelationType,
)
from origin_forge.runtime import OriginForgeRuntime


class ProjectIntelligenceReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("project-intelligence-read-test")
        self.mutable = ProjectIntelligenceService(self.runtime)
        self.reader = ProjectIntelligenceReadService(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _graph(self) -> tuple[str, str, str]:
        actor = self.mutable.create_entity(
            EntityKind.CHARACTER,
            "Factory Guard",
            description="Slow armored enemy",
            metadata={"private-note": "not for cockpit"},
        )
        weapon = self.mutable.create_entity(EntityKind.ITEM, "Mechanical Hammer")
        self.mutable.create_relation(
            actor,
            RelationType.USES,
            weapon,
            rationale="Primary combat tool",
        )
        self.mutable.create_binding(
            actor,
            BindingType.EXTERNAL,
            "design://factory-guard",
            metadata={"private-binding": "not for cockpit"},
        )
        rule = self.mutable.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            "Heavy silhouette",
            "Factory guards must read as heavy at a glance.",
            DesignRuleAuthority.REQUIRED,
            scope_entity_ids=(actor,),
        )
        return actor, weapon, rule

    def test_bounded_lists_counts_and_details_are_read_only_projections(self) -> None:
        actor, _, rule = self._graph()
        before = self.runtime.status()
        counts = self.reader.counts()
        entities = self.reader.list_entities(limit=1)
        relations = self.reader.list_relations(limit=1)
        bindings = self.reader.list_bindings(limit=1)
        rules = self.reader.list_design_rules(limit=1)
        after = self.runtime.status()
        self.assertEqual(before, after)
        self.assertEqual(counts, {"entities": 2, "relations": 1, "bindings": 1, "design_rules": 1})
        self.assertEqual(len(entities), 1)
        self.assertEqual(len(relations), 1)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(len(rules), 1)
        self.assertNotIn("metadata_json", entities[0])
        self.assertFalse(relations[0]["evidence_refs_disclosed"])
        self.assertFalse(bindings[0]["metadata_disclosed"])
        self.assertEqual(self.reader.get_entity(actor)["name"], "Factory Guard")
        self.assertEqual(self.reader.get_design_rule(rule)["scope_entity_ids"], (actor,))

    def test_invalid_limits_and_ids_fail_closed(self) -> None:
        for value in (0, 10_001, True, "1"):
            with self.assertRaises(ValueError):
                self.reader.list_entities(limit=value)  # type: ignore[arg-type]
        with self.assertRaises(KeyError):
            self.reader.get_entity("ENTITY-not-real")
        with self.assertRaises(KeyError):
            self.reader.get_design_rule("RULE-not-real")

    def test_facade_source_is_select_only_and_has_no_mutation_operations(self) -> None:
        source = inspect.getsource(read_module)
        for forbidden in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "_append_event",
            "new_id(",
            "create_entity(",
            "create_relation(",
            "create_binding(",
            "create_design_rule(",
            "retire_",
            "supersede_",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
