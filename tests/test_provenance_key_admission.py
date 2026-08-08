from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.provenance_crypto import OpenSslEd25519Backend
from origin_forge.provenance_service import ProvenanceService, ProvenanceServiceError
from origin_forge.runtime import OriginForgeRuntime


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for provenance key admission tests")
class ProvenanceKeyAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.project_temp.name)
        self.secret_root = Path(self.secret_temp.name)
        self.runtime = OriginForgeRuntime(self.project_root)
        self.runtime.initialize("provenance-key-admission-test")
        self.openssl = shutil.which("openssl")
        assert self.openssl is not None
        self.backend = OpenSslEd25519Backend(self.project_root)
        self.service = ProvenanceService(self.runtime, backend=self.backend)

    def tearDown(self) -> None:
        self.project_temp.cleanup()
        self.secret_temp.cleanup()

    def _ed25519_key(self, name: str) -> Path:
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

    def _rsa_public_der(self) -> bytes:
        private = self.secret_root / "rsa.pem"
        public = self.secret_root / "rsa.der"
        subprocess.run(
            [
                self.openssl,
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                self.openssl,
                "pkey",
                "-in",
                str(private),
                "-pubout",
                "-outform",
                "DER",
                "-out",
                str(public),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return public.read_bytes()

    def test_rsa_public_key_cannot_enter_ed25519_trust_or_certificate_flow(self) -> None:
        rsa_public = self._rsa_public_der()
        with self.assertRaisesRegex(ProvenanceServiceError, "not canonical Ed25519"):
            self.service.trust_root_public("Not Ed25519", rsa_public)
        self.assertEqual(self.service.store.list_root_ids(), ())

        root_key = self._ed25519_key("root.pem")
        self.service.trust_root_public(
            "Origin Forge",
            self.backend.public_key_der(root_key),
        )
        with self.assertRaisesRegex(ProvenanceServiceError, "not canonical Ed25519"):
            self.service.issue_operational_certificate(
                rsa_public,
                root_private_key_handle=root_key,
            )
        self.assertEqual(self.service.store.list_certificate_ids(), ())


if __name__ == "__main__":
    unittest.main()
