from __future__ import annotations

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
        self.assertNotIn("advance_production_manager_once", source)
        self.assertNotIn("acquire_dispatch_claim", source)
        self.assertNotIn("planner.propose(", source)


if __name__ == "__main__":
    unittest.main()
