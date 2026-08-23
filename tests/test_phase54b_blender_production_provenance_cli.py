from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from origin_forge import blender_admin_cli
from origin_forge.ids import IdKind, new_id
from origin_forge.production_pixelorama_export import PixeloramaCliExportService
from origin_forge.provenance_crypto import OpenSslEd25519Backend
from origin_forge.provenance_models import OperationalKeyPurpose
from origin_forge.runtime import OriginForgeRuntime
from test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests
from test_phase54a_blender_production_provenance_signer import (
    Phase54ABlenderProductionProvenanceSignerTests,
)


class Phase54BBlenderProductionProvenanceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase54ABlenderProductionProvenanceSignerTests(
            methodName=(
                "test_terminal_acceptance_signs_exact_adopted_artifact_without_production_mutation"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    @staticmethod
    def _invoke(
        runtime: OriginForgeRuntime,
        execution_id: str,
        certificate_id: str,
        private_key: Path,
    ) -> tuple[int, dict[str, object], str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = blender_admin_cli.main(
                [
                    "--project-root",
                    str(runtime.project_root),
                    "sign-production-provenance",
                    "--execution-id",
                    execution_id,
                    "--certificate-id",
                    certificate_id,
                    "--operational-private-key",
                    str(private_key),
                ]
            )
        raw = output.getvalue()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AssertionError("Blender admin CLI output must be one JSON object")
        return code, payload, raw

    def test_module_operator_signs_exact_terminal_blender_artifact_without_production_mutation(self) -> None:
        runtime, binding, adoption, _ = self.fixture._accepted()
        service, certificate, operational_key, _ = self.fixture._provenance(runtime)
        artifact_id = adoption.adopted_artifact_id
        self.assertIsNotNone(artifact_id)
        destination = runtime.project_root / adoption.destination_path
        bytes_before = destination.read_bytes()
        production_before = self.fixture._production_snapshot(
            runtime,
            binding.task_id,
            artifact_id,
        )
        manifests_before = service.store.list_manifest_ids()

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_key,
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["execution_id"], binding.execution_id)
        self.assertEqual(payload["task_id"], binding.task_id)
        self.assertEqual(payload["adopted_artifact_id"], artifact_id)
        self.assertEqual(payload["adopted_destination_path"], adoption.destination_path)
        self.assertTrue(payload["trusted"])
        self.assertTrue(payload["current"])
        self.assertFalse(payload["artifact_status_changed"])
        self.assertFalse(payload["task_status_changed"])
        self.assertFalse(payload["production_verification_changed"])
        self.assertFalse(payload["release_authorized"])
        self.assertNotIn(str(operational_key), raw)
        self.assertEqual(destination.read_bytes(), bytes_before)
        self.assertEqual(
            self.fixture._production_snapshot(runtime, binding.task_id, artifact_id),
            production_before,
        )
        manifests_after = service.store.list_manifest_ids()
        self.assertEqual(len(manifests_after), len(manifests_before) + 1)
        self.assertIn(payload["manifest_id"], manifests_after)

    def test_adopted_but_not_accepted_execution_is_bounded_and_does_not_sign(self) -> None:
        runtime, binding, _, _, _ = self.fixture._published()
        certificate_id = new_id(IdKind.KEY_CERTIFICATE)
        unused_key = self.fixture.secret_root / "unused.pem"

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            certificate_id,
            unused_key,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "TASK_NOT_TERMINALLY_ACCEPTED")
        self.assertEqual(
            payload["detail"],
            "Blender production execution is not terminally accepted",
        )
        self.assertNotIn(str(unused_key), raw)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_terminal_acceptance_with_later_glb_drift_fails_without_manifest_or_key_leak(self) -> None:
        runtime, binding, adoption, _ = self.fixture._accepted()
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"drift")
        unused_key = self.fixture.secret_root / "unused-drift.pem"
        certificate_id = new_id(IdKind.KEY_CERTIFICATE)

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            certificate_id,
            unused_key,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ADOPTED_ARTIFACT_DRIFT")
        self.assertEqual(
            payload["detail"],
            "canonical adopted Blender Artifact is not current",
        )
        self.assertNotIn(str(unused_key), raw)
        from origin_forge.provenance_service import ProvenanceService

        self.assertEqual(ProvenanceService(runtime).store.list_manifest_ids(), ())

    def test_release_signing_certificate_cannot_sign_production_artifact(self) -> None:
        runtime, binding, _, _ = self.fixture._accepted()
        service, _, operational_key, other_key = self.fixture._provenance(runtime)
        backend = OpenSslEd25519Backend(runtime.project_root)
        release_certificate = service.issue_operational_certificate(
            backend.public_key_der(other_key),
            root_private_key_handle=self.fixture.secret_root / "root.pem",
            purpose=OperationalKeyPurpose.RELEASE_SIGNING,
        )
        manifests_before = service.store.list_manifest_ids()

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            release_certificate.certificate.certificate_id,
            other_key,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "SIGNING_REJECTED")
        self.assertEqual(payload["detail"], "Phase-18 provenance signing was rejected")
        self.assertNotIn(str(other_key), raw)
        self.assertEqual(service.store.list_manifest_ids(), manifests_before)
        self.assertTrue(operational_key.is_file())

    def test_project_contained_private_key_is_rejected_without_secret_path_leak(self) -> None:
        runtime, binding, _, _ = self.fixture._accepted()
        service, certificate, operational_key, _ = self.fixture._provenance(runtime)
        contained = runtime.project_root / "contained-operational-key.pem"
        shutil.copyfile(operational_key, contained)
        if os.name != "nt":
            contained.chmod(0o600)
        manifests_before = service.store.list_manifest_ids()

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            certificate.certificate.certificate_id,
            contained,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "SIGNING_REJECTED")
        self.assertEqual(payload["detail"], "Phase-18 provenance signing was rejected")
        self.assertNotIn(str(contained), raw)
        self.assertEqual(service.store.list_manifest_ids(), manifests_before)

    def test_execution_from_another_project_cannot_be_signed(self) -> None:
        source_runtime, binding, _, _ = self.fixture._accepted()
        other = tempfile.TemporaryDirectory()
        try:
            other_runtime = OriginForgeRuntime(Path(other.name))
            other_runtime.initialize("phase54b-other-project")
            unused_key = Path(other.name).parent / "phase54b-unused-external.pem"

            code, payload, raw = self._invoke(
                other_runtime,
                binding.execution_id,
                new_id(IdKind.KEY_CERTIFICATE),
                unused_key,
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["error"], "TASK_NOT_TERMINALLY_ACCEPTED")
            self.assertNotIn(str(unused_key), raw)
            self.assertEqual(source_runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        finally:
            other.cleanup()


class Phase54BPixeloramaExclusionTests(unittest.TestCase):
    def test_real_returned_pixelorama_execution_cannot_enter_blender_signing_path(self) -> None:
        fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        fixture.setUp()
        try:
            fixture.test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns()
            execution = fixture._execution()
            execution_id = execution["execution_id"]
            self.assertIsInstance(execution_id, str)
            output = io.StringIO()
            unused_key = fixture.root.parent / "phase54b-pixelorama-unused.pem"
            with redirect_stdout(output):
                code = blender_admin_cli.main(
                    [
                        "--project-root",
                        str(fixture.runtime.project_root),
                        "sign-production-provenance",
                        "--execution-id",
                        execution_id,
                        "--certificate-id",
                        new_id(IdKind.KEY_CERTIFICATE),
                        "--operational-private-key",
                        str(unused_key),
                    ]
                )
            raw = output.getvalue()
            payload = json.loads(raw)

            self.assertEqual(code, 2)
            self.assertEqual(payload["error"], "TASK_NOT_TERMINALLY_ACCEPTED")
            self.assertNotIn(str(unused_key), raw)
            from origin_forge.provenance_service import ProvenanceService

            self.assertEqual(
                ProvenanceService(fixture.runtime).store.list_manifest_ids(),
                (),
            )
            self.assertEqual(fixture.runtime.get_task(fixture.task_id)["status"], "RUNNING")
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
