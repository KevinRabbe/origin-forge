from __future__ import annotations

import unittest
from dataclasses import fields

from origin_forge.ids import IdKind, validate_id
from origin_forge.simulation_models import (
    SimulationInvariant,
    SimulationModelError,
    SimulationRule,
    SimulationSpec,
)


class SimulationModelTests(unittest.TestCase):
    def _rules(self) -> tuple[SimulationRule, ...]:
        return (
            SimulationRule(
                rule_id="craft",
                priority=20,
                probability_ppm=1_000_000,
                requires=(("ore", 2),),
                consume=(("ore", 2),),
                produce=(("ingot", 1),),
            ),
            SimulationRule(
                rule_id="mine",
                priority=10,
                probability_ppm=750_000,
                produce=(("ore", 1),),
            ),
        )

    def test_create_assigns_infrastructure_owned_ids(self) -> None:
        spec = SimulationSpec.create(
            seed=7,
            initial_state=(("ore", 0), ("ingot", 0)),
            rules=self._rules(),
        )
        self.assertTrue(validate_id(spec.spec_id, IdKind.SIMULATION_SPEC))
        self.assertTrue(validate_id(spec.session_id, IdKind.SIMULATION_SESSION))
        self.assertTrue(validate_id(spec.workspace_id, IdKind.SIMULATION_WORKSPACE))

    def test_content_hash_is_canonical_across_input_order(self) -> None:
        first = SimulationSpec.create(
            seed=99,
            initial_state=(("ore", 0), ("ingot", 0)),
            rules=self._rules(),
            invariants=(
                SimulationInvariant("ore-cap", "ore", maximum=100),
                SimulationInvariant("ingot-floor", "ingot", minimum=0),
            ),
            replicates=2,
            max_steps=50,
            stall_steps=10,
        )
        second = SimulationSpec(
            spec_id=first.spec_id,
            session_id=first.session_id,
            workspace_id=first.workspace_id,
            engine_id=first.engine_id,
            engine_version=first.engine_version,
            seed=first.seed,
            replicates=first.replicates,
            max_steps=first.max_steps,
            stall_steps=first.stall_steps,
            initial_state=tuple(reversed(first.initial_state)),
            rules=tuple(reversed(first.rules)),
            invariants=tuple(reversed(first.invariants)),
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual([rule.rule_id for rule in first.rules], ["mine", "craft"])

    def test_unknown_rule_variable_is_rejected(self) -> None:
        with self.assertRaisesRegex(SimulationModelError, "unknown state variable"):
            SimulationSpec.create(
                seed=1,
                initial_state=(("gold", 0),),
                rules=(
                    SimulationRule(
                        "bad",
                        0,
                        1_000_000,
                        produce=(("missing", 1),),
                    ),
                ),
            )

    def test_unknown_invariant_variable_is_rejected(self) -> None:
        with self.assertRaisesRegex(SimulationModelError, "unknown state variable"):
            SimulationSpec.create(
                seed=1,
                initial_state=(("gold", 0),),
                rules=(SimulationRule("income", 0, 1_000_000, produce=(("gold", 1),)),),
                invariants=(SimulationInvariant("bad", "missing", minimum=0),),
            )

    def test_duplicate_rule_id_is_rejected(self) -> None:
        duplicate = SimulationRule("same", 0, 1_000_000, produce=(("gold", 1),))
        with self.assertRaisesRegex(SimulationModelError, "duplicate rule_id"):
            SimulationSpec.create(
                seed=1,
                initial_state=(("gold", 0),),
                rules=(duplicate, duplicate),
            )

    def test_invariant_requires_valid_bounds(self) -> None:
        with self.assertRaisesRegex(SimulationModelError, "requires"):
            SimulationInvariant("bad", "gold")
        with self.assertRaisesRegex(SimulationModelError, "exceeds"):
            SimulationInvariant("bad", "gold", minimum=5, maximum=4)

    def test_rule_work_budget_fails_closed(self) -> None:
        rules = tuple(
            SimulationRule(
                f"rule-{index:03d}",
                index,
                0,
                produce=(("value", 1),),
            )
            for index in range(256)
        )
        with self.assertRaisesRegex(SimulationModelError, "work budget"):
            SimulationSpec.create(
                seed=1,
                initial_state=(("value", 0),),
                rules=rules,
                replicates=2,
                max_steps=10_000,
                stall_steps=1,
            )

    def test_invariant_work_is_included_in_budget(self) -> None:
        invariants = tuple(
            SimulationInvariant(f"limit-{index:03d}", "value", minimum=0)
            for index in range(256)
        )
        with self.assertRaisesRegex(SimulationModelError, "work budget"):
            SimulationSpec.create(
                seed=2,
                initial_state=(("value", 0),),
                rules=(SimulationRule("noop-probability", 0, 0, produce=(("value", 1),)),),
                invariants=invariants,
                replicates=256,
                max_steps=100,
                stall_steps=1,
            )

    def test_rule_surface_contains_only_declarative_state_transition_fields(self) -> None:
        self.assertEqual(
            {field.name for field in fields(SimulationRule)},
            {"rule_id", "priority", "probability_ppm", "requires", "consume", "produce"},
        )
        forbidden = {
            "script",
            "shell",
            "command",
            "path",
            "callback",
            "python",
            "javascript",
            "network",
            "executable",
        }
        self.assertTrue(forbidden.isdisjoint({field.name for field in fields(SimulationRule)}))


if __name__ == "__main__":
    unittest.main()
