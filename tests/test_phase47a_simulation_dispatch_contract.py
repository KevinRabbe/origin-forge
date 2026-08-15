from __future__ import annotations

import unittest

from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_simulation import (
    DeterministicSimulationDispatchValidator,
)
from origin_forge.production_work_order_validators import DispatchValidatorError
from origin_forge.simulation_models import SimulationInvariant, SimulationRule, SimulationSpec
from origin_forge.simulation_spec_template import SimulationSpecTemplate


class Phase47ASimulationDispatchTests(unittest.TestCase):
    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "seed": 7,
            "replicates": 2,
            "max_steps": 50,
            "stall_steps": 10,
            "initial_state_json": '{"ingot":0,"ore":0}',
            "rules_json": '[{"consume":{"ore":2},"priority":10,"probability_ppm":1000000,"produce":{"ingot":1},"requires":{"ore":2},"rule_id":"craft"},{"consume":{},"priority":0,"probability_ppm":750000,"produce":{"ore":1},"requires":{},"rule_id":"mine"}]',
            "invariants_json": '[{"invariant_id":"ore-floor","maximum":null,"minimum":0,"variable":"ore"}]',
        }

    def test_template_matches_concrete_phase25_semantics_without_ids(self) -> None:
        rules = (
            SimulationRule("craft", 10, 1_000_000, requires=(("ore", 2),), consume=(("ore", 2),), produce=(("ingot", 1),)),
            SimulationRule("mine", 0, 750_000, produce=(("ore", 1),)),
        )
        invariants = (SimulationInvariant("ore-floor", "ore", minimum=0),)
        template = SimulationSpecTemplate.create(
            seed=7,
            initial_state=(("ore", 0), ("ingot", 0)),
            rules=rules,
            invariants=invariants,
            replicates=2,
            max_steps=50,
            stall_steps=10,
        )
        concrete = SimulationSpec.create(
            seed=7,
            initial_state=(("ore", 0), ("ingot", 0)),
            rules=rules,
            invariants=invariants,
            replicates=2,
            max_steps=50,
            stall_steps=10,
        )
        semantic = concrete.to_dict()
        for key in ("spec_id", "session_id", "workspace_id"):
            semantic.pop(key)
        self.assertEqual(template.to_dict(), semantic)
        self.assertNotIn("spec_id", template.to_dict())
        self.assertNotIn("session_id", template.to_dict())
        self.assertNotIn("workspace_id", template.to_dict())

    def test_simulation_validator_reconstructs_exact_template(self) -> None:
        validator = DeterministicSimulationDispatchValidator()
        normalized = validator.validate(self._payload(), ())
        template = validator.template(normalized)
        self.assertEqual(template.engine_id, "origin-forge-deterministic-sim")
        self.assertEqual(template.engine_version, "1")
        self.assertEqual([rule.rule_id for rule in template.rules], ["mine", "craft"])
        self.assertEqual(template.initial_state, (("ingot", 0), ("ore", 0)))

    def test_simulation_validator_rejects_noncanonical_duplicate_float_and_refs(self) -> None:
        validator = DeterministicSimulationDispatchValidator()
        for field, value in (
            ("initial_state_json", '{"ore": 0,"ingot":0}'),
            ("initial_state_json", '{"ore":0,"ore":1}'),
            ("initial_state_json", '{"ore":0.0,"ingot":0}'),
        ):
            payload = self._payload()
            payload[field] = value
            with self.subTest(value=value):
                with self.assertRaises(DispatchValidatorError):
                    validator.validate(payload, ())
        with self.assertRaises(DispatchValidatorError):
            validator.validate({**self._payload(), "engine_id": "forged"}, ())

    def test_simulation_only_catalog_gets_exact_contract_while_full_catalog_stays_code_only(self) -> None:
        full = build_builtin_capability_catalog()
        legacy = build_builtin_dispatch_catalog(full)
        self.assertEqual(legacy.contract_ids, ("code.bounded-retry@1",))

        simulation_catalog = CapabilityCatalog.create(
            (full.capability("simulation.run"),),
            (full.adapter("originforge.simulation.deterministic"),),
        )
        dispatch = build_builtin_dispatch_catalog(simulation_catalog)
        self.assertEqual(dispatch.contract_ids, ("simulation.deterministic@1",))
        contract = dispatch.contract("simulation.deterministic@1")
        self.assertEqual(contract.adapter_id, "originforge.simulation.deterministic")
        self.assertEqual(contract.allowed_input_ref_types, ())
        self.assertEqual(contract.max_input_refs, 0)
        build_builtin_dispatch_validator_registry().validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
