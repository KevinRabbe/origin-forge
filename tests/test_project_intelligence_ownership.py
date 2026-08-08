from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.project_intelligence import (
    ProjectIntelligenceError,
    ProjectIntelligenceService,
)
from origin_forge.project_models import (
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
    RelationType,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import utc_now


class ProjectIntelligenceOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("ownership-test")
        self.intelligence = ProjectIntelligenceService(self.runtime)

        goal = self.runtime.create_goal("Current project goal")
        flow = self.runtime.create_flow(goal)
        self.local_task = self.runtime.create_task(flow, "Current project task")

        self.other_project = self.runtime.store.initialize_project(
            "other",
            self.root / "other",
        )
        other_goal = self.runtime.store.create_goal(self.other_project, "Other goal")
        other_flow = self.runtime.store.create_flow(other_goal)
        self.other_task = self.runtime.store.create_task(other_flow, "Other task")

        self.other_entity = new_id(IdKind.ENTITY)
        now = utc_now()
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO entities(
                       id, project_id, kind, name, description, status, revision,
                       metadata_json, created_at, updated_at
                   ) VALUES (?, ?, 'FEATURE', 'Other Entity', '', 'ACTIVE', 0, '{}', ?, ?)""",
                (self.other_entity, self.other_project, now, now),
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_task_binding_and_relation_evidence_are_project_scoped(self) -> None:
        source = self.intelligence.create_entity(EntityKind.FEATURE, "Source")
        target = self.intelligence.create_entity(EntityKind.SYSTEM, "Target")

        binding = self.intelligence.create_binding(
            source,
            BindingType.TASK,
            self.local_task,
        )
        self.assertEqual(self.intelligence.get_binding(binding)["target_ref"], self.local_task)
        with self.assertRaises(ProjectIntelligenceError):
            self.intelligence.create_binding(
                source,
                BindingType.TASK,
                self.other_task,
            )

        relation = self.intelligence.create_relation(
            source,
            RelationType.DEPENDS_ON,
            target,
            evidence_refs=(self.local_task,),
        )
        self.assertIn(self.local_task, self.intelligence.get_relation(relation)["evidence_refs_json"])
        with self.assertRaises(ProjectIntelligenceError):
            self.intelligence.create_relation(
                target,
                RelationType.USES,
                source,
                evidence_refs=(self.other_task,),
            )

    def test_design_rule_scope_cannot_reference_other_project_entity(self) -> None:
        local = self.intelligence.create_entity(EntityKind.SYSTEM, "Local")
        rule = self.intelligence.create_design_rule(
            DesignRuleCategory.TECHNICAL,
            "Local rule",
            "This rule is scoped to the local Entity.",
            DesignRuleAuthority.PRINCIPLE,
            scope_entity_ids=(local,),
        )
        self.assertEqual(self.intelligence.get_design_rule(rule)["status"], "ACTIVE")
        with self.assertRaises(KeyError):
            self.intelligence.create_design_rule(
                DesignRuleCategory.TECHNICAL,
                "Cross-project rule",
                "This must be rejected.",
                DesignRuleAuthority.HARD_CONSTRAINT,
                scope_entity_ids=(self.other_entity,),
            )


if __name__ == "__main__":
    unittest.main()
