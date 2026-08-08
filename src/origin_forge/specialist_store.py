from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4

from .ids import IdKind, validate_id
from .reviewer_audit import (
    ReviewerAuditFinding,
    ReviewerAuditFindingCode,
    ReviewerAuditReport,
    ReviewerAuditStatus,
)
from .runtime import OriginForgeRuntime
from .specialist_models import (
    ReviewerCategory,
    ReviewerFinding,
    ReviewerReport,
    ReviewerSeverity,
    SpecialistBudget,
    SpecialistContract,
    SpecialistEvidenceKind,
    SpecialistEvidenceRef,
    SpecialistModelError,
    SpecialistRole,
)


_SPECIALIST_AUDIT_RE = re.compile(r"^SPAUD-[0-9a-f]{64}$")
_T = TypeVar("_T")


class SpecialistStoreError(RuntimeError):
    pass


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SpecialistStoreError(f"invalid {label} fields")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise SpecialistStoreError(f"{label} must be a string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise SpecialistStoreError(f"{label} must be a string or null")
    return value


def _evidence_ref(value: object) -> SpecialistEvidenceRef:
    raw = _exact(value, {"ref_id", "content_hash", "evidence_kind"}, "specialist evidence ref")
    try:
        return SpecialistEvidenceRef(
            ref_id=_string(raw["ref_id"], "specialist evidence ref_id"),
            content_hash=_string(raw["content_hash"], "specialist evidence content_hash"),
            evidence_kind=SpecialistEvidenceKind(
                _string(raw["evidence_kind"], "specialist evidence kind")
            ),
        )
    except (SpecialistModelError, ValueError) as exc:
        raise SpecialistStoreError("specialist evidence ref validation failed") from exc


def _budget(value: object) -> SpecialistBudget:
    raw = _exact(
        value,
        {
            "max_evidence_bytes",
            "max_report_bytes",
            "max_findings",
            "max_model_calls",
            "max_input_tokens",
            "max_output_tokens",
        },
        "specialist budget",
    )
    if any(not isinstance(item, int) or isinstance(item, bool) for item in raw.values()):
        raise SpecialistStoreError("specialist budget fields must be integers")
    try:
        return SpecialistBudget(**raw)
    except SpecialistModelError as exc:
        raise SpecialistStoreError("specialist budget validation failed") from exc


def _contract(payload: object) -> SpecialistContract:
    raw = _exact(
        payload,
        {
            "contract_id",
            "role",
            "parent_task_id",
            "objective",
            "evidence_refs",
            "acceptance_questions",
            "budget",
            "content_hash",
        },
        "specialist contract",
    )
    refs_raw = raw["evidence_refs"]
    questions_raw = raw["acceptance_questions"]
    if not isinstance(refs_raw, list) or not isinstance(questions_raw, list):
        raise SpecialistStoreError("specialist contract arrays are invalid")
    if any(not isinstance(item, str) for item in questions_raw):
        raise SpecialistStoreError("specialist acceptance questions must be strings")
    try:
        value = SpecialistContract(
            contract_id=_string(raw["contract_id"], "contract_id"),
            role=SpecialistRole(_string(raw["role"], "specialist role")),
            parent_task_id=_string(raw["parent_task_id"], "parent_task_id"),
            objective=_string(raw["objective"], "specialist objective"),
            evidence_refs=tuple(_evidence_ref(item) for item in refs_raw),
            acceptance_questions=tuple(questions_raw),
            budget=_budget(raw["budget"]),
        )
    except (SpecialistModelError, ValueError) as exc:
        raise SpecialistStoreError("specialist contract validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise SpecialistStoreError("specialist contract content hash mismatch")
    return value


def _reviewer_finding(payload: object) -> ReviewerFinding:
    raw = _exact(
        payload,
        {
            "finding_id",
            "severity",
            "category",
            "summary",
            "evidence_refs",
            "recommendation",
            "content_hash",
        },
        "Reviewer finding",
    )
    refs_raw = raw["evidence_refs"]
    if not isinstance(refs_raw, list):
        raise SpecialistStoreError("Reviewer finding evidence_refs must be an array")
    try:
        value = ReviewerFinding(
            finding_id=_string(raw["finding_id"], "finding_id"),
            severity=ReviewerSeverity(_string(raw["severity"], "Reviewer severity")),
            category=ReviewerCategory(_string(raw["category"], "Reviewer category")),
            summary=_string(raw["summary"], "Reviewer summary"),
            evidence_refs=tuple(_evidence_ref(item) for item in refs_raw),
            recommendation=_string(raw["recommendation"], "Reviewer recommendation"),
        )
    except (SpecialistModelError, ValueError) as exc:
        raise SpecialistStoreError("Reviewer finding validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise SpecialistStoreError("Reviewer finding content hash mismatch")
    return value


def _reviewer_report(payload: object) -> ReviewerReport:
    raw = _exact(
        payload,
        {
            "report_id",
            "contract_id",
            "contract_hash",
            "model_id",
            "model_hash",
            "findings",
            "overall_risk",
            "content_hash",
        },
        "Reviewer report",
    )
    findings_raw = raw["findings"]
    if not isinstance(findings_raw, list):
        raise SpecialistStoreError("Reviewer findings must be an array")
    try:
        value = ReviewerReport(
            report_id=_string(raw["report_id"], "report_id"),
            contract_id=_string(raw["contract_id"], "contract_id"),
            contract_hash=_string(raw["contract_hash"], "contract_hash"),
            model_id=_string(raw["model_id"], "model_id"),
            model_hash=_optional_string(raw["model_hash"], "model_hash"),
            findings=tuple(_reviewer_finding(item) for item in findings_raw),
        )
    except SpecialistModelError as exc:
        raise SpecialistStoreError("Reviewer report validation failed") from exc
    if raw["overall_risk"] != value.overall_risk.value:
        raise SpecialistStoreError("Reviewer report overall risk mismatch")
    if raw["content_hash"] != value.content_hash:
        raise SpecialistStoreError("Reviewer report content hash mismatch")
    return value


def _audit_finding(payload: object) -> ReviewerAuditFinding:
    raw = _exact(
        payload,
        {"code", "message", "finding_id", "evidence_ref_id"},
        "Reviewer audit finding",
    )
    try:
        return ReviewerAuditFinding(
            code=ReviewerAuditFindingCode(_string(raw["code"], "audit finding code")),
            message=_string(raw["message"], "audit finding message"),
            finding_id=_optional_string(raw["finding_id"], "audit finding_id"),
            evidence_ref_id=_optional_string(raw["evidence_ref_id"], "audit evidence_ref_id"),
        )
    except (ValueError, RuntimeError) as exc:
        raise SpecialistStoreError("Reviewer audit finding validation failed") from exc


def _reviewer_audit(payload: object) -> ReviewerAuditReport:
    raw = _exact(
        payload,
        {
            "report_id",
            "report_hash",
            "contract_id",
            "contract_hash",
            "evidence_package_hash",
            "status",
            "findings",
            "semantic_findings_verified",
            "content_hash",
        },
        "Reviewer audit",
    )
    findings_raw = raw["findings"]
    if not isinstance(findings_raw, list):
        raise SpecialistStoreError("Reviewer audit findings must be an array")
    if raw["semantic_findings_verified"] is not False:
        raise SpecialistStoreError("Reviewer audit may not claim semantic verification")
    try:
        value = ReviewerAuditReport(
            report_id=_string(raw["report_id"], "audit report_id"),
            report_hash=_string(raw["report_hash"], "audit report_hash"),
            contract_id=_string(raw["contract_id"], "audit contract_id"),
            contract_hash=_string(raw["contract_hash"], "audit contract_hash"),
            evidence_package_hash=_string(
                raw["evidence_package_hash"], "audit evidence_package_hash"
            ),
            status=ReviewerAuditStatus(_string(raw["status"], "audit status")),
            findings=tuple(_audit_finding(item) for item in findings_raw),
            semantic_findings_verified=False,
        )
    except (ValueError, RuntimeError) as exc:
        raise SpecialistStoreError("Reviewer audit validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise SpecialistStoreError("Reviewer audit content hash mismatch")
    return value


class SpecialistStore:
    FORMAT_VERSION = 1

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_contracts: int = 4096,
        max_reports: int = 8192,
        max_audits: int = 8192,
        max_contract_bytes: int = 512 * 1024,
        max_report_bytes: int = 512 * 1024,
        max_audit_bytes: int = 512 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        for name, value in (
            ("max_contracts", max_contracts),
            ("max_reports", max_reports),
            ("max_audits", max_audits),
            ("max_contract_bytes", max_contract_bytes),
            ("max_report_bytes", max_report_bytes),
            ("max_audit_bytes", max_audit_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.runtime = runtime
        self.root = runtime.state_dir / "specialists"
        self.contracts_dir = self.root / "contracts"
        self.reports_dir = self.root / "reports"
        self.audits_dir = self.root / "audits"
        self.max_contracts = max_contracts
        self.max_reports = max_reports
        self.max_audits = max_audits
        self.max_contract_bytes = max_contract_bytes
        self.max_report_bytes = max_report_bytes
        self.max_audit_bytes = max_audit_bytes

    @staticmethod
    def _canonical_bytes(kind: str, payload: dict[str, object]) -> bytes:
        return (
            json.dumps(
                {
                    "format_version": SpecialistStore.FORMAT_VERSION,
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
    def _atomic_publish(path: Path, data: bytes) -> bool:
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                return False
            except OSError as exc:
                raise SpecialistStoreError(
                    f"unable to atomically publish specialist object: {path.name}"
                ) from exc
            return True
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise SpecialistStoreError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise SpecialistStoreError(f"{label} exceeds byte limit ({len(data)} > {maximum})")
        return data

    def _validate_dir(self, path: Path, *, create: bool) -> None:
        state = self.runtime.state_dir.resolve()
        if path.is_symlink():
            raise SpecialistStoreError(f"specialist store path may not be a symlink: {path.name}")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        try:
            path.resolve().relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SpecialistStoreError("specialist store path escapes protected project state") from exc
        if path.exists() and not path.is_dir():
            raise SpecialistStoreError(f"specialist store path must be a directory: {path}")

    def ensure(self) -> None:
        for path in (self.root, self.contracts_dir, self.reports_dir, self.audits_dir):
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
                raise SpecialistStoreError(
                    f"{label} registry contains unsupported entry: {path.name}"
                )
            object_id = path.stem
            if not validator(object_id):
                raise SpecialistStoreError(f"{label} registry contains invalid ID: {object_id}")
            values.append(object_id)
            if len(values) > maximum:
                raise SpecialistStoreError(
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
            raise SpecialistStoreError(f"invalid {label} ID: {object_id}")
        data = self._canonical_bytes(kind, payload)
        if len(data) > maximum_bytes:
            raise SpecialistStoreError(
                f"{label} exceeds byte limit ({len(data)} > {maximum_bytes})"
            )
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            current = self._bounded_read(path, maximum_bytes, label)
            if current != data:
                raise SpecialistStoreError(f"{label} ID is immutable and already exists: {object_id}")
            return path
        if len(
            self._list_ids(
                directory,
                maximum=maximum_count,
                validator=validator,
                label=label,
            )
        ) >= maximum_count:
            raise SpecialistStoreError(
                f"{label} catalog exceeds limit ({maximum_count + 1} > {maximum_count})"
            )
        if not self._atomic_publish(path, data):
            current = self._bounded_read(path, maximum_bytes, label)
            if current != data:
                raise SpecialistStoreError(f"{label} ID is immutable and already exists: {object_id}")
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
            raise SpecialistStoreError(f"invalid {label} ID: {object_id}")
        path = directory / f"{object_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(object_id)
        data = self._bounded_read(path, maximum_bytes, label)
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistStoreError(f"invalid {label} JSON: {object_id}") from exc
        envelope = _exact(raw, {"format_version", "kind", "payload"}, f"{label} envelope")
        if envelope["format_version"] != self.FORMAT_VERSION or envelope["kind"] != kind:
            raise SpecialistStoreError(f"invalid {label} envelope metadata: {object_id}")
        value = parser(envelope["payload"])
        if loaded_id(value) != object_id:
            raise SpecialistStoreError(f"{label} filename/ID mismatch: {object_id}")
        return value

    @staticmethod
    def audit_id(audit: ReviewerAuditReport) -> str:
        if not isinstance(audit, ReviewerAuditReport):
            raise TypeError("audit must be a ReviewerAuditReport")
        return "SPAUD-" + audit.content_hash.split(":", 1)[1]

    def list_contract_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.contracts_dir,
            maximum=self.max_contracts,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_CONTRACT),
            label="specialist contract",
        )

    def put_contract(self, contract: SpecialistContract) -> Path:
        if not isinstance(contract, SpecialistContract):
            raise TypeError("contract must be a SpecialistContract")
        return self._put(
            self.contracts_dir,
            object_id=contract.contract_id,
            kind="SPECIALIST_CONTRACT",
            payload=contract.to_dict(),
            maximum_count=self.max_contracts,
            maximum_bytes=self.max_contract_bytes,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_CONTRACT),
            label="specialist contract",
        )

    def load_contract(self, contract_id: str) -> SpecialistContract:
        return self._load(
            self.contracts_dir,
            object_id=contract_id,
            kind="SPECIALIST_CONTRACT",
            maximum_bytes=self.max_contract_bytes,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_CONTRACT),
            parser=_contract,
            loaded_id=lambda value: value.contract_id,
            label="specialist contract",
        )

    def list_report_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.reports_dir,
            maximum=self.max_reports,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_REPORT),
            label="Reviewer report",
        )

    def list_audit_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.audits_dir,
            maximum=self.max_audits,
            validator=lambda value: bool(_SPECIALIST_AUDIT_RE.fullmatch(value)),
            label="Reviewer audit",
        )

    def put_review(
        self,
        report: ReviewerReport,
        audit: ReviewerAuditReport,
    ) -> tuple[Path, Path]:
        if not isinstance(report, ReviewerReport):
            raise TypeError("report must be a ReviewerReport")
        if not isinstance(audit, ReviewerAuditReport):
            raise TypeError("audit must be a ReviewerAuditReport")
        if audit.status != ReviewerAuditStatus.STRUCTURALLY_VALID:
            raise SpecialistStoreError("rejected Reviewer report cannot enter trusted registry")
        if audit.semantic_findings_verified:
            raise SpecialistStoreError("Reviewer structural audit cannot claim semantic verification")
        if audit.report_id != report.report_id or audit.report_hash != report.content_hash:
            raise SpecialistStoreError("Reviewer audit does not bind exact report")
        if audit.contract_id != report.contract_id or audit.contract_hash != report.contract_hash:
            raise SpecialistStoreError("Reviewer audit does not bind exact contract")
        contract = self.load_contract(report.contract_id)
        if contract.content_hash != report.contract_hash:
            raise SpecialistStoreError("stored specialist contract hash does not match Reviewer report")

        report_path = self._put(
            self.reports_dir,
            object_id=report.report_id,
            kind="REVIEWER_REPORT",
            payload=report.to_dict(),
            maximum_count=self.max_reports,
            maximum_bytes=self.max_report_bytes,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_REPORT),
            label="Reviewer report",
        )
        audit_id = self.audit_id(audit)
        audit_path = self._put(
            self.audits_dir,
            object_id=audit_id,
            kind="REVIEWER_AUDIT",
            payload=audit.to_dict(),
            maximum_count=self.max_audits,
            maximum_bytes=self.max_audit_bytes,
            validator=lambda value: bool(_SPECIALIST_AUDIT_RE.fullmatch(value)),
            label="Reviewer audit",
        )
        return report_path, audit_path

    def load_report(self, report_id: str) -> ReviewerReport:
        return self._load(
            self.reports_dir,
            object_id=report_id,
            kind="REVIEWER_REPORT",
            maximum_bytes=self.max_report_bytes,
            validator=lambda value: validate_id(value, IdKind.SPECIALIST_REPORT),
            parser=_reviewer_report,
            loaded_id=lambda value: value.report_id,
            label="Reviewer report",
        )

    def load_audit(self, audit_id: str) -> ReviewerAuditReport:
        return self._load(
            self.audits_dir,
            object_id=audit_id,
            kind="REVIEWER_AUDIT",
            maximum_bytes=self.max_audit_bytes,
            validator=lambda value: bool(_SPECIALIST_AUDIT_RE.fullmatch(value)),
            parser=_reviewer_audit,
            loaded_id=lambda value: self.audit_id(value),
            label="Reviewer audit",
        )
