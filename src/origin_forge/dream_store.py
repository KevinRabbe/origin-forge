from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable, TypeVar
from uuid import uuid4

from .dream_models import (
    DreamBudget,
    DreamCandidate,
    DreamCandidateType,
    DreamInputManifest,
    DreamModelError,
    EvidenceClass,
    EvidenceRef,
    MemoryEntry,
    MemoryGeneration,
    MemoryKind,
    MemoryStatus,
)
from .dream_roles import (
    DreamAuditFinding,
    DreamAuditFindingCode,
    DreamAuditReport,
    DreamAuditStatus,
)
from .ids import IdKind, validate_id
from .runtime import OriginForgeRuntime


_AUDIT_ID_RE = re.compile(r"^DREAM-AUDIT-[0-9a-f]{64}$")
_T = TypeVar("_T")


class DreamStoreError(RuntimeError):
    pass


def _require_exact_keys(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DreamStoreError(f"invalid {label} fields")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DreamStoreError(f"{label} must be a string")
    return value


def _require_optional_string(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DreamStoreError(f"{label} must be a string or null")
    return value


def _require_string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DreamStoreError(f"{label} must be an array of strings")
    return tuple(value)


def _evidence_ref(value: object) -> EvidenceRef:
    raw = _require_exact_keys(
        value,
        {"ref_id", "content_hash", "evidence_class", "revision"},
        "Dream evidence ref",
    )
    revision = raw["revision"]
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool)):
        raise DreamStoreError("Dream evidence revision must be an integer or null")
    try:
        return EvidenceRef(
            ref_id=_require_string(raw["ref_id"], "Dream evidence ref_id"),
            content_hash=_require_string(raw["content_hash"], "Dream evidence content_hash"),
            evidence_class=EvidenceClass(
                _require_string(raw["evidence_class"], "Dream evidence class")
            ),
            revision=revision,
        )
    except (DreamModelError, ValueError) as exc:
        raise DreamStoreError("Dream evidence ref validation failed") from exc


def _evidence_refs(value: object, label: str) -> tuple[EvidenceRef, ...]:
    if not isinstance(value, list):
        raise DreamStoreError(f"{label} must be an array")
    return tuple(_evidence_ref(item) for item in value)


def _budget(value: object) -> DreamBudget:
    raw = _require_exact_keys(
        value,
        {
            "max_runs",
            "max_total_evidence_bytes",
            "max_candidates",
            "max_model_calls",
            "max_analysis_tokens",
            "max_elapsed_seconds",
            "max_retries",
        },
        "Dream budget",
    )
    if any(not isinstance(item, int) or isinstance(item, bool) for item in raw.values()):
        raise DreamStoreError("Dream budget fields must be integers")
    try:
        return DreamBudget(**raw)
    except DreamModelError as exc:
        raise DreamStoreError("Dream budget validation failed") from exc


def _manifest(payload: object) -> DreamInputManifest:
    raw = _require_exact_keys(
        payload,
        {
            "manifest_id",
            "parent_memory_generation_id",
            "run_refs",
            "task_refs",
            "decision_refs",
            "verification_refs",
            "memory_refs",
            "window_start",
            "window_end",
            "budget",
            "content_hash",
        },
        "Dream input manifest",
    )
    try:
        value = DreamInputManifest(
            manifest_id=_require_string(raw["manifest_id"], "manifest_id"),
            parent_memory_generation_id=_require_optional_string(
                raw["parent_memory_generation_id"], "parent_memory_generation_id"
            ),
            run_refs=_evidence_refs(raw["run_refs"], "run_refs"),
            task_refs=_evidence_refs(raw["task_refs"], "task_refs"),
            decision_refs=_evidence_refs(raw["decision_refs"], "decision_refs"),
            verification_refs=_evidence_refs(raw["verification_refs"], "verification_refs"),
            memory_refs=_evidence_refs(raw["memory_refs"], "memory_refs"),
            window_start=_require_optional_string(raw["window_start"], "window_start"),
            window_end=_require_optional_string(raw["window_end"], "window_end"),
            budget=_budget(raw["budget"]),
        )
    except (DreamModelError, DreamStoreError) as exc:
        raise DreamStoreError("Dream input manifest validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise DreamStoreError("Dream input manifest content hash mismatch")
    return value


def _candidate(payload: object) -> DreamCandidate:
    raw = _require_exact_keys(
        payload,
        {
            "candidate_id",
            "candidate_type",
            "summary",
            "proposed_action",
            "evidence_refs",
            "contradiction_refs",
            "target_memory_generation_id",
            "required_gate",
            "content_hash",
        },
        "Dream candidate",
    )
    try:
        value = DreamCandidate(
            candidate_id=_require_string(raw["candidate_id"], "candidate_id"),
            candidate_type=DreamCandidateType(
                _require_string(raw["candidate_type"], "candidate_type")
            ),
            summary=_require_string(raw["summary"], "candidate summary"),
            proposed_action=_require_string(raw["proposed_action"], "candidate proposed_action"),
            evidence_refs=_evidence_refs(raw["evidence_refs"], "candidate evidence_refs"),
            contradiction_refs=_evidence_refs(
                raw["contradiction_refs"], "candidate contradiction_refs"
            ),
            target_memory_generation_id=_require_optional_string(
                raw["target_memory_generation_id"], "target_memory_generation_id"
            ),
        )
    except (DreamModelError, DreamStoreError, ValueError) as exc:
        raise DreamStoreError("Dream candidate validation failed") from exc
    if raw["required_gate"] != value.required_gate.value:
        raise DreamStoreError("Dream candidate downstream gate mismatch")
    if raw["content_hash"] != value.content_hash:
        raise DreamStoreError("Dream candidate content hash mismatch")
    return value


def _memory_entry(payload: object) -> MemoryEntry:
    raw = _require_exact_keys(
        payload,
        {
            "entry_id",
            "kind",
            "claim",
            "evidence_refs",
            "supersedes",
            "valid_from",
            "status",
            "content_hash",
        },
        "memory entry",
    )
    if raw["status"] != MemoryStatus.VERIFIED_DERIVED.value:
        raise DreamStoreError("memory entry status is invalid")
    try:
        value = MemoryEntry(
            entry_id=_require_string(raw["entry_id"], "entry_id"),
            kind=MemoryKind(_require_string(raw["kind"], "memory kind")),
            claim=_require_string(raw["claim"], "memory claim"),
            evidence_refs=_evidence_refs(raw["evidence_refs"], "memory evidence_refs"),
            supersedes=_require_string_list(raw["supersedes"], "memory supersedes"),
            valid_from=_require_optional_string(raw["valid_from"], "memory valid_from"),
        )
    except (DreamModelError, DreamStoreError, ValueError) as exc:
        raise DreamStoreError("memory entry validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise DreamStoreError("memory entry content hash mismatch")
    return value


def _audit_report(payload: object) -> DreamAuditReport:
    raw = _require_exact_keys(
        payload,
        {
            "candidate_id",
            "candidate_hash",
            "manifest_id",
            "manifest_hash",
            "evidence_snapshot_hash",
            "status",
            "required_gate",
            "semantic_review_required",
            "findings",
            "content_hash",
        },
        "Dream audit report",
    )
    findings_raw = raw["findings"]
    if not isinstance(findings_raw, list):
        raise DreamStoreError("Dream audit findings must be an array")
    findings: list[DreamAuditFinding] = []
    for item in findings_raw:
        finding_raw = _require_exact_keys(
            item,
            {"code", "message", "evidence_ref_id"},
            "Dream audit finding",
        )
        try:
            findings.append(
                DreamAuditFinding(
                    code=DreamAuditFindingCode(
                        _require_string(finding_raw["code"], "audit finding code")
                    ),
                    message=_require_string(finding_raw["message"], "audit finding message"),
                    evidence_ref_id=_require_optional_string(
                        finding_raw["evidence_ref_id"], "audit finding evidence_ref_id"
                    ),
                )
            )
        except (DreamRoleError, DreamStoreError, ValueError) as exc:
            raise DreamStoreError("Dream audit finding validation failed") from exc
    semantic = raw["semantic_review_required"]
    if not isinstance(semantic, bool):
        raise DreamStoreError("semantic_review_required must be boolean")
    try:
        value = DreamAuditReport(
            candidate_id=_require_string(raw["candidate_id"], "audit candidate_id"),
            candidate_hash=_require_string(raw["candidate_hash"], "audit candidate_hash"),
            manifest_id=_require_string(raw["manifest_id"], "audit manifest_id"),
            manifest_hash=_require_string(raw["manifest_hash"], "audit manifest_hash"),
            evidence_snapshot_hash=_require_string(
                raw["evidence_snapshot_hash"], "audit evidence_snapshot_hash"
            ),
            status=DreamAuditStatus(_require_string(raw["status"], "audit status")),
            required_gate=_require_string(raw["required_gate"], "audit required_gate"),
            semantic_review_required=semantic,
            findings=tuple(findings),
        )
    except (DreamRoleError, DreamStoreError, ValueError) as exc:
        raise DreamStoreError("Dream audit report validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise DreamStoreError("Dream audit report content hash mismatch")
    return value


def _generation(payload: object) -> MemoryGeneration:
    raw = _require_exact_keys(
        payload,
        {
            "generation_id",
            "parent_generation_id",
            "dream_run_id",
            "input_manifest_id",
            "input_manifest_hash",
            "accepted_entry_refs",
            "superseded_entry_ids",
            "deferred_candidate_ids",
            "audit_verification_ref",
            "content_hash",
        },
        "memory generation",
    )
    try:
        value = MemoryGeneration(
            generation_id=_require_string(raw["generation_id"], "generation_id"),
            parent_generation_id=_require_optional_string(
                raw["parent_generation_id"], "parent_generation_id"
            ),
            dream_run_id=_require_string(raw["dream_run_id"], "dream_run_id"),
            input_manifest_id=_require_string(raw["input_manifest_id"], "input_manifest_id"),
            input_manifest_hash=_require_string(
                raw["input_manifest_hash"], "input_manifest_hash"
            ),
            accepted_entry_refs=_evidence_refs(
                raw["accepted_entry_refs"], "accepted_entry_refs"
            ),
            superseded_entry_ids=_require_string_list(
                raw["superseded_entry_ids"], "superseded_entry_ids"
            ),
            deferred_candidate_ids=_require_string_list(
                raw["deferred_candidate_ids"], "deferred_candidate_ids"
            ),
            audit_verification_ref=_evidence_ref(raw["audit_verification_ref"]),
        )
    except (DreamModelError, DreamStoreError) as exc:
        raise DreamStoreError("memory generation validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise DreamStoreError("memory generation content hash mismatch")
    return value


# Import here to keep the error mapping above explicit without widening model APIs.
from .dream_roles import DreamRoleError  # noqa: E402


class DreamStore:
    """Protected immutable persistence for Dream proposals and derived memory.

    The store has no method that mutates canonical project records, Skills,
    routing/context policy, source code, or merge state.
    """

    FORMAT_VERSION = 1

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_manifests: int = 1024,
        max_candidates: int = 8192,
        max_audits: int = 16384,
        max_memory_entries: int = 4096,
        max_generations: int = 2048,
        max_manifest_bytes: int = 4 * 1024 * 1024,
        max_candidate_bytes: int = 256 * 1024,
        max_audit_bytes: int = 512 * 1024,
        max_memory_entry_bytes: int = 256 * 1024,
        max_generation_bytes: int = 512 * 1024,
    ):
        limits = (
            (max_manifests, "max_manifests"),
            (max_candidates, "max_candidates"),
            (max_audits, "max_audits"),
            (max_memory_entries, "max_memory_entries"),
            (max_generations, "max_generations"),
            (max_manifest_bytes, "max_manifest_bytes"),
            (max_candidate_bytes, "max_candidate_bytes"),
            (max_audit_bytes, "max_audit_bytes"),
            (max_memory_entry_bytes, "max_memory_entry_bytes"),
            (max_generation_bytes, "max_generation_bytes"),
        )
        for value, name in limits:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.runtime = runtime
        self.root = runtime.state_dir / "dream"
        self.manifests_dir = self.root / "manifests"
        self.candidates_dir = self.root / "candidates"
        self.audits_dir = self.root / "audits"
        self.memory_root = self.root / "memory"
        self.memory_entries_dir = self.memory_root / "entries"
        self.generations_dir = self.memory_root / "generations"
        self.max_manifests = max_manifests
        self.max_candidates = max_candidates
        self.max_audits = max_audits
        self.max_memory_entries = max_memory_entries
        self.max_generations = max_generations
        self.max_manifest_bytes = max_manifest_bytes
        self.max_candidate_bytes = max_candidate_bytes
        self.max_audit_bytes = max_audit_bytes
        self.max_memory_entry_bytes = max_memory_entry_bytes
        self.max_generation_bytes = max_generation_bytes

    @staticmethod
    def _canonical_bytes(kind: str, payload: dict[str, object]) -> bytes:
        return (
            json.dumps(
                {
                    "format_version": DreamStore.FORMAT_VERSION,
                    "kind": kind,
                    "payload": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise DreamStoreError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise DreamStoreError(f"{label} exceeds byte limit ({len(data)} > {maximum})")
        return data

    def _validate_dir(self, path: Path, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if path.is_symlink():
            raise DreamStoreError(f"Dream store path may not be a symlink: {path.name}")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        try:
            resolved = path.resolve()
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DreamStoreError("Dream store path escapes protected project state") from exc
        if path.exists() and not path.is_dir():
            raise DreamStoreError(f"Dream store path must be a directory: {path}")
        return resolved

    def ensure(self) -> None:
        for path in (
            self.root,
            self.manifests_dir,
            self.candidates_dir,
            self.audits_dir,
            self.memory_root,
            self.memory_entries_dir,
            self.generations_dir,
        ):
            self._validate_dir(path, create=True)

    def _list_ids(
        self,
        directory: Path,
        *,
        maximum: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise DreamStoreError(f"{label} registry contains unsupported entry: {path.name}")
            object_id = path.stem
            if not validator(object_id):
                raise DreamStoreError(f"{label} registry contains invalid ID: {object_id}")
            values.append(object_id)
            if len(values) > maximum:
                raise DreamStoreError(
                    f"{label} catalog exceeds limit ({len(values)} > {maximum})"
                )
        return tuple(sorted(values))

    def _put(
        self,
        directory: Path,
        *,
        object_id: str,
        kind: str,
        payload: dict[str, object],
        maximum_count: int,
        maximum_bytes: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> Path:
        self.ensure()
        if not validator(object_id):
            raise DreamStoreError(f"invalid {label} ID: {object_id}")
        data = self._canonical_bytes(kind, payload)
        if len(data) > maximum_bytes:
            raise DreamStoreError(
                f"{label} exceeds byte limit ({len(data)} > {maximum_bytes})"
            )
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            current = self._bounded_read(path, maximum_bytes, label)
            if current != data:
                raise DreamStoreError(f"{label} ID is immutable and already exists: {object_id}")
            return path
        if len(
            self._list_ids(
                directory,
                maximum=maximum_count,
                validator=validator,
                label=label,
            )
        ) >= maximum_count:
            raise DreamStoreError(
                f"{label} catalog exceeds limit ({maximum_count + 1} > {maximum_count})"
            )
        self._atomic_write(path, data)
        return path

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
        label: str,
    ) -> _T:
        self.ensure()
        if not validator(object_id):
            raise DreamStoreError(f"invalid {label} ID: {object_id}")
        path = directory / f"{object_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(object_id)
        data = self._bounded_read(path, maximum_bytes, label)
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DreamStoreError(f"invalid {label} JSON: {object_id}") from exc
        envelope = _require_exact_keys(
            raw,
            {"format_version", "kind", "payload"},
            f"{label} envelope",
        )
        if envelope["format_version"] != self.FORMAT_VERSION or envelope["kind"] != kind:
            raise DreamStoreError(f"invalid {label} envelope metadata: {object_id}")
        value = parser(envelope["payload"])
        if loaded_id(value) != object_id:
            raise DreamStoreError(f"{label} filename/ID mismatch: {object_id}")
        return value

    @staticmethod
    def audit_report_id(report: DreamAuditReport) -> str:
        if not isinstance(report, DreamAuditReport):
            raise TypeError("report must be a DreamAuditReport")
        return "DREAM-AUDIT-" + report.content_hash.split(":", 1)[1]

    def list_manifest_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.manifests_dir,
            maximum=self.max_manifests,
            validator=lambda value: validate_id(value, IdKind.DREAM_MANIFEST),
            label="Dream manifest",
        )

    def put_manifest(self, manifest: DreamInputManifest) -> Path:
        if not isinstance(manifest, DreamInputManifest):
            raise TypeError("manifest must be a DreamInputManifest")
        return self._put(
            self.manifests_dir,
            object_id=manifest.manifest_id,
            kind="DREAM_INPUT_MANIFEST",
            payload=manifest.to_dict(),
            maximum_count=self.max_manifests,
            maximum_bytes=self.max_manifest_bytes,
            validator=lambda value: validate_id(value, IdKind.DREAM_MANIFEST),
            label="Dream manifest",
        )

    def load_manifest(self, manifest_id: str) -> DreamInputManifest:
        return self._load(
            self.manifests_dir,
            object_id=manifest_id,
            kind="DREAM_INPUT_MANIFEST",
            maximum_bytes=self.max_manifest_bytes,
            validator=lambda value: validate_id(value, IdKind.DREAM_MANIFEST),
            parser=_manifest,
            loaded_id=lambda value: value.manifest_id,
            label="Dream manifest",
        )

    def list_candidate_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.candidates_dir,
            maximum=self.max_candidates,
            validator=lambda value: validate_id(value, IdKind.DREAM_CANDIDATE),
            label="Dream candidate",
        )

    def put_candidate(self, candidate: DreamCandidate) -> Path:
        if not isinstance(candidate, DreamCandidate):
            raise TypeError("candidate must be a DreamCandidate")
        return self._put(
            self.candidates_dir,
            object_id=candidate.candidate_id,
            kind="DREAM_CANDIDATE",
            payload=candidate.to_dict(),
            maximum_count=self.max_candidates,
            maximum_bytes=self.max_candidate_bytes,
            validator=lambda value: validate_id(value, IdKind.DREAM_CANDIDATE),
            label="Dream candidate",
        )

    def load_candidate(self, candidate_id: str) -> DreamCandidate:
        return self._load(
            self.candidates_dir,
            object_id=candidate_id,
            kind="DREAM_CANDIDATE",
            maximum_bytes=self.max_candidate_bytes,
            validator=lambda value: validate_id(value, IdKind.DREAM_CANDIDATE),
            parser=_candidate,
            loaded_id=lambda value: value.candidate_id,
            label="Dream candidate",
        )

    def list_audit_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.audits_dir,
            maximum=self.max_audits,
            validator=lambda value: bool(_AUDIT_ID_RE.fullmatch(value)),
            label="Dream audit",
        )

    def put_audit(self, report: DreamAuditReport) -> Path:
        report_id = self.audit_report_id(report)
        return self._put(
            self.audits_dir,
            object_id=report_id,
            kind="DREAM_AUDIT_REPORT",
            payload=report.to_dict(),
            maximum_count=self.max_audits,
            maximum_bytes=self.max_audit_bytes,
            validator=lambda value: bool(_AUDIT_ID_RE.fullmatch(value)),
            label="Dream audit",
        )

    def load_audit(self, report_id: str) -> DreamAuditReport:
        return self._load(
            self.audits_dir,
            object_id=report_id,
            kind="DREAM_AUDIT_REPORT",
            maximum_bytes=self.max_audit_bytes,
            validator=lambda value: bool(_AUDIT_ID_RE.fullmatch(value)),
            parser=_audit_report,
            loaded_id=lambda value: self.audit_report_id(value),
            label="Dream audit",
        )

    def list_memory_entry_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.memory_entries_dir,
            maximum=self.max_memory_entries,
            validator=lambda value: validate_id(value, IdKind.MEMORY_ENTRY),
            label="memory entry",
        )

    def put_memory_entry(self, entry: MemoryEntry) -> Path:
        if not isinstance(entry, MemoryEntry):
            raise TypeError("entry must be a MemoryEntry")
        return self._put(
            self.memory_entries_dir,
            object_id=entry.entry_id,
            kind="MEMORY_ENTRY",
            payload=entry.to_dict(),
            maximum_count=self.max_memory_entries,
            maximum_bytes=self.max_memory_entry_bytes,
            validator=lambda value: validate_id(value, IdKind.MEMORY_ENTRY),
            label="memory entry",
        )

    def load_memory_entry(self, entry_id: str) -> MemoryEntry:
        return self._load(
            self.memory_entries_dir,
            object_id=entry_id,
            kind="MEMORY_ENTRY",
            maximum_bytes=self.max_memory_entry_bytes,
            validator=lambda value: validate_id(value, IdKind.MEMORY_ENTRY),
            parser=_memory_entry,
            loaded_id=lambda value: value.entry_id,
            label="memory entry",
        )

    def list_generation_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.generations_dir,
            maximum=self.max_generations,
            validator=lambda value: validate_id(value, IdKind.MEMORY_GENERATION),
            label="memory generation",
        )

    def put_generation(self, generation: MemoryGeneration) -> Path:
        if not isinstance(generation, MemoryGeneration):
            raise TypeError("generation must be a MemoryGeneration")
        return self._put(
            self.generations_dir,
            object_id=generation.generation_id,
            kind="MEMORY_GENERATION",
            payload=generation.to_dict(),
            maximum_count=self.max_generations,
            maximum_bytes=self.max_generation_bytes,
            validator=lambda value: validate_id(value, IdKind.MEMORY_GENERATION),
            label="memory generation",
        )

    def load_generation(self, generation_id: str) -> MemoryGeneration:
        return self._load(
            self.generations_dir,
            object_id=generation_id,
            kind="MEMORY_GENERATION",
            maximum_bytes=self.max_generation_bytes,
            validator=lambda value: validate_id(value, IdKind.MEMORY_GENERATION),
            parser=_generation,
            loaded_id=lambda value: value.generation_id,
            label="memory generation",
        )
