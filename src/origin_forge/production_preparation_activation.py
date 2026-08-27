from __future__ import annotations

import sqlite3

from .production_preparation_models import (
    PreparationStage,
    TaskPreparationReceipt,
)
from .production_preparation_receipts import (
    _load_receipt_connection,
    _require_active_checkpoint,
)
from .production_task_activation import (
    TaskActivationResult,
    _activate_dependency_ready_task_connection,
)
from .runtime import OriginForgeRuntime
from .service import StaleRevision, utc_now


class PreparationActivationError(RuntimeError):
    pass


def _checkpoint_preparation_activated_connection(
    conn: sqlite3.Connection,
    receipt: TaskPreparationReceipt,
    activation: TaskActivationResult,
    now: str,
) -> TaskPreparationReceipt:
    """Checkpoint one exact Phase-35 activation inside the caller-owned transaction."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be a sqlite3.Connection")
    if not isinstance(receipt, TaskPreparationReceipt):
        raise TypeError("receipt must be a TaskPreparationReceipt")
    if not isinstance(activation, TaskActivationResult):
        raise TypeError("activation must be a TaskActivationResult")
    if not isinstance(now, str) or not now:
        raise PreparationActivationError("checkpoint timestamp must be non-empty text")
    if (
        activation.task_id != receipt.task_id
        or activation.previous_revision != receipt.queued_task_revision
        or activation.previous_task_content_hash != receipt.queued_task_hash
        or activation.new_revision != receipt.queued_task_revision + 1
    ):
        raise PreparationActivationError(
            "Phase-35 activation does not exactly continue PREP queued authority"
        )

    new_revision = receipt.revision + 1
    cursor = conn.execute(
        """UPDATE task_preparations
           SET ready_task_revision = ?, ready_task_hash = ?,
               stage = 'ACTIVATED', revision = ?, updated_at = ?
           WHERE preparation_id = ? AND status = 'ACTIVE'
             AND stage = 'CLAIMED' AND revision = ?""",
        (
            activation.new_revision,
            activation.new_task_content_hash,
            new_revision,
            now,
            receipt.preparation_id,
            receipt.revision,
        ),
    )
    if cursor.rowcount != 1:
        raise StaleRevision("PREP changed during atomic activation checkpoint")

    updated = _load_receipt_connection(conn, receipt.preparation_id)
    if (
        updated.stage is not PreparationStage.ACTIVATED
        or updated.revision != new_revision
        or updated.ready_task_revision != activation.new_revision
        or updated.ready_task_hash != activation.new_task_content_hash
    ):
        raise PreparationActivationError(
            "atomic activation checkpoint did not reconstruct exact PREP authority"
        )
    return updated


def activate_and_checkpoint_preparation(
    runtime: OriginForgeRuntime,
    preparation_id: str,
    expected_revision: int,
) -> TaskPreparationReceipt:
    """Atomically bind one CLAIMED PREP to its exact Phase-35 Task activation.

    One BEGIN IMMEDIATE transaction owns both the canonical dependency-ready
    QUEUED -> READY Task transition/event and PREP CLAIMED -> ACTIVATED
    checkpoint. Any exception before commit rolls both operations back. Caller
    authority is limited to one existing PREP identity plus its expected receipt
    revision; Task identity/revision/hash are loaded from durable PREP authority.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")
    if type(expected_revision) is not int or expected_revision < 0:
        raise PreparationActivationError(
            "expected_revision must be a non-negative integer"
        )

    now = utc_now()
    with runtime.store.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute(
            "SELECT id FROM projects WHERE root_path = ?",
            (str(runtime.project_root),),
        ).fetchone()
        if project is None:
            raise PreparationActivationError("current project is unavailable")

        receipt = _load_receipt_connection(conn, preparation_id)
        if receipt.project_id != project["id"]:
            raise PreparationActivationError(
                "PREP receipt belongs to another project"
            )
        _require_active_checkpoint(
            receipt,
            expected_stage=PreparationStage.CLAIMED,
            expected_revision=expected_revision,
        )

        activation = _activate_dependency_ready_task_connection(
            runtime,
            conn,
            project["id"],
            receipt.task_id,
            receipt.queued_task_revision,
            now,
        )
        if (
            activation.previous_task_content_hash != receipt.queued_task_hash
            or activation.previous_revision != receipt.queued_task_revision
        ):
            raise PreparationActivationError(
                "canonical Task changed outside exact PREP queued authority"
            )

        return _checkpoint_preparation_activated_connection(
            conn,
            receipt,
            activation,
            now,
        )
