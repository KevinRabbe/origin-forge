from __future__ import annotations

import tempfile
import unittest

from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    TrustedProductionAdapter,
)
from origin_forge.production_capability_routing import (
    CapabilityRouteOutcome,
    CapabilityRouteReasonCode,
    CapabilityRoutingError,
    resolve_task_route,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.state import TaskStatus


_FINGERPRINT_A = "a" * 64
_FINGERPRINT_B = "b" * 64
_FINGERPRINT_C = "c" * 64


def _capability(capability_id: str, domain: CapabilityDomain) -> ProductionCapability:
    return ProductionCapability(
        capability_id=capability_id,
        name=capability_id,
        summary=f"governed {capability_id}",
        media_domain=domain,
        contract_version="1",
    )


def _adapter(
    adapter_id: str,
    capabilities: tuple[str, ...],
    fingerprint: str,
) -> TrustedProductionAdapter:
    return TrustedProductionAdapter(
        adapter_id=adapter_id,
        adapter_family=adapter_id.split(".")[0],
        adapter_version="1",
        implementation_fingerprint=fingerprint,
        capability_ids=capabilities,
        execution_effect=AdapterExecutionEffect.PROPOSAL_ONLY,
        replay_class=AdapterReplayClass.REVISION_BOUND,
    )


class ProductionCapabilityRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = OriginForgeRuntime(self.tempdir.name)
        self.runtime.initialize("capability-routing")
        self.goal = self.runtime.create_goal("route production work")
        self.flow = self.runtime.create_flow(self.goal)

        self.code = _capability("code.change", CapabilityDomain.CODE)
        self.observe = _capability("runtime.observe", CapabilityDomain.RUNTIME)
        self.image = _capability("image.generate", CapabilityDomain.IMAGE)
        self.code_only = _adapter(
            "code.bounded",
            ("code.change",),
            _FINGERPRINT_A,
        )
        self.code_observe = _adapter(
            "code.observed",
            ("code.change", "runtime.observe"),
            _FINGERPRINT_B,
        )
        self.image_adapter = _adapter(
            "image.generator",
            ("image.generate",),
            _FINGERPRINT_C,
        )
        self.catalog = CapabilityCatalog.create(
            (self.code, self.observe, self.image),
            (self.code_only, self.code_observe, self.image_adapter),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _task(self, capabilities: tuple[str, ...]) -> str:
        return self.runtime.create_task(
            self.flow,
            "perform governed production work",
            acceptance_criteria=("verified output",),
            constraints=("bounded",),
            required_capabilities=capabilities,
            priority=7,
        )

    def _policy(
        self,
        adapters: tuple[str, ...],
        capabilities: tuple[str, ...],
    ) -> CapabilityRoutingPolicy:
        return CapabilityRoutingPolicy.create(
            self.catalog,
            ordered_adapter_ids=adapters,
            allowed_capability_ids=capabilities,
        )

    def test_explicit_policy_order_controls_single_adapter_route(self) -> None:
        task = self._task(("code.change", "runtime.observe"))
        policy = self._policy(
            ("code.bounded", "code.observed"),
            ("code.change", "runtime.observe"),
        )
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(result.outcome, CapabilityRouteOutcome.ROUTABLE)
        self.assertEqual(result.selected_adapter_id, "code.observed")
        self.assertEqual(result.selected_adapter_fingerprint, _FINGERPRINT_B)
        self.assertEqual(
            result.considered_adapter_ids,
            ("code.bounded", "code.observed"),
        )
        self.assertEqual(len(result.reasons), 1)
        self.assertEqual(
            result.reasons[0].code,
            CapabilityRouteReasonCode.ADAPTER_MISSING_CAPABILITY,
        )
        self.assertEqual(result.reasons[0].capability_ids, ("runtime.observe",))

    def test_unlisted_catalog_adapter_never_becomes_implicit_fallback(self) -> None:
        task = self._task(("code.change", "runtime.observe"))
        policy = self._policy(
            ("code.bounded",),
            ("code.change", "runtime.observe"),
        )
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(result.outcome, CapabilityRouteOutcome.NO_ELIGIBLE_ADAPTER)
        self.assertIsNone(result.selected_adapter_id)
        self.assertEqual(result.considered_adapter_ids, ("code.bounded",))
        self.assertNotIn("code.observed", result.considered_adapter_ids)

    def test_unknown_capability_fails_before_adapter_consideration(self) -> None:
        task = self._task(("code.change", "physics.simulate"))
        policy = self._policy(
            ("code.observed",),
            ("code.change", "runtime.observe"),
        )
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(result.outcome, CapabilityRouteOutcome.UNKNOWN_CAPABILITY)
        self.assertEqual(result.considered_adapter_ids, ())
        self.assertEqual(result.reasons[0].subject_id, "physics.simulate")

    def test_policy_disallowed_capability_fails_before_adapter_consideration(self) -> None:
        task = self._task(("image.generate",))
        policy = self._policy(("image.generator",), ("code.change",))
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(
            result.outcome,
            CapabilityRouteOutcome.CAPABILITY_NOT_ALLOWED,
        )
        self.assertEqual(result.considered_adapter_ids, ())
        self.assertEqual(
            result.reasons[0].code,
            CapabilityRouteReasonCode.CAPABILITY_NOT_ALLOWED,
        )

    def test_two_partial_adapters_are_not_composed_into_one_task_route(self) -> None:
        task = self._task(("code.change", "image.generate"))
        policy = self._policy(
            ("code.bounded", "image.generator"),
            ("code.change", "image.generate"),
        )
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(result.outcome, CapabilityRouteOutcome.NO_ELIGIBLE_ADAPTER)
        self.assertEqual(
            result.considered_adapter_ids,
            ("code.bounded", "image.generator"),
        )
        self.assertEqual(len(result.reasons), 2)
        self.assertIsNone(result.selected_adapter_id)

    def test_task_without_required_capability_is_invalid_for_routing(self) -> None:
        task = self._task(())
        policy = self._policy(("code.bounded",), ("code.change",))
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(
            result.outcome,
            CapabilityRouteOutcome.INVALID_TASK_CONTRACT,
        )
        self.assertEqual(
            result.reasons[0].code,
            CapabilityRouteReasonCode.NO_REQUIRED_CAPABILITY,
        )

    def test_route_binds_exact_task_revision_and_content(self) -> None:
        task = self._task(("code.change",))
        policy = self._policy(("code.bounded",), ("code.change",))
        before = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(before.route_input.task_revision, 0)

        self.runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
        after = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        self.assertEqual(after.route_input.task_revision, 1)
        self.assertNotEqual(
            before.route_input.task_content_hash,
            after.route_input.task_content_hash,
        )
        self.assertNotEqual(before.content_hash, after.content_hash)

    def test_route_resolution_does_not_transition_task_or_start_run(self) -> None:
        task = self._task(("code.change",))
        policy = self._policy(("code.bounded",), ("code.change",))
        before = self.runtime.get_task(task)
        self.assertEqual(self.runtime.list_runs(task), [])
        result = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        after = self.runtime.get_task(task)
        self.assertEqual(result.outcome, CapabilityRouteOutcome.ROUTABLE)
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(self.runtime.list_runs(task), [])

    def test_corrupt_task_json_fails_closed(self) -> None:
        task = self._task(("code.change",))
        policy = self._policy(("code.bounded",), ("code.change",))
        with self.runtime.store.session() as conn:
            conn.execute(
                "UPDATE tasks SET required_capabilities_json = ? WHERE id = ?",
                ('{"not":"a-list"}', task),
            )
        with self.assertRaisesRegex(CapabilityRoutingError, "list bounds"):
            resolve_task_route(self.runtime.store, task, self.catalog, policy)

    def test_policy_catalog_drift_fails_closed_before_task_route(self) -> None:
        task = self._task(("code.change",))
        policy = self._policy(("code.bounded",), ("code.change",))
        changed_code = ProductionCapability(
            capability_id="code.change",
            name="code.change",
            summary="drifted code contract",
            media_domain=CapabilityDomain.CODE,
            contract_version="1",
        )
        changed_catalog = CapabilityCatalog(
            catalog_id=self.catalog.catalog_id,
            capabilities=(changed_code, self.observe, self.image),
            adapters=(self.code_only, self.code_observe, self.image_adapter),
        )
        with self.assertRaisesRegex(CapabilityRoutingError, "not valid"):
            resolve_task_route(self.runtime.store, task, changed_catalog, policy)

    def test_same_canonical_inputs_reconstruct_same_route_after_restart(self) -> None:
        task = self._task(("code.change", "runtime.observe"))
        policy = self._policy(
            ("code.bounded", "code.observed"),
            ("code.change", "runtime.observe"),
        )
        before = resolve_task_route(self.runtime.store, task, self.catalog, policy)
        restarted = OriginForgeRuntime(self.tempdir.name)
        after = resolve_task_route(restarted.store, task, self.catalog, policy)
        self.assertEqual(before.to_dict(), after.to_dict())
        self.assertEqual(before.content_hash, after.content_hash)


if __name__ == "__main__":
    unittest.main()
