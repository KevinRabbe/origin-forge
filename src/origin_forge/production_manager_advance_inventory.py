from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .ids import IdKind, validate_id
from .production_preparation_models import (
    PreparationStage,
    PreparationStatus,
    ProductionPreparationModelError,
    TaskPreparationPolicyBinding,
    TaskPreparationReceipt,
)
from .production_preparation_policy_store import (
    ProductionPreparationPolicyStoreError,
    read_preparation_policy,
)
from .production_read_guard import ProductionReadGuardError, production_read_connection
from .runtime import OriginForgeRuntime
from .state import TaskStatus


_MAX_PREPARATION_POLICIES = 10_000
_MAX_PREPARATION_RECEIPTS = 10_000


class ManagerAdvanceInventoryStatus(StrEnum):
    COMPLETE = "COMPLETE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    INVALID_STATE = "INVALID_STATE"


@dataclass(frozen=True)
class PreparationPolicyInventory:
    status: ManagerAdvanceInventoryStatus
    policies: tuple[TaskPreparationPolicyBinding, ...]
    scanned_count: int
    detail: str | None = None

    @property
    def policy_count(self) -> int:
        return len(self.policies)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "policies": [policy.to_dict() for policy in self.policies],
            "scanned_count": self.scanned_count,
            "policy_count": self.policy_count,
            "detail": self.detail,
            "authority": "read-only-preparation-policy-inventory",
        }


@dataclass(frozen=True)
class PreparationReceiptInventoryEntry:
    receipt: TaskPreparationReceipt
    task_created_at: str
    current_task_status: TaskStatus
    current_task_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, TaskPreparationReceipt):
            raise TypeError("receipt must be a TaskPreparationReceipt")
        if (
            not isinstance(self.task_created_at, str)
            or not self.task_created_at
            or self.task_created_at.strip() != self.task_created_at
            or len(self.task_created_at) > 128
        ):
            raise ValueError("task_created_at is invalid")
        if not isinstance(self.current_task_status, TaskStatus):
            raise TypeError("current_task_status must be a TaskStatus")
        if type(self.current_task_revision) is not int or self.current_task_revision < 0:
            raise ValueError("current_task_revision must be non-negative")

    @property
    def task_id(self) -> str:
        return self.receipt.task_id

    @property
    def preparation_id(self) -> str:
        return self.receipt.preparation_id

    @property
    def task_order_key(self) -> tuple[str, str]:
        return (self.task_created_at, self.receipt.task_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt": self.receipt.to_dict(),
            "task_created_at": self.task_created_at,
            "current_task_status": self.current_task_status.value,
            "current_task_revision": self.current_task_revision,
            "task_order_key": [self.task_created_at, self.receipt.task_id],
        }


@dataclass(frozen=True)
class PreparationReceiptInventory:
    status: ManagerAdvanceInventoryStatus
    entries: tuple[PreparationReceiptInventoryEntry, ...]
    scanned_count: int
    detail: str | None = None

    @property
    def receipt_count(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "entries": [entry.to_dict() for entry in self.entries],
            "scanned_count": self.scanned_count,
            "receipt_count": self.receipt_count,
            "detail": self.detail,
            "authority": "read-only-preparation-receipt-inventory",
        }


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:4096]


def _policy_root(runtime: OriginForgeRuntime) -> Path:
    return runtime.state_dir / "production-preparation" / "policies"


def _policy_inventory_failure(
    status: ManagerAdvanceInventoryStatus,
    scanned_count: int,
    detail: str,
) -> PreparationPolicyInventory:
    return PreparationPolicyInventory(status, (), scanned_count, detail)


def inspect_preparation_policy_inventory_readonly(
    runtime: OriginForgeRuntime,
) -> PreparationPolicyInventory:
    """Enumerate every protected PREPPOL without creating store state.

    Directory order is never returned as scheduling authority. All discovered
    IDs are validated first and each policy is then independently reloaded by
    the existing Phase-39 protected reader/currentness checks.
    """

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    root = _policy_root(runtime)
    parent = root.parent
    try:
        state = runtime.state_dir.resolve(strict=True)
        if parent.is_symlink() or root.is_symlink():
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL inventory path may not be a symlink"
            )
        if parent.exists() and not parent.is_dir():
            raise ProductionPreparationPolicyStoreError(
                "production-preparation inventory parent is not a directory"
            )
        if not root.exists():
            return PreparationPolicyInventory(
                ManagerAdvanceInventoryStatus.COMPLETE,
                (),
                0,
                None,
            )
        if not root.is_dir():
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL inventory root is not a directory"
            )
        resolved_root = root.resolve(strict=True)
        resolved_root.relative_to(state)
        if resolved_root != root:
            raise ProductionPreparationPolicyStoreError(
                "PREPPOL inventory root is aliased"
            )

        policy_ids: list[str] = []
        scanned = 0
        for path in root.iterdir():
            scanned += 1
            if scanned > _MAX_PREPARATION_POLICIES:
                return _policy_inventory_failure(
                    ManagerAdvanceInventoryStatus.LIMIT_EXCEEDED,
                    scanned,
                    "PREPPOL inventory object-count limit exceeded",
                )
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ProductionPreparationPolicyStoreError(
                    "PREPPOL inventory contains an undeclared or aliased entry"
                )
            policy_id = path.stem
            if (
                path.name != f"{policy_id}.json"
                or not validate_id(policy_id, IdKind.TASK_PREPARATION_POLICY)
            ):
                raise ProductionPreparationPolicyStoreError(
                    "PREPPOL inventory contains an invalid evidence filename"
                )
            if path.resolve(strict=True) != path or path.parent != root:
                raise ProductionPreparationPolicyStoreError(
                    "PREPPOL inventory evidence path is aliased"
                )
            policy_ids.append(policy_id)

        policies = tuple(
            read_preparation_policy(runtime, policy_id)
            for policy_id in sorted(policy_ids)
        )
        return PreparationPolicyInventory(
            ManagerAdvanceInventoryStatus.COMPLETE,
            policies,
            scanned,
            None,
        )
    except ProductionPreparationPolicyStoreError as exc:
        return _policy_inventory_failure(
            ManagerAdvanceInventoryStatus.INVALID_STATE,
            locals().get("scanned", 0),
            _detail(exc),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _policy_inventory_failure(
            ManagerAdvanceInventoryStatus.INVALID_STATE,
            locals().get("scanned", 0),
            _detail(exc),
        )


def _receipt_from_row_readonly(row) -> TaskPreparationReceipt:
    try:
        return TaskPreparationReceipt(
            preparation_id=row["preparation_id"],
            project_id=row["project_id"],
            preparation_policy_id=row["preparation_policy_id"],
            preparation_policy_hash=row["preparation_policy_hash"],
            materialization_id=row["materialization_id"],
            materialization_hash=row["materialization_hash"],
            planning_input_id=row["planning_input_id"],
            planning_input_hash=row["planning_input_hash"],
            task_id=row["task_id"],
            queued_task_revision=int(row["queued_task_revision"]),
            queued_task_hash=row["queued_task_hash"],
            ready_task_revision=(
                None
                if row["ready_task_revision"] is None
                else int(row["ready_task_revision"])
            ),
            ready_task_hash=row["ready_task_hash"],
            route_decision_id=row["route_decision_id"],
            route_decision_hash=row["route_decision_hash"],
            planner_dependency_plan_hash=row["planner_dependency_plan_hash"],
            planner_run_id=row["planner_run_id"],
            work_order_id=row["work_order_id"],
            work_order_hash=row["work_order_hash"],
            work_order_audit_id=row["work_order_audit_id"],
            work_order_audit_hash=row["work_order_audit_hash"],
            input_resolution_id=row["input_resolution_id"],
            input_resolution_hash=row["input_resolution_hash"],
            dispatch_binding_id=row["dispatch_binding_id"],
            dispatch_binding_hash=row["dispatch_binding_hash"],
            binding_audit_id=row["binding_audit_id"],
            binding_audit_hash=row["binding_audit_hash"],
            stage=PreparationStage(row["stage"]),
            status=PreparationStatus(row["status"]),
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_reason=row["terminal_reason"],
        )
    except (KeyError, TypeError, ValueError, ProductionPreparationModelError) as exc:
        raise ValueError("stored PREP receipt failed typed lifecycle validation") from exc


def _receipt_inventory_failure(
    status: ManagerAdvanceInventoryStatus,
    scanned_count: int,
    detail: str,
) -> PreparationReceiptInventory:
    return PreparationReceiptInventory(status, (), scanned_count, detail)


def inspect_preparation_receipt_inventory_readonly(
    runtime: OriginForgeRuntime,
) -> PreparationReceiptInventory:
    """Enumerate current-project PREP receipts from one immutable SQLite snapshot."""

    if not isinstance(runtime, OriginForgeRuntime):
        raise TypeError("runtime must be an OriginForgeRuntime")

    try:
        with production_read_connection(runtime) as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE root_path = ?",
                (str(runtime.project_root),),
            ).fetchone()
            if project is None:
                raise ValueError("current project is unavailable")
            rows = conn.execute(
                """SELECT tp.*,
                          t.created_at AS task_created_at,
                          t.status AS current_task_status,
                          t.revision AS current_task_revision,
                          g.project_id AS task_project_id
                   FROM task_preparations tp
                   JOIN tasks t ON t.id = tp.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id
                   WHERE tp.project_id = ?
                   ORDER BY tp.preparation_id
                   LIMIT ?""",
                (project["id"], _MAX_PREPARATION_RECEIPTS + 1),
            ).fetchall()

            if len(rows) > _MAX_PREPARATION_RECEIPTS:
                return _receipt_inventory_failure(
                    ManagerAdvanceInventoryStatus.LIMIT_EXCEEDED,
                    len(rows),
                    "PREP receipt inventory row-count limit exceeded",
                )

            entries: list[PreparationReceiptInventoryEntry] = []
            for row in rows:
                if row["task_project_id"] != project["id"]:
                    raise ValueError("PREP receipt Task belongs to another project")
                receipt = _receipt_from_row_readonly(row)
                if receipt.project_id != project["id"]:
                    raise ValueError("PREP receipt belongs to another project")
                entry = PreparationReceiptInventoryEntry(
                    receipt=receipt,
                    task_created_at=row["task_created_at"],
                    current_task_status=TaskStatus(row["current_task_status"]),
                    current_task_revision=int(row["current_task_revision"]),
                )
                entries.append(entry)

        return PreparationReceiptInventory(
            ManagerAdvanceInventoryStatus.COMPLETE,
            tuple(entries),
            len(entries),
            None,
        )
    except ProductionReadGuardError as exc:
        return _receipt_inventory_failure(
            ManagerAdvanceInventoryStatus.INVALID_STATE,
            0,
            _detail(exc),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _receipt_inventory_failure(
            ManagerAdvanceInventoryStatus.INVALID_STATE,
            locals().get("scanned", 0),
            _detail(exc),
        )
