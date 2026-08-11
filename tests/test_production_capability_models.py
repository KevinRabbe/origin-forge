from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    ProductionCapabilityError,
    TrustedProductionAdapter,
)


_FINGERPRINT_A = "a" * 64
_FINGERPRINT_B = "b" * 64


def _capability(
    capability_id: str,
    *,
    domain: CapabilityDomain = CapabilityDomain.GENERAL,
    summary: str = "governed capability",
) -> ProductionCapability:
    return ProductionCapability(
        capability_id=capability_id,
        name=capability_id.replace(".", " ").title(),
        summary=summary,
        media_domain=domain,
        contract_version="1",
    )


def _adapter(
    adapter_id: str,
    capabilities: tuple[str, ...],
    *,
    fingerprint: str = _FINGERPRINT_A,
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


class ProductionCapabilityModelTests(unittest.TestCase):
    def test_phase32_id_families_are_infrastructure_owned_ids(self) -> None:
        for kind in (
            IdKind.CAPABILITY_CATALOG,
            IdKind.CAPABILITY_ROUTING_POLICY,
            IdKind.CAPABILITY_ROUTE_DECISION,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))
        self.assertFalse(
            validate_id("CAPCAT-model-chosen", IdKind.CAPABILITY_CATALOG)
        )

    def test_capability_is_bounded_and_content_addressed(self) -> None:
        capability = _capability("code.change", domain=CapabilityDomain.CODE)
        self.assertEqual(capability.capability_id, "code.change")
        self.assertEqual(len(capability.content_hash), 64)
        changed = _capability(
            "code.change",
            domain=CapabilityDomain.CODE,
            summary="different governed contract",
        )
        self.assertNotEqual(capability.content_hash, changed.content_hash)

        with self.assertRaises(ProductionCapabilityError):
            _capability("Code Change")
        with self.assertRaises(ProductionCapabilityError):
            ProductionCapability(
                capability_id="code.change",
                name="x",
                summary="y" * 2049,
                media_domain=CapabilityDomain.CODE,
                contract_version="1",
            )

    def test_adapter_descriptor_contains_no_executable_payload_surface(self) -> None:
        adapter = _adapter(
            "code.bounded",
            ("runtime.observe", "code.change"),
        )
        self.assertEqual(
            adapter.capability_ids,
            ("code.change", "runtime.observe"),
        )
        self.assertEqual(
            set(adapter.to_dict()),
            {
                "adapter_id",
                "adapter_family",
                "adapter_version",
                "implementation_fingerprint",
                "capability_ids",
                "execution_effect",
                "replay_class",
            },
        )
        for forbidden in (
            "argv",
            "shell",
            "command",
            "callable",
            "import_path",
            "environment",
            "container_image",
            "url",
            "secret",
        ):
            self.assertNotIn(forbidden, adapter.to_dict())

        with self.assertRaises(ProductionCapabilityError):
            _adapter("code.bounded", ("code.change", "code.change"))
        with self.assertRaises(ProductionCapabilityError):
            TrustedProductionAdapter(
                adapter_id="code.bounded",
                adapter_family="code",
                adapter_version="1",
                implementation_fingerprint="not-a-digest",
                capability_ids=("code.change",),
                execution_effect=AdapterExecutionEffect.PROPOSAL_ONLY,
                replay_class=AdapterReplayClass.REVISION_BOUND,
            )

    def test_catalog_is_deterministic_for_one_infrastructure_identity(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        observe = _capability("runtime.observe", domain=CapabilityDomain.RUNTIME)
        first = _adapter("code.bounded", ("code.change",))
        second = _adapter(
            "runtime.observer",
            ("runtime.observe",),
            fingerprint=_FINGERPRINT_B,
        )
        catalog_id = new_id(IdKind.CAPABILITY_CATALOG)
        catalog_a = CapabilityCatalog(
            catalog_id,
            (observe, code),
            (second, first),
        )
        catalog_b = CapabilityCatalog(
            catalog_id,
            (code, observe),
            (first, second),
        )
        self.assertEqual(catalog_a.capability_ids, ("code.change", "runtime.observe"))
        self.assertEqual(catalog_a.adapter_ids, ("code.bounded", "runtime.observer"))
        self.assertEqual(catalog_a.to_dict(), catalog_b.to_dict())
        self.assertEqual(catalog_a.content_hash, catalog_b.content_hash)

    def test_catalog_rejects_duplicate_and_unknown_references(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        with self.assertRaisesRegex(ProductionCapabilityError, "duplicate capability"):
            CapabilityCatalog.create((code, code))
        adapter = _adapter("image.generator", ("image.generate",))
        with self.assertRaisesRegex(ProductionCapabilityError, "unknown capabilities"):
            CapabilityCatalog.create((code,), (adapter,))
        adapter_a = _adapter("code.bounded", ("code.change",))
        adapter_b = _adapter(
            "code.bounded",
            ("code.change",),
            fingerprint=_FINGERPRINT_B,
        )
        with self.assertRaisesRegex(ProductionCapabilityError, "duplicate adapter"):
            CapabilityCatalog.create((code,), (adapter_a, adapter_b))

    def test_policy_is_explicit_catalog_bound_inventory_subset(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        observe = _capability("runtime.observe", domain=CapabilityDomain.RUNTIME)
        fast = _adapter("code.fast", ("code.change",))
        strong = _adapter(
            "code.strong",
            ("code.change",),
            fingerprint=_FINGERPRINT_B,
        )
        observer = _adapter("runtime.observer", ("runtime.observe",))
        catalog = CapabilityCatalog.create((code, observe), (fast, strong, observer))
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("code.strong", "code.fast"),
            allowed_capability_ids=("code.change",),
        )
        self.assertEqual(policy.catalog_id, catalog.catalog_id)
        self.assertEqual(policy.catalog_hash, catalog.content_hash)
        self.assertEqual(policy.ordered_adapter_ids, ("code.strong", "code.fast"))
        self.assertEqual(policy.allowed_capability_ids, ("code.change",))
        self.assertNotIn("runtime.observer", policy.ordered_adapter_ids)
        self.assertEqual(len(policy.content_hash), 64)

    def test_policy_rejects_unknown_or_duplicate_authority(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        adapter = _adapter("code.bounded", ("code.change",))
        catalog = CapabilityCatalog.create((code,), (adapter,))

        with self.assertRaisesRegex(ProductionCapabilityError, "unknown adapters"):
            CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("code.hidden",),
                allowed_capability_ids=("code.change",),
            )
        with self.assertRaisesRegex(ProductionCapabilityError, "unknown capabilities"):
            CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("code.bounded",),
                allowed_capability_ids=("image.generate",),
            )
        with self.assertRaisesRegex(ProductionCapabilityError, "duplicates"):
            CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("code.bounded", "code.bounded"),
                allowed_capability_ids=("code.change",),
            )

    def test_policy_detects_catalog_content_drift(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        adapter = _adapter("code.bounded", ("code.change",))
        catalog = CapabilityCatalog.create((code,), (adapter,))
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("code.bounded",),
            allowed_capability_ids=("code.change",),
        )
        changed = CapabilityCatalog(
            catalog_id=catalog.catalog_id,
            capabilities=(
                _capability(
                    "code.change",
                    domain=CapabilityDomain.CODE,
                    summary="drifted contract",
                ),
            ),
            adapters=(adapter,),
        )
        with self.assertRaisesRegex(ProductionCapabilityError, "binding drifted"):
            policy.validate_against(changed)

    def test_direct_policy_construction_cannot_use_boolean_schema_version_trick(self) -> None:
        code = _capability("code.change", domain=CapabilityDomain.CODE)
        with self.assertRaisesRegex(ProductionCapabilityError, "schema_version"):
            CapabilityCatalog(
                new_id(IdKind.CAPABILITY_CATALOG),
                (code,),
                (),
                schema_version=True,
            )


if __name__ == "__main__":
    unittest.main()
