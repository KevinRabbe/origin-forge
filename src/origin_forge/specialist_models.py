from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_TEXT = 8192
_MAX_QUESTIONS = 64
_MAX_EVIDENCE_REFS = 512
_MAX_FINDINGS = 128


class SpecialistModelError(ValueError):
    pass


class SpecialistRole(StrEnum):
    REVIEWER = "REVIEWER"
    RESEARCHER = "RESEARCHER"
    TEST_PLANNER = "TEST_PLANNER"
    VISUAL_CRITIC = "VISUAL_CRITIC"


class SpecialistEvidenceKind(StrEnum):
    TASK = "TASK"
    RUN = "RUN"
    ARTIFACT = "ARTIFACT"
    VERIFICATION = "VERIFICATION"
    WORKSPACE = "WORKSPACE"
    DECISION = "DECISION"


class ReviewerSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewerCategory(StrEnum):
    REQUIREMENT_GAP = "REQUIREMENT_GAP"
    REGRESSION_RISK = "REGRESSION_RISK"
    TEST_GAP = "TEST_GAP"
    COMPATIBILITY = "COMPATIBILITY"
    SECURITY = "SECURITY"
    MAINTAINABILITY = "MAINTAINABILITY"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    OTHER = "OTHER"


_EVIDENCE_ID_KIND = {
    SpecialistEvidenceKind.TASK: IdKind.TASK,
    SpecialistEvidenceKind.RUN: IdKind.RUN,
    SpecialistEvidenceKind.ARTIFACT: IdKind.ARTIFACT,
    SpecialistEvidenceKind.VERIFICATION: IdKind.VERIFICATION,
    SpecialistEvidenceKind.WORKSPACE: IdKind.WORKSPACE,
    SpecialistEvidenceKind.DECISION: IdKind.DECISION,
}

_SEVERITY_ORDER = {
    ReviewerSeverity.INFO: 0,
    ReviewerSeverity.LOW: 1,
    ReviewerSeverity.MEDIUM: 2,
    ReviewerSeverity.HIGH: 3,
    ReviewerSeverity.CRITICAL: 4,
}


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpecialistModelError("specialist value must be finite JSON data") from exc


def _content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_text(value: object, label: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise SpecialistModelError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SpecialistModelError(f"{label} must be non-empty")
    if len(normalized) > maximum:
        raise SpecialistModelError(f"{label} exceeds character limit")
    if "\x00" in normalized:
        raise SpecialistModelError(f"{label} contains NUL")
    return normalized


def _sorted_strings(values: Iterable[str], *, label: str, maximum: int) -> tuple[str, ...]:
    result = tuple(_require_text(value, label) for value in values)
    if len(result) > maximum:
        raise SpecialistModelError(f"{label} exceeds count limit")
    if len(result) != len(set(result)):
        raise SpecialistModelError(f"{label} contains duplicates")
    return tuple(sorted(result))


@dataclass(frozen=True)
class SpecialistEvidenceRef:
    ref_id: str
    content_hash: str
    evidence_kind: SpecialistEvidenceKind

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_kind, SpecialistEvidenceKind):
            raise SpecialistModelError("evidence_kind must be a SpecialistEvidenceKind")
        if not isinstance(self.ref_id, str) or not validate_id(
            self.ref_id, _EVIDENCE_ID_KIND[self.evidence_kind]
        ):
            raise SpecialistModelError(
                f"specialist evidence ID does not match {self.evidence_kind.value}"
            )
        if not isinstance(self.content_hash, str) or not _SHA256_RE.fullmatch(self.content_hash):
            raise SpecialistModelError("specialist evidence content_hash must be sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "content_hash": self.content_hash,
            "evidence_kind": self.evidence_kind.value,
        }


@dataclass(frozen=True)
class SpecialistBudget:
    max_evidence_bytes: int = 1024 * 1024
    max_report_bytes: int = 256 * 1024
    max_findings: int = 64
    max_model_calls: int = 1
    max_input_tokens: int = 32768
    max_output_tokens: int = 8192

    def __post_init__(self) -> None:
        for name, value in (
            ("max_evidence_bytes", self.max_evidence_bytes),
            ("max_report_bytes", self.max_report_bytes),
            ("max_findings", self.max_findings),
            ("max_model_calls", self.max_model_calls),
            ("max_input_tokens", self.max_input_tokens),
            ("max_output_tokens", self.max_output_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SpecialistModelError(f"{name} must be a non-negative integer")
        if self.max_evidence_bytes == 0 or self.max_report_bytes == 0:
            raise SpecialistModelError("specialist byte budgets must be positive")
        if self.max_findings > _MAX_FINDINGS:
            raise SpecialistModelError("max_findings exceeds infrastructure limit")
        if self.max_model_calls > 1:
            raise SpecialistModelError("Phase-16 v0 permits at most one model call")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_evidence_bytes": self.max_evidence_bytes,
            "max_report_bytes": self.max_report_bytes,
            "max_findings": self.max_findings,
            "max_model_calls": self.max_model_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class SpecialistContract:
    contract_id: str
    role: SpecialistRole
    parent_task_id: str
    objective: str
    evidence_refs: tuple[SpecialistEvidenceRef, ...]
    acceptance_questions: tuple[str, ...]
    budget: SpecialistBudget

    def __post_init__(self) -> None:
        if not validate_id(self.contract_id, IdKind.SPECIALIST_CONTRACT):
            raise SpecialistModelError("contract_id must be an SPCON ID")
        if not isinstance(self.role, SpecialistRole):
            raise SpecialistModelError("role must be a SpecialistRole")
        if not validate_id(self.parent_task_id, IdKind.TASK):
            raise SpecialistModelError("parent_task_id must be a TASK ID")
        object.__setattr__(self, "objective", _require_text(self.objective, "specialist objective"))
        refs = tuple(self.evidence_refs)
        if any(not isinstance(item, SpecialistEvidenceRef) for item in refs):
            raise SpecialistModelError("evidence_refs must contain SpecialistEvidenceRef values")
        if len(refs) == 0:
            raise SpecialistModelError("specialist contract requires evidence_refs")
        if len(refs) > _MAX_EVIDENCE_REFS:
            raise SpecialistModelError("specialist evidence_refs exceeds count limit")
        ref_keys = [(item.evidence_kind.value, item.ref_id) for item in refs]
        if len(ref_keys) != len(set(ref_keys)):
            raise SpecialistModelError("specialist evidence_refs contains duplicate IDs")
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(sorted(refs, key=lambda item: (item.evidence_kind.value, item.ref_id))),
        )
        object.__setattr__(
            self,
            "acceptance_questions",
            _sorted_strings(
                self.acceptance_questions,
                label="acceptance question",
                maximum=_MAX_QUESTIONS,
            ),
        )
        if not isinstance(self.budget, SpecialistBudget):
            raise SpecialistModelError("budget must be a SpecialistBudget")

    @classmethod
    def create(
        cls,
        *,
        role: SpecialistRole,
        parent_task_id: str,
        objective: str,
        evidence_refs: Iterable[SpecialistEvidenceRef],
        acceptance_questions: Iterable[str] = (),
        budget: SpecialistBudget | None = None,
    ) -> "SpecialistContract":
        return cls(
            contract_id=new_id(IdKind.SPECIALIST_CONTRACT),
            role=role,
            parent_task_id=parent_task_id,
            objective=objective,
            evidence_refs=tuple(evidence_refs),
            acceptance_questions=tuple(acceptance_questions),
            budget=budget or SpecialistBudget(),
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "parent_task_id": self.parent_task_id,
            "objective": self.objective,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "acceptance_questions": list(self.acceptance_questions),
            "budget": self.budget.to_dict(),
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ReviewerFinding:
    finding_id: str
    severity: ReviewerSeverity
    category: ReviewerCategory
    summary: str
    evidence_refs: tuple[SpecialistEvidenceRef, ...]
    recommendation: str

    def __post_init__(self) -> None:
        if not validate_id(self.finding_id, IdKind.SPECIALIST_FINDING):
            raise SpecialistModelError("finding_id must be an SPFIND ID")
        if not isinstance(self.severity, ReviewerSeverity):
            raise SpecialistModelError("severity must be a ReviewerSeverity")
        if not isinstance(self.category, ReviewerCategory):
            raise SpecialistModelError("category must be a ReviewerCategory")
        object.__setattr__(self, "summary", _require_text(self.summary, "review finding summary"))
        object.__setattr__(
            self,
            "recommendation",
            _require_text(self.recommendation, "review finding recommendation"),
        )
        refs = tuple(self.evidence_refs)
        if any(not isinstance(item, SpecialistEvidenceRef) for item in refs):
            raise SpecialistModelError("finding evidence_refs must contain SpecialistEvidenceRef values")
        if not refs:
            raise SpecialistModelError("review finding requires evidence")
        keys = [(item.evidence_kind.value, item.ref_id) for item in refs]
        if len(keys) != len(set(keys)):
            raise SpecialistModelError("review finding evidence_refs contains duplicate IDs")
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(sorted(refs, key=lambda item: (item.evidence_kind.value, item.ref_id))),
        )

    @classmethod
    def create(
        cls,
        *,
        severity: ReviewerSeverity,
        category: ReviewerCategory,
        summary: str,
        evidence_refs: Iterable[SpecialistEvidenceRef],
        recommendation: str,
    ) -> "ReviewerFinding":
        return cls(
            finding_id=new_id(IdKind.SPECIALIST_FINDING),
            severity=severity,
            category=category,
            summary=summary,
            evidence_refs=tuple(evidence_refs),
            recommendation=recommendation,
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "summary": self.summary,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "recommendation": self.recommendation,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ReviewerReport:
    report_id: str
    contract_id: str
    contract_hash: str
    model_id: str
    model_hash: str | None
    findings: tuple[ReviewerFinding, ...]

    def __post_init__(self) -> None:
        if not validate_id(self.report_id, IdKind.SPECIALIST_REPORT):
            raise SpecialistModelError("report_id must be an SPREP ID")
        if not validate_id(self.contract_id, IdKind.SPECIALIST_CONTRACT):
            raise SpecialistModelError("contract_id must be an SPCON ID")
        if not isinstance(self.contract_hash, str) or not _SHA256_RE.fullmatch(self.contract_hash):
            raise SpecialistModelError("contract_hash must be sha256")
        object.__setattr__(self, "model_id", _require_text(self.model_id, "review model_id", maximum=256))
        if self.model_hash is not None and (
            not isinstance(self.model_hash, str) or not _SHA256_RE.fullmatch(self.model_hash)
        ):
            raise SpecialistModelError("model_hash must be sha256 or null")
        findings = tuple(self.findings)
        if len(findings) > _MAX_FINDINGS:
            raise SpecialistModelError("review findings exceeds infrastructure limit")
        if any(not isinstance(item, ReviewerFinding) for item in findings):
            raise SpecialistModelError("findings must contain ReviewerFinding values")
        ids = [item.finding_id for item in findings]
        hashes = [item.content_hash for item in findings]
        if len(ids) != len(set(ids)):
            raise SpecialistModelError("review report contains duplicate finding IDs")
        if len(hashes) != len(set(hashes)):
            raise SpecialistModelError("review report contains duplicate semantic findings")
        object.__setattr__(self, "findings", tuple(sorted(findings, key=lambda item: item.finding_id)))

    @classmethod
    def create(
        cls,
        *,
        contract: SpecialistContract,
        model_id: str,
        model_hash: str | None,
        findings: Iterable[ReviewerFinding],
    ) -> "ReviewerReport":
        if contract.role != SpecialistRole.REVIEWER:
            raise SpecialistModelError("ReviewerReport requires a REVIEWER contract")
        return cls(
            report_id=new_id(IdKind.SPECIALIST_REPORT),
            contract_id=contract.contract_id,
            contract_hash=contract.content_hash,
            model_id=model_id,
            model_hash=model_hash,
            findings=tuple(findings),
        )

    @property
    def overall_risk(self) -> ReviewerSeverity:
        if not self.findings:
            return ReviewerSeverity.INFO
        return max(
            (item.severity for item in self.findings),
            key=lambda value: _SEVERITY_ORDER[value],
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "findings": [item.to_dict() for item in self.findings],
            "overall_risk": self.overall_risk.value,
        }

    @property
    def content_hash(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            **self._content_dict(),
            "content_hash": self.content_hash,
        }
