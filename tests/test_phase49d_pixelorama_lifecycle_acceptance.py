from __future__ import annotations

import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import test_phase49b_pixelorama_output_recovery as phase49b
from origin_forge.pixelorama_admin_cli import main as pixelorama_admin_main
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_claim_read import read_dispatch_claim
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_pixelorama_adoption_receipt import (
    PixeloramaProductionAdoptionReceiptError,
    read_pixelorama_production_adoption_receipt,
)
from origin_forge.production_pixelorama_dispatch_output_binding_read import (
    read_pixelorama_dispatch_output_binding,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService


class Phase49DPixeloramaLifecycleAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = phase49b.Phase49BPixeloramaOutputRecoveryTests(
            methodName=(
                "test_bound_started_execution_repairs_returned_without_second_owner_call"
            )
        )
        self.harness.setUp()

    def tearDown(self) -> None:
        self.harness.tearDown()

    def _cli(self, execution_id: str) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            code = pixelorama_admin_main(
                [
                    "--project-root",
                    str(self.harness.fixture.runtime.project_root),
                    "adopt-production-new",
                    execution_id,
                    "assets/nonterminal.png",
                ]
            )
        return code, json.loads(output.getvalue())

    def test_started_bound_output_with_active_claim_is_non_authorizing_and_never_replayed(self) -> None:
        fixture = self.harness.fixture
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
        execution_id = caught.exception.execution_id
        binding = read_pixelorama_dispatch_output_binding(fixture.runtime, execution_id)
        self.assertEqual(binding.execution_id, execution_id)
        self.assertEqual(fixture._execution()["status"], DispatchExecutionStatus.STARTED.value)
        self.assertEqual(
            read_dispatch_claim(fixture.runtime, fixture.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )

        with patch.object(
            PixeloramaCliExportService,
            "execute",
            autospec=True,
        ) as replay:
            code, payload = self._cli(execution_id)
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(code, 2)
        self.assertIn("EXECUTION_NOT_RETURNED", str(payload["detail"]))
        self.assertFalse((fixture.runtime.project_root / "assets/nonterminal.png").exists())
        with self.assertRaises(PixeloramaProductionAdoptionReceiptError):
            read_pixelorama_production_adoption_receipt(fixture.runtime, execution_id)
        self.assertEqual(fixture._execution()["status"], DispatchExecutionStatus.STARTED.value)
        self.assertEqual(
            read_dispatch_claim(fixture.runtime, fixture.claim.claim_id).status,
            DispatchClaimStatus.ACTIVE,
        )


if __name__ == "__main__":
    unittest.main()
