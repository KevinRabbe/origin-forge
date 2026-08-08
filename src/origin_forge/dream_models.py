from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_REF_ID_CHARS = 256
_MAX_EVIDENCE_REFS = 4096
_MAX_CLAIM_CHARS = 8192
_MAX_ACTION_CHARS = 4096
_MAX_SUPERSESSION_IDS = 256

_MAX_RUNS_HARD = 1000
_MAX_EVIDENCE_BYTES_HARD = 64 * 1024 * 1024
_MAX_CANDIDATES_HARD = 1024
_MAX_MODEL_CALLS_HARD = 32
_MAX_ANALYSIS_TOKENS_HARD = 2_000_000
_MAX_ELAPSED_SECONDS_HARD = 24 * 60 * 60
_MAX_RETRIES_HARD = 8


class DreamModelError(ValueError):
    pass


class EvidenceClass(StrEnum):
    CANONICAL = "CANONICAL"
    VERIFICATION = "VERIFICATION"
    TRAJECTORY = "TRAJECTORY"
    DERIVED_MEMORY = "DERIVED_MEMORY"
    BENCHMARK = "BENCHMARK"


class MemoryKind(StrEnum):
    ARCHITECTURAL_FACT = "ARCHITECTURAL_FACT"
    PROJECT_CONVENTION = "PROJECT_CONVENTION"
    PREFERENCE = "PREFERENCE"
    ENTITY_RELATION = "ENTITY_RELATION"
    PROCEDURAL_OBSERVATION = "PROCEDURAL_OBSERVATION"


class MemoryStatus(StrEnum):
    VERIFIED_DERIVED = "VERIFIED_DERIVED"


class DreamCandidateType(StrEnum):
    MEMORY = "MEMORY"
    SKILL = "SKILL"
    ROUTING = "ROUTING"
    CONTEXT = "CONTEXT"
    PROCESS = "PROCESS"
    DATA_QUALITY = "DATA_QUALITY"


class DreamDownstreamGate(StrEnum):
    DREAM_AUDIT = "DREAM_AUDIT"
    SKILL_EVALUATION = "SKILL_EVALUATION"
    ROUTING_BENCHMARK = "ROUTING_BENCHMARK"
    CONTEXT_BENCHMARK = "CONTEXT_BENCHMARK"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"


_GATE_BY_TYPE = {
    DreamCandidateType.MEMORY: DreamDownstreamGate.DREAM_AUDIT,
    DreamCandidateType.SKILL: DreamDownstreamGate.SKILL_EVALUATION,
    DreamCandidateType.ROUTING: DreamDownstreamGate.ROUTING_BENCHMARK,
    DreamCandidateType.CONTEXT: DreamDownstreamGate.CONTEXT_BENCHMARK,
    DreamCandidateType.PROCESS: DreamDownstreamGate.ENGINEERING_REVIEW,
    DreamCandidateType.DATA_QUALITY: DreamDownstreamGate.DETERMINISTIC_VALIDATION,
}


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DreamModelError("Dream model content must be finite JSON data") from exc


def _content_hash(value: object) -> str:
    encoded = _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_hash(value: str, label: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise DreamModelError(f"{label} must be a lowercase sha256 content hash")
    return value


def _require_ref_id(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_REF_ID_CHARS
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DreamModelError(f"{label} must be a bounded non-whitespace reference ID")
    return value


def _require_text(value: str, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DreamModelError(f"{label} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise DreamModelError(f"{label} exceeds character limit ({len(normalized)} > {maximum})")
    return normalized


def _parse_timestamp(value: str | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DreamModelError(f"{label} must be an ISO-8601 timestamp or null")
    normalized = value.strip()
    parse_value = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise DreamModelError(f"{label} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DreamModelError(f"{label} must include a timezone")
    return parsed


def _sorted_unique_refs(
    values: Iterable["EvidenceRef"],
    *,
    label: str,
    require_nonempty: bool = False,
) -> tuple["EvidenceRef", ...]:
    result = tuple(values)
    if any(not isinstance(item, EvidenceRef) for item in result):
        raise DreamModelError(f"{label} must contain EvidenceRef values")
    if require_nonempty and not result:
        raise DreamModelError(f"{label} may not be empty")
    if len(result) > _MAX_EVIDENCE_REFS:
        raise DreamModelError(
            f"{label} exceeds evidence reference limit ({len(result)} > {_MAX_EVIDENCE_REFS})"
        )
    keys = [item.key for item in result]
    if len(keys) != len(set(keys)):
        raise DreamModelError(f"{label} contains duplicate evidence references")
    return tuple(sorted(result, key=lambda item: item.key))


def _sorted_unique_ids(
    values: Iterable[str],
    *,
    label: str,
    kind: IdKind,
    maximum: int,
) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) > maximum:
        raise DreamModelError(f"{label} exceeds item limit ({len(result)} > {maximum})")
    if any(not isinstance(value, str) or not validate_id(value, kind) for value in result):
        raise DreamModelError(f"{label} contains invalid {kind.value} IDs")
    if len(result) != len(set(result)):
        raise DreamModelError(f"{label} contains duplicate IDs")
    return tuple(sorted(result))


@dataclass(frozen=True)
class EvidenceRef:
    """Immutable pointer to exact evidence used by a Dream object."""

    ref_id: str
    content_hash: str
    evidence_class: EvidenceClass
    revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _require_ref_id(self.ref_id, "evidence ref_id"))
        object.__setattr__(
            self,
            "content_hash",
            _require_hash(self.content_hash, "evidence content_hash"),
        )
        if not isinstance(self.evidence_class, EvidenceClass):
            raise DreamModelError("evidence_class must be an EvidenceClass")
        if self.revision is not None and (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 0
        ):
            raise DreamModelError("evidence revision must be a non-negative integer or null")

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (
            self.ref_id,
            self.content_hash,
            self.evidence_class.value,
            -1 if self.revision is None else self.revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "evidence_class": self.evidence_class.value,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class DreamBudget:
    max_runs: int = 100
    max_total_evidence_bytes: int = 4 * 1024 * 1024
    max_candidates: int = 128
    max_model_calls: int = 4
    max_analysis_tokens: int = 131_072
    max_elapsed_seconds: int = 3600
    max_retries: int = 1

    def __post_init__(self) -> None:
        bounds = (
            (self.max_runs, "max_runs", 1, _MAX_RUNS_HARD),
            (
                self.max_total_evidence_bytes,
                "max_total_evidence_bytes",
                1,
                _MAX_EVIDENCE_BYTES_HARD,
            ),
            (self.max_candidates, "max_candidates", 1, _MAX_CANDIDATES_HARD),
            (self.max_model_calls, "max_model_calls", 0, _MAX_MODEL_CALLS_HARD),
            (
                self.max_analysis_tokens,
                "max_analysis_tokens",
                0,
                _MAX_ANALYSIS_TOKENS_HARD,
            ),
            (
                self.max_elapsed_seconds,
                "max_elapsed_seconds",
                1,
                _MAX_ELAPSED_SECONDS_HARD,
            ),
            (self.max_retries, "max_retries", 0, _MAX_RETRIES_HARD),
        )
        for value, name, minimum, maximum in bounds:
            if not isinstance(value, int) or isinstance(value, bool):
                raise DreamModelError(f"Dream budget {name} must be an integer")
            if value < minimum or value > maximum:
                raise DreamModelError(
                    f"Dream budget {name} must be between {minimum} and {maximum}"
                )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_runs": self.max_runs,
            "max_total_evidence_bytes": self.max_total_evidence_bytes,
            "max_candidates": self.max_candidates,
            "max_model_calls": self.max_model_calls,
            "max_analysis_tokens": self.max_analysis_tokens,
            "max_elapsed_seconds": self.max_elapsed_seconds,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True)
class DreamInputManifest:
    manifest_id: str
    parent_memory_generation_id: str | None
    run_refs: tuple[EvidenceRef, ...]
    task_refs: tuple[EvidenceRef, ...] = ()
    decision_refs: tuple[EvidenceRef, ...] = ()
    verification_refs: tuple[EvidenceRef, ...] = ()
    memory_refs: tuple[EvidenceRef, ...] = ()
    window_start: str | None = None
    window_end: str | None = None
    budget: DreamBudget = DreamBudget()

    def __post_init__(self) -> None:
        if not validate_id(self.manifest_id, IdKind.DREAM_MANIFEST):
            raise DreamModelError("manifest_id must be a DREAMIN ID")
        if self.parent_memory_generation_id is not None and not validate_id(
            self.parent_memory_generation_id, IdKind.MEMORY_GENERATION
        ):
            raise DreamModelError("parent_memory_generation_id must be a MEMGEN ID or null")
        if not isinstance(self.budget, DreamBudget):
            raise DreamModelError("budget must be a DreamBudget")

        run_refs = _sorted_unique_refs(self.run_refs, label="run_refs")
        task_refs = _sorted_unique_refs(self.task_refs, label="task_refs")
        decision_refs = _sorted_unique_refs(self.decision_refs, label="decision_refs")
        verification_refs = _sorted_unique_refs(
            self.verification_refs, label="verification_refs"
        )
        memory_refs = _sorted_unique_refs(self.memory_refs, label="memory_refs")
        if len(run_refs) > self.budget.max_runs:
            raise DreamModelError(
                f"run_refs exceeds Dream budget ({len(run_refs)} > {self.budget.max_runs})"
            )
        total_refs = sum(
            len(values)
            for values in (run_refs, task_refs, decision_refs, verification_refs, memory_refs)
        )
        if total_refs > _MAX_EVIDENCE_REFS:
            raise DreamModelError(
                f"Dream input manifest exceeds evidence reference limit ({total_refs} > {_MAX_EVIDENCE_REFS})"
            )

        start = _parse_timestamp(self.window_start, "window_start")
        end = _parse_timestamp(self.window_end, "window_end")
        if (start is None) != (end is None):
            raise DreamModelError("Dream input window requires both start and end or neither")
        if start is not None and end is not None and start > end:
            raise DreamModelError("Dream input window start must not be after end")

        object.__setattr__(self, "run_refs", run_refs)
        object.__setattr__(self, "task_refs", task_refs)
        object.__setattr__(self, "decision_refs", decision_refs)
        object.__setattr__(self, "verification_refs", verification_refs)
        object.__setattr__(self, "memory_refs", memory_refs)

    @classmethod
    def create(
        cls,
        *,
        parent_memory_generation_id: str | None = None,
        run_refs: Iterable[EvidenceRef] = (),
        task_refs: Iterable[EvidenceRef] = (),
        decision_refs: Iterable[EvidenceRef] = (),
        verification_refs: Iterable[EvidenceRef] = (),
        memory_refs: Iterable[EvidenceRef] = (),
        window_start: str | None = None,
        window_end: str | None = None,
        budget: DreamBudget | None = None,
    ) -> "DreamInputManifest":
        return cls(
            manifest_id=new_id(IdKind.DREAM_MANIFEST),
            parent_memory_generation_id=parent_memory_generation_id,
            run_refs=tuple(run_refs),
            task_refs=tuple(task_refs),
            decision_refs=tuple(decision_refs),
            verification_refs=tuple(verification_refs),
            memory_refs=tuple(memory_refs),
            window_start=window_start,
            window_end=window_end,
            budget=budget or DreamBudget(),
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "parent_memory_generation_id": self.parent_memory_generation_id,
            "run_refs": [item.to_dict() for item in self.run_refs],
            "task_refs": [item.to_dict() for item in self.task_refs],
            "decision_refs": [item.to_dict() for item in self.decision_refs],
            "verification_refs": [item.to_dict() for item in self.verification_refs],
            "memory_refs": [item.to_dict() for item in self.memory_refs],
            "window_start": self.window_start,
            "window_end": self.window_end,
            "budget": self.budget.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    kind: MemoryKind
    claim: str
    evidence_refs: tuple[EvidenceRef, ...]
    supersedes: tuple[str, ...] = ()
    valid_from: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.entry_id, IdKind.MEMORY_ENTRY):
            raise DreamModelError("entry_id must be a MEM ID")
        if not isinstance(self.kind, MemoryKind):
            raise DreamModelError("memory kind must be a MemoryKind")
        object.__setattr__(
            self,
            "claim",
            _require_text(self.claim, "memory claim", maximum=_MAX_CLAIM_CHARS),
        )
        evidence_refs = _sorted_unique_refs(
            self.evidence_refs,
            label="memory evidence_refs",
            require_nonempty=True,
        )
        supersedes = _sorted_unique_ids(
            self.supersedes,
            label="memory supersedes",
            kind=IdKind.MEMORY_ENTRY,
            maximum=_MAX_SUPERSESSION_IDS,
        )
        _parse_timestamp(self.valid_from, "memory valid_from")
        if self.entry_id in supersedes:
            raise DreamModelError("memory entry cannot supersede itself")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "supersedes", supersedes)

    @classmethod
    def create(
        cls,
        *,
        kind: MemoryKind,
        claim: str,
        evidence_refs: Iterable[EvidenceRef],
        supersedes: Iterable[str] = (),
        valid_from: str | None = None,
    ) -> "MemoryEntry":
        return cls(
            entry_id=new_id(IdKind.MEMORY_ENTRY),
            kind=kind,
            claim=claim,
            evidence_refs=tuple(evidence_refs),
            supersedes=tuple(supersedes),
            valid_from=valid_from,
        )

    @property
    def status(self) -> MemoryStatus:
        return MemoryStatus.VERIFIED_DERIVED

    def _content_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "claim": self.claim,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "supersedes": list(self.supersedes),
            "valid_from": self.valid_from,
            "status": self.status.value,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }

    def as_evidence_ref(self) -> EvidenceRef:
        return EvidenceRef(
            self.entry_id,
            self.content_hash,
            EvidenceClass.DERIVED_MEMORY,
        )


@dataclass(frozen=True)
class DreamCandidate:
    candidate_id: str
    candidate_type: DreamCandidateType
    summary: str
    proposed_action: str
    evidence_refs: tuple[EvidenceRef, ...]
    contradiction_refs: tuple[EvidenceRef, ...] = ()
    target_memory_generation_id: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.candidate_id, IdKind.DREAM_CANDIDATE):
            raise DreamModelError("candidate_id must be a DREAM ID")
        if not isinstance(self.candidate_type, DreamCandidateType):
            raise DreamModelError("candidate_type must be a DreamCandidateType")
        object.__setattr__(
            self,
            "summary",
            _require_text(self.summary, "Dream candidate summary", maximum=_MAX_CLAIM_CHARS),
        )
        object.__setattr__(
            self,
            "proposed_action",
            _require_text(
                self.proposed_action,
                "Dream candidate proposed_action",
                maximum=_MAX_ACTION_CHARS,
            ),
        )
        evidence_refs = _sorted_unique_refs(
            self.evidence_refs,
            label="Dream candidate evidence_refs",
            require_nonempty=True,
        )
        contradiction_refs = _sorted_unique_refs(
            self.contradiction_refs,
            label="Dream candidate contradiction_refs",
        )
        if self.target_memory_generation_id is not None and not validate_id(
            self.target_memory_generation_id, IdKind.MEMORY_GENERATION
        ):
            raise DreamModelError("target_memory_generation_id must be a MEMGEN ID or null")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "contradiction_refs", contradiction_refs)

    @classmethod
    def create(
        cls,
        *,
        candidate_type: DreamCandidateType,
        summary: str,
        proposed_action: str,
        evidence_refs: Iterable[EvidenceRef],
        contradiction_refs: Iterable[EvidenceRef] = (),
        target_memory_generation_id: str | None = None,
    ) -> "DreamCandidate":
        return cls(
            candidate_id=new_id(IdKind.DREAM_CANDIDATE),
            candidate_type=candidate_type,
            summary=summary,
            proposed_action=proposed_action,
            evidence_refs=tuple(evidence_refs),
            contradiction_refs=tuple(contradiction_refs),
            target_memory_generation_id=target_memory_generation_id,
        )

    @property
    def required_gate(self) -> DreamDownstreamGate:
        return _GATE_BY_TYPE[self.candidate_type]

    def _content_dict(self) -> dict[str, object]:
        return {
            "candidate_type": self.candidate_type.value,
            "summary": self.summary,
            "proposed_action": self.proposed_action,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "contradiction_refs": [item.to_dict() for item in self.contradiction_refs],
            "target_memory_generation_id": self.target_memory_generation_id,
            "required_gate": self.required_gate.value,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class MemoryGeneration:
    generation_id: str
    parent_generation_id: str | None
    dream_run_id: str
    input_manifest_id: str
    input_manifest_hash: str
    accepted_entry_refs: tuple[EvidenceRef, ...]
    superseded_entry_ids: tuple[str, ...]
    deferred_candidate_ids: tuple[str, ...]
    audit_verification_ref: EvidenceRef

    def __post_init__(self) -> None:
        if not validate_id(self.generation_id, IdKind.MEMORY_GENERATION):
            raise DreamModelError("generation_id must be a MEMGEN ID")
        if self.parent_generation_id is not None and not validate_id(
            self.parent_generation_id, IdKind.MEMORY_GENERATION
        ):
            raise DreamModelError("parent_generation_id must be a MEMGEN ID or null")
        if self.parent_generation_id == self.generation_id:
            raise DreamModelError("memory generation cannot parent itself")
        if not validate_id(self.dream_run_id, IdKind.RUN):
            raise DreamModelError("dream_run_id must be a RUN ID")
        if not validate_id(self.input_manifest_id, IdKind.DREAM_MANIFEST):
            raise DreamModelError("input_manifest_id must be a DREAMIN ID")
        object.__setattr__(
            self,
            "input_manifest_hash",
            _require_hash(self.input_manifest_hash, "input_manifest_hash"),
        )

        accepted = _sorted_unique_refs(
            self.accepted_entry_refs,
            label="accepted_entry_refs",
        )
        for ref in accepted:
            if not validate_id(ref.ref_id, IdKind.MEMORY_ENTRY):
                raise DreamModelError("accepted_entry_refs must reference MEM IDs")
            if ref.evidence_class != EvidenceClass.DERIVED_MEMORY:
                raise DreamModelError(
                    "accepted_entry_refs must use DERIVED_MEMORY evidence class"
                )
        superseded = _sorted_unique_ids(
            self.superseded_entry_ids,
            label="superseded_entry_ids",
            kind=IdKind.MEMORY_ENTRY,
            maximum=_MAX_SUPERSESSION_IDS,
        )
        deferred = _sorted_unique_ids(
            self.deferred_candidate_ids,
            label="deferred_candidate_ids",
            kind=IdKind.DREAM_CANDIDATE,
            maximum=_MAX_EVIDENCE_REFS,
        )
        if not isinstance(self.audit_verification_ref, EvidenceRef):
            raise DreamModelError("audit_verification_ref must be an EvidenceRef")
        if not validate_id(self.audit_verification_ref.ref_id, IdKind.VERIFICATION):
            raise DreamModelError("audit_verification_ref must reference a VERIFY ID")
        if self.audit_verification_ref.evidence_class != EvidenceClass.VERIFICATION:
            raise DreamModelError(
                "audit_verification_ref must use VERIFICATION evidence class"
            )
        accepted_ids = {ref.ref_id for ref in accepted}
        if accepted_ids.intersection(superseded):
            raise DreamModelError(
                "a memory generation cannot both accept and supersede the same entry"
            )
        object.__setattr__(self, "accepted_entry_refs", accepted)
        object.__setattr__(self, "superseded_entry_ids", superseded)
        object.__setattr__(self, "deferred_candidate_ids", deferred)

    @classmethod
    def create(
        cls,
        *,
        parent_generation_id: str | None,
        dream_run_id: str,
        input_manifest: DreamInputManifest,
        accepted_entries: Iterable[MemoryEntry],
        superseded_entry_ids: Iterable[str] = (),
        deferred_candidate_ids: Iterable[str] = (),
        audit_verification_ref: EvidenceRef,
    ) -> "MemoryGeneration":
        if not isinstance(input_manifest, DreamInputManifest):
            raise DreamModelError("input_manifest must be a DreamInputManifest")
        entries = tuple(accepted_entries)
        if any(not isinstance(entry, MemoryEntry) for entry in entries):
            raise DreamModelError("accepted_entries must contain MemoryEntry values")
        return cls(
            generation_id=new_id(IdKind.MEMORY_GENERATION),
            parent_generation_id=parent_generation_id,
            dream_run_id=dream_run_id,
            input_manifest_id=input_manifest.manifest_id,
            input_manifest_hash=input_manifest.content_hash,
            accepted_entry_refs=tuple(entry.as_evidence_ref() for entry in entries),
            superseded_entry_ids=tuple(superseded_entry_ids),
            deferred_candidate_ids=tuple(deferred_candidate_ids),
            audit_verification_ref=audit_verification_ref,
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "parent_generation_id": self.parent_generation_id,
            "dream_run_id": self.dream_run_id,
            "input_manifest_id": self.input_manifest_id,
            "input_manifest_hash": self.input_manifest_hash,
            "accepted_entry_refs": [item.to_dict() for item in self.accepted_entry_refs],
            "superseded_entry_ids": list(self.superseded_entry_ids),
            "deferred_candidate_ids": list(self.deferred_candidate_ids),
            "audit_verification_ref": self.audit_verification_ref.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }
