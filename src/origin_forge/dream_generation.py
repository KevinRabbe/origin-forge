from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from .dream_evidence import verification_evidence_ref
from .dream_models import (
    DreamCandidate,
    DreamInputManifest,
    EvidenceRef,
    MemoryEntry,
    MemoryGeneration,
)
from .dream_store import DreamStore, DreamStoreError
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


class DreamGenerationError(RuntimeError):
    pass


def _manifest_ref_map(manifest: DreamInputManifest) -> dict[tuple[str, str, str, int | None], EvidenceRef]:
    result: dict[tuple[str, str, str, int | None], EvidenceRef] = {}
    for values in (
        manifest.run_refs,
        manifest.task_refs,
        manifest.decision_refs,
        manifest.verification_refs,
        manifest.memory_refs,
    ):
        for item in values:
            key = (
                item.ref_id,
                item.content_hash,
                item.evidence_class.value,
                item.revision,
            )
            result[key] = item
    return result


def _ref_key(ref: EvidenceRef) -> tuple[str, str, str, int | None]:
    return (ref.ref_id, ref.content_hash, ref.evidence_class.value, ref.revision)


def generation_audit_evidence(
    manifest: DreamInputManifest,
    *,
    accepted_entries: Iterable[MemoryEntry],
    superseded_entry_ids: Iterable[str] = (),
    deferred_candidates: Iterable[DreamCandidate] = (),
) -> dict[str, object]:
    """Canonical evidence payload that a PASS `dream-audit` Verification must bind."""

    if not isinstance(manifest, DreamInputManifest):
        raise TypeError("manifest must be a DreamInputManifest")
    entries = tuple(accepted_entries)
    candidates = tuple(deferred_candidates)
    if any(not isinstance(item, MemoryEntry) for item in entries):
        raise TypeError("accepted_entries must contain MemoryEntry values")
    if any(not isinstance(item, DreamCandidate) for item in candidates):
        raise TypeError("deferred_candidates must contain DreamCandidate values")
    superseded = tuple(superseded_entry_ids)
    if any(not isinstance(value, str) or not validate_id(value, IdKind.MEMORY_ENTRY) for value in superseded):
        raise DreamGenerationError("superseded_entry_ids contains invalid MEM IDs")
    if len(superseded) != len(set(superseded)):
        raise DreamGenerationError("superseded_entry_ids contains duplicates")
    if len({item.entry_id for item in entries}) != len(entries):
        raise DreamGenerationError("accepted_entries contains duplicate IDs")
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise DreamGenerationError("deferred_candidates contains duplicate IDs")
    return {
        "manifest_id": manifest.manifest_id,
        "manifest_hash": manifest.content_hash,
        "accepted_entry_refs": [
            {"entry_id": item.entry_id, "content_hash": item.content_hash}
            for item in sorted(entries, key=lambda value: value.entry_id)
        ],
        "superseded_entry_ids": sorted(superseded),
        "deferred_candidate_refs": [
            {"candidate_id": item.candidate_id, "content_hash": item.content_hash}
            for item in sorted(candidates, key=lambda value: value.candidate_id)
        ],
    }


@dataclass(frozen=True)
class ActiveMemorySnapshot:
    parent_generation_id: str | None
    entries: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        values = tuple(self.entries)
        if any(not isinstance(item, EvidenceRef) for item in values):
            raise DreamGenerationError("active memory snapshot must contain EvidenceRef values")
        object.__setattr__(self, "entries", tuple(sorted(values, key=lambda item: item.ref_id)))

    @property
    def content_hash(self) -> str:
        import hashlib

        encoded = json.dumps(
            {
                "parent_generation_id": self.parent_generation_id,
                "entries": [item.to_dict() for item in self.entries],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DreamGenerationBuilder:
    """Construct and revalidate immutable generations from audit-bound inputs."""

    def __init__(self, runtime: OriginForgeRuntime, store: DreamStore):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(store, DreamStore):
            raise TypeError("store must be a DreamStore")
        if store.runtime.project_root != runtime.project_root:
            raise DreamGenerationError("DreamStore and runtime must belong to the same project")
        self.runtime = runtime
        self.store = store

    def _verification_ref(
        self,
        verification_id: str,
        *,
        dream_run_id: str,
        expected_evidence: dict[str, object],
    ) -> EvidenceRef:
        if not validate_id(verification_id, IdKind.VERIFICATION):
            raise DreamGenerationError("audit_verification_id must be a VERIFY ID")
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
        if row is None:
            raise DreamGenerationError(f"audit Verification does not exist: {verification_id}")
        value = dict(row)
        if value["target_type"] != "RUN" or value["target_id"] != dream_run_id:
            raise DreamGenerationError("audit Verification must target the exact Dream RUN")
        if value["verification_type"] != "dream-audit":
            raise DreamGenerationError("audit Verification type must be exactly 'dream-audit'")
        if value["status"] != "PASS":
            raise DreamGenerationError("audit Verification must have PASS status")
        try:
            evidence = json.loads(value["evidence_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise DreamGenerationError("audit Verification contains invalid JSON evidence") from exc
        if evidence != expected_evidence:
            raise DreamGenerationError(
                "audit Verification evidence does not bind the exact generation inputs"
            )
        try:
            return verification_evidence_ref(value)
        except Exception as exc:
            raise DreamGenerationError("audit Verification canonical record is invalid") from exc

    def _validate_stored_generation(self, generation: MemoryGeneration) -> None:
        try:
            manifest = self.store.load_manifest(generation.input_manifest_id)
        except (KeyError, DreamStoreError) as exc:
            raise DreamGenerationError(
                f"stored generation manifest is unavailable or invalid: {generation.input_manifest_id}"
            ) from exc
        if manifest.content_hash != generation.input_manifest_hash:
            raise DreamGenerationError(
                f"stored generation manifest hash mismatch: {generation.generation_id}"
            )
        if manifest.parent_memory_generation_id != generation.parent_generation_id:
            raise DreamGenerationError(
                f"stored generation manifest parent mismatch: {generation.generation_id}"
            )

        entries: list[MemoryEntry] = []
        for pinned in generation.accepted_entry_refs:
            try:
                entry = self.store.load_memory_entry(pinned.ref_id)
            except (KeyError, DreamStoreError) as exc:
                raise DreamGenerationError(
                    f"stored generation memory entry is unavailable or invalid: {pinned.ref_id}"
                ) from exc
            if entry.content_hash != pinned.content_hash:
                raise DreamGenerationError(
                    f"stored generation memory entry hash mismatch: {pinned.ref_id}"
                )
            entries.append(entry)

        candidates: list[DreamCandidate] = []
        for candidate_id in generation.deferred_candidate_ids:
            try:
                candidate = self.store.load_candidate(candidate_id)
            except (KeyError, DreamStoreError) as exc:
                raise DreamGenerationError(
                    f"stored generation deferred candidate is unavailable or invalid: {candidate_id}"
                ) from exc
            candidates.append(candidate)

        expected_evidence = generation_audit_evidence(
            manifest,
            accepted_entries=entries,
            superseded_entry_ids=generation.superseded_entry_ids,
            deferred_candidates=candidates,
        )
        current_ref = self._verification_ref(
            generation.audit_verification_ref.ref_id,
            dream_run_id=generation.dream_run_id,
            expected_evidence=expected_evidence,
        )
        if current_ref != generation.audit_verification_ref:
            raise DreamGenerationError(
                f"stored generation audit Verification changed after generation creation: {generation.generation_id}"
            )

    def _active_memory(self, parent_generation_id: str | None) -> ActiveMemorySnapshot:
        if parent_generation_id is None:
            return ActiveMemorySnapshot(None, ())
        if not validate_id(parent_generation_id, IdKind.MEMORY_GENERATION):
            raise DreamGenerationError("parent_generation_id must be a MEMGEN ID or null")

        chain: list[MemoryGeneration] = []
        seen: set[str] = set()
        current_id: str | None = parent_generation_id
        while current_id is not None:
            if current_id in seen:
                raise DreamGenerationError("memory generation parent chain contains a cycle")
            seen.add(current_id)
            if len(chain) >= self.store.max_generations:
                raise DreamGenerationError("memory generation parent chain exceeds store limit")
            try:
                generation = self.store.load_generation(current_id)
            except (KeyError, DreamStoreError) as exc:
                raise DreamGenerationError(
                    f"memory generation parent is unavailable or invalid: {current_id}"
                ) from exc
            self._validate_stored_generation(generation)
            chain.append(generation)
            current_id = generation.parent_generation_id

        active: dict[str, EvidenceRef] = {}
        for generation in reversed(chain):
            for entry_id in generation.superseded_entry_ids:
                if entry_id not in active:
                    raise DreamGenerationError(
                        f"generation {generation.generation_id} supersedes inactive memory {entry_id}"
                    )
                del active[entry_id]
            for pinned in generation.accepted_entry_refs:
                if pinned.ref_id in active:
                    raise DreamGenerationError(
                        f"generation re-accepts already active memory entry: {pinned.ref_id}"
                    )
                active[pinned.ref_id] = pinned

        return ActiveMemorySnapshot(parent_generation_id, tuple(active.values()))

    def active_memory(self, parent_generation_id: str | None) -> ActiveMemorySnapshot:
        return self._active_memory(parent_generation_id)

    def build(
        self,
        *,
        parent_generation_id: str | None,
        dream_run_id: str,
        manifest_id: str,
        accepted_entry_ids: Iterable[str] = (),
        superseded_entry_ids: Iterable[str] = (),
        deferred_candidate_ids: Iterable[str] = (),
        audit_verification_id: str,
    ) -> MemoryGeneration:
        try:
            self.runtime.get_run(dream_run_id)
        except KeyError as exc:
            raise DreamGenerationError(f"Dream RUN does not exist: {dream_run_id}") from exc

        try:
            manifest = self.store.load_manifest(manifest_id)
        except (KeyError, DreamStoreError) as exc:
            raise DreamGenerationError(f"Dream manifest is unavailable or invalid: {manifest_id}") from exc
        if manifest.parent_memory_generation_id != parent_generation_id:
            raise DreamGenerationError(
                "Dream manifest parent generation does not match requested generation parent"
            )

        parent_snapshot = self._active_memory(parent_generation_id)
        active = {item.ref_id: item for item in parent_snapshot.entries}

        accepted_ids = tuple(accepted_entry_ids)
        superseded_ids = tuple(superseded_entry_ids)
        deferred_ids = tuple(deferred_candidate_ids)
        if len(accepted_ids) != len(set(accepted_ids)):
            raise DreamGenerationError("accepted_entry_ids contains duplicates")
        if len(superseded_ids) != len(set(superseded_ids)):
            raise DreamGenerationError("superseded_entry_ids contains duplicates")
        if len(deferred_ids) != len(set(deferred_ids)):
            raise DreamGenerationError("deferred_candidate_ids contains duplicates")

        entries: list[MemoryEntry] = []
        for entry_id in accepted_ids:
            try:
                entry = self.store.load_memory_entry(entry_id)
            except (KeyError, DreamStoreError) as exc:
                raise DreamGenerationError(
                    f"accepted memory entry is unavailable or invalid: {entry_id}"
                ) from exc
            entries.append(entry)

        candidates: list[DreamCandidate] = []
        for candidate_id in deferred_ids:
            try:
                candidate = self.store.load_candidate(candidate_id)
            except (KeyError, DreamStoreError) as exc:
                raise DreamGenerationError(
                    f"deferred candidate is unavailable or invalid: {candidate_id}"
                ) from exc
            if candidate.target_memory_generation_id not in (None, parent_generation_id):
                raise DreamGenerationError(
                    f"deferred candidate targets a different memory generation: {candidate_id}"
                )
            candidates.append(candidate)

        for entry_id in superseded_ids:
            if entry_id not in active:
                raise DreamGenerationError(
                    f"cannot supersede inactive memory entry: {entry_id}"
                )

        manifest_refs = _manifest_ref_map(manifest)
        for entry in entries:
            for evidence in entry.evidence_refs:
                if _ref_key(evidence) not in manifest_refs:
                    raise DreamGenerationError(
                        f"accepted memory entry cites evidence outside frozen manifest: {entry.entry_id}"
                    )
        for candidate in candidates:
            for evidence in (*candidate.evidence_refs, *candidate.contradiction_refs):
                if _ref_key(evidence) not in manifest_refs:
                    raise DreamGenerationError(
                        f"deferred candidate cites evidence outside frozen manifest: {candidate.candidate_id}"
                    )

        superseded_set = set(superseded_ids)
        declared_supersessions = {
            superseded
            for entry in entries
            for superseded in entry.supersedes
        }
        if not declared_supersessions.issubset(superseded_set):
            raise DreamGenerationError(
                "accepted memory entry declares supersession not recorded by generation"
            )

        remaining_hashes = {
            pinned.content_hash
            for entry_id, pinned in active.items()
            if entry_id not in superseded_set
        }
        for entry in entries:
            if entry.entry_id in active:
                raise DreamGenerationError(
                    f"cannot re-accept already active memory entry: {entry.entry_id}"
                )
            if entry.content_hash in remaining_hashes:
                raise DreamGenerationError(
                    f"accepted memory entry duplicates active semantic memory: {entry.entry_id}"
                )
            remaining_hashes.add(entry.content_hash)

        expected_evidence = generation_audit_evidence(
            manifest,
            accepted_entries=entries,
            superseded_entry_ids=superseded_ids,
            deferred_candidates=candidates,
        )
        audit_ref = self._verification_ref(
            audit_verification_id,
            dream_run_id=dream_run_id,
            expected_evidence=expected_evidence,
        )

        generation = MemoryGeneration.create(
            parent_generation_id=parent_generation_id,
            dream_run_id=dream_run_id,
            input_manifest=manifest,
            accepted_entries=entries,
            superseded_entry_ids=superseded_ids,
            deferred_candidate_ids=deferred_ids,
            audit_verification_ref=audit_ref,
        )
        self.store.put_generation(generation)
        return generation
