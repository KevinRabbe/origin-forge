from __future__ import annotations

import sqlite3
import unittest

from origin_forge.model3d_requests import Model3DRequestReader
from origin_forge.production_model3d_request_authoring import (
    BoundedModel3DRequestAuthor,
    DeterministicModel3DRequestAuthorAdapter,
    audit_model3d_request_proposal,
)
from origin_forge.production_model3d_request_authoring_evidence import (
    freeze_model3d_request_input,
)
from origin_forge.production_model3d_request_publication import (
    Model3DRequestPublicationError,
    approve_model3d_request_publication,
    publish_approved_model3d_request,
    read_model3d_request_approval,
    read_model3d_request_publication,
    require_current_model3d_publication,
)
from origin_forge.state import GoalStatus
from tests.test_phase57a_model3d_request_authoring import (
    Phase57AModel3DRequestAuthoringTests,
    _semantic_response,
)


class Phase57BModel3DRequestPublicationTests(unittest.TestCase):
    def _fixture(self) -> Phase57AModel3DRequestAuthoringTests:
        fixture = Phase57AModel3DRequestAuthoringTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def _approved(self) -> tuple[Phase57AModel3DRequestAuthoringTests, object]:
        fixture = self._fixture()
        request_input = freeze_model3d_request_input(
            fixture.runtime, fixture.task_id, evidence_store=fixture.evidence
        )
        result = BoundedModel3DRequestAuthor(
            fixture.runtime,
            DeterministicModel3DRequestAuthorAdapter(_semantic_response()),
            evidence_store=fixture.evidence,
        ).propose(request_input.request_input_id)
        audit_model3d_request_proposal(
            fixture.runtime, result.proposal.proposal_id, evidence_store=fixture.evidence
        )
        approval = approve_model3d_request_publication(
            fixture.runtime, result.proposal.proposal_id, operator_id="operator-1"
        )
        return fixture, approval

    def test_human_approval_freezes_infrastructure_request_without_publication(self) -> None:
        fixture, approval = self._approved()
        self.assertTrue(approval.request_id.startswith("MODEL3DREQ-"))
        self.assertTrue(approval.request_hash.startswith("sha256:"))
        self.assertEqual(approval.authority, "HUMAN_OPERATOR")
        self.assertEqual(read_model3d_request_approval(fixture.runtime, approval.approval_id), approval)
        self.assertFalse((fixture.runtime.state_dir / "model3d-requests").exists())

    def test_exact_approval_retry_reuses_frozen_identity(self) -> None:
        fixture, approval = self._approved()
        retried = approve_model3d_request_publication(
            fixture.runtime, approval.proposal_id, operator_id="different-operator"
        )
        self.assertEqual(retried, approval)

    def test_publication_is_create_only_and_restart_safe(self) -> None:
        fixture, approval = self._approved()
        first = publish_approved_model3d_request(fixture.runtime, approval.approval_id)
        second = publish_approved_model3d_request(fixture.runtime, approval.approval_id)
        self.assertEqual(first, second)
        request = Model3DRequestReader(fixture.runtime).get(
            first.request_id, first.request_hash
        )
        self.assertEqual(request.request_hash, first.request_hash)
        self.assertEqual(
            read_model3d_request_publication(fixture.runtime, first.publication_id), first
        )

    def test_approval_rejects_non_pass_audit(self) -> None:
        fixture = self._fixture()
        request_input = freeze_model3d_request_input(
            fixture.runtime, fixture.task_id, evidence_store=fixture.evidence
        )
        result = BoundedModel3DRequestAuthor(
            fixture.runtime,
            DeterministicModel3DRequestAuthorAdapter(_semantic_response()),
            evidence_store=fixture.evidence,
        ).propose(request_input.request_input_id)
        with self.assertRaises(Model3DRequestPublicationError):
            approve_model3d_request_publication(fixture.runtime, result.proposal.proposal_id)

    def test_approval_and_publication_are_immutable(self) -> None:
        fixture, approval = self._approved()
        publication = publish_approved_model3d_request(fixture.runtime, approval.approval_id)
        with self.assertRaises(sqlite3.IntegrityError), fixture.runtime.store.session() as conn:
            conn.execute(
                "UPDATE model3d_request_approvals SET request_hash = ? WHERE approval_id = ?",
                ("sha256:" + "0" * 64, approval.approval_id),
            )
        with self.assertRaises(sqlite3.IntegrityError), fixture.runtime.store.session() as conn:
            conn.execute(
                "DELETE FROM model3d_request_publications WHERE publication_id = ?",
                (publication.publication_id,),
            )

    def test_protected_request_tamper_blocks_publication(self) -> None:
        fixture, approval = self._approved()
        request_root = fixture.runtime.state_dir / "model3d-requests"
        request_root.mkdir(parents=True)
        target = request_root / f"{approval.request_id}--{approval.request_hash.removeprefix('sha256:')}.json"
        target.write_text("{}", encoding="utf-8")
        with self.assertRaises(Model3DRequestPublicationError):
            publish_approved_model3d_request(fixture.runtime, approval.approval_id)

    def test_second_proposal_cannot_create_competing_task_approval(self) -> None:
        fixture, first = self._approved()
        request_input = freeze_model3d_request_input(
            fixture.runtime, fixture.task_id, evidence_store=fixture.evidence
        )
        second_result = BoundedModel3DRequestAuthor(
            fixture.runtime,
            DeterministicModel3DRequestAuthorAdapter(_semantic_response()),
            evidence_store=fixture.evidence,
        ).propose(request_input.request_input_id)
        audit_model3d_request_proposal(
            fixture.runtime, second_result.proposal.proposal_id, evidence_store=fixture.evidence
        )
        with self.assertRaises(Model3DRequestPublicationError):
            approve_model3d_request_publication(
                fixture.runtime, second_result.proposal.proposal_id
            )
        self.assertEqual(
            read_model3d_request_approval(fixture.runtime, first.approval_id), first
        )

    def test_phase51_admission_requires_exact_current_publication(self) -> None:
        fixture, approval = self._approved()
        publication = publish_approved_model3d_request(fixture.runtime, approval.approval_id)
        self.assertEqual(
            require_current_model3d_publication(
                fixture.runtime,
                task_id=fixture.task_id,
                request_id=publication.request_id,
                request_hash=publication.request_hash,
            ),
            publication,
        )
        with self.assertRaises(Model3DRequestPublicationError):
            require_current_model3d_publication(
                fixture.runtime,
                task_id=fixture.task_id,
                request_id=publication.request_id,
                request_hash="sha256:" + "0" * 64,
            )

    def test_stale_upstream_lineage_blocks_phase51_admission(self) -> None:
        fixture, approval = self._approved()
        publication = publish_approved_model3d_request(fixture.runtime, approval.approval_id)
        fixture.runtime.transition_goal(fixture.goal_id, GoalStatus.ACTIVE, expected_revision=0)
        with self.assertRaisesRegex(Model3DRequestPublicationError, "historical"):
            require_current_model3d_publication(
                fixture.runtime,
                task_id=fixture.task_id,
                request_id=publication.request_id,
                request_hash=publication.request_hash,
            )


if __name__ == "__main__":
    unittest.main()
