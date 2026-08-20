from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.blockbench_models import BlockbenchProjectSpec, CuboidSpec, Vec3
from origin_forge.ids import IdKind, new_id
from origin_forge.model3d_requests import (
    Model3DProductionRequest,
    Model3DRequestReader,
    Model3DRequestStore,
)
from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_planning_models import PlanningEvidenceRef, PlanningInput
from origin_forge.production_preparation_input_authority import (
    PreparationInputAuthorityError,
    planner_allowed_input_refs,
    work_order_input_refs_within_authority,
)
from origin_forge.production_preparation_owner import (
    build_builtin_preparation_owner_registry,
    require_current_preparation_owner,
)
from origin_forge.production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    _matching_owner,
)
from origin_forge.production_preparation_models import TaskPreparationPolicyBinding
from origin_forge.production_goal_bootstrap_authority import build_builtin_goal_bootstrap_owner
from origin_forge.production_work_order_builtin import build_builtin_dispatch_catalog
from origin_forge.production_work_order_models import (
    DispatchContractCatalog,
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_planner import (
    ProductionWorkOrderPlannerError,
    parse_work_order_proposal,
)
from origin_forge.runtime import OriginForgeRuntime


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64


class Phase51CBlenderPreparationOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase51c-blender-preparation")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _project(name: str) -> BlockbenchProjectSpec:
        return BlockbenchProjectSpec(
            project_name=name,
            bones=(),
            cuboids=(
                CuboidSpec(
                    element_id="body",
                    name="Body",
                    from_point=Vec3(0, 0, 0),
                    to_point=Vec3(2, 3, 4),
                    origin=Vec3(0, 0, 0),
                    rotation=Vec3(0, 0, 0),
                ),
            ),
        )

    def _stored_request(self, name: str) -> Model3DProductionRequest:
        request = Model3DProductionRequest.create(project=self._project(name))
        Model3DRequestStore(self.runtime).put(request)
        return request

    @staticmethod
    def _blender_catalogs():
        full = build_builtin_capability_catalog()
        phase32 = CapabilityCatalog.create(
            (full.capability("media.3d.blender"),),
            (full.adapter("originforge.blender.model3d"),),
        )
        return full, phase32, build_builtin_dispatch_catalog(phase32)

    @staticmethod
    def _planning_input(*refs: PlanningEvidenceRef) -> PlanningInput:
        return PlanningInput.create(
            project_id=new_id(IdKind.PROJECT),
            goal_id=new_id(IdKind.GOAL),
            goal_revision=0,
            goal_content_hash=_HASH_A,
            verified_state_refs=refs,
            active_design_rule_refs=(),
            project_intelligence_hash=_HASH_B,
            capability_catalog_hash=_HASH_C,
            capability_ids=("media.3d.blender",),
            model_policy_hash=_HASH_D,
            resource_policy_hash=_HASH_E,
        )

    def test_registry_adds_exact_blender_owner_without_runtime_authority(self) -> None:
        registry = build_builtin_preparation_owner_registry()
        self.assertEqual(
            tuple(owner.owner_id for owner in registry.descriptors),
            (
                "originforge.preparation.blender-export-glb@1",
                "originforge.preparation.pixelorama-spritesheet-export-planner@1",
                "originforge.preparation.simulation-work-order-planner@1",
                "originforge.preparation.work-order-planner@1",
            ),
        )
        owner = registry.owner("originforge.preparation.blender-export-glb@1")
        self.assertEqual(owner.owner_version, "1")
        self.assertEqual(owner.planner_request_version, "1")
        self.assertEqual(
            owner.planner_contract_id,
            "BoundedProductionWorkOrderPlanner.propose@1",
        )
        self.assertEqual(owner.supported_adapter_id, "originforge.blender.model3d")
        self.assertEqual(owner.supported_dispatch_contract_id, "blender.export-glb@1")
        self.assertEqual(owner.model_strategy_roles, (ModelRole.CODER_STRONG,))
        forbidden = {
            "operation_id",
            "workspace_id",
            "path",
            "profile",
            "runtime",
            "executable",
            "runner",
            "process",
            "argv",
            "environment",
        }
        self.assertTrue(forbidden.isdisjoint(owner.to_dict()))

    def test_blender_only_preppol_owner_is_current_and_mixed_owner_fails_closed(self) -> None:
        full, phase32, dispatch = self._blender_catalogs()
        owner = _matching_owner(dispatch)
        self.assertEqual(owner.owner_id, "originforge.preparation.blender-export-glb@1")
        policy = TaskPreparationPolicyBinding.create(
            project_id="PROJECT-00000000-0000-4000-8000-000000000001",
            materialization_id="PLMAT-00000000-0000-4000-8000-000000000002",
            materialization_hash=_HASH_A,
            planning_input_id="PLINPUT-00000000-0000-4000-8000-000000000003",
            planning_input_hash=_HASH_B,
            capability_catalog_id=phase32.catalog_id,
            capability_catalog_hash=phase32.content_hash,
            capability_routing_policy_id="CAPPOL-00000000-0000-4000-8000-000000000004",
            capability_routing_policy_hash=_HASH_C,
            dispatch_contract_catalog_id=dispatch.dispatch_catalog_id,
            dispatch_contract_catalog_hash=dispatch.content_hash,
            preparation_owner_id=owner.owner_id,
            preparation_owner_fingerprint=owner.fingerprint,
            planner_request_version=owner.planner_request_version,
            planner_contract_id=owner.planner_contract_id,
            model_strategy_roles=owner.policy_role_names,
        )
        self.assertEqual(require_current_preparation_owner(policy, dispatch), owner)

        pixelorama_phase32 = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter("originforge.pixelorama.export"),),
        )
        pixelorama_dispatch = build_builtin_dispatch_catalog(pixelorama_phase32)
        mixed_phase32 = CapabilityCatalog.create(
            (full.capability("media.2d.export"), full.capability("media.3d.blender")),
            (
                full.adapter("originforge.pixelorama.export"),
                full.adapter("originforge.blender.model3d"),
            ),
        )
        mixed_dispatch = DispatchContractCatalog.create(
            mixed_phase32,
            (*pixelorama_dispatch.contracts, *dispatch.contracts),
        )
        with self.assertRaisesRegex(
            ProductionPreparationPolicyStoreError,
            "does not resolve one code-owned preparation owner",
        ):
            _matching_owner(mixed_dispatch)

        goal_owner = build_builtin_goal_bootstrap_owner()
        self.assertEqual(
            (
                goal_owner.supported_capability_id,
                goal_owner.supported_adapter_id,
                goal_owner.supported_dispatch_contract_id,
                goal_owner.preparation_owner_id,
            ),
            (
                "code.change",
                "originforge.code.bounded-retry",
                "code.bounded-retry@1",
                "originforge.preparation.work-order-planner@1",
            ),
        )

    def test_only_frozen_model3d_requests_enter_planner_allow_list(self) -> None:
        first = self._stored_request("crate-a")
        second = self._stored_request("crate-b")
        _, _, dispatch = self._blender_catalogs()
        owner = _matching_owner(dispatch)
        contract = dispatch.contract_for_adapter(owner.supported_adapter_id)
        planning_input = self._planning_input(
            PlanningEvidenceRef(
                ref_id=first.request_id,
                content_hash=first.request_hash.removeprefix("sha256:"),
                revision=None,
            ),
            PlanningEvidenceRef(
                ref_id=new_id(IdKind.ARTIFACT),
                content_hash=_HASH_E,
                revision=None,
            ),
            PlanningEvidenceRef(
                ref_id=second.request_id,
                content_hash=second.request_hash.removeprefix("sha256:"),
                revision=1,
            ),
        )
        allowed = planner_allowed_input_refs(planning_input, owner.owner_id, contract)
        self.assertEqual(
            allowed,
            (
                WorkOrderInputRef(
                    WorkOrderRefType.MODEL3D_REQUEST,
                    first.request_id,
                    first.request_hash.removeprefix("sha256:"),
                    "model3d_request",
                    None,
                ),
            ),
        )
        self.assertEqual(
            Model3DRequestReader(self.runtime).get(
                allowed[0].ref_id,
                f"sha256:{allowed[0].content_hash}",
            ),
            first,
        )
        self.assertNotEqual(second.request_id, allowed[0].ref_id)

        empty = self._planning_input(
            PlanningEvidenceRef(
                ref_id=new_id(IdKind.ARTIFACT),
                content_hash=_HASH_A,
                revision=None,
            )
        )
        with self.assertRaisesRegex(
            PreparationInputAuthorityError,
            "requires frozen MODEL3D request evidence",
        ):
            planner_allowed_input_refs(empty, owner.owner_id, contract)

    def test_returned_ref_must_be_exact_member_of_frozen_authority(self) -> None:
        request = self._stored_request("crate")
        _, _, dispatch = self._blender_catalogs()
        owner = _matching_owner(dispatch)
        contract = dispatch.contract_for_adapter(owner.supported_adapter_id)
        planning_input = self._planning_input(
            PlanningEvidenceRef(
                request.request_id,
                request.request_hash.removeprefix("sha256:"),
                None,
            )
        )
        allowed = planner_allowed_input_refs(planning_input, owner.owner_id, contract)
        self.assertTrue(
            work_order_input_refs_within_authority(
                allowed,
                planning_input=planning_input,
                owner_id=owner.owner_id,
                contract=contract,
            )
        )
        for forged in (
            WorkOrderInputRef(
                WorkOrderRefType.MODEL3D_REQUEST,
                request.request_id,
                "9" * 64,
                "model3d_request",
                None,
            ),
            WorkOrderInputRef(
                WorkOrderRefType.MODEL3D_REQUEST,
                request.request_id,
                request.request_hash.removeprefix("sha256:"),
                "source",
                None,
            ),
            WorkOrderInputRef(
                WorkOrderRefType.MODEL3D_REQUEST,
                request.request_id,
                request.request_hash.removeprefix("sha256:"),
                "model3d_request",
                1,
            ),
        ):
            self.assertFalse(
                work_order_input_refs_within_authority(
                    (forged,),
                    planning_input=planning_input,
                    owner_id=owner.owner_id,
                    contract=contract,
                )
            )

    def test_model_can_select_only_the_infrastructure_supplied_request_ref(self) -> None:
        request = self._stored_request("crate")
        _, _, dispatch = self._blender_catalogs()
        owner = _matching_owner(dispatch)
        contract = dispatch.contract_for_adapter(owner.supported_adapter_id)
        planning_input = self._planning_input(
            PlanningEvidenceRef(
                request.request_id,
                request.request_hash.removeprefix("sha256:"),
                None,
            )
        )
        allowed = planner_allowed_input_refs(planning_input, owner.owner_id, contract)
        proposal = parse_work_order_proposal(
            json.dumps(
                {
                    "contract_id": "blender.export-glb@1",
                    "input_refs": [allowed[0].to_dict()],
                    "payload": {},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            contract=contract,
            allowed_input_refs=allowed,
        )
        self.assertEqual(proposal.input_refs, allowed)
        self.assertEqual(proposal.payload, {})

        forged = allowed[0].to_dict()
        forged["content_hash"] = "8" * 64
        with self.assertRaisesRegex(
            ProductionWorkOrderPlannerError,
            "outside the infrastructure allow-list",
        ):
            parse_work_order_proposal(
                json.dumps(
                    {
                        "contract_id": "blender.export-glb@1",
                        "input_refs": [forged],
                        "payload": {},
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                contract=contract,
                allowed_input_refs=allowed,
            )


if __name__ == "__main__":
    unittest.main()
