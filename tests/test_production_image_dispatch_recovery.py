from __future__ import annotations

import unittest
from unittest.mock import patch

from origin_forge.ids import IdKind, new_id
from origin_forge.production_dispatch_execution_models import (
    DispatchExecution,
    DispatchExecutionStatus,
)
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationRecoveryRequired,
)
from origin_forge.production_dispatch_invocation_image_owner import (
    recover_image_dispatch_execution_once,
)
from origin_forge.production_image_dispatch_output_binding import (
    ImageDispatchOutputBindingError,
)
from origin_forge.production_image_dispatch_output_binding_models import (
    ImageDispatchOutput,
    ImageDispatchOutputBinding,
)


def _execution(status: DispatchExecutionStatus) -> DispatchExecution:
    return DispatchExecution(
        execution_id=new_id(IdKind.DISPATCH_EXECUTION),
        project_id=new_id(IdKind.PROJECT),
        claim_id=new_id(IdKind.DISPATCH_CLAIM),
        claim_revision_at_start=2,
        task_id=new_id(IdKind.TASK),
        task_revision=3,
        task_content_hash="a" * 64,
        work_order_id=new_id(IdKind.PRODUCTION_WORK_ORDER),
        work_order_hash="b" * 64,
        input_resolution_id=new_id(IdKind.INPUT_RESOLUTION_BUNDLE),
        input_resolution_hash="c" * 64,
        dispatch_binding_id=new_id(IdKind.DISPATCH_BINDING),
        dispatch_binding_hash="d" * 64,
        binding_audit_id=new_id(IdKind.DISPATCH_BINDING_AUDIT),
        binding_audit_hash="e" * 64,
        selected_adapter_id="originforge.image.generate",
        selected_adapter_fingerprint="f" * 64,
        dispatch_contract_id="image.generate@1",
        dispatch_contract_hash="1" * 64,
        binder_id="binder.image.generate@1",
        binder_fingerprint="2" * 64,
        execution_owner_id="originforge.execution.image.generate@1",
        execution_owner_fingerprint="3" * 64,
        runtime_dependency_plan_hash="4" * 64,
        status=status,
        revision=1 if status is not DispatchExecutionStatus.STARTED else 0,
        created_at="2026-08-26T00:00:00Z",
        updated_at="2026-08-26T00:00:01Z",
        terminal_detail_hash="5" * 64 if status is not DispatchExecutionStatus.STARTED else None,
    )


def _binding(execution: DispatchExecution) -> ImageDispatchOutputBinding:
    return ImageDispatchOutputBinding(
        execution_id=execution.execution_id,
        claim_id=execution.claim_id,
        task_id=execution.task_id,
        task_revision=execution.task_revision,
        task_content_hash=execution.task_content_hash,
        work_order_id=execution.work_order_id,
        work_order_hash=execution.work_order_hash,
        dispatch_binding_id=execution.dispatch_binding_id,
        dispatch_binding_hash=execution.dispatch_binding_hash,
        execution_owner_id=execution.execution_owner_id,
        run_id=new_id(IdKind.RUN),
        request_artifact_id=new_id(IdKind.ARTIFACT),
        result_artifact_id=new_id(IdKind.ARTIFACT),
        outputs=(
            ImageDispatchOutput(
                "exports/robot.png",
                new_id(IdKind.ARTIFACT),
                new_id(IdKind.VERIFICATION),
                "6" * 64,
                "7" * 64,
                32,
                32,
                1024,
            ),
        ),
        backend_result_hash="8" * 64,
        schema_version=1,
        created_at="2026-08-26T00:00:02Z",
    )


class ImageDispatchRecoveryTests(unittest.TestCase):
    def test_returned_binding_materializes_without_adapter_or_backend(self) -> None:
        execution = _execution(DispatchExecutionStatus.RETURNED)
        binding = _binding(execution)
        with (
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_dispatch_execution",
                return_value=execution,
            ),
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_image_dispatch_output_binding",
                return_value=binding,
            ),
        ):
            recovered = recover_image_dispatch_execution_once(
                object(), execution.execution_id
            )
        self.assertEqual(recovered.execution, execution)
        self.assertEqual(recovered.image_result.run_id, binding.run_id)
        self.assertEqual(recovered.image_result.outputs[0].artifact_id, binding.outputs[0].artifact_id)

    def test_missing_binding_fails_closed_without_replay(self) -> None:
        execution = _execution(DispatchExecutionStatus.STARTED)
        with (
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_dispatch_execution",
                return_value=execution,
            ),
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_image_dispatch_output_binding",
                side_effect=ImageDispatchOutputBindingError("missing"),
            ),
        ):
            with self.assertRaises(ProductionDispatchInvocationRecoveryRequired):
                recover_image_dispatch_execution_once(object(), execution.execution_id)

    def test_started_execution_with_binding_is_terminalized_without_reinvocation(self) -> None:
        execution = _execution(DispatchExecutionStatus.STARTED)
        binding = _binding(execution)
        returned = _execution(DispatchExecutionStatus.RETURNED)
        returned = DispatchExecution(
            **{
                **returned.__dict__,
                "execution_id": execution.execution_id,
                "project_id": execution.project_id,
                "claim_id": execution.claim_id,
                "task_id": execution.task_id,
                "work_order_id": execution.work_order_id,
                "input_resolution_id": execution.input_resolution_id,
                "dispatch_binding_id": execution.dispatch_binding_id,
                "binding_audit_id": execution.binding_audit_id,
            }
        )
        with (
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_dispatch_execution",
                return_value=execution,
            ),
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.read_image_dispatch_output_binding",
                return_value=binding,
            ),
            patch(
                "origin_forge.production_dispatch_invocation_image_owner._require_started_image_authority",
            ),
            patch(
                "origin_forge.production_dispatch_invocation_image_owner.mark_dispatch_execution_returned",
                return_value=returned,
            ) as terminalize,
        ):
            recovered = recover_image_dispatch_execution_once(
                object(), execution.execution_id
            )
        terminalize.assert_called_once()
        self.assertEqual(recovered.execution.status, DispatchExecutionStatus.RETURNED)
        self.assertEqual(recovered.image_result.run_id, binding.run_id)
