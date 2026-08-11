from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.provenance_read as read_module
from origin_forge.ids import IdKind, new_id
from origin_forge.provenance_models import (
    CompanyRootIdentity,
    DetachedSignature,
    OperationalKeyCertificate,
    OperationalKeyPurpose,
    OperationalKeyRevocation,
    ProvenanceManifest,
    ProvenanceRecordRef,
    ProvenanceRecordType,
    SignatureAlgorithm,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
)
from origin_forge.provenance_read import ProvenanceReadError, ProvenanceReadService
from origin_forge.provenance_store import ProvenanceStore
from origin_forge.runtime import OriginForgeRuntime


NOW = "2026-08-11T01:00:00Z"
LATER = "2026-08-11T02:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class ProvenanceReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("provenance-read-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _public_fixture(self) -> tuple[str, str, str, str]:
        store = ProvenanceStore(self.runtime)
        root = CompanyRootIdentity.create(
            "Origin Forge Test",
            b"root-public-key",
            created_at=NOW,
        )
        certificate = OperationalKeyCertificate.create(
            root,
            purpose=OperationalKeyPurpose.ARTIFACT_SIGNING,
            public_key_der=b"operational-public-key",
            issued_at=NOW,
        )
        signed_certificate = SignedOperationalKeyCertificate(
            certificate,
            DetachedSignature.create(
                key_id=root.root_key_id,
                algorithm=SignatureAlgorithm.ED25519,
                signed_payload_hash=certificate.content_hash,
                signature=b"c" * 64,
            ),
        )
        revocation = OperationalKeyRevocation.create(
            root,
            certificate,
            reason="retired test key",
            effective_at=LATER,
        )
        signed_revocation = SignedOperationalKeyRevocation(
            revocation,
            DetachedSignature.create(
                key_id=root.root_key_id,
                algorithm=SignatureAlgorithm.ED25519,
                signed_payload_hash=revocation.content_hash,
                signature=b"r" * 64,
            ),
        )
        artifact_id = new_id(IdKind.ARTIFACT)
        manifest = ProvenanceManifest(
            manifest_id=new_id(IdKind.PROVENANCE_MANIFEST),
            schema_version=1,
            company_id=root.company_id,
            root_identity_hash=root.content_hash,
            project_ref=ProvenanceRecordRef(
                ProvenanceRecordType.PROJECT,
                self.runtime.project_id(),
                HASH_A,
            ),
            artifact_ref=ProvenanceRecordRef(
                ProvenanceRecordType.ARTIFACT,
                artifact_id,
                HASH_B,
            ),
            artifact_content_hash=HASH_C,
            artifact_type="SOURCE",
            artifact_location="artifact.txt",
            model_id="model-id",
            model_hash=HASH_A,
            model_profile="coding-small",
            skill_refs=("SECRET_SKILL_REF",),
            tool_refs=("SECRET_TOOL_REF",),
            created_at=NOW,
        )
        signed_manifest = SignedProvenanceManifest(
            manifest=manifest,
            signing_key_id=certificate.key_id,
            signing_certificate_hash=signed_certificate.content_hash,
            signature=DetachedSignature.create(
                key_id=certificate.key_id,
                algorithm=SignatureAlgorithm.ED25519,
                signed_payload_hash=manifest.content_hash,
                signature=b"m" * 64,
            ),
        )
        store.put_root(root)
        store.put_certificate(signed_certificate)
        store.put_revocation(signed_revocation)
        store.put_manifest(signed_manifest)
        return (
            root.company_id,
            certificate.certificate_id,
            revocation.revocation_id,
            manifest.manifest_id,
        )

    def test_absent_provenance_remains_absent_after_inspection(self) -> None:
        provenance = self.runtime.state_dir / "provenance"
        self.assertFalse(provenance.exists())
        reader = ProvenanceReadService(self.runtime)
        self.assertEqual(
            reader.counts(),
            {"roots": 0, "certificates": 0, "revocations": 0, "manifests": 0},
        )
        self.assertEqual(reader.roots(), ())
        self.assertEqual(reader.certificates(), ())
        self.assertEqual(reader.revocations(), ())
        self.assertEqual(reader.manifests(), ())
        self.assertFalse(provenance.exists())

    def test_canonical_public_objects_are_validated_and_redacted(self) -> None:
        root_id, cert_id, revocation_id, manifest_id = self._public_fixture()
        reader = ProvenanceReadService(self.runtime)
        before = sorted(
            (str(path.relative_to(self.runtime.state_dir)), path.stat().st_mtime_ns)
            for path in (self.runtime.state_dir / "provenance").rglob("*")
        )
        self.assertEqual(
            reader.counts(),
            {"roots": 1, "certificates": 1, "revocations": 1, "manifests": 1},
        )
        root = reader.roots()[0]
        certificate = reader.certificates()[0]
        revocation = reader.revocations()[0]
        manifest = reader.manifests()[0]
        after = sorted(
            (str(path.relative_to(self.runtime.state_dir)), path.stat().st_mtime_ns)
            for path in (self.runtime.state_dir / "provenance").rglob("*")
        )
        self.assertEqual(before, after)
        self.assertEqual(root["company_id"], root_id)
        self.assertEqual(certificate["certificate_id"], cert_id)
        self.assertEqual(revocation["revocation_id"], revocation_id)
        self.assertEqual(manifest["manifest_id"], manifest_id)
        self.assertFalse(root["public_key_der_disclosed"])
        self.assertFalse(certificate["public_key_der_disclosed"])
        self.assertFalse(certificate["signature_bytes_disclosed"])
        self.assertFalse(revocation["signature_bytes_disclosed"])
        self.assertFalse(manifest["signature_bytes_disclosed"])
        self.assertFalse(manifest["cryptographic_trust_verified_by_cockpit"])
        self.assertFalse(manifest["artifact_currentness_verified_by_cockpit"])
        self.assertFalse(manifest["artifact_bytes_read"])
        self.assertEqual(manifest["skill_ref_count"], 1)
        self.assertEqual(manifest["tool_ref_count"], 1)
        self.assertNotIn("SECRET_SKILL_REF", repr(manifest))
        self.assertNotIn("SECRET_TOOL_REF", repr(manifest))

    def test_noncanonical_or_aliased_public_store_fails_closed(self) -> None:
        _, _, _, manifest_id = self._public_fixture()
        manifest_path = (
            self.runtime.state_dir
            / "provenance"
            / "signed-manifests"
            / f"{manifest_id}.json"
        )
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ProvenanceReadError, "not canonical"):
            ProvenanceReadService(self.runtime).load_manifest(manifest_id)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("provenance-read-symlink-test")
            outside = root / "outside"
            outside.mkdir()
            (runtime.state_dir / "provenance").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ProvenanceReadError):
                ProvenanceReadService(runtime).counts()

    def test_reader_source_has_no_creation_secret_or_artifact_currentness_surface(self) -> None:
        source = inspect.getsource(read_module)
        for forbidden in (
            "mkdir(",
            ".ensure(",
            "private_key",
            "secret_key",
            "sign_artifact(",
            "verify_manifest(",
            "artifact_location).read",
            "artifact_path",
            "OpenSslEd25519Backend",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
