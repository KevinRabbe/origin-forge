from __future__ import annotations

import json
from typing import Any

from .production_work_order_models import WorkOrderInputRef, content_hash
from .production_work_order_validators import (
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)
from .simulation_models import SimulationInvariant, SimulationModelError, SimulationRule
from .simulation_spec_template import SimulationSpecTemplate


SIMULATION_ADAPTER_ID = "originforge.simulation.deterministic"
SIMULATION_CONTRACT_ID = "simulation.deterministic@1"
SIMULATION_VALIDATOR_ID = "validator.simulation.deterministic@1"
SIMULATION_SCHEMA_ID = "schema.simulation.deterministic@1"
_MAX_JSON_CHARS = 65_536
_MAX_SEED = 9_223_372_036_854_775_807


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DispatchValidatorError(f"duplicate simulation JSON key: {key}")
        value[key] = item
    return value


def _reject_float(_: str) -> object:
    raise DispatchValidatorError("simulation JSON does not permit floating-point values")


def _reject_constant(_: str) -> object:
    raise DispatchValidatorError("simulation JSON does not permit non-finite values")


def _strict_json(text: str, label: str) -> object:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except DispatchValidatorError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DispatchValidatorError(f"{label} is not strict JSON") from exc
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if canonical != text:
        raise DispatchValidatorError(f"{label} must use canonical JSON encoding")
    return value


def _pairs(value: object, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        raise DispatchValidatorError(f"{label} must be a JSON object")
    if any(not isinstance(key, str) for key in value):
        raise DispatchValidatorError(f"{label} keys must be strings")
    return tuple((key, item) for key, item in value.items())


def _rule(value: object) -> SimulationRule:
    keys = {"rule_id", "priority", "probability_ppm", "requires", "consume", "produce"}
    if not isinstance(value, dict) or set(value) != keys:
        raise DispatchValidatorError("simulation rule schema is invalid")
    return SimulationRule(
        rule_id=value["rule_id"],
        priority=value["priority"],
        probability_ppm=value["probability_ppm"],
        requires=_pairs(value["requires"], "simulation rule requires"),
        consume=_pairs(value["consume"], "simulation rule consume"),
        produce=_pairs(value["produce"], "simulation rule produce"),
    )


def _invariant(value: object) -> SimulationInvariant:
    keys = {"invariant_id", "variable", "minimum", "maximum"}
    if not isinstance(value, dict) or set(value) != keys:
        raise DispatchValidatorError("simulation invariant schema is invalid")
    return SimulationInvariant(
        invariant_id=value["invariant_id"],
        variable=value["variable"],
        minimum=value["minimum"],
        maximum=value["maximum"],
    )


class DeterministicSimulationDispatchValidator:
    """Validate one self-contained inert Phase-25 simulation template."""

    _IMPLEMENTATION_ID = "origin-forge-deterministic-simulation-work-order-validator@1"

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=SIMULATION_VALIDATOR_ID,
            payload_schema_id=SIMULATION_SCHEMA_ID,
            fields=(
                PayloadFieldRule("seed", PayloadFieldKind.INTEGER, min_integer=0, max_integer=_MAX_SEED),
                PayloadFieldRule("replicates", PayloadFieldKind.INTEGER, min_integer=1, max_integer=256),
                PayloadFieldRule("max_steps", PayloadFieldKind.INTEGER, min_integer=1, max_integer=10_000),
                PayloadFieldRule("stall_steps", PayloadFieldKind.INTEGER, min_integer=1, max_integer=10_000),
                PayloadFieldRule("initial_state_json", PayloadFieldKind.STRING, max_string_chars=_MAX_JSON_CHARS),
                PayloadFieldRule("rules_json", PayloadFieldKind.STRING, max_string_chars=_MAX_JSON_CHARS),
                PayloadFieldRule("invariants_json", PayloadFieldKind.STRING, max_string_chars=_MAX_JSON_CHARS),
            ),
        )
        self._fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "base_validator_fingerprint": self._base.validator_fingerprint,
                "semantic_contract": {
                    "engine_id": "origin-forge-deterministic-sim",
                    "engine_version": "1",
                    "template": "SimulationSpecTemplate@1",
                    "input_refs": "none",
                    "nested_json": "strict-canonical-no-floats-no-duplicates",
                },
            }
        )

    @property
    def validator_id(self) -> str:
        return self._base.validator_id

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return self._base.payload_schema_id

    @property
    def payload_schema_hash(self) -> str:
        return self._base.payload_schema_hash

    def schema_dict(self) -> dict[str, object]:
        return self._base.schema_dict()

    def template(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...] = (),
    ) -> SimulationSpecTemplate:
        if input_refs:
            raise DispatchValidatorError("deterministic simulation WorkOrder accepts no input refs")
        normalized = self._base.validate(payload, input_refs)
        initial = _strict_json(normalized["initial_state_json"], "initial_state_json")
        rules = _strict_json(normalized["rules_json"], "rules_json")
        invariants = _strict_json(normalized["invariants_json"], "invariants_json")
        if not isinstance(rules, list):
            raise DispatchValidatorError("rules_json must be a JSON array")
        if not isinstance(invariants, list):
            raise DispatchValidatorError("invariants_json must be a JSON array")
        try:
            return SimulationSpecTemplate.create(
                seed=normalized["seed"],
                replicates=normalized["replicates"],
                max_steps=normalized["max_steps"],
                stall_steps=normalized["stall_steps"],
                initial_state=_pairs(initial, "initial_state_json"),
                rules=tuple(_rule(value) for value in rules),
                invariants=tuple(_invariant(value) for value in invariants),
            )
        except (SimulationModelError, TypeError, ValueError) as exc:
            raise DispatchValidatorError("simulation payload violates Phase-25 bounds") from exc

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        template = self.template(payload, input_refs)
        return {
            "seed": template.seed,
            "replicates": template.replicates,
            "max_steps": template.max_steps,
            "stall_steps": template.stall_steps,
            "initial_state_json": json.dumps(dict(template.initial_state), ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True),
            "rules_json": json.dumps([rule.to_dict() for rule in template.rules], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True),
            "invariants_json": json.dumps([value.to_dict() for value in template.invariants], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True),
        }
