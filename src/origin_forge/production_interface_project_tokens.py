from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Iterable, Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot


_STYLE_MARKER = "</style>"
_INDEX_MARKER = '<nav class="section-nav" aria-label="Cockpit sections">'
_PROJECT_TOKENS_CSS = """
.project-tokens {
  margin: 0 0 1.2rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .82rem;
  background: rgba(16, 20, 25, .86);
  box-shadow: var(--shadow);
}
.project-tokens-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .85rem;
}
.project-tokens-heading h2 {
  margin: 0;
  padding: 0;
  font-size: 1rem;
}
.project-tokens-heading p {
  margin: .28rem 0 0;
  max-width: 760px;
  color: var(--subtle);
  font-size: .76rem;
}
.project-token-coverage {
  flex: 0 0 auto;
  padding: .28rem .46rem;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--muted);
  background: rgba(255, 255, 255, .018);
  font-size: .64rem;
  font-weight: 760;
  letter-spacing: .065em;
  text-transform: uppercase;
}
.project-token-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: .55rem;
  margin-bottom: .75rem;
}
.project-token-metric {
  min-width: 0;
  padding: .72rem;
  border: 1px solid var(--line);
  border-radius: .6rem;
  background: rgba(255, 255, 255, .018);
}
.project-token-metric strong {
  display: block;
  color: var(--text);
  font-size: 1.08rem;
  letter-spacing: -.025em;
  overflow-wrap: anywhere;
}
.project-token-metric span {
  display: block;
  margin-top: .2rem;
  color: var(--subtle);
  font-size: .61rem;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.project-token-total {
  border-color: #4a3829;
  background: linear-gradient(145deg, rgba(240, 163, 91, .08), rgba(24, 29, 36, .68));
}
.project-token-total strong { color: #f5bd88; }
.project-token-note {
  margin: 0 0 .9rem;
  padding: .65rem .72rem;
  border-left: 2px solid var(--line-strong);
  color: var(--muted);
  background: rgba(255, 255, 255, .012);
  font-size: .71rem;
}
.project-token-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr);
  gap: .75rem;
}
.project-token-block {
  min-width: 0;
  padding: .8rem;
  border: 1px solid var(--line);
  border-radius: .68rem;
  background: rgba(12, 15, 19, .28);
}
.project-token-block h3 {
  margin: 0 0 .55rem;
  color: #dce2e7;
  font-size: .72rem;
  font-weight: 760;
  letter-spacing: .065em;
  text-transform: uppercase;
}
.project-token-table-shell {
  max-width: 100%;
  overflow-x: auto;
}
.project-token-table {
  width: 100%;
  border-collapse: collapse;
  font-size: .7rem;
}
.project-token-table caption {
  padding: 0 0 .55rem;
  color: var(--subtle);
  font-size: .66rem;
  text-align: left;
}
.project-token-table th,
.project-token-table td {
  padding: .5rem .46rem;
  border-bottom: 1px solid var(--line);
  text-align: right;
  vertical-align: top;
  white-space: nowrap;
}
.project-token-table th:first-child,
.project-token-table td:first-child { text-align: left; }
.project-token-table th {
  color: var(--subtle);
  font-size: .6rem;
  letter-spacing: .055em;
  text-transform: uppercase;
}
.project-token-table tbody tr:last-child td { border-bottom: 0; }
.project-token-task {
  display: block;
  max-width: 24rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-token-task-objective {
  display: block;
  max-width: 24rem;
  margin-top: .18rem;
  overflow: hidden;
  color: var(--subtle);
  font-size: .63rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-token-profiles { display: grid; gap: .45rem; }
.project-token-profile {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: .65rem;
  align-items: baseline;
  padding: .58rem .62rem;
  border: 1px solid var(--line);
  border-radius: .52rem;
  background: rgba(255, 255, 255, .014);
}
.project-token-profile-name {
  min-width: 0;
  overflow: hidden;
  color: #dce2e7;
  font: 700 .67rem/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-token-profile-usage {
  color: #f1b985;
  font-size: .68rem;
  font-weight: 740;
  white-space: nowrap;
}
.project-token-profile-meta {
  grid-column: 1 / -1;
  color: var(--subtle);
  font-size: .61rem;
}
.project-token-empty {
  padding: 1rem;
  color: var(--subtle);
  text-align: center;
  font-size: .72rem;
}
@media (max-width: 1180px) {
  .project-token-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .project-token-columns { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .project-tokens-heading { flex-direction: column; }
  .project-token-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 420px) {
  .project-token-summary { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit project-token marker is missing")
    return page.replace(old, new, 1)


def _token_count(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _format_tokens(value: int) -> str:
    return f"{value:,}"


def _reported_usage(
    runs: Iterable[Mapping[str, object]],
) -> tuple[int, int, int, int, int, int]:
    input_total = 0
    output_total = 0
    run_count = 0
    complete_runs = 0
    missing_counters = 0
    for run in runs:
        run_count += 1
        input_count = _token_count(run.get("input_token_count"))
        output_count = _token_count(run.get("output_token_count"))
        if input_count is None:
            missing_counters += 1
        else:
            input_total += input_count
        if output_count is None:
            missing_counters += 1
        else:
            output_total += output_count
        if input_count is not None and output_count is not None:
            complete_runs += 1
    return (
        input_total,
        output_total,
        input_total + output_total,
        run_count,
        complete_runs,
        missing_counters,
    )


def _task_rows(snapshot: ProductionInterfaceSnapshot) -> tuple[str, ...]:
    task_index = {str(row.get("id") or ""): row for row in snapshot.tasks}
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for run in snapshot.runs:
        task_id = str(run.get("task_id") or "")
        grouped[task_id].append(run)

    ranked: list[tuple[int, str, tuple[int, int, int, int, int, int]]] = []
    for task_id, runs in grouped.items():
        usage = _reported_usage(runs)
        ranked.append((usage[2], task_id, usage))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    rows: list[str] = []
    for _, task_id, usage in ranked[:12]:
        input_total, output_total, total, run_count, _, missing = usage
        task = task_index.get(task_id)
        if task is not None:
            task_markup = f'<a class="project-token-task" href="/task/{_e(task_id)}"><code>{_e(task_id)}</code></a>'
            objective = task.get("objective")
            if objective is not None:
                task_markup += f'<span class="project-token-task-objective" title="{_e(objective)}">{_e(objective)}</span>'
        elif task_id:
            task_markup = f'<code class="project-token-task" title="Task record is outside this bounded snapshot">{_e(task_id)}</code>'
        else:
            task_markup = '<span class="project-token-task">Unassigned Run</span>'
        reported = (run_count * 2) - missing
        rows.append(
            "<tr>"
            f"<td>{task_markup}</td>"
            f"<td>{run_count}</td>"
            f"<td>{_e(_format_tokens(input_total))}</td>"
            f"<td>{_e(_format_tokens(output_total))}</td>"
            f"<td>{_e(_format_tokens(total))}</td>"
            f"<td>{reported}/{run_count * 2}</td>"
            "</tr>"
        )
    return tuple(rows)


def _task_table(snapshot: ProductionInterfaceSnapshot) -> str:
    rows = _task_rows(snapshot)
    if not rows:
        return '<div class="project-token-empty">No visible Run token records to rank by Task.</div>'
    extra = max(0, len({str(run.get("task_id") or "") for run in snapshot.runs}) - 12)
    suffix = "" if extra == 0 else f" Showing the top 12; {extra} additional visible Task group(s) are omitted."
    return (
        '<div class="project-token-table-shell"><table class="project-token-table">'
        '<caption>Tasks ordered by reported token counters in this snapshot.'
        + _e(suffix)
        + "</caption><thead><tr>"
        '<th scope="col">Task</th><th scope="col">Runs</th>'
        '<th scope="col">Input</th><th scope="col">Output</th>'
        '<th scope="col">Reported total</th><th scope="col">Counters</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _profile_rows(snapshot: ProductionInterfaceSnapshot) -> tuple[str, ...]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for run in snapshot.runs:
        raw = run.get("model_profile")
        profile = str(raw) if raw not in (None, "") else "Unspecified"
        grouped[profile].append(run)

    ranked: list[tuple[int, str, tuple[int, int, int, int, int, int]]] = []
    for profile, runs in grouped.items():
        usage = _reported_usage(runs)
        ranked.append((usage[2], profile, usage))
    ranked.sort(key=lambda item: (-item[0], item[1].casefold(), item[1]))

    rows: list[str] = []
    for _, profile, usage in ranked[:8]:
        input_total, output_total, total, run_count, complete_runs, missing = usage
        completeness = (
            "all counters reported"
            if missing == 0
            else f"{missing} counter(s) unreported"
        )
        rows.append(
            '<div class="project-token-profile">'
            f'<span class="project-token-profile-name" title="{_e(profile)}">{_e(profile)}</span>'
            f'<span class="project-token-profile-usage">{_e(_format_tokens(total))} tokens</span>'
            f'<span class="project-token-profile-meta">{run_count} Run(s) · {complete_runs} fully reported · '
            f'{_e(_format_tokens(input_total))} in · {_e(_format_tokens(output_total))} out · {_e(completeness)}</span>'
            "</div>"
        )
    return tuple(rows)


def _profiles(snapshot: ProductionInterfaceSnapshot) -> str:
    rows = _profile_rows(snapshot)
    if not rows:
        return '<div class="project-token-empty">No visible model-profile token records.</div>'
    profile_count = len(
        {
            str(run.get("model_profile"))
            if run.get("model_profile") not in (None, "")
            else "Unspecified"
            for run in snapshot.runs
        }
    )
    extra = max(0, profile_count - 8)
    note = "" if extra == 0 else f'<p class="project-token-note">Top 8 visible profiles shown; {_e(extra)} additional profile(s) omitted.</p>'
    return '<div class="project-token-profiles">' + "".join(rows) + "</div>" + note


def _int_value(value: object, fallback: int) -> int:
    return value if type(value) is int and value >= 0 else fallback


def _panel(snapshot: ProductionInterfaceSnapshot) -> str:
    input_total, output_total, total, run_count, complete_runs, missing = _reported_usage(
        snapshot.runs
    )
    total_runs = _int_value(snapshot.total_counts.get("runs"), run_count)
    runs_truncated = bool(snapshot.truncated.get("runs"))

    if runs_truncated:
        coverage_badge = "Visible Runs only"
        coverage = (
            f"Run coverage is bounded: {run_count} of {total_runs} project Runs are visible. "
            "Reported token totals below are not project-wide."
        )
    else:
        coverage_badge = "All project Runs visible"
        coverage = f"Run coverage is complete for this snapshot: all {run_count} project Runs are visible."

    if missing:
        counter_note = (
            f" {missing} input/output token counter(s) are unreported; known counters are summed, "
            "and missing values are never imputed."
        )
    else:
        counter_note = " Every visible Run input/output token counter is reported."

    return (
        '<section id="project-tokens" class="project-tokens" aria-label="Project token telemetry">'
        '<div class="project-tokens-heading"><div><h2>Project token telemetry</h2>'
        '<p>Local inference consumption from durable Run counters. No currency conversion or latency estimate is inferred.</p>'
        f'</div><span class="project-token-coverage">{_e(coverage_badge)}</span></div>'
        '<div class="project-token-summary">'
        '<div class="project-token-metric project-token-total">'
        f'<strong>{_e(_format_tokens(total))}</strong><span>Reported tokens</span></div>'
        '<div class="project-token-metric">'
        f'<strong>{_e(_format_tokens(input_total))}</strong><span>Input tokens</span></div>'
        '<div class="project-token-metric">'
        f'<strong>{_e(_format_tokens(output_total))}</strong><span>Output tokens</span></div>'
        '<div class="project-token-metric">'
        f'<strong>{run_count}</strong><span>Visible Runs</span></div>'
        '<div class="project-token-metric">'
        f'<strong>{complete_runs}/{run_count}</strong><span>Fully reported Runs</span></div>'
        '<div class="project-token-metric">'
        f'<strong>{missing}</strong><span>Missing counters</span></div>'
        "</div>"
        f'<p class="project-token-note">{_e(coverage + counter_note)}</p>'
        '<div class="project-token-columns">'
        '<section class="project-token-block" aria-label="Task token ranking"><h3>Task usage</h3>'
        + _task_table(snapshot)
        + "</section>"
        '<section class="project-token-block" aria-label="Model profile token ranking"><h3>Model profiles</h3>'
        + _profiles(snapshot)
        + "</section></div></section>"
    )


def decorate_project_tokens(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _PROJECT_TOKENS_CSS + _STYLE_MARKER)
    page = _replace_once(
        page,
        _INDEX_MARKER,
        _INDEX_MARKER + '<a href="#project-tokens">Tokens</a>',
    )
    return _replace_once(page, _INDEX_MARKER, _panel(snapshot) + _INDEX_MARKER)
