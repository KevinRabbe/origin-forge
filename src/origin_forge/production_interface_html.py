from __future__ import annotations

from .production_interface_classic import (
    ProductionInterfaceRenderError,
    render_detail as _render_classic_detail,
    render_overview as _render_classic_overview,
)
from .production_interface_detail_context import decorate_detail_context
from .production_interface_lifecycle import decorate_lifecycle
from .production_interface_lineage import decorate_lineage
from .production_interface_project_tokens import decorate_project_tokens
from .production_interface_snapshot import ProductionInterfaceSnapshot
from .production_interface_task_workspace import decorate_task_workspace
from .production_interface_theme import decorate_detail, decorate_overview
from .production_interface_workspace import decorate_workspace


_MAX_HTML_BYTES = 4 * 1024 * 1024


def _bounded(page: str) -> str:
    if len(page.encode("utf-8")) > _MAX_HTML_BYTES:
        raise ProductionInterfaceRenderError("rendered interface page exceeds byte limit")
    return page


def render_overview(snapshot: ProductionInterfaceSnapshot) -> str:
    classic = _render_classic_overview(snapshot)
    try:
        themed = decorate_overview(classic, snapshot)
        themed = decorate_workspace(themed, snapshot)
        themed = decorate_project_tokens(themed, snapshot)
        themed = decorate_lifecycle(themed, snapshot)
        themed = decorate_lineage(themed, snapshot)
    except ValueError as exc:
        raise ProductionInterfaceRenderError("cockpit theme render failed") from exc
    return _bounded(themed)


def render_detail(
    snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str
) -> str:
    classic = _render_classic_detail(snapshot, kind, object_id)
    try:
        themed = decorate_detail(classic, kind=kind, object_id=object_id)
        themed = decorate_detail_context(
            themed,
            snapshot,
            kind=kind,
            object_id=object_id,
        )
        if kind.lower() == "task":
            themed = decorate_task_workspace(
                themed,
                snapshot,
                task_id=object_id,
            )
    except ValueError as exc:
        raise ProductionInterfaceRenderError("cockpit theme render failed") from exc
    return _bounded(themed)
