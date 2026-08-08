from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .dream_models import (
    DreamCandidate,
    DreamCandidateType,
    DreamInputManifest,
    EvidenceRef,
    MemoryEntry,
)
from .dream_preprocess import DreamPreprocessReport, EvidenceSnapshot


class DreamRoleError(ValueError):
    pass


class DreamAuditStatus(StrEnum):
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class DreamAuditFindingCode(StrEnum):
    EVIDENCE_OUTSIDE_MANIFEST = "EVIDENCE_OUTSIDE_MANIFEST"
    EVIDENCE_NOT_CURRENT = "EVIDENCE_NOT_CURRENT"
    EVIDENCE_HASH_CHANGED = "EVIDENCE_HASH_CHANGED"
    EVIDENCE_REVISION_CHANGED = "EVIDENCE_REVISION_CHANGED"
    EVIDENCE_CLASS_CHANGED = "EVIDENCE_CLASS_CHANGED"
    TARGET_GENERATION_MISMATCH = "TARGET_GENERATION_MISMATCH"


_SEMANTIC_TYPES = frozenset(
    {
        DreamCandidateType.MEMORY,
        DreamCandidateType.SKILL,
        DreamCandidateType.ROUTING,
        DreamCandidateType.CONTEXT,
        DreamCandidateType.PROCESS,
    }
)


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
class DreamAnalysisPackage:
    """Frozen non-authoritative input presented to a Dream Analyzer.

    The package contains exact refs and derived memory/preprocessing results. It
    grants no filesystem, Skill, routing-policy, or canonical-state mutation
    capability by itself.
    """

    manifest: DreamInputManifest
    preprocess_report: DreamPreprocessReport
    memory_entries: tuple[MemoryEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, DreamInputManifest):
            raise DreamRoleError("analysis manifest must be a DreamInputManifest")
        if not isinstance(self.preprocess_report, DreamPreprocessReport):
            raise DreamRoleError("preprocess_report must be a DreamPreprocessReport")
        entries = tuple(self.memory_entries)
        if any(not isinstance(item, MemoryEntry) for item in entries):
            raise DreamRoleError("memory_entries must contain MemoryEntry values")
        ids = [item.entry_id for item in entries]
        if len(ids) != len(set(ids)):
            raise DreamRoleError("analysis package contains duplicate memory entry IDs")
        if self.preprocess_report.memory_entry_count != len(entries):
            raise DreamRoleError(
                "analysis package memory entries do not match preprocessing report count"
            )
        object.__setattr__(
            self,
            "memory_entries",
            tuple(sorted(entries, key=lambda item: item.entry_id)),
        )

    @property
    def content_hash(self) -> str:
        return _hash(
            {
                "manifest_id": self.manifest.manifest_id,
                "manifest_hash": self.manifest.content_hash,
                "preprocess_report_hash": self.preprocess_report.content_hash,
                "memory_entries": [
                    {"entry_id": item.entry_id, "content_hash": item.content_hash}
                    for item in self.memory_entries
                ],
            }
        )


class DreamAnalyzer(Protocol):
    """Proposal-only analyzer interface. Implementations receive no authority here."""

    def analyze(self, package: DreamAnalysisPackage) -> tuple[DreamCandidate, ...]: ...


@dataclass(frozen=True)
class DreamAuditFinding:
    code: DreamAuditFindingCode
    message: str
    evidence_ref_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, DreamAuditFindingCode):
            raise DreamRoleError("audit finding code must be a DreamAuditFindingCode")
        if not isinstance(self.message, str) or not self.message.strip():
            raise DreamRoleError("audit finding message must be non-empty")
        object.__setattr__(self, "message", self.message.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "evidence_ref_id": self.evidence_ref_id,
        }


@dataclass(frozen=True)
class DreamAuditReport:
    candidate_id: str
    candidate_hash: str
    manifest_id: str
    manifest_hash: str
    evidence_snapshot_hash: str
    status: DreamAuditStatus
    required_gate: str
    semantic_review_required: bool
    findings: tuple[DreamAuditFinding, ...]

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = {
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "manifest_id": self.manifest_id,
            "manifest_hash": self.manifest_hash,
            "evidence_snapshot_hash": self.evidence_snapshot_hash,
            "status": self.status.value,
            "required_gate": self.required_gate,
            "semantic_review_required": self.semantic_review_required,
            "findings": [item.to_dict() for item in self.findings],
        }
        if include_hash:
            payload["content_hash"] = self.content_hash
        return payload


class DreamAuditor(Protocol):
    """Independent candidate-review interface. It has no promotion operation."""

    def audit(
        self,
        candidate: DreamCandidate,
        manifest: DreamInputManifest,
        evidence_snapshot: EvidenceSnapshot,
    ) -> DreamAuditReport: ...


def _manifest_refs(manifest: DreamInputManifest) -> dict[str, EvidenceRef]:
    result: dict[str, EvidenceRef] = {}
    for values in (
        manifest.run_refs,
        manifest.task_refs,
        manifest.decision_refs,
        manifest.verification_refs,
        manifest.memory_refs,
    ):
        for item in values:
            current = result.get(item.ref_id)
            if current is not None and current != item:
                raise DreamRoleError(
                    f"manifest contains conflicting evidence refs for {item.ref_id}"
                )
            result[item.ref_id] = item
    return result


class DeterministicDreamAuditor:
    """Structural evidence auditor; it deliberately does not judge claim semantics."""

    def audit(
        self,
        candidate: DreamCandidate,
        manifest: DreamInputManifest,
        evidence_snapshot: EvidenceSnapshot,
    ) -> DreamAuditReport:
        if not isinstance(candidate, DreamCandidate):
            raise TypeError("candidate must be a DreamCandidate")
        if not isinstance(manifest, DreamInputManifest):
            raise TypeError("manifest must be a DreamInputManifest")
        if not isinstance(evidence_snapshot, EvidenceSnapshot):
            raise TypeError("evidence_snapshot must be an EvidenceSnapshot")

        frozen = _manifest_refs(manifest)
        current = evidence_snapshot.by_id()
        findings: list[DreamAuditFinding] = []
        rejected = False
        deferred = False

        for cited in (*candidate.evidence_refs, *candidate.contradiction_refs):
            frozen_ref = frozen.get(cited.ref_id)
            if frozen_ref is None or frozen_ref != cited:
                findings.append(
                    DreamAuditFinding(
                        DreamAuditFindingCode.EVIDENCE_OUTSIDE_MANIFEST,
                        "candidate evidence is not an exact ref from the frozen Dream manifest",
                        cited.ref_id,
                    )
                )
                rejected = True
                continue

            current_ref = current.get(cited.ref_id)
            if current_ref is None:
                findings.append(
                    DreamAuditFinding(
                        DreamAuditFindingCode.EVIDENCE_NOT_CURRENT,
                        "candidate evidence is no longer present in the current evidence snapshot",
                        cited.ref_id,
                    )
                )
                deferred = True
                continue
            if current_ref.content_hash != cited.content_hash:
                findings.append(
                    DreamAuditFinding(
                        DreamAuditFindingCode.EVIDENCE_HASH_CHANGED,
                        "candidate evidence content hash changed after the Dream snapshot",
                        cited.ref_id,
                    )
                )
                deferred = True
            if current_ref.revision != cited.revision:
                findings.append(
                    DreamAuditFinding(
                        DreamAuditFindingCode.EVIDENCE_REVISION_CHANGED,
                        "candidate evidence revision changed after the Dream snapshot",
                        cited.ref_id,
                    )
                )
                deferred = True
            if current_ref.evidence_class != cited.evidence_class:
                findings.append(
                    DreamAuditFinding(
                        DreamAuditFindingCode.EVIDENCE_CLASS_CHANGED,
                        "candidate evidence class changed after the Dream snapshot",
                        cited.ref_id,
                    )
                )
                deferred = True

        target = candidate.target_memory_generation_id
        if target is not None and target != manifest.parent_memory_generation_id:
            findings.append(
                DreamAuditFinding(
                    DreamAuditFindingCode.TARGET_GENERATION_MISMATCH,
                    "candidate targets a memory generation other than the frozen parent generation",
                )
            )
            rejected = True

        if rejected:
            status = DreamAuditStatus.REJECTED
        elif deferred:
            status = DreamAuditStatus.DEFERRED
        else:
            status = DreamAuditStatus.STRUCTURALLY_VALID

        findings.sort(key=lambda item: (item.code.value, item.evidence_ref_id or "", item.message))
        return DreamAuditReport(
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.content_hash,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.content_hash,
            evidence_snapshot_hash=evidence_snapshot.content_hash,
            status=status,
            required_gate=candidate.required_gate.value,
            semantic_review_required=candidate.candidate_type in _SEMANTIC_TYPES,
            findings=tuple(findings),
        )
