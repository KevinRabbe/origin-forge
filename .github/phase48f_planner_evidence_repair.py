from pathlib import Path

path = Path("src/origin_forge/production_preparation_planner_evidence.py")
text = path.read_text(encoding="utf-8")

old_import = """from .production_work_order_models import (
    ProductionWorkOrderModelError,
    content_hash,
)
"""
new_import = """from .production_work_order_models import (
    ProductionWorkOrderModelError,
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
"""
if text.count(old_import) != 1:
    raise SystemExit(f"expected one work-order-model import block, found {text.count(old_import)}")
text = text.replace(old_import, new_import, 1)

start_marker = "def _work_order_from_evidence(value: object) -> ProductionWorkOrder:\n"
end_marker = "\n\ndef _row_to_result(\n"
start = text.index(start_marker)
end = text.index(end_marker, start)
new_func = '''def _work_order_from_evidence(value: object) -> ProductionWorkOrder:
    if not isinstance(value, dict) or set(value) != _WORK_ORDER_KEYS:
        raise PreparationPlannerEvidenceError("planner WorkOrder schema drifted")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise PreparationPlannerEvidenceError("planner WorkOrder payload is invalid")

    raw_refs = value["input_refs"]
    if not isinstance(raw_refs, list):
        raise PreparationPlannerEvidenceError("planner WorkOrder input refs are not a list")
    if (
        value["selected_adapter_id"] == "originforge.pixelorama.export"
        and value["dispatch_contract_id"] == "pixelorama.spritesheet-export@1"
    ):
        if len(raw_refs) != 1 or not isinstance(raw_refs[0], dict):
            raise PreparationPlannerEvidenceError(
                "Pixelorama planner WorkOrder requires exactly one input ref"
            )
        raw_ref = raw_refs[0]
        if set(raw_ref) != {"ref_type", "ref_id", "content_hash", "role", "revision"}:
            raise PreparationPlannerEvidenceError(
                "Pixelorama planner WorkOrder input ref schema drifted"
            )
        try:
            refs = (
                WorkOrderInputRef(
                    ref_type=WorkOrderRefType(raw_ref["ref_type"]),
                    ref_id=raw_ref["ref_id"],
                    content_hash=raw_ref["content_hash"],
                    role=raw_ref["role"],
                    revision=raw_ref["revision"],
                ),
            )
        except (ProductionWorkOrderModelError, TypeError, ValueError) as exc:
            raise PreparationPlannerEvidenceError(
                "Pixelorama planner WorkOrder input ref failed reconstruction"
            ) from exc
        ref = refs[0]
        if (
            ref.ref_type is not WorkOrderRefType.ARTIFACT
            or ref.role != "pixelorama_project"
            or ref.revision is not None
        ):
            raise PreparationPlannerEvidenceError(
                "Pixelorama planner WorkOrder input ref authority drifted"
            )
    else:
        if raw_refs != []:
            raise PreparationPlannerEvidenceError(
                "non-Pixelorama planner evidence may not contain WorkOrder input refs"
            )
        refs = ()

    try:
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        work_order = ProductionWorkOrder(
            work_order_id=value["work_order_id"],
            task_id=value["task_id"],
            task_revision=value["task_revision"],
            task_content_hash=value["task_content_hash"],
            flow_id=value["flow_id"],
            route_decision_id=value["route_decision_id"],
            route_decision_hash=value["route_decision_hash"],
            selected_adapter_id=value["selected_adapter_id"],
            selected_adapter_fingerprint=value["selected_adapter_fingerprint"],
            dispatch_catalog_id=value["dispatch_catalog_id"],
            dispatch_catalog_hash=value["dispatch_catalog_hash"],
            dispatch_contract_id=value["dispatch_contract_id"],
            dispatch_contract_hash=value["dispatch_contract_hash"],
            input_refs=refs,
            payload_json=payload_json,
        )
    except (
        ProductionWorkOrderError,
        ProductionWorkOrderModelError,
        TypeError,
        ValueError,
    ) as exc:
        raise PreparationPlannerEvidenceError(
            "planner WorkOrder failed exact contract reconstruction"
        ) from exc
    if work_order.to_dict() != value:
        raise PreparationPlannerEvidenceError(
            "planner WorkOrder derived fields do not reconstruct exactly"
        )
    return work_order
'''
text = text[:start] + new_func + text[end:]

legacy_metric = '        or metrics["allowed_input_refs"] != 0\n'
if text.count(legacy_metric) != 1:
    raise SystemExit(f"expected one legacy allowed_input_refs check, found {text.count(legacy_metric)}")
text = text.replace(legacy_metric, "", 1)

old_bind = """    work_order = _work_order_from_evidence(evidence["work_order"])
    if (
        work_order.work_order_id != evidence["work_order_id"]
"""
new_bind = """    work_order = _work_order_from_evidence(evidence["work_order"])
    if (
        metrics["allowed_input_refs"] != len(work_order.input_refs)
        or work_order.work_order_id != evidence["work_order_id"]
"""
if text.count(old_bind) != 1:
    raise SystemExit(f"expected one WorkOrder evidence binding block, found {text.count(old_bind)}")
text = text.replace(old_bind, new_bind, 1)

path.write_text(text, encoding="utf-8")
