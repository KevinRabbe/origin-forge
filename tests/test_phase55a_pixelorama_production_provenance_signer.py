from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_pixelorama_provenance_signer import (
    GovernedPixeloramaProductionProvenanceSigner,
    PixeloramaProductionProvenanceSigningBlocked,
    PixeloramaProductionProvenanceSigningFailureCode,
)
from origin_forge.production_pixelorama_task_acceptance_currentness import (
    PixeloramaProductionTaskAcceptanceCurrentnessStatus,
    inspect_pixelorama_production_task_acceptance_currentness_readonly,
)
from origin_forge.production_pixelorama_task_acceptor import (
    GovernedPixeloramaProductionTaskAcceptor,
)
from origin_forge.provenance_crypto import OpenSslEd25519Backend
from origin_forge.provenance_models import OperationalKeyPurpose
from origin_forge.provenance_service import ProvenanceService
from .test_phase50a_pixelorama_production_task_acceptance import (
    Phase50APixeloramaProductionTaskAcceptanceTests,
)
from .test_phase54a_blender_production_provenance_signer import (
    Phase54ABlenderProductionProvenanceSignerTests,
)


NOW = "2026-08-23T03:00:00Z"


class Phase55APixeloramaProductionProvenanceSignerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase50APixeloramaProductionTaskAcceptanceTests(
            methodName=(
                "test_acceptance_atomically_records_exact_task_pass_and_receipt_without_terminalizing_task"
            )
        )
        self.fixture.setUp()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.secret_root = Path(self.secret_temp.name)

    def tearDown(self) -> None:
        self.secret_temp.cleanup()
        self.fixture.tearDown()

    def _published(self):
        binding, adoption, task_revision = self.fixture._published_inputs()
        return self.fixture.fixture.runtime, binding, adoption, task_revision

    def _accepted(self):
        runtime, binding, adoption, _ = self._published()
        accepted = GovernedPixeloramaProductionTaskAcceptor(runtime).accept(
            binding.execution_id,
            actor_id="operator.phase55a.accept",
        )
        currentness = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        return runtime, binding, adoption, accepted

    def _key(self, name: str, openssl: str) -> Path:
        path = self.secret_root / name
        subprocess.run(
            [openssl, "genpkey", "-algorithm", "ED25519", "-out", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def _provenance(self, runtime):
        openssl = shutil.which("openssl")
        if openssl is None:
            self.skipTest("OpenSSL required for Phase 55A signing tests")
        backend = OpenSslEd25519Backend(runtime.project_root)
        service = ProvenanceService(runtime, backend=backend)
        root_key = self._key("root.pem", openssl)
        operational_key = self._key("operational.pem", openssl)
        other_key = self._key("other.pem", openssl)
        service.trust_root_public(
            "Origin Forge Phase 55A Test",
            backend.public_key_der(root_key),
            created_at=NOW,
        )
        certificate = service.issue_operational_certificate(
            backend.public_key_der(operational_key),
            root_private_key_handle=root_key,
            purpose=OperationalKeyPurpose.ARTIFACT_SIGNING,
            issued_at=NOW,
        )
        return service, certificate, operational_key, other_key

    @staticmethod
    def _production_snapshot(runtime, task_id: str, artifact_id: str):
        lineage = OriginForgeLineage(runtime)
        with runtime.store.session() as conn:
            verifications = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT * FROM verifications
                       WHERE (target_type = 'TASK' AND target_id = ?)
                          OR (target_type = 'ARTIFACT' AND target_id = ?)
                       ORDER BY id""",
                    (task_id, artifact_id),
                )
            )
            runs = tuple(tuple(row) for row in conn.execute("SELECT * FROM runs ORDER BY id"))
            events = tuple(
                tuple(row)
                for row in conn.execute(
                    "SELECT * FROM state_events WHERE aggregate_id = ? ORDER BY rowid",
                    (task_id,),
                )
            )
        return (
            dict(runtime.get_task(task_id)),
            dict(lineage.get_artifact(artifact_id)),
            verifications,
            runs,
            events,
        )

    def test_malformed_execution_fails_before_provenance_signing(self) -> None:
        runtime, _, _, _ = self._published()
        signer = GovernedPixeloramaProductionProvenanceSigner(runtime)
        with self.assertRaises(PixeloramaProductionProvenanceSigningBlocked) as caught:
            signer.sign(
                "TASK-not-a-dispatch-execution",
                new_id(IdKind.KEY_CERTIFICATE),
                operational_private_key_handle=self.secret_root / "unused.pem",
            )
        self.assertEqual(
            caught.exception.code,
            PixeloramaProductionProvenanceSigningFailureCode.INVALID_EXECUTION_ID,
        )
        self.assertEqual(signer.provenance_service.store.list_manifest_ids(), ())

    def test_adopted_but_not_terminally_accepted_execution_cannot_be_signed(self) -> None:
        runtime, binding, _, _ = self._published()
        signer = GovernedPixeloramaProductionProvenanceSigner(runtime)
        with self.assertRaises(PixeloramaProductionProvenanceSigningBlocked) as caught:
            signer.sign(
                binding.execution_id,
                new_id(IdKind.KEY_CERTIFICATE),
                operational_private_key_handle=self.secret_root / "unused.pem",
            )
        self.assertEqual(
            caught.exception.code,
            PixeloramaProductionProvenanceSigningFailureCode.TASK_NOT_TERMINALLY_ACCEPTED,
        )
        self.assertEqual(signer.provenance_service.store.list_manifest_ids(), ())
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_terminal_acceptance_signs_exact_adopted_artifact_without_production_mutation(self) -> None:
        runtime, binding, adoption, _ = self._accepted()
        service, certificate, operational_key, _ = self._provenance(runtime)
        artifact_id = adoption.adopted_artifact_id
        self.assertIsNotNone(artifact_id)
        before = self._production_snapshot(runtime, binding.task_id, artifact_id)

        result = GovernedPixeloramaProductionProvenanceSigner(
            runtime,
            provenance_service=service,
        ).sign(
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_private_key_handle=operational_key,
        )

        self.assertEqual(result.execution_id, binding.execution_id)
        self.assertEqual(result.task_id, binding.task_id)
        self.assertEqual(result.adopted_artifact_id, artifact_id)
        self.assertEqual(result.adopted_destination_path, adoption.destination_path)
        self.assertEqual(result.accepted_content_hash, "sha256:" + binding.output_content_hash)
        self.assertEqual(result.accepted_byte_count, binding.output_byte_count)
        self.assertTrue(result.trusted)
        self.assertTrue(result.current)
        self.assertFalse(result.artifact_status_changed)
        self.assertFalse(result.task_status_changed)
        self.assertFalse(result.production_verification_changed)
        self.assertFalse(result.release_authorized)
        self.assertNotIn(str(operational_key), str(result.to_dict()))

        signed = service.store.load_manifest(result.manifest_id)
        manifest = signed.manifest
        self.assertEqual(manifest.artifact_ref.record_id, artifact_id)
        self.assertEqual(manifest.artifact_content_hash, result.accepted_content_hash)
        self.assertEqual(manifest.artifact_type, "SPRITESHEET_EXPORT")
        self.assertEqual(manifest.artifact_location, adoption.destination_path)
        self.assertIsNotNone(manifest.task_ref)
        self.assertEqual(manifest.task_ref.record_id, binding.task_id)
        self.assertIsNotNone(manifest.run_ref)
        self.assertEqual(manifest.run_ref.record_id, binding.run_id)
        verification_ids = {ref.record_id for ref in manifest.verification_refs}
        self.assertIn(adoption.verification_id, verification_ids)
        self.assertIn(result.acceptance_verification_id, verification_ids)
        self.assertEqual(manifest.parent_manifest_refs, ())
        self.assertEqual(OriginForgeLineage(runtime).get_artifact(artifact_id)["status"], "ADOPTED")
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        self.assertEqual(self._production_snapshot(runtime, binding.task_id, artifact_id), before)

    def test_post_acceptance_png_drift_preserves_acceptance_but_blocks_signing(self) -> None:
        runtime, binding, adoption, _ = self._accepted()
        service, certificate, operational_key, _ = self._provenance(runtime)
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"post-acceptance-drift")

        currentness = inspect_pixelorama_production_task_acceptance_currentness_readonly(
            runtime,
            binding.execution_id,
        )
        self.assertEqual(
            currentness.status,
            PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED,
        )
        before_manifests = service.store.list_manifest_ids()
        with self.assertRaises(PixeloramaProductionProvenanceSigningBlocked) as caught:
            GovernedPixeloramaProductionProvenanceSigner(
                runtime,
                provenance_service=service,
            ).sign(
                binding.execution_id,
                certificate.certificate.certificate_id,
                operational_private_key_handle=operational_key,
            )
        self.assertEqual(
            caught.exception.code,
            PixeloramaProductionProvenanceSigningFailureCode.ADOPTED_ARTIFACT_DRIFT,
        )
        self.assertEqual(service.store.list_manifest_ids(), before_manifests)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")

    def test_two_explicit_signing_invocations_create_distinct_manifests_only(self) -> None:
        runtime, binding, adoption, _ = self._accepted()
        service, certificate, operational_key, _ = self._provenance(runtime)
        artifact_id = adoption.adopted_artifact_id
        self.assertIsNotNone(artifact_id)
        signer = GovernedPixeloramaProductionProvenanceSigner(
            runtime,
            provenance_service=service,
        )
        before = self._production_snapshot(runtime, binding.task_id, artifact_id)

        first = signer.sign(
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_private_key_handle=operational_key,
        )
        second = signer.sign(
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_private_key_handle=operational_key,
        )

        self.assertNotEqual(first.manifest_id, second.manifest_id)
        self.assertEqual(
            set(service.store.list_manifest_ids()),
            {first.manifest_id, second.manifest_id},
        )
        self.assertEqual(first.adopted_artifact_id, second.adopted_artifact_id)
        self.assertEqual(first.accepted_content_hash, second.accepted_content_hash)
        self.assertEqual(self._production_snapshot(runtime, binding.task_id, artifact_id), before)

    def test_wrong_operational_key_is_bounded_and_does_not_leak_key_path(self) -> None:
        runtime, binding, _, _ = self._accepted()
        service, certificate, _, other_key = self._provenance(runtime)
        before_manifests = service.store.list_manifest_ids()

        with self.assertRaises(PixeloramaProductionProvenanceSigningBlocked) as caught:
            GovernedPixeloramaProductionProvenanceSigner(
                runtime,
                provenance_service=service,
            ).sign(
                binding.execution_id,
                certificate.certificate.certificate_id,
                operational_private_key_handle=other_key,
            )

        self.assertEqual(
            caught.exception.code,
            PixeloramaProductionProvenanceSigningFailureCode.SIGNING_REJECTED,
        )
        self.assertNotIn(str(other_key), str(caught.exception))
        self.assertEqual(service.store.list_manifest_ids(), before_manifests)

    def test_real_terminal_blender_execution_cannot_enter_pixelorama_signing_path(self) -> None:
        blender = Phase54ABlenderProductionProvenanceSignerTests(
            methodName=(
                "test_terminal_acceptance_signs_exact_adopted_artifact_without_production_mutation"
            )
        )
        blender.setUp()
        try:
            runtime, binding, _, _ = blender._accepted()
            signer = GovernedPixeloramaProductionProvenanceSigner(runtime)
            unused_key = blender.secret_root / "unused-pixelorama-signing.pem"

            with self.assertRaises(PixeloramaProductionProvenanceSigningBlocked) as caught:
                signer.sign(
                    binding.execution_id,
                    new_id(IdKind.KEY_CERTIFICATE),
                    operational_private_key_handle=unused_key,
                )

            self.assertEqual(
                caught.exception.code,
                PixeloramaProductionProvenanceSigningFailureCode.TASK_NOT_TERMINALLY_ACCEPTED,
            )
            self.assertEqual(signer.provenance_service.store.list_manifest_ids(), ())
            self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        finally:
            blender.tearDown()


if __name__ == "__main__":
    unittest.main()
