from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .model import ModelAdapter, ModelRequest, ModelResponse
from .production_planning_evidence import (
    ProductionPlanningEvidenceError,
    ProductionPlanningEvidenceStore,
    goal_planning_hash,
)
from .production_planning_models import PlanProposal, PlanningInput
from .production_planning_proposal import parse_plan_proposal
from .runs import create_run, finish_run
from .runtime import OriginForgeRuntime
from .scheduled_model_adapter import ScheduledModelAdapter
from .state import RunStatus


PLANNER_INSTRUCTIONS = """You are the Origin Forge bounded production Planner.
You receive one frozen Goal planning input and an infrastructure-owned capability catalog.
Return exactly one JSON object matching the supplied plan schema.
Use proposal-local step_key values only; never invent canonical FLOW, TASK, RUN, VERIFY, ART, or other Origin Forge IDs.
Describe finite bounded Tasks, acceptance criteria, constraints, required capabilities, priorities, attempt hints, and explicit dependency keys.
Do not claim any Task is approved, materialized, running, verified, complete, adopted, signed, merged, or released.
Do not emit code, shell commands, SQL, tool calls, callbacks, loops, or hidden executable predicates.
A valid response is a proposal only. Infrastructure independently validates and may later materialize it under separate explicit authority.
"""


PLAN_PROPOSAL_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "steps"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 4096},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "step_key",
                    "objective",
                    "acceptance_criteria",
                    "constraints",
                    "required_capabilities",
                    "priority",
                    "budget_hint",
                    "depends_on",
                ],
                "properties": {
                    "step_key": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                    },
                    "objective": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "acceptance_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "constraints": {
                        "type": "array",
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "required_capabilities": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$",
                        },
                    },
                    "priority": {"type": "integer", "minimum": -1000, "maximum": 1000},
                    "budget_hint": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["attempts"],
                        "properties": {
                            "attempts": {"type": "integer", "minimum": 1, "maximum": 16}
                        },
                    },
                    "depends_on": {
                        "type": "array",
                        "maxItems": 63,
                        "items": {
                            "type": "string",
                            "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                        },
                    },
                },
            },
        },
    },
}


class ProductionPlannerError(RuntimeError):
    pass


def _canonical_hash(value: object) -> str:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionPlannerError("Planner request evidence is not canonical JSON") from exc
    return hashlib.sha256(data).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class DeterministicPlannerAdapter:
    """No-I/O adapter for deterministic tests/manual proposal evidence only."""

    response_text: str
    fixture_model_id: str = "deterministic-planner-fixture"
    input_tokens: int | None = None
    output_tokens: int | None = None
    call_count: int = 0
    last_request: ModelRequest | None = None

    @property
    def model_id(self) -> str:
        return self.fixture_model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        self.call_count += 1
        self.last_request = request
        return ModelResponse(
            text=self.response_text,
            model_id=self.fixture_model_id,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


@dataclass(frozen=True)
class PlannerResult:
    run_id: str
    planning_input_id: str
    planning_input_hash: str
    request_hash: str
    response_hash: str
    proposal: PlanProposal
    verification_id: str
    model_id: str
    model_hash: str | None


class BoundedProductionPlanner:
    """One-shot proposal-only Planner over frozen durable planning evidence."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        *,
        evidence_store: ProductionPlanningEvidenceStore | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(model, (ScheduledModelAdapter, DeterministicPlannerAdapter)):
            raise TypeError(
                "Planner model must be ScheduledModelAdapter or DeterministicPlannerAdapter"
            )
        self.runtime = runtime
        self.model = model
        self.evidence_store = evidence_store or ProductionPlanningEvidenceStore(runtime)

    def _context(self, planning_input: PlanningInput) -> dict[str, object]:
        project_id = self.runtime.project_id()
        if planning_input.project_id != project_id:
            raise ProductionPlannerError("planning input belongs to another project")
        with self.runtime.store.session() as conn:
            goal = conn.execute(
                "SELECT * FROM goals WHERE id = ? AND project_id = ?",
                (planning_input.goal_id, project_id),
            ).fetchone()
            if goal is None:
                raise KeyError(planning_input.goal_id)
            if (
                int(goal["revision"]) != planning_input.goal_revision
                or goal_planning_hash(goal) != planning_input.goal_content_hash
            ):
                raise ProductionPlannerError("planning input became stale before Planner generation")
            try:
                success = json.loads(goal["success_criteria_json"])
                constraints = json.loads(goal["constraints_json"])
                budgets = json.loads(goal["budgets_json"])
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ProductionPlannerError("Goal planning context is invalid") from exc
            return {
                "planning_input": planning_input.to_dict(),
                "goal": {
                    "id": goal["id"],
                    "revision": int(goal["revision"]),
                    "objective": goal["objective"],
                    "success_criteria": success,
                    "constraints": constraints,
                    "budgets": budgets,
                    "priority": int(goal["priority"]),
                    "status": goal["status"],
                },
            }

    def propose(
        self,
        planning_input_id: str,
        *,
        model_profile: str | None = None,
    ) -> PlannerResult:
        planning_input = self.evidence_store.load_input(planning_input_id)
        context = self._context(planning_input)
        run_id = create_run(
            self.runtime.store,
            None,
            role="PLANNER",
            model_profile=model_profile or self.model.model_id,
        )
        request = ModelRequest(
            run_id=run_id,
            task_id=None,
            instructions=PLANNER_INSTRUCTIONS,
            context=context,
            response_schema=PLAN_PROPOSAL_SCHEMA,
        )
        request_hash = _canonical_hash(
            {
                "run_id": request.run_id,
                "task_id": request.task_id,
                "instructions": request.instructions,
                "context": request.context,
                "response_schema": request.response_schema,
            }
        )
        try:
            response = self.model.generate(request)
            if not isinstance(response, ModelResponse) or not response.model_id:
                raise ProductionPlannerError("Planner model returned an invalid response envelope")
            proposal = parse_plan_proposal(
                response.text,
                planning_input=planning_input,
            )
            self.evidence_store.publish_proposal(proposal)
            response_hash = _text_hash(response.text)
            verification_id = self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="planner-generation",
                verifier="OriginForge.BoundedProductionPlanner",
                status="PASS",
                evidence={
                    "planning_input_id": planning_input.planning_input_id,
                    "planning_input_hash": planning_input.content_hash,
                    "request_hash": request_hash,
                    "response_hash": response_hash,
                    "proposal_id": proposal.proposal_id,
                    "proposal_hash": proposal.content_hash,
                    "model_id": response.model_id,
                    "model_hash": response.model_hash,
                    "materialized": False,
                },
                metrics={
                    "response_bytes": len(response.text.encode("utf-8")),
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model_calls": 1,
                },
                run_id=run_id,
            )
            finish_run(
                self.runtime.store,
                run_id,
                RunStatus.SUCCEEDED,
                input_token_count=response.input_tokens,
                output_token_count=response.output_tokens,
            )
            return PlannerResult(
                run_id=run_id,
                planning_input_id=planning_input.planning_input_id,
                planning_input_hash=planning_input.content_hash,
                request_hash=request_hash,
                response_hash=response_hash,
                proposal=proposal,
                verification_id=verification_id,
                model_id=response.model_id,
                model_hash=response.model_hash,
            )
        except Exception as exc:
            try:
                run = self.runtime.get_run(run_id)
                if run["status"] == RunStatus.RUNNING.value:
                    reason = f"{type(exc).__name__}: {exc}"[:1000]
                    finish_run(
                        self.runtime.store,
                        run_id,
                        RunStatus.FAILED,
                        failure_reason=reason,
                    )
            except Exception:
                pass
            raise
