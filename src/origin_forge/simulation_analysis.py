from __future__ import annotations

from dataclasses import dataclass

from .simulation_models import SimulationResult, SimulationSpec


@dataclass(frozen=True)
class SimulationVariableSummary:
    variable: str
    replicate_count: int
    final_minimum: int
    final_maximum: int
    final_sum: int
    minimum_observed: int
    maximum_observed: int

    def to_dict(self) -> dict[str, object]:
        return {
            "variable": self.variable,
            "replicate_count": self.replicate_count,
            "final_minimum": self.final_minimum,
            "final_maximum": self.final_maximum,
            "final_sum": self.final_sum,
            "mean_final_numerator": self.final_sum,
            "mean_final_denominator": self.replicate_count,
            "minimum_observed": self.minimum_observed,
            "maximum_observed": self.maximum_observed,
        }


@dataclass(frozen=True)
class SimulationRuleSummary:
    rule_id: str
    attempts: int
    firings: int

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "attempts": self.attempts,
            "firings": self.firings,
            "firing_rate_numerator": self.firings,
            "firing_rate_denominator": self.attempts,
        }


@dataclass(frozen=True)
class SimulationSummary:
    spec_hash: str
    result_hash: str
    replicate_count: int
    total_steps_executed: int
    stalled_replicates: int
    violation_count: int
    violation_replicates: int
    truncated_violation_replicates: int
    variables: tuple[SimulationVariableSummary, ...]
    rules: tuple[SimulationRuleSummary, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_hash": self.spec_hash,
            "result_hash": self.result_hash,
            "replicate_count": self.replicate_count,
            "total_steps_executed": self.total_steps_executed,
            "stalled_replicates": self.stalled_replicates,
            "violation_count": self.violation_count,
            "violation_replicates": self.violation_replicates,
            "truncated_violation_replicates": self.truncated_violation_replicates,
            "variables": [value.to_dict() for value in self.variables],
            "rules": [value.to_dict() for value in self.rules],
            "production_task_verified": False,
            "semantic_balance_verified": False,
            "automatic_tuning_authorized": False,
        }


def analyze_simulation(
    spec: SimulationSpec,
    result: SimulationResult,
) -> SimulationSummary:
    if not isinstance(spec, SimulationSpec):
        raise TypeError("spec must be a SimulationSpec")
    if not isinstance(result, SimulationResult):
        raise TypeError("result must be a SimulationResult")
    result.bind_spec(spec)

    state_maps = tuple(
        (
            dict(replicate.final_state),
            dict(replicate.minimum_state),
            dict(replicate.maximum_state),
        )
        for replicate in result.replicates
    )
    rule_maps = tuple(
        (dict(replicate.rule_attempts), dict(replicate.rule_firings))
        for replicate in result.replicates
    )

    variables: list[SimulationVariableSummary] = []
    for name, _ in spec.initial_state:
        finals = [maps[0][name] for maps in state_maps]
        observed_minima = [maps[1][name] for maps in state_maps]
        observed_maxima = [maps[2][name] for maps in state_maps]
        variables.append(
            SimulationVariableSummary(
                variable=name,
                replicate_count=len(result.replicates),
                final_minimum=min(finals),
                final_maximum=max(finals),
                final_sum=sum(finals),
                minimum_observed=min(observed_minima),
                maximum_observed=max(observed_maxima),
            )
        )

    rules: list[SimulationRuleSummary] = []
    for rule_id in sorted(rule.rule_id for rule in spec.rules):
        attempts = sum(maps[0][rule_id] for maps in rule_maps)
        firings = sum(maps[1][rule_id] for maps in rule_maps)
        rules.append(
            SimulationRuleSummary(
                rule_id=rule_id,
                attempts=attempts,
                firings=firings,
            )
        )

    return SimulationSummary(
        spec_hash=spec.content_hash,
        result_hash=result.content_hash,
        replicate_count=len(result.replicates),
        total_steps_executed=sum(value.steps_executed for value in result.replicates),
        stalled_replicates=sum(1 for value in result.replicates if value.stalled),
        violation_count=sum(value.violation_count for value in result.replicates),
        violation_replicates=sum(1 for value in result.replicates if value.violation_count),
        truncated_violation_replicates=sum(
            1 for value in result.replicates if value.violations_truncated
        ),
        variables=tuple(variables),
        rules=tuple(rules),
    )
