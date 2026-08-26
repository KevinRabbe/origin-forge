from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_execution_owner as owner_module
from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_builtin import (
    builtin_trusted_production_adapters,
)
from origin_forge.production_dispatch_binding import CodeBoundedRetryInputBinder
from origin_forge.production_dispatch_binding_blender import BlenderExportGLBInputBinder
from origin_forge.production_dispatch_binding_pixelorama import (
    PixeloramaSpritesheetExportInputBinder,
)
from origin_forge.production_dispatch_binding_simulation import (
    DeterministicSimulationInputBinder,
)
from origin_forge.production_execution_owner import (
    ProductionExecutionOwnerDescriptor,
    ProductionExecutionOwnerError,
    ProductionExecutionOwnerRegistry,
    build_builtin_execution_owner_registry,
    builtin_execution_owner_descriptors,
)


class ProductionExecutionOwnerTests(unittest.TestCase):
    def _descriptor(self, *, owner_id: str = "owner.test@1") -> ProductionExecutionOwnerDescriptor:
        binder = CodeBoundedRetryInputBinder().descriptor
        adapter = next(
            value
            for value in builtin_trusted_production_adapters()
            if value.adapter_id == "originforge.code.bounded-retry"
        )
        return ProductionExecutionOwnerDescriptor(
            owner_id=owner_id,
            owner_version="1",
            adapter_id=adapter.adapter_id,
            adapter_fingerprint=adapter.implementation_fingerprint,
            dispatch_contract_id=binder.dispatch_contract_id,
            binder_id=binder.binder_id,
            binder_fingerprint=binder.binder_fingerprint,
            request_type_id=binder.request_type_id,
            request_schema_hash=binder.request_schema_hash,
            model_strategy_roles=(ModelRole.CODER_STRONG,),
            requires_sandbox=True,
            requires_workspace_manager=True,
        )

    def test_builtin_owners_exactly_match_reviewed_adapters_and_binders(self) -> None:
        owners = builtin_execution_owner_descriptors()
        self.assertEqual(len(owners), 8)
        code_owner, simulation_owner, pixelorama_owner, blender_owner, image_owner, piper_owner, runtime_owner, playtest_owner = owners
        self.assertEqual(image_owner.owner_id, "originforge.execution.image.generate@1")
        self.assertEqual(piper_owner.owner_id, "originforge.execution.audio.piper-tts@1")
        self.assertEqual(runtime_owner.owner_id, "originforge.execution.runtime.observe@1")
        self.assertEqual(playtest_owner.owner_id, "originforge.execution.playtest.cooperative@1")
        adapters = {
            value.adapter_id: value for value in builtin_trusted_production_adapters()
        }

        code_adapter = adapters["originforge.code.bounded-retry"]
        code_binder = CodeBoundedRetryInputBinder().descriptor
        self.assertEqual(code_owner.owner_id, "originforge.execution.bounded-retry@1")
        self.assertEqual(code_owner.adapter_id, code_adapter.adapter_id)
        self.assertEqual(
            code_owner.adapter_fingerprint,
            code_adapter.implementation_fingerprint,
        )
        self.assertEqual(code_owner.dispatch_contract_id, code_binder.dispatch_contract_id)
        self.assertEqual(code_owner.binder_id, code_binder.binder_id)
        self.assertEqual(code_owner.binder_fingerprint, code_binder.binder_fingerprint)
        self.assertEqual(code_owner.request_type_id, code_binder.request_type_id)
        self.assertEqual(code_owner.request_schema_hash, code_binder.request_schema_hash)
        self.assertEqual(code_owner.model_strategy_roles, (ModelRole.CODER_STRONG,))
        self.assertNotIn(ModelRole.CODER_FAST, code_owner.model_strategy_roles)
        self.assertTrue(code_owner.requires_sandbox)
        self.assertTrue(code_owner.requires_workspace_manager)

        simulation_adapter = adapters["originforge.simulation.deterministic"]
        simulation_binder = DeterministicSimulationInputBinder().descriptor
        self.assertEqual(
            simulation_owner.owner_id,
            "originforge.execution.simulation.deterministic@1",
        )
        self.assertEqual(simulation_owner.adapter_id, simulation_adapter.adapter_id)
        self.assertEqual(
            simulation_owner.adapter_fingerprint,
            simulation_adapter.implementation_fingerprint,
        )
        self.assertEqual(
            simulation_owner.dispatch_contract_id,
            simulation_binder.dispatch_contract_id,
        )
        self.assertEqual(simulation_owner.binder_id, simulation_binder.binder_id)
        self.assertEqual(
            simulation_owner.binder_fingerprint,
            simulation_binder.binder_fingerprint,
        )
        self.assertEqual(
            simulation_owner.request_type_id,
            simulation_binder.request_type_id,
        )
        self.assertEqual(
            simulation_owner.request_schema_hash,
            simulation_binder.request_schema_hash,
        )
        self.assertEqual(simulation_owner.model_strategy_roles, ())
        self.assertFalse(simulation_owner.requires_sandbox)
        self.assertFalse(simulation_owner.requires_workspace_manager)

        pixelorama_adapter = adapters["originforge.pixelorama.export"]
        pixelorama_binder = PixeloramaSpritesheetExportInputBinder().descriptor
        self.assertEqual(
            pixelorama_owner.owner_id,
            "originforge.execution.pixelorama.spritesheet-export@1",
        )
        self.assertEqual(pixelorama_owner.adapter_id, pixelorama_adapter.adapter_id)
        self.assertEqual(pixelorama_owner.adapter_fingerprint, pixelorama_adapter.implementation_fingerprint)
        self.assertEqual(pixelorama_owner.dispatch_contract_id, pixelorama_binder.dispatch_contract_id)
        self.assertEqual(pixelorama_owner.binder_id, pixelorama_binder.binder_id)
        self.assertEqual(pixelorama_owner.binder_fingerprint, pixelorama_binder.binder_fingerprint)
        self.assertEqual(pixelorama_owner.request_type_id, pixelorama_binder.request_type_id)
        self.assertEqual(pixelorama_owner.request_schema_hash, pixelorama_binder.request_schema_hash)
        self.assertEqual(pixelorama_owner.model_strategy_roles, ())
        self.assertFalse(pixelorama_owner.requires_sandbox)
        self.assertFalse(pixelorama_owner.requires_workspace_manager)

        blender_adapter = adapters["originforge.blender.model3d"]
        blender_binder = BlenderExportGLBInputBinder().descriptor
        self.assertEqual(
            blender_owner.owner_id,
            "originforge.execution.blender.export-glb@1",
        )
        self.assertEqual(blender_owner.adapter_id, blender_adapter.adapter_id)
        self.assertEqual(
            blender_owner.adapter_fingerprint,
            blender_adapter.implementation_fingerprint,
        )
        self.assertEqual(
            blender_owner.dispatch_contract_id,
            blender_binder.dispatch_contract_id,
        )
        self.assertEqual(blender_owner.binder_id, blender_binder.binder_id)
        self.assertEqual(
            blender_owner.binder_fingerprint,
            blender_binder.binder_fingerprint,
        )
        self.assertEqual(blender_owner.request_type_id, blender_binder.request_type_id)
        self.assertEqual(
            blender_owner.request_schema_hash,
            blender_binder.request_schema_hash,
        )
        self.assertEqual(blender_owner.model_strategy_roles, ())
        self.assertFalse(blender_owner.requires_sandbox)
        self.assertFalse(blender_owner.requires_workspace_manager)

    def test_owner_and_registry_fingerprints_are_deterministic(self) -> None:
        first = build_builtin_execution_owner_registry()
        second = build_builtin_execution_owner_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.descriptors, second.descriptors)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")
        for first_owner, second_owner in zip(first.descriptors, second.descriptors):
            self.assertEqual(first_owner.fingerprint, second_owner.fingerprint)
            self.assertRegex(first_owner.fingerprint, r"^[0-9a-f]{64}$")

    def test_exact_relation_selects_owner_and_any_drift_fails_closed(self) -> None:
        registry = build_builtin_execution_owner_registry()
        owner = registry.descriptors[0]
        selected = registry.owner_for(
            adapter_id=owner.adapter_id,
            adapter_fingerprint=owner.adapter_fingerprint,
            dispatch_contract_id=owner.dispatch_contract_id,
            binder_id=owner.binder_id,
            binder_fingerprint=owner.binder_fingerprint,
            request_type_id=owner.request_type_id,
            request_schema_hash=owner.request_schema_hash,
        )
        self.assertEqual(selected, owner)

        base = {
            "adapter_id": owner.adapter_id,
            "adapter_fingerprint": owner.adapter_fingerprint,
            "dispatch_contract_id": owner.dispatch_contract_id,
            "binder_id": owner.binder_id,
            "binder_fingerprint": owner.binder_fingerprint,
            "request_type_id": owner.request_type_id,
            "request_schema_hash": owner.request_schema_hash,
        }
        drift = (
            ("adapter_id", "originforge.audio.ffmpeg"),
            ("adapter_fingerprint", "0" * 64),
            ("dispatch_contract_id", "code.other@1"),
            ("binder_id", "binder.other@1"),
            ("binder_fingerprint", "0" * 64),
            ("request_type_id", "OtherRequest@1"),
            ("request_schema_hash", "0" * 64),
        )
        for field, value in drift:
            with self.subTest(field=field), self.assertRaises(ProductionExecutionOwnerError):
                registry.owner_for(**{**base, field: value})

    def test_registry_rejects_duplicate_ids_and_ambiguous_relations(self) -> None:
        first = self._descriptor(owner_id="owner.one@1")
        duplicate_id = self._descriptor(owner_id="owner.one@1")
        with self.assertRaisesRegex(ProductionExecutionOwnerError, "duplicate owner"):
            ProductionExecutionOwnerRegistry((first, duplicate_id))

        ambiguous = self._descriptor(owner_id="owner.two@1")
        with self.assertRaisesRegex(ProductionExecutionOwnerError, "ambiguous"):
            ProductionExecutionOwnerRegistry((first, ambiguous))

    def test_descriptor_allows_empty_roles_and_rejects_malformed_strategy_authority(self) -> None:
        base = self._descriptor()
        values = base.authority_dict()
        common = {
            "owner_id": values["owner_id"],
            "owner_version": values["owner_version"],
            "adapter_id": values["adapter_id"],
            "adapter_fingerprint": values["adapter_fingerprint"],
            "dispatch_contract_id": values["dispatch_contract_id"],
            "binder_id": values["binder_id"],
            "binder_fingerprint": values["binder_fingerprint"],
            "request_type_id": values["request_type_id"],
            "request_schema_hash": values["request_schema_hash"],
            "requires_sandbox": True,
            "requires_workspace_manager": True,
        }
        empty = ProductionExecutionOwnerDescriptor(
            **common,
            model_strategy_roles=(),
        )
        self.assertEqual(empty.model_strategy_roles, ())
        with self.assertRaises(ProductionExecutionOwnerError):
            ProductionExecutionOwnerDescriptor(
                **common,
                model_strategy_roles=(ModelRole.CODER_STRONG, ModelRole.CODER_STRONG),
            )
        with self.assertRaises(ProductionExecutionOwnerError):
            ProductionExecutionOwnerDescriptor(
                **{**common, "adapter_fingerprint": "X" * 64},
                model_strategy_roles=(ModelRole.CODER_STRONG,),
            )
        with self.assertRaises(ProductionExecutionOwnerError):
            ProductionExecutionOwnerDescriptor(
                **{**common, "requires_sandbox": 1},
                model_strategy_roles=(ModelRole.CODER_STRONG,),
            )

    def test_persistable_descriptor_contains_no_dynamic_execution_authority(self) -> None:
        for owner in build_builtin_execution_owner_registry().descriptors:
            payload = owner.to_dict()
            self.assertEqual(
                set(payload),
                {
                    "owner_id",
                    "owner_version",
                    "adapter_id",
                    "adapter_fingerprint",
                    "dispatch_contract_id",
                    "binder_id",
                    "binder_fingerprint",
                    "request_type_id",
                    "request_schema_hash",
                    "model_strategy_roles",
                    "requires_sandbox",
                    "requires_workspace_manager",
                    "owner_fingerprint",
                },
            )
            for forbidden in (
                "callable",
                "import",
                "module",
                "shell",
                "argv",
                "endpoint",
                "api_key",
                "executable",
                "environment",
                "loader",
            ):
                self.assertNotIn(forbidden, payload)

    def test_source_has_no_executor_runtime_or_process_authority(self) -> None:
        source = inspect.getsource(owner_module)
        for forbidden in (
            "BoundedRetryPolicy",
            "ScheduledModelAdapter",
            "LlamaCppAdapter",
            "subprocess",
            "importlib",
            "sandbox_factory",
            "model_runtime_registry",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        forbidden_calls = {
            "drive",
            "generate",
            "load",
            "unload",
            "start_run",
            "create_run",
            "transition_task",
            "create_workspace",
            "lease",
            "use",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
