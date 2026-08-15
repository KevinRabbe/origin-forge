from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_preparation_owner import (
    ProductionPreparationOwnerDescriptor,
    ProductionPreparationOwnerError,
    build_builtin_preparation_owner_registry,
    require_current_preparation_owner,
)
from origin_forge.production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    _matching_owner,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import DispatchContractCatalog
from origin_forge.production_work_order_planner import (
    BoundedProductionWorkOrderPlanner,
    DeterministicWorkOrderPlannerAdapter,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.simulation_service import SimulationService


class Phase47CSimulationPreparationOwnerTests(unittest.TestCase):
    @staticmethod
    def _simulation_catalogs():
        full = build_builtin_capability_catalog()
        simulation_phase32 = CapabilityCatalog.create(
            (full.capability("simulation.run"),),
            (full.adapter("originforge.simulation.deterministic"),),
        )
        return full, simulation_phase32, build_builtin_dispatch_catalog(simulation_phase32)

    @staticmethod
    def _proposal_json() -> str:
        return json.dumps(
            {
                "contract_id": "simulation.deterministic@1",
                "input_refs": [],
                "payload": {
                    "seed": 7,
                    "replicates": 2,
                    "max_steps": 5,
                    "stall_steps": 3,
                    "initial_state_json": '{"ore":0}',
                    "rules_json": '[{"consume":{},"priority":0,"probability_ppm":1000000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
                    "invariants_json": "[]",
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def test_registry_adds_simulation_owner_without_changing_code_owner_authority(self) -> None:
        registry = build_builtin_preparation_owner_registry()
        self.assertEqual(
            tuple(value.owner_id for value in registry.descriptors),
            (
                "originforge.preparation.simulation-work-order-planner@1",
                "originforge.preparation.work-order-planner@1",
            ),
        )

        full = build_builtin_capability_catalog()
        code_adapter = full.adapter("originforge.code.bounded-retry")
        code_contract = build_builtin_dispatch_catalog(full).contract_for_adapter(
            code_adapter.adapter_id
        )
        legacy_expected = ProductionPreparationOwnerDescriptor(
            owner_id="originforge.preparation.work-order-planner@1",
            owner_version="1",
            planner_request_version="1",
            planner_contract_id="BoundedProductionWorkOrderPlanner.propose@1",
            supported_adapter_id=code_adapter.adapter_id,
            supported_adapter_fingerprint=code_adapter.implementation_fingerprint,
            supported_dispatch_contract_id=code_contract.contract_id,
            supported_dispatch_contract_hash=code_contract.content_hash,
            model_strategy_roles=(ModelRole.CODER_STRONG,),
        )
        code_owner = registry.owner("originforge.preparation.work-order-planner@1")
        self.assertEqual(code_owner.to_dict(), legacy_expected.to_dict())
        self.assertEqual(code_owner.fingerprint, legacy_expected.fingerprint)

        _, simulation_phase32, simulation_dispatch = self._simulation_catalogs()
        simulation_adapter = simulation_phase32.adapter(
            "originforge.simulation.deterministic"
        )
        simulation_contract = simulation_dispatch.contract_for_adapter(
            simulation_adapter.adapter_id
        )
        simulation_owner = registry.owner(
            "originforge.preparation.simulation-work-order-planner@1"
        )
        self.assertEqual(simulation_owner.owner_version, "1")
        self.assertEqual(simulation_owner.planner_request_version, "1")
        self.assertEqual(
            simulation_owner.planner_contract_id,
            "BoundedProductionWorkOrderPlanner.propose@1",
        )
        self.assertEqual(
            simulation_owner.supported_adapter_id,
            "originforge.simulation.deterministic",
        )
        self.assertEqual(
            simulation_owner.supported_adapter_fingerprint,
            simulation_adapter.implementation_fingerprint,
        )
        self.assertEqual(
            simulation_owner.supported_dispatch_contract_id,
            "simulation.deterministic@1",
        )
        self.assertEqual(
            simulation_owner.supported_dispatch_contract_hash,
            simulation_contract.content_hash,
        )
        self.assertEqual(
            simulation_owner.model_strategy_roles,
            (ModelRole.CODER_STRONG,),
        )
        self.assertEqual(simulation_owner.policy_role_names, ("CODER_STRONG",))

    def test_simulation_only_preppol_resolution_and_multi_owner_catalog_fail_closed(self) -> None:
        full, simulation_phase32, simulation_dispatch = self._simulation_catalogs()
        owner = _matching_owner(simulation_dispatch)
        self.assertEqual(
            owner.owner_id,
            "originforge.preparation.simulation-work-order-planner@1",
        )

        policy = TaskPreparationPolicyBinding.create(
            project_id="PROJECT-00000000-0000-4000-8000-000000000001",
            materialization_id="PLMAT-00000000-0000-4000-8000-000000000002",
            materialization_hash="a" * 64,
            planning_input_id="PLINPUT-00000000-0000-4000-8000-000000000003",
            planning_input_hash="b" * 64,
            capability_catalog_id=simulation_phase32.catalog_id,
            capability_catalog_hash=simulation_phase32.content_hash,
            capability_routing_policy_id="CAPPOL-00000000-0000-4000-8000-000000000004",
            capability_routing_policy_hash="c" * 64,
            dispatch_contract_catalog_id=simulation_dispatch.dispatch_catalog_id,
            dispatch_contract_catalog_hash=simulation_dispatch.content_hash,
            preparation_owner_id=owner.owner_id,
            preparation_owner_fingerprint=owner.fingerprint,
            planner_request_version=owner.planner_request_version,
            planner_contract_id=owner.planner_contract_id,
            model_strategy_roles=owner.policy_role_names,
        )
        self.assertEqual(
            require_current_preparation_owner(policy, simulation_dispatch),
            owner,
        )
        with self.assertRaisesRegex(ProductionPreparationOwnerError, "not current"):
            require_current_preparation_owner(
                replace(policy, preparation_owner_fingerprint="0" * 64),
                simulation_dispatch,
            )

        code_dispatch = build_builtin_dispatch_catalog(full)
        combined = DispatchContractCatalog.create(
            full,
            (*code_dispatch.contracts, *simulation_dispatch.contracts),
        )
        with self.assertRaisesRegex(
            ProductionPreparationPolicyStoreError,
            "does not resolve one code-owned preparation owner",
        ):
            _matching_owner(combined)

    def test_simulation_work_order_planner_proposes_once_without_backend_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = OriginForgeRuntime(tempdir)
            runtime.initialize("phase47c-simulation-preparation")
            goal = runtime.create_goal("plan deterministic simulation evidence")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(
                flow,
                "simulate a bounded ore process",
                acceptance_criteria=("produce deterministic simulation evidence",),
                constraints=("no external inputs",),
                required_capabilities=("simulation.run",),
                priority=40,
            )
            full = build_builtin_capability_catalog()
            phase32 = CapabilityCatalog.create(
                (full.capability("simulation.run"),),
                (full.adapter("originforge.simulation.deterministic"),),
            )
            routing_policy = CapabilityRoutingPolicy.create(
                phase32,
                ordered_adapter_ids=("originforge.simulation.deterministic",),
                allowed_capability_ids=("simulation.run",),
            )
            capability_store = ProductionCapabilityStore(runtime)
            capability_store.publish_catalog(phase32)
            capability_store.publish_policy(routing_policy, phase32)
            route = capability_store.resolve_and_publish(
                task,
                phase32.catalog_id,
                routing_policy.routing_policy_id,
            )
            dispatch_catalog = build_builtin_dispatch_catalog(phase32)
            model = DeterministicWorkOrderPlannerAdapter(
                self._proposal_json(),
                input_tokens=12,
                output_tokens=8,
            )
            before = runtime.get_task(task)
            with patch.object(
                SimulationService,
                "execute",
                side_effect=AssertionError("simulation backend executed during preparation"),
            ):
                result = BoundedProductionWorkOrderPlanner(
                    runtime,
                    capability_store,
                    dispatch_catalog,
                    build_builtin_dispatch_validator_registry(),
                    model,
                ).propose(route.route_decision_id, allowed_input_refs=())

            self.assertEqual(model.call_count, 1)
            self.assertEqual(
                model.last_request.context["dispatch_contract"]["contract_id"],
                "simulation.deterministic@1",
            )
            self.assertEqual(model.last_request.context["allowed_input_refs"], [])
            self.assertEqual(
                result.work_order.selected_adapter_id,
                "originforge.simulation.deterministic",
            )
            self.assertEqual(
                result.work_order.dispatch_contract_id,
                "simulation.deterministic@1",
            )
            self.assertEqual(result.work_order.input_refs, ())
            self.assertEqual(result.work_order.payload["seed"], 7)
            after = runtime.get_task(task)
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(runtime.list_runs(task), [])


if __name__ == "__main__":
    unittest.main()
