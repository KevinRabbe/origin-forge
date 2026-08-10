from __future__ import annotations

import unittest

from origin_forge.simulation_analysis import analyze_simulation
from origin_forge.simulation_engine import run_simulation
from origin_forge.simulation_models import SimulationInvariant, SimulationRule, SimulationSpec


class SimulationAnalysisTests(unittest.TestCase):
    def test_summary_uses_exact_integer_and_rational_metrics(self) -> None:
        spec = SimulationSpec.create(
            seed=11,
            initial_state=(("gold", 0), ("stock", 2)),
            rules=(
                SimulationRule("income", 0, 1_000_000, produce=(("gold", 3),)),
                SimulationRule(
                    "consume-stock",
                    1,
                    1_000_000,
                    consume=(("stock", 1),),
                    produce=(("gold", 1),),
                ),
            ),
            invariants=(SimulationInvariant("gold-cap", "gold", maximum=8),),
            replicates=2,
            max_steps=3,
            stall_steps=3,
        )
        result = run_simulation(spec)
        summary = analyze_simulation(spec, result)
        payload = summary.to_dict()

        self.assertEqual(payload["spec_hash"], spec.content_hash)
        self.assertEqual(payload["result_hash"], result.content_hash)
        self.assertEqual(payload["replicate_count"], 2)
        self.assertEqual(payload["total_steps_executed"], 6)
        self.assertEqual(payload["stalled_replicates"], 0)
        self.assertEqual(payload["violation_count"], 2)
        self.assertEqual(payload["violation_replicates"], 2)
        self.assertFalse(payload["production_task_verified"])
        self.assertFalse(payload["semantic_balance_verified"])
        self.assertFalse(payload["automatic_tuning_authorized"])

        by_variable = {value["variable"]: value for value in payload["variables"]}
        self.assertEqual(by_variable["gold"]["final_minimum"], 11)
        self.assertEqual(by_variable["gold"]["final_maximum"], 11)
        self.assertEqual(by_variable["gold"]["final_sum"], 22)
        self.assertEqual(by_variable["gold"]["mean_final_numerator"], 22)
        self.assertEqual(by_variable["gold"]["mean_final_denominator"], 2)
        self.assertEqual(by_variable["stock"]["minimum_observed"], 0)

        by_rule = {value["rule_id"]: value for value in payload["rules"]}
        self.assertEqual(by_rule["income"]["attempts"], 6)
        self.assertEqual(by_rule["income"]["firings"], 6)
        self.assertEqual(by_rule["income"]["firing_rate_numerator"], 6)
        self.assertEqual(by_rule["income"]["firing_rate_denominator"], 6)
        self.assertEqual(by_rule["consume-stock"]["attempts"], 4)
        self.assertEqual(by_rule["consume-stock"]["firings"], 4)

    def test_summary_is_deterministic(self) -> None:
        spec = SimulationSpec.create(
            seed=12,
            initial_state=(("value", 0),),
            rules=(SimulationRule("maybe", 0, 500_000, produce=(("value", 1),)),),
            replicates=5,
            max_steps=25,
            stall_steps=10,
        )
        first_result = run_simulation(spec)
        second_result = run_simulation(spec)
        self.assertEqual(
            analyze_simulation(spec, first_result).to_dict(),
            analyze_simulation(spec, second_result).to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
