from __future__ import annotations
import unittest
from dataclasses import replace
from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_goal_bootstrap_authority import build_builtin_goal_bootstrap_owner
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_preparation_owner import ProductionPreparationOwnerError, build_builtin_preparation_owner_registry, require_current_preparation_owner
from origin_forge.production_preparation_policy_store import ProductionPreparationPolicyStoreError, _matching_owner
from origin_forge.production_work_order_builtin import build_builtin_dispatch_catalog
from origin_forge.production_work_order_models import DispatchContractCatalog

class Phase48CPixeloramaPreparationOwnerTests(unittest.TestCase):
    def catalogs(self):
        full=build_builtin_capability_catalog()
        p32=CapabilityCatalog.create((full.capability("media.2d.export"),),(full.adapter("originforge.pixelorama.export"),))
        return full,p32,build_builtin_dispatch_catalog(p32)

    def test_exact_owner_and_currentness(self):
        full,p32,dispatch=self.catalogs(); registry=build_builtin_preparation_owner_registry()
        self.assertEqual(tuple(x.owner_id for x in registry.descriptors),(
            "originforge.preparation.pixelorama-spritesheet-export-planner@1",
            "originforge.preparation.simulation-work-order-planner@1",
            "originforge.preparation.work-order-planner@1"))
        owner=_matching_owner(dispatch)
        self.assertEqual(owner.owner_id,"originforge.preparation.pixelorama-spritesheet-export-planner@1")
        self.assertEqual(owner.supported_adapter_id,"originforge.pixelorama.export")
        self.assertEqual(owner.supported_dispatch_contract_id,"pixelorama.spritesheet-export@1")
        self.assertEqual(owner.model_strategy_roles,(ModelRole.CODER_STRONG,))
        policy=TaskPreparationPolicyBinding.create(project_id="PROJECT-00000000-0000-4000-8000-000000000001",materialization_id="PLMAT-00000000-0000-4000-8000-000000000002",materialization_hash="a"*64,planning_input_id="PLINPUT-00000000-0000-4000-8000-000000000003",planning_input_hash="b"*64,capability_catalog_id=p32.catalog_id,capability_catalog_hash=p32.content_hash,capability_routing_policy_id="CAPPOL-00000000-0000-4000-8000-000000000004",capability_routing_policy_hash="c"*64,dispatch_contract_catalog_id=dispatch.dispatch_catalog_id,dispatch_contract_catalog_hash=dispatch.content_hash,preparation_owner_id=owner.owner_id,preparation_owner_fingerprint=owner.fingerprint,planner_request_version=owner.planner_request_version,planner_contract_id=owner.planner_contract_id,model_strategy_roles=owner.policy_role_names)
        self.assertEqual(require_current_preparation_owner(policy,dispatch),owner)
        with self.assertRaisesRegex(ProductionPreparationOwnerError,"not current"):
            require_current_preparation_owner(replace(policy,preparation_owner_fingerprint="0"*64),dispatch)

    def test_mixed_owner_fails_closed_and_goal_bootstrap_stays_code_only(self):
        full,p32,pdisp=self.catalogs()
        s32=CapabilityCatalog.create((full.capability("simulation.run"),),(full.adapter("originforge.simulation.deterministic"),)); sdisp=build_builtin_dispatch_catalog(s32)
        mixed32=CapabilityCatalog.create((full.capability("media.2d.export"),full.capability("simulation.run")),(full.adapter("originforge.pixelorama.export"),full.adapter("originforge.simulation.deterministic")))
        mixed=DispatchContractCatalog.create(mixed32,(*pdisp.contracts,*sdisp.contracts))
        with self.assertRaisesRegex(ProductionPreparationPolicyStoreError,"does not resolve one code-owned preparation owner"):
            _matching_owner(mixed)
        goal=build_builtin_goal_bootstrap_owner()
        self.assertEqual((goal.supported_capability_id,goal.supported_adapter_id,goal.supported_dispatch_contract_id,goal.preparation_owner_id),("code.change","originforge.code.bounded-retry","code.bounded-retry@1","originforge.preparation.work-order-planner@1"))

if __name__ == "__main__": unittest.main()
