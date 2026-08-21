from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Iterable, Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot
from . import production_interface_workspace as workspace


_STYLE_MARKER = "</style>"
_INDEX_MARKER = '<nav class="section-nav" aria-label="Cockpit sections">'
_DETAIL_TABLE_MARKER = '<div class="table-shell"><table>'
_RUN_TIMING_CSS = """
.run-timing {
  margin: 0 0 1.2rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .82rem;
  background: rgba(16, 20, 25, .86);
  box-shadow: var(--shadow);
}
.run-timing-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .85rem;
}
.run-timing-heading h2 {
  margin: 0;
  padding: 0;
  font-size: 1rem;
}
.run-timing-heading p {
  margin: .28rem 0 0;
  max-width: 760px;
  color: var(--subtle);
  font-size: .76rem;
}
.run-timing-badge {
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
.run-timing-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .55rem;
  margin-bottom: .8rem;
}
.run-timing-metric {
  min-width: 0;
  padding: .72rem;
  border: 1px solid var(--line);
  border-radius: .6rem;
  background: rgba(255, 255, 255, .018);
}
.run-timing-metric strong {
  display: block;
  color: var(--text);
  font-size: 1.08rem;
  letter-spacing: -.025em;
  overflow-wrap: anywhere;
}
.run-timing-metric span {
  display: block;
  margin-top: .2rem;
  color: var(--subtle);
  font-size: .61rem;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.run-timing-primary {
  border-color: #4a3829;
  background: linear-gradient(145deg, rgba(240, 163, 91, .08), rgba(24, 29, 36, .68));
}
.run-timing-primary strong { color: #f5bd88; }
.run-timing-note {
  margin: 0 0 .8rem;
  padding: .65rem .72rem;
  border-left: 2px solid var(--line-strong);
  color: var(--muted);
  background: rgba(255, 255, 255, .012);
  font-size: .71rem;
  line-height: 1.5;
}
.run-timing-list {
  display: grid;
  gap: .5rem;
}
.run-timing-row {
  display: grid;
  grid-template-columns: minmax(160px, 1.25fr) minmax(100px, .65fr) minmax(100px, .65fr) minmax(100px, .65fr) minmax(120px, .7fr);
  gap: .55rem;
  align-items: center;
  min-width: 0;
  padding: .62rem .68rem;
  border: 1px solid var(--line);
  border-radius: .58rem;
  background: rgba(255, 255, 255, .014);
}
.run-timing-row a,
.run-timing-row code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-timing-cell {
  min-width: 0;
  color: var(--muted);
  font-size: .68rem;
  overflow-wrap: anywhere;
}
.run-timing-cell strong {
  display: block;
  margin-bottom: .16rem;
  color: var(--subtle);
  font-size: .56rem;
  font-weight: 720;
  letter-spacing: .055em;
  text-transform: uppercase;
}
.run-timing-empty {
  padding: 1rem;
  color: var(--subtle);
  text-align: center;
  font-size: .72rem;
}
@media (max-width: 980px) {
  .run-timing-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .run-timing-row { grid-template-columns: minmax(160px, 1fr) repeat(2, minmax(100px, .6fr)); }
  .run-timing-row .run-timing-cell:nth-child(4),
  .run-timing-row .run-timing-cell:nth-child(5) { grid-column: auto; }
}
@media (max-width: 680px) {
  .run-timing-heading { flex-direction: column; }
  .run-timing-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .run-timing-row { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit Run timing marker is missing")
    return page.replace(old, new, 1)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _elapsed_seconds(run: Mapping[str, object]) -> float | None:
    started = _parse_timestamp(run.get("started_at"))
    ended = _parse_timestamp(run.get("ended_at"))
    if started is None or ended is None:
        return None
    elapsed = (ended - started).total_seconds()
    if elapsed < 0:
        return None
    return elapsed


def _duration_state(run: Mapping[str, object]) -> str:
    if run.get("ended_at") in (None, ""):
        return "OPEN" if _parse_timestamp(run.get("started_at")) is not None else "UNREPORTED"
    return "COMPLETE" if _elapsed_seconds(run) is not None else "UNREPORTED"


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "Unreported"
    if seconds < 60:
        return f"{seconds:.2f} s"
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _format_run_elapsed(run: Mapping[str, object]) -> str:
    state = _duration_state(run)
    if state == "OPEN":
        return "Open — no end timestamp"
    return _format_elapsed(_elapsed_seconds(run))


def _reported_tokens(run: Mapping[str, object]) -> str:
    input_count = workspace._token_count(run.get("input_token_count"))
    output_count = workspace._token_count(run.get("output_token_count"))
    if input_count is None or output_count is None:
        known = (input_count or 0) + (output_count or 0)
        return f"{workspace._format_tokens(known)} known · partial"
    return workspace._format_tokens(input_count + output_count)


def _timing_summary(
    runs: Iterable[Mapping[str, object]],
) -> tuple[float, int, int, int, int]:
    total_seconds = 0.0
    completed = 0
    open_count = 0
    unreported = 0
    count = 0
    for run in runs:
        count += 1
        state = _duration_state(run)
        if state == "COMPLETE":
            elapsed = _elapsed_seconds(run)
            if elapsed is None:
                unreported += 1
            else:
                completed += 1
                total_seconds += elapsed
        elif state == "OPEN":
            open_count += 1
        else:
            unreported += 1
    return total_seconds, count, completed, open_count, unreported


def _run_key(run: Mapping[str, object]) -> tuple[str, str]:
    return str(run.get("started_at") or ""), str(run.get("id") or "")


def _task_link(
    snapshot: ProductionInterfaceSnapshot,
    task_id: object,
) -> str:
    normalized = str(task_id or "")
    if normalized and any(str(task.get("id") or "") == normalized for task in snapshot.tasks):
        return f'<a href="/task/{_e(normalized)}"><code>{_e(normalized)}</code></a>'
    return f'<code>{_e(normalized or "Unlinked")}</code>'


def _run_row(snapshot: ProductionInterfaceSnapshot, run: Mapping[str, object]) -> str:
    run_id = str(run.get("id") or "")
    return (
        '<div class="run-timing-row">'
        '<span class="run-timing-cell"><strong>Run</strong>'
        f'<a href="/run/{_e(run_id)}"><code>{_e(run_id)}</code></a></span>'
        '<span class="run-timing-cell"><strong>Elapsed</strong>'
        f'{_e(_format_run_elapsed(run))}</span>'
        '<span class="run-timing-cell"><strong>Tokens</strong>'
        f'{_e(_reported_tokens(run))}</span>'
        '<span class="run-timing-cell"><strong>Model profile</strong>'
        f'{_e(run.get("model_profile") or "Unspecified")}</span>'
        '<span class="run-timing-cell"><strong>Task / status</strong>'
        + _task_link(snapshot, run.get("task_id"))
        + f' · {_e(run.get("status"))}</span>'
        "</div>"
    )


def _panel(
    snapshot: ProductionInterfaceSnapshot,
    runs: tuple[Mapping[str, object], ...],
    *,
    title: str,
    exact_task: bool,
) -> str:
    total_seconds, run_count, completed, open_count, unreported = _timing_summary(runs)
    ordered = tuple(sorted(runs, key=_run_key, reverse=True))
    shown = ordered[:10]
    rows = "".join(_run_row(snapshot, run) for run in shown)
    if not rows:
        rows = '<div class="run-timing-empty">No visible Runs have timing records in this scope.</div>'

    if exact_task:
        coverage_badge = "Exact Task Runs"
        coverage = (
            "Only Runs linked to the selected Task are included. Snapshot Run bounds may still omit older linked Runs."
            if snapshot.truncated.get("runs")
            else "All visible Runs linked to the selected Task are included."
        )
    elif snapshot.truncated.get("runs"):
        coverage_badge = "Visible Runs only"
        coverage = "The Run projection is bounded, so timing totals are visible-snapshot-only and not project-wide."
    else:
        coverage_badge = "All project Runs visible"
        coverage = "All project Runs are visible in this snapshot."

    omitted = max(0, len(ordered) - len(shown))
    omitted_note = "" if omitted == 0 else f" The list shows the 10 most recent; {omitted} additional visible Run(s) are omitted."
    note = (
        f"{coverage} Summed elapsed time is the sum of {completed} completed Run duration(s), not wall-clock time; concurrent Runs can overlap. "
        "No generation throughput is inferred from these timestamps."
        + omitted_note
    )

    return (
        '<section id="run-timing" class="run-timing" aria-label="Run timing telemetry">'
        '<div class="run-timing-heading"><div>'
        f'<h2>{_e(title)}</h2>'
        '<p>Recorded execution time from durable Run start/end timestamps, shown beside durable token counters.</p>'
        f'</div><span class="run-timing-badge">{_e(coverage_badge)}</span></div>'
        '<div class="run-timing-summary">'
        '<div class="run-timing-metric run-timing-primary">'
        f'<strong>{_e(_format_elapsed(total_seconds))}</strong><span>Summed completed elapsed</span></div>'
        '<div class="run-timing-metric">'
        f'<strong>{run_count}</strong><span>Visible Runs</span></div>'
        '<div class="run-timing-metric">'
        f'<strong>{completed}</strong><span>Completed durations</span></div>'
        '<div class="run-timing-metric">'
        f'<strong>{open_count}</strong><span>Open durations</span></div>'
        '<div class="run-timing-metric">'
        f'<strong>{unreported}</strong><span>Unreported durations</span></div>'
        "</div>"
        f'<p class="run-timing-note">{_e(note)}</p>'
        f'<div class="run-timing-list">{rows}</div></section>'
    )


def decorate_overview_run_timing(
    page: str,
    snapshot: ProductionInterfaceSnapshot,
) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _RUN_TIMING_CSS + _STYLE_MARKER)
    page = _replace_once(
        page,
        _INDEX_MARKER,
        _INDEX_MARKER + '<a href="#run-timing">Run time</a>',
    )
    return _replace_once(
        page,
        _INDEX_MARKER,
        _panel(snapshot, tuple(snapshot.runs), title="Run timing", exact_task=False)
        + _INDEX_MARKER,
    )


def decorate_task_run_timing(
    page: str,
    snapshot: ProductionInterfaceSnapshot,
    *,
    task_id: str,
) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    runs = tuple(
        run for run in snapshot.runs if str(run.get("task_id") or "") == task_id
    )
    page = _replace_once(page, _STYLE_MARKER, _RUN_TIMING_CSS + _STYLE_MARKER)
    return _replace_once(
        page,
        _DETAIL_TABLE_MARKER,
        _panel(snapshot, runs, title="Task Run timing", exact_task=True)
        + _DETAIL_TABLE_MARKER,
    )
