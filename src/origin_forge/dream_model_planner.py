from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .dream_model_analyzer import (
    BoundedModelDreamAnalyzer,
    DreamModelAnalysisResult,
)
from .dream_models import DreamBudget, DreamCandidate
from .dream_planner import DreamPlanResult, DreamPlanningCoordinator, DreamPlanningError
from .dream_preprocess import EvidenceSnapshot, preprocess_memory
from .dream_roles import DreamAnalysisPackage
from .dream_store import DreamStore
from .model import ModelAdapter
from .runtime import OriginForgeRuntime
from .state import RunStatus, TaskStatus


@dataclass(frozen=True)
class ModelDreamPlanResult:
    plan: DreamPlanResult
    model_analysis: DreamModelAnalysisResult
    trace_verification_id: str

    def __post_init__(self) -> None:
        plan_hashes = {item.content_hash for item in self.plan.candidates}
        if any(
            item.content_hash not in plan_hashes
            for item in self.model_analysis.candidates
        ):
            raise DreamPlanningError(
                "model analysis contains a candidate that is not part of the audited Dream plan"
            )
        if not isinstance(self.trace_verification_id, str) or not self.trace_verification_id.startswith(
            "VERIFY-"
        ):
            raise DreamPlanningError("model Dream plan must bind a durable trace Verification")

    def to_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.to_dict(),
            "model_analysis": self.model_analysis.to_dict(),
            "trace_verification_id": self.trace_verification_id,
            "memory_generation_created": False,
            "canonical_project_state_changed": False,
        }


class ModelDreamPlanningCoordinator(DreamPlanningCoordinator):
    """Proposal-only Dream planning with one bounded model analyzer call.

    The caller must provide an already-running durable DREAM_ANALYZER Run and
    its owning Task. This coordinator does not create, finish, approve, promote,
    apply, or merge anything. Model output is parsed into candidates, combined
    with deterministic findings, independently audited, and only then persisted
    as inert Dream proposal evidence.
    """

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        store: DreamStore | None = None,
        *,
        max_context_bytes: int = 1024 * 1024,
        max_response_bytes: int = 256 * 1024,
    ):
        super().__init__(runtime, store)
        self.model_analyzer = BoundedModelDreamAnalyzer(
            model,
            max_context_bytes=max_context_bytes,
            max_response_bytes=max_response_bytes,
        )

    def _validate_model_run(self, model_run_id: str, model_task_id: str) -> None:
        try:
            run = self.runtime.get_run(model_run_id)
            task = self.runtime.get_task(model_task_id)
        except KeyError as exc:
            raise DreamPlanningError(
                "model Dream planning requires an existing durable Run and Task"
            ) from exc
        if run["task_id"] != model_task_id:
            raise DreamPlanningError("Dream analyzer Run does not belong to the supplied Task")
        if run["status"] != RunStatus.RUNNING.value:
            raise DreamPlanningError("Dream analyzer Run must be RUNNING")
        if task["status"] != TaskStatus.RUNNING.value:
            raise DreamPlanningError("Dream analyzer Task must be RUNNING")
        if run["role"] != "DREAM_ANALYZER":
            raise DreamPlanningError("Dream analyzer Run role must be exactly DREAM_ANALYZER")

    @staticmethod
    def _deduplicate_candidates(
        deterministic: Iterable[DreamCandidate],
        model: Iterable[DreamCandidate],
    ) -> tuple[tuple[DreamCandidate, ...], tuple[DreamCandidate, ...]]:
        combined: list[DreamCandidate] = []
        model_kept: list[DreamCandidate] = []
        seen_hashes: set[str] = set()
        for candidate in deterministic:
            if candidate.content_hash not in seen_hashes:
                seen_hashes.add(candidate.content_hash)
                combined.append(candidate)
        for candidate in model:
            if candidate.content_hash in seen_hashes:
                continue
            seen_hashes.add(candidate.content_hash)
            combined.append(candidate)
            model_kept.append(candidate)
        return tuple(combined), tuple(model_kept)

    @staticmethod
    def _enforce_model_tokens(
        result: DreamModelAnalysisResult,
        budget: DreamBudget,
    ) -> None:
        if result.input_tokens is None or result.output_tokens is None:
            raise DreamPlanningError(
                "bounded model Dream planning requires reported input/output token counts"
            )
        if (
            not isinstance(result.input_tokens, int)
            or isinstance(result.input_tokens, bool)
            or result.input_tokens < 0
            or not isinstance(result.output_tokens, int)
            or isinstance(result.output_tokens, bool)
            or result.output_tokens < 0
        ):
            raise DreamPlanningError("Dream model returned invalid token accounting")
        observed = result.input_tokens + result.output_tokens
        if observed > budget.max_analysis_tokens:
            raise DreamPlanningError(
                "Dream model analysis exceeded frozen token budget "
                f"({observed} > {budget.max_analysis_tokens})"
            )

    def _record_trace(
        self,
        *,
        model_run_id: str,
        manifest_hash: str,
        manifest_id: str,
        parent_generation_id: str | None,
        result: DreamModelAnalysisResult,
        candidates: tuple[DreamCandidate, ...],
        audits,
    ) -> str:
        run = self.runtime.get_run(model_run_id)
        return self.runtime.record_verification(
            "RUN",
            model_run_id,
            verification_type="dream-model-structural-capture",
            verifier="origin-forge-dream-model-planner",
            status="PASS",
            evidence={
                "manifest_id": manifest_id,
                "manifest_hash": manifest_hash,
                "parent_memory_generation_id": parent_generation_id,
                "model_profile": run["model_profile"],
                "model_id": result.model_id,
                "model_hash": result.model_hash,
                "context_hash": result.context_hash,
                "response_hash": result.response_hash,
                "candidate_refs": [
                    {"candidate_id": item.candidate_id, "content_hash": item.content_hash}
                    for item in candidates
                ],
                "audit_refs": [
                    {
                        "candidate_id": item.candidate_id,
                        "audit_hash": item.content_hash,
                        "status": item.status.value,
                    }
                    for item in audits
                ],
                "semantic_claims_verified": False,
                "memory_generation_created": False,
                "canonical_project_state_changed": False,
            },
            metrics={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "observed_analysis_tokens": result.input_tokens + result.output_tokens,
                "model_candidate_count": len(result.candidates),
                "persisted_candidate_count": len(candidates),
                "audit_count": len(audits),
            },
            run_id=model_run_id,
        )

    def plan(
        self,
        run_ids: Iterable[str],
        *,
        model_run_id: str,
        model_task_id: str,
        parent_generation_id: str | None = None,
        budget: DreamBudget | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> ModelDreamPlanResult:
        effective_budget = budget or DreamBudget()
        if effective_budget.max_model_calls < 1:
            raise DreamPlanningError("Dream model call is disabled by the frozen budget")
        self._validate_model_run(model_run_id, model_task_id)

        selected = self.collector.collect(
            run_ids,
            parent_memory_generation_id=parent_generation_id,
            budget=effective_budget,
            window_start=window_start,
            window_end=window_end,
        )
        memory_entries = self._active_memory(parent_generation_id)
        pinned_dependencies = tuple(
            evidence
            for entry in memory_entries
            for evidence in entry.evidence_refs
        )
        unique_dependencies = {
            evidence.ref_id: evidence for evidence in pinned_dependencies
        }
        if len(unique_dependencies) != len({item.ref_id for item in pinned_dependencies}):
            raise DreamPlanningError("active memory evidence references are ambiguous")
        resolved = self.resolver.resolve(unique_dependencies.values())
        records = self._merge_records(selected, resolved.records)

        total_evidence_bytes = sum(item.byte_count for item in records)
        if total_evidence_bytes > effective_budget.max_total_evidence_bytes:
            raise DreamPlanningError(
                "Dream plan evidence exceeds frozen budget after resolving active-memory dependencies "
                f"({total_evidence_bytes} > {effective_budget.max_total_evidence_bytes})"
            )

        manifest = self._manifest_from_records(
            records,
            memory_entries,
            parent_generation_id=parent_generation_id,
            budget=effective_budget,
            window_start=window_start,
            window_end=window_end,
        )
        current_refs = tuple(item.ref for item in records) + tuple(
            item.as_evidence_ref() for item in memory_entries
        )
        snapshot = EvidenceSnapshot.create(
            current_refs,
            superseded_ref_ids=resolved.superseded_ref_ids,
        )
        preprocess_report = preprocess_memory(memory_entries, snapshot)
        package = DreamAnalysisPackage(manifest, preprocess_report, memory_entries)

        deterministic_candidates = self.analyzer.analyze(package)
        model_result = self.model_analyzer.analyze(
            package,
            records,
            run_id=model_run_id,
            task_id=model_task_id,
        )
        self._enforce_model_tokens(model_result, effective_budget)
        candidates, kept_model_candidates = self._deduplicate_candidates(
            deterministic_candidates,
            model_result.candidates,
        )
        if len(candidates) > effective_budget.max_candidates:
            raise DreamPlanningError(
                "combined deterministic/model Dream candidates exceeded frozen candidate budget"
            )

        audits = tuple(
            self.auditor.audit(candidate, manifest, snapshot)
            for candidate in candidates
        )

        # Persistence is intentionally last. A malformed/over-budget model
        # response cannot leave a partial manifest or candidate catalog behind.
        self.store.put_manifest(manifest)
        for candidate in candidates:
            self.store.put_candidate(candidate)
        for audit in audits:
            self.store.put_audit(audit)

        plan = DreamPlanResult(
            manifest=manifest,
            evidence_records=records,
            active_memory_entries=memory_entries,
            preprocess_report=preprocess_report,
            candidates=candidates,
            audits=audits,
        )
        filtered_model_result = DreamModelAnalysisResult(
            candidates=kept_model_candidates,
            model_id=model_result.model_id,
            model_hash=model_result.model_hash,
            input_tokens=model_result.input_tokens,
            output_tokens=model_result.output_tokens,
            context_hash=model_result.context_hash,
            response_hash=model_result.response_hash,
        )
        trace_verification_id = self._record_trace(
            model_run_id=model_run_id,
            manifest_hash=manifest.content_hash,
            manifest_id=manifest.manifest_id,
            parent_generation_id=parent_generation_id,
            result=filtered_model_result,
            candidates=candidates,
            audits=audits,
        )
        return ModelDreamPlanResult(
            plan=plan,
            model_analysis=filtered_model_result,
            trace_verification_id=trace_verification_id,
        )
