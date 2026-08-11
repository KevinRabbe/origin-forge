from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.dream_models import (
    DreamCandidate,
    DreamCandidateType,
    EvidenceClass,
    EvidenceRef,
)
from origin_forge.dream_store import DreamStore
from origin_forge.ids import IdKind, new_id
from origin_forge.production_interface_html import render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.provenance_models import CompanyRootIdentity
from origin_forge.provenance_store import ProvenanceStore
from origin_forge.runtime import OriginForgeRuntime


_HASH = "sha256:" + ("1" * 64)


class ProductionInterfaceProvenanceDreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-provenance-dream-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_empty_snapshot_does_not_create_provenance_or_dream_registries(self) -> None:
        provenance = self.runtime.state_dir / "provenance"
        dream = self.runtime.state_dir / "dream"
        self.assertFalse(provenance.exists())
        self.assertFalse(dream.exists())

        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_overview(snapshot)

        self.assertFalse(provenance.exists())
        self.assertFalse(dream.exists())
        self.assertEqual(snapshot.provenance["counts"]["manifests"], 0)
        self.assertEqual(snapshot.dream_memory["counts"]["candidates"], 0)
        self.assertIn("Provenance Inspector", page)
        self.assertIn("Dream / Memory Inspector", page)
        authority = snapshot.to_dict()["authority"]
        self.assertFalse(authority["provenance_trust_verification"])
        self.assertFalse(authority["dream_execution"])
        self.assertFalse(authority["automatic_memory_promotion"])

    def test_canonical_public_objects_are_projected_redacted_and_escaped(self) -> None:
        root = CompanyRootIdentity.create(
            "<script>Root</script>",
            b"public-key-material",
            created_at="2026-08-11T00:00:00Z",
        )
        ProvenanceStore(self.runtime).put_root(root)

        evidence = EvidenceRef(
            ref_id=new_id(IdKind.RUN),
            content_hash=_HASH,
            evidence_class=EvidenceClass.TRAJECTORY,
            revision=1,
        )
        candidate = DreamCandidate.create(
            candidate_type=DreamCandidateType.PROCESS,
            summary="<img src=x onerror=boom> investigate repeated repair loops",
            proposed_action="Benchmark a governed process change.",
            evidence_refs=(evidence,),
        )
        DreamStore(self.runtime).put_candidate(candidate)

        snapshot = build_production_interface_snapshot(self.runtime)
        payload = json.dumps(snapshot.to_dict(), sort_keys=True)
        page = render_overview(snapshot)

        self.assertEqual(snapshot.provenance["counts"]["roots"], 1)
        self.assertEqual(snapshot.dream_memory["counts"]["candidates"], 1)
        self.assertNotIn(root.public_key_der_b64, payload)
        self.assertNotIn(evidence.ref_id, payload)
        self.assertIn('"public_key_der_disclosed": false', payload)
        self.assertIn('"evidence_refs_disclosed": false', payload)
        self.assertNotIn("<script>Root</script>", page)
        self.assertIn("&lt;script&gt;Root&lt;/script&gt;", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x onerror=boom&gt;", page)
        self.assertIn(candidate.candidate_id, page)


if __name__ == "__main__":
    unittest.main()
