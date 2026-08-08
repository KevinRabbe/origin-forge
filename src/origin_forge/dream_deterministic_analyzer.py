from __future__ import annotations

from .dream_models import DreamCandidate, DreamCandidateType, EvidenceRef
from .dream_preprocess import DreamFindingType
from .dream_roles import DreamAnalysisPackage, DreamRoleError


_ACTIONS = {
    DreamFindingType.DUPLICATE_MEMORY: (
        "Propose deterministic duplicate consolidation in a future audited memory generation; "
        "do not delete or rewrite either stored entry in place."
    ),
    DreamFindingType.MISSING_EVIDENCE: (
        "Treat the derived memory as requiring re-audit because its pinned evidence is unavailable; "
        "do not use this finding alone to invent replacement truth."
    ),
    DreamFindingType.EVIDENCE_HASH_CHANGED: (
        "Re-audit the derived memory against the current canonical evidence before it is reused or superseded."
    ),
    DreamFindingType.EVIDENCE_REVISION_CHANGED: (
        "Re-audit the derived memory against the current canonical revision before it is reused or superseded."
    ),
    DreamFindingType.SOURCE_SUPERSEDED: (
        "Review the superseding canonical source and propose a new derived-memory entry only if independently supported."
    ),
}


class DeterministicDreamAnalyzer:
    """Convert deterministic preprocessing findings into proposal-only candidates.

    This analyzer does not infer new facts from trajectories. It exposes only
    data-quality work already proven mechanically by preprocessing.
    """

    def analyze(self, package: DreamAnalysisPackage) -> tuple[DreamCandidate, ...]:
        if not isinstance(package, DreamAnalysisPackage):
            raise TypeError("package must be a DreamAnalysisPackage")

        memory_by_id = {entry.entry_id: entry for entry in package.memory_entries}
        manifest_refs: dict[str, EvidenceRef] = {}
        for values in (
            package.manifest.run_refs,
            package.manifest.task_refs,
            package.manifest.decision_refs,
            package.manifest.verification_refs,
            package.manifest.memory_refs,
        ):
            for item in values:
                existing = manifest_refs.get(item.ref_id)
                if existing is not None and existing != item:
                    raise DreamRoleError(
                        f"manifest contains conflicting evidence refs for {item.ref_id}"
                    )
                manifest_refs[item.ref_id] = item

        candidates: list[DreamCandidate] = []
        for finding in package.preprocess_report.findings:
            entry = memory_by_id.get(finding.memory_entry_id)
            if entry is None:
                raise DreamRoleError(
                    f"preprocessing finding references unavailable memory entry: {finding.memory_entry_id}"
                )

            evidence: list[EvidenceRef] = []
            memory_ref = manifest_refs.get(entry.entry_id)
            if memory_ref is None or memory_ref != entry.as_evidence_ref():
                raise DreamRoleError(
                    f"memory entry is not pinned by the frozen Dream manifest: {entry.entry_id}"
                )
            evidence.append(memory_ref)

            if finding.evidence_ref_id is not None:
                pinned = manifest_refs.get(finding.evidence_ref_id)
                if pinned is not None:
                    evidence.append(pinned)

            for related_entry_id in finding.related_entry_ids:
                related = memory_by_id.get(related_entry_id)
                if related is None:
                    raise DreamRoleError(
                        f"duplicate finding references unavailable memory entry: {related_entry_id}"
                    )
                related_ref = manifest_refs.get(related_entry_id)
                if related_ref is None or related_ref != related.as_evidence_ref():
                    raise DreamRoleError(
                        f"related memory entry is not pinned by the frozen Dream manifest: {related_entry_id}"
                    )
                evidence.append(related_ref)

            unique = {item.key: item for item in evidence}
            evidence_refs = tuple(unique[key] for key in sorted(unique))
            summary = (
                f"{finding.finding_type.value}: derived memory {finding.memory_entry_id} "
                "requires deterministic consolidation review."
            )
            candidates.append(
                DreamCandidate.create(
                    candidate_type=DreamCandidateType.DATA_QUALITY,
                    summary=summary,
                    proposed_action=_ACTIONS[finding.finding_type],
                    evidence_refs=evidence_refs,
                    target_memory_generation_id=package.manifest.parent_memory_generation_id,
                )
            )
            if len(candidates) > package.manifest.budget.max_candidates:
                raise DreamRoleError(
                    "deterministic Dream candidates exceed frozen manifest budget "
                    f"({len(candidates)} > {package.manifest.budget.max_candidates})"
                )

        return tuple(candidates)
