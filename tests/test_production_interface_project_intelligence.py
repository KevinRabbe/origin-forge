from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.production_interface_html import render_detail, render_overview
from origin_forge.production_interface_server import ProductionInterfaceRouter
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_models import (
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
    RelationType,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceProjectIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-project-intelligence-test")
        self.intelligence = ProjectIntelligenceService(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _graph(self) -> tuple[str, str, str]:
        actor = self.intelligence.create_entity(
            EntityKind.COMPONENT,
            '<script>alert("entity")</script>',
            description='<img src=x onerror="entity">',
            metadata={"SECRET_ENTITY_METADATA": "do-not-render"},
        )
        weapon = self.intelligence.create_entity(EntityKind.ASSET, "Mechanical Hammer")
        self.intelligence.create_relation(
            actor,
            RelationType.USES,
            weapon,
            rationale='<script>alert("relation")</script>',
            evidence_refs=(),
        )
        self.intelligence.create_binding(
            actor,
            BindingType.EXTERNAL_REF,
            "design://factory-guard",
            metadata={"SECRET_BINDING_METADATA": "do-not-render"},
        )
        rule = self.intelligence.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            '<script>alert("rule-title")</script>',
            '<img src=x onerror="rule-statement">',
            DesignRuleAuthority.HARD_CONSTRAINT,
            rationale='<script>alert("rule-rationale")</script>',
            scope_entity_ids=(actor,),
        )
        return actor, weapon, rule

    def test_snapshot_binds_counts_redaction_and_authority(self) -> None:
        actor, _, rule = self._graph()
        before = self.runtime.status()
        snapshot = build_production_interface_snapshot(self.runtime)
        after = self.runtime.status()
        self.assertEqual(before, after)
        self.assertEqual(snapshot.total_counts["entities"], 2)
        self.assertEqual(snapshot.total_counts["entity_relations"], 1)
        self.assertEqual(snapshot.total_counts["entity_bindings"], 1)
        self.assertEqual(snapshot.total_counts["design_rules"], 1)
        self.assertEqual(snapshot.entities[0]["id"], actor)
        self.assertEqual(snapshot.design_rules[0]["id"], rule)
        self.assertFalse(snapshot.entity_relations[0]["evidence_refs_disclosed"])
        self.assertFalse(snapshot.entity_bindings[0]["metadata_disclosed"])
        self.assertFalse(snapshot.to_dict()["authority"]["project_intelligence_mutation"])
        serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
        self.assertNotIn("SECRET_ENTITY_METADATA", serialized)
        self.assertNotIn("SECRET_BINDING_METADATA", serialized)

    def test_overview_and_details_escape_project_intelligence_text(self) -> None:
        actor, _, rule = self._graph()
        snapshot = build_production_interface_snapshot(self.runtime)
        overview = render_overview(snapshot)
        entity_page = render_detail(snapshot, "entity", actor)
        rule_page = render_detail(snapshot, "rule", rule)
        for page in (overview, entity_page, rule_page):
            self.assertNotIn('<script>alert("entity")</script>', page)
            self.assertNotIn('<script>alert("rule-title")</script>', page)
            self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", overview)
        self.assertIn("design://factory-guard", entity_page)
        self.assertIn(f"/rule/{rule}", entity_page)

    def test_entity_and_rule_routes_are_typed_and_read_only(self) -> None:
        actor, _, rule = self._graph()
        router = ProductionInterfaceRouter(self.runtime)
        self.assertEqual(router.route("GET", f"/entity/{actor}").status, 200)
        self.assertEqual(router.route("GET", f"/rule/{rule}").status, 200)
        self.assertEqual(router.route("GET", "/entity/ENTITY-not-real").status, 404)
        self.assertEqual(router.route("GET", "/rule/RULE-not-real").status, 404)
        self.assertEqual(router.route("POST", f"/entity/{actor}").status, 405)

    def test_project_intelligence_sections_have_explicit_truncation(self) -> None:
        self.intelligence.create_entity(EntityKind.COMPONENT, "one")
        self.intelligence.create_entity(EntityKind.COMPONENT, "two")
        snapshot = build_production_interface_snapshot(self.runtime, max_entities=1)
        self.assertEqual(len(snapshot.entities), 1)
        self.assertEqual(snapshot.total_counts["entities"], 2)
        self.assertTrue(snapshot.truncated["entities"])


if __name__ == "__main__":
    unittest.main()
