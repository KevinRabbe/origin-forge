from __future__ import annotations

import inspect
import unittest

import origin_forge.production_work_order_validators as validator_module
from origin_forge.production_work_order_models import (
    DispatchContract,
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)


class ProductionWorkOrderValidatorTests(unittest.TestCase):
    def _validator(self) -> StaticObjectPayloadValidator:
        return StaticObjectPayloadValidator(
            validator_id="validator.example@1",
            payload_schema_id="schema.example@1",
            fields=(
                PayloadFieldRule(
                    "mode",
                    PayloadFieldKind.STRING,
                    allowed_values=("safe", "strict"),
                    max_string_chars=16,
                ),
                PayloadFieldRule(
                    "attempts",
                    PayloadFieldKind.INTEGER,
                    min_integer=1,
                    max_integer=5,
                ),
                PayloadFieldRule(
                    "change_required",
                    PayloadFieldKind.BOOLEAN,
                ),
                PayloadFieldRule(
                    "seed_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=128,
                    max_items=8,
                ),
            ),
        )

    def _contract(
        self,
        validator: StaticObjectPayloadValidator,
        *,
        validator_fingerprint: str | None = None,
        schema_hash: str | None = None,
        ref_types: tuple[WorkOrderRefType, ...] = (WorkOrderRefType.ARTIFACT,),
        max_refs: int = 2,
        max_payload_bytes: int = 4096,
    ) -> DispatchContract:
        return DispatchContract(
            contract_id="example@1",
            contract_version="1",
            adapter_id="originforge.example",
            adapter_fingerprint="a" * 64,
            validator_id=validator.validator_id,
            validator_fingerprint=(
                validator.validator_fingerprint
                if validator_fingerprint is None
                else validator_fingerprint
            ),
            payload_schema_id=validator.payload_schema_id,
            payload_schema_hash=(
                validator.payload_schema_hash if schema_hash is None else schema_hash
            ),
            allowed_input_ref_types=ref_types,
            max_payload_bytes=max_payload_bytes,
            max_input_refs=max_refs,
        )

    def test_static_schema_identity_is_deterministic_and_order_independent(self) -> None:
        first = self._validator()
        second = StaticObjectPayloadValidator(
            validator_id="validator.example@1",
            payload_schema_id="schema.example@1",
            fields=tuple(reversed(first.fields)),
        )
        self.assertEqual(first.schema_dict(), second.schema_dict())
        self.assertEqual(first.payload_schema_hash, second.payload_schema_hash)
        self.assertEqual(first.validator_fingerprint, second.validator_fingerprint)

    def test_static_validator_rejects_unknown_missing_and_wrong_types(self) -> None:
        validator = self._validator()
        valid = {
            "mode": "safe",
            "attempts": 2,
            "change_required": True,
            "seed_paths": ["src/a.py", "tests/test_a.py"],
        }
        self.assertEqual(validator.validate(valid, ()), valid)

        with self.assertRaisesRegex(DispatchValidatorError, "unknown fields"):
            validator.validate({**valid, "shell": "rm -rf /"}, ())
        missing = dict(valid)
        missing.pop("mode")
        with self.assertRaisesRegex(DispatchValidatorError, "missing required"):
            validator.validate(missing, ())
        wrong_integer = dict(valid)
        wrong_integer["attempts"] = True
        with self.assertRaisesRegex(DispatchValidatorError, "integer bounds"):
            validator.validate(wrong_integer, ())
        wrong_bool = dict(valid)
        wrong_bool["change_required"] = 1
        with self.assertRaisesRegex(DispatchValidatorError, "must be boolean"):
            validator.validate(wrong_bool, ())
        wrong_enum = dict(valid)
        wrong_enum["mode"] = "unsafe"
        with self.assertRaisesRegex(DispatchValidatorError, "allowed value"):
            validator.validate(wrong_enum, ())

    def test_registry_binds_exact_validator_and_schema_fingerprints(self) -> None:
        validator = self._validator()
        registry = DispatchContractValidatorRegistry((validator,))
        contract = self._contract(validator)
        self.assertIs(registry.validate_contract(contract), validator)

        drifted_validator = self._contract(
            validator,
            validator_fingerprint="b" * 64,
        )
        with self.assertRaisesRegex(DispatchValidatorError, "fingerprint drifted"):
            registry.validate_contract(drifted_validator)
        drifted_schema = self._contract(validator, schema_hash="c" * 64)
        with self.assertRaisesRegex(DispatchValidatorError, "schema hash drifted"):
            registry.validate_contract(drifted_schema)

        unknown_contract = DispatchContract(
            "unknown@1",
            "1",
            "originforge.example",
            "a" * 64,
            "validator.unknown@1",
            "b" * 64,
            "schema.unknown@1",
            "c" * 64,
            (),
            1024,
            0,
        )
        with self.assertRaisesRegex(DispatchValidatorError, "unknown dispatch validator"):
            registry.validate_contract(unknown_contract)

    def test_registry_enforces_ref_type_count_and_duplicate_bounds(self) -> None:
        validator = self._validator()
        registry = DispatchContractValidatorRegistry((validator,))
        contract = self._contract(validator)
        artifact = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            "ART-11111111-1111-4111-8111-111111111111",
            "d" * 64,
            "source",
        )
        verification = WorkOrderInputRef(
            WorkOrderRefType.VERIFICATION,
            "VERIFY-11111111-1111-4111-8111-111111111111",
            "e" * 64,
            "verification",
        )
        payload = {
            "mode": "safe",
            "attempts": 1,
            "change_required": False,
        }
        self.assertEqual(
            registry.validate_payload(contract, payload, (artifact,)),
            payload,
        )
        with self.assertRaisesRegex(DispatchValidatorError, "not allowed"):
            registry.validate_payload(contract, payload, (verification,))
        with self.assertRaisesRegex(DispatchValidatorError, "duplicates"):
            registry.validate_payload(contract, payload, (artifact, artifact))
        one_ref_contract = self._contract(validator, max_refs=1)
        other_artifact = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            "ART-22222222-2222-4222-8222-222222222222",
            "f" * 64,
            "other",
        )
        with self.assertRaisesRegex(DispatchValidatorError, "count exceeds"):
            registry.validate_payload(
                one_ref_contract,
                payload,
                (artifact, other_artifact),
            )

    def test_registry_enforces_payload_byte_limit(self) -> None:
        validator = StaticObjectPayloadValidator(
            validator_id="validator.small@1",
            payload_schema_id="schema.small@1",
            fields=(
                PayloadFieldRule(
                    "text",
                    PayloadFieldKind.STRING,
                    max_string_chars=256,
                ),
            ),
        )
        registry = DispatchContractValidatorRegistry((validator,))
        contract = self._contract(
            validator,
            max_refs=0,
            ref_types=(),
            max_payload_bytes=32,
        )
        with self.assertRaisesRegex(DispatchValidatorError, "byte size exceeds"):
            registry.validate_payload(contract, {"text": "x" * 100}, ())

    def test_validator_source_has_no_dynamic_execution_surface(self) -> None:
        source = inspect.getsource(validator_module)
        for forbidden in (
            "importlib",
            "subprocess",
            "os.system",
            "eval(",
            "exec(",
            "__import__",
            "open(",
            "urllib",
            "requests.",
            "socket.",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
