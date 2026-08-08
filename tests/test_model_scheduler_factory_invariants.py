from __future__ import annotations

import unittest

from origin_forge.model_scheduler import (
    ModelResourceProfile,
    ModelRole,
    ModelSelectionPolicy,
)
from origin_forge.model_scheduler_factory import create_model_scheduling
from origin_forge.resource_model_config import ResourceModelConfig
from origin_forge.resource_scheduler import ResourceCapacity, ResourceRequest


class ModelSchedulerFactoryInvariantTests(unittest.TestCase):
    def _profile(self, profile_id: str, role: ModelRole) -> ModelResourceProfile:
        return ModelResourceProfile(
            profile_id,
            role,
            f"model-{profile_id}",
            "runtime",
            ResourceRequest(cpu_slots=1),
        )

    def test_disabled_direct_config_cannot_hide_model_inventory(self) -> None:
        profile = self._profile("fast", ModelRole.CODER_FAST)
        config = ResourceModelConfig(False, None, (profile,), ())
        with self.assertRaisesRegex(ValueError, "disabled resource scheduling"):
            create_model_scheduling(config)

    def test_direct_duplicate_policy_roles_are_revalidated(self) -> None:
        profile = self._profile("fast", ModelRole.CODER_FAST)
        policy = ModelSelectionPolicy(ModelRole.CODER_FAST, "fast")
        config = ResourceModelConfig(
            True,
            ResourceCapacity(4, 8192),
            (profile,),
            (policy, policy),
        )
        with self.assertRaisesRegex(ValueError, "duplicate configured model policy role"):
            create_model_scheduling(config)

    def test_direct_cross_role_policy_is_revalidated(self) -> None:
        fast = self._profile("fast", ModelRole.CODER_FAST)
        strong = self._profile("strong", ModelRole.CODER_STRONG)
        config = ResourceModelConfig(
            True,
            ResourceCapacity(4, 8192),
            (fast, strong),
            (ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("fast",)),),
        )
        with self.assertRaisesRegex(ValueError, "does not match profiles"):
            create_model_scheduling(config)


if __name__ == "__main__":
    unittest.main()
