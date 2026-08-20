from __future__ import annotations

from .production_interface_classic import (
    ProductionInterfaceRenderError,
    render_detail as _render_classic_detail,
    render_overview as _render_classic_overview,
)
from .production_interface_snapshot import ProductionInterfaceSnapshot
from .production_interface_theme import decorate_detail, decorate_overview


_MAX_HTML_BYTES = 4 * 1024 * 1024


def _bounded(page: str) -> str:
    if len(page.encode("utf-8")) > _MAX_HTML_BYTES:
        raise ProductionInterfaceRenderError("rendered interface page exceeds byte limit")
    return page


def render_overview(snapshot: ProductionInterfaceSnapshot) -> str:
    classic = _render_classic_overview(snapshot)
    try:
        themed = decorate_overview(classic, snapshot)
    except ValueError as exc:
        raise ProductionInterfaceRenderError("cockpit theme render failed") from exc
    return _bounded(themed)


def render_detail(
    snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str
) -> str:
    classic = _render_classic_detail(snapshot, kind, object_id)
    try:
        themed = decorate_detail(classic, kind=kind, object_id=object_id)
    except ValueError as exc:
        raise ProductionInterfaceRenderError("cockpit theme render failed") from exc
    return _bounded(themed)
