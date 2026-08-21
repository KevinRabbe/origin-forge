from __future__ import annotations

from html import escape
from typing import Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot
from . import production_interface_workspace as workspace


_STYLE_MARKER = "</style>"
_DETAIL_TABLE_MARKER = '<div class="table-shell"><table>'
_TASK_WORKSPACE_CSS = """
.task-workspace .workspace-focus-rule strong {
  color: #dce2e7;
  font-weight: 720;
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit task workspace marker is missing")
    return page.replace(old, new, 1)


def _task(
    snapshot: ProductionInterfaceSnapshot, task_id: str
) -> Mapping[str, object]:
    for row in snapshot.tasks:
        if row.get("id") == task_id:
            return row
    raise ValueError("snapshot task record is missing")


def _detail_usage(
    task: Mapping[str, object],
    runs: tuple[Mapping[str, object], ...],
) -> str:
    task_id = str(task.get("id") or "")
    input_total, output_total, total, complete = workspace._reported_usage(runs)
    if not runs:
        completeness = "No Runs are present for this task; token consumption is 0 in this snapshot."
    elif complete:
        completeness = "All Run input/output token counters in this snapshot are reported."
    else:
        completeness = "Partial total: one or more Run token counters are unreported. Reported values are never imputed."

    run_markup = "".join(workspace._run_usage(run) for run in reversed(runs))
    if not run_markup:
        run_markup = '<div class="workspace-empty">No Run token records for this task.</div>'

    return (
        '<aside class="workspace-usage" aria-label="Selected task token telemetry">'
        '<div class="workspace-usage-heading"><div><h2>Task tokens</h2>'
        '<p>Local inference work measured from durable Run counters.</p></div></div>'
        '<div class="workspace-usage-body">'
        '<div class="workspace-focus"><span class="workspace-focus-label">Selected task</span>'
        f'<code>{_e(task_id)}</code>'
        f'<p class="workspace-focus-rule"><strong>Exact Task detail selection.</strong> Status {_e(task.get("status"))}; no overview focus heuristic is used here.</p></div>'
        '<div class="token-total">'
        f'<span class="token-total-value">{_e(workspace._format_tokens(total))}</span>'
        '<span class="token-total-label">Reported task tokens</span></div>'
        '<div class="token-grid">'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{_e(workspace._format_tokens(input_total))}</span>'
        '<span class="token-metric-label">Input tokens</span></div>'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{_e(workspace._format_tokens(output_total))}</span>'
        '<span class="token-metric-label">Output tokens</span></div>'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{len(runs)}</span>'
        '<span class="token-metric-label">Runs</span></div>'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{_e(task.get("attempt_count"))}</span>'
        '<span class="token-metric-label">Attempts</span></div>'
        '</div>'
        f'<p class="token-completeness">{_e(completeness)}</p>'
        '<h3 class="token-runs-heading">Run usage</h3>'
        f'<div class="token-runs">{run_markup}</div>'
        '</div></aside>'
    )


def _panel(snapshot: ProductionInterfaceSnapshot, task_id: str) -> str:
    task = _task(snapshot, task_id)
    runs = workspace._task_runs(snapshot, task_id)
    return (
        '<section id="task-workspace" class="workspace-shell task-workspace" '
        'aria-label="Selected task workspace">'
        + workspace._conversation(task, runs)
        + _detail_usage(task, runs)
        + "</section>"
    )


def decorate_task_workspace(
    page: str,
    snapshot: ProductionInterfaceSnapshot,
    *,
    task_id: str,
) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    css = workspace._WORKSPACE_CSS + _TASK_WORKSPACE_CSS
    page = _replace_once(page, _STYLE_MARKER, css + _STYLE_MARKER)
    return _replace_once(
        page,
        _DETAIL_TABLE_MARKER,
        _panel(snapshot, task_id) + _DETAIL_TABLE_MARKER,
    )
