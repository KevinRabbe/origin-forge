from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.production_work_order_pixelorama as pixelorama_module
from origin_forge.ids import IdKind, new_id
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import WorkOrderInputRef, WorkOrderRefType
from origin_forge.production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_CONTRACT_ID,
    PIXELORAMA_EXPORT_PATH,
    PIXELORAMA_OPERATION,
    PIXELORAMA_SOURCE_ROLE,
    PIXELORAMA_STAGED_SOURCE_PATH,
    PixeloramaSpritesheetExportDispatchValidator,
)
from origin_forge.production_work_order_validators import DispatchValidatorError


class Phase48APixeloramaDispatchContractTests(unittest.TestCase):
    @staticmethod
    def _source_ref(**overrides: object) -> WorkOrderInputRef:
        values: dict[str, object] = {
            "ref_type": WorkOrderRefType.ARTIFACT,
            "ref_id": new_id(IdKind.ARTIFACT),
            "content_hash": "1" * 64,
            "role": PIXELORAMA_SOURCE_ROLE,
            "revision": None,
        }
        values.update(overrides)
        return WorkOrderInputRef(**values)  # type: ignore[arg-type]

    def test_validator_accepts_only_fixed_empty_payload_and_exact_source_ref(self) -> None:
        validator = PixeloramaSpritesheetExportDispatchValidator()
        ref = self._source_ref()
        self.assertEqual(validator.validate({}, (ref,)), {})
        self.assertEqual(validator.schema_dict()["fields"], [])
        self.assertEqual(validator.schema_dict()["additional_fields"], False)
        self.assertEqual(PIXELORAMA_OPERATION, "EXPORT_SPRITESHEET")
        self.assertEqual(PIXELORAMA_STAGED_SOURCE_PATH, "inputs/source.pxo")
        self.assertEqual(PIXELORAMA_EXPORT_PATH, "exports/spritesheet.png")

        with self.assertRaises(DispatchValidatorError):
            validator.validate({"operation": "EXPORT_SPRITESHEET"}, (ref,))
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, ())
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, (ref, self._source_ref()))
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, (self._source_ref(role="artifact"),))
        with self.assertRaises(DispatchValidatorError):
            validator.validate({}, (self._source_ref(revision=0),))
        with self.assertRaises(DispatchValidatorError):
            validator.validate(
                {},
                (
                    self._source_ref(
                        ref_type=WorkOrderRefType.VERIFICATION,
                        ref_id=new_id(IdKind.VERIFICATION),
                    ),
                ),
            )
        with self.assertRaises(DispatchValidatorError):
            validator.validate(
                {},
                (self._source_ref(ref_id=new_id(IdKind.VERIFICATION)),),
            )

    def test_validator_identity_is_deterministic_and_contains_no_execution_surface(self) -> None:
        first = PixeloramaSpritesheetExportDispatchValidator()
        second = PixeloramaSpritesheetExportDispatchValidator()
        self.assertEqual(first.validator_id, second.validator_id)
        self.assertEqual(first.validator_fingerprint, second.validator_fingerprint)
        self.assertEqual(first.payload_schema_id, second.payload_schema_id)
        self.assertEqual(first.payload_schema_hash, second.payload_schema_hash)

        source = inspect.getsource(pixelorama_module)
        for forbidden in (
            "PixeloramaCliExportAdapter",
            "PixeloramaCliProfile",
            "subprocess",
            "os.system",
            "importlib",
            "runtime.create_run",
            "new_id(IdKind.PIXELORAMA_OPERATION",
            "new_id(IdKind.MEDIA_WORKSPACE",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        executable_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue({"execute", "run", "drive"}.isdisjoint(executable_calls))

    def test_pixelorama_only_catalog_gets_exact_contract_and_full_catalog_stays_code_only(self) -> None:
        full = build_builtin_capability_catalog()
        legacy = build_builtin_dispatch_catalog(full)
        self.assertEqual(legacy.contract_ids, ("code.bounded-retry@1",))

        pixelorama_catalog = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter(PIXELORAMA_ADAPTER_ID),),
        )
        dispatch = build_builtin_dispatch_catalog(pixelorama_catalog)
        self.assertEqual(dispatch.contract_ids, (PIXELORAMA_CONTRACT_ID,))
        contract = dispatch.contract(PIXELORAMA_CONTRACT_ID)
        self.assertEqual(contract.adapter_id, PIXELORAMA_ADAPTER_ID)
        self.assertEqual(
            contract.allowed_input_ref_types,
            (WorkOrderRefType.ARTIFACT,),
        )
        self.assertEqual(contract.max_input_refs, 1)
        self.assertEqual(contract.max_payload_bytes, 2)
        registry = build_builtin_dispatch_validator_registry()
        registry.validate_contract(contract)
        self.assertEqual(
            registry.validate_payload(contract, {}, (self._source_ref(),)),
            {},
        )

    def test_simulation_only_catalog_is_unchanged_and_mixed_noncode_reviewed_catalog_fails_closed(self) -> None:
        full = build_builtin_capability_catalog()
        simulation_catalog = CapabilityCatalog.create(
            (full.capability("simulation.run"),),
            (full.adapter("originforge.simulation.deterministic"),),
        )
        simulation_dispatch = build_builtin_dispatch_catalog(simulation_catalog)
        self.assertEqual(simulation_dispatch.contract_ids, ("simulation.deterministic@1",))

        mixed = CapabilityCatalog.create(
            (
                full.capability("simulation.run"),
                full.capability("media.2d.export"),
            ),
            (
                full.adapter("originforge.simulation.deterministic"),
                full.adapter(PIXELORAMA_ADAPTER_ID),
            ),
        )
        with self.assertRaisesRegex(ValueError, "multiple reviewed non-code"):
            build_builtin_dispatch_catalog(mixed)


if __name__ == "__main__":
    unittest.main()
