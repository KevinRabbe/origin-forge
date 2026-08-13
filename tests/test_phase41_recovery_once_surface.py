from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_preparation_recovery_once as module


class Phase41RecoveryOnceSurfaceTests(unittest.TestCase):
    def test_public_surface_is_single_prep_only(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(module.recover_preparation_once).parameters),
            ("runtime", "preparation_id"),
        )
        source = inspect.getsource(module)
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)))
        self.assertEqual(source.count("inspect_preparation_recovery_readonly("), 1)
        self.assertEqual(source.count("resume_routed_preparation_planner_once("), 1)
        self.assertEqual(source.count("recover_planner_evidence("), 1)
        for forbidden in (
            "advance_production_manager_once",
            "dispatch_manager_tick",
            "acquire_dispatch_claim",
            "_dispatch_selected_candidate_once",
            "planner.propose(",
            ".generate(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
