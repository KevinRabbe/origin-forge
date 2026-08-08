from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .dream_models import DreamBudget
from .dream_planner import DreamPlanResult, DreamPlanningCoordinator
from .dream_store import DreamStore
from .runtime import OriginForgeRuntime
from .state import FlowStatus, GoalStatus, RunStatus, TaskStatus


@dataclass(frozen=True)
class DreamCycleResult:
    goal_id: str
    flow_id: str
    task_id: str
    run_id: str
    verification_id: str
    plan: DreamPlanResult

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "flow_id": self.flow_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "verification_id": self.verification_id,
            "manifest_id": self.plan.manifest.manifest_id,
            "manifest_hash": self.plan.manifest.content_hash,
            "plan_hash": self.plan.content_hash,
            "candidate_ids": [item.candidate_id for item in self.plan.candidates],
            "audit_count": len(self.plan.audits),
            "model_invoked": False,
            "memory_generation_created": False,
        }


class DreamCycleService:
    """Durable operator lifecycle for deterministic proposal-only Dream planning."""

    RUN_ROLE = "DREAM_CYCLE"

    def __init__(self, runtime: OriginForgeRuntime, store: DreamStore | None = None):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store = store or DreamStore(runtime)
        if self.store.runtime.project_root != runtime.project_root:
            raise ValueError("DreamStore and runtime must belong to the same project")
        self.planner = DreamPlanningCoordinator(runtime, self.store)

    @staticmethod
    def _metrics(plan: DreamPlanResult) -> dict[str, int]:
        return {
            "evidence_record_count": len(plan.evidence_records),
            "active_memory_entry_count": len(plan.active_memory_entries),
            "preprocess_finding_count": len(plan.preprocess_report.findings),
            "candidate_count": len(plan.candidates),
            "audit_count": len(plan.audits),
        }

    def _record_success(self, run_id: str, task_id: str, plan: DreamPlanResult) -> tuple[str, str]:
        evidence = {
            "manifest_id": plan.manifest.manifest_id,
            "manifest_hash": plan.manifest.content_hash,
            "plan_hash": plan.content_hash,
            "candidate_refs": [
                {"candidate_id": item.candidate_id, "content_hash": item.content_hash}
                for item in plan.candidates
            ],
            "audit_refs": [
                {
                    "candidate_id": item.candidate_id,
                    "audit_hash": item.content_hash,
                    "status": item.status.value,
                }
                for item in plan.audits
            ],
            "model_invoked": False,
            "memory_generation_created": False,
            "canonical_project_state_changed_by_dream_output": False,
        }
        metrics = self._metrics(plan)
        run_verification = self.runtime.record_verification(
            "RUN",
            run_id,
            verification_type="dream-cycle-plan",
            verifier="origin-forge-dream-cycle",
            status="PASS",
            evidence=evidence,
            metrics=metrics,
            run_id=run_id,
        )
        task_verification = self.runtime.record_verification(
            "TASK",
            task_id,
            verification_type="dream-cycle-plan",
            verifier="origin-forge-dream-cycle",
            status="PASS",
            evidence={
                "run_id": run_id,
                "run_verification_id": run_verification,
                "manifest_id": plan.manifest.manifest_id,
                "manifest_hash": plan.manifest.content_hash,
            },
            metrics=metrics,
            run_id=run_id,
        )
        return run_verification, task_verification

    def _record_goal_success(
        self,
        *,
        goal_id: str,
        flow_id: str,
        task_id: str,
        run_id: str,
        run_verification_id: str,
        plan: DreamPlanResult,
    ) -> str:
        return self.runtime.record_verification(
            "GOAL",
            goal_id,
            verification_type="dream-cycle-plan",
            verifier="origin-forge-dream-cycle",
            status="PASS",
            evidence={
                "flow_id": flow_id,
                "task_id": task_id,
                "run_id": run_id,
                "run_verification_id": run_verification_id,
                "manifest_id": plan.manifest.manifest_id,
                "manifest_hash": plan.manifest.content_hash,
                "plan_hash": plan.content_hash,
                "model_invoked": False,
                "memory_generation_created": False,
                "canonical_project_state_changed_by_dream_output": False,
            },
            metrics=self._metrics(plan),
            run_id=run_id,
        )

    def _record_failure(self, run_id: str, exc: Exception) -> None:
        try:
            self.runtime.record_verification(
                "RUN",
                run_id,
                verification_type="dream-cycle-plan",
                verifier="origin-forge-dream-cycle",
                status="FAIL",
                evidence={
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:4096],
                    "model_invoked": False,
                    "memory_generation_created": False,
                },
                run_id=run_id,
            )
        except Exception:
            # Failure recording must never hide the original planning failure.
            pass

    def run(
        self,
        run_ids: Iterable[str],
        *,
        parent_generation_id: str | None = None,
        budget: DreamBudget | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> DreamCycleResult:
        goal_id = self.runtime.create_goal(
            "Offline Dream consolidation",
            success_criteria=(
                "freeze bounded completed-work evidence",
                "persist proposal-only candidates and independent audits",
                "do not create a memory generation automatically",
            ),
            constraints=(
                "no model invocation",
                "no source, Skill, routing-policy, or canonical-truth mutation from Dream output",
            ),
        )
        goal_revision = self.runtime.transition_goal(
            goal_id,
            GoalStatus.ACTIVE,
            expected_revision=0,
        )
        flow_id = self.runtime.create_flow(goal_id, controller="DREAM_CYCLE")
        flow_revision = self.runtime.transition_flow(
            flow_id,
            FlowStatus.RUNNING,
            expected_revision=0,
        )
        task_id = self.runtime.create_task(
            flow_id,
            "Plan one bounded deterministic Dream cycle",
            acceptance_criteria=(
                "Dream input manifest is frozen and persisted",
                "every candidate has an independent audit",
                "no memory generation is auto-created",
            ),
            constraints=("proposal-only", "deterministic analyzer only"),
            required_capabilities=("dream.plan",),
        )
        task_revision = self.runtime.transition_task(
            task_id,
            TaskStatus.READY,
            expected_revision=0,
        )
        task_revision = self.runtime.transition_task(
            task_id,
            TaskStatus.RUNNING,
            expected_revision=task_revision,
        )
        run_id = self.runtime.start_run(task_id, role=self.RUN_ROLE)

        try:
            plan = self.planner.plan(
                run_ids,
                parent_generation_id=parent_generation_id,
                budget=budget,
                window_start=window_start,
                window_end=window_end,
            )
            run_verification, _ = self._record_success(run_id, task_id, plan)
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            self.runtime.transition_task(
                task_id,
                TaskStatus.SUCCEEDED,
                expected_revision=task_revision,
            )
            self.runtime.transition_flow(
                flow_id,
                FlowStatus.SUCCEEDED,
                expected_revision=flow_revision,
            )
            self._record_goal_success(
                goal_id=goal_id,
                flow_id=flow_id,
                task_id=task_id,
                run_id=run_id,
                run_verification_id=run_verification,
                plan=plan,
            )
            self.runtime.transition_goal(
                goal_id,
                GoalStatus.SUCCEEDED,
                expected_revision=goal_revision,
            )
            return DreamCycleResult(
                goal_id=goal_id,
                flow_id=flow_id,
                task_id=task_id,
                run_id=run_id,
                verification_id=run_verification,
                plan=plan,
            )
        except Exception as exc:
            self._record_failure(run_id, exc)
            try:
                if self.runtime.get_run(run_id)["status"] == RunStatus.RUNNING.value:
                    self.runtime.finish_run(
                        run_id,
                        RunStatus.FAILED,
                        failure_reason=f"{type(exc).__name__}: {str(exc)[:2048]}",
                    )
            finally:
                try:
                    current_task = self.runtime.get_task(task_id)
                    if current_task["status"] == TaskStatus.RUNNING.value:
                        self.runtime.transition_task(
                            task_id,
                            TaskStatus.FAILED,
                            expected_revision=int(current_task["revision"]),
                        )
                finally:
                    try:
                        current_flow = self.runtime.get_flow(flow_id)
                        if current_flow["status"] == FlowStatus.RUNNING.value:
                            self.runtime.transition_flow(
                                flow_id,
                                FlowStatus.FAILED,
                                expected_revision=int(current_flow["revision"]),
                            )
                    finally:
                        current_goal = self.runtime.get_goal(goal_id)
                        if current_goal["status"] == GoalStatus.ACTIVE.value:
                            self.runtime.transition_goal(
                                goal_id,
                                GoalStatus.BLOCKED,
                                expected_revision=int(current_goal["revision"]),
                            )
            raise
