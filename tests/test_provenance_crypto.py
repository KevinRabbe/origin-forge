from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.provenance_crypto import (
    CERTIFICATE_DOMAIN,
    PROVENANCE_MANIFEST_DOMAIN,
    OpenSslEd25519Backend,
    OperationalManifestSigner,
    RootAuthority,
    SecretContainmentError,
    SignatureBackendError,
    certificate_message,
    domain_message,
    provenance_manifest_message,
)
from origin_forge.provenance_models import (
    CompanyRootIdentity,
    DetachedSignature,
    OperationalKeyCertificate,
    OperationalKeyPurpose,
    ProvenanceManifest,
    ProvenanceModelError,
    ProvenanceRecordRef,
    ProvenanceRecordType,
    SignatureAlgorithm,
    canonical_hash,
    public_key_b64,
    public_key_fingerprint,
)


NOW = "2026-08-08T20:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def make_ref(record_type: ProvenanceRecordType, kind: IdKind, digest: str = HASH_A, revision=None):
    return ProvenanceRecordRef(record_type, new_id(kind), digest, revision)


def minimal_manifest(root: CompanyRootIdentity) -> ProvenanceManifest:
    return ProvenanceManifest(
        manifest_id=new_id(IdKind.PROVENANCE_MANIFEST),
        schema_version=1,
        company_id=root.company_id,
        root_identity_hash=root.content_hash,
        project_ref=make_ref(ProvenanceRecordType.PROJECT, IdKind.PROJECT),
        artifact_ref=make_ref(ProvenanceRecordType.ARTIFACT, IdKind.ARTIFACT, HASH_B),
        artifact_content_hash=HASH_A,
        artifact_type="TEST_ARTIFACT",
        artifact_location="out/result.bin",
        task_ref=make_ref(ProvenanceRecordType.TASK, IdKind.TASK, revision=2),
        run_ref=make_ref(ProvenanceRecordType.RUN, IdKind.RUN),
        model_id="test-model",
        model_hash=HASH_B,
        model_profile="coder-strong",
        skill_refs=("review@1.0.0",),
        tool_refs=("git@system",),
        created_at=NOW,
    )


class ProvenanceModelTests(unittest.TestCase):
    def test_root_identity_binds_exact_public_key_fingerprint(self) -> None:
        public = b"test-public-key-der"
        root = CompanyRootIdentity.create("Origin Forge Test", public, created_at=NOW)
        self.assertEqual(root.public_key_der_b64, public_key_b64(public))
        self.assertEqual(root.public_key_fingerprint, public_key_fingerprint(public))
        self.assertTrue(root.content_hash.startswith("sha256:"))
        with self.assertRaisesRegex(ProvenanceModelError, "fingerprint mismatch"):
            CompanyRootIdentity(
                root.company_id,
                root.display_name,
                root.root_key_id,
                root.algorithm,
                root.public_key_der_b64,
                HASH_A,
                root.created_at,
            )

    def test_detached_signature_is_strict_ed25519_and_payload_bound(self) -> None:
        key_id = new_id(IdKind.PROVENANCE_KEY)
        signature = DetachedSignature.create(
            key_id=key_id,
            algorithm=SignatureAlgorithm.ED25519,
            signed_payload_hash=HASH_A,
            signature=b"s" * 64,
        )
        self.assertEqual(signature.signature_bytes, b"s" * 64)
        self.assertTrue(signature.signature_hash.startswith("sha256:"))
        with self.assertRaisesRegex(ProvenanceModelError, "exactly 64"):
            DetachedSignature.create(
                key_id=key_id,
                algorithm=SignatureAlgorithm.ED25519,
                signed_payload_hash=HASH_A,
                signature=b"short",
            )

    def test_signature_domains_are_distinct_and_bounded(self) -> None:
        payload = {"value": 1}
        cert = domain_message(CERTIFICATE_DOMAIN, payload)
        manifest = domain_message(PROVENANCE_MANIFEST_DOMAIN, payload)
        self.assertNotEqual(cert, manifest)
        self.assertNotEqual(canonical_hash(cert.hex()), canonical_hash(manifest.hex()))
        with self.assertRaisesRegex(SignatureBackendError, "exceeds byte limit"):
            domain_message(CERTIFICATE_DOMAIN, {"value": "x" * 100}, maximum=8)

    def test_manifest_normalizes_refs_and_keeps_signature_authority_outside_payload(self) -> None:
        root = CompanyRootIdentity.create("Root", b"der", created_at=NOW)
        manifest = minimal_manifest(root)
        payload = manifest.to_dict()
        self.assertNotIn("signature", payload)
        self.assertNotIn("trusted", payload)
        self.assertNotIn("verified", payload)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["content_hash"].startswith("sha256:"))


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for Ed25519 integration tests")
class OpenSslProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.project_temp.name)
        self.secret_root = Path(self.secret_temp.name)
        self.openssl = shutil.which("openssl")
        assert self.openssl is not None
        self.root_key = self.secret_root / "root.pem"
        self.operational_key = self.secret_root / "operational.pem"
        self.other_key = self.secret_root / "other.pem"
        for path in (self.root_key, self.operational_key, self.other_key):
            subprocess.run(
                [self.openssl, "genpkey", "-algorithm", "ED25519", "-out", str(path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if os.name != "nt":
                path.chmod(0o600)
        self.backend = OpenSslEd25519Backend(self.project_root)

    def tearDown(self) -> None:
        self.project_temp.cleanup()
        self.secret_temp.cleanup()

    def test_real_ed25519_round_trip_and_tampering(self) -> None:
        public = self.backend.public_key_der(self.root_key)
        signature = self.backend.sign(self.root_key, b"message")
        self.assertEqual(len(signature), 64)
        self.assertTrue(self.backend.verify(public, b"message", signature))
        self.assertFalse(self.backend.verify(public, b"changed", signature))
        altered = signature[:-1] + bytes([signature[-1] ^ 1])
        self.assertFalse(self.backend.verify(public, b"message", altered))
        other_public = self.backend.public_key_der(self.other_key)
        self.assertFalse(self.backend.verify(other_public, b"message", signature))

    def test_root_certificate_and_operational_manifest_signature_chain(self) -> None:
        root_public = self.backend.public_key_der(self.root_key)
        root = CompanyRootIdentity.create("Origin Forge", root_public, created_at=NOW)
        operational_public = self.backend.public_key_der(self.operational_key)
        certificate = OperationalKeyCertificate.create(
            root,
            purpose=OperationalKeyPurpose.ARTIFACT_SIGNING,
            public_key_der=operational_public,
            issued_at=NOW,
        )
        signed_certificate = RootAuthority(root, self.backend, self.root_key).sign_certificate(
            certificate
        )
        self.assertTrue(
            self.backend.verify(
                root_public,
                certificate_message(certificate),
                signed_certificate.root_signature.signature_bytes,
            )
        )

        manifest = minimal_manifest(root)
        signed_manifest = OperationalManifestSigner(
            signed_certificate,
            self.backend,
            self.operational_key,
        ).sign(manifest)
        self.assertTrue(
            self.backend.verify(
                operational_public,
                provenance_manifest_message(manifest),
                signed_manifest.signature.signature_bytes,
            )
        )
        self.assertEqual(signed_manifest.signing_key_id, certificate.key_id)
        self.assertEqual(
            signed_manifest.signing_certificate_hash,
            signed_certificate.content_hash,
        )

    def test_private_key_paths_fail_closed_before_secret_use(self) -> None:
        with self.assertRaisesRegex(SecretContainmentError, "must be absolute"):
            self.backend.sign(Path("relative.pem"), b"message")

        inside = self.project_root / "inside.pem"
        shutil.copyfile(self.root_key, inside)
        if os.name != "nt":
            inside.chmod(0o600)
        with self.assertRaisesRegex(SecretContainmentError, "outside the project root"):
            self.backend.sign(inside, b"message")

        link = self.secret_root / "link.pem"
        try:
            link.symlink_to(self.root_key)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaisesRegex(SecretContainmentError, "symlink"):
                self.backend.sign(link, b"message")

        if os.name != "nt":
            insecure = self.secret_root / "insecure.pem"
            shutil.copyfile(self.root_key, insecure)
            insecure.chmod(0o644)
            with self.assertRaisesRegex(SecretContainmentError, "group/world"):
                self.backend.sign(insecure, b"message")

    def test_message_limit_and_key_identity_checks_fail_closed(self) -> None:
        small = OpenSslEd25519Backend(self.project_root, max_message_bytes=4)
        with self.assertRaisesRegex(SignatureBackendError, "exceeds byte limit"):
            small.sign(self.root_key, b"12345")

        root_public = self.backend.public_key_der(self.root_key)
        root = CompanyRootIdentity.create("Origin Forge", root_public, created_at=NOW)
        with self.assertRaisesRegex(SecretContainmentError, "does not match"):
            RootAuthority(root, self.backend, self.other_key)

        operational_public = self.backend.public_key_der(self.operational_key)
        build_certificate = OperationalKeyCertificate.create(
            root,
            purpose=OperationalKeyPurpose.BUILD_SIGNING,
            public_key_der=operational_public,
            issued_at=NOW,
        )
        signed_build = RootAuthority(root, self.backend, self.root_key).sign_certificate(
            build_certificate
        )
        with self.assertRaisesRegex(SignatureBackendError, "not authorized"):
            OperationalManifestSigner(
                signed_build,
                self.backend,
                self.operational_key,
            )

    def test_crypto_services_have_no_model_task_or_merge_authority(self) -> None:
        root = CompanyRootIdentity.create(
            "Origin Forge",
            self.backend.public_key_der(self.root_key),
            created_at=NOW,
        )
        authority = RootAuthority(root, self.backend, self.root_key)
        for obj in (self.backend, authority):
            for forbidden in (
                "generate",
                "model",
                "apply",
                "patch",
                "verify_task",
                "transition_task",
                "merge",
                "release",
                "delegate",
            ):
                self.assertFalse(hasattr(obj, forbidden))


if __name__ == "__main__":
    unittest.main()
