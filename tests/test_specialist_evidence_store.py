from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_evidence_store import (
    SpecialistEvidenceStore,
    SpecialistEvidenceStoreError,
)
from origin_forge.specialist_models import (
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)
from origin_forge.specialist_store import SpecialistStore


class SpecialistEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("specialist-evidence-store-test")
        self.store = SpecialistStore(self.runtime)
        self.evidence_store = SpecialistEvidenceStore(self.store)
        self.task_id = new_id(IdKind.TASK)
        payload = {"id": self.task_id, "status": "SUCCEEDED", "objective": "Frozen"}
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.record = SpecialistEvidenceRecord(self.ref, payload)
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review frozen evidence",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(self.contract, (self.record,))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_package_round_trip_preserves_payload_bytes_semantics(self) -> None:
        self.store.put_contract(self.contract)
        path = self.evidence_store.put(self.package)
        self.assertTrue(path.is_file())
        loaded = self.evidence_store.load(self.contract.contract_id)
        self.assertEqual(loaded, self.package)
        self.assertEqual(loaded.records[0].payload, self.record.payload)
        self.assertEqual(loaded.content_hash, self.package.content_hash)
        self.assertEqual(self.evidence_store.list_contract_ids(), (self.contract.contract_id,))
        self.evidence_store.put(self.package)
        self.assertEqual(self.evidence_store.list_contract_ids(), (self.contract.contract_id,))

    def test_package_requires_trusted_stored_contract_first(self) -> None:
        with self.assertRaises(KeyError):
            self.evidence_store.put(self.package)
        self.assertEqual(self.evidence_store.list_contract_ids(), ())

    def test_same_contract_id_cannot_be_reused_for_different_frozen_payload(self) -> None:
        self.store.put_contract(self.contract)
        self.evidence_store.put(self.package)
        path = self.evidence_store.directory / f"{self.contract.contract_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["payload"]["records"][0]["payload"]["objective"] = "changed"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(SpecialistEvidenceStoreError):
            self.evidence_store.load(self.contract.contract_id)

    def test_embedded_contract_tampering_is_detected(self) -> None:
        self.store.put_contract(self.contract)
        self.evidence_store.put(self.package)
        path = self.evidence_store.directory / f"{self.contract.contract_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["payload"]["contract"]["objective"] = "tampered"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(
            SpecialistEvidenceStoreError,
            "embedded contract does not match trusted contract",
        ):
            self.evidence_store.load(self.contract.contract_id)

    def test_symlink_evidence_directory_fails_closed(self) -> None:
        self.store.ensure()
        external = self.root / "external-evidence"
        external.mkdir()
        self.evidence_store.directory.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(Exception, "symlink"):
            self.evidence_store.list_contract_ids()

    def test_store_byte_and_count_limits_fail_closed(self) -> None:
        self.store.put_contract(self.contract)
        small = SpecialistEvidenceStore(self.store, max_package_bytes=32)
        with self.assertRaisesRegex(SpecialistEvidenceStoreError, "exceeds store byte limit"):
            small.put(self.package)

        limited = SpecialistEvidenceStore(self.store, max_packages=1)
        limited.put(self.package)
        other_task = new_id(IdKind.TASK)
        other_payload = {"id": other_task, "status": "SUCCEEDED"}
        other_ref = SpecialistEvidenceRef(
            other_task,
            canonical_hash(other_payload),
            SpecialistEvidenceKind.TASK,
        )
        other_contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=other_task,
            objective="Other",
            evidence_refs=(other_ref,),
        )
        self.store.put_contract(other_contract)
        other_package = SpecialistEvidencePackage(
            other_contract,
            (SpecialistEvidenceRecord(other_ref, other_payload),),
        )
        with self.assertRaisesRegex(SpecialistEvidenceStoreError, "catalog exceeds limit"):
            limited.put(other_package)

    def test_evidence_store_has_no_project_mutation_or_model_surface(self) -> None:
        for forbidden in (
            "generate",
            "review",
            "apply",
            "patch",
            "transition_task",
            "verify_task",
            "change_policy",
            "merge",
        ):
            self.assertFalse(hasattr(self.evidence_store, forbidden))


if __name__ == "__main__":
    unittest.main()
