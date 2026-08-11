from __future__ import annotations

from html import escape
from typing import Iterable, Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot


_MAX_HTML_BYTES = 4 * 1024 * 1024


class ProductionInterfaceRenderError(ValueError):
    pass


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _page(title: str, body: str) -> str:
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
        "script-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; "
        "base-uri 'none'; object-src 'none'\">"
        f"<title>{_e(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #aaa;padding:.4rem;vertical-align:top;text-align:left}"
        "code{overflow-wrap:anywhere}.muted{opacity:.7}.warn{font-weight:700}nav a{margin-right:1rem}</style>"
        "</head><body><nav><a href=\"/\">Overview</a><a href=\"/api/snapshot\">Snapshot JSON</a></nav>"
        f"{body}</body></html>"
    )
    if len(document.encode("utf-8")) > _MAX_HTML_BYTES:
        raise ProductionInterfaceRenderError("rendered interface page exceeds byte limit")
    return document


def _table(headers: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> str:
    head = "".join(f"<th>{_e(value)}</th>" for value in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{_e(value)}</td>" for value in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _linked_id(kind: str, object_id: object) -> str:
    return f'<a href="/{_e(kind)}/{_e(object_id)}"><code>{_e(object_id)}</code></a>'


def _linked_table(headers: tuple[str, ...], rows: Iterable[tuple[str, object, tuple[object, ...]]]) -> str:
    head = "".join(f"<th>{_e(value)}</th>" for value in headers)
    body = []
    for kind, object_id, rest in rows:
        cells = [f"<td>{_linked_id(kind, object_id)}</td>"]
        cells.extend(f"<td>{_e(value)}</td>" for value in rest)
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_overview(snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    body = [
        "<h1>Origin Forge Production Cockpit</h1>",
        f"<p>Project <code>{_e(snapshot.project_id)}</code></p>",
        f"<p>Snapshot <code>{_e(snapshot.content_hash)}</code></p>",
        "<p class=\"muted\">Read-only projection. Visible evidence does not grant mutation or verification authority.</p>",
    ]
    if any(snapshot.truncated.values()):
        body.append("<p class=\"warn\">One or more sections are truncated by interface limits.</p>")

    body.append("<h2>Goals</h2>")
    body.append(
        _linked_table(
            ("ID", "Status", "Objective"),
            (("goal", row["id"], (row["status"], row["objective"])) for row in snapshot.goals),
        )
    )
    body.append("<h2>Flows</h2>")
    body.append(
        _linked_table(
            ("ID", "Goal", "Status", "Controller"),
            (("flow", row["id"], (row["goal_id"], row["status"], row["controller"])) for row in snapshot.flows),
        )
    )
    body.append("<h2>Tasks</h2>")
    body.append(
        _linked_table(
            ("ID", "Flow", "Status", "Objective"),
            (("task", row["id"], (row["flow_id"], row["status"], row["objective"])) for row in snapshot.tasks),
        )
    )
    body.append("<h2>Runs</h2>")
    body.append(
        _linked_table(
            ("ID", "Task", "Role", "Status", "Model"),
            (("run", row["id"], (row["task_id"], row["role"], row["status"], row["model_profile"])) for row in snapshot.runs),
        )
    )
    body.append("<h2>Task Verifications</h2>")
    body.append(
        _linked_table(
            ("ID", "Target", "Type", "Status", "Verifier"),
            (("verification", row["id"], (row["target_id"], row["verification_type"], row["status"], row["verifier"])) for row in snapshot.task_verifications),
        )
    )
    return _page("Origin Forge Production Cockpit", "".join(body))


def _find(rows: Iterable[Mapping[str, object]], object_id: str) -> Mapping[str, object]:
    for row in rows:
        if row.get("id") == object_id:
            return row
    raise KeyError(object_id)


def _record_table(row: Mapping[str, object]) -> str:
    return _table(("Field", "Value"), ((key, value) for key, value in sorted(row.items())))


def render_detail(snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    kind = kind.lower()
    related = ""
    if kind == "goal":
        row = _find(snapshot.goals, object_id)
        related = "<h2>Flows</h2>" + _linked_table(
            ("ID", "Status", "Controller"),
            (("flow", value["id"], (value["status"], value["controller"])) for value in snapshot.flows if value["goal_id"] == object_id),
        )
    elif kind == "flow":
        row = _find(snapshot.flows, object_id)
        related = "<h2>Tasks</h2>" + _linked_table(
            ("ID", "Status", "Objective"),
            (("task", value["id"], (value["status"], value["objective"])) for value in snapshot.tasks if value["flow_id"] == object_id),
        )
    elif kind == "task":
        row = _find(snapshot.tasks, object_id)
        related = "<h2>Runs</h2>" + _linked_table(
            ("ID", "Role", "Status"),
            (("run", value["id"], (value["role"], value["status"])) for value in snapshot.runs if value["task_id"] == object_id),
        )
        related += "<h2>Verifications</h2>" + _linked_table(
            ("ID", "Type", "Status", "Verifier"),
            (("verification", value["id"], (value["verification_type"], value["status"], value["verifier"])) for value in snapshot.task_verifications if value["target_id"] == object_id),
        )
    elif kind == "run":
        row = _find(snapshot.runs, object_id)
    elif kind == "verification":
        row = _find(snapshot.task_verifications, object_id)
    else:
        raise KeyError(kind)
    body = f"<h1>{_e(kind.title())}</h1>{_record_table(row)}{related}"
    return _page(f"Origin Forge — {kind}", body)
