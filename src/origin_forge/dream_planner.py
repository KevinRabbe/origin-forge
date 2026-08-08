from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .dream_deterministic_analyzer import DeterministicDreamAnalyzer
from .dream_evidence import (
    DreamEvidenceBundle,
    DreamEvidenceRecord,
    RuntimeDreamEvidenceCollector,
)
from .dream_evidence_resolver import RuntimeDreamEvidenceResolver
from .dream_generation import DreamGenerationBuilder
from .dream_models import DreamBudget, DreamCandidate, DreamInputManifest, MemoryEntry
from .dream_preprocess import DreamPreprocessReport, EvidenceSnapshot, preprocess_memory
from .dream_roles import (
    DeterministicDreamAuditor,
    DreamAnalysisPackage,
    DreamAuditReport,
)
from .dream_store import DreamStore
from .runtime import OriginForgeRuntime


class DreamPlanningError(RuntimeError):
    pass


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DreamPlanResult:
    manifest: DreamInputManifest
    evidence_records: tuple[DreamEvidenceRecord, ...]
    active_memory_entries: tuple[MemoryEntry, ...]
    preprocess_report: DreamPreprocessReport
    candidates: tuple[DreamCandidate, ...]
    audits: tuple[DreamAuditReport, ...]

    def __post_init__(self) -> None:
        if len(self.candidates) != len(self.audits):
            raise DreamPlanningError("every Dream candidate must have exactly one audit report")
        audit_by_candidate = {item.candidate_id: item for item in self.audits}
        if len(audit_by_candidate) != len(self.audits):
            raise DreamPlanningError("Dream plan contains duplicate candidate audit reports")
        for candidate in self.candidates:
            audit = audit_by_candidate.get(candidate.candidate_id)
            if audit is None or audit.candidate_hash != candidate.content_hash:
                raise DreamPlanningError("Dream audit does not bind its candidate")
            if audit.manifest_id != self.manifest.manifest_id:
                raise DreamPlanningError("Dream audit does not bind the plan manifest")

    @property
    def content_hash(self) -> str:
        return _hash(
            {
                "manifest_hash": self.manifest.content_hash,
                "evidence": [
                    {
                        "record_type": item.record_type,
                        "ref": item.ref.to_dict(),
                    }
                    for item in self.evidence_records
                ],
                "active_memory": [
                    {"entry_id": item.entry_id, "content_hash": item.content_hash}
                    for item in self.active_memory_entries
                ],
                "preprocess_report_hash": self.preprocess_report.content_hash,
                "candidate_hashes": [item.content_hash for item in self.candidates],
                "audit_hashes": [item.content_hash for item in self.audits],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "evidence_record_count": len(self.evidence_records),
            "active_memory_entry_count": len(self.active_memory_entries),
            "preprocess_report": self.preprocess_report.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "audits": [item.to_dict() for item in self.audits],
            "content_hash": self.content_hash,
        }


class DreamPlanningCoordinator:
    """First proposal-only Dream cycle over completed durable work.

    This coordinator intentionally has no generation-building, source mutation,
    Skill promotion, routing-policy mutation, or model invocation operation.
    """

    def __init__(self, runtime: OriginForgeRuntime, store: DreamStore | None = None):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store = store or DreamStore(runtime)
        if self.store.runtime.project_root != runtime.project_root:
            raise DreamPlanningError("DreamStore and runtime must belong to the same project")
        self.collector = RuntimeDreamEvidenceCollector(runtime)
        self.resolver = RuntimeDreamEvidenceResolver(runtime)
        self.generation_builder = DreamGenerationBuilder(runtime, self.store)
        self.analyzer = DeterministicDreamAnalyzer()
        self.auditor = DeterministicDreamAuditor()

    @staticmethod
    def _merge_records(
        selected: DreamEvidenceBundle,
        resolved: tuple[DreamEvidenceRecord, ...],
    ) -> tuple[DreamEvidenceRecord, ...]:
        by_id: dict[str, DreamEvidenceRecord] = {}
        for record in (*selected.records, *resolved):
            existing = by_id.get(record.ref.ref_id)
            if existing is not None and existing != record:
                raise DreamPlanningError(
                    "durable evidence changed while Dream plan was being frozen: "
                    f"{record.ref.ref_id}"
                )
            by_id[record.ref.ref_id] = record
        return tuple(sorted(by_id.values(), key=lambda item: (item.record_type, item.ref.ref_id)))

    def _active_memory(
        self,
        parent_generation_id: str | None,
    ) -> tuple[MemoryEntry, ...]:
        snapshot = self.generation_builder.active_memory(parent_generation_id)
        entries: list[MemoryEntry] = []
        for pinned in snapshot.entries:
            entry = self.store.load_memory_entry(pinned.ref_id)
            if entry.content_hash != pinned.content_hash:
                raise DreamPlanningError(
                    f"active memory entry changed after generation was recorded: {pinned.ref_id}"
                )
            entries.append(entry)
        return tuple(sorted(entries, key=lambda item: item.entry_id))

    @staticmethod
    def _manifest_from_records(
        records: tuple[DreamEvidenceRecord, ...],
        memory_entries: tuple[MemoryEntry, ...],
        *,
        parent_generation_id: str | None,
        budget: DreamBudget,
        window_start: str | None,
        window_end: str | None,
    ) -> DreamInputManifest:
        return DreamInputManifest.create(
            parent_memory_generation_id=parent_generation_id,
            run_refs=(item.ref for item in records if item.record_type == "RUN"),
            task_refs=(item.ref for item in records if item.record_type == "TASK"),
            decision_refs=(item.ref for item in records if item.record_type == "DECISION"),
            verification_refs=(
                item.ref for item in records if item.record_type == "VERIFICATION"
            ),
            memory_refs=(item.as_evidence_ref() for item in memory_entries),
            window_start=window_start,
            window_end=window_end,
            budget=budget,
        )

    def plan(
        self,
        run_ids: Iterable[str],
        *,
        parent_generation_id: str | None = None,
        budget: DreamBudget | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> DreamPlanResult:
        effective_budget = budget or DreamBudget()
        selected = self.collector.collect(
            run_ids,
            parent_memory_generation_id=parent_generation_id,
            budget=effective_budget,
            window_start=window_start,
            window_end=window_end,
        )
        memory_entries = self._active_memory(parent_generation_id)

        pinned_dependencies = tuple(
            evidence
            for entry in memory_entries
            for evidence in entry.evidence_refs
        )
        unique_dependencies = {
            evidence.ref_id: evidence for evidence in pinned_dependencies
        }
        if len(unique_dependencies) != len({item.ref_id for item in pinned_dependencies}):
            raise DreamPlanningError("active memory evidence references are ambiguous")
        resolved = self.resolver.resolve(unique_dependencies.values())
        records = self._merge_records(selected, resolved.records)

        total_evidence_bytes = sum(item.byte_count for item in records)
        if total_evidence_bytes > effective_budget.max_total_evidence_bytes:
            raise DreamPlanningError(
                "Dream plan evidence exceeds frozen budget after resolving active-memory dependencies "
                f"({total_evidence_bytes} > {effective_budget.max_total_evidence_bytes})"
            )

        manifest = self._manifest_from_records(
            records,
            memory_entries,
            parent_generation_id=parent_generation_id,
            budget=effective_budget,
            window_start=window_start,
            window_end=window_end,
        )
        current_refs = tuple(item.ref for item in records) + tuple(
            item.as_evidence_ref() for item in memory_entries
        )
        snapshot = EvidenceSnapshot.create(
            current_refs,
            superseded_ref_ids=resolved.superseded_ref_ids,
        )
        preprocess_report = preprocess_memory(memory_entries, snapshot)
        package = DreamAnalysisPackage(manifest, preprocess_report, memory_entries)
        candidates = self.analyzer.analyze(package)
        if len(candidates) > effective_budget.max_candidates:
            raise DreamPlanningError("Dream analyzer exceeded frozen candidate budget")
        audits = tuple(
            self.auditor.audit(candidate, manifest, snapshot)
            for candidate in candidates
        )

        # Persistence is intentionally last: no partial plan is stored if any
        # deterministic collection/analysis/audit invariant fails.
        self.store.put_manifest(manifest)
        for candidate in candidates:
            self.store.put_candidate(candidate)
        for audit in audits:
            self.store.put_audit(audit)

        return DreamPlanResult(
            manifest=manifest,
            evidence_records=records,
            active_memory_entries=memory_entries,
            preprocess_report=preprocess_report,
            candidates=candidates,
            audits=audits,
        )
