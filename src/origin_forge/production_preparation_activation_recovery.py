from __future__ import annotations

from .production_capability_routing import CapabilityRoutingError, TaskRouteInput
from .production_preparation_activation import (
    _checkpoint_preparation_activated_connection,
)
from .production_preparation_models import PreparationStage, TaskPreparationReceipt
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_preparation_provenance import (
    ProductionPreparationProvenanceError,
    resolve_preparation_policy_provenance,
)
from .production_preparation_receipts import (
    _load_receipt_connection,
    _require_active_checkpoint,
)
from .production_preparation_recovery import (
    PreparationRecoveryReadError,
    PreparationRecoveryState,
    _acquisition_event,
    _activation_event_evidence,
    _parse_canonical_object,
)
from .production_task_activation import TaskActivationResult
from .runtime import OriginForgeRuntime
from .service import utc_now
from .state import TaskStatus
from .task_readiness import (
    TaskReadinessError,
    resolve_task_dependency_readiness_connection,
)


class PreparationActivationRecoveryError(RuntimeError):
    pass


def adopt_legacy_preparation_activation(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
) -> TaskPreparationReceipt:
    """Adopt one proven legacy Phase-35 activation into a missing PREP checkpoint.

    The immutable 41A classifier is not trusted as mutation authority. This
    function independently replays the exact PREPPOL/provenance and acquisition /
    activation-event proof under one BEGIN IMMEDIATE SQLite transaction and then
    uses the 41B connection-scoped checkpoint helper. It never changes Task state
    and never synthesizes a new activation event.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if type(expected_revision) is not int or expected_revision < 0:
        raise PreparationActivationRecoveryError(
            "expected_revision must be a non-negative integer"
        )

    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise PreparationActivationRecoveryError("current project is unavailable")

        receipt = _load_receipt_connection(conn, preparation_id)
        if receipt.project_id != project["id"]:
            raise PreparationActivationRecoveryError(
                "PREP receipt belongs to another project"
            )
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.CLAIMED,
            expected_revision=expected_revision,
        )
        if receipt.revision != 0:
            raise PreparationActivationRecoveryError(
                "legacy activation adoption requires original PREP revision zero"
            )

        try:
            policy = read_preparation_policy(runtime, receipt.preparation_policy_id)
            if (
                policy.content_hash != receipt.preparation_policy_hash
                or policy.project_id != receipt.project_id
                or policy.materialization_id != receipt.materialization_id
                or policy.materialization_hash != receipt.materialization_hash
                or policy.planning_input_id != receipt.planning_input_id
                or policy.planning_input_hash != receipt.planning_input_hash
            ):
                raise PreparationActivationRecoveryError(
                    "PREP no longer binds exact durable PREPPOL authority"
                )
            resolve_preparation_policy_provenance(runtime, policy)
        except PreparationActivationRecoveryError:
            raise
        except (
            ProductionPreparationPolicyStoreError,
            ProductionPreparationProvenanceError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise PreparationActivationRecoveryError(
                "PREPPOL provenance is unavailable, stale, or invalid"
            ) from exc

        task = conn.execute(
            """SELECT t.*, g.project_id
               FROM tasks t
               JOIN flows f ON f.id = t.flow_id
               JOIN goals g ON g.id = f.goal_id
               WHERE t.id = ?""",
            (receipt.task_id,),
        ).fetchone()
        if task is None or task["project_id"] != project["id"]:
            raise PreparationActivationRecoveryError(
                "PREP Task is unavailable in current project"
            )
        try:
            task_status = TaskStatus(task["status"])
            task_input = TaskRouteInput.from_row(task)
            readiness = resolve_task_dependency_readiness_connection(
                conn, receipt.task_id
            )
        except (
            CapabilityRoutingError,
            TaskReadinessError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise PreparationActivationRecoveryError(
                "legacy activation Task/readiness evidence is invalid"
            ) from exc
        if task_status is not TaskStatus.READY:
            raise PreparationActivationRecoveryError(
                "legacy activation adoption requires canonical READY Task"
            )

        acquisition_row, acquisition_state, acquisition_detail = _acquisition_event(
            conn, receipt
        )
        if acquisition_state is not None or acquisition_row is None:
            raise PreparationActivationRecoveryError(
                acquisition_detail or "exact PREP acquisition evidence is unavailable"
            )
        activation_row, activation_state, activation_detail = _activation_event_evidence(
            conn,
            receipt,
            task_status,
            task_input,
            readiness,
            acquisition_row,
        )
        if (
            activation_state is not PreparationRecoveryState.ADOPTABLE_ACTIVATION_CHECKPOINT
            or activation_row is None
        ):
            raise PreparationActivationRecoveryError(
                activation_detail or "exact Phase-35 activation evidence is not adoptable"
            )
        try:
            metadata = _parse_canonical_object(
                activation_row["metadata_json"],
                "Phase-35 activation",
            )
        except PreparationRecoveryReadError as exc:
            raise PreparationActivationRecoveryError(
                "exact Phase-35 activation metadata cannot be reconstructed"
            ) from exc

        activation = TaskActivationResult(
            task_id=receipt.task_id,
            previous_revision=receipt.queued_task_revision,
            new_revision=task_input.task_revision,
            previous_task_content_hash=receipt.queued_task_hash,
            new_task_content_hash=task_input.task_content_hash,
            dependency_count=metadata["dependency_count"],
            satisfied_dependency_count=metadata["satisfied_dependency_count"],
        )
        return _checkpoint_preparation_activated_connection(
            conn,
            receipt,
            activation,
            utc_now(),
        )
