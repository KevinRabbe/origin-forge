from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}$")
_STEP_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT_CHARS = 4096
_MAX_ITEM_TEXT_CHARS = 2048
_MAX_EVIDENCE_REFS = 128
_MAX_CAPABILITIES = 64
_MAX_STEPS = 64
_MAX_EDGES = 192
_MAX_DEPTH = 16
_MAX_ACCEPTANCE = 32
_MAX_CONSTRAINTS = 32
_MAX_STEP_CAPABILITIES = 16
_MAX_ATTEMPTS = 16


class ProductionPlanningModelError(ValueError):
    pass


class PlanAuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionPlanningModelError("planning data is not canonical JSON") from exc


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProductionPlanningModelError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ProductionPlanningModelError(f"{label} must be a bounded identity token")
    return value


def _step_key(value: str, label: str = "step_key") -> str:
    if not isinstance(value, str) or not _STEP_KEY_RE.fullmatch(value):
        raise ProductionPlanningModelError(f"{label} must be a bounded proposal-local key")
    return value


def _exact_int(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProductionPlanningModelError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _text(value: str, label: str, *, maximum: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionPlanningModelError(f"{label} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ProductionPlanningModelError(f"{label} exceeds character limit")
    return normalized


def _text_items(
    values: Iterable[str],
    label: str,
    *,
    maximum_items: int,
    require_one: bool = False,
) -> tuple[str, ...]:
    items = tuple(values)
    if len(items) > maximum_items or (require_one and not items):
        raise ProductionPlanningModelError(f"{label} are outside bounds")
    normalized = tuple(_text(v, label, maximum=_MAX_ITEM_TEXT_CHARS) for v in items)
    if len(normalized) != len(set(normalized)):
        raise ProductionPlanningModelError(f"{label} contain duplicates")
    return normalized


@dataclass(frozen=True)
class PlanningEvidenceRef:
    ref_id: str
    content_hash: str
    revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _token(self.ref_id, "evidence ref_id"))
        _sha256(self.content_hash, "evidence content_hash")
        if self.revision is not None:
            _exact_int(self.revision, "evidence revision", 0, 2_147_483_647)

    @property
    def key(self) -> tuple[str, str, int]:
        return (
            self.ref_id,
            self.content_hash,
            -1 if self.revision is None else self.revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class PlanningInput:
    planning_input_id: str
    project_id: str
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    verified_state_refs: tuple[PlanningEvidenceRef, ...]
    active_design_rule_refs: tuple[PlanningEvidenceRef, ...]
    project_intelligence_hash: str
    capability_catalog_hash: str
    capability_ids: tuple[str, ...]
    model_policy_hash: str
    resource_policy_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.planning_input_id, IdKind.PLANNING_INPUT):
            raise ProductionPlanningModelError("planning_input_id must be a PLINPUT ID")
        if not validate_id(self.project_id, IdKind.PROJECT):
            raise ProductionPlanningModelError("project_id must be a PROJECT ID")
        if not validate_id(self.goal_id, IdKind.GOAL):
            raise ProductionPlanningModelError("goal_id must be a GOAL ID")
        _exact_int(self.goal_revision, "goal_revision", 0, 2_147_483_647)
        for field in (
            "goal_content_hash",
            "project_intelligence_hash",
            "capability_catalog_hash",
            "model_policy_hash",
            "resource_policy_hash",
        ):
            _sha256(getattr(self, field), field)

        verified = tuple(self.verified_state_refs)
        rules = tuple(self.active_design_rule_refs)
        for label, refs in (
            ("verified_state_refs", verified),
            ("active_design_rule_refs", rules),
        ):
            if len(refs) > _MAX_EVIDENCE_REFS or not all(
                isinstance(v, PlanningEvidenceRef) for v in refs
            ):
                raise ProductionPlanningModelError(f"{label} are outside bounds")
            keys = [v.key for v in refs]
            if len(keys) != len(set(keys)):
                raise ProductionPlanningModelError(f"{label} contain duplicates")
        object.__setattr__(self, "verified_state_refs", tuple(sorted(verified, key=lambda v: v.key)))
        object.__setattr__(self, "active_design_rule_refs", tuple(sorted(rules, key=lambda v: v.key)))

        capabilities = tuple(_token(v, "capability_id") for v in self.capability_ids)
        if not capabilities or len(capabilities) > _MAX_CAPABILITIES:
            raise ProductionPlanningModelError("capability_ids are outside bounds")
        if len(capabilities) != len(set(capabilities)):
            raise ProductionPlanningModelError("capability_ids contain duplicates")
        object.__setattr__(self, "capability_ids", tuple(sorted(capabilities)))

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        goal_id: str,
        goal_revision: int,
        goal_content_hash: str,
        verified_state_refs: Iterable[PlanningEvidenceRef] = (),
        active_design_rule_refs: Iterable[PlanningEvidenceRef] = (),
        project_intelligence_hash: str,
        capability_catalog_hash: str,
        capability_ids: Iterable[str],
        model_policy_hash: str,
        resource_policy_hash: str,
    ) -> "PlanningInput":
        return cls(
            planning_input_id=new_id(IdKind.PLANNING_INPUT),
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            goal_content_hash=goal_content_hash,
            verified_state_refs=tuple(verified_state_refs),
            active_design_rule_refs=tuple(active_design_rule_refs),
            project_intelligence_hash=project_intelligence_hash,
            capability_catalog_hash=capability_catalog_hash,
            capability_ids=tuple(capability_ids),
            model_policy_hash=model_policy_hash,
            resource_policy_hash=resource_policy_hash,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "planning_input_id": self.planning_input_id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "verified_state_refs": [v.to_dict() for v in self.verified_state_refs],
            "active_design_rule_refs": [v.to_dict() for v in self.active_design_rule_refs],
            "project_intelligence_hash": self.project_intelligence_hash,
            "capability_catalog_hash": self.capability_catalog_hash,
            "capability_ids": list(self.capability_ids),
            "model_policy_hash": self.model_policy_hash,
            "resource_policy_hash": self.resource_policy_hash,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self.to_dict())


@dataclass(frozen=True)
class PlanStep:
    step_key: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    priority: int = 0
    max_attempts: int = 1
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_key", _step_key(self.step_key))
        object.__setattr__(self, "objective", _text(self.objective, "objective"))
        object.__setattr__(
            self,
            "acceptance_criteria",
            _text_items(
                self.acceptance_criteria,
                "acceptance_criteria",
                maximum_items=_MAX_ACCEPTANCE,
                require_one=True,
            ),
        )
        object.__setattr__(
            self,
            "constraints",
            _text_items(
                self.constraints,
                "constraints",
                maximum_items=_MAX_CONSTRAINTS,
            ),
        )
        capabilities = tuple(_token(v, "required_capability") for v in self.required_capabilities)
        if len(capabilities) > _MAX_STEP_CAPABILITIES:
            raise ProductionPlanningModelError("required_capabilities are outside bounds")
        if len(capabilities) != len(set(capabilities)):
            raise ProductionPlanningModelError("required_capabilities contain duplicates")
        object.__setattr__(self, "required_capabilities", tuple(sorted(capabilities)))
        _exact_int(self.priority, "priority", -1000, 1000)
        _exact_int(self.max_attempts, "max_attempts", 1, _MAX_ATTEMPTS)
        dependencies = tuple(_step_key(v, "dependency step_key") for v in self.depends_on)
        if len(dependencies) > _MAX_STEPS - 1:
            raise ProductionPlanningModelError("depends_on is outside bounds")
        if len(dependencies) != len(set(dependencies)):
            raise ProductionPlanningModelError("depends_on contains duplicates")
        if self.step_key in dependencies:
            raise ProductionPlanningModelError("step cannot depend on itself")
        object.__setattr__(self, "depends_on", tuple(sorted(dependencies)))

    def to_dict(self) -> dict[str, object]:
        return {
            "step_key": self.step_key,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "required_capabilities": list(self.required_capabilities),
            "priority": self.priority,
            "budget_hint": {"attempts": self.max_attempts},
            "depends_on": list(self.depends_on),
        }


def _graph_metrics(steps: tuple[PlanStep, ...]) -> tuple[tuple[str, ...], int, int]:
    if not steps or len(steps) > _MAX_STEPS:
        raise ProductionPlanningModelError("plan steps are outside bounds")
    keys = [v.step_key for v in steps]
    if len(keys) != len(set(keys)):
        raise ProductionPlanningModelError("plan contains duplicate step keys")
    key_set = set(keys)
    edge_count = sum(len(v.depends_on) for v in steps)
    if edge_count > _MAX_EDGES:
        raise ProductionPlanningModelError("plan dependency edge count exceeds limit")

    indegree = {key: 0 for key in keys}
    outgoing: dict[str, list[str]] = {key: [] for key in keys}
    for step in steps:
        for dependency in step.depends_on:
            if dependency not in key_set:
                raise ProductionPlanningModelError(
                    f"plan dependency references unknown step: {dependency}"
                )
            indegree[step.step_key] += 1
            outgoing[dependency].append(step.step_key)

    ready = sorted(key for key, count in indegree.items() if count == 0)
    depth = {key: 1 for key in ready}
    order: list[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child in sorted(outgoing[key]):
            depth[child] = max(depth.get(child, 1), depth[key] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()

    if len(order) != len(steps):
        raise ProductionPlanningModelError("plan dependency graph contains a cycle")
    max_depth = max(depth.values(), default=0)
    if max_depth > _MAX_DEPTH:
        raise ProductionPlanningModelError("plan dependency depth exceeds limit")
    return tuple(order), edge_count, max_depth


@dataclass(frozen=True)
class PlanProposal:
    proposal_id: str
    planning_input_id: str
    planning_input_hash: str
    summary: str
    steps: tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.proposal_id, IdKind.PLAN_PROPOSAL):
            raise ProductionPlanningModelError("proposal_id must be a PLPROP ID")
        if not validate_id(self.planning_input_id, IdKind.PLANNING_INPUT):
            raise ProductionPlanningModelError("planning_input_id must be a PLINPUT ID")
        _sha256(self.planning_input_hash, "planning_input_hash")
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        steps = tuple(self.steps)
        if not all(isinstance(v, PlanStep) for v in steps):
            raise ProductionPlanningModelError("plan steps are invalid")
        steps = tuple(sorted(steps, key=lambda v: v.step_key))
        _graph_metrics(steps)
        object.__setattr__(self, "steps", steps)

    @classmethod
    def create(
        cls,
        *,
        planning_input: PlanningInput,
        summary: str,
        steps: Iterable[PlanStep],
    ) -> "PlanProposal":
        if not isinstance(planning_input, PlanningInput):
            raise TypeError("planning_input must be a PlanningInput")
        proposal = cls(
            proposal_id=new_id(IdKind.PLAN_PROPOSAL),
            planning_input_id=planning_input.planning_input_id,
            planning_input_hash=planning_input.content_hash,
            summary=summary,
            steps=tuple(steps),
        )
        proposal.bind(planning_input)
        return proposal

    def bind(self, planning_input: PlanningInput) -> None:
        if not isinstance(planning_input, PlanningInput):
            raise TypeError("planning_input must be a PlanningInput")
        if self.planning_input_id != planning_input.planning_input_id:
            raise ProductionPlanningModelError("proposal planning_input_id does not match")
        if self.planning_input_hash != planning_input.content_hash:
            raise ProductionPlanningModelError("proposal planning_input_hash does not match")
        allowed = set(planning_input.capability_ids)
        for step in self.steps:
            unknown = sorted(set(step.required_capabilities) - allowed)
            if unknown:
                raise ProductionPlanningModelError(
                    f"step {step.step_key} requests unknown capabilities: {', '.join(unknown)}"
                )

    @property
    def topological_step_keys(self) -> tuple[str, ...]:
        return _graph_metrics(self.steps)[0]

    @property
    def edge_count(self) -> int:
        return _graph_metrics(self.steps)[1]

    @property
    def max_depth(self) -> int:
        return _graph_metrics(self.steps)[2]

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "summary": self.summary,
            "steps": [v.to_dict() for v in self.steps],
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self.to_dict())


@dataclass(frozen=True)
class PlanAudit:
    audit_id: str
    planning_input_id: str
    planning_input_hash: str
    proposal_id: str
    proposal_hash: str
    status: PlanAuditStatus
    task_count: int
    edge_count: int
    max_depth: int
    topological_step_keys: tuple[str, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.audit_id, IdKind.PLAN_AUDIT):
            raise ProductionPlanningModelError("audit_id must be a PLAUD ID")
        if not validate_id(self.planning_input_id, IdKind.PLANNING_INPUT):
            raise ProductionPlanningModelError("planning_input_id must be a PLINPUT ID")
        if not validate_id(self.proposal_id, IdKind.PLAN_PROPOSAL):
            raise ProductionPlanningModelError("proposal_id must be a PLPROP ID")
        _sha256(self.planning_input_hash, "planning_input_hash")
        _sha256(self.proposal_hash, "proposal_hash")
        if not isinstance(self.status, PlanAuditStatus):
            raise ProductionPlanningModelError("audit status is invalid")
        _exact_int(self.task_count, "task_count", 1, _MAX_STEPS)
        _exact_int(self.edge_count, "edge_count", 0, _MAX_EDGES)
        _exact_int(self.max_depth, "max_depth", 1, _MAX_DEPTH)
        order = tuple(_step_key(v, "topological step_key") for v in self.topological_step_keys)
        if len(order) != self.task_count or len(order) != len(set(order)):
            raise ProductionPlanningModelError("topological_step_keys are inconsistent")
        object.__setattr__(self, "topological_step_keys", order)
        if self.status is PlanAuditStatus.PASS:
            if self.failure_reason is not None:
                raise ProductionPlanningModelError("passing audit cannot contain failure_reason")
        else:
            object.__setattr__(self, "failure_reason", _text(self.failure_reason or "", "failure_reason"))

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "status": self.status.value,
            "task_count": self.task_count,
            "edge_count": self.edge_count,
            "max_depth": self.max_depth,
            "topological_step_keys": list(self.topological_step_keys),
            "failure_reason": self.failure_reason,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self.to_dict())


def audit_plan(planning_input: PlanningInput, proposal: PlanProposal) -> PlanAudit:
    if not isinstance(planning_input, PlanningInput):
        raise TypeError("planning_input must be a PlanningInput")
    if not isinstance(proposal, PlanProposal):
        raise TypeError("proposal must be a PlanProposal")
    order, edge_count, max_depth = _graph_metrics(proposal.steps)
    status = PlanAuditStatus.PASS
    reason: str | None = None
    try:
        proposal.bind(planning_input)
    except ProductionPlanningModelError:
        status = PlanAuditStatus.FAIL
        reason = "proposal failed exact planning-input binding"
    return PlanAudit(
        audit_id=new_id(IdKind.PLAN_AUDIT),
        planning_input_id=planning_input.planning_input_id,
        planning_input_hash=planning_input.content_hash,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal.content_hash,
        status=status,
        task_count=len(proposal.steps),
        edge_count=edge_count,
        max_depth=max_depth,
        topological_step_keys=order,
        failure_reason=reason,
    )
