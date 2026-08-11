from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_interface_html import render_detail, render_overview
from origin_forge.production_interface_server import ProductionInterfaceRouter
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceCausalEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-causal-evidence-test")
        self.lineage = OriginForgeLineage(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _chain(self) -> tuple[str, str, str, str]:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        decision = self.lineage.create_decision(
            title='<script>alert("decision")</script>',
            decision="Use metadata-only artifact inspection",
            context="SECRET_CONTEXT",
            rationale='<img src=x onerror="rationale">',
            alternatives=("SECRET_ALTERNATIVE",),
            goal_id=goal,
            task_id=task,
        )
        change = self.lineage.create_change(
            task,
            summary='<script>alert("change")</script>',
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
            skill_versions=("SECRET_SKILL",),
            tool_versions=("SECRET_TOOL",),
        )
        verification = self.lineage.record_artifact_verification(
            artifact,
            verification_type="integrity",
            verifier='<script>alert("verifier")</script>',
            status="PASS",
            evidence={"secret": "SECRET_EVIDENCE"},
            metrics={"secret": "SECRET_METRIC"},
        )
        return decision, change, artifact, verification

    def test_snapshot_carries_redacted_causal_chain_without_reading_artifact_bytes(self) -> None:
        decision, change, artifact, verification = self._chain()
        before = self.runtime.status()
        snapshot = build_production_interface_snapshot(self.runtime)
        after = self.runtime.status()
        self.assertEqual(before, after)
        self.assertEqual(snapshot.total_counts["decisions"], 1)
        self.assertEqual(snapshot.total_counts["changes"], 1)
        self.assertEqual(snapshot.total_counts["artifacts"], 1)
        self.assertEqual(snapshot.total_counts["artifact_verifications"], 1)
        self.assertEqual(snapshot.decisions[0]["id"], decision)
        self.assertEqual(snapshot.changes[0]["id"], change)
        self.assertEqual(snapshot.artifacts[0]["id"], artifact)
        self.assertEqual(snapshot.artifact_verifications[0]["id"], verification)
        self.assertFalse(snapshot.to_dict()["authority"]["artifact_bytes_read"])
        self.assertFalse(snapshot.to_dict()["authority"]["verification_payload_read"])
        serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
        for forbidden in (
            "SECRET_CONTEXT",
            "SECRET_ALTERNATIVE",
            "SECRET_ARTIFACT_BYTES",
            "SECRET_SKILL",
            "SECRET_TOOL",
            "SECRET_EVIDENCE",
            "SECRET_METRIC",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_causal_pages_escape_text_and_link_chain(self) -> None:
        decision, change, artifact, verification = self._chain()
        snapshot = build_production_interface_snapshot(self.runtime)
        overview = render_overview(snapshot)
        decision_page = render_detail(snapshot, "decision", decision)
        change_page = render_detail(snapshot, "change", change)
        artifact_page = render_detail(snapshot, "artifact", artifact)
        verification_page = render_detail(snapshot, "verification", verification)
        for page in (overview, decision_page, change_page, artifact_page, verification_page):
            self.assertNotIn('<script>alert("decision")</script>', page)
            self.assertNotIn('<script>alert("change")</script>', page)
            self.assertNotIn('<script>alert("verifier")</script>', page)
            self.assertNotIn("SECRET_ARTIFACT_BYTES", page)
        self.assertIn(f"/change/{change}", decision_page)
        self.assertIn(f"/artifact/{artifact}", change_page)
        self.assertIn(f"/verification/{verification}", artifact_page)
        self.assertIn("integrity", verification_page)

    def test_causal_routes_are_typed_and_non_mutating(self) -> None:
        decision, change, artifact, verification = self._chain()
        router = ProductionInterfaceRouter(self.runtime)
        for path in (
            f"/decision/{decision}",
            f"/change/{change}",
            f"/artifact/{artifact}",
            f"/verification/{verification}",
        ):
            self.assertEqual(router.route("GET", path).status, 200)
            self.assertEqual(router.route("POST", path).status, 405)
        self.assertEqual(router.route("GET", "/artifact/ART-not-real").status, 404)
        self.assertEqual(router.route("GET", "/decision/DEC-not-real").status, 404)

    def test_causal_sections_report_truncation(self) -> None:
        self._chain()
        second = self.lineage.create_decision(title="second", decision="second")
        snapshot = build_production_interface_snapshot(self.runtime, max_decisions=1)
        self.assertEqual(len(snapshot.decisions), 1)
        self.assertEqual(snapshot.total_counts["decisions"], 2)
        self.assertTrue(snapshot.truncated["decisions"])
        self.assertTrue(second.startswith("DEC-"))


if __name__ == "__main__":
    unittest.main()
