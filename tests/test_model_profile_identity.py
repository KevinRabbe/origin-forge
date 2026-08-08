from __future__ import annotations

import unittest

from origin_forge.model_scheduler import ModelResourceProfile, ModelRole
from origin_forge.resource_scheduler import ResourceRequest


class ModelProfileIdentityTests(unittest.TestCase):
    def test_runtime_model_id_may_use_provider_style_slash_name(self) -> None:
        profile = ModelResourceProfile(
            "coder-strong",
            ModelRole.CODER_STRONG,
            "Qwen/Qwen3-Coder-30B-A3B",
            "llamacpp",
            ResourceRequest(cpu_slots=1),
        )
        self.assertEqual(profile.model_id, "Qwen/Qwen3-Coder-30B-A3B")

    def test_governed_profile_and_runtime_ids_remain_strict(self) -> None:
        with self.assertRaises(ValueError):
            ModelResourceProfile(
                "bad/profile",
                ModelRole.CODER_STRONG,
                "Qwen/Qwen3",
                "llamacpp",
                ResourceRequest(cpu_slots=1),
            )
        with self.assertRaises(ValueError):
            ModelResourceProfile(
                "profile",
                ModelRole.CODER_STRONG,
                "Qwen/Qwen3",
                "bad runtime",
                ResourceRequest(cpu_slots=1),
            )

    def test_model_id_rejects_whitespace_and_control_characters(self) -> None:
        for model_id in ("bad model", "bad\nmodel", ""):
            with self.subTest(model_id=model_id):
                with self.assertRaises(ValueError):
                    ModelResourceProfile(
                        "profile",
                        ModelRole.CODER_STRONG,
                        model_id,
                        "runtime",
                        ResourceRequest(cpu_slots=1),
                    )

    def test_model_hash_is_bounded_and_whitespace_free(self) -> None:
        ModelResourceProfile(
            "profile",
            ModelRole.CODER_STRONG,
            "model",
            "runtime",
            ResourceRequest(cpu_slots=1),
            model_hash="sha256:abc123",
        )
        with self.assertRaises(ValueError):
            ModelResourceProfile(
                "profile",
                ModelRole.CODER_STRONG,
                "model",
                "runtime",
                ResourceRequest(cpu_slots=1),
                model_hash="sha256:bad hash",
            )


if __name__ == "__main__":
    unittest.main()
