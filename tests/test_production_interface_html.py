from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.production_interface_html import render_detail, render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-html-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_hostile_project_text_is_escaped_and_inert(self) -> None:
        hostile = '<script>alert(1)</script><img src=x onerror="boom">'
        goal = self.runtime.create_goal(hostile)
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_overview(snapshot)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("onerror=&quot;boom&quot;", page)
        detail = render_detail(snapshot, "goal", goal)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", detail)

    def test_page_has_no_executable_or_mutation_markup(self) -> None:
        self.runtime.create_goal("goal")
        page = render_overview(build_production_interface_snapshot(self.runtime))
        lowered = page.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("javascript:", lowered)
        self.assertIn("script-src 'none'", page)
        self.assertIn("form-action 'none'", page)
        self.assertIn("connect-src 'none'", page)

    def test_ui_foundation_is_read_only_and_navigable(self) -> None:
        self.runtime.create_goal("goal")
        page = render_overview(build_production_interface_snapshot(self.runtime))
        self.assertIn('class="app-header"', page)
        self.assertIn('class="mode-badge"', page)
        self.assertIn("Read only", page)
        self.assertIn('class="metric-grid"', page)
        self.assertIn('aria-label="Cockpit sections"', page)
        self.assertIn('href="#resources"', page)
        self.assertIn('id="resources"', page)
        self.assertIn('class="table-shell"', page)
        self.assertIn('<main id="main" class="cockpit-main">', page)
        self.assertNotIn("<link", page.lower())

    def test_lifecycle_summary_is_snapshot_scoped_and_read_only(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        self.runtime.create_task(flow, "task")
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_overview(snapshot)
        self.assertIn('aria-label="Production lifecycle summary"', page)
        self.assertIn("Production lifecycle", page)
        self.assertIn(
            'class="lifecycle-stage-name">Goals</span>'
            '<span class="lifecycle-stage-total">1</span>',
            page,
        )
        self.assertIn(
            'class="lifecycle-stage-name">Flows</span>'
            '<span class="lifecycle-stage-total">1</span>',
            page,
        )
        self.assertIn(
            'class="lifecycle-stage-name">Tasks</span>'
            '<span class="lifecycle-stage-total">1</span>',
            page,
        )
        self.assertIn(
            'class="lifecycle-stage-name">Artifacts</span>'
            '<span class="lifecycle-stage-total">0</span>',
            page,
        )
        goal_status = str(snapshot.goals[0]["status"])
        self.assertIn(f'title="{goal_status}"', page)
        self.assertIn("do not grant execution, mutation, or verification authority", page)

    def test_evidence_lineage_joins_existing_snapshot_records_without_new_authority(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        snapshot = build_production_interface_snapshot(self.runtime)
        run_id = "RUN-lineage"
        change_id = "CHANGE-lineage"
        artifact_id = "ARTIFACT-lineage"
        verification_id = "VERIFY-lineage"
        manifest_id = "MANIFEST-lineage"
        enriched = replace(
            snapshot,
            runs=(
                {
                    "id": run_id,
                    "task_id": task,
                    "role": "PRODUCER",
                    "model_profile": "profile-lineage",
                    "model_hash": "sha256:model",
                    "status": "SUCCEEDED",
                    "started_at": "2026-08-21T00:00:00Z",
                    "ended_at": "2026-08-21T00:00:01Z",
                    "input_token_count": 0,
                    "output_token_count": 0,
                },
            ),
            changes=(
                {
                    "id": change_id,
                    "task_id": task,
                    "decision_id": None,
                    "run_id": run_id,
                    "summary": "lineage change",
                    "summary_truncated": False,
                    "change_type": "ASSET",
                    "change_type_truncated": False,
                    "before_ref": None,
                    "before_ref_truncated": False,
                    "after_ref": "artifact:model.glb",
                    "after_ref_truncated": False,
                    "status": "RECORDED",
                    "created_at": "2026-08-21T00:00:01Z",
                },
            ),
            artifacts=(
                {
                    "id": artifact_id,
                    "change_id": change_id,
                    "type": "MODEL3D",
                    "type_truncated": False,
                    "path_or_uri": "artifacts/model.glb",
                    "path_or_uri_truncated": False,
                    "content_hash": "sha256:artifact",
                    "parent_artifact_id": None,
                    "created_by_run_id": run_id,
                    "model_id": "model-lineage",
                    "model_id_truncated": False,
                    "status": "ADOPTED",
                    "created_at": "2026-08-21T00:00:02Z",
                    "artifact_bytes_disclosed": False,
                    "skill_versions_disclosed": False,
                    "tool_versions_disclosed": False,
                },
            ),
            artifact_verifications=(
                {
                    "id": verification_id,
                    "target_type": "ARTIFACT",
                    "target_id": artifact_id,
                    "verification_type": "STRUCTURAL",
                    "verification_type_truncated": False,
                    "verifier": "test-verifier",
                    "verifier_truncated": False,
                    "status": "PASSED",
                    "run_id": run_id,
                    "created_at": "2026-08-21T00:00:03Z",
                    "evidence_disclosed": False,
                    "metrics_disclosed": False,
                },
            ),
            provenance={
                **snapshot.provenance,
                "manifests": [
                    {
                        "manifest_id": manifest_id,
                        "artifact_id": artifact_id,
                        "artifact_type": "MODEL3D",
                        "artifact_location": "artifacts/model.glb",
                        "task_id": task,
                        "run_id": run_id,
                        "signing_key_id": "KEY-lineage",
                    }
                ],
            },
        )
        page = render_overview(enriched)
        self.assertIn('aria-label="Evidence and lineage"', page)
        self.assertIn('href="#lineage"', page)
        self.assertIn('id="lineage"', page)
        self.assertIn(f'href="/task/{task}"', page)
        self.assertIn(f'href="/run/{run_id}"', page)
        self.assertIn(f'href="/change/{change_id}"', page)
        self.assertIn(f'href="/artifact/{artifact_id}"', page)
        self.assertIn(f'href="/verification/{verification_id}"', page)
        self.assertIn(manifest_id, page)
        self.assertIn("KEY-lineage", page)
        self.assertNotIn(f'/manifest/{manifest_id}', page)
        self.assertIn("does not perform Ed25519 trust verification", page)
        self.assertIn(
            "Visibility does not grant execution, verification, mutation, or trust authority",
            page,
        )

    def test_detail_uses_same_shell_without_gaining_authority(self) -> None:
        goal = self.runtime.create_goal("goal")
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_detail(snapshot, "goal", goal)
        lowered = page.lower()
        self.assertIn('class="breadcrumb"', page)
        self.assertIn('href="/">Overview</a>', page)
        self.assertIn('aria-label="Snapshot relationships"', page)
        self.assertIn(goal, page)
        self.assertIn("Read only", page)
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)

    def test_task_detail_context_links_parent_and_counts_snapshot_children(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_detail(snapshot, "task", task)
        self.assertIn('aria-label="Snapshot relationships"', page)
        self.assertIn(f'href="/flow/{flow}"', page)
        self.assertIn("Parent flow", page)
        self.assertIn(
            '<span class="detail-context-label">Runs</span>'
            '<span class="detail-context-value">0</span>',
            page,
        )
        self.assertIn(
            '<span class="detail-context-label">Verifications</span>'
            '<span class="detail-context-value">0</span>',
            page,
        )
        self.assertIn(
            '<span class="detail-context-label">Changes</span>'
            '<span class="detail-context-value">0</span>',
            page,
        )

    def test_causal_detail_navigation_is_snapshot_scoped(self) -> None:
        goal = self.runtime.create_goal("goal")
        flow = self.runtime.create_flow(goal)
        task = self.runtime.create_task(flow, "task")
        snapshot = build_production_interface_snapshot(self.runtime)
        goal_page = render_detail(snapshot, "goal", goal)
        flow_page = render_detail(snapshot, "flow", flow)
        task_page = render_detail(snapshot, "task", task)
        self.assertIn(f'/flow/{flow}', goal_page)
        self.assertIn(f'/task/{task}', flow_page)
        self.assertIn(task, task_page)

    def test_unknown_detail_fails_closed(self) -> None:
        snapshot = build_production_interface_snapshot(self.runtime)
        with self.assertRaises(KeyError):
            render_detail(snapshot, "goal", "GOAL-not-real")
        with self.assertRaises(KeyError):
            render_detail(snapshot, "unknown", "x")


if __name__ == "__main__":
    unittest.main()
