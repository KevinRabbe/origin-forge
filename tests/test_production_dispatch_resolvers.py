from __future__ import annotations

import ast
import inspect
import tempfile
import unittest

import origin_forge.production_dispatch_resolvers as resolver_module
from origin_forge.dream_evidence import canonical_verification_record
from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_resolution_models import (
    InputResolverDescriptor,
    ResolvedInputCurrentness,
    ResolverClaim,
)
from origin_forge.production_dispatch_resolvers import (
    ArtifactInputResolver,
    DispatchInputResolutionError,
    WorkOrderInputResolverRegistry,
    build_core_input_resolver_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_intelligence_read import ProjectIntelligenceReadService
from origin_forge.project_models import (
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
)
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime


class _AmbiguousArtifactResolver:
    def __init__(self, resolver_id: str):
        claim = ResolverClaim(WorkOrderRefType.ARTIFACT, "ART-", "ARTIFACT")
        self._descriptor = InputResolverDescriptor(
            resolver_id,
            content_hash({"resolver": resolver_id}),
            (claim,),
        )

    @property
    def descriptor(self):
        return self._descriptor

    def resolve(self, runtime, ref):
        raise AssertionError("ambiguous resolver must never run")


class ProductionDispatchResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("dispatch-resolvers")
        goal = self.runtime.create_goal("resolve dispatch evidence")
        flow = self.runtime.create_flow(goal)
        self.task = self.runtime.create_task(flow, "consume exact evidence")
        self.registry = build_core_input_resolver_registry()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_registry_is_deterministic_and_has_exact_core_claims(self) -> None:
        second = build_core_input_resolver_registry()
        self.assertEqual(self.registry.fingerprint, second.fingerprint)
        self.assertEqual(
            tuple(value.resolver_id for value in self.registry.descriptors),
            (
                "resolver.core.artifact@1",
                "resolver.core.design-rule@1",
                "resolver.core.project-entity@1",
                "resolver.core.verification@1",
            ),
        )
        claims = {
            claim.ref_type
            for descriptor in self.registry.descriptors
            for claim in descriptor.claims
        }
        self.assertEqual(
            claims,
            {
                WorkOrderRefType.ARTIFACT,
                WorkOrderRefType.VERIFICATION,
                WorkOrderRefType.PROJECT_ENTITY,
                WorkOrderRefType.DESIGN_RULE,
            },
        )

    def test_registry_rejects_ambiguous_claims_before_resolution(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous claims"):
            WorkOrderInputResolverRegistry(
                (
                    _AmbiguousArtifactResolver("resolver.one@1"),
                    _AmbiguousArtifactResolver("resolver.two@1"),
                )
            )

    def test_artifact_resolution_binds_stored_content_hash_without_reading_bytes(self) -> None:
        artifact_id = create_artifact(
            self.runtime.store,
            self.runtime.project_id(),
            artifact_type="TEXT",
            path_or_uri="exports/result.txt",
            content_hash="a" * 64,
        )
        ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            artifact_id,
            "a" * 64,
            "source",
            None,
        )
        resolved = self.registry.resolve(self.runtime, ref)
        self.assertEqual(resolved.original_ref, ref)
        self.assertEqual(resolved.currentness, ResolvedInputCurrentness.CURRENT)
        self.assertEqual(resolved.projection["id"], artifact_id)
        self.assertEqual(resolved.projection["path_or_uri"], "exports/result.txt")
        self.assertNotIn("artifact_bytes", resolved.projection)

        with self.assertRaisesRegex(DispatchInputResolutionError, "hash drifted"):
            self.registry.resolve(
                self.runtime,
                WorkOrderInputRef(
                    WorkOrderRefType.ARTIFACT,
                    artifact_id,
                    "b" * 64,
                    "source",
                    None,
                ),
            )
        with self.assertRaisesRegex(DispatchInputResolutionError, "not revision-numbered"):
            ArtifactInputResolver().resolve(
                self.runtime,
                WorkOrderInputRef(
                    WorkOrderRefType.ARTIFACT,
                    artifact_id,
                    "a" * 64,
                    "source",
                    1,
                ),
            )

    def test_verification_resolution_hashes_full_record_but_discloses_metadata_only(self) -> None:
        verification_id = self.runtime.record_verification(
            "TASK",
            self.task,
            verification_type="dispatch-source-check",
            verifier="test",
            status="PASS",
            evidence={"private_detail": "not model-visible"},
            metrics={"score": 9},
        )
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        record_hash = content_hash(canonical_verification_record(dict(row)))
        ref = WorkOrderInputRef(
            WorkOrderRefType.VERIFICATION,
            verification_id,
            record_hash,
            "verification",
            None,
        )
        resolved = self.registry.resolve(self.runtime, ref)
        projection = resolved.projection
        self.assertEqual(projection["record_hash"], record_hash)
        self.assertEqual(projection["status"], "PASS")
        self.assertIn("evidence_hash", projection)
        self.assertIn("metrics_hash", projection)
        self.assertNotIn("evidence", projection)
        self.assertNotIn("metrics", projection)
        self.assertNotIn("private_detail", str(projection))

    def test_project_entity_and_design_rule_require_exact_current_revision_and_hash(self) -> None:
        intelligence = ProjectIntelligenceService(self.runtime)
        entity_id = intelligence.create_entity(
            EntityKind.FEATURE,
            "Factory Golem",
            description="Heavy enemy",
        )
        rule_id = intelligence.create_design_rule(
            DesignRuleCategory.GAMEPLAY,
            "Heavy movement",
            "Heavy enemies move slowly.",
            DesignRuleAuthority.HARD_CONSTRAINT,
            scope_entity_ids=(entity_id,),
        )
        reader = ProjectIntelligenceReadService(self.runtime)
        entity = reader.get_entity(entity_id)
        rule = reader.get_design_rule(rule_id)

        entity_ref = WorkOrderInputRef(
            WorkOrderRefType.PROJECT_ENTITY,
            entity_id,
            content_hash(entity),
            "entity",
            int(entity["revision"]),
        )
        rule_ref = WorkOrderInputRef(
            WorkOrderRefType.DESIGN_RULE,
            rule_id,
            content_hash(rule),
            "design_rule",
            int(rule["revision"]),
        )
        resolved = self.registry.resolve_all(self.runtime, (rule_ref, entity_ref))
        self.assertEqual(
            tuple(value.original_ref.ref_type for value in resolved),
            (WorkOrderRefType.DESIGN_RULE, WorkOrderRefType.PROJECT_ENTITY),
        )
        self.assertEqual(resolved[0].projection["id"], rule_id)
        self.assertEqual(resolved[1].projection["id"], entity_id)

        intelligence.update_entity(entity_id, expected_revision=0, name="Armored Factory Golem")
        with self.assertRaisesRegex(DispatchInputResolutionError, "revision drifted"):
            self.registry.resolve(self.runtime, entity_ref)

    def test_unknown_and_cross_project_refs_fail_without_fallback(self) -> None:
        unknown = WorkOrderInputRef(
            WorkOrderRefType.AUDIO_PROFILE,
            new_id(IdKind.AUDIO_PROFILE),
            "a" * 64,
            "audio_profile",
            None,
        )
        with self.assertRaisesRegex(DispatchInputResolutionError, "no trusted input resolver"):
            self.registry.resolve(self.runtime, unknown)

        with tempfile.TemporaryDirectory() as other:
            other_runtime = OriginForgeRuntime(other)
            other_runtime.initialize("other-project")
            artifact_id = create_artifact(
                other_runtime.store,
                other_runtime.project_id(),
                artifact_type="TEXT",
                path_or_uri="exports/other.txt",
                content_hash="c" * 64,
            )
            ref = WorkOrderInputRef(
                WorkOrderRefType.ARTIFACT,
                artifact_id,
                "c" * 64,
                "source",
                None,
            )
            with self.assertRaisesRegex(
                DispatchInputResolutionError,
                "not available in the current project",
            ):
                self.registry.resolve(self.runtime, ref)

    def test_resolver_layer_has_no_dynamic_loading_or_execution_mutation_surface(self) -> None:
        source = inspect.getsource(resolver_module)
        self.assertNotIn("importlib", source)
        self.assertNotIn("subprocess", source)
        tree = ast.parse(source)
        forbidden = {
            "transition_task",
            "start_run",
            "create_run",
            "generate",
            "drive",
            "dispatch",
            "publish_work_order",
            "publish_audit",
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden.isdisjoint(called_attributes | called_names))

        execute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]
        self.assertTrue(execute_calls)
        self.assertTrue(
            all(
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "conn"
                for node in execute_calls
            )
        )
        self.assertNotIn("execute", called_names)


if __name__ == "__main__":
    unittest.main()
