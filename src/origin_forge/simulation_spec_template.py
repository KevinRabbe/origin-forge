from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .runtime_observation_models import content_hash
from .simulation_models import (
    SimulationInvariant,
    SimulationModelError,
    SimulationRule,
    _MAX_INVARIANTS,
    _MAX_REPLICATES,
    _MAX_RULES,
    _MAX_SEED,
    _MAX_STEPS,
    _MAX_WORK_UNITS,
    _STATE_MAX,
    _STATE_MIN,
    _normalize_pairs,
    _pairs_dict,
)


SIMULATION_ENGINE_ID = "origin-forge-deterministic-sim"
SIMULATION_ENGINE_VERSION = "1"


@dataclass(frozen=True)
class SimulationSpecTemplate:
    """Bounded semantic simulation input with no execution-owned identities.

    Phase 25's concrete ``SimulationSpec`` also owns SIMSPEC/SIM/SIMWS identity.
    Production planning must not choose those identities, so Phase 47 freezes only
    the semantic fields here. Concrete identities are deliberately allocated by a
    later execution-owned boundary.
    """

    seed: int
    replicates: int
    max_steps: int
    stall_steps: int
    initial_state: tuple[tuple[str, int], ...]
    rules: tuple[SimulationRule, ...]
    invariants: tuple[SimulationInvariant, ...] = ()

    def __post_init__(self) -> None:
        from .simulation_models import _bounded_int

        _bounded_int(self.seed, "simulation seed", 0, _MAX_SEED)
        _bounded_int(self.replicates, "simulation replicates", 1, _MAX_REPLICATES)
        _bounded_int(self.max_steps, "simulation max_steps", 1, _MAX_STEPS)
        _bounded_int(self.stall_steps, "simulation stall_steps", 1, self.max_steps)

        initial = _normalize_pairs(
            self.initial_state,
            label="initial_state",
            minimum=_STATE_MIN,
            maximum=_STATE_MAX,
            allow_empty=False,
        )
        object.__setattr__(self, "initial_state", initial)
        variables = {name for name, _ in initial}

        rules = tuple(self.rules)
        if not rules or len(rules) > _MAX_RULES:
            raise SimulationModelError("rules must contain from 1 to 256 entries")
        if not all(isinstance(rule, SimulationRule) for rule in rules):
            raise SimulationModelError("rules must contain SimulationRule objects")
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise SimulationModelError("rules contain duplicate rule_id values")
        for rule in rules:
            if rule.referenced_variables() - variables:
                raise SimulationModelError(
                    f"rule {rule.rule_id} references unknown state variable"
                )
        rules = tuple(sorted(rules, key=lambda value: (value.priority, value.rule_id)))
        object.__setattr__(self, "rules", rules)

        invariants = tuple(self.invariants)
        if len(invariants) > _MAX_INVARIANTS:
            raise SimulationModelError("invariants exceed limit")
        if not all(isinstance(value, SimulationInvariant) for value in invariants):
            raise SimulationModelError("invariants must contain SimulationInvariant objects")
        if len({value.invariant_id for value in invariants}) != len(invariants):
            raise SimulationModelError("invariants contain duplicate invariant_id values")
        for invariant in invariants:
            if invariant.variable not in variables:
                raise SimulationModelError("invariant references unknown state variable")
        invariants = tuple(sorted(invariants, key=lambda value: value.invariant_id))
        object.__setattr__(self, "invariants", invariants)

        rule_step_cost = sum(
            1
            + len(rule.requires)
            + 6 * len(rule.consume)
            + 5 * len(rule.produce)
            for rule in rules
        )
        per_replicate_work = (
            3 * len(initial)
            + 2 * len(rules)
            + self.max_steps * rule_step_cost
            + (self.max_steps + 1) * len(invariants)
        )
        if self.replicates * per_replicate_work > _MAX_WORK_UNITS:
            raise SimulationModelError("simulation work budget exceeds v1 limit")

    @classmethod
    def create(
        cls,
        *,
        seed: int,
        initial_state: Iterable[tuple[str, int]],
        rules: Iterable[SimulationRule],
        invariants: Iterable[SimulationInvariant] = (),
        replicates: int = 1,
        max_steps: int = 100,
        stall_steps: int = 20,
    ) -> "SimulationSpecTemplate":
        return cls(
            seed=seed,
            replicates=replicates,
            max_steps=max_steps,
            stall_steps=stall_steps,
            initial_state=tuple(initial_state),
            rules=tuple(rules),
            invariants=tuple(invariants),
        )

    @property
    def engine_id(self) -> str:
        return SIMULATION_ENGINE_ID

    @property
    def engine_version(self) -> str:
        return SIMULATION_ENGINE_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "seed": self.seed,
            "replicates": self.replicates,
            "max_steps": self.max_steps,
            "stall_steps": self.stall_steps,
            "initial_state": _pairs_dict(self.initial_state),
            "rules": [rule.to_dict() for rule in self.rules],
            "invariants": [value.to_dict() for value in self.invariants],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())
