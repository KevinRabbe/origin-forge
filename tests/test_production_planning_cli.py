from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import origin_forge.production_planning_cli as planning_cli_module
from origin_forge.production_planning_cli import build_parser, main
from origin_forge.production_planning_evidence import (
    ProductionPlanningEvidenceStore,
    freeze_planning_input,
)
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.runtime import OriginForgeRuntime


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class ProductionPlanningCliTests(unittest.TestCase):
    def test_parser_exposes_only_read_only_inspection_commands(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.prog, "origin-forge-plan")
        self.assertEqual(parser.parse_args(["status"]).command, "status")
        self.assertEqual(
            parser.parse_args(["input-show", "PLINPUT-example"]).command,
            "input-show",
        )
        self.assertEqual(
            parser.parse_args(["proposal-show", "PLPROP-example"]).command,
            "proposal-show",
        )
        self.assertEqual(
            parser.parse_args(["audit-show", "PLAUD-example"]).command,
            "audit-show",
        )
        self.assertEqual(
            parser.parse_args(["materialization-show", "PLMAT-example"]).command,
            "materialization-show",
        )
        self.assertEqual(parser.parse_args(["graph", "FLOW-example"]).command, "graph")
        self.assertEqual(
            parser.parse_args(["readiness", "TASK-example"]).command,
            "readiness",
        )
        for forbidden in ("materialize", "run", "approve", "verify", "generate"):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parser.parse_args([forbidden])

    def test_help_and_uninitialized_status_create_no_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit_info:
                main(["--project-root", str(root), "--help"])
            self.assertEqual(exit_info.exception.code, 0)
            self.assertFalse(state.exists())

            output = StringIO()
            with redirect_stdout(output):
                result = main(["--project-root", str(root), "status"])
            self.assertEqual(result, 2)
            self.assertFalse(state.exists())
            payload = json.loads(output.getvalue())
            self.assertIn("error", payload)

    def test_initialized_commands_return_revalidated_read_only_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("planning-cli-test")
            goal = runtime.create_goal("Inspect planning through CLI")
            evidence = ProductionPlanningEvidenceStore(runtime)
            planning_input = freeze_planning_input(
                runtime,
                goal,
                project_intelligence_hash=_sha("project-intelligence"),
                capability_catalog_hash=_sha("catalog"),
                capability_ids=("code", "runtime-observation"),
                model_policy_hash=_sha("model-policy"),
                resource_policy_hash=_sha("resource-policy"),
            )
            proposal = PlanProposal.create(
                planning_input=planning_input,
                summary="Implement then observe.",
                steps=(
                    PlanStep(
                        step_key="code",
                        objective="Implement code.",
                        acceptance_criteria=("Tests pass.",),
                        required_capabilities=("code",),
                    ),
                    PlanStep(
                        step_key="runtime",
                        objective="Observe runtime.",
                        acceptance_criteria=("Evidence exists.",),
                        required_capabilities=("runtime-observation",),
                        depends_on=("code",),
                    ),
                ),
            )
            audit = audit_plan(planning_input, proposal)
            evidence.publish_input(planning_input)
            evidence.publish_proposal(proposal)
            evidence.publish_audit(audit)
            materialization = evidence.materialize(
                planning_input_id=planning_input.planning_input_id,
                proposal_id=proposal.proposal_id,
                audit_id=audit.audit_id,
            )
            bindings = {
                value.step_key: value.task_id
                for value in materialization.task_bindings
            }

            commands = (
                (["status"], lambda p: self.assertEqual(p["materialization_count"], 1)),
                (
                    ["input-show", planning_input.planning_input_id],
                    lambda p: self.assertEqual(p["content_hash"], planning_input.content_hash),
                ),
                (
                    ["proposal-show", proposal.proposal_id],
                    lambda p: self.assertEqual(p["content_hash"], proposal.content_hash),
                ),
                (
                    ["audit-show", audit.audit_id],
                    lambda p: self.assertEqual(p["content_hash"], audit.content_hash),
                ),
                (
                    ["materialization-show", materialization.materialization_id],
                    lambda p: self.assertEqual(p["flow_id"], materialization.flow_id),
                ),
                (
                    ["graph", materialization.flow_id],
                    lambda p: self.assertEqual(len(p["edges"]), 1),
                ),
                (
                    ["readiness", bindings["runtime"]],
                    lambda p: self.assertEqual(p["status"], "WAITING_ON_DEPENDENCIES"),
                ),
            )
            for command, assertion in commands:
                output = StringIO()
                with redirect_stdout(output):
                    result = main(["--project-root", str(root), *command])
                self.assertEqual(result, 0, command)
                assertion(json.loads(output.getvalue()))

    def test_cli_source_contains_no_mutating_or_model_commands(self) -> None:
        source = inspect.getsource(planning_cli_module)
        for forbidden in (
            "materialize(",
            "generate(",
            "create_goal(",
            "create_flow(",
            "create_task(",
            "transition_task(",
            "record_verification(",
            "merge_pull_request(",
            "release(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
