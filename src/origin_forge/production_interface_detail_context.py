from __future__ import annotations

from collections.abc import Iterable, Mapping
from html import escape

from .production_interface_snapshot import ProductionInterfaceSnapshot

_STYLE_MARKER = "</style>"
_DETAIL_TABLE_MARKER = '<div class="table-shell"><table>'
_DETAIL_CONTEXT_CSS = """
.detail-context {
  margin: 0 0 1.35rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .75rem;
  background: rgba(16, 20, 25, .78);
}
.detail-context-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .8rem;
}
.detail-context-title {
  color: #dce2e7;
  font-size: .76rem;
  font-weight: 760;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.detail-context-note {
  color: var(--subtle);
  font-size: .72rem;
}
.detail-context-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .55rem;
}
.detail-context-item,
.detail-context-link {
  min-width: 0;
  min-height: 72px;
  padding: .72rem .78rem;
  border: 1px solid var(--line);
  border-radius: .58rem;
  background: rgba(255, 255, 255, .018);
}
.detail-context-link {
  display: block;
  color: inherit;
  text-decoration: none;
}
.detail-context-link:hover {
  border-color: var(--line-strong);
  background: rgba(255, 255, 255, .035);
}
.detail-context-label {
  display: block;
  margin-bottom: .3rem;
  color: var(--subtle);
  font-size: .66rem;
  font-weight: 740;
  letter-spacing: .07em;
  text-transform: uppercase;
}
.detail-context-value {
  display: block;
  color: var(--text);
  font-size: 1rem;
  font-weight: 700;
}
.detail-context-link code {
  display: block;
  color: #f1b985;
  font-size: .76rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 980px) {
  .detail-context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .detail-context-head { align-items: start; flex-direction: column; }
  .detail-context-grid { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit detail context marker is missing")
    return page.replace(old, new, 1)


def _find(rows: Iterable[Mapping[str, object]], object_id: str) -> Mapping[str, object]:
    for row in rows:
        if row.get("id") == object_id:
            return row
    raise ValueError("snapshot detail record is missing")


def _record(
    snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str
) -> Mapping[str, object]:
    sources: dict[str, Iterable[Mapping[str, object]]] = {
        "goal": snapshot.goals,
        "flow": snapshot.flows,
        "task": snapshot.tasks,
        "run": snapshot.runs,
        "decision": snapshot.decisions,
        "change": snapshot.changes,
        "artifact": snapshot.artifacts,
        "entity": snapshot.entities,
        "rule": snapshot.design_rules,
    }
    if kind == "verification":
        try:
            return _find(snapshot.task_verifications, object_id)
        except ValueError:
            return _find(snapshot.artifact_verifications, object_id)
    rows = sources.get(kind)
    if rows is None:
        raise ValueError("unsupported cockpit detail kind")
    return _find(rows, object_id)


def _metric(label: str, value: object) -> str:
    return (
        '<div class="detail-context-item">'
        f'<span class="detail-context-label">{_e(label)}</span>'
        f'<span class="detail-context-value">{_e(value)}</span></div>'
    )


def _link(kind: str, object_id: object, label: str) -> str:
    return (
        f'<a class="detail-context-link" href="/{_e(kind)}/{_e(object_id)}">'
        f'<span class="detail-context-label">{_e(label)}</span>'
        f'<code>{_e(object_id)}</code></a>'
    )


def _count(rows: Iterable[Mapping[str, object]], field: str, value: object) -> int:
    return sum(1 for row in rows if row.get(field) == value)


def _relationship_items(
    snapshot: ProductionInterfaceSnapshot,
    *,
    kind: str,
    object_id: str,
    row: Mapping[str, object],
) -> tuple[str, ...]:
    items: list[str] = []
    if row.get("status") is not None:
        items.append(_metric("Status", row.get("status")))

    if kind == "goal":
        items.append(_metric("Flows", _count(snapshot.flows, "goal_id", object_id)))
    elif kind == "flow":
        items.append(_link("goal", row.get("goal_id"), "Parent goal"))
        items.append(_metric("Tasks", _count(snapshot.tasks, "flow_id", object_id)))
    elif kind == "task":
        items.append(_link("flow", row.get("flow_id"), "Parent flow"))
        items.append(_metric("Runs", _count(snapshot.runs, "task_id", object_id)))
        items.append(
            _metric(
                "Verifications",
                _count(snapshot.task_verifications, "target_id", object_id),
            )
        )
        items.append(_metric("Changes", _count(snapshot.changes, "task_id", object_id)))
    elif kind == "run":
        items.append(_link("task", row.get("task_id"), "Parent task"))
        if row.get("role") is not None:
            items.append(_metric("Role", row.get("role")))
    elif kind == "verification":
        is_task_verification = any(
            value.get("id") == object_id for value in snapshot.task_verifications
        )
        target_kind = "task" if is_task_verification else "artifact"
        items.append(_link(target_kind, row.get("target_id"), "Verified target"))
        if row.get("verification_type") is not None:
            items.append(_metric("Verification type", row.get("verification_type")))
    elif kind == "decision":
        items.append(_link("task", row.get("task_id"), "Parent task"))
        items.append(_metric("Changes", _count(snapshot.changes, "decision_id", object_id)))
    elif kind == "change":
        items.append(_link("task", row.get("task_id"), "Parent task"))
        if row.get("decision_id") is not None:
            items.append(_link("decision", row.get("decision_id"), "Decision"))
        items.append(_metric("Artifacts", _count(snapshot.artifacts, "change_id", object_id)))
    elif kind == "artifact":
        items.append(_link("change", row.get("change_id"), "Parent change"))
        items.append(
            _metric(
                "Verifications",
                _count(snapshot.artifact_verifications, "target_id", object_id),
            )
        )
        if row.get("type") is not None:
            items.append(_metric("Artifact type", row.get("type")))
    elif kind == "entity":
        relation_count = sum(
            1
            for value in snapshot.entity_relations
            if value.get("source_entity_id") == object_id
            or value.get("target_entity_id") == object_id
        )
        binding_count = _count(snapshot.entity_bindings, "entity_id", object_id)
        scoped_rules = sum(
            1
            for value in snapshot.design_rules
            if (
                isinstance(value.get("scope_entity_ids"), (list, tuple))
                and object_id in value["scope_entity_ids"]
            )
        )
        items.extend(
            (
                _metric("Relations", relation_count),
                _metric("Bindings", binding_count),
                _metric("Scoped rules", scoped_rules),
            )
        )
    elif kind == "rule":
        scope_ids = row.get("scope_entity_ids")
        scope_count = len(scope_ids) if isinstance(scope_ids, (list, tuple)) else 0
        items.append(_metric("Scoped entities", scope_count))
        if row.get("authority") is not None:
            items.append(_metric("Rule authority", row.get("authority")))

    return tuple(items)


def _panel(
    snapshot: ProductionInterfaceSnapshot, *, kind: str, object_id: str
) -> str:
    normalized_kind = kind.lower()
    row = _record(snapshot, normalized_kind, object_id)
    items = _relationship_items(
        snapshot,
        kind=normalized_kind,
        object_id=object_id,
        row=row,
    )
    return (
        '<section class="detail-context" aria-label="Snapshot relationships">'
        '<div class="detail-context-head">'
        '<span class="detail-context-title">Snapshot relationships</span>'
        '<span class="detail-context-note">Read-only context from this snapshot only</span>'
        '</div><div class="detail-context-grid">'
        + "".join(items)
        + "</div></section>"
    )


def decorate_detail_context(
    page: str,
    snapshot: ProductionInterfaceSnapshot,
    *,
    kind: str,
    object_id: str,
) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _DETAIL_CONTEXT_CSS + _STYLE_MARKER)
    panel = _panel(snapshot, kind=kind, object_id=object_id)
    return _replace_once(page, _DETAIL_TABLE_MARKER, panel + _DETAIL_TABLE_MARKER)
