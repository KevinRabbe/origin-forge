from __future__ import annotations

import json
import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_dispatch_binding_models import (
    BindingAuditStatus,
    DispatchBinderDescriptor,
    DispatchBinding,
    DispatchBindingAudit,
    DispatchBindingCurrentness,
    DispatchBindingCurrentnessStatus,
    DispatchBindingModelError,
)
from origin_forge.production_dispatch_resolution_models import (
    DispatchResolutionModelError,
    InputResolutionBundle,
    InputResolverDescriptor,
    ResolvedInputCurrentness,
    ResolvedWorkOrderInput,
    ResolverClaim,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType


H = {
    "a": "a" * 64,
    "b": "b" * 64,
    "c": "c" * 64,
    "d": "d" * 64,
    "e": "e" * 64,
    "f": "f" * 64,
}


class ProductionDispatchBindingModelTests(unittest.TestCase):
    def _ref(self, *, role: str = "source") -> WorkOrderInputRef:
        return WorkOrderInputRef(
            ref_type=WorkOrderRefType.ARTIFACT,
            ref_id=new_id(IdKind.ARTIFACT),
            content_hash=H["a"],
            role=role,
            revision=None,
        )

    def _resolved(self, *, role: str = "source") -> ResolvedWorkOrderInput:
        ref = self._ref(role=role)
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id="resolver.core.artifact@1",
            resolver_fingerprint=H["b"],
            source_object_type="ARTIFACT",
            resolution_class="CANONICAL_ARTIFACT",
            projection={"artifact_id": ref.ref_id, "content_hash": ref.content_hash},
        )

    def _bundle(
        self,
        resolved_inputs: tuple[ResolvedWorkOrderInput, ...],
    ) -> InputResolutionBundle:
        return InputResolutionBundle.create(
            work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
            work_order_hash=H["a"],
            work_order_audit_id=new_id(IdKind.WORK_ORDER_AUDIT),
            work_order_audit_hash=H["b"],
            task_id=new_id(IdKind.TASK),
            task_revision=3,
            task_content_hash=H["c"],
            route_decision_id=new_id(IdKind.CAPABILITY_ROUTE_DECISION),
            route_decision_hash=H["d"],
            selected_adapter_id="originforge.test.adapter",
            selected_adapter_fingerprint=H["e"],
            dispatch_catalog_id=new_id(IdKind.DISPATCH_CONTRACT_CATALOG),
            dispatch_catalog_hash=H["f"],
            dispatch_contract_id="test.contract@1",
            dispatch_contract_hash=H["a"],
            resolver_registry_fingerprint=H["b"],
            resolved_inputs=resolved_inputs,
        )

    def _binder(self, *, roles: tuple[str, ...] = ("source",)) -> DispatchBinderDescriptor:
        return DispatchBinderDescriptor(
            binder_id="binder.test.adapter@1",
            binder_fingerprint=H["c"],
            adapter_id="originforge.test.adapter",
            dispatch_contract_id="test.contract@1",
            request_type_id="TestRequest@1",
            request_schema_hash=H["d"],
            accepted_input_roles=roles,
        )

    def test_phase34_id_families_use_existing_opaque_id_contract(self) -> None:
        for kind in (
            IdKind.INPUT_RESOLUTION_BUNDLE,
            IdKind.DISPATCH_BINDING,
            IdKind.DISPATCH_BINDING_AUDIT,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))
            self.assertTrue(value.startswith(f"{kind.value}-"))

    def test_resolver_descriptor_is_order_normalized_and_content_addressed(self) -> None:
        first_claim = ResolverClaim(
            WorkOrderRefType.ARTIFACT,
            "ART-",
            "ARTIFACT",
            "source",
        )
        second_claim = ResolverClaim(
            WorkOrderRefType.VERIFICATION,
            "VERIFY-",
            "VERIFICATION",
            None,
        )
        one = InputResolverDescriptor(
            "resolver.core@1",
            H["a"],
            (second_claim, first_claim),
        )
        two = InputResolverDescriptor(
            "resolver.core@1",
            H["a"],
            (first_claim, second_claim),
        )
        self.assertEqual(one, two)
        self.assertEqual(one.content_hash, two.content_hash)
        self.assertEqual(one.claims[0], first_claim)

    def test_resolver_claims_reject_bad_prefix_duplicate_and_invalid_role(self) -> None:
        with self.assertRaises(DispatchResolutionModelError):
            ResolverClaim(WorkOrderRefType.ARTIFACT, "../", "ARTIFACT")
        with self.assertRaises(DispatchResolutionModelError):
            ResolverClaim(WorkOrderRefType.ARTIFACT, "ART-", "ARTIFACT", "bad role")
        claim = ResolverClaim(
            WorkOrderRefType.ARTIFACT,
            "ART-",
            "ARTIFACT",
            "source",
        )
        with self.assertRaisesRegex(DispatchResolutionModelError, "duplicate claims"):
            InputResolverDescriptor("resolver.core@1", H["a"], (claim, claim))

    def test_resolved_input_must_bind_exact_original_ref_hash_and_revision(self) -> None:
        ref = WorkOrderInputRef(
            WorkOrderRefType.PROJECT_ENTITY,
            new_id(IdKind.ENTITY),
            H["a"],
            "entity",
            4,
        )
        resolved = ResolvedWorkOrderInput.create(
            ref,
            resolver_id="resolver.entity@1",
            resolver_fingerprint=H["b"],
            source_object_type="PROJECT_ENTITY",
            resolution_class="CANONICAL_ENTITY",
            projection={"id": ref.ref_id, "revision": 4},
        )
        self.assertEqual(resolved.source_id, ref.ref_id)
        self.assertEqual(resolved.source_content_hash, ref.content_hash)
        self.assertEqual(resolved.source_revision, 4)
        with self.assertRaisesRegex(DispatchResolutionModelError, "source hash"):
            replace(resolved, source_content_hash=H["c"])
        with self.assertRaisesRegex(DispatchResolutionModelError, "source revision"):
            replace(resolved, source_revision=5)

    def test_projection_is_canonical_and_defensively_decoded(self) -> None:
        resolved = self._resolved()
        first = resolved.projection
        self.assertIsInstance(first, dict)
        assert isinstance(first, dict)
        first["artifact_id"] = "tampered"
        self.assertNotEqual(first, resolved.projection)
        self.assertEqual(
            resolved.projection_json,
            json.dumps(resolved.projection, separators=(",", ":"), sort_keys=True),
        )
        with self.assertRaisesRegex(DispatchResolutionModelError, "not canonical"):
            replace(resolved, projection_json='{"z":1,"a":2}')

    def test_bundle_sorts_inputs_and_rejects_duplicate_ref_identity(self) -> None:
        source = self._resolved(role="source")
        baseline = self._resolved(role="baseline")
        bundle = self._bundle((source, baseline))
        self.assertEqual(
            tuple(value.original_ref.role for value in bundle.resolved_inputs),
            ("baseline", "source"),
        )
        with self.assertRaisesRegex(DispatchResolutionModelError, "duplicate resolved refs"):
            self._bundle((source, source))

    def test_binder_descriptor_is_inert_order_normalized_contract_identity(self) -> None:
        one = self._binder(roles=("source", "baseline"))
        two = self._binder(roles=("baseline", "source"))
        self.assertEqual(one, two)
        self.assertEqual(one.content_hash, two.content_hash)
        self.assertNotIn("import", one.to_dict())
        self.assertNotIn("callable", one.to_dict())
        self.assertNotIn("executable", one.to_dict())

    def test_binding_requires_exact_adapter_contract_and_input_role_set(self) -> None:
        resolved = self._resolved()
        bundle = self._bundle((resolved,))
        binding = DispatchBinding.create(
            bundle,
            self._binder(),
            request_projection={"artifact": resolved.projection},
        )
        self.assertEqual(binding.work_order_id, bundle.work_order_id)
        self.assertEqual(binding.input_resolution_hash, bundle.content_hash)
        self.assertEqual(binding.request_projection["artifact"], resolved.projection)

        with self.assertRaisesRegex(DispatchBindingModelError, "adapter"):
            DispatchBinding.create(
                bundle,
                replace(self._binder(), adapter_id="originforge.other.adapter"),
                request_projection={},
            )
        with self.assertRaisesRegex(DispatchBindingModelError, "contract"):
            DispatchBinding.create(
                bundle,
                replace(self._binder(), dispatch_contract_id="other.contract@1"),
                request_projection={},
            )
        with self.assertRaisesRegex(DispatchBindingModelError, "input roles"):
            DispatchBinding.create(
                bundle,
                self._binder(roles=()),
                request_projection={},
            )

    def test_zero_ref_binding_is_valid_when_binder_requires_zero_roles(self) -> None:
        bundle = self._bundle(())
        binding = DispatchBinding.create(
            bundle,
            self._binder(roles=()),
            request_projection={"context_mode": "auto"},
        )
        self.assertTrue(validate_id(binding.dispatch_binding_id, IdKind.DISPATCH_BINDING))
        self.assertEqual(binding.request_projection, {"context_mode": "auto"})

    def test_pass_audit_binds_exact_binding_bundle_and_requires_request_hash(self) -> None:
        bundle = self._bundle(())
        binding = DispatchBinding.create(
            bundle,
            self._binder(roles=()),
            request_projection={"context_mode": "auto"},
        )
        audit = DispatchBindingAudit.pass_for(binding, bundle)
        self.assertEqual(audit.status, BindingAuditStatus.PASS)
        self.assertEqual(audit.dispatch_binding_hash, binding.content_hash)
        self.assertEqual(audit.input_resolution_hash, bundle.content_hash)
        self.assertEqual(audit.request_content_hash, binding.request_content_hash)
        with self.assertRaisesRegex(DispatchBindingModelError, "PASS binding audit"):
            replace(audit, request_content_hash=None)
        with self.assertRaisesRegex(DispatchBindingModelError, "FAIL binding audit"):
            replace(
                audit,
                status=BindingAuditStatus.FAIL,
                request_content_hash=None,
                failure_reason=None,
            )

    def test_currentness_is_typed_bounded_non_authoritative_evidence(self) -> None:
        bundle = self._bundle(())
        binding = DispatchBinding.create(
            bundle,
            self._binder(roles=()),
            request_projection={"context_mode": "auto"},
        )
        audit = DispatchBindingAudit.pass_for(binding, bundle)
        currentness = DispatchBindingCurrentness(
            binding.dispatch_binding_id,
            audit.binding_audit_id,
            binding.work_order_id,
            binding.task_id,
            DispatchBindingCurrentnessStatus.CURRENT_READY,
            None,
        )
        self.assertEqual(currentness.to_dict()["status"], "CURRENT_READY")
        with self.assertRaises(DispatchBindingModelError):
            replace(currentness, dispatch_binding_id=new_id(IdKind.PRODUCTION_WORK_ORDER))


if __name__ == "__main__":
    unittest.main()
