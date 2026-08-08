from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .dream_models import EvidenceRef, MemoryEntry


_MAX_MEMORY_ENTRIES = 2048
_MAX_CURRENT_EVIDENCE = 8192
_MAX_SUPERSEDED_REFS = 8192


class DreamPreprocessError(ValueError):
    pass


class DreamFindingType(StrEnum):
    DUPLICATE_MEMORY = "DUPLICATE_MEMORY"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EVIDENCE_HASH_CHANGED = "EVIDENCE_HASH_CHANGED"
    EVIDENCE_REVISION_CHANGED = "EVIDENCE_REVISION_CHANGED"
    SOURCE_SUPERSEDED = "SOURCE_SUPERSEDED"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EvidenceSnapshot:
    """One deterministic view of the evidence refs considered current.

    A ref may remain readable historically while also being listed in
    `superseded_ref_ids`. The snapshot does not alter canonical records; it only
    lets preprocessing identify derived memory that requires re-audit.
    """

    refs: tuple[EvidenceRef, ...]
    superseded_ref_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        refs = tuple(self.refs)
        if len(refs) > _MAX_CURRENT_EVIDENCE:
            raise DreamPreprocessError(
                f"current evidence exceeds limit ({len(refs)} > {_MAX_CURRENT_EVIDENCE})"
            )
        if any(not isinstance(item, EvidenceRef) for item in refs):
            raise DreamPreprocessError("current evidence must contain EvidenceRef values")
        ids = [item.ref_id for item in refs]
        if len(ids) != len(set(ids)):
            raise DreamPreprocessError("current evidence contains duplicate ref IDs")

        superseded = tuple(self.superseded_ref_ids)
        if len(superseded) > _MAX_SUPERSEDED_REFS:
            raise DreamPreprocessError(
                "superseded evidence ID count exceeds preprocessing limit"
            )
        if any(not isinstance(value, str) or not value for value in superseded):
            raise DreamPreprocessError("superseded evidence IDs must be non-empty strings")
        if len(superseded) != len(set(superseded)):
            raise DreamPreprocessError("superseded evidence IDs contain duplicates")

        object.__setattr__(self, "refs", tuple(sorted(refs, key=lambda item: item.ref_id)))
        object.__setattr__(self, "superseded_ref_ids", tuple(sorted(superseded)))

    @classmethod
    def create(
        cls,
        refs: Iterable[EvidenceRef],
        *,
        superseded_ref_ids: Iterable[str] = (),
    ) -> "EvidenceSnapshot":
        return cls(tuple(refs), tuple(superseded_ref_ids))

    @property
    def content_hash(self) -> str:
        return _canonical_hash(
            {
                "refs": [item.to_dict() for item in self.refs],
                "superseded_ref_ids": list(self.superseded_ref_ids),
            }
        )

    def by_id(self) -> dict[str, EvidenceRef]:
        return {item.ref_id: item for item in self.refs}


@dataclass(frozen=True)
class DreamPreprocessFinding:
    finding_type: DreamFindingType
    memory_entry_id: str
    related_entry_ids: tuple[str, ...] = ()
    evidence_ref_id: str | None = None
    expected_hash: str | None = None
    current_hash: str | None = None
    expected_revision: int | None = None
    current_revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.finding_type, DreamFindingType):
            raise DreamPreprocessError("finding_type must be a DreamFindingType")
        if not isinstance(self.memory_entry_id, str) or not self.memory_entry_id:
            raise DreamPreprocessError("memory_entry_id must be a non-empty string")
        related = tuple(self.related_entry_ids)
        if any(not isinstance(value, str) or not value for value in related):
            raise DreamPreprocessError("related_entry_ids must contain non-empty strings")
        if len(related) != len(set(related)):
            raise DreamPreprocessError("related_entry_ids contains duplicates")
        object.__setattr__(self, "related_entry_ids", tuple(sorted(related)))

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = {
            "finding_type": self.finding_type.value,
            "memory_entry_id": self.memory_entry_id,
            "related_entry_ids": list(self.related_entry_ids),
            "evidence_ref_id": self.evidence_ref_id,
            "expected_hash": self.expected_hash,
            "current_hash": self.current_hash,
            "expected_revision": self.expected_revision,
            "current_revision": self.current_revision,
        }
        if include_hash:
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True)
class DreamPreprocessReport:
    evidence_snapshot_hash: str
    memory_entry_count: int
    findings: tuple[DreamPreprocessFinding, ...]

    @property
    def content_hash(self) -> str:
        return _canonical_hash(
            {
                "evidence_snapshot_hash": self.evidence_snapshot_hash,
                "memory_entry_count": self.memory_entry_count,
                "findings": [item.to_dict() for item in self.findings],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_snapshot_hash": self.evidence_snapshot_hash,
            "memory_entry_count": self.memory_entry_count,
            "findings": [item.to_dict() for item in self.findings],
            "content_hash": self.content_hash,
        }


def preprocess_memory(
    entries: Iterable[MemoryEntry],
    evidence_snapshot: EvidenceSnapshot,
) -> DreamPreprocessReport:
    """Detect mechanically provable stale/duplicate derived memory.

    No finding mutates or retires a MemoryEntry. A later Dream Auditor or
    deterministic maintenance gate decides what, if anything, may be proposed.
    """

    if not isinstance(evidence_snapshot, EvidenceSnapshot):
        raise TypeError("evidence_snapshot must be an EvidenceSnapshot")
    values = tuple(entries)
    if len(values) > _MAX_MEMORY_ENTRIES:
        raise DreamPreprocessError(
            f"memory entry count exceeds limit ({len(values)} > {_MAX_MEMORY_ENTRIES})"
        )
    if any(not isinstance(item, MemoryEntry) for item in values):
        raise DreamPreprocessError("entries must contain MemoryEntry values")
    entry_ids = [item.entry_id for item in values]
    if len(entry_ids) != len(set(entry_ids)):
        raise DreamPreprocessError("memory entries contain duplicate entry IDs")

    findings: list[DreamPreprocessFinding] = []

    by_hash: dict[str, list[MemoryEntry]] = {}
    for entry in values:
        by_hash.setdefault(entry.content_hash, []).append(entry)
    for same_content in by_hash.values():
        if len(same_content) < 2:
            continue
        ordered = sorted(same_content, key=lambda item: item.entry_id)
        retained = ordered[0].entry_id
        for duplicate in ordered[1:]:
            findings.append(
                DreamPreprocessFinding(
                    DreamFindingType.DUPLICATE_MEMORY,
                    duplicate.entry_id,
                    related_entry_ids=(retained,),
                )
            )

    current_by_id = evidence_snapshot.by_id()
    superseded_ids = set(evidence_snapshot.superseded_ref_ids)
    for entry in sorted(values, key=lambda item: item.entry_id):
        for pinned in entry.evidence_refs:
            current = current_by_id.get(pinned.ref_id)
            if current is None:
                findings.append(
                    DreamPreprocessFinding(
                        DreamFindingType.MISSING_EVIDENCE,
                        entry.entry_id,
                        evidence_ref_id=pinned.ref_id,
                        expected_hash=pinned.content_hash,
                        expected_revision=pinned.revision,
                    )
                )
                continue
            if pinned.ref_id in superseded_ids:
                findings.append(
                    DreamPreprocessFinding(
                        DreamFindingType.SOURCE_SUPERSEDED,
                        entry.entry_id,
                        evidence_ref_id=pinned.ref_id,
                        expected_hash=pinned.content_hash,
                        current_hash=current.content_hash,
                        expected_revision=pinned.revision,
                        current_revision=current.revision,
                    )
                )
            if current.content_hash != pinned.content_hash:
                findings.append(
                    DreamPreprocessFinding(
                        DreamFindingType.EVIDENCE_HASH_CHANGED,
                        entry.entry_id,
                        evidence_ref_id=pinned.ref_id,
                        expected_hash=pinned.content_hash,
                        current_hash=current.content_hash,
                        expected_revision=pinned.revision,
                        current_revision=current.revision,
                    )
                )
            if (
                pinned.revision is not None
                and current.revision is not None
                and current.revision != pinned.revision
            ):
                findings.append(
                    DreamPreprocessFinding(
                        DreamFindingType.EVIDENCE_REVISION_CHANGED,
                        entry.entry_id,
                        evidence_ref_id=pinned.ref_id,
                        expected_hash=pinned.content_hash,
                        current_hash=current.content_hash,
                        expected_revision=pinned.revision,
                        current_revision=current.revision,
                    )
                )

    findings.sort(
        key=lambda item: (
            item.memory_entry_id,
            item.finding_type.value,
            item.evidence_ref_id or "",
            item.related_entry_ids,
        )
    )
    return DreamPreprocessReport(
        evidence_snapshot_hash=evidence_snapshot.content_hash,
        memory_entry_count=len(values),
        findings=tuple(findings),
    )
