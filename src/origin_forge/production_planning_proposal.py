from __future__ import annotations

import json
from typing import Any

from .production_planning_models import (
    PlanProposal,
    PlanStep,
    PlanningInput,
    ProductionPlanningModelError,
)


_MAX_PROPOSAL_BYTES = 256 * 1024


class PlanProposalParseError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanProposalParseError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded_raw_json(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        if len(raw) > _MAX_PROPOSAL_BYTES:
            raise PlanProposalParseError("plan proposal exceeds byte limit")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlanProposalParseError("plan proposal must be UTF-8 JSON") from exc
    if not isinstance(raw, str):
        raise TypeError("plan proposal must be str or bytes")
    if len(raw.encode("utf-8")) > _MAX_PROPOSAL_BYTES:
        raise PlanProposalParseError("plan proposal exceeds byte limit")
    return raw


def parse_plan_proposal(
    raw: str | bytes,
    *,
    planning_input: PlanningInput,
) -> PlanProposal:
    """Parse proposal-only Planner output under an infrastructure-owned input."""

    if not isinstance(planning_input, PlanningInput):
        raise TypeError("planning_input must be a PlanningInput")

    text = _bounded_raw_json(raw)
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except PlanProposalParseError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise PlanProposalParseError("plan proposal is invalid bounded JSON") from exc

    if not isinstance(value, dict) or set(value) != {"summary", "steps"}:
        raise PlanProposalParseError("plan proposal must contain exactly summary and steps")
    if not isinstance(value["summary"], str) or not isinstance(value["steps"], list):
        raise PlanProposalParseError("plan proposal summary/steps types are invalid")
    if not value["steps"] or len(value["steps"]) > 64:
        raise PlanProposalParseError("plan proposal step count is outside bounds")

    steps: list[PlanStep] = []
    try:
        for index, item in enumerate(value["steps"]):
            required_fields = {
                "step_key",
                "objective",
                "acceptance_criteria",
                "constraints",
                "required_capabilities",
                "priority",
                "budget_hint",
                "depends_on",
            }
            if not isinstance(item, dict) or set(item) != required_fields:
                raise PlanProposalParseError(f"step {index} has unsupported fields")
            for field in ("step_key", "objective"):
                if not isinstance(item[field], str):
                    raise PlanProposalParseError(f"step {index} {field} is invalid")
            for field in (
                "acceptance_criteria",
                "constraints",
                "required_capabilities",
                "depends_on",
            ):
                if not isinstance(item[field], list) or any(
                    not isinstance(v, str) for v in item[field]
                ):
                    raise PlanProposalParseError(f"step {index} {field} is invalid")
            if type(item["priority"]) is not int:
                raise PlanProposalParseError(f"step {index} priority is invalid")
            budget = item["budget_hint"]
            if (
                not isinstance(budget, dict)
                or set(budget) != {"attempts"}
                or type(budget["attempts"]) is not int
            ):
                raise PlanProposalParseError(f"step {index} budget_hint is invalid")
            steps.append(
                PlanStep(
                    step_key=item["step_key"],
                    objective=item["objective"],
                    acceptance_criteria=tuple(item["acceptance_criteria"]),
                    constraints=tuple(item["constraints"]),
                    required_capabilities=tuple(item["required_capabilities"]),
                    priority=item["priority"],
                    max_attempts=budget["attempts"],
                    depends_on=tuple(item["depends_on"]),
                )
            )
        return PlanProposal.create(
            planning_input=planning_input,
            summary=value["summary"],
            steps=tuple(steps),
        )
    except PlanProposalParseError:
        raise
    except (ProductionPlanningModelError, TypeError, ValueError) as exc:
        raise PlanProposalParseError("plan proposal failed governed validation") from exc
