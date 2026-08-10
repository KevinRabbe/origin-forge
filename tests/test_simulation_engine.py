from __future__ import annotations

import unittest

from origin_forge.simulation_engine import SimulationEngineError, run_simulation
from origin_forge.simulation_models import (
    STATE_MAX,
    SimulationInvariant,
    SimulationRule,
    SimulationSpec,
)


class SimulationEngineTests(unittest.TestCase):
    def test_deterministic_execution_and_hash(self) -> None:
        spec = SimulationSpec.create(
            seed=42,
            initial_state=(("coins", 0),),
            rules=(SimulationRule("income", 0, 375_000, produce=(("coins", 2),)),),
            replicates=4,
            max_steps=100,
            stall_steps=20,
        )
        first = run_simulation(spec)
        second = run_simulation(spec)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.content_hash, second.content_hash)
        first.bind_spec(spec)

    def test_zero_and_full_probability_boundaries(self) -> None:
        spec = SimulationSpec.create(
            seed=2,
            initial_state=(("coins", 0),),
            rules=(
                SimulationRule("always", 0, 1_000_000, produce=(("coins", 2),)),
                SimulationRule("never", 1, 0, produce=(("coins", 100),)),
            ),
            max_steps=3,
            stall_steps=3,
        )
        result = run_simulation(spec).replicates[0]
        self.assertEqual(dict(result.final_state)["coins"], 6)
        self.assertEqual(dict(result.rule_attempts), {"always": 3, "never": 3})
        self.assertEqual(dict(result.rule_firings), {"always": 3, "never": 0})
        self.assertFalse(result.stalled)

    def test_requires_and_consumption_gate_rule(self) -> None:
        spec = SimulationSpec.create(
            seed=3,
            initial_state=(("ore", 2), ("ingot", 0)),
            rules=(
                SimulationRule(
                    "craft",
                    0,
                    1_000_000,
                    requires=(("ore", 2),),
                    consume=(("ore", 2),),
                    produce=(("ingot", 1),),
                ),
            ),
            max_steps=10,
            stall_steps=2,
        )
        result = run_simulation(spec).replicates[0]
        self.assertEqual(dict(result.final_state), {"ingot": 1, "ore": 0})
        self.assertEqual(dict(result.rule_attempts)["craft"], 1)
        self.assertEqual(dict(result.rule_firings)["craft"], 1)
        self.assertEqual(result.steps_executed, 3)
        self.assertTrue(result.stalled)

    def test_invariant_violations_are_retained_as_evidence(self) -> None:
        spec = SimulationSpec.create(
            seed=4,
            initial_state=(("gold", 0),),
            rules=(SimulationRule("income", 0, 1_000_000, produce=(("gold", 1),)),),
            invariants=(SimulationInvariant("gold-cap", "gold", maximum=2),),
            max_steps=4,
            stall_steps=4,
        )
        result = run_simulation(spec).replicates[0]
        self.assertEqual(result.violation_count, 2)
        self.assertFalse(result.violations_truncated)
        self.assertEqual([value.checkpoint for value in result.violations], [3, 4])
        self.assertEqual([value.observed for value in result.violations], [3, 4])

    def test_zero_net_firing_still_counts_as_no_state_progress(self) -> None:
        spec = SimulationSpec.create(
            seed=5,
            initial_state=(("coin", 1),),
            rules=(
                SimulationRule(
                    "exchange",
                    0,
                    1_000_000,
                    consume=(("coin", 1),),
                    produce=(("coin", 1),),
                ),
            ),
            max_steps=10,
            stall_steps=2,
        )
        result = run_simulation(spec).replicates[0]
        self.assertTrue(result.stalled)
        self.assertEqual(result.steps_executed, 2)
        self.assertEqual(dict(result.rule_firings)["exchange"], 2)
        self.assertEqual(dict(result.final_state)["coin"], 1)

    def test_state_overflow_fails_closed(self) -> None:
        spec = SimulationSpec.create(
            seed=6,
            initial_state=(("value", STATE_MAX),),
            rules=(SimulationRule("overflow", 0, 1_000_000, produce=(("value", 1),)),),
            max_steps=1,
            stall_steps=1,
        )
        with self.assertRaisesRegex(SimulationEngineError, "overflow"):
            run_simulation(spec)

    def test_multiple_replicates_are_contiguous_and_bound(self) -> None:
        spec = SimulationSpec.create(
            seed=7,
            initial_state=(("value", 0),),
            rules=(SimulationRule("maybe", 0, 500_000, produce=(("value", 1),)),),
            replicates=8,
            max_steps=20,
            stall_steps=10,
        )
        result = run_simulation(spec)
        self.assertEqual(
            [value.replicate_index for value in result.replicates], list(range(8))
        )
        result.bind_spec(spec)

    def test_result_supports_full_rule_count_contract(self) -> None:
        rules = tuple(
            SimulationRule(
                f"rule-{index:03d}",
                0,
                0,
                produce=(("value", 1),),
            )
            for index in range(129)
        )
        spec = SimulationSpec.create(
            seed=8,
            initial_state=(("value", 0),),
            rules=rules,
            max_steps=1,
            stall_steps=1,
        )
        result = run_simulation(spec)
        replicate = result.replicates[0]
        self.assertEqual(len(replicate.rule_attempts), 129)
        self.assertEqual(len(replicate.rule_firings), 129)
        result.bind_spec(spec)

    def test_caller_cannot_spoof_built_in_engine_identity(self) -> None:
        spec = SimulationSpec.create(
            seed=9,
            initial_state=(("value", 0),),
            rules=(SimulationRule("income", 0, 1_000_000, produce=(("value", 1),)),),
            max_steps=1,
            stall_steps=1,
            engine_id="caller-selected-engine",
            engine_version="999",
        )
        with self.assertRaisesRegex(SimulationEngineError, "engine identity"):
            run_simulation(spec)

    def test_engine_exposes_no_execution_or_mutation_authority(self) -> None:
        import origin_forge.simulation_engine as engine

        for forbidden in (
            "subprocess",
            "Popen",
            "system",
            "exec",
            "eval",
            "open",
            "socket",
            "requests",
            "transition_task",
            "complete_task",
            "adopt",
            "sign",
            "merge",
            "release",
        ):
            self.assertFalse(hasattr(engine, forbidden))


if __name__ == "__main__":
    unittest.main()
