from __future__ import annotations

import unittest
from dataclasses import replace

from origin_forge.ids import IdKind, new_id
from origin_forge.training_research_models import (
    ResearchDisclosureClass,
    TrainingEvidenceRef,
    TrainingEvidenceType,
    TrainingResearchModelError,
    TrainingTrajectory,
    TrainingTrajectoryOutcome,
)
from origin_forge.training_research_policy import (
    GovernedTrainingEligibilityAudit,
    GovernedTrainingTrajectory,
    RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
    RUNTIME_REDACTED_PRODUCER_ID,
    RUNTIME_REDACTED_PRODUCER_VERSION,
    V1_ELIGIBILITY_POLICY_FINGERPRINT,
    V1_ELIGIBILITY_POLICY_ID,
    V1_ELIGIBILITY_POLICY_VERSION,
    is_v1_trusted_trajectory,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def _refs(task_id: str, run_id: str) -> tuple[TrainingEvidenceRef, ...]:
    return (
        TrainingEvidenceRef(
            TrainingEvidenceType.TASK,
            task_id,
            HASH_A,
            1,
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
            ResearchDisclosureClass.ALLOWED,
        ),
    )


def _governed() -> GovernedTrainingTrajectory:
    task_id = new_id(IdKind.TASK)
    run_id = new_id(IdKind.RUN)
    return GovernedTrainingTrajectory.create(
        project_id=new_id(IdKind.PROJECT),
        task_id=task_id,
        run_id=run_id,
        leakage_group_hash=HASH_D,
        outcome=TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
        objective="verified terminal runtime trajectory",
        example={"input": {"role": "EXECUTOR"}, "target": {"status": "SUCCEEDED"}},
        source_refs=_refs(task_id, run_id),
        producer_id=RUNTIME_REDACTED_PRODUCER_ID,
        producer_version=RUNTIME_REDACTED_PRODUCER_VERSION,
        producer_fingerprint=RUNTIME_REDACTED_PRODUCER_FINGERPRINT,
    )


def _generic() -> TrainingTrajectory:
    task_id = new_id(IdKind.TASK)
    run_id = new_id(IdKind.RUN)
    return TrainingTrajectory.create(
        project_id=new_id(IdKind.PROJECT),
        task_id=task_id,
        run_id=run_id,
        leakage_group_hash=HASH_D,
        outcome=TrainingTrajectoryOutcome.VERIFIED_SUCCESS,
        objective="manually assembled research record",
        example={"input": {"claim": "safe"}, "target": {"claim": "verified"}},
        source_refs=_refs(task_id, run_id),
    )


class TrainingResearchPolicyTests(unittest.TestCase):
    def test_exact_runtime_producer_is_trusted_and_eligible(self) -> None:
        trajectory = _governed()
        self.assertTrue(is_v1_trusted_trajectory(trajectory))
        audit = GovernedTrainingEligibilityAudit.create(trajectory=trajectory)
        self.assertTrue(audit.eligible)
        self.assertEqual(audit.reasons, ())
        self.assertEqual(audit.policy_id, V1_ELIGIBILITY_POLICY_ID)
        self.assertEqual(audit.policy_version, V1_ELIGIBILITY_POLICY_VERSION)
        self.assertEqual(audit.policy_fingerprint, V1_ELIGIBILITY_POLICY_FINGERPRINT)
        audit.bind(trajectory)

    def test_generic_manual_trajectory_is_untrusted_even_with_allowed_refs(self) -> None:
        trajectory = _generic()
        self.assertFalse(is_v1_trusted_trajectory(trajectory))
        audit = GovernedTrainingEligibilityAudit.create(trajectory=trajectory)
        self.assertFalse(audit.eligible)
        self.assertEqual(audit.reasons, ("untrusted-producer",))

    def test_producer_fingerprint_drift_is_untrusted(self) -> None:
        trajectory = replace(_governed(), producer_fingerprint=HASH_A)
        self.assertFalse(is_v1_trusted_trajectory(trajectory))
        audit = GovernedTrainingEligibilityAudit.create(trajectory=trajectory)
        self.assertFalse(audit.eligible)
        self.assertIn("untrusted-producer", audit.reasons)

    def test_forged_eligible_audit_for_untrusted_trajectory_fails_revalidation(self) -> None:
        trajectory = _generic()
        audit = GovernedTrainingEligibilityAudit.create(trajectory=trajectory)
        forged = replace(audit, eligible=True, reasons=())
        with self.assertRaisesRegex(TrainingResearchModelError, "classification is inconsistent"):
            forged.bind(trajectory)

    def test_policy_fingerprint_or_trusted_producer_metadata_drift_fails_closed(self) -> None:
        trajectory = _governed()
        audit = GovernedTrainingEligibilityAudit.create(trajectory=trajectory)
        with self.assertRaisesRegex(TrainingResearchModelError, "policy fingerprint drifted"):
            replace(audit, policy_fingerprint=HASH_A).bind(trajectory)
        with self.assertRaisesRegex(TrainingResearchModelError, "trusted-producer policy drifted"):
            replace(audit, trusted_producer_fingerprint=HASH_A).bind(trajectory)


if __name__ == "__main__":
    unittest.main()
