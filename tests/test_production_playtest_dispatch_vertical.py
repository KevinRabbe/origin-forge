from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.playtest_models import (
    PlaytestAction,
    PlaytestActionKind,
    PlaytestScenario,
)
from origin_forge.playtest_service import PlaytestService
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_playtest_owner import (
    recover_playtest_dispatch_execution_once,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_playtest_dispatch_output_binding import (
    read_playtest_dispatch_output_binding,
)
from origin_forge.production_playtest_scenario_store import PlaytestScenarioStore
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observer import sha256_file
from tests.test_playtest_service import _FakePlaytestBackend


class PlaytestDispatchVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(Path(self.tempdir.name))
        self.runtime.initialize("playtest-dispatch-vertical")
        goal = self.runtime.create_goal("run a governed playtest")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow, "run the bounded cooperative scenario", required_capabilities=("runtime.playtest",)
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        executable = Path(sys.executable).resolve(strict=True)
        self.executable_hash = sha256_file(executable)
        self.executable = executable
        self.scenario = PlaytestScenario.create(
            harness_id="fixture-harness",
            harness_version="1",
            harness_hash=self.executable_hash,
            target_id="fixture-game",
            target_version="1",
            allowed_controls=("move-x", "attack"),
            actions=(
                PlaytestAction(0, 0, PlaytestActionKind.SET_AXIS, "move-x", 1000),
                PlaytestAction(1, 100, PlaytestActionKind.PRESS, "attack", None, 50),
            ),
            max_duration_ms=5000,
            max_log_bytes=4096,
            progression_stall_threshold_ms=500,
        )
        PlaytestScenarioStore(self.runtime).put(self.scenario)

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("runtime.playtest"),),
            (full.adapter("originforge.playtest.cooperative"),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.playtest.cooperative",),
            allowed_capability_ids=("runtime.playtest",),
        )
        self.cap_store = ProductionCapabilityStore(self.runtime)
        self.cap_store.publish_catalog(catalog)
        self.cap_store.publish_policy(policy, catalog)
        route = self.cap_store.resolve_and_publish(
            self.task_id, catalog.catalog_id, policy.routing_policy_id
        )
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, self.cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        input_ref = WorkOrderInputRef(
            ref_type=WorkOrderRefType.PLAYTEST_SCENARIO,
            ref_id=self.scenario.scenario_id,
            content_hash=self.scenario.content_hash.removeprefix("sha256:"),
            role="playtest_scenario",
        )
        work_order = create_current_work_order(
            self.runtime,
            self.cap_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            input_refs=(input_ref,),
            payload={"operation": "PLAYTEST"},
        )
        work_audit = audit_work_order_frozen(
            self.cap_store, dispatch_catalog, validators, work_order
        )
        self.assertEqual(work_audit.status.value, "PASS", work_audit.to_dict())
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(work_audit)
        resolvers = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(
            wo_store, resolvers, work_order.work_order_id, work_audit.work_order_audit_id
        )
        binding = create_dispatch_binding(wo_store, resolvers, binders, bundle)
        self.binding = binding
        binding_audit = audit_dispatch_binding_frozen(
            wo_store, resolvers, binders, bundle, binding
        )
        dispatch_store = ProductionDispatchStore(wo_store, resolvers, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(
            self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_dispatch_publishes_binding_and_recovery_does_not_replay(self) -> None:
        old_value = os.environ.get("ORIGIN_FORGE_PLAYTEST_EXECUTABLE")
        os.environ["ORIGIN_FORGE_PLAYTEST_EXECUTABLE"] = str(self.executable)
        calls = 0

        def execute(task_id, scenario):
            nonlocal calls
            calls += 1
            return PlaytestService(
                self.runtime, _FakePlaytestBackend(self.runtime)
            ).execute(task_id, scenario)

        try:
            with patch(
                "origin_forge.production_dispatch_invocation_playtest_owner.PlaytestService",
                side_effect=lambda runtime, harness: SimpleNamespace(execute=execute),
            ):
                completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
                self.assertEqual(calls, 1)
                binding = read_playtest_dispatch_output_binding(
                    self.runtime, completed.execution.execution_id
                )
                self.assertEqual(binding.task_id, self.task_id)
                self.assertTrue(binding.scenario_artifact_id.startswith("ART-"))
                recovered = recover_playtest_dispatch_execution_once(
                    self.runtime, completed.execution.execution_id
                )
            self.assertEqual(calls, 1)
            self.assertEqual(recovered.playtest_result, completed.playtest_result)
            self.assertEqual(recovered.execution.status.value, "RETURNED")
        finally:
            if old_value is None:
                os.environ.pop("ORIGIN_FORGE_PLAYTEST_EXECUTABLE", None)
            else:
                os.environ["ORIGIN_FORGE_PLAYTEST_EXECUTABLE"] = old_value

    def test_recovery_rejects_tampered_summary_evidence(self) -> None:
        old_value = os.environ.get("ORIGIN_FORGE_PLAYTEST_EXECUTABLE")
        os.environ["ORIGIN_FORGE_PLAYTEST_EXECUTABLE"] = str(self.executable)
        try:
            with patch(
                "origin_forge.production_dispatch_invocation_playtest_owner.PlaytestService",
                side_effect=lambda runtime, harness: SimpleNamespace(
                    execute=lambda task_id, scenario: PlaytestService(
                        self.runtime, _FakePlaytestBackend(self.runtime)
                    ).execute(task_id, scenario)
                ),
            ):
                completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
            binding = read_playtest_dispatch_output_binding(
                self.runtime, completed.execution.execution_id
            )
            summary_path = OriginForgeLineage(self.runtime).local_artifact_path(
                binding.summary_artifact_id
            )
            summary_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired):
                recover_playtest_dispatch_execution_once(
                    self.runtime, completed.execution.execution_id
                )
        finally:
            if old_value is None:
                os.environ.pop("ORIGIN_FORGE_PLAYTEST_EXECUTABLE", None)
            else:
                os.environ["ORIGIN_FORGE_PLAYTEST_EXECUTABLE"] = old_value


if __name__ == "__main__":
    unittest.main()
