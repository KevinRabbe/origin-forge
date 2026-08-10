from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.dream_models import EvidenceClass, EvidenceRef
from origin_forge.harness_workshop_cli import build_parser, main
from origin_forge.harness_workshop_models import (
    HarnessComponentKind,
    HarnessImprovementCandidate,
)
from origin_forge.harness_workshop_store import HarnessWorkshopStore
from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class HarnessWorkshopCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("workshop-cli-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, *args: str) -> tuple[int, object]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--project-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    @staticmethod
    def _candidate() -> HarnessImprovementCandidate:
        return HarnessImprovementCandidate.create(
            component_kind=HarnessComponentKind.SKILL,
            target_component_id="skill.cli-fixture",
            target_version="1",
            target_hash=HASH_A,
            baseline_payload_hash=HASH_B,
            candidate_payload={"instructions": ["one bounded change"]},
            hypothesis="This immutable candidate exists only for read-only CLI inspection.",
            source_evidence=(
                EvidenceRef(
                    ref_id=new_id(IdKind.RUN),
                    content_hash=HASH_C,
                    evidence_class=EvidenceClass.TRAJECTORY,
                ),
            ),
        )

    def test_command_surface_is_strictly_read_only(self) -> None:
        parser = build_parser()
        subparsers = next(action for action in parser._actions if action.dest == "command")
        commands = set(subparsers.choices)
        self.assertEqual(
            commands,
            {
                "status",
                "candidates",
                "plans",
                "reports",
                "audits",
                "decisions",
                "candidate-show",
                "plan-show",
                "report-show",
                "audit-show",
                "decision-show",
            },
        )
        for forbidden in (
            "refine",
            "apply",
            "promote",
            "activate",
            "install",
            "rewrite",
            "evaluate",
            "execute",
            "task-complete",
            "task-verify",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, commands)

    def test_status_is_non_mutating_and_reports_no_authority(self) -> None:
        before = self.runtime.status()
        code, value = self._call("status")
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "OK")
        self.assertEqual(
            value["counts"],
            {
                "audits": 0,
                "candidates": 0,
                "decisions": 0,
                "plans": 0,
                "reports": 0,
            },
        )
        self.assertEqual(
            value["trusted_evaluator_protocols"]["SKILL_BENCHMARK"],
            ["paired-skill-ab-v1"],
        )
        for family in (
            "PROMPT_BENCHMARK",
            "CONTEXT_BENCHMARK",
            "ROUTING_BENCHMARK",
            "SPECIALIST_BENCHMARK",
            "MINI_WORKFLOW_BENCHMARK",
        ):
            self.assertEqual(value["trusted_evaluator_protocols"][family], [])
        for key, enabled in value.items():
            if key.endswith("_enabled"):
                self.assertFalse(enabled, key)
        self.assertEqual(self.runtime.status(), before)

    def test_list_and_show_reuse_immutable_store_without_mutation(self) -> None:
        candidate = self._candidate()
        store = HarnessWorkshopStore(self.runtime)
        store.publish_candidate(candidate)
        before = self.runtime.status()

        code, listing = self._call("candidates")
        self.assertEqual(code, 0)
        self.assertEqual(listing["objects"][0]["object_id"], candidate.candidate_id)
        self.assertEqual(listing["objects"][0]["content_hash"], candidate.content_hash)

        code, shown = self._call("candidate-show", candidate.candidate_id)
        self.assertEqual(code, 0)
        self.assertEqual(shown["object_id"], candidate.candidate_id)
        self.assertEqual(shown["content_hash"], candidate.content_hash)
        self.assertFalse(shown["payload"]["production_activation_authorized"])
        self.assertEqual(self.runtime.status(), before)

    def test_invalid_or_wrong_category_ids_return_structured_error(self) -> None:
        code, value = self._call("candidate-show", "not-a-candidate")
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")

        code, value = self._call("candidate-show", new_id(IdKind.WORKSHOP_EVALUATION_PLAN))
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
