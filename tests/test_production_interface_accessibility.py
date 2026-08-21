from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.production_interface_html import render_detail, render_overview
from origin_forge.production_interface_snapshot import build_production_interface_snapshot
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-accessibility-test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_overview_skip_target_is_focusable_and_current_page_is_truthful(self) -> None:
        self.runtime.create_goal("goal")
        page = render_overview(build_production_interface_snapshot(self.runtime))

        self.assertIn('<a class="skip-link" href="#main">Skip to content</a>', page)
        self.assertIn('<main id="main" class="cockpit-main" tabindex="-1">', page)
        self.assertIn('<a href="/" aria-current="page">Overview</a>', page)
        self.assertIn(".cockpit-main [id] { scroll-margin-top: 90px; }", page)
        self.assertIn("@media (prefers-reduced-motion: reduce)", page)
        self.assertIn("html { scroll-behavior: auto; }", page)

    def test_detail_does_not_announce_overview_as_current_page(self) -> None:
        goal = self.runtime.create_goal("goal")
        snapshot = build_production_interface_snapshot(self.runtime)
        page = render_detail(snapshot, "goal", goal)

        self.assertIn('<main id="main" class="cockpit-main" tabindex="-1">', page)
        self.assertIn('<a href="/">Overview</a>', page)
        self.assertNotIn('<a href="/" aria-current="page">Overview</a>', page)
        self.assertIn('class="breadcrumb"><a href="/">Overview</a>', page)

    def test_accessibility_layer_preserves_read_only_markup(self) -> None:
        self.runtime.create_goal("goal")
        page = render_overview(build_production_interface_snapshot(self.runtime))
        lowered = page.lower()

        self.assertNotIn("<script", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("<button", lowered)
        self.assertNotIn("<input", lowered)
        self.assertNotIn("<textarea", lowered)
        self.assertIn("script-src 'none'", page)
        self.assertIn("form-action 'none'", page)
        self.assertIn("connect-src 'none'", page)


if __name__ == "__main__":
    unittest.main()
