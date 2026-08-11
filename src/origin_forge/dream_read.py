from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, TypeVar

from .dream_models import (
    DreamCandidate,
    DreamInputManifest,
    MemoryEntry,
    MemoryGeneration,
)
from .dream_roles import DreamAuditReport
from .dream_store import (
    DreamStoreError,
    _audit_report,
    _candidate,
    _generation,
    _manifest,
    _memory_entry,
)
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


_T = TypeVar("_T")
_FORMAT_VERSION = 1
_AUDIT_RE = re.compile(r"^DREAM-AUDIT-[0-9a-f]{64}$")
_MAX_MANIFESTS = 1024
_MAX_CANDIDATES = 8192
_MAX_AUDITS = 16384
_MAX_MEMORY_ENTRIES = 4096
_MAX_GENERATIONS = 2048
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 256 * 1024
_MAX_AUDIT_BYTES = 512 * 1024
_MAX_MEMORY_ENTRY_BYTES = 256 * 1024
_MAX_GENERATION_BYTES = 512 * 1024


class DreamReadError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DreamReadError(f"duplicate Dream JSON key: {key}")
        result[key] = value
    return result


def _canonical_bytes(kind: str, payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            {"format_version": _FORMAT_VERSION, "kind": kind, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _audit_id(value: DreamAuditReport) -> str:
    return "DREAM-AUDIT-" + value.content_hash.split(":", 1)[1]


class DreamReadService:
    """Non-creating inspection of immutable Dream and memory objects."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "dream"
        self.manifests_dir = self.root / "manifests"
        self.candidates_dir = self.root / "candidates"
        self.audits_dir = self.root / "audits"
        self.memory_root = self.root / "memory"
        self.memory_entries_dir = self.memory_root / "entries"
        self.generations_dir = self.memory_root / "generations"

    def _registry_root(self) -> Path | None:
        state = self.runtime.state_dir.resolve(strict=True)
        if not self.root.exists() and not self.root.is_symlink():
            return None
        if self.root.is_symlink() or not self.root.is_dir():
            raise DreamReadError("invalid Dream registry root")
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DreamReadError("Dream registry escaped protected state") from exc
        return resolved

    def _directory(self, path: Path) -> Path | None:
        root = self._registry_root()
        if root is None:
            return None
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_dir():
            raise DreamReadError(f"invalid Dream directory: {path.name}")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DreamReadError("Dream directory escaped registry root") from exc
        return resolved

    @staticmethod
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise DreamReadError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if not data or len(data) > maximum:
            raise DreamReadError(f"{label} byte size is outside bounds")
        return data

    def _list_ids(
        self,
        directory: Path,
        *,
        maximum: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> tuple[str, ...]:
        resolved = self._directory(directory)
        if resolved is None:
            return ()
        values: list[str] = []
        for path in resolved.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise DreamReadError(
                    f"{label} registry contains unsupported entry: {path.name}"
                )
            object_id = path.stem
            if not validator(object_id):
                raise DreamReadError(f"{label} registry contains invalid ID")
            values.append(object_id)
            if len(values) > maximum:
                raise DreamReadError(f"{label} catalog exceeds bound")
        return tuple(sorted(values))

    def _load(
        self,
        directory: Path,
        *,
        object_id: str,
        kind: str,
        maximum_bytes: int,
        validator: Callable[[str], bool],
        parser: Callable[[object], _T],
        loaded_id: Callable[[_T], str],
        to_dict: Callable[[_T], dict[str, object]],
        label: str,
    ) -> _T:
        if not validator(object_id):
            raise KeyError(object_id)
        resolved = self._directory(directory)
        if resolved is None:
            raise KeyError(object_id)
        path = resolved / f"{object_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(object_id)
        data = self._bounded_read(path, maximum_bytes, label)
        try:
            envelope = json.loads(
                data.decode("utf-8"), object_pairs_hook=_strict_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DreamReadError(f"invalid {label} JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "format_version",
            "kind",
            "payload",
        }:
            raise DreamReadError(f"invalid {label} envelope")
        if envelope["format_version"] != _FORMAT_VERSION or envelope["kind"] != kind:
            raise DreamReadError(f"invalid {label} envelope metadata")
        try:
            value = parser(envelope["payload"])
        except DreamStoreError as exc:
            raise DreamReadError(f"{label} validation failed") from exc
        if loaded_id(value) != object_id:
            raise DreamReadError(f"{label} filename/ID mismatch")
        if _canonical_bytes(kind, to_dict(value)) != data:
            raise DreamReadError(f"{label} bytes are not canonical")
        return value

    def manifest_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.manifests_dir,
            maximum=_MAX_MANIFESTS,
            validator=lambda value: validate_id(value, IdKind.DREAM_MANIFEST),
            label="Dream manifest",
        )

    def candidate_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.candidates_dir,
            maximum=_MAX_CANDIDATES,
            validator=lambda value: validate_id(value, IdKind.DREAM_CANDIDATE),
            label="Dream candidate",
        )

    def audit_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.audits_dir,
            maximum=_MAX_AUDITS,
            validator=lambda value: bool(_AUDIT_RE.fullmatch(value)),
            label="Dream audit",
        )

    def memory_entry_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.memory_entries_dir,
            maximum=_MAX_MEMORY_ENTRIES,
            validator=lambda value: validate_id(value, IdKind.MEMORY_ENTRY),
            label="memory entry",
        )

    def generation_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.generations_dir,
            maximum=_MAX_GENERATIONS,
            validator=lambda value: validate_id(value, IdKind.MEMORY_GENERATION),
            label="memory generation",
        )

    def counts(self) -> dict[str, int]:
        return {
            "manifests": len(self.manifest_ids()),
            "candidates": len(self.candidate_ids()),
            "audits": len(self.audit_ids()),
            "memory_entries": len(self.memory_entry_ids()),
            "generations": len(self.generation_ids()),
        }

    def load_manifest(self, object_id: str) -> DreamInputManifest:
        return self._load(
            self.manifests_dir,
            object_id=object_id,
            kind="DREAM_INPUT_MANIFEST",
            maximum_bytes=_MAX_MANIFEST_BYTES,
            validator=lambda value: validate_id(value, IdKind.DREAM_MANIFEST),
            parser=_manifest,
            loaded_id=lambda value: value.manifest_id,
            to_dict=lambda value: value.to_dict(),
            label="Dream manifest",
        )

    def load_candidate(self, object_id: str) -> DreamCandidate:
        return self._load(
            self.candidates_dir,
            object_id=object_id,
            kind="DREAM_CANDIDATE",
            maximum_bytes=_MAX_CANDIDATE_BYTES,
            validator=lambda value: validate_id(value, IdKind.DREAM_CANDIDATE),
            parser=_candidate,
            loaded_id=lambda value: value.candidate_id,
            to_dict=lambda value: value.to_dict(),
            label="Dream candidate",
        )

    def load_audit(self, object_id: str) -> DreamAuditReport:
        return self._load(
            self.audits_dir,
            object_id=object_id,
            kind="DREAM_AUDIT_REPORT",
            maximum_bytes=_MAX_AUDIT_BYTES,
            validator=lambda value: bool(_AUDIT_RE.fullmatch(value)),
            parser=_audit_report,
            loaded_id=_audit_id,
            to_dict=lambda value: value.to_dict(),
            label="Dream audit",
        )

    def load_memory_entry(self, object_id: str) -> MemoryEntry:
        return self._load(
            self.memory_entries_dir,
            object_id=object_id,
            kind="MEMORY_ENTRY",
            maximum_bytes=_MAX_MEMORY_ENTRY_BYTES,
            validator=lambda value: validate_id(value, IdKind.MEMORY_ENTRY),
            parser=_memory_entry,
            loaded_id=lambda value: value.entry_id,
            to_dict=lambda value: value.to_dict(),
            label="memory entry",
        )

    def load_generation(self, object_id: str) -> MemoryGeneration:
        return self._load(
            self.generations_dir,
            object_id=object_id,
            kind="MEMORY_GENERATION",
            maximum_bytes=_MAX_GENERATION_BYTES,
            validator=lambda value: validate_id(value, IdKind.MEMORY_GENERATION),
            parser=_generation,
            loaded_id=lambda value: value.generation_id,
            to_dict=lambda value: value.to_dict(),
            label="memory generation",
        )

    def manifests(self, *, limit: int = 128) -> tuple[dict[str, object], ...]:
        return tuple(
            self._manifest_projection(self.load_manifest(value))
            for value in self._limited(self.manifest_ids(), limit, _MAX_MANIFESTS)
        )

    def candidates(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        return tuple(
            self._candidate_projection(self.load_candidate(value))
            for value in self._limited(self.candidate_ids(), limit, _MAX_CANDIDATES)
        )

    def audits(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        return tuple(
            self._audit_projection(value, self.load_audit(value))
            for value in self._limited(self.audit_ids(), limit, _MAX_AUDITS)
        )

    def memory_entries(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        return tuple(
            self._memory_projection(self.load_memory_entry(value))
            for value in self._limited(self.memory_entry_ids(), limit, _MAX_MEMORY_ENTRIES)
        )

    def generations(self, *, limit: int = 128) -> tuple[dict[str, object], ...]:
        return tuple(
            self._generation_projection(self.load_generation(value))
            for value in self._limited(self.generation_ids(), limit, _MAX_GENERATIONS)
        )

    @staticmethod
    def _limited(values: tuple[str, ...], limit: int, maximum: int) -> tuple[str, ...]:
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ValueError(f"Dream read limit must be 1..{maximum}")
        return values[:limit]

    @staticmethod
    def _manifest_projection(value: DreamInputManifest) -> dict[str, object]:
        return {
            "manifest_id": value.manifest_id,
            "content_hash": value.content_hash,
            "parent_memory_generation_id": value.parent_memory_generation_id,
            "run_ref_count": len(value.run_refs),
            "task_ref_count": len(value.task_refs),
            "decision_ref_count": len(value.decision_refs),
            "verification_ref_count": len(value.verification_refs),
            "memory_ref_count": len(value.memory_refs),
            "window_start": value.window_start,
            "window_end": value.window_end,
            "budget": value.budget.to_dict(),
            "evidence_refs_disclosed": False,
        }

    @staticmethod
    def _candidate_projection(value: DreamCandidate) -> dict[str, object]:
        return {
            "candidate_id": value.candidate_id,
            "content_hash": value.content_hash,
            "candidate_type": value.candidate_type.value,
            "summary": value.summary,
            "proposed_action": value.proposed_action,
            "required_gate": value.required_gate.value,
            "target_memory_generation_id": value.target_memory_generation_id,
            "evidence_ref_count": len(value.evidence_refs),
            "contradiction_ref_count": len(value.contradiction_refs),
            "evidence_refs_disclosed": False,
            "automatic_promotion_authorized": False,
        }

    @staticmethod
    def _audit_projection(object_id: str, value: DreamAuditReport) -> dict[str, object]:
        return {
            "audit_id": object_id,
            "content_hash": value.content_hash,
            "candidate_id": value.candidate_id,
            "candidate_hash": value.candidate_hash,
            "manifest_id": value.manifest_id,
            "manifest_hash": value.manifest_hash,
            "evidence_snapshot_hash": value.evidence_snapshot_hash,
            "status": value.status.value,
            "required_gate": value.required_gate,
            "semantic_review_required": value.semantic_review_required,
            "finding_count": len(value.findings),
            "finding_codes": [finding.code.value for finding in value.findings],
            "finding_messages_disclosed": False,
            "semantic_truth_verified_by_cockpit": False,
        }

    @staticmethod
    def _memory_projection(value: MemoryEntry) -> dict[str, object]:
        return {
            "entry_id": value.entry_id,
            "content_hash": value.content_hash,
            "kind": value.kind.value,
            "status": value.status.value,
            "claim": value.claim,
            "valid_from": value.valid_from,
            "evidence_ref_count": len(value.evidence_refs),
            "supersedes_count": len(value.supersedes),
            "evidence_refs_disclosed": False,
        }

    @staticmethod
    def _generation_projection(value: MemoryGeneration) -> dict[str, object]:
        return {
            "generation_id": value.generation_id,
            "content_hash": value.content_hash,
            "parent_generation_id": value.parent_generation_id,
            "dream_run_id": value.dream_run_id,
            "input_manifest_id": value.input_manifest_id,
            "input_manifest_hash": value.input_manifest_hash,
            "accepted_entry_count": len(value.accepted_entry_refs),
            "superseded_entry_count": len(value.superseded_entry_ids),
            "deferred_candidate_count": len(value.deferred_candidate_ids),
            "audit_verification_id": value.audit_verification_ref.ref_id,
            "audit_verification_hash": value.audit_verification_ref.content_hash,
            "entry_refs_disclosed": False,
            "candidate_ids_disclosed": False,
            "production_state_mutation_authorized": False,
        }
