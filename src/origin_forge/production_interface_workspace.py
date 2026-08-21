from __future__ import annotations

from html import escape
from typing import Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot


_STYLE_MARKER = "</style>"
_INDEX_MARKER = '<nav class="section-nav" aria-label="Cockpit sections">'
_WORKSPACE_CSS = """
.workspace-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(300px, .75fr);
  gap: .8rem;
  margin: 1.15rem 0 1.25rem;
}
.workspace-panel,
.workspace-usage {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: .82rem;
  background: rgba(16, 20, 25, .86);
  box-shadow: var(--shadow);
}
.workspace-panel { overflow: hidden; }
.workspace-heading,
.workspace-usage-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.05rem;
  border-bottom: 1px solid var(--line);
}
.workspace-heading h2,
.workspace-usage-heading h2 {
  margin: 0;
  padding: 0;
  font-size: 1rem;
}
.workspace-heading p,
.workspace-usage-heading p {
  margin: .28rem 0 0;
  color: var(--subtle);
  font-size: .76rem;
}
.workspace-readonly {
  flex: 0 0 auto;
  padding: .26rem .44rem;
  border: 1px solid #365442;
  border-radius: 999px;
  color: #a8ddb9;
  background: rgba(58, 105, 73, .1);
  font-size: .65rem;
  font-weight: 760;
  letter-spacing: .07em;
  text-transform: uppercase;
}
.workspace-stream {
  display: grid;
  gap: .72rem;
  min-height: 280px;
  max-height: 560px;
  padding: 1rem;
  overflow-y: auto;
  background: linear-gradient(180deg, rgba(12, 15, 19, .34), rgba(12, 15, 19, .08));
}
.workspace-message {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: .72rem;
  align-items: start;
}
.workspace-avatar {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: .68rem;
  background: var(--panel-raised);
  color: var(--muted);
  font: 760 .62rem/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: .06em;
}
.workspace-message.task .workspace-avatar {
  border-color: #714a2b;
  color: #f1b985;
  background: rgba(240, 163, 91, .08);
}
.workspace-bubble {
  min-width: 0;
  padding: .78rem .85rem;
  border: 1px solid var(--line);
  border-radius: .72rem;
  background: rgba(24, 29, 36, .72);
}
.workspace-message.task .workspace-bubble { background: rgba(240, 163, 91, .045); }
.workspace-message-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: .7rem;
  margin-bottom: .38rem;
}
.workspace-message-label {
  color: #e3e8ec;
  font-size: .75rem;
  font-weight: 760;
}
.workspace-message-meta {
  color: var(--subtle);
  font-size: .68rem;
  text-align: right;
}
.workspace-message-body { margin: 0; color: #cbd3da; font-size: .86rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.workspace-run-stats {
  display: flex;
  flex-wrap: wrap;
  gap: .38rem;
  margin-top: .58rem;
}
.workspace-run-stat {
  padding: .25rem .4rem;
  border: 1px solid var(--line);
  border-radius: .42rem;
  color: var(--muted);
  background: rgba(255, 255, 255, .018);
  font-size: .67rem;
}
.workspace-composer {
  padding: .85rem 1rem 1rem;
  border-top: 1px solid var(--line);
  background: rgba(12, 15, 19, .42);
}
.workspace-composer-box {
  min-height: 66px;
  padding: .75rem .82rem;
  border: 1px dashed var(--line-strong);
  border-radius: .65rem;
  color: var(--subtle);
  background: rgba(255, 255, 255, .012);
  font-size: .8rem;
}
.workspace-composer-note { margin: .48rem 0 0; color: var(--subtle); font-size: .7rem; }
.workspace-usage { padding-bottom: .95rem; }
.workspace-usage-body { padding: 1rem; }
.workspace-focus {
  min-width: 0;
  margin-bottom: .9rem;
  padding-bottom: .9rem;
  border-bottom: 1px solid var(--line);
}
.workspace-focus-label { display: block; margin-bottom: .28rem; color: var(--subtle); font-size: .65rem; font-weight: 760; letter-spacing: .075em; text-transform: uppercase; }
.workspace-focus a { font-size: .79rem; font-weight: 700; }
.workspace-focus code { color: #f1b985; }
.workspace-focus-rule { margin: .38rem 0 0; color: var(--subtle); font-size: .68rem; }
.token-total {
  margin-bottom: .8rem;
  padding: .9rem;
  border: 1px solid #4a3829;
  border-radius: .72rem;
  background: linear-gradient(145deg, rgba(240, 163, 91, .09), rgba(24, 29, 36, .68));
}
.token-total-value { display: block; color: #f5bd88; font-size: 2rem; font-weight: 780; letter-spacing: -.045em; line-height: 1; }
.token-total-label { display: block; margin-top: .35rem; color: var(--muted); font-size: .68rem; font-weight: 730; letter-spacing: .07em; text-transform: uppercase; }
.token-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .55rem;
  margin-bottom: .9rem;
}
.token-metric {
  min-width: 0;
  padding: .7rem;
  border: 1px solid var(--line);
  border-radius: .58rem;
  background: rgba(255, 255, 255, .018);
}
.token-metric-value { display: block; color: var(--text); font-size: 1.08rem; font-weight: 760; letter-spacing: -.025em; }
.token-metric-label { display: block; margin-top: .2rem; color: var(--subtle); font-size: .62rem; text-transform: uppercase; letter-spacing: .065em; }
.token-completeness {
  margin: 0 0 .95rem;
  color: var(--subtle);
  font-size: .7rem;
}
.token-runs-heading { margin: 0 0 .55rem; color: #dce2e7; font-size: .72rem; font-weight: 760; letter-spacing: .065em; text-transform: uppercase; }
.token-runs { display: grid; gap: .5rem; }
.token-run {
  min-width: 0;
  padding: .62rem .68rem;
  border: 1px solid var(--line);
  border-radius: .55rem;
  background: rgba(255, 255, 255, .014);
}
.token-run-head { display: flex; justify-content: space-between; gap: .6rem; align-items: baseline; }
.token-run-head a { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .7rem; }
.token-run-status { flex: 0 0 auto; color: var(--subtle); font-size: .64rem; }
.token-run-usage { margin-top: .28rem; color: var(--muted); font-size: .68rem; }
.workspace-empty {
  display: grid;
  place-items: center;
  min-height: 220px;
  padding: 2rem;
  color: var(--subtle);
  text-align: center;
  font-size: .82rem;
}
@media (max-width: 980px) {
  .workspace-shell { grid-template-columns: 1fr; }
  .workspace-stream { max-height: none; }
}
@media (max-width: 560px) {
  .workspace-heading, .workspace-usage-heading { flex-direction: column; }
  .workspace-message { grid-template-columns: 34px minmax(0, 1fr); gap: .55rem; }
  .workspace-avatar { width: 34px; height: 34px; border-radius: .52rem; font-size: .55rem; }
  .workspace-message-head { align-items: start; flex-direction: column; gap: .15rem; }
  .workspace-message-meta { text-align: left; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit workspace marker is missing")
    return page.replace(old, new, 1)


def _token_count(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _format_tokens(value: int | None) -> str:
    return "Unreported" if value is None else f"{value:,}"


def _focus_task(snapshot: ProductionInterfaceSnapshot) -> Mapping[str, object] | None:
    if not snapshot.tasks:
        return None
    return max(
        snapshot.tasks,
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("id") or ""),
        ),
    )


def _task_runs(
    snapshot: ProductionInterfaceSnapshot, task_id: str
) -> tuple[Mapping[str, object], ...]:
    values = tuple(
        row for row in snapshot.runs if str(row.get("task_id") or "") == task_id
    )
    return tuple(
        sorted(
            values,
            key=lambda row: (
                str(row.get("started_at") or ""),
                str(row.get("id") or ""),
            ),
        )
    )


def _reported_usage(
    runs: tuple[Mapping[str, object], ...],
) -> tuple[int, int, int, bool]:
    input_total = 0
    output_total = 0
    complete = True
    for run in runs:
        input_count = _token_count(run.get("input_token_count"))
        output_count = _token_count(run.get("output_token_count"))
        if input_count is None or output_count is None:
            complete = False
        if input_count is not None:
            input_total += input_count
        if output_count is not None:
            output_total += output_count
    return input_total, output_total, input_total + output_total, complete


def _task_message(task: Mapping[str, object]) -> str:
    objective = task.get("objective")
    objective_text = "No task objective exposed in this snapshot." if objective is None else str(objective)
    return (
        '<article class="workspace-message task">'
        '<div class="workspace-avatar" aria-hidden="true">TASK</div>'
        '<div class="workspace-bubble">'
        '<div class="workspace-message-head">'
        '<span class="workspace-message-label">Task objective</span>'
        f'<span class="workspace-message-meta">Status · {_e(task.get("status"))}</span></div>'
        f'<p class="workspace-message-body">{_e(objective_text)}</p>'
        '</div></article>'
    )


def _run_message(run: Mapping[str, object]) -> str:
    input_count = _token_count(run.get("input_token_count"))
    output_count = _token_count(run.get("output_token_count"))
    total = None if input_count is None or output_count is None else input_count + output_count
    run_id = str(run.get("id") or "")
    role = run.get("role")
    model_profile = run.get("model_profile")
    return (
        '<article class="workspace-message run">'
        '<div class="workspace-avatar" aria-hidden="true">RUN</div>'
        '<div class="workspace-bubble">'
        '<div class="workspace-message-head">'
        f'<a class="workspace-message-label" href="/run/{_e(run_id)}">Run {_e(run_id)}</a>'
        f'<span class="workspace-message-meta">{_e(run.get("status"))}</span></div>'
        f'<p class="workspace-message-body">Role {_e(role)} · Model profile {_e(model_profile)}</p>'
        '<div class="workspace-run-stats">'
        f'<span class="workspace-run-stat">Input {_e(_format_tokens(input_count))}</span>'
        f'<span class="workspace-run-stat">Output {_e(_format_tokens(output_count))}</span>'
        f'<span class="workspace-run-stat">Total {_e(_format_tokens(total))}</span>'
        '</div></div></article>'
    )


def _conversation(task: Mapping[str, object], runs: tuple[Mapping[str, object], ...]) -> str:
    stream = _task_message(task) + "".join(_run_message(run) for run in runs)
    return (
        '<section class="workspace-panel" aria-label="Chat workspace">'
        '<div class="workspace-heading"><div><h2>Chat workspace</h2>'
        '<p>Conversation-shaped inspection of the selected task. Task intent and Run activity only.</p>'
        '</div><span class="workspace-readonly">Read only</span></div>'
        f'<div class="workspace-stream">{stream}</div>'
        '<div class="workspace-composer">'
        '<div class="workspace-composer-box" role="note">Message composer is intentionally locked. '
        'A governed conversation/application service must exist before this surface can send work.</div>'
        '<p class="workspace-composer-note">This is not a persisted chat transcript; no message or execution authority is exposed by the cockpit.</p>'
        '</div></section>'
    )


def _run_usage(run: Mapping[str, object]) -> str:
    input_count = _token_count(run.get("input_token_count"))
    output_count = _token_count(run.get("output_token_count"))
    total = None if input_count is None or output_count is None else input_count + output_count
    run_id = str(run.get("id") or "")
    return (
        '<div class="token-run">'
        '<div class="token-run-head">'
        f'<a href="/run/{_e(run_id)}"><code>{_e(run_id)}</code></a>'
        f'<span class="token-run-status">{_e(run.get("status"))}</span></div>'
        f'<div class="token-run-usage">{_e(_format_tokens(total))} tokens · '
        f'{_e(_format_tokens(input_count))} in · {_e(_format_tokens(output_count))} out</div>'
        '</div>'
    )


def _usage(task: Mapping[str, object], runs: tuple[Mapping[str, object], ...]) -> str:
    task_id = str(task.get("id") or "")
    input_total, output_total, total, complete = _reported_usage(runs)
    if not runs:
        completeness = "No Runs are present for this task; token consumption is 0 in this snapshot."
    elif complete:
        completeness = "All Run input/output token counters in this snapshot are reported."
    else:
        completeness = "Partial total: one or more Run token counters are unreported. Reported values are never imputed."
    run_markup = "".join(_run_usage(run) for run in reversed(runs))
    if not run_markup:
        run_markup = '<div class="workspace-empty">No Run token records for this task.</div>'
    return (
        '<aside class="workspace-usage" aria-label="Task token telemetry">'
        '<div class="workspace-usage-heading"><div><h2>Task tokens</h2>'
        '<p>Local inference work measured from durable Run counters.</p></div></div>'
        '<div class="workspace-usage-body">'
        '<div class="workspace-focus"><span class="workspace-focus-label">Focus task</span>'
        f'<a href="/task/{_e(task_id)}"><code>{_e(task_id)}</code></a>'
        f'<p class="workspace-focus-rule">Status {_e(task.get("status"))} · selected as the most recently updated Task in this bounded snapshot.</p></div>'
        '<div class="token-total">'
        f'<span class="token-total-value">{_e(_format_tokens(total))}</span>'
        '<span class="token-total-label">Reported task tokens</span></div>'
        '<div class="token-grid">'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{_e(_format_tokens(input_total))}</span>'
        '<span class="token-metric-label">Input tokens</span></div>'
        '<div class="token-metric">'
        f'<span class="token-metric-value">{_e(_format_tokens(output_total))}</span>'
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


def _empty_workspace() -> str:
    return (
        '<section id="workspace" class="workspace-shell" aria-label="Operator workspace">'
        '<section class="workspace-panel" aria-label="Chat workspace">'
        '<div class="workspace-heading"><div><h2>Chat workspace</h2>'
        '<p>Conversation surface is ready for a governed task, but no Task is visible in this snapshot.</p>'
        '</div><span class="workspace-readonly">Read only</span></div>'
        '<div class="workspace-empty">Create or expose a Task through the authoritative control plane to populate this workspace.</div>'
        '<div class="workspace-composer"><div class="workspace-composer-box" role="note">Message composer is intentionally locked.</div></div>'
        '</section>'
        '<aside class="workspace-usage" aria-label="Task token telemetry">'
        '<div class="workspace-usage-heading"><div><h2>Task tokens</h2>'
        '<p>No Task is available for token aggregation.</p></div></div>'
        '<div class="workspace-empty">0 visible task Runs</div></aside></section>'
    )


def _workspace(snapshot: ProductionInterfaceSnapshot) -> str:
    task = _focus_task(snapshot)
    if task is None:
        return _empty_workspace()
    task_id = str(task.get("id") or "")
    runs = _task_runs(snapshot, task_id)
    return (
        '<section id="workspace" class="workspace-shell" aria-label="Operator workspace">'
        + _conversation(task, runs)
        + _usage(task, runs)
        + "</section>"
    )


def decorate_workspace(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _WORKSPACE_CSS + _STYLE_MARKER)
    index = '<a href="#workspace">Workspace</a>' + _INDEX_MARKER
    page = _replace_once(page, _INDEX_MARKER, index)
    return _replace_once(page, _INDEX_MARKER, _workspace(snapshot) + _INDEX_MARKER)
