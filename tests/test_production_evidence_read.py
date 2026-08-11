from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import origin_forge.production_evidence_read as read_module
from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_evidence_read import ProductionEvidenceReadService
from origin_forge.runtime import OriginForgeRuntime


class ProductionEvidenceReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-evidence-read-test")
        self.lineage = OriginForgeLineage(self.runtime)
        self.reader = ProductionEvidenceReadService(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _evidence(self) -> tuple[str, str, str]:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        decision = self.lineage.create_decision(
            title="Choose approach",
            decision="Use bounded read projection",
            context="SECRET_DECISION_CONTEXT",
            rationale="Avoid a second truth store",
            alternatives=("SECRET_ALTERNATIVE",),
            goal_id=goal,
            task_id=task,
        )
        change = self.lineage.create_change(
            task,
            summary="Add cockpit evidence reader",
            change_type="IMPLEMENTATION",
            decision_id=decision,
            before_ref="before",
            after_ref="after",
        )
        artifact_path = self.root / "artifact.txt"
        artifact_path.write_text("SECRET_ARTIFACT_BYTES", encoding="utf-8")
        artifact = self.lineage.create_artifact(
            artifact_type="SOURCE",
            path_or_uri="artifact.txt",
            change_id=change,
            skill_versions=("SECRET_SKILL_VERSION",),
            tool_versions=("SECRET_TOOL_VERSION",),
        )
        self.lineage.record_artifact_verification(
            artifact,
            verification_type="integrity",
            verifier="evidence-read-test",
            status="PASS",
            evidence={"secret": "SECRET_VERIFICATION_EVIDENCE"},
            metrics={"secret": "SECRET_VERIFICATION_METRIC"},
        )
        return decision, change, artifact

    def test_counts_lists_details_and_redaction(self) -> None:
        decision, change, artifact = self._evidence()
        before = self.runtime.status()
        counts = self.reader.counts()
        decisions = self.reader.list_decisions(limit=1)
        changes = self.reader.list_changes(limit=1)
        artifacts = self.reader.list_artifacts(limit=1)
        verifications = self.reader.list_artifact_verifications(limit=1)
        after = self.runtime.status()
        self.assertEqual(before, after)
        self.assertEqual(
            counts,
            {"decisions": 1, "changes": 1, "artifacts": 1, "artifact_verifications": 1},
        )
        self.assertEqual(decisions[0]["id"], decision)
        self.assertEqual(changes[0]["id"], change)
        self.assertEqual(artifacts[0]["id"], artifact)
        self.assertFalse(decisions[0]["context_disclosed"])
        self.assertFalse(decisions[0]["alternatives_disclosed"])
        self.assertFalse(artifacts[0]["artifact_bytes_disclosed"])
        self.assertFalse(artifacts[0]["skill_versions_disclosed"])
        self.assertFalse(artifacts[0]["tool_versions_disclosed"])
        self.assertFalse(verifications[0]["evidence_disclosed"])
        self.assertFalse(verifications[0]["metrics_disclosed"])
        self.assertEqual(self.reader.get_decision(decision)["id"], decision)
        self.assertEqual(self.reader.get_change(change)["id"], change)
        self.assertEqual(self.reader.get_artifact(artifact)["id"], artifact)
        serialized = repr((decisions, changes, artifacts, verifications))
        for forbidden in (
            "SECRET_DECISION_CONTEXT",
            "SECRET_ALTERNATIVE",
            "SECRET_ARTIFACT_BYTES",
            "SECRET_SKILL_VERSION",
            "SECRET_TOOL_VERSION",
            "SECRET_VERIFICATION_EVIDENCE",
            "SECRET_VERIFICATION_METRIC",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_invalid_limits_and_ids_fail_closed(self) -> None:
        for value in (0, 10_001, True, "1"):
            with self.assertRaises(ValueError):
                self.reader.list_artifacts(limit=value)  # type: ignore[arg-type]
        with self.assertRaises(KeyError):
            self.reader.get_decision("DEC-not-real")
        with self.assertRaises(KeyError):
            self.reader.get_change("CHG-not-real")
        with self.assertRaises(KeyError):
            self.reader.get_artifact("ART-not-real")

    def test_facade_is_select_only_and_never_reads_artifact_files(self) -> None:
        source = inspect.getsource(read_module)
        for forbidden in (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "read_text(",
            "read_bytes(",
            "open(",
            "local_artifact_path",
            "create_artifact(",
            "record_verification(",
            "_append_event",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
