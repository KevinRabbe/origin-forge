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
    return _bounded(decorate_overview(_render_classic_overview(snapshot), snapshot))


def render_detail(
    snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str
) -> str:
    return _bounded(
        decorate_detail(
            _render_classic_detail(snapshot, kind, object_id),
            kind=kind,
            object_id=object_id,
        )
    )
