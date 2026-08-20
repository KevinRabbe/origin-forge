from __future__ import annotations

from collections.abc import Sequence

from .ids import IdKind, validate_id
from .production_planning_models import PlanningInput
from .production_work_order_models import (
    DispatchContract,
    WorkOrderInputRef,
    WorkOrderRefType,
)


class PreparationInputAuthorityError(RuntimeError):
    pass


_PIXELORAMA_PREPARATION_OWNER_ID = (
    "originforge.preparation.pixelorama-spritesheet-export-planner@1"
)
_PIXELORAMA_PROJECT_ROLE = "pixelorama_project"
_BLENDER_PREPARATION_OWNER_ID = "originforge.preparation.blender-export-glb@1"
_BLENDER_MODEL3D_REQUEST_ROLE = "model3d_request"


def planner_allowed_input_refs(
    planning_input: PlanningInput,
    owner_id: str,
    contract: DispatchContract,
) -> tuple[WorkOrderInputRef, ...]:
    """Project only frozen PlanningInput evidence into owner-specific ref choices."""

    if not isinstance(planning_input, PlanningInput):
        raise TypeError("planning_input must be a PlanningInput")
    if not isinstance(owner_id, str):
        raise TypeError("owner_id must be a string")
    if not isinstance(contract, DispatchContract):
        raise TypeError("contract must be a DispatchContract")

    if owner_id == _PIXELORAMA_PREPARATION_OWNER_ID:
        if (
            contract.max_input_refs != 1
            or contract.allowed_input_ref_types != (WorkOrderRefType.ARTIFACT,)
        ):
            raise PreparationInputAuthorityError(
                "Pixelorama preparation owner contract input authority drifted"
            )
        refs = tuple(
            WorkOrderInputRef(
                ref_type=WorkOrderRefType.ARTIFACT,
                ref_id=value.ref_id,
                content_hash=value.content_hash,
                role=_PIXELORAMA_PROJECT_ROLE,
                revision=None,
            )
            for value in planning_input.verified_state_refs
            if value.revision is None and validate_id(value.ref_id, IdKind.ARTIFACT)
        )
        refs = tuple(
            sorted(
                refs,
                key=lambda value: (value.ref_id, value.content_hash, value.role),
            )
        )
        if not refs:
            raise PreparationInputAuthorityError(
                "Pixelorama preparation requires frozen Artifact evidence in PlanningInput"
            )
        return refs

    if owner_id == _BLENDER_PREPARATION_OWNER_ID:
        if (
            contract.max_input_refs != 1
            or contract.allowed_input_ref_types != (WorkOrderRefType.MODEL3D_REQUEST,)
        ):
            raise PreparationInputAuthorityError(
                "Blender preparation owner contract input authority drifted"
            )
        refs = tuple(
            WorkOrderInputRef(
                ref_type=WorkOrderRefType.MODEL3D_REQUEST,
                ref_id=value.ref_id,
                content_hash=value.content_hash,
                role=_BLENDER_MODEL3D_REQUEST_ROLE,
                revision=None,
            )
            for value in planning_input.verified_state_refs
            if value.revision is None
            and validate_id(value.ref_id, IdKind.MODEL3D_REQUEST)
        )
        refs = tuple(
            sorted(
                refs,
                key=lambda value: (value.ref_id, value.content_hash, value.role),
            )
        )
        if not refs:
            raise PreparationInputAuthorityError(
                "Blender preparation requires frozen MODEL3D request evidence in PlanningInput"
            )
        return refs

    if contract.max_input_refs != 0:
        raise PreparationInputAuthorityError(
            "current dispatch contract exceeds exact v1 preparation-owner authority"
        )
    return ()


def work_order_input_refs_within_authority(
    input_refs: Sequence[WorkOrderInputRef],
    *,
    planning_input: PlanningInput,
    owner_id: str,
    contract: DispatchContract,
) -> bool:
    """Revalidate returned WorkOrder refs against the same frozen planner authority."""

    refs = tuple(input_refs)
    if any(not isinstance(value, WorkOrderInputRef) for value in refs):
        return False
    allowed = planner_allowed_input_refs(planning_input, owner_id, contract)
    if owner_id in (
        _PIXELORAMA_PREPARATION_OWNER_ID,
        _BLENDER_PREPARATION_OWNER_ID,
    ):
        return len(refs) == 1 and refs[0] in allowed
    return refs == () and allowed == ()
