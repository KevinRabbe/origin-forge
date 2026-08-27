from __future__ import annotations

from .production_capability_builtin import builtin_trusted_production_adapters
from .production_dispatch_binding_playtest import CooperativePlaytestInputBinder
from .production_execution_owner import (
    ProductionExecutionOwnerDescriptor,
    ProductionExecutionOwnerError,
)
from .production_work_order_playtest import PLAYTEST_ADAPTER_ID, PLAYTEST_CONTRACT_ID

PLAYTEST_EXECUTION_OWNER_ID = "originforge.execution.playtest.cooperative@1"


def cooperative_playtest_execution_owner_descriptor() -> (
    ProductionExecutionOwnerDescriptor
):
    adapter = next(
        (
            value
            for value in builtin_trusted_production_adapters()
            if value.adapter_id == PLAYTEST_ADAPTER_ID
        ),
        None,
    )
    if adapter is None:
        raise ProductionExecutionOwnerError(
            "built-in capability inventory lacks playtest adapter"
        )
    binder = CooperativePlaytestInputBinder().descriptor
    if (
        binder.adapter_id != adapter.adapter_id
        or binder.dispatch_contract_id != PLAYTEST_CONTRACT_ID
    ):
        raise ProductionExecutionOwnerError("built-in playtest binder relation drifted")
    return ProductionExecutionOwnerDescriptor(
        owner_id=PLAYTEST_EXECUTION_OWNER_ID,
        owner_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        dispatch_contract_id=binder.dispatch_contract_id,
        binder_id=binder.binder_id,
        binder_fingerprint=binder.binder_fingerprint,
        request_type_id=binder.request_type_id,
        request_schema_hash=binder.request_schema_hash,
        model_strategy_roles=(),
        requires_sandbox=False,
        requires_workspace_manager=False,
    )
