from __future__ import annotations

from html import escape
from typing import Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot
from . import production_interface_workspace as workspace


_STYLE_MARKER = "</style>"
_WORKSPACE_MARKER = '<section id="workspace" class="workspace-shell" aria-label="Operator workspace">'
_TASK_SWITCHER_CSS = """
.task-switcher {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: .82rem;
  background: rgba(16, 20, 25, .86);
  box-shadow: var(--shadow);
}
.task-switcher-heading {
  padding: .9rem .9rem .78rem;
  border-bottom: 1px solid var(--line);
}
.task-switcher-heading h2 {
  margin: 0;
  padding: 0;
  color: #dce2e7;
  font-size: .78rem;
  font-weight: 760;
  letter-spacing: .065em;
  text-transform: uppercase;
}
.task-switcher-heading p {
  margin: .3rem 0 0;
  color: var(--subtle);
  font-size: .67rem;
  line-height: 1.45;
}
.task-switcher-list {
  display: grid;
  gap: .35rem;
  max-height: 590px;
  padding: .55rem;
  overflow-y: auto;
}
.task-switcher-item {
  display: block;
  min-width: 0;
  padding: .68rem;
  border: 1px solid transparent;
  border-radius: .58rem;
  color: inherit;
  background: rgba(255, 255, 255, .012);
  text-decoration: none;
}
.task-switcher-item:hover,
.task-switcher-item:focus-visible {
  border-color: var(--line-strong);
  background: rgba(255, 255, 255, .035);
  outline: none;
}
.task-switcher-item.is-focus {
  border-color: #5b442f;
  background: rgba(240, 163, 91, .055);
}
.task-switcher-item-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: .45rem;
  margin-bottom: .35rem;
}
.task-switcher-item-head code {
  min-width: 0;
  overflow: hidden;
  color: #f1b985;
  font-size: .61rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-switcher-focus {
  flex: 0 0 auto;
  padding: .16rem .3rem;
  border: 1px solid #6c5035;
  border-radius: 999px;
  color: #f1b985;
  font-size: .55rem;
  font-weight: 760;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.task-switcher-objective {
  display: -webkit-box;
  overflow: hidden;
  color: #d8dee4;
  font-size: .73rem;
  font-weight: 680;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.task-switcher-meta {
  display: flex;
  flex-wrap: wrap;
  gap: .3rem .45rem;
  margin-top: .5rem;
  color: var(--subtle);
  font-size: .6rem;
}
.task-switcher-meta span { white-space: nowrap; }
.task-switcher-coverage {
  margin: .35rem .55rem .6rem;
  padding: .55rem .6rem;
  border-top: 1px solid var(--line);
  color: var(--subtle);
  font-size: .61rem;
  line-height: 1.45;
}
.task-switcher-empty {
  padding: 1.15rem .8rem;
  color: var(--subtle);
  text-align: center;
  font-size: .7rem;
}
.workspace-shell {
  grid-template-columns: minmax(210px, .55fr) minmax(0, 1.45fr) minmax(300px, .75fr);
}
@media (max-width: 1180px) {
  .workspace-shell { grid-template-columns: minmax(220px, .55fr) minmax(0, 1.45fr); }
  .workspace-usage { grid-column: 1 / -1; }
}
@media (max-width: 800px) {
  .workspace-shell { grid-template-columns: 1fr; }
  .workspace-usage { grid-column: auto; }
  .task-switcher-list {
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    max-height: none;
  }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit task-switcher marker is missing")
    return page.replace(old, new, 1)


def _task_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("updated_at") or ""),
        str(row.get("created_at") or ""),
        str(row.get("id") or ""),
    )


def _task_item(
    snapshot: ProductionInterfaceSnapshot,
    task: Mapping[str, object],
    *,
    focus_id: str | None,
) -> str:
    task_id = str(task.get("id") or "")
    runs = workspace._task_runs(snapshot, task_id)
    _, _, total, complete = workspace._reported_usage(runs)
    objective = task.get("objective")
    objective_text = "No task objective exposed in this snapshot." if objective is None else str(objective)
    completeness = "complete counters" if complete else "partial counters"
    focus = task_id == focus_id
    focus_markup = '<span class="task-switcher-focus">Focus</span>' if focus else ""
    focus_class = " is-focus" if focus else ""
    return (
        f'<a class="task-switcher-item{focus_class}" href="/task/{_e(task_id)}">'
        '<span class="task-switcher-item-head">'
        f'<code>{_e(task_id)}</code>{focus_markup}</span>'
        f'<span class="task-switcher-objective">{_e(objective_text)}</span>'
        '<span class="task-switcher-meta">'
        f'<span>Status {_e(task.get("status"))}</span>'
        f'<span>{len(runs)} Run(s)</span>'
        f'<span>{_e(workspace._format_tokens(total))} tokens</span>'
        f'<span>{_e(completeness)}</span>'
        "</span></a>"
    )


def _int_value(value: object, fallback: int) -> int:
    return value if type(value) is int and value >= 0 else fallback


def _panel(snapshot: ProductionInterfaceSnapshot) -> str:
    ordered = tuple(sorted(snapshot.tasks, key=_task_key, reverse=True))
    focus = workspace._focus_task(snapshot)
    focus_id = None if focus is None else str(focus.get("id") or "")
    visible = len(ordered)
    total = _int_value(snapshot.total_counts.get("tasks"), visible)
    truncated = bool(snapshot.truncated.get("tasks"))

    if ordered:
        items = "".join(
            _task_item(snapshot, task, focus_id=focus_id) for task in ordered[:12]
        )
    else:
        items = '<div class="task-switcher-empty">No Tasks are visible in this snapshot.</div>'

    omitted = max(0, visible - 12)
    if truncated:
        coverage = (
            f"Bounded Task view: {visible} of {total} Task records are visible. "
            "This rail is not complete project history."
        )
    else:
        coverage = f"All {visible} project Task records are visible in this snapshot."
    if omitted:
        coverage += f" The rail shows the 12 most recently updated; {omitted} additional visible Task(s) are omitted."

    return (
        '<aside class="task-switcher" aria-label="Recent Tasks">'
        '<div class="task-switcher-heading"><h2>Recent Tasks</h2>'
        '<p>Task navigation ordered by durable update timestamps. Tasks are work records, not persisted conversations.</p></div>'
        f'<nav class="task-switcher-list" aria-label="Task workspace links">{items}</nav>'
        f'<p class="task-switcher-coverage">{_e(coverage)}</p></aside>'
    )


def decorate_task_switcher(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _TASK_SWITCHER_CSS + _STYLE_MARKER)
    return _replace_once(
        page,
        _WORKSPACE_MARKER,
        _WORKSPACE_MARKER + _panel(snapshot),
    )
