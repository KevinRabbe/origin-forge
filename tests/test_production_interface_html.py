from __future__ import annotations

import tempfile
import unittest
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
