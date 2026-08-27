from __future__ import annotations

import tempfile
import unittest

from origin_forge.production_capability_builtin import (
    build_builtin_capability_catalog,
    builtin_production_capabilities,
    builtin_trusted_production_adapters,
)
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_routing import (
    CapabilityRouteOutcome,
    resolve_task_route,
)
from origin_forge.runtime import OriginForgeRuntime


class BuiltinProductionCapabilityTests(unittest.TestCase):
    def test_reviewed_builtin_inventory_is_well_formed_and_blockbench_absent(self) -> None:
        catalog = build_builtin_capability_catalog()
        expected_capabilities = {
            "design.specify",
            "build.integration",
            "code.change",
            "media.2d.export",
            "media.2d.source",
            "media.3d.blender",
            "image.generate",
            "image.inspect",
            "media.audio.process",
            "media.audio.tts",
            "runtime.observe",
            "runtime.playtest",
            "simulation.run",
        }
        self.assertEqual(set(catalog.capability_ids), expected_capabilities)
        self.assertEqual(
            set(catalog.capabilities),
            set(builtin_production_capabilities()),
        )
        self.assertEqual(
            set(catalog.adapters),
            set(builtin_trusted_production_adapters()),
        )
        self.assertFalse(any("blockbench" in value for value in catalog.adapter_ids))
        self.assertFalse(any("blockbench" in value for value in catalog.capability_ids))

    def test_design_capability_is_known_but_has_no_builtin_executor(self) -> None:
        catalog = build_builtin_capability_catalog()
        self.assertIn("design.specify", catalog.capability_ids)
        self.assertFalse(
            any("design.specify" in adapter.capability_ids for adapter in catalog.adapters)
        )

    def test_all_builtin_fingerprints_are_exact_contract_identity_hashes(self) -> None:
        adapters = builtin_trusted_production_adapters()
        self.assertEqual(len(adapters), len({value.adapter_id for value in adapters}))
        for adapter in adapters:
            self.assertEqual(len(adapter.implementation_fingerprint), 64)
            int(adapter.implementation_fingerprint, 16)
            payload = adapter.to_dict()
            for forbidden in (
                "argv",
                "shell",
                "callable",
                "import_path",
                "url",
                "secret",
                "executable",
            ):
                self.assertNotIn(forbidden, payload)

    def test_catalog_inventory_alone_does_not_route_without_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("builtin-routing")
            goal = runtime.create_goal("change code")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(
                flow,
                "bounded code change",
                required_capabilities=("code.change",),
            )
            catalog = build_builtin_capability_catalog()
            policy = CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("originforge.code.bounded-retry",),
                allowed_capability_ids=("code.change",),
            )
            result = resolve_task_route(runtime.store, task, catalog, policy)
            self.assertEqual(result.outcome, CapabilityRouteOutcome.ROUTABLE)
            self.assertEqual(
                result.selected_adapter_id,
                "originforge.code.bounded-retry",
            )
            self.assertNotIn(
                "originforge.pixelorama.export",
                result.considered_adapter_ids,
            )


if __name__ == "__main__":
    unittest.main()
