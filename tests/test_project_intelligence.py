from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.project_intelligence import (
    ProjectIntelligenceError,
    ProjectIntelligenceService,
)
from origin_forge.project_models import (
    BindingStatus,
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    DesignRuleStatus,
    EntityKind,
    EntityStatus,
    ImpactDirection,
    ImpactQuery,
    RelationStatus,
    RelationType,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.service import StaleRevision, utc_now


class ProjectIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("project-intelligence-test")
        self.intelligence = ProjectIntelligenceService(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_entity_identity_revision_history_and_retirement_are_durable(self) -> None:
        entity_id = self.intelligence.create_entity(
            EntityKind.FEATURE,
            "Stone Golem",
            description="Factory enemy",
            metadata={"tier": 2},
        )
        row = self.intelligence.get_entity(entity_id)
        self.assertEqual(row["status"], EntityStatus.ACTIVE.value)
        self.assertEqual(row["revision"], 0)

        revision = self.intelligence.update_entity(
            entity_id,
            expected_revision=0,
            name="Armored Stone Golem",
            metadata={"tier": 3},
        )
        self.assertEqual(revision, 1)
        with self.assertRaises(StaleRevision):
            self.intelligence.update_entity(
                entity_id,
                expected_revision=0,
                description="stale write",
            )

        revision = self.intelligence.set_entity_status(
            entity_id,
            EntityStatus.RETIRED,
            expected_revision=1,
        )
        self.assertEqual(revision, 2)
        retired = self.intelligence.get_entity(entity_id)
        self.assertEqual(retired["id"], entity_id)
        self.assertEqual(retired["status"], EntityStatus.RETIRED.value)
        self.assertEqual(
            [row["id"] for row in self.intelligence.list_entities(status=EntityStatus.RETIRED)],
            [entity_id],
        )
        events = self.runtime.store.event_history("ENTITY", entity_id)
        self.assertEqual(
            [row["event_type"] for row in events],
            ["ENTITY_CREATED", "ENTITY_UPDATED", "ENTITY_STATUS_CHANGED"],
        )

        reopened = ProjectIntelligenceService(OriginForgeRuntime(self.root))
        self.assertEqual(reopened.get_entity(entity_id)["name"], "Armored Stone Golem")

    def test_relation_integrity_duplicate_self_and_cross_project_are_rejected(self) -> None:
        source = self.intelligence.create_entity(EntityKind.SYSTEM, "Combat")
        target = self.intelligence.create_entity(EntityKind.SYSTEM, "Damage")
        relation_id = self.intelligence.create_relation(
            source,
            RelationType.DEPENDS_ON,
            target,
            rationale="Combat requires damage resolution.",
        )
        self.assertEqual(
            self.intelligence.get_relation(relation_id)["status"],
            RelationStatus.ACTIVE.value,
        )
        with self.assertRaises(ProjectIntelligenceError):
            self.intelligence.create_relation(source, RelationType.DEPENDS_ON, target)
        with self.assertRaisesRegex(ValueError, "self Entity relations"):
            self.intelligence.create_relation(source, RelationType.REFERENCES, source)

        other_project = self.runtime.store.initialize_project(
            "other-project",
            self.root / "other-project",
        )
        other_entity = new_id(IdKind.ENTITY)
        now = utc_now()
        with self.runtime.store.session() as conn:
            conn.execute(
                """INSERT INTO entities(
                       id, project_id, kind, name, description, status, revision,
                       metadata_json, created_at, updated_at
                   ) VALUES (?, ?, 'SYSTEM', 'Other', '', 'ACTIVE', 0, '{}', ?, ?)""",
                (other_entity, other_project, now, now),
            )
        with self.assertRaises(KeyError):
            self.intelligence.create_relation(source, RelationType.USES, other_entity)

        with self.runtime.store.session() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO entity_relations(
                           id, project_id, source_entity_id, relation_type,
                           target_entity_id, status, revision, rationale,
                           evidence_refs_json, created_at, updated_at
                       ) VALUES (?, ?, ?, 'USES', ?, 'ACTIVE', 0, '', '[]', ?, ?)""",
                    (
                        new_id(IdKind.ENTITY_RELATION),
                        self.intelligence.project_id,
                        source,
                        other_entity,
                        now,
                        now,
                    ),
                )

        revision = self.intelligence.retire_relation(relation_id, expected_revision=0)
        self.assertEqual(revision, 1)
        self.assertEqual(
            self.intelligence.get_relation(relation_id)["status"],
            RelationStatus.RETIRED.value,
        )
        replacement = self.intelligence.create_relation(
            source,
            RelationType.DEPENDS_ON,
            target,
        )
        self.assertNotEqual(replacement, relation_id)

    def test_file_binding_is_portable_immutable_by_identity_and_rejects_duplicates(self) -> None:
        entity = self.intelligence.create_entity(EntityKind.COMPONENT, "Inventory")
        binding = self.intelligence.create_binding(
            entity,
            BindingType.FILE,
            "src/inventory.py",
            target_hash="sha256:" + "a" * 64,
            metadata={"language": "python"},
        )
        row = self.intelligence.get_binding(binding)
        self.assertEqual(row["target_ref"], "src/inventory.py")
        self.assertEqual(row["status"], BindingStatus.ACTIVE.value)
        with self.assertRaises(ProjectIntelligenceError):
            self.intelligence.create_binding(entity, BindingType.FILE, "src/inventory.py")
        with self.assertRaisesRegex(ValueError, "protected"):
            self.intelligence.create_binding(entity, BindingType.FILE, ".origin-forge/project.db")
        with self.assertRaisesRegex(ValueError, "lowercase sha256"):
            self.intelligence.create_binding(
                entity,
                BindingType.FILE,
                "src/other.py",
                target_hash="not-a-hash",
            )

        self.intelligence.retire_binding(binding, expected_revision=0)
        self.assertEqual(
            self.intelligence.get_binding(binding)["status"],
            BindingStatus.RETIRED.value,
        )
        replacement = self.intelligence.create_binding(
            entity,
            BindingType.FILE,
            "src/inventory.py",
        )
        self.assertNotEqual(replacement, binding)

    def test_design_rule_scope_supersession_and_history(self) -> None:
        combat = self.intelligence.create_entity(EntityKind.SYSTEM, "Combat")
        rule = self.intelligence.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            "Readable attacks",
            "Every heavy attack must expose a readable anticipation window.",
            DesignRuleAuthority.HARD_CONSTRAINT,
            scope_entity_ids=(combat,),
        )
        original = self.intelligence.get_design_rule(rule)
        self.assertEqual(original["status"], DesignRuleStatus.ACTIVE.value)

        replacement = self.intelligence.supersede_design_rule(
            rule,
            expected_revision=0,
            category=DesignRuleCategory.GAMEPLAY,
            title="Readable heavy attacks",
            statement="Heavy attacks require a readable anticipation and recovery window.",
            authority=DesignRuleAuthority.HARD_CONSTRAINT,
            scope_entity_ids=(combat,),
            rationale="Clarify recovery readability.",
        )
        old = self.intelligence.get_design_rule(rule)
        new = self.intelligence.get_design_rule(replacement)
        self.assertEqual(old["status"], DesignRuleStatus.SUPERSEDED.value)
        self.assertEqual(old["revision"], 1)
        self.assertEqual(new["status"], DesignRuleStatus.ACTIVE.value)
        self.assertEqual(new["supersedes_rule_id"], rule)
        self.assertIn(rule, [row["id"] for row in self.intelligence.list_design_rules()])
        with self.assertRaises(ProjectIntelligenceError):
            self.intelligence.supersede_design_rule(
                rule,
                expected_revision=1,
                category=DesignRuleCategory.GAMEPLAY,
                title="Invalid second supersession",
                statement="Should not apply.",
                authority=DesignRuleAuthority.PRINCIPLE,
            )

    def test_inbound_dependency_impact_is_deterministic_cycle_safe_and_scoped(self) -> None:
        damage = self.intelligence.create_entity(EntityKind.SYSTEM, "Damage")
        combat = self.intelligence.create_entity(EntityKind.SYSTEM, "Combat")
        enemy = self.intelligence.create_entity(EntityKind.FEATURE, "Stone Golem")
        unrelated = self.intelligence.create_entity(EntityKind.FEATURE, "Fishing")

        relation_a = self.intelligence.create_relation(
            combat, RelationType.DEPENDS_ON, damage
        )
        relation_b = self.intelligence.create_relation(
            enemy, RelationType.DEPENDS_ON, combat
        )
        relation_c = self.intelligence.create_relation(
            damage, RelationType.DEPENDS_ON, enemy
        )
        binding = self.intelligence.create_binding(
            combat,
            BindingType.FILE,
            "src/combat.py",
        )
        global_rule = self.intelligence.create_design_rule(
            DesignRuleCategory.TECHNICAL,
            "No hidden network",
            "Production gameplay code must remain functional without network access.",
            DesignRuleAuthority.HARD_CONSTRAINT,
        )
        scoped_rule = self.intelligence.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            "Enemy readability",
            "Heavy enemies require readable anticipation.",
            DesignRuleAuthority.PRINCIPLE,
            scope_entity_ids=(enemy,),
        )
        unrelated_rule = self.intelligence.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            "Fishing pace",
            "Fishing interactions should remain calm.",
            DesignRuleAuthority.PRINCIPLE,
            scope_entity_ids=(unrelated,),
        )

        query = ImpactQuery(
            (damage,),
            relation_types=(RelationType.DEPENDS_ON,),
            direction=ImpactDirection.INBOUND,
            max_depth=4,
        )
        first = self.intelligence.impact(query)
        second = self.intelligence.impact(query)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(
            [(value.entity_id, value.depth) for value in first.entities],
            [(damage, 0), (combat, 1), (enemy, 2)],
        )
        self.assertEqual(
            set(first.relation_ids),
            {relation_a, relation_b, relation_c},
        )
        self.assertTrue(first.cycle_edges_observed)
        self.assertIn(binding, first.binding_ids)
        self.assertEqual(set(first.design_rule_ids), {global_rule, scoped_rule})
        self.assertNotIn(unrelated_rule, first.design_rule_ids)
        self.assertNotIn(
            unrelated,
            {value.entity_id for value in first.entities},
        )

        bounded = self.intelligence.impact(
            ImpactQuery(
                (damage,),
                relation_types=(RelationType.DEPENDS_ON,),
                direction=ImpactDirection.INBOUND,
                max_depth=4,
                max_entities=2,
            )
        )
        self.assertTrue(bounded.truncated_entities)
        self.assertEqual(len(bounded.entities), 2)

    def test_service_has_no_model_source_task_or_merge_authority(self) -> None:
        for forbidden in (
            "model",
            "generate",
            "apply",
            "patch",
            "write_source",
            "verify_task",
            "transition_task",
            "merge",
            "spawn_agent",
            "delegate",
        ):
            self.assertFalse(hasattr(self.intelligence, forbidden))


if __name__ == "__main__":
    unittest.main()
