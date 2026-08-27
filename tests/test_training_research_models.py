from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.training_research_models import (
    ResearchDisclosureClass,
    TrainingAcceptancePolicy,
    TrainingDatasetManifest,
    TrainingDatasetSplit,
    TrainingEligibilityAudit,
    TrainingEvaluationObservation,
    TrainingEvidenceRef,
    TrainingEvidenceType,
    TrainingExperimentPlan,
    TrainingExperimentReport,
    TrainingExperimentVerdict,
    TrainingMethodFamily,
    TrainingResearchModelError,
    TrainingTrajectory,
    TrainingTrajectoryOutcome,
    deterministic_training_split,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64


def _ref(
    evidence_type: TrainingEvidenceType,
    ref_id: str,
    content_hash: str,
    *,
    disclosure: ResearchDisclosureClass = ResearchDisclosureClass.ALLOWED,
    revision: int | None = None,
) -> TrainingEvidenceRef:
    return TrainingEvidenceRef(
        evidence_type=evidence_type,
        ref_id=ref_id,
        content_hash=content_hash,
        revision=revision,
        disclosure=disclosure,
    )


def _trajectory(
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    leakage_group_hash: str = HASH_D,
    outcome: TrainingTrajectoryOutcome = TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
    protected: bool = False,
) -> TrainingTrajectory:
    project_id = project_id or new_id(IdKind.PROJECT)
    task_id = task_id or new_id(IdKind.TASK)
    run_id = run_id or new_id(IdKind.RUN)
    refs = [
        _ref(TrainingEvidenceType.TASK, task_id, HASH_A, revision=3),
        _ref(TrainingEvidenceType.RUN, run_id, HASH_B),
    ]
    if outcome is not TrainingTrajectoryOutcome.INFRASTRUCTURE_FAILURE:
        refs.append(
            _ref(
                TrainingEvidenceType.VERIFICATION,
                new_id(IdKind.VERIFICATION),
                HASH_C,
                disclosure=(
                    ResearchDisclosureClass.PROTECTED
                    if protected
                    else ResearchDisclosureClass.ALLOWED
                ),
            )
        )
    elif protected:
        refs.append(
            _ref(
                TrainingEvidenceType.ARTIFACT,
                new_id(IdKind.ARTIFACT),
                HASH_C,
                disclosure=ResearchDisclosureClass.PROTECTED,
            )
        )
    return TrainingTrajectory.create(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        leakage_group_hash=leakage_group_hash,
        outcome=outcome,
        objective="Repair the bounded failing behavior.",
        model_profile="coding-small",
        model_hash=HASH_E,
        example={
            "input": {"task": "repair"},
            "target": {"result": "verified"},
        },
        source_refs=refs,
    )


def _audit(trajectory: TrainingTrajectory) -> TrainingEligibilityAudit:
    return TrainingEligibilityAudit.create(
        trajectory=trajectory,
        policy_id="verified-trajectory-v1",
        policy_version="1",
        policy_fingerprint=HASH_F,
    )


def _dataset(*trajectories: TrainingTrajectory) -> TrainingDatasetManifest:
    return TrainingDatasetManifest.create(
        trajectories=trajectories,
        audits=tuple(_audit(value) for value in trajectories),
        policy_id="verified-trajectory-v1",
        policy_version="1",
        policy_fingerprint=HASH_F,
        split_salt_hash=HASH_A,
    )


def _plan(dataset: TrainingDatasetManifest) -> TrainingExperimentPlan:
    return TrainingExperimentPlan.create(
        dataset=dataset,
        base_model_profile="coding-small",
        base_model_hash=HASH_B,
        tokenizer_hash=HASH_C,
        method_family=TrainingMethodFamily.ADAPTER_LORA,
        trainer_id="offline-trainer-unwired",
        trainer_version="1",
        trainer_fingerprint=HASH_D,
        evaluator_id="heldout-task-suite",
        evaluator_version="1",
        evaluator_fingerprint=HASH_E,
        evaluation_suite_id="phase29-heldout-v1",
        evaluation_suite_hash=HASH_F,
        max_training_tokens=1_000_000,
        max_wall_time_ms=3_600_000,
        max_checkpoint_bytes=128 * 1024 * 1024,
        acceptance=TrainingAcceptancePolicy(),
    )


def _observation(
    *,
    success: int = 900,
    quality: int = 900,
    critical: int = 0,
    calls: int = 3,
    input_tokens: int = 3000,
    output_tokens: int = 500,
    wall_time: int = 1000,
    evidence_hash: str = HASH_A,
) -> TrainingEvaluationObservation:
    return TrainingEvaluationObservation(
        success_milli=success,
        quality_milli=quality,
        critical_failures=critical,
        model_calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        wall_time_ms=wall_time,
        evidence_hash=evidence_hash,
    )


class TrainingResearchModelTests(unittest.TestCase):
    def test_verified_trajectory_requires_exact_task_run_and_verification_evidence(self) -> None:
        task_id = new_id(IdKind.TASK)
        run_id = new_id(IdKind.RUN)
        with self.assertRaisesRegex(TrainingResearchModelError, "verification evidence"):
            TrainingTrajectory.create(
                project_id=new_id(IdKind.PROJECT),
                task_id=task_id,
                run_id=run_id,
                leakage_group_hash=HASH_A,
                outcome=TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
                objective="work",
                example={"input": "x", "target": "y"},
                source_refs=(
                    _ref(TrainingEvidenceType.TASK, task_id, HASH_B),
                    _ref(TrainingEvidenceType.RUN, run_id, HASH_C),
                ),
            )

        trajectory = _trajectory()
        payload = trajectory.to_dict()
        self.assertFalse(payload["production_training_authorized"])
        self.assertFalse(payload["production_model_activation_authorized"])
        self.assertFalse(payload["production_task_verified"])

    def test_protected_evidence_makes_eligibility_fail_closed(self) -> None:
        trajectory = _trajectory(protected=True)
        audit = _audit(trajectory)
        self.assertFalse(audit.eligible)
        self.assertEqual(audit.reasons, ("protected-evidence",))
        with self.assertRaisesRegex(TrainingResearchModelError, "ineligible"):
            TrainingDatasetManifest.create(
                trajectories=(trajectory,),
                audits=(audit,),
                policy_id="verified-trajectory-v1",
                policy_version="1",
                policy_fingerprint=HASH_F,
                split_salt_hash=HASH_A,
            )

    def test_forged_eligibility_audit_is_recomputed(self) -> None:
        trajectory = _trajectory(protected=True)
        audit = _audit(trajectory)
        forged = replace(audit, eligible=True, reasons=())
        with self.assertRaisesRegex(TrainingResearchModelError, "classification is inconsistent"):
            forged.bind(trajectory)

    def test_leakage_group_split_is_deterministic_and_not_caller_selected(self) -> None:
        project = new_id(IdKind.PROJECT)
        first = _trajectory(project_id=project, leakage_group_hash=HASH_D)
        second = _trajectory(project_id=project, leakage_group_hash=HASH_D)
        dataset = _dataset(first, second)
        self.assertEqual(dataset.entries[0].split, dataset.entries[1].split)
        self.assertEqual(
            dataset.entries[0].split,
            deterministic_training_split(
                split_salt_hash=HASH_A,
                leakage_group_hash=HASH_D,
            ),
        )
        wrong = (
            TrainingDatasetSplit.TEST
            if dataset.entries[0].split is not TrainingDatasetSplit.TEST
            else TrainingDatasetSplit.TRAIN
        )
        forged_entry = replace(dataset.entries[0], split=wrong)
        with self.assertRaisesRegex(TrainingResearchModelError, "split assignment is inconsistent"):
            replace(dataset, entries=(forged_entry, dataset.entries[1]))

    def test_dataset_rejects_duplicate_trajectory_and_audit_policy_drift(self) -> None:
        trajectory = _trajectory()
        audit = _audit(trajectory)
        with self.assertRaisesRegex(TrainingResearchModelError, "duplicate trajectory IDs"):
            TrainingDatasetManifest.create(
                trajectories=(trajectory, trajectory),
                audits=(audit, audit),
                policy_id="verified-trajectory-v1",
                policy_version="1",
                policy_fingerprint=HASH_F,
                split_salt_hash=HASH_A,
            )
        drifted = replace(audit, policy_version="2")
        with self.assertRaisesRegex(TrainingResearchModelError, "policy binding drifted"):
            TrainingDatasetManifest.create(
                trajectories=(trajectory,),
                audits=(drifted,),
                policy_id="verified-trajectory-v1",
                policy_version="1",
                policy_fingerprint=HASH_F,
                split_salt_hash=HASH_A,
            )

    def test_plan_freezes_dataset_trainer_evaluator_and_zero_activation_authority(self) -> None:
        dataset = _dataset(_trajectory())
        plan = _plan(dataset)
        plan.bind_dataset(dataset)
        payload = plan.to_dict()
        self.assertEqual(payload["dataset_hash"], dataset.content_hash)
        self.assertFalse(payload["training_execution_authorized"])
        self.assertFalse(payload["production_model_activation_authorized"])
        self.assertFalse(payload["routing_activation_authorized"])
        drifted_dataset = replace(dataset, dataset_id=new_id(IdKind.TRAINING_DATASET))
        with self.assertRaisesRegex(TrainingResearchModelError, "dataset binding drifted"):
            plan.bind_dataset(drifted_dataset)

    def test_quality_regression_dominates_large_efficiency_gain(self) -> None:
        plan = _plan(_dataset(_trajectory()))
        report = TrainingExperimentReport.create(
            plan=plan,
            candidate_checkpoint_hash=HASH_A,
            checkpoint_bytes=1024,
            baseline=_observation(),
            candidate=_observation(
                quality=899,
                calls=1,
                input_tokens=100,
                output_tokens=100,
                wall_time=100,
            ),
        )
        self.assertIs(report.verdict, TrainingExperimentVerdict.REGRESSED)
        self.assertIn("quality_milli", report.regression_reasons)
        self.assertIn("model_calls", report.improvements)
        report.bind_plan(plan)

    def test_improvement_requires_no_frozen_regression(self) -> None:
        plan = _plan(_dataset(_trajectory()))
        report = TrainingExperimentReport.create(
            plan=plan,
            candidate_checkpoint_hash=HASH_B,
            checkpoint_bytes=2048,
            baseline=_observation(),
            candidate=_observation(
                success=920,
                quality=920,
                calls=2,
                input_tokens=2000,
                output_tokens=400,
                wall_time=900,
            ),
        )
        self.assertIs(report.verdict, TrainingExperimentVerdict.IMPROVED)
        self.assertEqual(report.regression_reasons, ())
        payload = report.to_dict()
        self.assertFalse(payload["training_loss_is_promotion_evidence"])
        self.assertFalse(payload["production_model_activation_authorized"])
        self.assertFalse(payload["routing_activation_authorized"])
        self.assertFalse(payload["production_task_verified"])
        self.assertFalse(payload["phase26_promotion_authorized"])

    def test_forged_report_verdict_and_evaluator_drift_fail_closed(self) -> None:
        plan = _plan(_dataset(_trajectory()))
        report = TrainingExperimentReport.create(
            plan=plan,
            candidate_checkpoint_hash=HASH_C,
            checkpoint_bytes=4096,
            baseline=_observation(),
            candidate=_observation(quality=800),
        )
        forged = replace(
            report,
            verdict=TrainingExperimentVerdict.IMPROVED,
            regression_reasons=(),
            improvements=("quality_milli",),
        )
        with self.assertRaisesRegex(TrainingResearchModelError, "classification is inconsistent"):
            forged.bind_plan(plan)
        evaluator_drift = replace(report, evaluator_id="self-reported-trainer")
        with self.assertRaisesRegex(TrainingResearchModelError, "evaluator identity drifted"):
            evaluator_drift.bind_plan(plan)

    def test_checkpoint_byte_limit_is_frozen_before_report(self) -> None:
        plan = _plan(_dataset(_trajectory()))
        with self.assertRaisesRegex(TrainingResearchModelError, "checkpoint exceeds"):
            TrainingExperimentReport.create(
                plan=plan,
                candidate_checkpoint_hash=HASH_D,
                checkpoint_bytes=plan.max_checkpoint_bytes + 1,
                baseline=_observation(),
                candidate=_observation(),
            )


if __name__ == "__main__":
    unittest.main()
