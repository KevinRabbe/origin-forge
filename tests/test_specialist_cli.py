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
from origin_forge.state import FlowStatus, RunStatus, TaskStatus


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
        payload = {"id": task_id, "status": "SUCCEEDED", "objective": "Review me"}
        ref = SpecialistEvidenceRef(
            task_id,
            canonical_hash(payload),
            SpecialistEvidenceKind.TASK,
        )
        contract = SpecialistContract.create(
            role=SpecialistRole.REVIEWER,
            parent_task_id=task_id,
            objective="Review exact evidence",
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
                "eval-case-list",
                "eval-case-show",
                "eval-report-list",
                "eval-report-show",
                "eval-report-status",
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

    def test_trusted_objects_are_listed_and_shown_without_mutation(self) -> None:
        contract, package, report, audit = self._trusted_review()
        code, payload = self._call("contract-list")
        self.assertEqual(code, 0)
        self.assertEqual(payload["contracts"], [contract.contract_id])
        code, payload = self._call("contract-show", contract.contract_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], contract.content_hash)

        code, payload = self._call("evidence-show", contract.contract_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], package.content_hash)

        code, payload = self._call("report-show", report.report_id)
        self.assertEqual(code, 0)
        self.assertEqual(payload["content_hash"], report.content_hash)

        code, payload = self._call("audit-show", self.store.audit_id(audit))
        self.assertEqual(code, 0)
        self.assertEqual(payload["report_hash"], report.content_hash)
        self.assertFalse(payload["semantic_findings_verified"])

    def test_invalid_id_returns_structured_failure_without_path_probe(self) -> None:
        code, payload = self._call("report-show", "../../outside")
        self.assertEqual(code, 2)
        self.assertIn("invalid Reviewer report ID", payload["detail"])

    def test_status_is_read_only_and_reports_reviewer_runs_only(self) -> None:
        goal = self.runtime.create_goal("Review status")
        flow = self.runtime.create_flow(goal)
        self.runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
        task = self.runtime.create_task(flow, "Review task")
        revision = self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
        reviewer_run = self.runtime.start_run(task, role="REVIEWER", model_profile="reviewer-profile")

        other_task = self.runtime.create_task(flow, "Executor task")
        revision = self.runtime.transition_task(other_task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(other_task, TaskStatus.RUNNING, expected_revision=revision)
        executor_run = self.runtime.start_run(other_task, role="EXECUTOR")
        self.runtime.finish_run(executor_run, RunStatus.FAILED, failure_reason="irrelevant")
        current = self.runtime.get_task(other_task)
        self.runtime.transition_task(
            other_task,
            TaskStatus.FAILED,
            expected_revision=int(current["revision"]),
        )

        code, payload = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["reviewer_runs"]), 1)
        self.assertEqual(payload["reviewer_runs"][0]["run_id"], reviewer_run)
        self.assertFalse(payload["model_execution_enabled"])
        self.assertFalse(payload["production_mutation_enabled"])
        self.assertFalse(payload["automatic_blocking_gate_enabled"])
        self.assertEqual(
            self.runtime.get_run(reviewer_run)["status"],
            RunStatus.RUNNING.value,
        )


if __name__ == "__main__":
    unittest.main()
