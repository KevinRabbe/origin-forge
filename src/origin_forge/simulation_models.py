from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .ids import IdKind, new_id, validate_id
from .runtime_observation_models import content_hash


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}$")
_MAX_VARIABLES = 128
_MAX_RULES = 256
_MAX_INVARIANTS = 256
_MAX_REPLICATES = 256
_MAX_STEPS = 10_000
_MAX_WORK_UNITS = 5_000_000
_MAX_VIOLATIONS_PER_REPLICATE = 1024
_MAX_TOTAL_STORED_VIOLATIONS = 8192
_STATE_MIN = -2_147_483_648
_STATE_MAX = 2_147_483_647
_MAX_QUANTITY = 1_000_000_000
_MAX_SEED = 9_223_372_036_854_775_807


class SimulationModelError(ValueError):
    pass


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise SimulationModelError(f"{label} must be a bounded identity token")
    return value


def _bounded_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SimulationModelError(f"{label} must be from {minimum} to {maximum}")
    return value


def _normalize_pairs(
    values: Iterable[tuple[str, int]],
    *,
    label: str,
    minimum: int,
    maximum: int,
    max_entries: int = _MAX_VARIABLES,
    allow_empty: bool = True,
) -> tuple[tuple[str, int], ...]:
    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, tuple) or len(raw) != 2:
            raise SimulationModelError(f"{label} entries must be (name, value) tuples")
        name, value = raw
        name = _token(name, f"{label} name")
        _bounded_int(value, f"{label} value", minimum, maximum)
        if name in seen:
            raise SimulationModelError(f"{label} contains duplicate variable {name}")
        seen.add(name)
        normalized.append((name, value))
    if not allow_empty and not normalized:
        raise SimulationModelError(f"{label} may not be empty")
    if len(normalized) > max_entries:
        raise SimulationModelError(f"{label} exceeds entry limit")
    return tuple(sorted(normalized))


def _pairs_dict(values: tuple[tuple[str, int], ...]) -> dict[str, int]:
    return {name: value for name, value in values}


@dataclass(frozen=True)
class SimulationRule:
    rule_id: str
    priority: int
    probability_ppm: int
    requires: tuple[tuple[str, int], ...] = ()
    consume: tuple[tuple[str, int], ...] = ()
    produce: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _token(self.rule_id, "rule_id"))
        _bounded_int(self.priority, "rule priority", -1000, 1000)
        _bounded_int(self.probability_ppm, "rule probability_ppm", 0, 1_000_000)
        object.__setattr__(
            self,
            "requires",
            _normalize_pairs(
                self.requires,
                label="rule requires",
                minimum=_STATE_MIN,
                maximum=_STATE_MAX,
            ),
        )
        object.__setattr__(
            self,
            "consume",
            _normalize_pairs(
                self.consume,
                label="rule consume",
                minimum=0,
                maximum=_MAX_QUANTITY,
            ),
        )
        object.__setattr__(
            self,
            "produce",
            _normalize_pairs(
                self.produce,
                label="rule produce",
                minimum=0,
                maximum=_MAX_QUANTITY,
            ),
        )
        if not self.consume and not self.produce:
            raise SimulationModelError("simulation rule must consume or produce state")

    def referenced_variables(self) -> set[str]:
        return {
            name
            for values in (self.requires, self.consume, self.produce)
            for name, _ in values
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "priority": self.priority,
            "probability_ppm": self.probability_ppm,
            "requires": _pairs_dict(self.requires),
            "consume": _pairs_dict(self.consume),
            "produce": _pairs_dict(self.produce),
        }


@dataclass(frozen=True)
class SimulationInvariant:
    invariant_id: str
    variable: str
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invariant_id", _token(self.invariant_id, "invariant_id")
        )
        object.__setattr__(self, "variable", _token(self.variable, "invariant variable"))
        if self.minimum is None and self.maximum is None:
            raise SimulationModelError("simulation invariant requires a minimum or maximum")
        if self.minimum is not None:
            _bounded_int(self.minimum, "invariant minimum", _STATE_MIN, _STATE_MAX)
        if self.maximum is not None:
            _bounded_int(self.maximum, "invariant maximum", _STATE_MIN, _STATE_MAX)
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise SimulationModelError("invariant minimum exceeds maximum")

    def to_dict(self) -> dict[str, object]:
        return {
            "invariant_id": self.invariant_id,
            "variable": self.variable,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class SimulationSpec:
    spec_id: str
    session_id: str
    workspace_id: str
    engine_id: str
    engine_version: str
    seed: int
    replicates: int
    max_steps: int
    stall_steps: int
    initial_state: tuple[tuple[str, int], ...]
    rules: tuple[SimulationRule, ...]
    invariants: tuple[SimulationInvariant, ...] = ()

    def __post_init__(self) -> None:
        if not validate_id(self.spec_id, IdKind.SIMULATION_SPEC):
            raise SimulationModelError("spec_id must be a SIMSPEC ID")
        if not validate_id(self.session_id, IdKind.SIMULATION_SESSION):
            raise SimulationModelError("session_id must be a SIM ID")
        if not validate_id(self.workspace_id, IdKind.SIMULATION_WORKSPACE):
            raise SimulationModelError("workspace_id must be a SIMWS ID")
        object.__setattr__(self, "engine_id", _token(self.engine_id, "engine_id"))
        object.__setattr__(
            self, "engine_version", _token(self.engine_version, "engine_version")
        )
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
            unknown = rule.referenced_variables() - variables
            if unknown:
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

        # Upper-bound the implemented Python work rather than only rule count.
        # The factors include eligibility, original-value tracking, mutation,
        # range/min/max bookkeeping and per-step progress comparison for fields
        # a firing may touch. Invariant checks are charged independently.
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
        work_units = self.replicates * per_replicate_work
        if work_units > _MAX_WORK_UNITS:
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
        engine_id: str = "origin-forge-deterministic-sim",
        engine_version: str = "1",
    ) -> "SimulationSpec":
        return cls(
            spec_id=new_id(IdKind.SIMULATION_SPEC),
            session_id=new_id(IdKind.SIMULATION_SESSION),
            workspace_id=new_id(IdKind.SIMULATION_WORKSPACE),
            engine_id=engine_id,
            engine_version=engine_version,
            seed=seed,
            replicates=replicates,
            max_steps=max_steps,
            stall_steps=stall_steps,
            initial_state=tuple(initial_state),
            rules=tuple(rules),
            invariants=tuple(invariants),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_id": self.spec_id,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
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


@dataclass(frozen=True)
class SimulationViolation:
    invariant_id: str
    variable: str
    checkpoint: int
    observed: int
    minimum: int | None
    maximum: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invariant_id", _token(self.invariant_id, "violation invariant_id")
        )
        object.__setattr__(self, "variable", _token(self.variable, "violation variable"))
        _bounded_int(self.checkpoint, "violation checkpoint", 0, _MAX_STEPS)
        _bounded_int(self.observed, "violation observed", _STATE_MIN, _STATE_MAX)
        if self.minimum is not None:
            _bounded_int(self.minimum, "violation minimum", _STATE_MIN, _STATE_MAX)
        if self.maximum is not None:
            _bounded_int(self.maximum, "violation maximum", _STATE_MIN, _STATE_MAX)

    def to_dict(self) -> dict[str, object]:
        return {
            "invariant_id": self.invariant_id,
            "variable": self.variable,
            "checkpoint": self.checkpoint,
            "observed": self.observed,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class SimulationReplicateResult:
    replicate_index: int
    steps_executed: int
    stalled: bool
    final_state: tuple[tuple[str, int], ...]
    minimum_state: tuple[tuple[str, int], ...]
    maximum_state: tuple[tuple[str, int], ...]
    rule_attempts: tuple[tuple[str, int], ...]
    rule_firings: tuple[tuple[str, int], ...]
    violation_count: int
    violations: tuple[SimulationViolation, ...]
    violations_truncated: bool

    def __post_init__(self) -> None:
        _bounded_int(self.replicate_index, "replicate_index", 0, _MAX_REPLICATES - 1)
        _bounded_int(self.steps_executed, "steps_executed", 0, _MAX_STEPS)
        if type(self.stalled) is not bool or type(self.violations_truncated) is not bool:
            raise SimulationModelError("replicate boolean fields must be bool")
        for field_name in ("final_state", "minimum_state", "maximum_state"):
            object.__setattr__(
                self,
                field_name,
                _normalize_pairs(
                    getattr(self, field_name),
                    label=field_name,
                    minimum=_STATE_MIN,
                    maximum=_STATE_MAX,
                    allow_empty=False,
                ),
            )
        for field_name in ("rule_attempts", "rule_firings"):
            object.__setattr__(
                self,
                field_name,
                _normalize_pairs(
                    getattr(self, field_name),
                    label=field_name,
                    minimum=0,
                    maximum=_MAX_STEPS,
                    max_entries=_MAX_RULES,
                    allow_empty=False,
                ),
            )
        _bounded_int(
            self.violation_count,
            "violation_count",
            0,
            _MAX_INVARIANTS * (_MAX_STEPS + 1),
        )
        violations = tuple(self.violations)
        if len(violations) > _MAX_VIOLATIONS_PER_REPLICATE:
            raise SimulationModelError("stored violations exceed v1 limit")
        if not all(isinstance(value, SimulationViolation) for value in violations):
            raise SimulationModelError("violations must contain SimulationViolation objects")
        object.__setattr__(self, "violations", violations)
        if self.violation_count < len(violations):
            raise SimulationModelError("violation_count is smaller than stored violations")
        if self.violations_truncated != (self.violation_count > len(violations)):
            raise SimulationModelError("violations_truncated disagrees with violation_count")

    def to_dict(self) -> dict[str, object]:
        return {
            "replicate_index": self.replicate_index,
            "steps_executed": self.steps_executed,
            "stalled": self.stalled,
            "final_state": _pairs_dict(self.final_state),
            "minimum_state": _pairs_dict(self.minimum_state),
            "maximum_state": _pairs_dict(self.maximum_state),
            "rule_attempts": _pairs_dict(self.rule_attempts),
            "rule_firings": _pairs_dict(self.rule_firings),
            "violation_count": self.violation_count,
            "violations": [value.to_dict() for value in self.violations],
            "violations_truncated": self.violations_truncated,
        }


@dataclass(frozen=True)
class SimulationResult:
    session_id: str
    spec_hash: str
    engine_id: str
    engine_version: str
    replicates: tuple[SimulationReplicateResult, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.session_id, IdKind.SIMULATION_SESSION):
            raise SimulationModelError("result session_id must be a SIM ID")
        if not isinstance(self.spec_hash, str) or not self.spec_hash.startswith("sha256:"):
            raise SimulationModelError("result spec_hash must be a sha256 content hash")
        if len(self.spec_hash) != 71:
            raise SimulationModelError("result spec_hash has invalid length")
        try:
            int(self.spec_hash[7:], 16)
        except ValueError as exc:
            raise SimulationModelError("result spec_hash is not hexadecimal") from exc
        object.__setattr__(self, "engine_id", _token(self.engine_id, "result engine_id"))
        object.__setattr__(
            self, "engine_version", _token(self.engine_version, "result engine_version")
        )
        replicates = tuple(self.replicates)
        if not replicates or len(replicates) > _MAX_REPLICATES:
            raise SimulationModelError("result replicates are outside bounds")
        if not all(isinstance(value, SimulationReplicateResult) for value in replicates):
            raise SimulationModelError(
                "result replicates must contain SimulationReplicateResult objects"
            )
        if [value.replicate_index for value in replicates] != list(range(len(replicates))):
            raise SimulationModelError("result replicate indexes must be contiguous from zero")
        object.__setattr__(self, "replicates", replicates)

    def bind_spec(self, spec: SimulationSpec) -> None:
        if not isinstance(spec, SimulationSpec):
            raise TypeError("spec must be a SimulationSpec")
        if (
            self.session_id != spec.session_id
            or self.spec_hash != spec.content_hash
            or self.engine_id != spec.engine_id
            or self.engine_version != spec.engine_version
            or len(self.replicates) != spec.replicates
        ):
            raise SimulationModelError("simulation result does not bind exact specification")

        expected_state_names = tuple(name for name, _ in spec.initial_state)
        expected_rule_ids = tuple(sorted(rule.rule_id for rule in spec.rules))
        initial_state = dict(spec.initial_state)
        invariant_by_id = {value.invariant_id: value for value in spec.invariants}

        for replicate in self.replicates:
            if replicate.steps_executed > spec.max_steps:
                raise SimulationModelError("replicate exceeds spec max_steps")

            state_maps: list[dict[str, int]] = []
            for values in (
                replicate.final_state,
                replicate.minimum_state,
                replicate.maximum_state,
            ):
                if tuple(name for name, _ in values) != expected_state_names:
                    raise SimulationModelError(
                        "replicate state variables differ from specification"
                    )
                state_maps.append(dict(values))
            final_state, minimum_state, maximum_state = state_maps
            for name in expected_state_names:
                if not (
                    minimum_state[name]
                    <= initial_state[name]
                    <= maximum_state[name]
                    and minimum_state[name]
                    <= final_state[name]
                    <= maximum_state[name]
                ):
                    raise SimulationModelError(
                        "replicate state extrema do not contain initial/final state"
                    )

            metric_maps: list[dict[str, int]] = []
            for values in (replicate.rule_attempts, replicate.rule_firings):
                if tuple(name for name, _ in values) != expected_rule_ids:
                    raise SimulationModelError(
                        "replicate rule metrics differ from specification"
                    )
                metric_maps.append(dict(values))
            attempts, firings = metric_maps
            for rule_id in expected_rule_ids:
                if not (
                    0
                    <= firings[rule_id]
                    <= attempts[rule_id]
                    <= replicate.steps_executed
                ):
                    raise SimulationModelError(
                        "replicate rule firing/attempt counts are inconsistent"
                    )

            possible_violations = len(spec.invariants) * (replicate.steps_executed + 1)
            if replicate.violation_count > possible_violations:
                raise SimulationModelError(
                    "replicate violation_count exceeds possible invariant checkpoints"
                )
            violation_keys: list[tuple[int, str]] = []
            for violation in replicate.violations:
                invariant = invariant_by_id.get(violation.invariant_id)
                if invariant is None:
                    raise SimulationModelError(
                        "replicate violation references unknown invariant"
                    )
                if (
                    violation.variable != invariant.variable
                    or violation.minimum != invariant.minimum
                    or violation.maximum != invariant.maximum
                ):
                    raise SimulationModelError(
                        "replicate violation differs from declared invariant"
                    )
                if violation.checkpoint > replicate.steps_executed:
                    raise SimulationModelError(
                        "replicate violation checkpoint exceeds executed steps"
                    )
                actually_violated = (
                    invariant.minimum is not None
                    and violation.observed < invariant.minimum
                ) or (
                    invariant.maximum is not None
                    and violation.observed > invariant.maximum
                )
                if not actually_violated:
                    raise SimulationModelError(
                        "replicate violation does not violate its declared invariant"
                    )
                violation_keys.append((violation.checkpoint, violation.invariant_id))
            if len(set(violation_keys)) != len(violation_keys):
                raise SimulationModelError("replicate contains duplicate stored violations")
            if violation_keys != sorted(violation_keys):
                raise SimulationModelError(
                    "replicate stored violations are not in canonical order"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "spec_hash": self.spec_hash,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "replicates": [value.to_dict() for value in self.replicates],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


MAX_STORED_VIOLATIONS = _MAX_VIOLATIONS_PER_REPLICATE
MAX_TOTAL_STORED_VIOLATIONS = _MAX_TOTAL_STORED_VIOLATIONS
STATE_MIN = _STATE_MIN
STATE_MAX = _STATE_MAX
