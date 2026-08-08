from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.lineage import OriginForgeLineage
from origin_forge.project_intelligence import ProjectIntelligenceService
from origin_forge.project_models import (
    BindingType,
    DesignRuleAuthority,
    DesignRuleCategory,
    EntityKind,
)
from origin_forge.provenance_builder import ProvenanceBuildError, ProvenanceManifestBuilder
from origin_forge.provenance_freshness import (
    ProvenanceFreshnessFinding,
    ProvenanceFreshnessVerifier,
)
from origin_forge.provenance_models import (
    CompanyRootIdentity,
    DetachedSignature,
    SignatureAlgorithm,
    SignedProvenanceManifest,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


NOW = "2026-08-08T20:00:00Z"
HASH_CERT = "sha256:" + "c" * 64


class ProvenanceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root_path)
        self.runtime.initialize("provenance-builder-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.project_intelligence = ProjectIntelligenceService(self.runtime)
        self.root_identity = CompanyRootIdentity.create(
            "Origin Forge Test",
            b"test-root-public-der",
            created_at=NOW,
        )

        self.goal = self.runtime.create_goal("Build provenance test artifact")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Produce result")
        revision = self.runtime.transition_task(
            self.task, TaskStatus.READY, expected_revision=0
        )
        self.task_revision = self.runtime.transition_task(
            self.task, TaskStatus.RUNNING, expected_revision=revision
        )
        self.run = self.runtime.start_run(
            self.task,
            role="EXECUTOR",
            model_profile="coder-strong",
        )
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE runs SET model_hash = ? WHERE id = ?",
                ("sha256:" + "d" * 64, self.run),
            )
        self.decision = self.lineage.create_decision(
            title="Use deterministic output",
            decision="Create one local result file.",
            goal_id=self.goal,
            task_id=self.task,
        )
        self.change = self.lineage.create_change(
            self.task,
            summary="Produce test artifact",
            change_type="TEST",
            decision_id=self.decision,
            run_id=self.run,
        )
        self.output = self.root_path / "out" / "result.txt"
        self.output.parent.mkdir()
        self.output.write_text("verified bytes\n", encoding="utf-8")
        self.artifact = self.lineage.create_artifact(
            artifact_type="TEST_RESULT",
            path_or_uri=str(self.output),
            change_id=self.change,
            created_by_run_id=self.run,
            model_id="test-model",
            skill_versions=("build-result@1.0.0",),
            tool_versions=("python@3",),
        )
        self.verification = self.lineage.record_artifact_verification(
            self.artifact,
            verification_type="test-result-integrity",
            verifier="unit-test",
            status="PASS",
        )
        self.entity = self.project_intelligence.create_entity(
            EntityKind.COMPONENT,
            "Result Component",
        )
        self.project_intelligence.create_binding(
            self.entity,
            BindingType.ARTIFACT,
            self.artifact,
        )
        self.rule = self.project_intelligence.create_design_rule(
            DesignRuleCategory.TECHNICAL,
            "Deterministic result",
            "Result artifacts must be reproducible from governed inputs.",
            DesignRuleAuthority.PRINCIPLE,
            scope_entity_ids=(self.entity,),
        )
        self.global_rule = self.project_intelligence.create_design_rule(
            DesignRuleCategory.PROCESS,
            "No hidden release authority",
            "Signing an artifact must not release it automatically.",
            DesignRuleAuthority.HARD_CONSTRAINT,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _builder(self) -> ProvenanceManifestBuilder:
        return ProvenanceManifestBuilder(self.runtime, self.root_identity)

    @staticmethod
    def _fake_signed(manifest) -> SignedProvenanceManifest:
        key_id = new_id(IdKind.PROVENANCE_KEY)
        return SignedProvenanceManifest(
            manifest=manifest,
            signing_key_id=key_id,
            signing_certificate_hash=HASH_CERT,
            signature=DetachedSignature.create(
                key_id=key_id,
                algorithm=SignatureAlgorithm.ED25519,
                signed_payload_hash=manifest.content_hash,
                signature=b"s" * 64,
            ),
        )

    def test_builder_pins_actual_causal_semantic_and_tool_lineage(self) -> None:
        manifest = self._builder().build(self.artifact, created_at=NOW)
        self.assertEqual(manifest.project_ref.record_id, self.runtime.project_id())
        self.assertEqual(manifest.artifact_ref.record_id, self.artifact)
        self.assertEqual(manifest.task_ref.record_id, self.task)
        self.assertEqual(manifest.run_ref.record_id, self.run)
        self.assertEqual(manifest.change_ref.record_id, self.change)
        self.assertEqual([ref.record_id for ref in manifest.decision_refs], [self.decision])
        self.assertIn(
            self.verification,
            [ref.record_id for ref in manifest.verification_refs],
        )
        self.assertEqual([ref.record_id for ref in manifest.entity_refs], [self.entity])
        self.assertEqual(
            {ref.record_id for ref in manifest.design_rule_refs},
            {self.rule, self.global_rule},
        )
        self.assertEqual(manifest.artifact_location, "out/result.txt")
        self.assertEqual(manifest.model_id, "test-model")
        self.assertEqual(manifest.model_profile, "coder-strong")
        self.assertEqual(manifest.model_hash, "sha256:" + "d" * 64)
        self.assertEqual(manifest.skill_refs, ("build-result@1.0.0",))
        self.assertEqual(manifest.tool_refs, ("python@3",))
        self.assertTrue(manifest.artifact_content_hash.startswith("sha256:"))

    def test_stale_local_artifact_cannot_receive_new_current_manifest(self) -> None:
        current = self._builder().build(self.artifact, created_at=NOW)
        signed = self._fake_signed(current)
        self.output.write_text("changed bytes\n", encoding="utf-8")

        with self.assertRaisesRegex(ProvenanceBuildError, "do not match recorded"):
            self._builder().build(self.artifact, created_at=NOW)

        freshness = ProvenanceFreshnessVerifier(self.runtime).verify(signed)
        self.assertFalse(freshness.current)
        self.assertFalse(freshness.artifact_hash_matches)
        self.assertTrue(freshness.record_refs_current)
        self.assertIn(
            ProvenanceFreshnessFinding.ARTIFACT_DRIFT,
            {finding.code for finding in freshness.findings},
        )
        self.assertFalse(freshness.to_dict()["historical_signed_manifest_changed"])

    def test_later_record_transition_reports_record_drift_not_signature_mutation(self) -> None:
        manifest = self._builder().build(self.artifact, created_at=NOW)
        signed = self._fake_signed(manifest)
        self.runtime.finish_run(self.run, RunStatus.FAILED, failure_reason="later outcome")
        task = self.runtime.get_task(self.task)
        self.runtime.transition_task(
            self.task,
            TaskStatus.FAILED,
            expected_revision=int(task["revision"]),
        )

        freshness = ProvenanceFreshnessVerifier(self.runtime).verify(signed)
        self.assertTrue(freshness.artifact_hash_matches)
        self.assertFalse(freshness.record_refs_current)
        drifted_ids = {
            finding.record_id
            for finding in freshness.findings
            if finding.code == ProvenanceFreshnessFinding.RECORD_DRIFT
        }
        self.assertIn(self.run, drifted_ids)
        self.assertIn(self.task, drifted_ids)
        self.assertEqual(signed.manifest.content_hash, manifest.content_hash)

    def test_protected_internal_artifact_is_not_signable_product_provenance(self) -> None:
        internal = self.runtime.state_dir / "internal.txt"
        internal.write_text("internal\n", encoding="utf-8")
        artifact = self.lineage.create_artifact(
            artifact_type="INTERNAL",
            path_or_uri=str(internal),
        )
        with self.assertRaises(ValueError):
            self._builder().build(artifact, created_at=NOW)

    def test_builder_has_no_model_generation_task_transition_or_merge_surface(self) -> None:
        builder = self._builder()
        for forbidden in (
            "model",
            "generate",
            "apply",
            "patch",
            "verify_task",
            "transition_task",
            "merge",
            "release",
            "promote",
        ):
            self.assertFalse(hasattr(builder, forbidden))


if __name__ == "__main__":
    unittest.main()
