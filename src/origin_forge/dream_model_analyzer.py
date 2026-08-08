from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .dream_evidence import DreamEvidenceRecord
from .dream_models import DreamCandidate, DreamCandidateType
from .dream_roles import DreamAnalysisPackage
from .ids import IdKind, validate_id
from .model import ModelAdapter, ModelRequest, ModelResponse


class DreamModelAnalyzerError(RuntimeError):
    pass


_ALLOWED_MODEL_TYPES = frozenset(
    {
        DreamCandidateType.MEMORY,
        DreamCandidateType.SKILL,
        DreamCandidateType.ROUTING,
        DreamCandidateType.CONTEXT,
        DreamCandidateType.PROCESS,
    }
)

DREAM_ANALYZER_INSTRUCTIONS = """You are an Origin Forge offline Dream Analyzer.
Analyze only the supplied frozen evidence and derived-memory state.
Return exactly one JSON object matching the supplied schema.
You may propose candidate knowledge or process improvements, but you have no authority to apply them.
Every candidate must cite one or more evidence_ref_ids from the supplied manifest.
Do not invent evidence IDs. Do not claim a candidate is verified, approved, promoted, or applied.
Do not emit source-code patches, shell commands, tool calls, memory-generation actions, or policy mutations.
Candidate type determines the mandatory downstream gate in Origin Forge; you do not choose that gate.
If there is no well-supported cross-session insight, return an empty candidates array.
"""

DREAM_CANDIDATE_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_type": {
                        "type": "string",
                        "enum": [
                            DreamCandidateType.MEMORY.value,
                            DreamCandidateType.SKILL.value,
                            DreamCandidateType.ROUTING.value,
                            DreamCandidateType.CONTEXT.value,
                            DreamCandidateType.PROCESS.value,
                        ],
                    },
                    "summary": {"type": "string", "minLength": 1, "maxLength": 8192},
                    "proposed_action": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4096,
                    },
                    "evidence_ref_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "contradiction_ref_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                },
                "required": [
                    "candidate_type",
                    "summary",
                    "proposed_action",
                    "evidence_ref_ids",
                    "contradiction_ref_ids",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
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
        raise DreamModelAnalyzerError("Dream model context must be finite JSON data") from exc


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class DreamModelAnalysisResult:
    candidates: tuple[DreamCandidate, ...]
    model_id: str
    model_hash: str | None
    input_tokens: int | None
    output_tokens: int | None
    context_hash: str
    response_hash: str

    def __post_init__(self) -> None:
        if any(not isinstance(item, DreamCandidate) for item in self.candidates):
            raise DreamModelAnalyzerError("result candidates must contain DreamCandidate values")
        if not isinstance(self.model_id, str) or not self.model_id:
            raise DreamModelAnalyzerError("result model_id must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_ids": [item.candidate_id for item in self.candidates],
            "candidate_hashes": [item.content_hash for item in self.candidates],
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "context_hash": self.context_hash,
            "response_hash": self.response_hash,
        }


class BoundedModelDreamAnalyzer:
    """Model-backed candidate generator with no mutation or promotion authority."""

    def __init__(
        self,
        model: ModelAdapter,
        *,
        max_context_bytes: int = 1024 * 1024,
        max_response_bytes: int = 256 * 1024,
    ):
        if not isinstance(model, ModelAdapter):
            raise TypeError("model must implement ModelAdapter")
        if not isinstance(max_context_bytes, int) or isinstance(max_context_bytes, bool) or max_context_bytes <= 0:
            raise ValueError("max_context_bytes must be a positive integer")
        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")
        self.model = model
        self.max_context_bytes = max_context_bytes
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def _manifest_refs(package: DreamAnalysisPackage) -> dict[str, object]:
        refs: dict[str, object] = {}
        for values in (
            package.manifest.run_refs,
            package.manifest.task_refs,
            package.manifest.decision_refs,
            package.manifest.verification_refs,
            package.manifest.memory_refs,
        ):
            for item in values:
                existing = refs.get(item.ref_id)
                if existing is not None and existing != item:
                    raise DreamModelAnalyzerError(
                        f"frozen manifest contains conflicting refs for {item.ref_id}"
                    )
                refs[item.ref_id] = item
        return refs

    def _context(
        self,
        package: DreamAnalysisPackage,
        evidence_records: Iterable[DreamEvidenceRecord],
    ) -> tuple[dict[str, object], dict[str, object]]:
        manifest_refs = self._manifest_refs(package)
        records = tuple(evidence_records)
        if any(not isinstance(item, DreamEvidenceRecord) for item in records):
            raise TypeError("evidence_records must contain DreamEvidenceRecord values")
        seen: set[str] = set()
        for record in records:
            if record.ref.ref_id in seen:
                raise DreamModelAnalyzerError(
                    f"duplicate Dream evidence record: {record.ref.ref_id}"
                )
            seen.add(record.ref.ref_id)
            frozen = manifest_refs.get(record.ref.ref_id)
            if frozen is None or frozen != record.ref:
                raise DreamModelAnalyzerError(
                    f"Dream evidence record is not an exact frozen manifest ref: {record.ref.ref_id}"
                )

        context = {
            "manifest": package.manifest.to_dict(),
            "preprocess_report": package.preprocess_report.to_dict(),
            "active_memory_entries": [item.to_dict() for item in package.memory_entries],
            "evidence_records": [
                item.to_dict()
                for item in sorted(records, key=lambda value: (value.record_type, value.ref.ref_id))
            ],
        }
        encoded = _canonical_bytes(context)
        if len(encoded) > self.max_context_bytes:
            raise DreamModelAnalyzerError(
                "Dream model context exceeds byte limit "
                f"({len(encoded)} > {self.max_context_bytes})"
            )
        return context, manifest_refs

    @staticmethod
    def _strict_object(
        value: object,
        *,
        required: set[str],
        label: str,
    ) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != required:
            raise DreamModelAnalyzerError(f"{label} does not match strict response contract")
        return value

    def _parse(
        self,
        response: ModelResponse,
        package: DreamAnalysisPackage,
        manifest_refs: dict[str, object],
    ) -> tuple[DreamCandidate, ...]:
        encoded = response.text.encode("utf-8")
        if len(encoded) > self.max_response_bytes:
            raise DreamModelAnalyzerError(
                "Dream model response exceeds byte limit "
                f"({len(encoded)} > {self.max_response_bytes})"
            )
        try:
            raw = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise DreamModelAnalyzerError("Dream model response must be one JSON object") from exc
        envelope = self._strict_object(raw, required={"candidates"}, label="Dream response")
        raw_candidates = envelope["candidates"]
        if not isinstance(raw_candidates, list):
            raise DreamModelAnalyzerError("Dream response candidates must be an array")
        if len(raw_candidates) > package.manifest.budget.max_candidates:
            raise DreamModelAnalyzerError(
                "Dream model candidate count exceeds frozen manifest budget "
                f"({len(raw_candidates)} > {package.manifest.budget.max_candidates})"
            )

        result: list[DreamCandidate] = []
        for index, raw_candidate in enumerate(raw_candidates):
            item = self._strict_object(
                raw_candidate,
                required={
                    "candidate_type",
                    "summary",
                    "proposed_action",
                    "evidence_ref_ids",
                    "contradiction_ref_ids",
                },
                label=f"Dream candidate[{index}]",
            )
            raw_type = item["candidate_type"]
            if not isinstance(raw_type, str):
                raise DreamModelAnalyzerError(f"Dream candidate[{index}].candidate_type must be a string")
            try:
                candidate_type = DreamCandidateType(raw_type)
            except ValueError as exc:
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}] has unsupported candidate_type"
                ) from exc
            if candidate_type not in _ALLOWED_MODEL_TYPES:
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}] type is not available to model analyzers"
                )
            summary = item["summary"]
            action = item["proposed_action"]
            if not isinstance(summary, str) or not isinstance(action, str):
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}] summary/action must be strings"
                )

            evidence_ids = item["evidence_ref_ids"]
            contradiction_ids = item["contradiction_ref_ids"]
            if (
                not isinstance(evidence_ids, list)
                or not evidence_ids
                or any(not isinstance(value, str) for value in evidence_ids)
            ):
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}].evidence_ref_ids must be a non-empty string array"
                )
            if (
                not isinstance(contradiction_ids, list)
                or any(not isinstance(value, str) for value in contradiction_ids)
            ):
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}].contradiction_ref_ids must be a string array"
                )
            if len(evidence_ids) != len(set(evidence_ids)) or len(contradiction_ids) != len(set(contradiction_ids)):
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}] contains duplicate evidence IDs"
                )

            try:
                evidence_refs = tuple(manifest_refs[value] for value in evidence_ids)
                contradiction_refs = tuple(manifest_refs[value] for value in contradiction_ids)
            except KeyError as exc:
                raise DreamModelAnalyzerError(
                    f"Dream candidate[{index}] cites evidence outside frozen manifest: {exc.args[0]}"
                ) from exc

            result.append(
                DreamCandidate.create(
                    candidate_type=candidate_type,
                    summary=summary,
                    proposed_action=action,
                    evidence_refs=evidence_refs,
                    contradiction_refs=contradiction_refs,
                    target_memory_generation_id=package.manifest.parent_memory_generation_id,
                )
            )
        return tuple(result)

    def analyze(
        self,
        package: DreamAnalysisPackage,
        evidence_records: Iterable[DreamEvidenceRecord],
        *,
        run_id: str,
        task_id: str,
    ) -> DreamModelAnalysisResult:
        if not isinstance(package, DreamAnalysisPackage):
            raise TypeError("package must be a DreamAnalysisPackage")
        if not validate_id(run_id, IdKind.RUN):
            raise DreamModelAnalyzerError("run_id must be a RUN ID")
        if not validate_id(task_id, IdKind.TASK):
            raise DreamModelAnalyzerError("task_id must be a TASK ID")
        context, manifest_refs = self._context(package, evidence_records)
        context_hash = _hash(context)
        request = ModelRequest(
            run_id=run_id,
            task_id=task_id,
            instructions=DREAM_ANALYZER_INSTRUCTIONS,
            context=context,
            response_schema=DREAM_CANDIDATE_RESPONSE_SCHEMA,
        )
        response = self.model.generate(request)
        if not isinstance(response, ModelResponse):
            raise DreamModelAnalyzerError("Dream model adapter returned an invalid response")
        candidates = self._parse(response, package, manifest_refs)
        return DreamModelAnalysisResult(
            candidates=candidates,
            model_id=response.model_id,
            model_hash=response.model_hash,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            context_hash=context_hash,
            response_hash="sha256:" + hashlib.sha256(response.text.encode("utf-8")).hexdigest(),
        )
