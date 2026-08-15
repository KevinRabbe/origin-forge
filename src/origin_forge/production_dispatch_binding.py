from __future__ import annotations

# Phase 47B keeps the accepted Phase-34 implementation byte-identical in the
# internal core module and narrows this public compatibility surface to the one
# authority expansion required here: one additional reviewed simulation binder.
from .production_dispatch_binding_core import *  # noqa: F401,F403
from .production_dispatch_binding_core import (
    CodeBoundedRetryInputBinder,
    DispatchInputBinder,
    DispatchInputBinderRegistry,
    _binding_with_id,
    _frozen_binding_audit_matches,
)
from .production_dispatch_binding_simulation import DeterministicSimulationInputBinder


def builtin_dispatch_binders() -> tuple[DispatchInputBinder, ...]:
    """Return exactly the two reviewed Phase-47 production input binders."""

    return (
        CodeBoundedRetryInputBinder(),
        DeterministicSimulationInputBinder(),
    )


def build_builtin_dispatch_binder_registry() -> DispatchInputBinderRegistry:
    return DispatchInputBinderRegistry(builtin_dispatch_binders())
