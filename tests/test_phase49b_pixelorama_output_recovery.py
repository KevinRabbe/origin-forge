from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from origin_forge.lineage import OriginForgeLineage
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_pixelorama import (
    recover_pixelorama_dispatch_execution_once,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    PixeloramaDispatchOutputBindingReadError,
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_dispatch_output_currentness import (
    PixeloramaDispatchOutputCurrentnessStatus,
    inspect_pixelorama_dispatch_output_currentness_readonly,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService
from .test_phase48f_pixelorama_invocation import Phase48FPixeloramaInvocationTests


class Phase49BPixeloramaOutputRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Phase48FPixeloramaInvocationTests(
            methodName=(
                "test_exact_pixelorama_owner_materializes_after_started_calls_service_once_and_returns"
            )
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _invoke_successfully(self):
        fixture = self.fixture
        fixture.original_service_execute = PixeloramaCliExportService.execute
        with patch.dict(os.environ, fixture.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=fixture._real_service_with_fake_adapter,
        ) as execute:
            completed = dispatch_claim_once(
                fixture.runtime,
                fixture.claim.claim_id,
                0,
            )
        self.assertEqual(execute.call_count, 1)
        return completed

    def test_success_binds_exact_digest_and_is_adoption_eligible(self) -> None:
        completed = self._invoke_successfully()
        binding = read_pixelorama_dispatch_output_binding(
            self.fixture.runtime,
            completed.execution_id,
        )
        lineage = OriginForgeLineage(self.fixture.runtime)
        output = lineage.get_artifact(binding.output_artifact_id)
        output_path = lineage.local_artifact_path(binding.output_artifact_id)

        self.assertEqual(output["content_hash"], "sha256:" + binding.output_content_hash)
        self.assertEqual(
            completed.pixelorama_result.operation.output_hash,
            "sha256:" + binding.output_content_hash,
        )
        self.assertEqual(output_path.stat().st_size, binding.output_byte_count)
        self.assertEqual(binding.run_id, completed.pixelorama_result.run_id)
        self.assertEqual(
            binding.output_verification_id,
            completed.pixelorama_result.output_verification_id,
        )
        self.assertEqual(
            binding.run_verification_id,
            completed.pixelorama_result.run_verification_id,
        )

        currentness = inspect_pixelorama_dispatch_output_currentness_readonly(
            self.fixture.runtime,
            completed.execution_id,
        )
        self.assertEqual(
            currentness.status,
            PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE,
        )
        self.assertFalse(currentness.production_task_verified)
        self.assertTrue(currentness.adoption_eligible)
        self.assertEqual(
            self.fixture.runtime.list_verifications("TASK", self.fixture.task_id),
            [],
        )

    def test_returned_recovery_materializes_typed_result_without_second_owner_call(self) -> None:
        completed = self._invoke_successfully()
        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as execute:
            recovered = recover_pixelorama_dispatch_execution_once(
                self.fixture.runtime,
                completed.execution_id,
            )
        self.assertEqual(execute.call_count, 0)
        self.assertEqual(recovered.execution, completed.execution)
        self.assertIsNotNone(recovered.pixelorama_result)
        self.assertEqual(
            recovered.pixelorama_result.to_dict(),
            completed.pixelorama_result.to_dict(),
        )

    def test_bound_started_execution_repairs_returned_without_second_owner_call(self) -> None:
        fixture = self.fixture
        fixture.original_service_execute = PixeloramaCliExportService.execute
        with patch.dict(os.environ, fixture.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=fixture._real_service_with_fake_adapter,
        ) as execute, patch(
            "origin_forge.production_dispatch_invocation.mark_dispatch_execution_returned",
            side_effect=RuntimeError("injected terminalization failure"),
        ):
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                dispatch_claim_once(fixture.runtime, fixture.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(caught.exception.reason_code, "RETURNED_TERMINALIZATION_FAILED")
        execution_id = caught.exception.execution_id
        self.assertEqual(
            fixture._execution()["status"],
            DispatchExecutionStatus.STARTED.value,
        )
        self.assertEqual(
            read_dispatch_claim(fixture.runtime, fixture.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )
        binding = read_pixelorama_dispatch_output_binding(fixture.runtime, execution_id)
        self.assertEqual(binding.execution_id, execution_id)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            recovered = recover_pixelorama_dispatch_execution_once(
                fixture.runtime,
                execution_id,
            )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(recovered.execution.status, DispatchExecutionStatus.RETURNED)
        self.assertIsNotNone(recovered.pixelorama_result)
        self.assertEqual(
            read_dispatch_claim(fixture.runtime, fixture.claim.claim_id).status,
            DispatchClaimStatus.CONSUMED,
        )
        self.assertEqual(
            inspect_pixelorama_dispatch_output_currentness_readonly(
                fixture.runtime,
                execution_id,
            ).status,
            PixeloramaDispatchOutputCurrentnessStatus.ELIGIBLE,
        )

    def test_started_without_binding_requires_recovery_and_never_replays_owner(self) -> None:
        fixture = self.fixture
        with patch.dict(os.environ, fixture.env, clear=False), patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
            side_effect=KeyboardInterrupt(),
        ) as execute:
            with self.assertRaises(KeyboardInterrupt):
                dispatch_claim_once(fixture.runtime, fixture.claim.claim_id, 0)
        self.assertEqual(execute.call_count, 1)
        execution_id = fixture._execution()["execution_id"]
        with self.assertRaises(PixeloramaDispatchOutputBindingReadError):
            read_pixelorama_dispatch_output_binding(fixture.runtime, execution_id)

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
                recover_pixelorama_dispatch_execution_once(
                    fixture.runtime,
                    execution_id,
                )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")
        self.assertEqual(
            fixture._execution()["status"],
            DispatchExecutionStatus.STARTED.value,
        )

    def test_output_byte_tamper_revokes_eligibility_and_recovery(self) -> None:
        completed = self._invoke_successfully()
        binding = read_pixelorama_dispatch_output_binding(
            self.fixture.runtime,
            completed.execution_id,
        )
        output_path = OriginForgeLineage(self.fixture.runtime).local_artifact_path(
            binding.output_artifact_id
        )
        output_path.write_bytes(b"tampered-output")

        currentness = inspect_pixelorama_dispatch_output_currentness_readonly(
            self.fixture.runtime,
            completed.execution_id,
        )
        self.assertEqual(
            currentness.status,
            PixeloramaDispatchOutputCurrentnessStatus.INVALID_EVIDENCE,
        )
        self.assertFalse(currentness.production_task_verified)
        self.assertFalse(currentness.adoption_eligible)
        with self.assertRaises(ProductionDispatchInvocationRecoveryRequired) as caught:
            recover_pixelorama_dispatch_execution_once(
                self.fixture.runtime,
                completed.execution_id,
            )
        self.assertEqual(caught.exception.reason_code, "OWNER_RETURN_CONTRACT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
