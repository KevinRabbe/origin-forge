from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_intelligence_cli import build_parser, main
from origin_forge.project_models import (
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
    RelationType,
)
from origin_forge.runtime import OriginForgeRuntime


class ProjectIntelligenceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("project-intelligence-cli-test")
        self.intelligence = ProjectIntelligenceService(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_cli_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = [
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        commands = set(subparsers[0].choices)
        self.assertEqual(
            commands,
            {
                "status",
                "entity-list",
                "entity-show",
                "relation-list",
                "relation-show",
                "binding-list",
                "binding-show",
                "binding-inspect",
                "rule-list",
                "rule-show",
                "impact",
            },
        )
        for forbidden in (
            "create",
            "update",
            "retire",
            "supersede",
            "apply",
            "patch",
            "model",
            "generate",
            "verify",
            "merge",
            "promote",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_and_empty_lists_are_deterministic(self) -> None:
        code, status = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(status["entities"], 0)
        self.assertEqual(status["relations"], 0)
        self.assertEqual(status["bindings"], 0)
        self.assertEqual(status["design_rules"], 0)
        self.assertFalse(status["model_execution_enabled"])
        self.assertFalse(status["canonical_mutation_enabled"])
        self.assertFalse(status["automatic_context_integration_enabled"])

        for command, field in (
            ("entity-list", "entities"),
            ("relation-list", "relations"),
            ("binding-list", "bindings"),
            ("rule-list", "design_rules"),
        ):
            code, payload = self._call(command)
            self.assertEqual(code, 0)
            self.assertEqual(payload[field], [])

    def test_list_show_binding_inspect_and_impact_do_not_mutate_graph(self) -> None:
        dependency = self.intelligence.create_entity(EntityKind.SYSTEM, "Dependency")
        dependent = self.intelligence.create_entity(EntityKind.FEATURE, "Dependent")
        relation = self.intelligence.create_relation(
            dependent,
            RelationType.DEPENDS_ON,
            dependency,
        )
        file_path = self.root / "feature.txt"
        file_path.write_bytes(b"feature")
        expected_hash = "sha256:" + hashlib.sha256(b"feature").hexdigest()
        binding = self.intelligence.create_binding(
            dependent,
            BindingType.FILE,
            "feature.txt",
            target_hash=expected_hash,
        )
        rule = self.intelligence.create_design_rule(
            DesignRuleCategory.TECHNICAL,
            "Stable dependency",
            "Dependency boundaries should remain explicit.",
            DesignRuleAuthority.PRINCIPLE,
            scope_entity_ids=(dependent,),
        )
        before = (
            len(self.intelligence.list_entities()),
            len(self.intelligence.list_relations()),
            len(self.intelligence.list_bindings()),
            len(self.intelligence.list_design_rules()),
        )

        code, payload = self._call("entity-show", dependent)
        self.assertEqual(code, 0)
        self.assertEqual(payload["id"], dependent)
        code, payload = self._call("relation-show", relation)
        self.assertEqual(code, 0)
        self.assertEqual(payload["id"], relation)
        code, payload = self._call("binding-inspect", binding)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "CURRENT")
        self.assertFalse(payload["canonical_binding_changed"])
        code, payload = self._call("rule-show", rule)
        self.assertEqual(code, 0)
        self.assertEqual(payload["id"], rule)

        code, payload = self._call(
            "impact",
            dependency,
            "--relation-type",
            "DEPENDS_ON",
            "--direction",
            "INBOUND",
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            [item["entity_id"] for item in payload["entities"]],
            [dependency, dependent],
        )
        self.assertIn(relation, payload["relation_ids"])
        self.assertIn(binding, payload["binding_ids"])
        self.assertIn(rule, payload["design_rule_ids"])
        self.assertTrue(payload["content_hash"].startswith("sha256:"))

        after = (
            len(self.intelligence.list_entities()),
            len(self.intelligence.list_relations()),
            len(self.intelligence.list_bindings()),
            len(self.intelligence.list_design_rules()),
        )
        self.assertEqual(after, before)

    def test_invalid_object_id_is_structured_failure(self) -> None:
        code, payload = self._call("entity-show", "../../outside")
        self.assertEqual(code, 2)
        self.assertIn("invalid Entity ID", payload["detail"])


if __name__ == "__main__":
    unittest.main()
