from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .ids import IdKind, validate_id


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_MAX_REASON_CHARS = 4096
_MAX_TIMESTAMP_CHARS = 128


class ProductionGoalBootstrapModelError(ValueError):
    pass


class GoalBootstrapStage(StrEnum):
    CLAIMED = "CLAIMED"
    AUTHORITY_PUBLISHED = "AUTHORITY_PUBLISHED"
    PLANNING_INPUT_PUBLISHED = "PLANNING_INPUT_PUBLISHED"
    PLANNER_STARTED = "PLANNER_STARTED"
    PLANNER_RETURNED = "PLANNER_RETURNED"
    PLAN_AUDITED = "PLAN_AUDITED"
    MATERIALIZED = "MATERIALIZED"
    PREPPOL_PUBLISHED = "PREPPOL_PUBLISHED"


class GoalBootstrapStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READY = "READY"
    FAILED_PRE_PLANNER = "FAILED_PRE_PLANNER"
    INTERRUPTED = "INTERRUPTED"


_STAGE_ORDER = {stage: index for index, stage in enumerate(GoalBootstrapStage)}


def _typed_id(value: object, kind: IdKind, label: str) -> str:
    if not isinstance(value, str) or not validate_id(value, kind):
        raise ProductionGoalBootstrapModelError(
            f"{label} must be a valid {kind.value} ID"
        )
    return value


def _optional_typed_id(value: object, kind: IdKind, label: str) -> str | None:
    if value is None:
        return None
    return _typed_id(value, kind, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ProductionGoalBootstrapModelError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _optional_digest(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _digest(value, label)


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ProductionGoalBootstrapModelError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProductionGoalBootstrapModelError(
            f"{label} must be a non-negative integer"
        )
    return value


def _timestamp(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TIMESTAMP_CHARS
        or value.strip() != value
    ):
        raise ProductionGoalBootstrapModelError(f"{label} is invalid")
    return value


def _checkpoint_pair(
    identifier: object,
    digest: object,
    kind: IdKind,
    id_label: str,
    hash_label: str,
) -> tuple[str | None, str | None]:
    if (identifier is None) != (digest is None):
        raise ProductionGoalBootstrapModelError(
            f"{id_label} and {hash_label} must appear together"
        )
    return (
        _optional_typed_id(identifier, kind, id_label),
        _optional_digest(digest, hash_label),
    )


@dataclass(frozen=True)
class GoalBootstrapReceipt:
    bootstrap_id: str
    project_id: str
    goal_id: str
    goal_revision: int
    goal_content_hash: str
    bootstrap_owner_id: str
    bootstrap_owner_fingerprint: str
    bootstrap_contract_version: str
    capability_catalog_id: str | None
    capability_catalog_hash: str | None
    capability_routing_policy_id: str | None
    capability_routing_policy_hash: str | None
    dispatch_contract_catalog_id: str | None
    dispatch_contract_catalog_hash: str | None
    planning_input_id: str | None
    planning_input_hash: str | None
    planner_dependency_plan_hash: str | None
    planner_run_id: str | None
    plan_proposal_id: str | None
    plan_proposal_hash: str | None
    plan_audit_id: str | None
    plan_audit_hash: str | None
    materialization_id: str | None
    materialization_hash: str | None
    preparation_policy_id: str | None
    preparation_policy_hash: str | None
    stage: GoalBootstrapStage
    status: GoalBootstrapStatus
    revision: int
    created_at: str
    updated_at: str
    terminal_reason: str | None

    def __post_init__(self) -> None:
        _typed_id(self.bootstrap_id, IdKind.GOAL_BOOTSTRAP, "bootstrap_id")
        _typed_id(self.project_id, IdKind.PROJECT, "project_id")
        _typed_id(self.goal_id, IdKind.GOAL, "goal_id")
        _nonnegative_int(self.goal_revision, "goal_revision")
        _digest(self.goal_content_hash, "goal_content_hash")
        _identity(self.bootstrap_owner_id, "bootstrap_owner_id")
        _digest(self.bootstrap_owner_fingerprint, "bootstrap_owner_fingerprint")
        _identity(self.bootstrap_contract_version, "bootstrap_contract_version")
        _checkpoint_pair(
            self.capability_catalog_id,
            self.capability_catalog_hash,
            IdKind.CAPABILITY_CATALOG,
            "capability_catalog_id",
            "capability_catalog_hash",
        )
        _checkpoint_pair(
            self.capability_routing_policy_id,
            self.capability_routing_policy_hash,
            IdKind.CAPABILITY_ROUTING_POLICY,
            "capability_routing_policy_id",
            "capability_routing_policy_hash",
        )
        _checkpoint_pair(
            self.dispatch_contract_catalog_id,
            self.dispatch_contract_catalog_hash,
            IdKind.DISPATCH_CONTRACT_CATALOG,
            "dispatch_contract_catalog_id",
            "dispatch_contract_catalog_hash",
        )
        _checkpoint_pair(
            self.planning_input_id,
            self.planning_input_hash,
            IdKind.PLANNING_INPUT,
            "planning_input_id",
            "planning_input_hash",
        )
        _optional_digest(
            self.planner_dependency_plan_hash,
            "planner_dependency_plan_hash",
        )
        _optional_typed_id(self.planner_run_id, IdKind.RUN, "planner_run_id")
        _checkpoint_pair(
            self.plan_proposal_id,
            self.plan_proposal_hash,
            IdKind.PLAN_PROPOSAL,
            "plan_proposal_id",
            "plan_proposal_hash",
        )
        _checkpoint_pair(
            self.plan_audit_id,
            self.plan_audit_hash,
            IdKind.PLAN_AUDIT,
            "plan_audit_id",
            "plan_audit_hash",
        )
        _checkpoint_pair(
            self.materialization_id,
            self.materialization_hash,
            IdKind.PLAN_MATERIALIZATION,
            "materialization_id",
            "materialization_hash",
        )
        _checkpoint_pair(
            self.preparation_policy_id,
            self.preparation_policy_hash,
            IdKind.TASK_PREPARATION_POLICY,
            "preparation_policy_id",
            "preparation_policy_hash",
        )
        if not isinstance(self.stage, GoalBootstrapStage):
            raise ProductionGoalBootstrapModelError(
                "stage must be a GoalBootstrapStage"
            )
        if not isinstance(self.status, GoalBootstrapStatus):
            raise ProductionGoalBootstrapModelError(
                "status must be a GoalBootstrapStatus"
            )
        _nonnegative_int(self.revision, "revision")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        self._validate_checkpoint_shape()
        self._validate_terminal_shape()

    def _validate_checkpoint_shape(self) -> None:
        rank = _STAGE_ORDER[self.stage]
        checkpoints = (
            (
                GoalBootstrapStage.AUTHORITY_PUBLISHED,
                self.capability_catalog_id is not None
                and self.capability_catalog_hash is not None
                and self.capability_routing_policy_id is not None
                and self.capability_routing_policy_hash is not None
                and self.dispatch_contract_catalog_id is not None
                and self.dispatch_contract_catalog_hash is not None,
                "capability/dispatch authority checkpoint",
            ),
            (
                GoalBootstrapStage.PLANNING_INPUT_PUBLISHED,
                self.planning_input_id is not None
                and self.planning_input_hash is not None,
                "PlanningInput checkpoint",
            ),
            (
                GoalBootstrapStage.PLANNER_STARTED,
                self.planner_dependency_plan_hash is not None,
                "planner dependency checkpoint",
            ),
            (
                GoalBootstrapStage.PLANNER_RETURNED,
                self.planner_run_id is not None
                and self.plan_proposal_id is not None
                and self.plan_proposal_hash is not None,
                "planner return checkpoint",
            ),
            (
                GoalBootstrapStage.PLAN_AUDITED,
                self.plan_audit_id is not None
                and self.plan_audit_hash is not None,
                "plan audit checkpoint",
            ),
            (
                GoalBootstrapStage.MATERIALIZED,
                self.materialization_id is not None
                and self.materialization_hash is not None,
                "materialization checkpoint",
            ),
            (
                GoalBootstrapStage.PREPPOL_PUBLISHED,
                self.preparation_policy_id is not None
                and self.preparation_policy_hash is not None,
                "PREPPOL checkpoint",
            ),
        )
        for checkpoint_stage, present, label in checkpoints:
            expected = rank >= _STAGE_ORDER[checkpoint_stage]
            if present != expected:
                relation = "requires" if expected else "cannot contain"
                raise ProductionGoalBootstrapModelError(
                    f"{self.stage.value} {relation} {label}"
                )

    def _validate_terminal_shape(self) -> None:
        if self.status in (GoalBootstrapStatus.ACTIVE, GoalBootstrapStatus.READY):
            if self.terminal_reason is not None:
                raise ProductionGoalBootstrapModelError(
                    f"{self.status.value} bootstrap cannot have terminal_reason"
                )
        else:
            if (
                not isinstance(self.terminal_reason, str)
                or not self.terminal_reason
                or self.terminal_reason.strip() != self.terminal_reason
                or len(self.terminal_reason) > _MAX_REASON_CHARS
            ):
                raise ProductionGoalBootstrapModelError(
                    "terminal bootstrap requires bounded terminal_reason"
                )
        if (
            self.status is GoalBootstrapStatus.READY
            and self.stage is not GoalBootstrapStage.PREPPOL_PUBLISHED
        ):
            raise ProductionGoalBootstrapModelError(
                "READY bootstrap must be at PREPPOL_PUBLISHED stage"
            )
        if (
            self.status is GoalBootstrapStatus.FAILED_PRE_PLANNER
            and _STAGE_ORDER[self.stage]
            >= _STAGE_ORDER[GoalBootstrapStage.PLANNER_STARTED]
        ):
            raise ProductionGoalBootstrapModelError(
                "FAILED_PRE_PLANNER cannot cross PLANNER_STARTED"
            )

    @property
    def is_active(self) -> bool:
        return self.status is GoalBootstrapStatus.ACTIVE

    @property
    def requires_planner_recovery(self) -> bool:
        return (
            self.status is GoalBootstrapStatus.ACTIVE
            and self.stage is GoalBootstrapStage.PLANNER_STARTED
        )

    def frozen_authority_dict(self) -> dict[str, object]:
        return {
            "bootstrap_id": self.bootstrap_id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "goal_content_hash": self.goal_content_hash,
            "bootstrap_owner_id": self.bootstrap_owner_id,
            "bootstrap_owner_fingerprint": self.bootstrap_owner_fingerprint,
            "bootstrap_contract_version": self.bootstrap_contract_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.frozen_authority_dict(),
            "capability_catalog_id": self.capability_catalog_id,
            "capability_catalog_hash": self.capability_catalog_hash,
            "capability_routing_policy_id": self.capability_routing_policy_id,
            "capability_routing_policy_hash": self.capability_routing_policy_hash,
            "dispatch_contract_catalog_id": self.dispatch_contract_catalog_id,
            "dispatch_contract_catalog_hash": self.dispatch_contract_catalog_hash,
            "planning_input_id": self.planning_input_id,
            "planning_input_hash": self.planning_input_hash,
            "planner_dependency_plan_hash": self.planner_dependency_plan_hash,
            "planner_run_id": self.planner_run_id,
            "plan_proposal_id": self.plan_proposal_id,
            "plan_proposal_hash": self.plan_proposal_hash,
            "plan_audit_id": self.plan_audit_id,
            "plan_audit_hash": self.plan_audit_hash,
            "materialization_id": self.materialization_id,
            "materialization_hash": self.materialization_hash,
            "preparation_policy_id": self.preparation_policy_id,
            "preparation_policy_hash": self.preparation_policy_hash,
            "stage": self.stage.value,
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminal_reason": self.terminal_reason,
        }
