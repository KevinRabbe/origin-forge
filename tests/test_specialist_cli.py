from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.reviewer_audit import ReviewerReportAuditor
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.specialist_cli import build_parser, main
from origin_forge.specialist_evidence import (
    SpecialistEvidencePackage,
    SpecialistEvidenceRecord,
    canonical_hash,
)
from origin_forge.specialist_evidence_store import SpecialistEvidenceStore
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
from origin_forge.specialist_store import SpecialistStore
from origin_forge.state import FlowStatus, TaskStatus


class SpecialistCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("specialist-cli-test")
        self.store = SpecialistStore(self.runtime)
        self.evidence_store = SpecialistEvidenceStore(self.store)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str):
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def _trusted_review(self):
        task_id = new_id(IdKind.TASK)
        payload = {"id": task_id, "status": "SUCCEEDED", "objective": "Review"}
        ref = SpecialistEvidenceRef(
            task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=task_id,
            objective="Review frozen evidence",
            evidence_refs=(ref,),
        )
        package = SpecialistEvidencePackage(
            contract,
            (SpecialistEvidenceRecord(ref, payload),),
        )
        finding = ReviewerFinding.create(
            severity=ReviewerSeverity.LOW,
            category=ReviewerCategory.MAINTAINABILITY,
            summary="Minor advisory concern.",
            evidence_refs=(ref,),
            recommendation="Consider a separate cleanup Task later.",
        )
        report = ReviewerReport.create(
            contract=contract,
            model_id="reviewer-model",
            model_hash=None,
            findings=(finding,),
        )
        audit = ReviewerReportAuditor().audit(report, package)
        self.store.put_contract(contract)
        self.evidence_store.put(package)
        self.store.put_review(report, audit)
        return contract, package, report, audit

    def test_cli_surface_is_read_only(self) -> None:
        parser = build_parser()
        subparsers = [
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertEqual(len(subparsers), 1)
        commands = set(subparsers[0].choices)
        self.assertEqual(
            commands,
            {
                "status",
                "contract-list",
                "contract-show",
                "evidence-list",
                "evidence-show",
                "report-list",
                "report-show",
                "audit-list",
                "audit-show",
            },
        )
        for forbidden in (
            "run",
            "review",
            "apply",
            "patch",
            "approve",
            "promote",
            "verify",
            "merge",
            "delegate",
            "spawn",
            "policy-update",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_is_read_only_and_reports_reviewer_runs_only(self) -> None:
        # Ordinary non-review task/run should not appear.
        goal = self.runtime.create_goal("Ordinary")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Ordinary task")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        self.runtime.start_run(task, role="EXECUTOR")

        review_goal = self.runtime.create_goal("Review")
        review_flow = self.runtime.create_flow(review_goal)
        self.runtime.transition_flow(review_flow, FlowStatus.RUNNING, expected_revision=0)
        review_task = self.runtime.create_task(review_flow, "Review task")
        revision = self.runtime.transition_task(
            review_task, TaskStatus.READY, expected_revision=0
        )
        self.runtime.transition_task(
            review_task, TaskStatus.RUNNING, expected_revision=revision
        )
        review_run = self.runtime.start_run(
            review_task,
            role="REVIEWER",
            model_profile="reviewer-strong",
        )
        before = len(self.runtime.list_runs())

        code, payload = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(payload["contracts"], 0)
        self.assertEqual(payload["evidence_packages"], 0)
        self.assertEqual(payload["reports"], 0)
        self.assertEqual(payload["audits"], 0)
        self.assertEqual(len(payload["reviewer_runs"]), 1)
        self.assertEqual(payload["reviewer_runs"][0]["run_id"], review_run)
        self.assertEqual(payload["reviewer_runs"][0]["model_profile"], "reviewer-strong")
        self.assertFalse(payload["model_execution_enabled"])
        self.assertFalse(payload["production_mutation_enabled"])
        self.assertFalse(payload["automatic_blocking_gate_enabled"])
        self.assertEqual(len(self.runtime.list_runs()), before)

    def test_trusted_objects_are_listed_and_shown_without_mutation(self) -> None:
        contract, package, report, audit = self._trusted_review()
        audit_id = self.store.audit_id(audit)

        code, payload = self._call("contract-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["contracts"], [contract.contract_id])
        code, payload = self._call("contract-show", contract.contract_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], contract.content_hash)

        code, payload = self._call("evidence-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["evidence_packages"], [contract.contract_id])
        code, payload = self._call("evidence-show", contract.contract_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], package.content_hash)

        code, payload = self._call("report-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["reports"], [report.report_id])
        code, payload = self._call("report-show", report.report_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], report.content_hash)
        self.assertEqual(payload["overall_risk"], "LOW")

        code, payload = self._call("audit-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["audits"], [audit_id])
        code, payload = self._call("audit-show", audit_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], audit.content_hash)
        self.assertEqual(payload["status"], "STRUCTURALLY_VALID")
        self.assertFalse(payload["semantic_findings_verified"])

    def test_invalid_id_returns_structured_failure_without_path_probe(self) -> None:
        code, payload = self._call("report-show", "not-a-report")
        self.assertEqual(code, 2)
        self.assertIn("invalid Reviewer report ID", payload["detail"])

    def test_empty_catalogs_are_deterministic(self) -> None:
        for command, field in (
            ("contract-list", "contracts"),
            ("evidence-list", "evidence_packages"),
            ("report-list", "reports"),
            ("audit-list", "audits"),
        ):
            code, payload = self._call(command)
            self.assertEqual(code, 0)
            self.assertEqual(payload[field], [])


if __name__ == "__main__":
    unittest.main()
