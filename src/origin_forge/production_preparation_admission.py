from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .production_capability_routing import CapabilityRoutingError, TaskRouteInput
from .production_manager_dispatch_admission import (
    ManagerDispatchAdmissionStatus,
    inspect_manager_dispatch_admission_readonly,
)
from .production_planning_inspection import (
    ProductionPlanningInspectionError,
    _load_materialization_connection,
    _project_id,
)
from .production_preparation_models import TaskPreparationPolicyBinding
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .state import TaskStatus
from .task_readiness import (
    DependencyReadinessStatus,
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class PreparationAdmissionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INVALID_POLICY_PROVENANCE = "INVALID_POLICY_PROVENANCE"
    INVALID_PHASE34_STATE = "INVALID_PHASE34_STATE"
    INVALID_CANONICAL_STATE = "INVALID_CANONICAL_STATE"


@dataclass(frozen=True)
class PreparationCandidate:
    task_id: str
    task_revision: int
    task_content_hash: str
    created_at: str
    step_key: str
    required_capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "task_content_hash": self.task_content_hash,
            "created_at": self.created_at,
            "step_key": self.step_key,
            "required_capabilities": list(self.required_capabilities),
        }


@dataclass(frozen=True)
class MaterializationPreparationAdmission:
    status: PreparationAdmissionStatus
    preparation_policy_id: str
    materialization_id: str
    candidates: tuple[PreparationCandidate, ...]
    not_queued_exclusion_count: int
    dependency_exclusion_count: int
    active_preparation_exclusion_count: int
    phase38_admissible_exclusion_count: int
    detail: str | None = None

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "preparation_policy_id": self.preparation_policy_id,
            "materialization_id": self.materialization_id,
            "candidate_count": self.candidate_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "not_queued_exclusion_count": self.not_queued_exclusion_count,
            "dependency_exclusion_count": self.dependency_exclusion_count,
            "active_preparation_exclusion_count": self.active_preparation_exclusion_count,
            "phase38_admissible_exclusion_count": self.phase38_admissible_exclusion_count,
            "detail": self.detail,
            "authority": "read-only eligibility",
        }


def _empty(
    policy: TaskPreparationPolicyBinding,
    status: PreparationAdmissionStatus,
    detail: str,
) -> MaterializationPreparationAdmission:
    return MaterializationPreparationAdmission(
        status=status,
        preparation_policy_id=policy.preparation_policy_id,
        materialization_id=policy.materialization_id,
        candidates=(),
        not_queued_exclusion_count=0,
        dependency_exclusion_count=0,
        active_preparation_exclusion_count=0,
        phase38_admissible_exclusion_count=0,
        detail=detail,
    )


def inspect_materialization_preparation_eligibility_readonly(
    runtime: OriginForgeRuntime,
    policy: TaskPreparationPolicyBinding,
) -> MaterializationPreparationAdmission:
    """Return deterministic Phase-39 candidates without creating authority.

    The exact PREPPOL planning/capability/dispatch-catalog provenance is checked
    first. Candidate truth is then derived in one immutable SQLite snapshot from
    only Tasks bound by the exact PLMAT. This function never activates a Task,
    creates a PREP receipt, publishes a route, calls a model, or dispatches work.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if not isinstance(policy, TaskPreparationPolicyBinding):
        raise TypeError("policy must be a TaskPreparationPolicyBinding")

    try:
        provenance = resolve_preparation_policy_provenance(runtime, policy)
    except ProductionPreparationProvenanceError as exc:
        return _empty(
            policy,
            PreparationAdmissionStatus.INVALID_POLICY_PROVENANCE,
            f"{type(exc).__name__}: {exc}",
        )

    # Reuse Phase 38's complete bounded current-authority inspection rather than
    # adding a second interpretation of Phase-34 evidence. Any globally invalid
    # or ambiguous Phase-34 state fails closed because an unreadable audit could
    # otherwise hide authority for a PLMAT Task.
    phase38 = inspect_manager_dispatch_admission_readonly(runtime)
    if phase38.status is not ManagerDispatchAdmissionStatus.COMPLETE:
        return _empty(
            policy,
            PreparationAdmissionStatus.INVALID_PHASE34_STATE,
            f"Phase-38 admission is {phase38.status.value}",
        )
    phase38_task_ids = {candidate.task_id for candidate in phase38.candidates}

    candidates: list[PreparationCandidate] = []
    not_queued = 0
    dependency_excluded = 0
    active_preparation = 0
    phase38_excluded = 0
    allowed_capabilities = set(
        provenance.capability_routing_policy.allowed_capability_ids
    )

    try:
        with production_read_connection(runtime) as conn:
            project_id = _project_id(conn, runtime)
            if project_id != policy.project_id:
                raise ProductionPlanningInspectionError(
                    "PREPPOL project does not match current repository project"
                )
            materialization = _load_materialization_connection(
                conn,
                project_id,
                policy.materialization_id,
            )
            if (
                materialization.content_hash != policy.materialization_hash
                or materialization.planning_input_id != policy.planning_input_id
                or materialization.planning_input_hash != policy.planning_input_hash
            ):
                raise ProductionPlanningInspectionError(
                    "PREPPOL materialization relation changed before admission snapshot"
                )

            for binding in materialization.task_bindings:
                row = conn.execute(
                    """SELECT t.*, g.project_id
                       FROM tasks t
                       JOIN flows f ON f.id = t.flow_id
                       JOIN goals g ON g.id = f.goal_id
                       WHERE t.id = ?""",
                    (binding.task_id,),
                ).fetchone()
                if (
                    row is None
                    or row["project_id"] != project_id
                    or row["flow_id"] != materialization.flow_id
                ):
                    raise ProductionPlanningInspectionError(
                        "materialized Task left exact project/Flow relation"
                    )

                try:
                    task_status = TaskStatus(row["status"])
                    route_input = TaskRouteInput.from_row(row)
                    readiness = resolve_task_dependency_readiness_connection(
                        conn,
                        binding.task_id,
                    )
                except (
                    CapabilityRoutingError,
                    TaskReadinessError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise ProductionPlanningInspectionError(
                        "materialized Task canonical state is invalid"
                    ) from exc

                if task_status is not TaskStatus.QUEUED:
                    not_queued += 1
                    continue
                if (
                    readiness.task_status is not TaskStatus.QUEUED
                    or readiness.status is not DependencyReadinessStatus.READY
                ):
                    dependency_excluded += 1
                    continue
                if not set(route_input.required_capabilities).issubset(
                    allowed_capabilities
                ):
                    raise ProductionPlanningInspectionError(
                        "materialized Task capabilities exceed PREPPOL CAPPOL authority"
                    )

                active = conn.execute(
                    """SELECT preparation_id FROM task_preparations
                       WHERE task_id = ? AND status = 'ACTIVE'
                       LIMIT 1""",
                    (binding.task_id,),
                ).fetchone()
                if active is not None:
                    active_preparation += 1
                    continue
                if binding.task_id in phase38_task_ids:
                    phase38_excluded += 1
                    continue

                created_at = row["created_at"]
                if not isinstance(created_at, str) or not created_at:
                    raise ProductionPlanningInspectionError(
                        "materialized Task created_at is invalid"
                    )
                candidates.append(
                    PreparationCandidate(
                        task_id=binding.task_id,
                        task_revision=route_input.task_revision,
                        task_content_hash=route_input.task_content_hash,
                        created_at=created_at,
                        step_key=binding.step_key,
                        required_capabilities=route_input.required_capabilities,
                    )
                )
    except (
        ProductionPlanningInspectionError,
        ProductionReadGuardError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return MaterializationPreparationAdmission(
            status=PreparationAdmissionStatus.INVALID_CANONICAL_STATE,
            preparation_policy_id=policy.preparation_policy_id,
            materialization_id=policy.materialization_id,
            candidates=(),
            not_queued_exclusion_count=not_queued,
            dependency_exclusion_count=dependency_excluded,
            active_preparation_exclusion_count=active_preparation,
            phase38_admissible_exclusion_count=phase38_excluded,
            detail=f"{type(exc).__name__}: {exc}",
        )

    candidates.sort(key=lambda value: (value.created_at, value.task_id))
    return MaterializationPreparationAdmission(
        status=PreparationAdmissionStatus.COMPLETE,
        preparation_policy_id=policy.preparation_policy_id,
        materialization_id=policy.materialization_id,
        candidates=tuple(candidates),
        not_queued_exclusion_count=not_queued,
        dependency_exclusion_count=dependency_excluded,
        active_preparation_exclusion_count=active_preparation,
        phase38_admissible_exclusion_count=phase38_excluded,
        detail=None,
    )
