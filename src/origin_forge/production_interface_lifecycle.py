from __future__ import annotations

from collections import Counter
from html import escape
from typing import Iterable, Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot


_STYLE_MARKER = "</style>"
_INDEX_MARKER = '<nav class="section-nav" aria-label="Cockpit sections">'
_LIFECYCLE_CSS = """
.lifecycle-panel {
  margin: 1rem 0 1.2rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .78rem;
  background: rgba(16, 20, 25, .82);
  box-shadow: var(--shadow);
}
.lifecycle-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .9rem;
}
.lifecycle-heading h2 {
  margin: 0;
  padding: 0;
  font-size: 1rem;
}
.lifecycle-heading p {
  margin: 0;
  max-width: 720px;
  color: var(--subtle);
  font-size: .78rem;
  text-align: right;
}
.lifecycle-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: .6rem;
}
.lifecycle-stage {
  min-width: 0;
  padding: .82rem;
  border: 1px solid var(--line);
  border-radius: .65rem;
  background: linear-gradient(180deg, rgba(24, 29, 36, .88), rgba(14, 18, 22, .88));
}
.lifecycle-stage-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: .7rem;
  margin-bottom: .65rem;
}
.lifecycle-stage-name {
  color: #dce2e7;
  font-size: .72rem;
  font-weight: 760;
  letter-spacing: .075em;
  text-transform: uppercase;
}
.lifecycle-stage-total {
  color: var(--text);
  font-size: 1.2rem;
  font-weight: 760;
  letter-spacing: -.03em;
}
.lifecycle-statuses {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem;
}
.lifecycle-status {
  display: inline-flex;
  align-items: center;
  gap: .35rem;
  min-width: 0;
  padding: .28rem .42rem;
  border: 1px solid var(--line);
  border-radius: .42rem;
  background: rgba(255, 255, 255, .025);
  color: var(--muted);
  font-size: .67rem;
  line-height: 1.15;
}
.lifecycle-status-name {
  max-width: 11rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lifecycle-status-count {
  color: #f1b985;
  font-weight: 760;
}
.lifecycle-empty {
  color: var(--subtle);
  font-size: .72rem;
}
@media (max-width: 1180px) {
  .lifecycle-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .lifecycle-heading { align-items: start; flex-direction: column; }
  .lifecycle-heading p { text-align: left; }
  .lifecycle-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 430px) {
  .lifecycle-grid { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit lifecycle marker is missing")
    return page.replace(old, new, 1)


def _status_counts(rows: Iterable[Mapping[str, object]]) -> tuple[tuple[str, int], ...]:
    counts = Counter(
        str(row.get("status")) if row.get("status") is not None else "Unspecified"
        for row in rows
    )
    return tuple(sorted(counts.items(), key=lambda item: (item[0].casefold(), item[0])))


def _stage(label: str, rows: tuple[Mapping[str, object], ...]) -> str:
    statuses = _status_counts(rows)
    if statuses:
        status_markup = "".join(
            '<span class="lifecycle-status">'
            f'<span class="lifecycle-status-name" title="{_e(status)}">{_e(status)}</span>'
            f'<span class="lifecycle-status-count">{count}</span></span>'
            for status, count in statuses
        )
    else:
        status_markup = '<span class="lifecycle-empty">No records</span>'
    return (
        '<article class="lifecycle-stage">'
        '<div class="lifecycle-stage-head">'
        f'<span class="lifecycle-stage-name">{_e(label)}</span>'
        f'<span class="lifecycle-stage-total">{len(rows)}</span></div>'
        f'<div class="lifecycle-statuses">{status_markup}</div></article>'
    )


def _panel(snapshot: ProductionInterfaceSnapshot) -> str:
    verifications = tuple(snapshot.task_verifications) + tuple(
        snapshot.artifact_verifications
    )
    stages = (
        ("Goals", tuple(snapshot.goals)),
        ("Flows", tuple(snapshot.flows)),
        ("Tasks", tuple(snapshot.tasks)),
        ("Runs", tuple(snapshot.runs)),
        ("Verifications", verifications),
        ("Artifacts", tuple(snapshot.artifacts)),
    )
    return (
        '<section class="lifecycle-panel" aria-label="Production lifecycle summary">'
        '<div class="lifecycle-heading"><h2>Production lifecycle</h2>'
        '<p>Snapshot-scoped counts. Status values are shown verbatim and do not grant '
        'execution, mutation, or verification authority.</p></div>'
        '<div class="lifecycle-grid">'
        + "".join(_stage(label, rows) for label, rows in stages)
        + "</div></section>"
    )


def decorate_lifecycle(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _LIFECYCLE_CSS + _STYLE_MARKER)
    return _replace_once(page, _INDEX_MARKER, _panel(snapshot) + _INDEX_MARKER)
