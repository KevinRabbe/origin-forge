from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from origin_forge.ids import IdKind, new_id
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.runtime_observation_models import canonical_bytes
from origin_forge.training_research_models import (
    ResearchDisclosureClass,
    TrainingAcceptancePolicy,
    TrainingDatasetManifest,
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
)
from origin_forge.training_research_store import (
    TrainingResearchStore,
    TrainingResearchStoreError,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64


def _trajectory(*, protected: bool = False) -> TrainingTrajectory:
    project_id = new_id(IdKind.PROJECT)
    task_id = new_id(IdKind.TASK)
    run_id = new_id(IdKind.RUN)
    return TrainingTrajectory.create(
        project_id=project_id,
        task_id=task_id,
        run_id=run_id,
        leakage_group_hash=HASH_D,
        outcome=TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
        objective="Persist one verified research trajectory.",
        model_profile="coding-small",
        model_hash=HASH_E,
        example={"input": {"task": "repair"}, "target": {"result": "verified"}},
        source_refs=(
            TrainingEvidenceRef(
                TrainingEvidenceType.TASK,
                task_id,
                HASH_A,
                2,
                ResearchDisclosureClass.ALLOWED,
            ),
            TrainingEvidenceRef(
                TrainingEvidenceType.RUN,
                run_id,
                HASH_B,
                None,
                ResearchDisclosureClass.ALLOWED,
            ),
            TrainingEvidenceRef(
                TrainingEvidenceType.VERIFICATION,
                new_id(IdKind.VERIFICATION),
                HASH_C,
                None,
                (
                    ResearchDisclosureClass.PROTECTED
                    if protected
                    else ResearchDisclosureClass.ALLOWED
                ),
            ),
        ),
    )


def _audit(trajectory: TrainingTrajectory) -> TrainingEligibilityAudit:
    return TrainingEligibilityAudit.create(
        trajectory=trajectory,
        policy_id="verified-trajectory-v1",
        policy_version="1",
        policy_fingerprint=HASH_F,
    )


def _dataset(trajectory: TrainingTrajectory, audit: TrainingEligibilityAudit) -> TrainingDatasetManifest:
    return TrainingDatasetManifest.create(
        trajectories=(trajectory,),
        audits=(audit,),
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
        max_checkpoint_bytes=1024 * 1024,
        acceptance=TrainingAcceptancePolicy(),
    )


def _observation(*, quality: int, calls: int = 3) -> TrainingEvaluationObservation:
    return TrainingEvaluationObservation(
        success_milli=900,
        quality_milli=quality,
        critical_failures=0,
        model_calls=calls,
        input_tokens=3000,
        output_tokens=500,
        wall_time_ms=1000,
        evidence_hash=HASH_A,
    )


class TrainingResearchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("training-research-store-test")
        self.store = TrainingResearchStore(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_publish_and_load_complete_research_chain(self) -> None:
        trajectory = _trajectory()
        audit = _audit(trajectory)
        dataset = _dataset(trajectory, audit)
        plan = _plan(dataset)
        report = TrainingExperimentReport.create(
            plan=plan,
            candidate_checkpoint_hash=HASH_C,
            checkpoint_bytes=4096,
            baseline=_observation(quality=900),
            candidate=_observation(quality=920, calls=2),
        )
        published = (
            ("trajectories", trajectory.trajectory_id, trajectory.content_hash, self.store.publish_trajectory(trajectory)),
            (
                "eligibility-audits",
                audit.audit_id,
                audit.content_hash,
                self.store.publish_eligibility_audit(audit, trajectory=trajectory),
            ),
            (
                "datasets",
                dataset.dataset_id,
                dataset.content_hash,
                self.store.publish_dataset(dataset, trajectories=(trajectory,), audits=(audit,)),
            ),
            (
                "experiment-plans",
                plan.plan_id,
                plan.content_hash,
                self.store.publish_experiment_plan(plan, dataset=dataset),
            ),
            (
                "experiment-reports",
                report.report_id,
                report.content_hash,
                self.store.publish_experiment_report(report, plan=plan),
            ),
        )
        for category, object_id, expected_hash, path in published:
            self.assertTrue(path.is_file())
            envelope = self.store.load(category, object_id)
            self.assertEqual(envelope["object_id"], object_id)
            self.assertEqual(envelope["content_hash"], expected_hash)

    def test_no_overwrite_and_tamper_detection(self) -> None:
        trajectory = _trajectory()
        path = self.store.publish_trajectory(trajectory)
        with self.assertRaisesRegex(TrainingResearchStoreError, "already exists"):
            self.store.publish_trajectory(trajectory)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["objective"] = "tampered"
        path.write_bytes(canonical_bytes(envelope))
        with self.assertRaisesRegex(TrainingResearchStoreError, "content hash drifted"):
            self.store.load("trajectories", trajectory.trajectory_id)

    def test_noncanonical_rewrite_and_symlinked_category_are_rejected(self) -> None:
        trajectory = _trajectory()
        path = self.store.publish_trajectory(trajectory)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(TrainingResearchStoreError, "not canonical"):
            self.store.load("trajectories", trajectory.trajectory_id)

        with tempfile.TemporaryDirectory() as second:
            runtime = OriginForgeRuntime(Path(second))
            runtime.initialize("training-research-symlink-test")
            store = TrainingResearchStore(runtime)
            root = runtime.state_dir / "training-research"
            root.mkdir()
            outside = runtime.state_dir / "outside-training"
            outside.mkdir()
            (root / "trajectories").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(TrainingResearchStoreError, "may not be a symlink"):
                store.publish_trajectory(_trajectory())

    def test_forged_eligibility_is_rejected_before_persistence(self) -> None:
        trajectory = _trajectory(protected=True)
        audit = _audit(trajectory)
        forged = replace(audit, eligible=True, reasons=())
        with self.assertRaisesRegex(TrainingResearchModelError, "classification is inconsistent"):
            self.store.publish_eligibility_audit(forged, trajectory=trajectory)
        self.assertEqual(self.store.list_objects("eligibility-audits"), ())

    def test_forged_dataset_split_is_rejected_before_persistence(self) -> None:
        trajectory = _trajectory()
        audit = _audit(trajectory)
        dataset = _dataset(trajectory, audit)
        entry = dataset.entries[0]
        wrong_split = type(entry.split).TEST if entry.split.value != "TEST" else type(entry.split).TRAIN
        forged = replace(dataset, entries=(replace(entry, split=wrong_split),))
        with self.assertRaisesRegex(TrainingResearchModelError, "split assignment is inconsistent"):
            # Dataclass construction itself is already fail-closed; if a future construction
            # path relaxes that, publish_dataset also recomputes source bindings.
            self.store.publish_dataset(forged, trajectories=(trajectory,), audits=(audit,))

    def test_forged_report_classification_is_rejected_before_persistence(self) -> None:
        trajectory = _trajectory()
        audit = _audit(trajectory)
        dataset = _dataset(trajectory, audit)
        plan = _plan(dataset)
        report = TrainingExperimentReport.create(
            plan=plan,
            candidate_checkpoint_hash=HASH_C,
            checkpoint_bytes=4096,
            baseline=_observation(quality=900),
            candidate=_observation(quality=800),
        )
        self.assertIs(report.verdict, TrainingExperimentVerdict.REGRESSED)
        forged = replace(
            report,
            verdict=TrainingExperimentVerdict.IMPROVED,
            regression_reasons=(),
            improvements=("quality_milli",),
        )
        with self.assertRaisesRegex(TrainingResearchModelError, "classification is inconsistent"):
            self.store.publish_experiment_report(forged, plan=plan)
        self.assertEqual(self.store.list_objects("experiment-reports"), ())

    def test_dataset_publication_recomputes_audit_and_entry_bindings(self) -> None:
        trajectory = _trajectory()
        audit = _audit(trajectory)
        dataset = _dataset(trajectory, audit)
        foreign = _trajectory()
        foreign_audit = _audit(foreign)
        with self.assertRaises(TrainingResearchModelError):
            self.store.publish_dataset(
                dataset,
                trajectories=(foreign,),
                audits=(foreign_audit,),
            )
        self.assertEqual(self.store.list_objects("datasets"), ())


if __name__ == "__main__":
    unittest.main()
