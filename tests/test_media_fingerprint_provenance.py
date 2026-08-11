from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.media_fingerprint_models import MediaFingerprintModelError
from origin_forge.media_fingerprint_provenance import FingerprintProvenanceLink
from origin_forge.media_fingerprint_store import MediaFingerprintStore
from origin_forge.provenance_models import (
    ProvenanceManifest,
    ProvenanceRecordRef,
    ProvenanceRecordType,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.source_text_fingerprint import fingerprint_source_text


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _manifest(*, artifact_id: str, artifact_content_hash: str) -> ProvenanceManifest:
    return ProvenanceManifest(
        manifest_id=new_id(IdKind.PROVENANCE_MANIFEST),
        schema_version=1,
        company_id=new_id(IdKind.COMPANY_IDENTITY),
        root_identity_hash=HASH_A,
        project_ref=ProvenanceRecordRef(
            ProvenanceRecordType.PROJECT,
            new_id(IdKind.PROJECT),
            HASH_B,
        ),
        artifact_ref=ProvenanceRecordRef(
            ProvenanceRecordType.ARTIFACT,
            artifact_id,
            HASH_C,
        ),
        artifact_content_hash=artifact_content_hash,
        artifact_type="SOURCE_TEXT",
        artifact_location="artifacts/source.txt",
        created_at="2026-08-11T00:00:00Z",
    )


class MediaFingerprintProvenanceTests(unittest.TestCase):
    def test_exact_artifact_id_and_content_hash_bind_manifest_without_signature_claim(self) -> None:
        artifact_id = new_id(IdKind.ARTIFACT)
        fingerprint = fingerprint_source_text(
            source_ref=artifact_id,
            source=b"verified source\n",
        )
        manifest = _manifest(
            artifact_id=artifact_id,
            artifact_content_hash=fingerprint.source_hash,
        )
        link = FingerprintProvenanceLink.create(
            fingerprint=fingerprint,
            manifest=manifest,
        )
        link.bind(fingerprint, manifest)
        payload = link.to_dict()
        self.assertTrue(payload["phase18_manifest_bound"])
        self.assertFalse(payload["phase18_signature_verified"])
        self.assertFalse(payload["cryptographic_provenance_verified"])
        self.assertFalse(payload["authorship_proven"])
        self.assertFalse(payload["production_task_verified"])

    def test_artifact_id_or_content_hash_mismatch_fails_closed(self) -> None:
        artifact_id = new_id(IdKind.ARTIFACT)
        fingerprint = fingerprint_source_text(
            source_ref=artifact_id,
            source=b"source\n",
        )
        wrong_id = _manifest(
            artifact_id=new_id(IdKind.ARTIFACT),
            artifact_content_hash=fingerprint.source_hash,
        )
        with self.assertRaisesRegex(MediaFingerprintModelError, "artifact ID"):
            FingerprintProvenanceLink.create(
                fingerprint=fingerprint,
                manifest=wrong_id,
            )

        wrong_hash = _manifest(
            artifact_id=artifact_id,
            artifact_content_hash=HASH_A,
        )
        with self.assertRaisesRegex(MediaFingerprintModelError, "content hash"):
            FingerprintProvenanceLink.create(
                fingerprint=fingerprint,
                manifest=wrong_hash,
            )

    def test_forged_link_is_revalidated_against_source_binding(self) -> None:
        artifact_id = new_id(IdKind.ARTIFACT)
        original = fingerprint_source_text(
            source_ref=artifact_id,
            source=b"source\n",
        )
        manifest = _manifest(
            artifact_id=artifact_id,
            artifact_content_hash=original.source_hash,
        )
        link = FingerprintProvenanceLink.create(
            fingerprint=original,
            manifest=manifest,
        )
        foreign = fingerprint_source_text(
            source_ref=new_id(IdKind.ARTIFACT),
            source=b"source\n",
        )
        forged = replace(
            link,
            fingerprint_id=foreign.fingerprint_id,
            fingerprint_hash=foreign.content_hash,
        )
        with self.assertRaisesRegex(MediaFingerprintModelError, "artifact ID"):
            forged.bind(foreign, manifest)

    def test_link_is_immutable_persisted_evidence(self) -> None:
        artifact_id = new_id(IdKind.ARTIFACT)
        fingerprint = fingerprint_source_text(
            source_ref=artifact_id,
            source=b"source\n",
        )
        manifest = _manifest(
            artifact_id=artifact_id,
            artifact_content_hash=fingerprint.source_hash,
        )
        link = FingerprintProvenanceLink.create(
            fingerprint=fingerprint,
            manifest=manifest,
        )
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(Path(tempdir))
            runtime.initialize("phase28-provenance-link-test")
            store = MediaFingerprintStore(runtime)
            path = store.publish_provenance_link(
                link,
                fingerprint=fingerprint,
                manifest=manifest,
            )
            self.assertTrue(path.is_file())
            loaded = store.load("provenance-links", link.link_id)
            self.assertEqual(loaded["content_hash"], link.content_hash)
            self.assertFalse(loaded["payload"]["phase18_signature_verified"])


if __name__ == "__main__":
    unittest.main()
