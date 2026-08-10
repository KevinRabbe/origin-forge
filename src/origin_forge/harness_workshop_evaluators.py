from __future__ import annotations

from .harness_workshop_models import (
    HarnessWorkshopModelError,
    WorkshopEvaluationPlan,
    WorkshopEvaluatorFamily,
)
from .harness_workshop_skill_adapter import PHASE12_SKILL_PROTOCOL


# Promotion-capable evaluator protocols are infrastructure-owned code, not
# candidate or plan data. v1 intentionally trusts only the existing Phase-12
# Skill benchmark adapter. Other component families may be represented and
# planned, but fail closed for promotion until a separately governed adapter is
# added here together with its own evidence validation.
_TRUSTED_PROTOCOLS: dict[WorkshopEvaluatorFamily, frozenset[str]] = {
    WorkshopEvaluatorFamily.SKILL_BENCHMARK: frozenset({PHASE12_SKILL_PROTOCOL}),
    WorkshopEvaluatorFamily.PROMPT_BENCHMARK: frozenset(),
    WorkshopEvaluatorFamily.CONTEXT_BENCHMARK: frozenset(),
    WorkshopEvaluatorFamily.ROUTING_BENCHMARK: frozenset(),
    WorkshopEvaluatorFamily.SPECIALIST_BENCHMARK: frozenset(),
    WorkshopEvaluatorFamily.MINI_WORKFLOW_BENCHMARK: frozenset(),
}


def trusted_workshop_protocols() -> dict[str, tuple[str, ...]]:
    """Return a read-only serializable snapshot of promotion-capable protocols."""

    return {
        family.value: tuple(sorted(protocols))
        for family, protocols in sorted(
            _TRUSTED_PROTOCOLS.items(), key=lambda item: item[0].value
        )
    }


def is_trusted_workshop_evaluator(plan: WorkshopEvaluationPlan) -> bool:
    if not isinstance(plan, WorkshopEvaluationPlan):
        raise TypeError("plan must be a WorkshopEvaluationPlan")
    return plan.evaluator_protocol in _TRUSTED_PROTOCOLS[plan.evaluator_family]


def require_trusted_workshop_evaluator(plan: WorkshopEvaluationPlan) -> None:
    if not is_trusted_workshop_evaluator(plan):
        raise HarnessWorkshopModelError(
            "workshop evaluation plan has no promotion-capable trusted evaluator adapter"
        )
