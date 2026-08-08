from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from .dream_models import (
    DreamBudget,
    DreamInputManifest,
    EvidenceClass,
    EvidenceRef,
)
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime
from .state import RunStatus, TaskStatus


class DreamEvidenceError(RuntimeError):
    pass


_TERMINAL_RUNS = frozenset(
    {
        RunStatus.SUCCEEDED.value,
        RunStatus.FAILED.value,
        RunStatus.INTERRUPTED.value,
        RunStatus.CANCELLED.value,
    }
)
_TERMINAL_TASKS = frozenset(
    {
        TaskStatus.FAILED.value,
        TaskStatus.QUARANTINED.value,
        TaskStatus.SUCCEEDED.value,
        TaskStatus.CANCELLED.value,
    }
)
_MAX_RECORD_BYTES = 2 * 1024 * 1024
_MAX_RELATED_PER_RUN = 1024


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DreamEvidenceError("Dream evidence must be finite JSON data") from exc


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _json_field(value: object, label: str) -> object:
    if not isinstance(value, str):
        raise DreamEvidenceError(f"{label} must be JSON text")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise DreamEvidenceError(f"{label} contains invalid JSON") from exc


def canonical_run_record(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "model_profile": row["model_profile"],
        "model_hash": row["model_hash"],
        "skills": _json_field(row["skills_json"], "runs.skills_json"),
        "allowed_tools": _json_field(row["allowed_tools_json"], "runs.allowed_tools_json"),
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "status": row["status"],
        "input_token_count": row["input_token_count"],
        "output_token_count": row["output_token_count"],
        "resource_metrics": _json_field(
            row["resource_metrics_json"], "runs.resource_metrics_json"
        ),
        "failure_reason": row["failure_reason"],
    }


def canonical_task_record(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "flow_id": row["flow_id"],
        "parent_task_id": row["parent_task_id"],
        "objective": row["objective"],
        "acceptance_criteria": _json_field(
            row["acceptance_criteria_json"], "tasks.acceptance_criteria_json"
        ),
        "constraints": _json_field(row["constraints_json"], "tasks.constraints_json"),
        "required_capabilities": _json_field(
            row["required_capabilities_json"], "tasks.required_capabilities_json"
        ),
        "budget": _json_field(row["budget_json"], "tasks.budget_json"),
        "priority": row["priority"],
        "status": row["status"],
        "revision": row["revision"],
        "attempt_count": row["attempt_count"],
        "assigned_run_id": row["assigned_run_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def canonical_decision_record(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "goal_id": row["goal_id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "context": row["context"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "alternatives": _json_field(row["alternatives_json"], "decisions.alternatives_json"),
        "status": row["status"],
        "supersedes_decision_id": row["supersedes_decision_id"],
        "created_at": row["created_at"],
    }


def canonical_verification_record(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "verification_type": row["verification_type"],
        "verifier": row["verifier"],
        "status": row["status"],
        "evidence": _json_field(row["evidence_json"], "verifications.evidence_json"),
        "metrics": _json_field(row["metrics_json"], "verifications.metrics_json"),
        "run_id": row["run_id"],
        "created_at": row["created_at"],
    }


def verification_evidence_ref(row: Mapping[str, object]) -> EvidenceRef:
    record = canonical_verification_record(row)
    return EvidenceRef(
        str(record["id"]),
        _hash(record),
        EvidenceClass.VERIFICATION,
    )


@dataclass(frozen=True)
class DreamEvidenceRecord:
    ref: EvidenceRef
    record_type: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.ref, EvidenceRef):
            raise DreamEvidenceError("Dream evidence record ref must be an EvidenceRef")
        if self.record_type not in {"RUN", "TASK", "DECISION", "VERIFICATION"}:
            raise DreamEvidenceError(f"unsupported Dream evidence record type: {self.record_type}")
        if not isinstance(self.payload, dict):
            raise DreamEvidenceError("Dream evidence record payload must be an object")
        payload = json.loads(_canonical_bytes(self.payload).decode("utf-8"))
        data = _canonical_bytes(payload)
        if len(data) > _MAX_RECORD_BYTES:
            raise DreamEvidenceError(
                f"Dream evidence record exceeds byte limit ({len(data)} > {_MAX_RECORD_BYTES})"
            )
        if self.ref.content_hash != _hash(payload):
            raise DreamEvidenceError("Dream evidence ref hash does not match record payload")
        object.__setattr__(self, "payload", payload)

    @property
    def byte_count(self) -> int:
        return len(_canonical_bytes(self.payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "ref": self.ref.to_dict(),
            "payload": self.payload,
        }


@dataclass(frozen=True)
class DreamEvidenceBundle:
    manifest: DreamInputManifest
    records: tuple[DreamEvidenceRecord, ...]
    total_evidence_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, DreamInputManifest):
            raise DreamEvidenceError("bundle manifest must be a DreamInputManifest")
        records = tuple(self.records)
        if any(not isinstance(item, DreamEvidenceRecord) for item in records):
            raise DreamEvidenceError("bundle records must contain DreamEvidenceRecord values")
        keys = [(item.record_type, item.ref.ref_id) for item in records]
        if len(keys) != len(set(keys)):
            raise DreamEvidenceError("Dream evidence bundle contains duplicate records")
        ordered = tuple(sorted(records, key=lambda item: (item.record_type, item.ref.ref_id)))
        actual_bytes = sum(item.byte_count for item in ordered)
        if actual_bytes != self.total_evidence_bytes:
            raise DreamEvidenceError("Dream evidence byte count does not match records")
        if actual_bytes > self.manifest.budget.max_total_evidence_bytes:
            raise DreamEvidenceError("Dream evidence bundle exceeds manifest byte budget")
        object.__setattr__(self, "records", ordered)

    @property
    def content_hash(self) -> str:
        return _hash(
            {
                "manifest_id": self.manifest.manifest_id,
                "manifest_hash": self.manifest.content_hash,
                "records": [item.to_dict() for item in self.records],
                "total_evidence_bytes": self.total_evidence_bytes,
            }
        )

    def record(self, ref_id: str) -> DreamEvidenceRecord:
        matches = [item for item in self.records if item.ref.ref_id == ref_id]
        if not matches:
            raise KeyError(ref_id)
        if len(matches) != 1:
            raise DreamEvidenceError(f"ambiguous Dream evidence ref: {ref_id}")
        return matches[0]


class RuntimeDreamEvidenceCollector:
    """Read-only bounded collector for completed durable runtime evidence."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    @staticmethod
    def _record(
        record_type: str,
        payload: dict[str, object],
        *,
        evidence_class: EvidenceClass,
        revision: int | None = None,
    ) -> DreamEvidenceRecord:
        ref = EvidenceRef(
            str(payload["id"]),
            _hash(payload),
            evidence_class,
            revision,
        )
        return DreamEvidenceRecord(ref, record_type, payload)

    def collect(
        self,
        run_ids: Iterable[str],
        *,
        parent_memory_generation_id: str | None = None,
        budget: DreamBudget | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> DreamEvidenceBundle:
        budget = budget or DreamBudget()
        if not isinstance(budget, DreamBudget):
            raise TypeError("budget must be a DreamBudget")
        requested = tuple(run_ids)
        if len(requested) != len(set(requested)):
            raise DreamEvidenceError("Dream run selection contains duplicate IDs")
        if len(requested) > budget.max_runs:
            raise DreamEvidenceError(
                f"Dream run selection exceeds budget ({len(requested)} > {budget.max_runs})"
            )
        if any(not isinstance(value, str) or not validate_id(value, IdKind.RUN) for value in requested):
            raise DreamEvidenceError("Dream run selection contains invalid RUN IDs")

        records: dict[tuple[str, str], DreamEvidenceRecord] = {}
        task_ids: set[str] = set()

        with self.runtime.store.session() as conn:
            for run_id in sorted(requested):
                row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                if row is None:
                    raise DreamEvidenceError(f"selected Dream RUN does not exist: {run_id}")
                run_row = dict(row)
                if run_row["status"] not in _TERMINAL_RUNS:
                    raise DreamEvidenceError(f"selected Dream RUN is still active: {run_id}")
                task_id = run_row["task_id"]
                if not isinstance(task_id, str) or not validate_id(task_id, IdKind.TASK):
                    raise DreamEvidenceError(f"selected Dream RUN has no durable Task: {run_id}")
                task_row_raw = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if task_row_raw is None:
                    raise DreamEvidenceError(f"selected Dream RUN Task is unavailable: {task_id}")
                task_row = dict(task_row_raw)
                if task_row["status"] not in _TERMINAL_TASKS:
                    raise DreamEvidenceError(
                        f"selected Dream RUN belongs to nonterminal Task {task_id}: {task_row['status']}"
                    )

                run_payload = canonical_run_record(run_row)
                records[("RUN", run_id)] = self._record(
                    "RUN",
                    run_payload,
                    evidence_class=EvidenceClass.TRAJECTORY,
                )
                task_ids.add(task_id)
                task_payload = canonical_task_record(task_row)
                records[("TASK", task_id)] = self._record(
                    "TASK",
                    task_payload,
                    evidence_class=EvidenceClass.CANONICAL,
                    revision=int(task_row["revision"]),
                )

            for task_id in sorted(task_ids):
                decision_rows = conn.execute(
                    "SELECT * FROM decisions WHERE project_id = ? AND task_id = ? ORDER BY id",
                    (self.runtime.project_id(), task_id),
                ).fetchall()
                if len(decision_rows) > _MAX_RELATED_PER_RUN:
                    raise DreamEvidenceError(
                        f"Dream task decision count exceeds limit: {task_id}"
                    )
                for row in decision_rows:
                    payload = canonical_decision_record(dict(row))
                    records[("DECISION", str(payload["id"]))] = self._record(
                        "DECISION",
                        payload,
                        evidence_class=EvidenceClass.CANONICAL,
                    )

            verification_rows = []
            for run_id in sorted(requested):
                verification_rows.extend(
                    conn.execute(
                        """SELECT * FROM verifications
                           WHERE (target_type = 'RUN' AND target_id = ?)
                              OR run_id = ?
                           ORDER BY id""",
                        (run_id, run_id),
                    ).fetchall()
                )
            for task_id in sorted(task_ids):
                verification_rows.extend(
                    conn.execute(
                        """SELECT * FROM verifications
                           WHERE target_type = 'TASK' AND target_id = ?
                           ORDER BY id""",
                        (task_id,),
                    ).fetchall()
                )
            if len(verification_rows) > _MAX_RELATED_PER_RUN * max(len(requested), 1):
                raise DreamEvidenceError("Dream verification count exceeds bounded related-record limit")
            for row in verification_rows:
                row_dict = dict(row)
                payload = canonical_verification_record(row_dict)
                record = DreamEvidenceRecord(
                    verification_evidence_ref(row_dict),
                    "VERIFICATION",
                    payload,
                )
                records[("VERIFICATION", record.ref.ref_id)] = record

        ordered = tuple(sorted(records.values(), key=lambda item: (item.record_type, item.ref.ref_id)))
        total_bytes = sum(item.byte_count for item in ordered)
        if total_bytes > budget.max_total_evidence_bytes:
            raise DreamEvidenceError(
                "Dream evidence exceeds byte budget "
                f"({total_bytes} > {budget.max_total_evidence_bytes})"
            )

        manifest = DreamInputManifest.create(
            parent_memory_generation_id=parent_memory_generation_id,
            run_refs=(item.ref for item in ordered if item.record_type == "RUN"),
            task_refs=(item.ref for item in ordered if item.record_type == "TASK"),
            decision_refs=(item.ref for item in ordered if item.record_type == "DECISION"),
            verification_refs=(
                item.ref for item in ordered if item.record_type == "VERIFICATION"
            ),
            window_start=window_start,
            window_end=window_end,
            budget=budget,
        )
        return DreamEvidenceBundle(manifest, ordered, total_bytes)
