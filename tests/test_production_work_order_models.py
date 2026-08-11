from __future__ import annotations

import unittest

from origin_forge.ids import IdKind, new_id, validate_id
from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    ProductionCapability,
    TrustedProductionAdapter,
)
from origin_forge.production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64


def _phase32_catalog(*, fingerprint: str = _HASH_A) -> CapabilityCatalog:
    capability = ProductionCapability(
        "code.change",
        "Code change",
        "bounded coding",
        CapabilityDomain.CODE,
        "1",
    )
    adapter = TrustedProductionAdapter(
        "originforge.code.bounded-retry",
        "originforge.code",
        "1",
        fingerprint,
        ("code.change",),
        AdapterExecutionEffect.WORKSPACE_MUTATION,
        AdapterReplayClass.REVISION_BOUND,
    )
    return CapabilityCatalog.create((capability,), (adapter,))


def _contract(*, adapter_fingerprint: str = _HASH_A) -> DispatchContract:
    return DispatchContract(
        contract_id="code.bounded-retry@1",
        contract_version="1",
        adapter_id="originforge.code.bounded-retry",
        adapter_fingerprint=adapter_fingerprint,
        validator_id="validator.code.bounded-retry@1",
        validator_fingerprint=_HASH_B,
        payload_schema_id="schema.code.bounded-retry@1",
        payload_schema_hash=_HASH_C,
        allowed_input_ref_types=(
            WorkOrderRefType.ARTIFACT,
            WorkOrderRefType.VERIFICATION,
        ),
        max_payload_bytes=65536,
        max_input_refs=16,
    )


class ProductionWorkOrderModelTests(unittest.TestCase):
    def test_phase33_id_families_are_infrastructure_owned(self) -> None:
        for kind in (
            IdKind.DISPATCH_CONTRACT_CATALOG,
            IdKind.PRODUCTION_WORK_ORDER,
            IdKind.WORK_ORDER_AUDIT,
        ):
            value = new_id(kind)
            self.assertTrue(validate_id(value, kind))
        self.assertFalse(
            validate_id("WORKORD-model-chosen", IdKind.PRODUCTION_WORK_ORDER)
        )

    def test_input_ref_is_bounded_exact_evidence_metadata(self) -> None:
        value = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            "ART-11111111-1111-4111-8111-111111111111",
            _HASH_D,
            "source_asset",
            revision=7,
        )
        self.assertEqual(
            value.to_dict(),
            {
                "ref_type": "ARTIFACT",
                "ref_id": "ART-11111111-1111-4111-8111-111111111111",
                "content_hash": _HASH_D,
                "role": "source_asset",
                "revision": 7,
            },
        )
        with self.assertRaises(ProductionWorkOrderModelError):
            WorkOrderInputRef(
                WorkOrderRefType.ARTIFACT,
                "ART value with spaces",
                _HASH_D,
                "source_asset",
            )
        with self.assertRaises(ProductionWorkOrderModelError):
            WorkOrderInputRef(
                WorkOrderRefType.ARTIFACT,
                "ART-valid",
                _HASH_D,
                "source_asset",
                revision=True,
            )

    def test_dispatch_contract_has_no_executable_authority_fields(self) -> None:
        contract = _contract()
        payload = contract.to_dict()
        self.assertEqual(len(contract.content_hash), 64)
        self.assertEqual(
            set(payload),
            {
                "contract_id",
                "contract_version",
                "adapter_id",
                "adapter_fingerprint",
                "validator_id",
                "validator_fingerprint",
                "payload_schema_id",
                "payload_schema_hash",
                "allowed_input_ref_types",
                "max_payload_bytes",
                "max_input_refs",
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
            "executable",
            "endpoint",
            "secret",
        ):
            self.assertNotIn(forbidden, payload)

    def test_contract_bounds_reject_boolean_integer_confusion_and_duplicate_ref_types(self) -> None:
        base = _contract()
        with self.assertRaisesRegex(ProductionWorkOrderModelError, "max_payload_bytes"):
            DispatchContract(
                base.contract_id,
                base.contract_version,
                base.adapter_id,
                base.adapter_fingerprint,
                base.validator_id,
                base.validator_fingerprint,
                base.payload_schema_id,
                base.payload_schema_hash,
                base.allowed_input_ref_types,
                True,
                base.max_input_refs,
            )
        with self.assertRaisesRegex(ProductionWorkOrderModelError, "duplicates"):
            DispatchContract(
                base.contract_id,
                base.contract_version,
                base.adapter_id,
                base.adapter_fingerprint,
                base.validator_id,
                base.validator_fingerprint,
                base.payload_schema_id,
                base.payload_schema_hash,
                (WorkOrderRefType.ARTIFACT, WorkOrderRefType.ARTIFACT),
                base.max_payload_bytes,
                base.max_input_refs,
            )

    def test_dispatch_catalog_binds_exact_phase32_adapter_identity(self) -> None:
        phase32 = _phase32_catalog()
        catalog = DispatchContractCatalog.create(phase32, (_contract(),))
        self.assertEqual(catalog.phase32_catalog_id, phase32.catalog_id)
        self.assertEqual(catalog.phase32_catalog_hash, phase32.content_hash)
        self.assertEqual(catalog.contract_ids, ("code.bounded-retry@1",))
        self.assertEqual(
            catalog.contract_for_adapter("originforge.code.bounded-retry").contract_id,
            "code.bounded-retry@1",
        )
        self.assertEqual(len(catalog.content_hash), 64)

    def test_dispatch_catalog_rejects_unknown_or_drifted_adapter(self) -> None:
        phase32 = _phase32_catalog()
        drifted = _contract(adapter_fingerprint=_HASH_D)
        with self.assertRaisesRegex(ProductionWorkOrderModelError, "fingerprint drifted"):
            DispatchContractCatalog.create(phase32, (drifted,))

        unknown = DispatchContract(
            "other@1",
            "1",
            "originforge.unknown",
            _HASH_A,
            "validator.other@1",
            _HASH_B,
            "schema.other@1",
            _HASH_C,
            (),
            1024,
            0,
        )
        with self.assertRaisesRegex(ProductionWorkOrderModelError, "unknown adapter"):
            DispatchContractCatalog.create(phase32, (unknown,))

    def test_dispatch_catalog_rejects_multiple_v1_contracts_for_one_adapter(self) -> None:
        phase32 = _phase32_catalog()
        first = _contract()
        second = DispatchContract(
            "code.second@1",
            "1",
            first.adapter_id,
            first.adapter_fingerprint,
            "validator.code.second@1",
            _HASH_B,
            "schema.code.second@1",
            _HASH_C,
            (),
            1024,
            0,
        )
        with self.assertRaisesRegex(ProductionWorkOrderModelError, "multiple v1 contracts"):
            DispatchContractCatalog.create(phase32, (first, second))


if __name__ == "__main__":
    unittest.main()
