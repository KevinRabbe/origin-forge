from __future__ import annotations

import unittest

from origin_forge.production_execution_owner_runtime import (
    RUNTIME_EXECUTION_OWNER_ID,
    runtime_observation_execution_owner_descriptor,
)


class RuntimeObservationExecutionOwnerTests(unittest.TestCase):
    def test_owner_is_evidence_only_and_matches_exact_runtime_relation(self) -> None:
        owner = runtime_observation_execution_owner_descriptor()
        self.assertEqual(owner.owner_id, RUNTIME_EXECUTION_OWNER_ID)
        self.assertEqual(owner.adapter_id, "originforge.runtime.observe")
        self.assertEqual(owner.dispatch_contract_id, "runtime.observe@1")
        self.assertEqual(owner.model_strategy_roles, ())
        self.assertFalse(owner.requires_sandbox)
        self.assertFalse(owner.requires_workspace_manager)


if __name__ == "__main__":
    unittest.main()
