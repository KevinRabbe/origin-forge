from __future__ import annotations

import hashlib

from .simulation_models import (
    MAX_STORED_VIOLATIONS,
    MAX_TOTAL_STORED_VIOLATIONS,
    STATE_MAX,
    STATE_MIN,
    SimulationModelError,
    SimulationReplicateResult,
    SimulationResult,
    SimulationRule,
    SimulationSpec,
    SimulationViolation,
)


ENGINE_ID = "origin-forge-deterministic-sim"
ENGINE_VERSION = "1"


class SimulationEngineError(RuntimeError):
    pass


def _probability_draw(
    seed: int,
    replicate_index: int,
    step_index: int,
    rule_id: str,
) -> int:
    """Return a stable integer in [0, 1_000_000) without runtime RNG state."""

    material = (
        f"origin-forge-sim-v1\0{seed}\0{replicate_index}\0{step_index}\0{rule_id}"
    ).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest, "big") % 1_000_000


def _eligible(state: dict[str, int], rule: SimulationRule) -> bool:
    for name, minimum in rule.requires:
        if state[name] < minimum:
            return False
    for name, amount in rule.consume:
        if state[name] < amount:
            return False
    return True


def _remember_original(
    state: dict[str, int],
    step_original: dict[str, int],
    name: str,
) -> None:
    if name not in step_original:
        step_original[name] = state[name]


def _apply_rule(
    state: dict[str, int],
    rule: SimulationRule,
    step_original: dict[str, int],
) -> tuple[str, ...]:
    changed: set[str] = set()
    for name, amount in rule.consume:
        _remember_original(state, step_original, name)
        state[name] -= amount
        changed.add(name)
    for name, amount in rule.produce:
        _remember_original(state, step_original, name)
        value = state[name] + amount
        if value < STATE_MIN or value > STATE_MAX:
            raise SimulationEngineError(
                f"simulation state overflow for {name} while firing {rule.rule_id}"
            )
        state[name] = value
        changed.add(name)
    return tuple(sorted(changed))


def _record_invariants(
    spec: SimulationSpec,
    state: dict[str, int],
    checkpoint: int,
    stored: list[SimulationViolation],
    storage_limit: int,
) -> int:
    count = 0
    for invariant in spec.invariants:
        observed = state[invariant.variable]
        violated = (
            invariant.minimum is not None and observed < invariant.minimum
        ) or (
            invariant.maximum is not None and observed > invariant.maximum
        )
        if not violated:
            continue
        count += 1
        if len(stored) < storage_limit:
            stored.append(
                SimulationViolation(
                    invariant_id=invariant.invariant_id,
                    variable=invariant.variable,
                    checkpoint=checkpoint,
                    observed=observed,
                    minimum=invariant.minimum,
                    maximum=invariant.maximum,
                )
            )
    return count


def _state_pairs(state: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(state.items()))


def _run_replicate(
    spec: SimulationSpec,
    replicate_index: int,
    violation_storage_limit: int,
) -> SimulationReplicateResult:
    state = dict(spec.initial_state)
    minimum_state = dict(state)
    maximum_state = dict(state)
    attempts = {rule.rule_id: 0 for rule in spec.rules}
    firings = {rule.rule_id: 0 for rule in spec.rules}
    violations: list[SimulationViolation] = []
    violation_count = _record_invariants(
        spec, state, 0, violations, violation_storage_limit
    )
    no_progress_steps = 0
    stalled = False
    steps_executed = 0

    for step_index in range(spec.max_steps):
        step_original: dict[str, int] = {}
        for rule in spec.rules:
            if not _eligible(state, rule):
                continue
            attempts[rule.rule_id] += 1
            probability = rule.probability_ppm
            fires = probability == 1_000_000 or (
                probability > 0
                and _probability_draw(
                    spec.seed,
                    replicate_index,
                    step_index,
                    rule.rule_id,
                )
                < probability
            )
            if not fires:
                continue
            changed = _apply_rule(state, rule, step_original)
            firings[rule.rule_id] += 1
            for name in changed:
                value = state[name]
                if value < minimum_state[name]:
                    minimum_state[name] = value
                if value > maximum_state[name]:
                    maximum_state[name] = value

        steps_executed = step_index + 1
        violation_count += _record_invariants(
            spec,
            state,
            steps_executed,
            violations,
            violation_storage_limit,
        )
        progressed = any(
            state[name] != original for name, original in step_original.items()
        )
        if progressed:
            no_progress_steps = 0
        else:
            no_progress_steps += 1
        if no_progress_steps >= spec.stall_steps:
            stalled = True
            break

    return SimulationReplicateResult(
        replicate_index=replicate_index,
        steps_executed=steps_executed,
        stalled=stalled,
        final_state=_state_pairs(state),
        minimum_state=_state_pairs(minimum_state),
        maximum_state=_state_pairs(maximum_state),
        rule_attempts=tuple(sorted(attempts.items())),
        rule_firings=tuple(sorted(firings.items())),
        violation_count=violation_count,
        violations=tuple(violations),
        violations_truncated=violation_count > len(violations),
    )


def run_simulation(spec: SimulationSpec) -> SimulationResult:
    """Execute the frozen deterministic Phase-25 simulation contract."""

    if not isinstance(spec, SimulationSpec):
        raise TypeError("spec must be a SimulationSpec")
    if (spec.engine_id, spec.engine_version) != (ENGINE_ID, ENGINE_VERSION):
        raise SimulationEngineError(
            "simulation specification does not match the governed v1 engine identity"
        )
    violation_storage_limit = min(
        MAX_STORED_VIOLATIONS,
        max(1, MAX_TOTAL_STORED_VIOLATIONS // spec.replicates),
    )
    replicates = tuple(
        _run_replicate(spec, replicate_index, violation_storage_limit)
        for replicate_index in range(spec.replicates)
    )
    result = SimulationResult(
        session_id=spec.session_id,
        spec_hash=spec.content_hash,
        engine_id=ENGINE_ID,
        engine_version=ENGINE_VERSION,
        replicates=replicates,
    )
    try:
        result.bind_spec(spec)
    except SimulationModelError as exc:
        raise SimulationEngineError("simulation engine produced an invalid result") from exc
    return result
