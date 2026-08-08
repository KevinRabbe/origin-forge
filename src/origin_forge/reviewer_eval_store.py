from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .reviewer_evaluation import (
    ExpectedReviewerIssue,
    ReviewerBenchmarkReport,
    ReviewerEvalCase,
    ReviewerEvaluationError,
)
from .specialist_evidence_store import SpecialistEvidenceStore, SpecialistEvidenceStoreError
from .specialist_models import ReviewerCategory, ReviewerSeverity
from .specialist_store import SpecialistStore, SpecialistStoreError


_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPORT_ID_RE = re.compile(r"^REVBENCH-[0-9a-f]{64}$")


class ReviewerEvalStoreError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class LoadedReviewerBenchmark:
    report_id: str
    payload: dict[str, object]

    @property
    def content_hash(self) -> str:
        return self.payload["content_hash"]  # type: ignore[return-value]


@dataclass(frozen=True)
class ReviewerEvalReplayStatus:
    report_id: str
    content_hash: str
    replayable: bool
    stale_case_ids: tuple[str, ...]
    stale_binding_case_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "content_hash": self.content_hash,
            "replayable": self.replayable,
            "stale_case_ids": list(self.stale_case_ids),
            "stale_binding_case_ids": list(self.stale_binding_case_ids),
        }


class ReviewerEvalStore:
    FORMAT_VERSION = 1

    def __init__(
        self,
        store: SpecialistStore,
        evidence_store: SpecialistEvidenceStore | None = None,
        *,
        max_cases: int = 2048,
        max_reports: int = 2048,
        max_case_bytes: int = 256 * 1024,
        max_report_bytes: int = 4 * 1024 * 1024,
    ):
        if not isinstance(store, SpecialistStore):
            raise TypeError("store must be a SpecialistStore")
        self.store = store
        self.runtime = store.runtime
        self.evidence_store = evidence_store or SpecialistEvidenceStore(store)
        for name, value in (
            ("max_cases", max_cases),
            ("max_reports", max_reports),
            ("max_case_bytes", max_case_bytes),
            ("max_report_bytes", max_report_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.root = store.root / "evaluation"
        self.cases_dir = self.root / "cases"
        self.reports_dir = self.root / "reports"
        self.max_cases = max_cases
        self.max_reports = max_reports
        self.max_case_bytes = max_case_bytes
        self.max_report_bytes = max_report_bytes

    def ensure(self) -> None:
        self.store.ensure()
        for path in (self.root, self.cases_dir, self.reports_dir):
            self.store._validate_dir(path, create=True)

    @staticmethod
    def report_id(report: ReviewerBenchmarkReport) -> str:
        if not isinstance(report, ReviewerBenchmarkReport):
            raise TypeError("report must be a ReviewerBenchmarkReport")
        return "REVBENCH-" + report.content_hash.split(":", 1)[1]

    def _list(self, directory: Path, *, maximum: int, validator, label: str) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ReviewerEvalStoreError(f"{label} registry contains unsupported entry: {path.name}")
            object_id = path.stem
            if not validator(object_id):
                raise ReviewerEvalStoreError(f"{label} registry contains invalid ID: {object_id}")
            values.append(object_id)
            if len(values) > maximum:
                raise ReviewerEvalStoreError(f"{label} catalog exceeds limit ({len(values)} > {maximum})")
        return tuple(sorted(values))

    def list_case_ids(self) -> tuple[str, ...]:
        return self._list(
            self.cases_dir,
            maximum=self.max_cases,
            validator=lambda value: bool(_CASE_ID_RE.fullmatch(value)),
            label="Reviewer eval case",
        )

    def list_report_ids(self) -> tuple[str, ...]:
        return self._list(
            self.reports_dir,
            maximum=self.max_reports,
            validator=lambda value: bool(_REPORT_ID_RE.fullmatch(value)),
            label="Reviewer benchmark report",
        )

    def _validate_case_bindings(self, case: ReviewerEvalCase) -> None:
        try:
            contract = self.store.load_contract(case.contract_id)
            package = self.evidence_store.load(case.contract_id)
        except (KeyError, SpecialistStoreError, SpecialistEvidenceStoreError) as exc:
            raise ReviewerEvalStoreError(
                f"Reviewer eval case bindings are unavailable: {case.case_id}"
            ) from exc
        if contract.content_hash != case.contract_hash:
            raise ReviewerEvalStoreError(
                f"Reviewer eval case contract hash is stale: {case.case_id}"
            )
        if package.content_hash != case.evidence_package_hash:
            raise ReviewerEvalStoreError(
                f"Reviewer eval case evidence package hash is stale: {case.case_id}"
            )

    def put_case(self, case: ReviewerEvalCase) -> Path:
        if not isinstance(case, ReviewerEvalCase):
            raise TypeError("case must be a ReviewerEvalCase")
        self.ensure()
        self._validate_case_bindings(case)
        payload = case.canonical_dict()
        envelope = {
            "format_version": self.FORMAT_VERSION,
            "kind": "REVIEWER_EVAL_CASE",
            "payload": payload,
            "content_hash": case.content_hash,
        }
        data = _canonical_bytes(envelope) + b"\n"
        if len(data) > self.max_case_bytes:
            raise ReviewerEvalStoreError(
                f"Reviewer eval case exceeds byte limit ({len(data)} > {self.max_case_bytes})"
            )
        path = self.cases_dir / f"{case.case_id}.json"
        if path.exists() or path.is_symlink():
            current = self.store._bounded_read(path, self.max_case_bytes, "Reviewer eval case")
            if current != data:
                raise ReviewerEvalStoreError(
                    f"Reviewer eval case ID is immutable and already exists: {case.case_id}"
                )
            return path
        if len(self.list_case_ids()) >= self.max_cases:
            raise ReviewerEvalStoreError(
                f"Reviewer eval case catalog exceeds limit ({self.max_cases + 1} > {self.max_cases})"
            )
        if not self.store._atomic_publish(path, data):
            current = self.store._bounded_read(path, self.max_case_bytes, "Reviewer eval case")
            if current != data:
                raise ReviewerEvalStoreError(
                    f"Reviewer eval case ID is immutable and already exists: {case.case_id}"
                )
        return path

    def load_case(self, case_id: str) -> ReviewerEvalCase:
        self.ensure()
        if not _CASE_ID_RE.fullmatch(case_id):
            raise ReviewerEvalStoreError(f"invalid Reviewer eval case ID: {case_id}")
        path = self.cases_dir / f"{case_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(case_id)
        data = self.store._bounded_read(path, self.max_case_bytes, "Reviewer eval case")
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewerEvalStoreError("invalid Reviewer eval case JSON") from exc
        if not isinstance(raw, dict) or set(raw) != {
            "format_version",
            "kind",
            "payload",
            "content_hash",
        }:
            raise ReviewerEvalStoreError("invalid Reviewer eval case envelope")
        if raw["format_version"] != self.FORMAT_VERSION or raw["kind"] != "REVIEWER_EVAL_CASE":
            raise ReviewerEvalStoreError("invalid Reviewer eval case metadata")
        payload = raw["payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "case_id",
            "contract_id",
            "contract_hash",
            "evidence_package_hash",
            "expected_issues",
            "max_false_positives",
            "minimum_precision",
        }:
            raise ReviewerEvalStoreError("invalid Reviewer eval case fields")
        issues_raw = payload["expected_issues"]
        if not isinstance(issues_raw, list):
            raise ReviewerEvalStoreError("Reviewer eval expected_issues must be an array")
        issues: list[ExpectedReviewerIssue] = []
        try:
            for item in issues_raw:
                if not isinstance(item, dict) or set(item) != {
                    "issue_id",
                    "category",
                    "minimum_severity",
                    "evidence_ref_ids",
                    "description",
                }:
                    raise ReviewerEvalStoreError("invalid Reviewer expected issue fields")
                refs = item["evidence_ref_ids"]
                if not isinstance(refs, list):
                    raise ReviewerEvalStoreError("expected issue evidence_ref_ids must be an array")
                issues.append(
                    ExpectedReviewerIssue(
                        issue_id=item["issue_id"],
                        category=ReviewerCategory(item["category"]),
                        minimum_severity=ReviewerSeverity(item["minimum_severity"]),
                        evidence_ref_ids=tuple(refs),
                        description=item["description"],
                    )
                )
            case = ReviewerEvalCase(
                case_id=payload["case_id"],
                contract_id=payload["contract_id"],
                contract_hash=payload["contract_hash"],
                evidence_package_hash=payload["evidence_package_hash"],
                expected_issues=tuple(issues),
                max_false_positives=payload["max_false_positives"],
                minimum_precision=payload["minimum_precision"],
            )
        except (ReviewerEvaluationError, ValueError, TypeError) as exc:
            raise ReviewerEvalStoreError("Reviewer eval case validation failed") from exc
        if case.case_id != case_id:
            raise ReviewerEvalStoreError("Reviewer eval case filename/ID mismatch")
        if raw["content_hash"] != case.content_hash:
            raise ReviewerEvalStoreError("Reviewer eval case content hash mismatch")
        return case

    def put_report(self, report: ReviewerBenchmarkReport) -> Path:
        if not isinstance(report, ReviewerBenchmarkReport):
            raise TypeError("report must be a ReviewerBenchmarkReport")
        self.ensure()
        for comparison in report.comparisons:
            case = self.load_case(comparison.case_id)
            if case.content_hash != comparison.case_hash:
                raise ReviewerEvalStoreError(
                    f"Reviewer benchmark case hash is stale: {comparison.case_id}"
                )
            self._validate_case_bindings(case)
        report_id = self.report_id(report)
        payload = report.to_dict()
        envelope = {
            "format_version": self.FORMAT_VERSION,
            "kind": "REVIEWER_BENCHMARK_REPORT",
            "payload": payload,
        }
        data = _canonical_bytes(envelope) + b"\n"
        if len(data) > self.max_report_bytes:
            raise ReviewerEvalStoreError(
                f"Reviewer benchmark report exceeds byte limit ({len(data)} > {self.max_report_bytes})"
            )
        path = self.reports_dir / f"{report_id}.json"
        if path.exists() or path.is_symlink():
            current = self.store._bounded_read(
                path, self.max_report_bytes, "Reviewer benchmark report"
            )
            if current != data:
                raise ReviewerEvalStoreError("content-addressed Reviewer benchmark report mismatch")
            return path
        if len(self.list_report_ids()) >= self.max_reports:
            raise ReviewerEvalStoreError(
                f"Reviewer benchmark catalog exceeds limit ({self.max_reports + 1} > {self.max_reports})"
            )
        if not self.store._atomic_publish(path, data):
            current = self.store._bounded_read(
                path, self.max_report_bytes, "Reviewer benchmark report"
            )
            if current != data:
                raise ReviewerEvalStoreError("content-addressed Reviewer benchmark report mismatch")
        return path

    def load_report(self, report_id: str) -> LoadedReviewerBenchmark:
        self.ensure()
        if not _REPORT_ID_RE.fullmatch(report_id):
            raise ReviewerEvalStoreError(f"invalid Reviewer benchmark report ID: {report_id}")
        path = self.reports_dir / f"{report_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(report_id)
        data = self.store._bounded_read(path, self.max_report_bytes, "Reviewer benchmark report")
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewerEvalStoreError("invalid Reviewer benchmark report JSON") from exc
        if not isinstance(raw, dict) or set(raw) != {"format_version", "kind", "payload"}:
            raise ReviewerEvalStoreError("invalid Reviewer benchmark report envelope")
        if (
            raw["format_version"] != self.FORMAT_VERSION
            or raw["kind"] != "REVIEWER_BENCHMARK_REPORT"
        ):
            raise ReviewerEvalStoreError("invalid Reviewer benchmark report metadata")
        payload = raw["payload"]
        if not isinstance(payload, dict) or "content_hash" not in payload:
            raise ReviewerEvalStoreError("invalid Reviewer benchmark report payload")
        content_hash = payload["content_hash"]
        if not isinstance(content_hash, str):
            raise ReviewerEvalStoreError("Reviewer benchmark content_hash must be a string")
        unhashed = dict(payload)
        del unhashed["content_hash"]
        expected = _hash(unhashed)
        if content_hash != expected:
            raise ReviewerEvalStoreError("Reviewer benchmark report content hash mismatch")
        if report_id != "REVBENCH-" + content_hash.split(":", 1)[1]:
            raise ReviewerEvalStoreError("Reviewer benchmark filename/content hash mismatch")
        return LoadedReviewerBenchmark(report_id=report_id, payload=payload)

    def inspect_replay(self, report_id: str) -> ReviewerEvalReplayStatus:
        loaded = self.load_report(report_id)
        comparisons = loaded.payload.get("comparisons")
        if not isinstance(comparisons, list):
            raise ReviewerEvalStoreError("Reviewer benchmark comparisons must be an array")
        stale_cases: list[str] = []
        stale_bindings: list[str] = []
        for comparison in comparisons:
            if not isinstance(comparison, dict):
                raise ReviewerEvalStoreError("invalid Reviewer benchmark comparison")
            case_id = comparison.get("case_id")
            case_hash = comparison.get("case_hash")
            if not isinstance(case_id, str) or not isinstance(case_hash, str):
                raise ReviewerEvalStoreError("invalid Reviewer benchmark case binding")
            try:
                case = self.load_case(case_id)
            except (KeyError, ReviewerEvalStoreError):
                stale_cases.append(case_id)
                continue
            if case.content_hash != case_hash:
                stale_cases.append(case_id)
                continue
            try:
                self._validate_case_bindings(case)
            except ReviewerEvalStoreError:
                stale_bindings.append(case_id)
        stale_case_ids = tuple(sorted(set(stale_cases)))
        stale_binding_case_ids = tuple(sorted(set(stale_bindings)))
        return ReviewerEvalReplayStatus(
            report_id=loaded.report_id,
            content_hash=loaded.content_hash,
            replayable=not stale_case_ids and not stale_binding_case_ids,
            stale_case_ids=stale_case_ids,
            stale_binding_case_ids=stale_binding_case_ids,
        )
