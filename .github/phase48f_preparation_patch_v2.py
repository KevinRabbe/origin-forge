from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"required Phase 48F patch anchor missing: {old[:80]!r}")
    return text.replace(old, new, 1)


path = Path("src/origin_forge/production_preparation_planner_boundary.py")
text = path.read_text()
text = replace_once(
    text,
    "from dataclasses import dataclass\n\nfrom .production_capability_routing import (",
    "from dataclasses import dataclass\n\nfrom .ids import IdKind, validate_id\nfrom .production_capability_routing import (",
)
text = replace_once(
    text,
    "from .production_work_order_models import DispatchContractCatalog\n",
    "from .production_work_order_models import (\n"
    "    DispatchContract,\n"
    "    DispatchContractCatalog,\n"
    "    WorkOrderInputRef,\n"
    "    WorkOrderRefType,\n"
    ")\n",
)
text = replace_once(
    text,
    "class PreparationPlannerBoundaryError(RuntimeError):\n"
    "    pass\n\n\n"
    "@dataclass(frozen=True)\n"
    "class RoutedPreparationPlannerBoundary:\n",
    '''class PreparationPlannerBoundaryError(RuntimeError):
    pass


_PIXELORAMA_PREPARATION_OWNER_ID = (
    "originforge.preparation.pixelorama-spritesheet-export-planner@1"
)
_PIXELORAMA_PROJECT_ROLE = "pixelorama_project"


def _planner_allowed_input_refs(
    planning_input,
    owner_id: str,
    contract: DispatchContract,
) -> tuple[WorkOrderInputRef, ...]:
    """Project frozen PlanningInput evidence into owner-specific WorkOrder choices."""

    if owner_id == _PIXELORAMA_PREPARATION_OWNER_ID:
        if (
            contract.max_input_refs != 1
            or contract.allowed_input_ref_types != (WorkOrderRefType.ARTIFACT,)
        ):
            raise PreparationPlannerBoundaryError(
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
        return tuple(
            sorted(
                refs,
                key=lambda value: (value.ref_id, value.content_hash, value.role),
            )
        )
    if contract.max_input_refs != 0:
        raise PreparationPlannerBoundaryError(
            "current dispatch contract exceeds exact v1 preparation-owner authority"
        )
    return ()


@dataclass(frozen=True)
class RoutedPreparationPlannerBoundary:
''',
)
text = replace_once(
    text,
    "    dependencies: PreparationPlannerDependencies\n"
    "    dispatch_catalog: DispatchContractCatalog\n",
    "    dependencies: PreparationPlannerDependencies\n"
    "    dispatch_catalog: DispatchContractCatalog\n"
    "    allowed_input_refs: tuple[WorkOrderInputRef, ...] = ()\n",
)
text = replace_once(
    text,
    "            or contract.content_hash != owner.supported_dispatch_contract_hash\n"
    "            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint\n"
    "            or contract.max_input_refs != 0\n"
    "        ):\n"
    "            raise PreparationPlannerBoundaryError(\n"
    "                \"current dispatch contract exceeds exact v1 preparation-owner authority\"\n"
    "            )\n",
    "            or contract.content_hash != owner.supported_dispatch_contract_hash\n"
    "            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint\n"
    "        ):\n"
    "            raise PreparationPlannerBoundaryError(\n"
    "                \"current dispatch contract exceeds exact v1 preparation-owner authority\"\n"
    "            )\n"
    "        allowed_input_refs = _planner_allowed_input_refs(\n"
    "            provenance.planning_input,\n"
    "            owner.owner_id,\n"
    "            contract,\n"
    "        )\n",
)
text = replace_once(
    text,
    "        dependencies=dependencies,\n"
    "        dispatch_catalog=dispatch_catalog,\n"
    "    )",
    "        dependencies=dependencies,\n"
    "        dispatch_catalog=dispatch_catalog,\n"
    "        allowed_input_refs=allowed_input_refs,\n"
    "    )",
)
path.write_text(text)

path = Path("src/origin_forge/production_preparation_planner_same_call.py")
text = path.read_text()
text = replace_once(
    text,
    "from .production_preparation_planner_boundary import (\n"
    "    PreparationPlannerBoundaryError,\n"
    "    RoutedPreparationPlannerBoundary,\n"
    ")\n",
    "from .production_preparation_planner_boundary import (\n"
    "    PreparationPlannerBoundaryError,\n"
    "    RoutedPreparationPlannerBoundary,\n"
    "    _planner_allowed_input_refs,\n"
    ")\n",
)
text = replace_once(
    text,
    "            or contract.content_hash != owner.supported_dispatch_contract_hash\n"
    "            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint\n"
    "            or contract.max_input_refs != 0\n"
    "        ):\n"
    "            raise PreparationPlannerBoundaryError(\n"
    "                \"current dispatch contract exceeds exact v1 preparation-owner authority\"\n"
    "            )\n",
    "            or contract.content_hash != owner.supported_dispatch_contract_hash\n"
    "            or contract.adapter_fingerprint != owner.supported_adapter_fingerprint\n"
    "        ):\n"
    "            raise PreparationPlannerBoundaryError(\n"
    "                \"current dispatch contract exceeds exact v1 preparation-owner authority\"\n"
    "            )\n"
    "        allowed_input_refs = _planner_allowed_input_refs(\n"
    "            provenance.planning_input,\n"
    "            owner.owner_id,\n"
    "            contract,\n"
    "        )\n",
)
text = replace_once(
    text,
    "        dependencies=dependencies,\n"
    "        dispatch_catalog=dispatch_catalog,\n"
    "    )",
    "        dependencies=dependencies,\n"
    "        dispatch_catalog=dispatch_catalog,\n"
    "        allowed_input_refs=allowed_input_refs,\n"
    "    )",
)
path.write_text(text)

path = Path("src/origin_forge/production_preparation_planner_resume.py")
text = path.read_text()
text = replace_once(
    text,
    "        planner_result = planner.propose(\n"
    "            started.route_decision_id,\n"
    "            allowed_input_refs=(),\n"
    "        )\n",
    "        planner_result = planner.propose(\n"
    "            started.route_decision_id,\n"
    "            allowed_input_refs=boundary.allowed_input_refs,\n"
    "        )\n",
)
path.write_text(text)
