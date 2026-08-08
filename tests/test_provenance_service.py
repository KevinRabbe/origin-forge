from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.provenance_crypto import (
    OpenSslEd25519Backend,
    SecretContainmentError,
)
from origin_forge.provenance_models import OperationalKeyPurpose
from origin_forge.provenance_service import (
    ProvenanceService,
    ProvenanceServiceError,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, TaskStatus


NOW = "2026-08-08T20:00:00Z"


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for provenance service tests")
class ProvenanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.project_temp.name)
        self.secret_root = Path(self.secret_temp.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("provenance-service-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.openssl = shutil.which("openssl")
        assert self.openssl is not None

        self.root_key = self._key("root.pem")
        self.operational_key = self._key("operational.pem")
        self.other_key = self._key("other.pem")
        self.backend = OpenSslEd25519Backend(self.root)
        self.service = ProvenanceService(
            self.runtime,
            backend=self.backend,
        )

        self.goal = self.runtime.create_goal("Produce a signed artifact")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Create result")
        revision = self.runtime.transition_task(
            self.task,
            TaskStatus.READY,
            expected_revision=0,
        )
        self.runtime.transition_task(
            self.task,
            TaskStatus.RUNNING,
            expected_revision=revision,
        )
        self.run = self.runtime.start_run(
            self.task,
            role="EXECUTOR",
            model_profile="coder-strong",
        )
        self.decision = self.lineage.create_decision(
            title="Create local output",
            decision="Write one local artifact for provenance testing.",
            goal_id=self.goal,
            task_id=self.task,
        )
        self.change = self.lineage.create_change(
            self.task,
            summary="Create result artifact",
            change_type="TEST",
            decision_id=self.decision,
            run_id=self.run,
        )
        self.output = self.root / "dist" / "result.txt"
        self.output.parent.mkdir()
        self.output.write_text("signed bytes\n", encoding="utf-8")
        self.artifact = self.lineage.create_artifact(
            artifact_type="TEST_RESULT",
            path_or_uri=str(self.output),
            change_id=self.change,
            created_by_run_id=self.run,
            model_id="test-model",
            skill_versions=("artifact-build@1.0.0",),
            tool_versions=("python@3",),
        )
        self.lineage.record_artifact_verification(
            self.artifact,
            verification_type="artifact-integrity",
            verifier="test",
            status="PASS",
        )

    def tearDown(self) -> None:
        self.project_temp.cleanup()
        self.secret_temp.cleanup()

    def _key(self, name: str) -> Path:
        path = self.secret_root / name
        subprocess.run(
            [self.openssl, "genpkey", "-algorithm", "ED25519", "-out", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def _trust_root_and_issue_certificate(self):
        root = self.service.trust_root_public(
            "Origin Forge Test",
            self.backend.public_key_der(self.root_key),
            created_at=NOW,
        )
        certificate = self.service.issue_operational_certificate(
            self.backend.public_key_der(self.operational_key),
            root_private_key_handle=self.root_key,
            purpose=OperationalKeyPurpose.ARTIFACT_SIGNING,
            issued_at=NOW,
        )
        return root, certificate

    def _production_snapshot(self) -> tuple[dict, dict, tuple[tuple[str, str], ...]]:
        task = self.runtime.get_task(self.task)
        with self.runtime.store.session() as conn:
            artifact = dict(
                conn.execute(
                    "SELECT * FROM artifacts WHERE id = ?",
                    (self.artifact,),
                ).fetchone()
            )
            verifications = tuple(
                (row["id"], row["status"])
                for row in conn.execute(
                    "SELECT id, status FROM verifications WHERE target_type = 'ARTIFACT' AND target_id = ? ORDER BY id",
                    (self.artifact,),
                )
            )
        return task, artifact, verifications

    def test_full_trust_issue_sign_verify_lifecycle_is_public_and_non_mutating(self) -> None:
        before = self._production_snapshot()
        root, certificate = self._trust_root_and_issue_certificate()

        self.assertEqual(self.service.store.load_root(root.company_id), root)
        self.assertEqual(
            self.service.store.load_certificate(certificate.certificate.certificate_id),
            certificate,
        )

        signed = self.service.sign_artifact(
            self.artifact,
            certificate.certificate.certificate_id,
            operational_private_key_handle=self.operational_key,
            created_at=NOW,
        )
        self.assertIn(
            signed.manifest.manifest_id,
            self.service.store.list_manifest_ids(),
        )

        inspection = self.service.verify_manifest(signed.manifest.manifest_id)
        self.assertTrue(inspection.cryptographic.trusted)
        self.assertTrue(inspection.freshness.current)
        self.assertTrue(inspection.trusted_and_current)
        self.assertFalse(inspection.to_dict()["production_verification_changed"])
        self.assertFalse(inspection.to_dict()["artifact_status_changed"])
        self.assertFalse(inspection.to_dict()["task_status_changed"])
        self.assertEqual(self._production_snapshot(), before)

        status = self.service.status()
        self.assertFalse(status["private_keys_stored"])
        self.assertFalse(status["model_signing_enabled"])
        self.assertFalse(status["automatic_task_verification_enabled"])
        self.assertFalse(status["automatic_release_enabled"])

    def test_same_root_import_is_idempotent_and_different_trust_anchor_is_rejected(self) -> None:
        public = self.backend.public_key_der(self.root_key)
        first = self.service.trust_root_public(
            "Origin Forge Test",
            public,
            created_at=NOW,
        )
        second = self.service.trust_root_public(
            "Origin Forge Test",
            public,
            created_at="2026-08-08T20:01:00Z",
        )
        self.assertEqual(second, first)
        self.assertEqual(self.service.store.list_root_ids(), (first.company_id,))

        with self.assertRaisesRegex(ProvenanceServiceError, "different Company Root"):
            self.service.trust_root_public(
                "Other Root",
                self.backend.public_key_der(self.other_key),
                created_at=NOW,
            )

    def test_wrong_root_or_operational_private_key_fails_without_partial_publication(self) -> None:
        root = self.service.trust_root_public(
            "Origin Forge Test",
            self.backend.public_key_der(self.root_key),
            created_at=NOW,
        )
        before_certificates = self.service.store.list_certificate_ids()
        with self.assertRaisesRegex(SecretContainmentError, "does not match"):
            self.service.issue_operational_certificate(
                self.backend.public_key_der(self.operational_key),
                root_private_key_handle=self.other_key,
                issued_at=NOW,
            )
        self.assertEqual(self.service.store.list_certificate_ids(), before_certificates)
        self.assertEqual(self.service.store.load_root(root.company_id), root)

        certificate = self.service.issue_operational_certificate(
            self.backend.public_key_der(self.operational_key),
            root_private_key_handle=self.root_key,
            issued_at=NOW,
        )
        before_manifests = self.service.store.list_manifest_ids()
        with self.assertRaisesRegex(SecretContainmentError, "does not match"):
            self.service.sign_artifact(
                self.artifact,
                certificate.certificate.certificate_id,
                operational_private_key_handle=self.other_key,
                created_at=NOW,
            )
        self.assertEqual(self.service.store.list_manifest_ids(), before_manifests)

    def test_artifact_drift_preserves_cryptographic_trust_but_breaks_currentness(self) -> None:
        _, certificate = self._trust_root_and_issue_certificate()
        signed = self.service.sign_artifact(
            self.artifact,
            certificate.certificate.certificate_id,
            operational_private_key_handle=self.operational_key,
            created_at=NOW,
        )
        self.output.write_text("later bytes\n", encoding="utf-8")

        inspection = self.service.verify_manifest(signed.manifest.manifest_id)
        self.assertTrue(inspection.cryptographic.trusted)
        self.assertFalse(inspection.freshness.current)
        self.assertFalse(inspection.freshness.artifact_hash_matches)
        self.assertFalse(inspection.trusted_and_current)
        self.assertEqual(
            self.service.store.load_manifest(signed.manifest.manifest_id),
            signed,
        )

    def test_root_signed_revocation_blocks_future_manifest_persistence(self) -> None:
        _, certificate = self._trust_root_and_issue_certificate()
        first = self.service.sign_artifact(
            self.artifact,
            certificate.certificate.certificate_id,
            operational_private_key_handle=self.operational_key,
            created_at=NOW,
        )
        revocation = self.service.revoke_operational_certificate(
            certificate.certificate.certificate_id,
            root_private_key_handle=self.root_key,
            reason="Compromised operational key",
            effective_at="2026-08-08T20:05:00Z",
        )
        self.assertIn(
            revocation.revocation.revocation_id,
            self.service.store.list_revocation_ids(),
        )

        old_inspection = self.service.verify_manifest(first.manifest.manifest_id)
        self.assertFalse(old_inspection.cryptographic.trusted)
        self.assertTrue(old_inspection.cryptographic.key_revoked)

        before = self.service.store.list_manifest_ids()
        with self.assertRaisesRegex(ProvenanceServiceError, "not trusted"):
            self.service.sign_artifact(
                self.artifact,
                certificate.certificate.certificate_id,
                operational_private_key_handle=self.operational_key,
                created_at="2026-08-08T20:06:00Z",
            )
        self.assertEqual(self.service.store.list_manifest_ids(), before)

        with self.assertRaisesRegex(ProvenanceServiceError, "already has a stored revocation"):
            self.service.revoke_operational_certificate(
                certificate.certificate.certificate_id,
                root_private_key_handle=self.root_key,
                reason="duplicate",
                effective_at="2026-08-08T20:07:00Z",
            )

    def test_service_exposes_no_model_task_merge_release_or_key_generation_surface(self) -> None:
        for forbidden in (
            "model",
            "generate",
            "generate_key",
            "put_private_key",
            "apply",
            "patch",
            "verify_task",
            "transition_task",
            "transition_goal",
            "merge",
            "release",
            "publish",
            "watermark",
        ):
            self.assertFalse(hasattr(self.service, forbidden))


if __name__ == "__main__":
    unittest.main()
