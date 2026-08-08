from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer_audit import ReviewerReportAuditor
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_models import (
    ReviewerCategory,
    ReviewerFinding,
    ReviewerReport,
    ReviewerSeverity,
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistRole,
)
from origin_forge.specialist_store import SpecialistStore, SpecialistStoreError


class SpecialistStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("specialist-store-test")
        self.store = SpecialistStore(self.runtime)

        self.task_id = new_id(IdKind.TASK)
        payload = {"id": self.task_id, "status": "SUCCEEDED", "objective": "Review"}
        self.ref = SpecialistEvidenceRef(
            self.task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        self.record = SpecialistEvidenceRecord(self.ref, payload)
        self.contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Review exact evidence",
            evidence_refs=(self.ref,),
        )
        self.package = SpecialistEvidencePackage(self.contract, (self.record,))
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.MEDIUM,
            category=ReviewerCategory.TEST_GAP,
            summary="A test scenario may be missing.",
            evidence_refs=(self.ref,),
            recommendation="Create a separate governed test Task if confirmed.",
        )
        self.report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        self.audit = ReviewerReportAuditor().audit(self.report, self.package)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_contract_report_and_audit_round_trip_immutably(self) -> None:
        contract_path = self.store.put_contract(self.contract)
        report_path, audit_path = self.store.put_review(self.report, self.audit)
        self.assertTrue(contract_path.is_file())
        self.assertTrue(report_path.is_file())
        self.assertTrue(audit_path.is_file())
        self.assertEqual(self.store.load_contract(self.contract.contract_id), self.contract)
        self.assertEqual(self.store.load_report(self.report.report_id), self.report)
        audit_id = self.store.audit_id(self.audit)
        self.assertEqual(self.store.load_audit(audit_id), self.audit)
        self.assertEqual(self.store.list_contract_ids(), (self.contract.contract_id,))
        self.assertEqual(self.store.list_report_ids(), (self.report.report_id,))
        self.assertEqual(self.store.list_audit_ids(), (audit_id,))

        # Identical writes are idempotent.
        self.store.put_contract(self.contract)
        self.store.put_review(self.report, self.audit)
        self.assertEqual(self.store.list_report_ids(), (self.report.report_id,))

    def test_report_cannot_enter_registry_without_stored_exact_contract(self) -> None:
        with self.assertRaises(KeyError):
            self.store.put_review(self.report, self.audit)
        self.assertEqual(self.store.list_report_ids(), ())
        self.assertEqual(self.store.list_audit_ids(), ())

        other = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Different contract",
            evidence_refs=(self.ref,),
        )
        self.store.put_contract(other)
        with self.assertRaises(KeyError):
            self.store.put_review(self.report, self.audit)
        self.assertEqual(self.store.list_report_ids(), ())

    def test_rejected_audit_cannot_enter_trusted_report_registry(self) -> None:
        self.store.put_contract(self.contract)
        outside_task = new_id(IdKind.TASK)
        outside = SpecialistEvidenceRef(
            outside_task,
            "sha256:" + "a" * 64,
            SpecialistEvidenceKind.TASK,
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.HIGH,
            category=ReviewerCategory.EVIDENCE_CONFLICT,
            summary="Outside evidence.",
            evidence_refs=(outside,),
            recommendation="Reject.",
        )
        report = ReviewerReport.create(
            contract=self.contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        rejected = ReviewerReportAuditor().audit(report, self.package)
        with self.assertRaisesRegex(SpecialistStoreError, "rejected Reviewer report"):
            self.store.put_review(report, rejected)
        self.assertEqual(self.store.list_report_ids(), ())
        self.assertEqual(self.store.list_audit_ids(), ())

    def test_audit_must_bind_exact_report_and_contract(self) -> None:
        self.store.put_contract(self.contract)
        other_report = ReviewerReport.create(
            contract=self.contract,
            model_id="different-model",
            model_hash=None,
            findings=(),
        )
        with self.assertRaisesRegex(SpecialistStoreError, "exact report"):
            self.store.put_review(other_report, self.audit)
        self.assertEqual(self.store.list_report_ids(), ())

    def test_tampered_contract_and_report_are_detected_on_load(self) -> None:
        contract_path = self.store.put_contract(self.contract)
        self.store.put_review(self.report, self.audit)
        report_path = self.store.reports_dir / f"{self.report.report_id}.json"

        raw = json.loads(contract_path.read_text(encoding="utf-8"))
        raw["payload"]["objective"] = "tampered"
        contract_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(SpecialistStoreError, "content hash mismatch"):
            self.store.load_contract(self.contract.contract_id)

        raw = json.loads(report_path.read_text(encoding="utf-8"))
        raw["payload"]["overall_risk"] = "CRITICAL"
        report_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(SpecialistStoreError, "overall risk mismatch"):
            self.store.load_report(self.report.report_id)

    def test_symlink_registry_path_fails_closed(self) -> None:
        external = self.root / "external"
        external.mkdir()
        specialists = self.runtime.state_dir / "specialists"
        specialists.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(SpecialistStoreError, "may not be a symlink"):
            self.store.list_contract_ids()

    def test_catalog_and_byte_limits_fail_closed(self) -> None:
        limited = SpecialistStore(self.runtime, max_contracts=1, max_contract_bytes=32)
        with self.assertRaisesRegex(SpecialistStoreError, "exceeds byte limit"):
            limited.put_contract(self.contract)

        limited = SpecialistStore(self.runtime, max_contracts=1)
        limited.put_contract(self.contract)
        second = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=self.task_id,
            objective="Second review",
            evidence_refs=(self.ref,),
        )
        with self.assertRaisesRegex(SpecialistStoreError, "catalog exceeds limit"):
            limited.put_contract(second)

    def test_atomic_publish_never_replaces_competing_target(self) -> None:
        target_dir = self.root / "atomic"
        target_dir.mkdir()
        target = target_dir / "object.json"
        barrier = threading.Barrier(2)
        results: list[tuple[bool, bytes]] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def publish(data: bytes) -> None:
            try:
                barrier.wait(timeout=5)
                created = SpecialistStore._atomic_publish(target, data)
                with lock:
                    results.append((created, data))
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        first = threading.Thread(target=publish, args=(b"first\n",))
        second = threading.Thread(target=publish, args=(b"second\n",))
        first.start()
        second.start()
        first.join(timeout=10)
        second.join(timeout=10)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        winners = [data for created, data in results if created]
        losers = [data for created, data in results if not created]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(target.read_bytes(), winners[0])
        self.assertNotEqual(winners[0], losers[0])

    def test_store_has_no_source_task_skill_policy_or_merge_mutation_surface(self) -> None:
        for forbidden in (
            "write_source",
            "apply",
            "patch",
            "transition_task",
            "promote_skill",
            "change_policy",
            "merge",
        ):
            self.assertFalse(hasattr(self.store, forbidden))


if __name__ == "__main__":
    unittest.main()
