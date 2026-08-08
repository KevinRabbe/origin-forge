from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .dream_evidence import (
    DreamEvidenceError,
    DreamEvidenceRecord,
    canonical_decision_record,
    canonical_run_record,
    canonical_task_record,
    canonical_verification_record,
    verification_evidence_ref,
)
from .dream_models import EvidenceClass, EvidenceRef
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


class DreamEvidenceResolutionError(RuntimeError):
    pass


def _hash_record(record: DreamEvidenceRecord) -> EvidenceRef:
    return record.ref


@dataclass(frozen=True)
class ResolvedDreamEvidence:
    records: tuple[DreamEvidenceRecord, ...]
    missing_ref_ids: tuple[str, ...]
    superseded_ref_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        records = tuple(self.records)
        if any(not isinstance(item, DreamEvidenceRecord) for item in records):
            raise DreamEvidenceResolutionError("records must contain DreamEvidenceRecord values")
        ids = [item.ref.ref_id for item in records]
        if len(ids) != len(set(ids)):
            raise DreamEvidenceResolutionError("resolved evidence contains duplicate ref IDs")
        missing = tuple(self.missing_ref_ids)
        superseded = tuple(self.superseded_ref_ids)
        if len(missing) != len(set(missing)) or len(superseded) != len(set(superseded)):
            raise DreamEvidenceResolutionError("resolved evidence metadata contains duplicate IDs")
        object.__setattr__(self, "records", tuple(sorted(records, key=lambda item: item.ref.ref_id)))
        object.__setattr__(self, "missing_ref_ids", tuple(sorted(missing)))
        object.__setattr__(self, "superseded_ref_ids", tuple(sorted(superseded)))


class RuntimeDreamEvidenceResolver:
    """Resolve already-referenced durable evidence to its current project-local record."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    def _run(self, ref_id: str) -> DreamEvidenceRecord | None:
        try:
            row = self.runtime.get_run(ref_id)
        except KeyError:
            return None
        payload = canonical_run_record(row)
        # Reuse DreamEvidenceRecord validation by creating the expected ref from payload.
        from .dream_evidence import RuntimeDreamEvidenceCollector

        return RuntimeDreamEvidenceCollector._record(
            "RUN", payload, evidence_class=EvidenceClass.TRAJECTORY
        )

    def _task(self, ref_id: str) -> DreamEvidenceRecord | None:
        try:
            row = self.runtime.get_task(ref_id)
        except KeyError:
            return None
        payload = canonical_task_record(row)
        from .dream_evidence import RuntimeDreamEvidenceCollector

        return RuntimeDreamEvidenceCollector._record(
            "TASK",
            payload,
            evidence_class=EvidenceClass.CANONICAL,
            revision=int(row["revision"]),
        )

    def _decision(self, ref_id: str) -> DreamEvidenceRecord | None:
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ? AND project_id = ?",
                (ref_id, self.runtime.project_id()),
            ).fetchone()
        if row is None:
            return None
        payload = canonical_decision_record(dict(row))
        from .dream_evidence import RuntimeDreamEvidenceCollector

        return RuntimeDreamEvidenceCollector._record(
            "DECISION", payload, evidence_class=EvidenceClass.CANONICAL
        )

    def _verification(self, ref_id: str) -> DreamEvidenceRecord | None:
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (ref_id,),
            ).fetchone()
        if row is None:
            return None
        row_dict = dict(row)
        payload = canonical_verification_record(row_dict)
        return DreamEvidenceRecord(
            verification_evidence_ref(row_dict),
            "VERIFICATION",
            payload,
        )

    def _resolve_one(self, ref_id: str) -> DreamEvidenceRecord | None:
        if validate_id(ref_id, IdKind.RUN):
            return self._run(ref_id)
        if validate_id(ref_id, IdKind.TASK):
            return self._task(ref_id)
        if validate_id(ref_id, IdKind.DECISION):
            return self._decision(ref_id)
        if validate_id(ref_id, IdKind.VERIFICATION):
            return self._verification(ref_id)
        raise DreamEvidenceResolutionError(
            f"unsupported durable evidence ID for runtime resolution: {ref_id}"
        )

    def _decision_superseded_ids(self, decision_ids: tuple[str, ...]) -> tuple[str, ...]:
        if not decision_ids:
            return ()
        placeholders = ",".join("?" for _ in decision_ids)
        params = [self.runtime.project_id(), *decision_ids]
        with self.runtime.store.session() as conn:
            rows = conn.execute(
                f"""SELECT supersedes_decision_id FROM decisions
                    WHERE project_id = ?
                      AND supersedes_decision_id IN ({placeholders})
                    ORDER BY supersedes_decision_id, id""",
                params,
            ).fetchall()
        return tuple(sorted({row["supersedes_decision_id"] for row in rows}))

    def resolve(self, refs: Iterable[EvidenceRef]) -> ResolvedDreamEvidence:
        requested = tuple(refs)
        if any(not isinstance(item, EvidenceRef) for item in requested):
            raise TypeError("refs must contain EvidenceRef values")
        ids = [item.ref_id for item in requested]
        if len(ids) != len(set(ids)):
            raise DreamEvidenceResolutionError(
                "runtime evidence resolution requires unique ref IDs"
            )

        records: list[DreamEvidenceRecord] = []
        missing: list[str] = []
        for ref_id in sorted(ids):
            try:
                current = self._resolve_one(ref_id)
            except DreamEvidenceError as exc:
                raise DreamEvidenceResolutionError(
                    f"current durable evidence is invalid: {ref_id}"
                ) from exc
            if current is None:
                missing.append(ref_id)
            else:
                records.append(current)

        decision_ids = tuple(
            ref_id for ref_id in ids if validate_id(ref_id, IdKind.DECISION)
        )
        return ResolvedDreamEvidence(
            tuple(records),
            tuple(missing),
            self._decision_superseded_ids(decision_ids),
        )
