from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from origin_forge import pixelorama_admin_cli
from origin_forge.ids import IdKind, new_id
from origin_forge.provenance_crypto import OpenSslEd25519Backend
from origin_forge.provenance_models import OperationalKeyPurpose
from origin_forge.runtime import OriginForgeRuntime
from test_phase54a_blender_production_provenance_signer import (
    Phase54ABlenderProductionProvenanceSignerTests,
)
from test_phase55a_pixelorama_production_provenance_signer import (
    Phase55APixeloramaProductionProvenanceSignerTests,
)


class Phase55BPixeloramaProductionProvenanceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase55APixeloramaProductionProvenanceSignerTests(
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
            code = pixelorama_admin_cli.main(
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
            raise AssertionError("Pixelorama admin CLI output must be one JSON object")
        return code, payload, raw

    def test_module_operator_signs_exact_terminal_pixelorama_artifact_without_production_mutation(self) -> None:
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
        self.assertEqual(payload["accepted_content_hash"], "sha256:" + binding.output_content_hash)
        self.assertEqual(payload["accepted_byte_count"], binding.output_byte_count)
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

        signed = service.store.load_manifest(str(payload["manifest_id"]))
        verification_ids = {ref.record_id for ref in signed.manifest.verification_refs}
        self.assertEqual(signed.manifest.artifact_ref.record_id, artifact_id)
        self.assertEqual(signed.manifest.task_ref.record_id, binding.task_id)
        self.assertEqual(signed.manifest.run_ref.record_id, binding.run_id)
        self.assertIn(adoption.verification_id, verification_ids)
        self.assertIn(payload["acceptance_verification_id"], verification_ids)
        self.assertEqual(signed.manifest.parent_manifest_refs, ())

    def test_adopted_but_not_accepted_execution_is_bounded_and_does_not_sign(self) -> None:
        runtime, binding, _, _ = self.fixture._published()
        unused_key = self.fixture.secret_root / "unused-not-accepted.pem"

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            new_id(IdKind.KEY_CERTIFICATE),
            unused_key,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "TASK_NOT_TERMINALLY_ACCEPTED")
        self.assertEqual(
            payload["detail"],
            "Pixelorama production execution is not terminally accepted",
        )
        self.assertNotIn(str(unused_key), raw)
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "RUNNING")

    def test_terminal_acceptance_with_later_png_drift_fails_without_manifest_or_key_leak(self) -> None:
        runtime, binding, adoption, _ = self.fixture._accepted()
        destination = runtime.project_root / adoption.destination_path
        destination.write_bytes(destination.read_bytes() + b"drift")
        unused_key = self.fixture.secret_root / "unused-drift.pem"

        code, payload, raw = self._invoke(
            runtime,
            binding.execution_id,
            new_id(IdKind.KEY_CERTIFICATE),
            unused_key,
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ADOPTED_ARTIFACT_DRIFT")
        self.assertEqual(
            payload["detail"],
            "canonical adopted Pixelorama Artifact is not current",
        )
        self.assertNotIn(str(unused_key), raw)
        from origin_forge.provenance_service import ProvenanceService

        self.assertEqual(ProvenanceService(runtime).store.list_manifest_ids(), ())
        self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")

    def test_release_signing_certificate_cannot_sign_production_artifact(self) -> None:
        runtime, binding, _, _ = self.fixture._accepted()
        service, _, _, other_key = self.fixture._provenance(runtime)
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
            other_runtime.initialize("phase55b-other-project")
            unused_key = Path(other.name).parent / "phase55b-unused-external.pem"

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

    def test_terminal_blender_execution_cannot_enter_pixelorama_operator_path(self) -> None:
        blender = Phase54ABlenderProductionProvenanceSignerTests(
            methodName=(
                "test_terminal_acceptance_signs_exact_adopted_artifact_without_production_mutation"
            )
        )
        blender.setUp()
        try:
            runtime, binding, _, _ = blender._accepted()
            unused_key = blender.secret_root / "unused-phase55b-blender.pem"

            code, payload, raw = self._invoke(
                runtime,
                binding.execution_id,
                new_id(IdKind.KEY_CERTIFICATE),
                unused_key,
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["error"], "TASK_NOT_TERMINALLY_ACCEPTED")
            self.assertNotIn(str(unused_key), raw)
            self.assertEqual(runtime.get_task(binding.task_id)["status"], "SUCCEEDED")
        finally:
            blender.tearDown()

    def test_two_explicit_operator_invocations_create_distinct_manifests_only(self) -> None:
        runtime, binding, adoption, _ = self.fixture._accepted()
        service, certificate, operational_key, _ = self.fixture._provenance(runtime)
        artifact_id = adoption.adopted_artifact_id
        self.assertIsNotNone(artifact_id)
        before = self.fixture._production_snapshot(runtime, binding.task_id, artifact_id)

        first_code, first, _ = self._invoke(
            runtime,
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_key,
        )
        second_code, second, _ = self._invoke(
            runtime,
            binding.execution_id,
            certificate.certificate.certificate_id,
            operational_key,
        )

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertNotEqual(first["manifest_id"], second["manifest_id"])
        self.assertEqual(
            set(service.store.list_manifest_ids()),
            {first["manifest_id"], second["manifest_id"]},
        )
        self.assertEqual(first["adopted_artifact_id"], second["adopted_artifact_id"])
        self.assertEqual(first["accepted_content_hash"], second["accepted_content_hash"])
        self.assertEqual(
            self.fixture._production_snapshot(runtime, binding.task_id, artifact_id),
            before,
        )

    def test_signing_parser_has_only_three_authorized_signing_inputs_and_old_grammar_is_unchanged(self) -> None:
        parser = pixelorama_admin_cli.build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        signing = subparsers.choices["sign-production-provenance"]
        signing_options = {
            option
            for action in signing._actions
            for option in action.option_strings
            if option != "--help" and option != "-h"
        }
        self.assertEqual(
            signing_options,
            {"--execution-id", "--certificate-id", "--operational-private-key"},
        )
        signing_positionals = [
            action.dest
            for action in signing._actions
            if not action.option_strings and action.dest != "help"
        ]
        self.assertEqual(signing_positionals, [])

        old_adopt = parser.parse_args(
            ["adopt-production-new", "DISPEXEC-old", "assets/old.png"]
        )
        self.assertEqual(old_adopt.execution_id, "DISPEXEC-old")
        self.assertEqual(old_adopt.destination_relative_path, "assets/old.png")
        old_accept = parser.parse_args(["accept-production-task", "DISPEXEC-old"])
        self.assertEqual(old_accept.execution_id, "DISPEXEC-old")

        forbidden = {
            "artifact_id",
            "task_id",
            "run_id",
            "verification_id",
            "destination",
            "source",
            "expected_hash",
            "expected_byte_count",
            "acceptance_override",
            "force",
            "bypass",
            "overwrite",
            "parent_manifest_ids",
            "root_private_key",
            "release",
            "publish",
            "deploy",
            "media",
            "model",
            "tool",
            "specialist",
        }
        self.assertTrue(forbidden.isdisjoint({action.dest for action in signing._actions}))

    def test_package_scripts_remain_exactly_three_and_signing_path_does_not_call_old_authorities(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)["project"]
        self.assertEqual(
            project["scripts"],
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )

        with tempfile.TemporaryDirectory() as tempdir:
            project_root = Path(tempdir)
            with patch.object(
                pixelorama_admin_cli,
                "GovernedPixeloramaProductionProvenanceSigner",
            ) as signer_cls, patch.object(
                pixelorama_admin_cli,
                "GovernedPixeloramaOutputAdopter",
            ) as legacy_adopter, patch.object(
                pixelorama_admin_cli,
                "GovernedPixeloramaProductionOutputAdopter",
            ) as production_adopter, patch.object(
                pixelorama_admin_cli,
                "GovernedPixeloramaProductionTaskAcceptor",
            ) as task_acceptor:
                signer_cls.return_value.sign.return_value.to_dict.return_value = {
                    "execution_id": "DISPEXEC-test",
                    "release_authorized": False,
                }
                output = io.StringIO()
                with redirect_stdout(output):
                    code = pixelorama_admin_cli.main(
                        [
                            "--project-root",
                            str(project_root),
                            "sign-production-provenance",
                            "--execution-id",
                            "DISPEXEC-test",
                            "--certificate-id",
                            "KEYCERT-test",
                            "--operational-private-key",
                            str(project_root.parent / "external-key.pem"),
                        ]
                    )

                self.assertEqual(code, 0)
                signer_cls.assert_called_once()
                signer_cls.return_value.sign.assert_called_once()
                legacy_adopter.assert_not_called()
                production_adopter.assert_not_called()
                task_acceptor.assert_not_called()
                payload = json.loads(output.getvalue())
                self.assertFalse(payload["release_authorized"])


if __name__ == "__main__":
    unittest.main()
