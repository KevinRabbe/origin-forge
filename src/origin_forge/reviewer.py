from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .ids import IdKind, validate_id
from .model import ModelAdapter, ModelRequest, ModelResponse
from .specialist_evidence import SpecialistEvidencePackage
from .specialist_models import (
    ReviewerCategory,
    ReviewerFinding,
    ReviewerReport,
    ReviewerSeverity,
    SpecialistModelError,
    SpecialistRole,
)


class ReviewerError(RuntimeError):
    pass


REVIEWER_INSTRUCTIONS = """You are an Origin Forge isolated Reviewer.
Review only the supplied immutable specialist contract and frozen evidence package.
Return exactly one JSON object matching the supplied schema.
Every finding must cite one or more evidence_ref_ids from the supplied package.
Do not invent evidence IDs.
Do not claim that a Task, Workspace, Goal, Flow, or release is verified, passed, failed, approved, promoted, or complete.
Do not emit patches, file writes, shell commands, tool calls, permission changes, merge/release actions, or follow-up agent instructions.
Findings are advisory evidence only. Deterministic audit, tests, compiler/runtime evidence, and Origin Forge verification remain authoritative.
If no evidence-backed issue is found, return an empty findings array.
"""

REVIEWER_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": [item.value for item in ReviewerSeverity],
                    },
                    "category": {
                        "type": "string",
                        "enum": [item.value for item in ReviewerCategory],
                    },
                    "summary": {"type": "string", "minLength": 1, "maxLength": 8192},
                    "evidence_ref_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "recommendation": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8192,
                    },
                },
                "required": [
                    "severity",
                    "category",
                    "summary",
                    "evidence_ref_ids",
                    "recommendation",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
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
        raise ReviewerError("Reviewer context must be finite JSON data") from exc


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ReviewerResult:
    report: ReviewerReport
    model_id: str
    model_hash: str | None
    input_tokens: int
    output_tokens: int
    context_hash: str
    response_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report.report_id,
            "report_hash": self.report.content_hash,
            "overall_risk": self.report.overall_risk.value,
            "finding_count": len(self.report.findings),
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "context_hash": self.context_hash,
            "response_hash": self.response_hash,
            "production_verification_changed": False,
        }


class IsolatedReviewer:
    """One-shot model Reviewer that can emit advisory findings only."""

    def __init__(self, model: ModelAdapter):
        if not isinstance(model, ModelAdapter):
            raise TypeError("model must implement ModelAdapter")
        self.model = model

    @staticmethod
    def _strict_object(value: object, *, required: set[str], label: str) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != required:
            raise ReviewerError(f"{label} does not match strict response contract")
        return value

    @staticmethod
    def _require_tokens(response: ModelResponse, package: SpecialistEvidencePackage) -> tuple[int, int]:
        values = (
            (response.input_tokens, "input_tokens", package.contract.budget.max_input_tokens),
            (response.output_tokens, "output_tokens", package.contract.budget.max_output_tokens),
        )
        result: list[int] = []
        for value, name, maximum in values:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ReviewerError(f"Reviewer model must report non-negative {name}")
            if value > maximum:
                raise ReviewerError(
                    f"Reviewer model {name} exceeds frozen budget ({value} > {maximum})"
                )
            result.append(value)
        return result[0], result[1]

    def review(
        self,
        package: SpecialistEvidencePackage,
        *,
        run_id: str,
    ) -> ReviewerResult:
        if not isinstance(package, SpecialistEvidencePackage):
            raise TypeError("package must be a SpecialistEvidencePackage")
        if package.contract.role != SpecialistRole.REVIEWER:
            raise ReviewerError("IsolatedReviewer requires a REVIEWER contract")
        if not validate_id(run_id, IdKind.RUN):
            raise ReviewerError("run_id must be a RUN ID")
        if package.contract.budget.max_model_calls < 1:
            raise ReviewerError("Reviewer model call is disabled by the frozen contract budget")

        context = package.to_dict()
        context_bytes = _canonical_bytes(context)
        if len(context_bytes) > package.contract.budget.max_evidence_bytes + 256 * 1024:
            raise ReviewerError("Reviewer context exceeds bounded envelope limit")
        context_hash = "sha256:" + hashlib.sha256(context_bytes).hexdigest()

        request = ModelRequest(
            run_id=run_id,
            task_id=package.contract.parent_task_id,
            instructions=REVIEWER_INSTRUCTIONS,
            context=context,
            response_schema=REVIEWER_RESPONSE_SCHEMA,
        )
        response = self.model.generate(request)
        if not isinstance(response, ModelResponse):
            raise ReviewerError("Reviewer model adapter returned an invalid response")
        input_tokens, output_tokens = self._require_tokens(response, package)
        response_bytes = response.text.encode("utf-8")
        if len(response_bytes) > package.contract.budget.max_report_bytes:
            raise ReviewerError(
                "Reviewer model response exceeds frozen report byte budget "
                f"({len(response_bytes)} > {package.contract.budget.max_report_bytes})"
            )
        try:
            raw = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ReviewerError("Reviewer response must be exactly one JSON object") from exc
        envelope = self._strict_object(raw, required={"findings"}, label="Reviewer response")
        raw_findings = envelope["findings"]
        if not isinstance(raw_findings, list):
            raise ReviewerError("Reviewer findings must be an array")
        if len(raw_findings) > package.contract.budget.max_findings:
            raise ReviewerError(
                "Reviewer finding count exceeds frozen budget "
                f"({len(raw_findings)} > {package.contract.budget.max_findings})"
            )

        evidence_by_id = {item.ref.ref_id: item.ref for item in package.records}
        findings: list[ReviewerFinding] = []
        for index, raw_finding in enumerate(raw_findings):
            item = self._strict_object(
                raw_finding,
                required={
                    "severity",
                    "category",
                    "summary",
                    "evidence_ref_ids",
                    "recommendation",
                },
                label=f"Reviewer finding[{index}]",
            )
            severity_raw = item["severity"]
            category_raw = item["category"]
            summary = item["summary"]
            recommendation = item["recommendation"]
            evidence_ids = item["evidence_ref_ids"]
            if not all(isinstance(value, str) for value in (severity_raw, category_raw, summary, recommendation)):
                raise ReviewerError(f"Reviewer finding[{index}] contains non-string fields")
            try:
                severity = ReviewerSeverity(severity_raw)
                category = ReviewerCategory(category_raw)
            except ValueError as exc:
                raise ReviewerError(f"Reviewer finding[{index}] contains unsupported enum value") from exc
            if (
                not isinstance(evidence_ids, list)
                or not evidence_ids
                or any(not isinstance(value, str) for value in evidence_ids)
            ):
                raise ReviewerError(
                    f"Reviewer finding[{index}].evidence_ref_ids must be a non-empty string array"
                )
            if len(evidence_ids) != len(set(evidence_ids)):
                raise ReviewerError(f"Reviewer finding[{index}] contains duplicate evidence IDs")
            try:
                evidence_refs = tuple(evidence_by_id[value] for value in evidence_ids)
            except KeyError as exc:
                raise ReviewerError(
                    f"Reviewer finding[{index}] cites evidence outside frozen contract: {exc.args[0]}"
                ) from exc
            try:
                findings.append(
                    ReviewerFinding.create(
                        severity=severity,
                        category=category,
                        summary=summary,
                        evidence_refs=evidence_refs,
                        recommendation=recommendation,
                    )
                )
            except SpecialistModelError as exc:
                raise ReviewerError(f"Reviewer finding[{index}] failed validation") from exc

        try:
            report = ReviewerReport.create(
                contract=package.contract,
                model_id=response.model_id,
                model_hash=response.model_hash,
                findings=findings,
            )
        except SpecialistModelError as exc:
            raise ReviewerError("Reviewer report failed infrastructure validation") from exc
        report_bytes = _canonical_bytes(report.to_dict())
        if len(report_bytes) > package.contract.budget.max_report_bytes:
            raise ReviewerError(
                "Reviewer normalized report exceeds frozen report byte budget "
                f"({len(report_bytes)} > {package.contract.budget.max_report_bytes})"
            )

        return ReviewerResult(
            report=report,
            model_id=response.model_id,
            model_hash=response.model_hash,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_hash=context_hash,
            response_hash="sha256:" + hashlib.sha256(response_bytes).hexdigest(),
        )
