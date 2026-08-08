from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.provenance_admin_cli import (
    build_parser as build_admin_parser,
    main as admin_main,
)
from origin_forge.provenance_cli import (
    build_parser as build_read_parser,
    main as read_main,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import FlowStatus, TaskStatus


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for provenance CLI tests")
class ProvenanceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.project_temp.name)
        self.secret_root = Path(self.secret_temp.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("provenance-cli-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.openssl = shutil.which("openssl")
        assert self.openssl is not None

        self.root_key = self._key("root.pem")
        self.operational_key = self._key("operational.pem")
        self.root_public = self._public_der(self.root_key, "root.der")
        self.operational_public = self._public_der(
            self.operational_key,
            "operational.der",
        )

        self.goal = self.runtime.create_goal("CLI provenance")
        self.flow = self.runtime.create_flow(self.goal)
        self.runtime.transition_flow(self.flow, FlowStatus.RUNNING, expected_revision=0)
        self.task = self.runtime.create_task(self.flow, "Create signed result")
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
        self.run = self.runtime.start_run(self.task, role="EXECUTOR")
        self.change = self.lineage.create_change(
            self.task,
            summary="Create CLI result",
            change_type="TEST",
            run_id=self.run,
        )
        self.output = self.root / "dist" / "cli.txt"
        self.output.parent.mkdir()
        self.output.write_text("cli bytes\n", encoding="utf-8")
        self.artifact = self.lineage.create_artifact(
            artifact_type="CLI_RESULT",
            path_or_uri=str(self.output),
            change_id=self.change,
            created_by_run_id=self.run,
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

    def _public_der(self, private_key: Path, name: str) -> Path:
        path = self.secret_root / name
        subprocess.run(
            [
                self.openssl,
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-outform",
                "DER",
                "-out",
                str(path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return path

    def _admin(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = admin_main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def _read(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = read_main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    @staticmethod
    def _commands(parser: argparse.ArgumentParser) -> set[str]:
        subparsers = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        if len(subparsers) != 1:
            raise AssertionError("expected exactly one subparser group")
        return set(subparsers[0].choices)

    def test_read_and_admin_surfaces_have_disjoint_bounded_authority(self) -> None:
        self.assertEqual(
            self._commands(build_read_parser()),
            {
                "status",
                "root-show",
                "certificate-list",
                "certificate-show",
                "revocation-list",
                "revocation-show",
                "manifest-list",
                "manifest-show",
                "verify",
            },
        )
        self.assertEqual(
            self._commands(build_admin_parser()),
            {
                "root-trust",
                "certificate-issue",
                "certificate-revoke",
                "sign-artifact",
            },
        )
        all_commands = self._commands(build_read_parser()) | self._commands(
            build_admin_parser()
        )
        for forbidden in (
            "key-generate",
            "generate-key",
            "task-verify",
            "goal-complete",
            "merge",
            "release",
            "publish",
            "watermark",
            "model-sign",
            "policy-update",
        ):
            self.assertNotIn(forbidden, all_commands)

    def test_admin_lifecycle_is_inspectable_read_only_and_does_not_change_task(self) -> None:
        task_before = self.runtime.get_task(self.task)

        code, root_payload = self._admin(
            "root-trust",
            "--display-name",
            "Origin Forge Test",
            "--public-key-der",
            str(self.root_public),
        )
        self.assertEqual(code, 0)
        self.assertFalse(root_payload["private_key_stored"])
        self.assertFalse(root_payload["key_generated"])

        code, certificate_payload = self._admin(
            "certificate-issue",
            "--operational-public-key-der",
            str(self.operational_public),
            "--root-private-key",
            str(self.root_key),
        )
        self.assertEqual(code, 0)
        certificate_id = certificate_payload["certificate"]["certificate"][
            "certificate_id"
        ]
        self.assertFalse(certificate_payload["private_key_stored"])
        self.assertFalse(certificate_payload["key_generated"])

        code, sign_payload = self._admin(
            "sign-artifact",
            self.artifact,
            "--certificate",
            certificate_id,
            "--private-key",
            str(self.operational_key),
        )
        self.assertEqual(code, 0)
        manifest_id = sign_payload["signed_manifest"]["manifest"]["manifest_id"]
        self.assertFalse(sign_payload["private_key_stored"])
        self.assertFalse(sign_payload["task_status_changed"])
        self.assertFalse(sign_payload["artifact_status_changed"])
        self.assertFalse(sign_payload["automatic_release_performed"])

        code, status = self._read("status")
        self.assertEqual(code, 0)
        self.assertEqual(len(status["root_ids"]), 1)
        self.assertEqual(status["certificate_ids"], [certificate_id])
        self.assertEqual(status["manifest_ids"], [manifest_id])
        self.assertFalse(status["private_keys_stored"])
        self.assertFalse(status["mutation_commands_enabled"])

        code, verification = self._read("verify", manifest_id)
        self.assertEqual(code, 0)
        self.assertTrue(verification["trusted_and_current"])
        self.assertTrue(verification["cryptographic"]["trusted"])
        self.assertTrue(verification["freshness"]["current"])
        self.assertFalse(verification["production_verification_changed"])
        self.assertFalse(verification["task_status_changed"])
        self.assertEqual(self.runtime.get_task(self.task), task_before)

        code, revocation_payload = self._admin(
            "certificate-revoke",
            certificate_id,
            "--root-private-key",
            str(self.root_key),
            "--reason",
            "test revocation",
        )
        self.assertEqual(code, 0)
        revocation_id = revocation_payload["revocation"]["revocation"][
            "revocation_id"
        ]
        code, listed = self._read("revocation-list")
        self.assertEqual(code, 0)
        self.assertEqual(listed["revocations"], [revocation_id])
        code, verification = self._read("verify", manifest_id)
        self.assertEqual(code, 4)
        self.assertFalse(verification["cryptographic"]["trusted"])
        self.assertTrue(verification["cryptographic"]["key_revoked"])
        self.assertEqual(self.runtime.get_task(self.task), task_before)

    def test_relative_private_key_path_is_structured_failure_and_persists_no_certificate(self) -> None:
        code, _ = self._admin(
            "root-trust",
            "--display-name",
            "Origin Forge Test",
            "--public-key-der",
            str(self.root_public),
        )
        self.assertEqual(code, 0)

        code, payload = self._admin(
            "certificate-issue",
            "--operational-public-key-der",
            str(self.operational_public),
            "--root-private-key",
            "relative-root.pem",
        )
        self.assertEqual(code, 2)
        self.assertIn("private key path must be absolute", payload["detail"])
        code, listed = self._read("certificate-list")
        self.assertEqual(code, 0)
        self.assertEqual(listed["certificates"], [])

    def test_public_key_reader_rejects_symlink_without_following_it(self) -> None:
        link = self.secret_root / "public-link.der"
        try:
            link.symlink_to(self.root_public)
        except (OSError, NotImplementedError):
            return
        code, payload = self._admin(
            "root-trust",
            "--display-name",
            "Origin Forge Test",
            "--public-key-der",
            str(link),
        )
        self.assertEqual(code, 2)
        self.assertIn("public key path may not be a symlink", payload["detail"])
        code, status = self._read("status")
        self.assertEqual(code, 0)
        self.assertEqual(status["root_ids"], [])


if __name__ == "__main__":
    unittest.main()
