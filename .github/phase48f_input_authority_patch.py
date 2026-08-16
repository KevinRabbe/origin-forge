from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing {label} anchor")
    return text.replace(old, new, 1)


# Boundary: consume the shared pure input-authority helper instead of owning it.
path = Path("src/origin_forge/production_preparation_planner_boundary.py")
text = path.read_text()
text = replace_once(
    text,
    "from .ids import IdKind, validate_id\n",
    "",
    "boundary ids import",
)
text = replace_once(
    text,
    "from .production_preparation_models import (\n",
    "from .production_preparation_input_authority import (\n"
    "    PreparationInputAuthorityError,\n"
    "    planner_allowed_input_refs,\n"
    ")\n"
    "from .production_preparation_models import (\n",
    "boundary helper import",
)
text = replace_once(
    text,
    "from .production_work_order_models import (\n"
    "    DispatchContract,\n"
    "    DispatchContractCatalog,\n"
    "    WorkOrderInputRef,\n"
    "    WorkOrderRefType,\n"
    ")\n",
    "from .production_work_order_models import DispatchContractCatalog, WorkOrderInputRef\n",
    "boundary work order imports",
)
start = text.index("_PIXELORAMA_PREPARATION_OWNER_ID = (")
end = text.index("@dataclass(frozen=True)\nclass RoutedPreparationPlannerBoundary:")
text = text[:start] + text[end:]
text = text.replace("_planner_allowed_input_refs(\n", "planner_allowed_input_refs(\n")
text = replace_once(
    text,
    "        ProductionPreparationProvenanceError,\n",
    "        ProductionPreparationProvenanceError,\n"
    "        PreparationInputAuthorityError,\n",
    "boundary catch",
)
path.write_text(text)


# Same-call boundary: import the shared helper/error directly.
path = Path("src/origin_forge/production_preparation_planner_same_call.py")
text = path.read_text()
text = replace_once(
    text,
    "from .production_preparation_models import (\n",
    "from .production_preparation_input_authority import (\n"
    "    PreparationInputAuthorityError,\n"
    "    planner_allowed_input_refs,\n"
    ")\n"
    "from .production_preparation_models import (\n",
    "same call helper import",
)
text = replace_once(
    text,
    "from .production_preparation_planner_boundary import (\n"
    "    PreparationPlannerBoundaryError,\n"
    "    RoutedPreparationPlannerBoundary,\n"
    "    _planner_allowed_input_refs,\n"
    ")\n",
    "from .production_preparation_planner_boundary import (\n"
    "    PreparationPlannerBoundaryError,\n"
    "    RoutedPreparationPlannerBoundary,\n"
    ")\n",
    "same call boundary imports",
)
text = text.replace("_planner_allowed_input_refs(\n", "planner_allowed_input_refs(\n")
text = replace_once(
    text,
    "        ProductionPreparationAssemblyError,\n",
    "        ProductionPreparationAssemblyError,\n"
    "        PreparationInputAuthorityError,\n",
    "same call catch",
)
path.write_text(text)


# Planner-return checkpoint: revalidate returned WorkOrder refs against the same
# frozen PlanningInput/PREPPOL owner authority rather than hard-coding zero refs.
path = Path("src/origin_forge/production_preparation_receipts.py")
text = path.read_text()
text = replace_once(
    text,
    "from .production_preparation_models import (\n",
    "from .production_preparation_input_authority import (\n"
    "    PreparationInputAuthorityError,\n"
    "    work_order_input_refs_within_authority,\n"
    ")\n"
    "from .production_preparation_models import (\n",
    "receipts helper import",
)
old = '''    if (
        work_order.dispatch_catalog_id != policy.dispatch_contract_catalog_id
        or work_order.dispatch_catalog_hash != policy.dispatch_contract_catalog_hash
        or work_order.dispatch_contract_id != contract.contract_id
        or work_order.dispatch_contract_hash != contract.content_hash
        or work_order.selected_adapter_id != resolution.selected_adapter_id
        or work_order.selected_adapter_fingerprint
        != resolution.selected_adapter_fingerprint
        or work_order.input_refs
    ):
        raise PreparationReceiptError(
            "planner WorkOrder exceeds exact PREPPOL route/dispatch authority"
        )
'''
new = '''    try:
        inputs_current = work_order_input_refs_within_authority(
            work_order.input_refs,
            planning_input=provenance.planning_input,
            owner_id=policy.preparation_owner_id,
            contract=contract,
        )
    except (PreparationInputAuthorityError, TypeError, ValueError) as exc:
        raise PreparationReceiptError(
            "planner WorkOrder input authority cannot be revalidated"
        ) from exc
    if (
        work_order.dispatch_catalog_id != policy.dispatch_contract_catalog_id
        or work_order.dispatch_catalog_hash != policy.dispatch_contract_catalog_hash
        or work_order.dispatch_contract_id != contract.contract_id
        or work_order.dispatch_contract_hash != contract.content_hash
        or work_order.selected_adapter_id != resolution.selected_adapter_id
        or work_order.selected_adapter_fingerprint
        != resolution.selected_adapter_fingerprint
        or not inputs_current
    ):
        raise PreparationReceiptError(
            "planner WorkOrder exceeds exact PREPPOL route/dispatch authority"
        )
'''
text = replace_once(text, old, new, "planner return input authority")
path.write_text(text)
