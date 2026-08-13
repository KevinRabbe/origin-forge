from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_manager_advance_inventory as inventory_module
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_manager_advance_inventory import (
    ManagerAdvanceInventoryStatus,
    inspect_preparation_policy_inventory_readonly,
    inspect_preparation_receipt_inventory_readonly,
)
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import PlanProposal, PlanStep, audit_plan
from origin_forge.production_preparation_admission import (
    PreparationAdmissionStatus,
    inspect_materialization_preparation_eligibility_readonly,
)
from origin_forge.production_preparation_models import PreparationStage, PreparationStatus
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_preparation_receipts import acquire_preparation_receipt
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class ManagerAdvanceInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase40a-inventory")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _scenario(self):
        goal = self.runtime.create_goal("inventory one governed preparation policy")
        catalog = build_builtin_capability_catalog()
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.code.bounded-retry",),
            allowed_capability_ids=("code.change",),
        )
        capability_store = ProductionCapabilityStore(self.runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        planning_input = freeze_governed_planning_input(
            self.runtime,
            goal,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Materialize one code Task.",
            steps=(
                PlanStep(
                    step_key="code",
                    objective="Implement a bounded change.",
                    acceptance_criteria=("Tests pass.",),
                    required_capabilities=("code.change",),
                ),
            ),
        )
        plan_audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(self.runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(plan_audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_orders = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        work_orders.publish_dispatch_catalog(dispatch_catalog)
        policy = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(self.runtime, policy)
        return policy, materialization

    def _acquire_receipt(self):
        policy, materialization = self._scenario()
        admission = inspect_materialization_preparation_eligibility_readonly(
            self.runtime,
            policy,
        )
        self.assertEqual(admission.status, PreparationAdmissionStatus.COMPLETE)
        self.assertEqual(admission.candidate_count, 1)
        receipt = acquire_preparation_receipt(
            self.runtime,
            policy,
            admission.candidates[0],
        )
        return policy, materialization, receipt

    def _db_signature(self):
        database = self.runtime.store.db_path
        stat = database.stat()
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            tuple(
                (suffix, Path(str(database) + suffix).exists())
                for suffix in ("-wal", "-shm", "-journal")
            ),
        )

    def test_missing_policy_store_is_empty_and_not_created(self) -> None:
        parent = self.runtime.state_dir / "production-preparation"
        self.assertFalse(parent.exists())

        inventory = inspect_preparation_policy_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.COMPLETE)
        self.assertEqual(inventory.policies, ())
        self.assertEqual(inventory.scanned_count, 0)
        self.assertFalse(parent.exists())

    def test_policy_inventory_reloads_all_valid_policies_in_id_order(self) -> None:
        first, materialization = self._scenario()
        second = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=first.capability_catalog_id,
            capability_routing_policy_id=first.capability_routing_policy_id,
            dispatch_contract_catalog_id=first.dispatch_contract_catalog_id,
        )
        publish_preparation_policy(self.runtime, second)

        inventory = inspect_preparation_policy_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.COMPLETE)
        self.assertEqual(inventory.policy_count, 2)
        self.assertEqual(
            tuple(policy.preparation_policy_id for policy in inventory.policies),
            tuple(sorted((first.preparation_policy_id, second.preparation_policy_id))),
        )
        self.assertEqual(inventory.scanned_count, 2)

    def test_malformed_policy_entry_fails_closed_without_partial_inventory(self) -> None:
        self._scenario()
        policy_root = self.runtime.state_dir / "production-preparation" / "policies"
        policy_root.joinpath("unexpected.txt").write_text("not governed evidence", encoding="utf-8")

        inventory = inspect_preparation_policy_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.INVALID_STATE)
        self.assertEqual(inventory.policies, ())
        self.assertGreaterEqual(inventory.scanned_count, 1)

    def test_policy_inventory_limit_fails_closed_without_partial_inventory(self) -> None:
        first, materialization = self._scenario()
        second = create_preparation_policy_binding(
            self.runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=first.capability_catalog_id,
            capability_routing_policy_id=first.capability_routing_policy_id,
            dispatch_contract_catalog_id=first.dispatch_contract_catalog_id,
        )
        publish_preparation_policy(self.runtime, second)

        with patch.object(inventory_module, "_MAX_PREPARATION_POLICIES", 1):
            inventory = inspect_preparation_policy_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.LIMIT_EXCEEDED)
        self.assertEqual(inventory.policies, ())
        self.assertEqual(inventory.scanned_count, 2)

    def test_receipt_inventory_reads_typed_lifecycle_without_sqlite_mutation(self) -> None:
        _, _, receipt = self._acquire_receipt()
        before = self._db_signature()

        inventory = inspect_preparation_receipt_inventory_readonly(self.runtime)
        after = self._db_signature()

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.COMPLETE)
        self.assertEqual(inventory.receipt_count, 1)
        self.assertEqual(inventory.scanned_count, 1)
        entry = inventory.entries[0]
        self.assertEqual(entry.preparation_id, receipt.preparation_id)
        self.assertEqual(entry.task_id, receipt.task_id)
        self.assertEqual(entry.receipt.stage, PreparationStage.CLAIMED)
        self.assertEqual(entry.receipt.status, PreparationStatus.ACTIVE)
        self.assertEqual(entry.current_task_status, TaskStatus.QUEUED)
        self.assertEqual(entry.current_task_revision, receipt.queued_task_revision)
        self.assertEqual(entry.task_order_key, (entry.task_created_at, receipt.task_id))
        self.assertEqual(after, before)

    def test_invalid_receipt_lifecycle_fails_closed_without_partial_inventory(self) -> None:
        _, _, receipt = self._acquire_receipt()
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE task_preparations SET stage = 'BOUND' WHERE preparation_id = ?",
                (receipt.preparation_id,),
            )

        inventory = inspect_preparation_receipt_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.INVALID_STATE)
        self.assertEqual(inventory.entries, ())

    def test_receipt_inventory_limit_fails_closed_without_partial_inventory(self) -> None:
        self._acquire_receipt()
        with patch.object(inventory_module, "_MAX_PREPARATION_RECEIPTS", 0):
            inventory = inspect_preparation_receipt_inventory_readonly(self.runtime)

        self.assertEqual(inventory.status, ManagerAdvanceInventoryStatus.LIMIT_EXCEEDED)
        self.assertEqual(inventory.entries, ())
        self.assertEqual(inventory.scanned_count, 1)

    def test_inventory_source_has_no_selection_or_mutation_authority(self) -> None:
        source = Path(inventory_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_modules = {
            "production_manager_dispatch_tick",
            "production_preparation_tick",
            "production_preparation_receipts",
            "production_preparation_work_order_finalize",
            "production_preparation_phase34_finalize",
            "production_task_activation",
            "scheduled_model_adapter",
        }
        forbidden_calls = {
            "session",
            "publish_preparation_policy",
            "acquire_preparation_receipt",
            "activate_dependency_ready_task",
            "prepare_materialization_tick",
            "finalize_preparation_work_order_audit",
            "finalize_preparation_phase34",
            "dispatch_manager_tick",
            "acquire_dispatch_claim",
            "dispatch_claim_once",
            "generate",
            "propose",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                self.assertNotIn(node.module.rsplit(".", 1)[-1], forbidden_modules)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                else:
                    continue
                self.assertNotIn(call_name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
