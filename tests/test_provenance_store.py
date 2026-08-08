from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.provenance_crypto import (
    OpenSslEd25519Backend,
    OperationalManifestSigner,
    RootAuthority,
)
from origin_forge.provenance_models import (
    CompanyRootIdentity,
    OperationalKeyCertificate,
    OperationalKeyPurpose,
    OperationalKeyRevocation,
    ProvenanceManifest,
    ProvenanceRecordRef,
    ProvenanceRecordType,
)
from origin_forge.provenance_store import ProvenanceStore, ProvenanceStoreError
from origin_forge.provenance_verifier import (
    ProvenanceTrustFinding,
    ProvenanceTrustVerifier,
)
from origin_forge.runtime import OriginForgeRuntime


NOW = "2026-08-08T20:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def ref(record_type: ProvenanceRecordType, kind: IdKind, digest=HASH_A, revision=None):
    return ProvenanceRecordRef(record_type, new_id(kind), digest, revision)


def manifest(root: CompanyRootIdentity) -> ProvenanceManifest:
    return ProvenanceManifest(
        manifest_id=new_id(IdKind.PROVENANCE_MANIFEST),
        schema_version=1,
        company_id=root.company_id,
        root_identity_hash=root.content_hash,
        project_ref=ref(ProvenanceRecordType.PROJECT, IdKind.PROJECT),
        artifact_ref=ref(ProvenanceRecordType.ARTIFACT, IdKind.ARTIFACT, HASH_B),
        artifact_content_hash=HASH_A,
        artifact_type="TEST",
        artifact_location="out.bin",
        task_ref=ref(ProvenanceRecordType.TASK, IdKind.TASK, revision=1),
        created_at=NOW,
    )


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for provenance store tests")
class ProvenanceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_temp = tempfile.TemporaryDirectory()
        self.secret_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.project_temp.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("provenance-store-test")
        self.store = ProvenanceStore(self.runtime)
        self.secret_root = Path(self.secret_temp.name)
        self.openssl = shutil.which("openssl")
        assert self.openssl is not None
        self.root_key = self._key("root.pem")
        self.operational_key = self._key("operational.pem")
        self.backend = OpenSslEd25519Backend(self.root)
        self.identity = CompanyRootIdentity.create(
            "Origin Forge",
            self.backend.public_key_der(self.root_key),
            created_at=NOW,
        )
        certificate = OperationalKeyCertificate.create(
            self.identity,
            purpose=OperationalKeyPurpose.ARTIFACT_SIGNING,
            public_key_der=self.backend.public_key_der(self.operational_key),
            issued_at=NOW,
        )
        self.signed_certificate = RootAuthority(
            self.identity, self.backend, self.root_key
        ).sign_certificate(certificate)
        self.signed_manifest = OperationalManifestSigner(
            self.signed_certificate,
            self.backend,
            self.operational_key,
        ).sign(manifest(self.identity))

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

    def tearDown(self) -> None:
        self.project_temp.cleanup()
        self.secret_temp.cleanup()

    def test_public_trust_objects_round_trip_and_verify_offline(self) -> None:
        self.store.put_root(self.identity)
        self.store.put_certificate(self.signed_certificate)
        self.store.put_manifest(self.signed_manifest)

        self.assertEqual(self.store.load_root(self.identity.company_id), self.identity)
        self.assertEqual(
            self.store.load_certificate(self.signed_certificate.certificate.certificate_id),
            self.signed_certificate,
        )
        self.assertEqual(
            self.store.load_manifest(self.signed_manifest.manifest.manifest_id),
            self.signed_manifest,
        )

        result = ProvenanceTrustVerifier(self.identity, self.backend).verify(
            self.signed_manifest,
            self.signed_certificate,
        )
        self.assertTrue(result.trusted)
        self.assertTrue(result.root_trusted)
        self.assertTrue(result.certificate_valid)
        self.assertTrue(result.manifest_signature_valid)
        self.assertFalse(result.key_revoked)
        self.assertEqual(result.findings, ())
        self.assertFalse(result.to_dict()["canonical_project_state_changed"])

    def test_root_signed_revocation_removes_trust_conservatively(self) -> None:
        revocation = OperationalKeyRevocation.create(
            self.identity,
            self.signed_certificate.certificate,
            reason="Operational key compromised",
            effective_at="2026-08-08T20:05:00Z",
        )
        signed_revocation = RootAuthority(
            self.identity, self.backend, self.root_key
        ).sign_revocation(revocation)
        self.store.put_revocation(signed_revocation)
        loaded = self.store.load_revocation(revocation.revocation_id)
        result = ProvenanceTrustVerifier(self.identity, self.backend).verify(
            self.signed_manifest,
            self.signed_certificate,
            revocations=(loaded,),
        )
        self.assertFalse(result.trusted)
        self.assertTrue(result.key_revoked)
        self.assertIn(ProvenanceTrustFinding.KEY_REVOKED, result.findings)

    def test_tamper_unknown_fields_and_immutable_ids_fail_closed(self) -> None:
        self.store.put_manifest(self.signed_manifest)
        path = (
            self.store.signed_manifests_dir
            / f"{self.signed_manifest.manifest.manifest_id}.json"
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["payload"]["manifest"]["artifact_type"] = "TAMPERED"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceStoreError, "validation failed"):
            self.store.load_manifest(self.signed_manifest.manifest.manifest_id)

        # Restore exact bytes through a fresh store fixture is simpler than making
        # the mutable test file authoritative again.
        other = ProvenanceStore(self.runtime)
        with self.assertRaises(ProvenanceStoreError):
            other.put_manifest(self.signed_manifest)

        self.store.put_root(self.identity)
        different = CompanyRootIdentity.create(
            "Different Root",
            b"different-public-der",
            created_at=NOW,
        )
        with self.assertRaisesRegex(ProvenanceStoreError, "different Company Root"):
            self.store.put_root(different)

    def test_store_root_and_object_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as other_temp:
            target = Path(other_temp)
            provenance = self.runtime.state_dir / "provenance"
            if provenance.exists():
                shutil.rmtree(provenance)
            try:
                provenance.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(ProvenanceStoreError, "symlink"):
                ProvenanceStore(self.runtime).ensure()

    def test_atomic_publish_never_replaces_competing_bytes(self) -> None:
        self.store.ensure()
        target = self.store.root / "race.json"
        first = b"first\n"
        second = b"second\n"

        def publish(data: bytes):
            return self.store._atomic_publish(target, data)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, (first, second)))
        self.assertEqual(sum(bool(value) for value in results), 1)
        self.assertIn(target.read_bytes(), {first, second})

    def test_store_exposes_no_secret_source_task_or_merge_surface(self) -> None:
        for forbidden in (
            "private_key",
            "put_private_key",
            "generate_key",
            "model",
            "generate",
            "apply",
            "patch",
            "verify_task",
            "transition_task",
            "merge",
            "release",
        ):
            self.assertFalse(hasattr(self.store, forbidden))


if __name__ == "__main__":
    unittest.main()
