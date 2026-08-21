from __future__ import annotations

from html import escape

from .production_interface_snapshot import ProductionInterfaceSnapshot


_CLASSIC_NAV = (
    '<body><nav><a href="/">Overview</a>'
    '<a href="/api/snapshot">Snapshot JSON</a></nav>'
)
_READ_ONLY_COPY = (
    '<p class="muted">Read-only projection. Visible evidence does not grant mutation '
    'or verification authority.</p>'
)
_THEME_CSS = """
:root {
  color-scheme: dark;
  --bg: #0b0d10;
  --panel: #12161b;
  --panel-raised: #181d24;
  --panel-soft: #101419;
  --line: #29313b;
  --line-strong: #3b4653;
  --text: #f3f5f7;
  --muted: #9aa5b1;
  --subtle: #737f8c;
  --accent: #f0a35b;
  --accent-soft: rgba(240, 163, 91, .12);
  --good: #76c893;
  --warn: #f6c85f;
  --code: #cbd5df;
  --shadow: 0 18px 45px rgba(0, 0, 0, .24);
}
* { box-sizing: border-box; }
html { background: var(--bg); scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  background:
    radial-gradient(circle at 85% -10%, rgba(240, 163, 91, .10), transparent 32rem),
    linear-gradient(180deg, #0d1014 0%, var(--bg) 26rem);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}
a { color: #e9eef3; text-decoration-color: #56616d; text-underline-offset: .2em; }
a:hover { color: #fff; text-decoration-color: var(--accent); }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
.skip-link {
  position: absolute;
  left: 1rem;
  top: -4rem;
  z-index: 100;
  padding: .65rem .9rem;
  border: 1px solid var(--line-strong);
  border-radius: .5rem;
  background: var(--panel-raised);
}
.skip-link:focus { top: 1rem; }
.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid rgba(59, 70, 83, .75);
  background: rgba(11, 13, 16, .92);
  backdrop-filter: blur(14px);
}
.app-header-inner {
  width: min(1480px, calc(100% - 2rem));
  min-height: 68px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 1rem;
}
.brand {
  display: flex;
  align-items: center;
  gap: .72rem;
  min-width: max-content;
}
.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid #714a2b;
  border-radius: 9px;
  background: linear-gradient(145deg, #2a1d14, #12161b 70%);
  box-shadow: inset 0 0 0 1px rgba(240, 163, 91, .08);
  color: var(--accent);
  font: 700 .69rem/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: .08em;
}
.brand-copy { display: grid; line-height: 1.08; }
.brand-name { font-weight: 720; letter-spacing: -.02em; }
.brand-subtitle { margin-top: .22rem; color: var(--subtle); font-size: .74rem; text-transform: uppercase; letter-spacing: .09em; }
.app-nav { margin-left: auto; display: flex; align-items: center; gap: .25rem; }
.app-nav a {
  padding: .48rem .68rem;
  border-radius: .45rem;
  color: var(--muted);
  font-size: .88rem;
  text-decoration: none;
}
.app-nav a:hover, .app-nav a[aria-current="page"] { background: var(--panel-raised); color: var(--text); }
.mode-badge {
  display: inline-flex;
  align-items: center;
  gap: .42rem;
  margin-left: .45rem;
  padding: .34rem .58rem;
  border: 1px solid #365442;
  border-radius: 999px;
  color: #a8ddb9;
  background: rgba(58, 105, 73, .12);
  font-size: .73rem;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
}
.mode-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--good); box-shadow: 0 0 0 3px rgba(118, 200, 147, .1); }
.cockpit-main { width: min(1480px, calc(100% - 2rem)); margin: 0 auto; padding: 3rem 0 5rem; }
.cockpit-main > h1 {
  margin: 0 0 .55rem;
  max-width: 900px;
  font-size: clamp(2rem, 5vw, 3.55rem);
  line-height: 1.02;
  letter-spacing: -.045em;
}
.eyebrow { margin-bottom: .72rem; color: var(--accent); font-size: .76rem; font-weight: 760; letter-spacing: .13em; text-transform: uppercase; }
.identity-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .75rem;
  max-width: 980px;
  margin: 1.45rem 0 1rem;
}
.identity-item {
  min-width: 0;
  padding: .9rem 1rem;
  border: 1px solid var(--line);
  border-radius: .65rem;
  background: rgba(18, 22, 27, .72);
}
.identity-label { display: block; margin-bottom: .28rem; color: var(--subtle); font-size: .69rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.authority-banner {
  max-width: 980px;
  margin: 1rem 0 1.4rem;
  padding: .85rem 1rem;
  border-left: 3px solid var(--good);
  border-radius: 0 .55rem .55rem 0;
  background: rgba(118, 200, 147, .07);
  color: #c8d3cc;
}
.authority-banner strong { color: #dff2e5; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .75rem;
  margin: 2.15rem 0 1rem;
}
.metric {
  min-width: 0;
  min-height: 102px;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .72rem;
  background: linear-gradient(180deg, rgba(24, 29, 36, .92), rgba(16, 20, 25, .92));
  box-shadow: 0 1px 0 rgba(255,255,255,.025) inset;
}
.metric-value { display: block; font-size: 1.75rem; font-weight: 740; letter-spacing: -.035em; }
.metric-label { display: block; margin-top: .28rem; color: var(--muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .075em; }
.section-nav {
  display: flex;
  gap: .45rem;
  margin: .95rem 0 2.25rem;
  padding: .6rem;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: .72rem;
  background: rgba(16, 20, 25, .74);
}
.section-nav a { flex: 0 0 auto; padding: .42rem .64rem; border-radius: .42rem; color: var(--muted); font-size: .82rem; text-decoration: none; }
.section-nav a:hover { background: var(--panel-raised); color: var(--text); }
h2 {
  margin: 3.1rem 0 1rem;
  padding-top: .25rem;
  color: #f1f4f6;
  font-size: 1.12rem;
  letter-spacing: -.015em;
  scroll-margin-top: 90px;
}
h3 { margin: 1.6rem 0 .8rem; color: #dce2e7; font-size: .92rem; }
p { color: #c5cdd5; }
.muted { color: var(--muted); opacity: 1; }
.warn {
  max-width: 980px;
  padding: .85rem 1rem;
  border: 1px solid #68562d;
  border-radius: .55rem;
  background: rgba(246, 200, 95, .08);
  color: #f8dda0;
  font-weight: 650;
}
.table-shell { width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: .72rem; background: rgba(16, 20, 25, .84); box-shadow: var(--shadow); }
table { width: 100%; margin: 0; border: 0; border-collapse: collapse; font-size: .84rem; }
th, td { padding: .72rem .8rem; border: 0; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
th { position: sticky; top: 67px; z-index: 2; background: #171c22; color: #8793a0; font-size: .67rem; font-weight: 760; letter-spacing: .075em; text-transform: uppercase; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: rgba(255, 255, 255, .018); }
code {
  color: var(--code);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: .9em;
  overflow-wrap: anywhere;
}
td:first-child code { color: #f1b985; }
.breadcrumb { display: flex; align-items: center; gap: .45rem; margin-bottom: 1.15rem; color: var(--subtle); font-size: .82rem; }
.breadcrumb a { color: var(--muted); text-decoration: none; }
.detail-heading { margin-bottom: 1.6rem; }
.detail-heading h1 { margin: 0; font-size: clamp(1.9rem, 4vw, 3rem); line-height: 1.05; letter-spacing: -.04em; }
.detail-id { margin: .7rem 0 0; color: var(--muted); }
.detail-id code { color: #f1b985; }
.app-footer { width: min(1480px, calc(100% - 2rem)); margin: 0 auto; padding: 0 0 2.4rem; color: var(--subtle); font-size: .76rem; }
.app-footer-inner { padding-top: 1rem; border-top: 1px solid var(--line); }
@media (max-width: 980px) {
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .identity-grid { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .app-header-inner { width: min(100% - 1rem, 1480px); min-height: 60px; }
  .brand-subtitle { display: none; }
  .app-nav a { padding: .42rem .48rem; font-size: .78rem; }
  .mode-badge { display: none; }
  .cockpit-main { width: min(100% - 1.15rem, 1480px); padding-top: 2rem; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric { min-height: 88px; }
  th { top: 59px; }
  th, td { padding: .62rem .65rem; }
  .app-footer { width: min(100% - 1.15rem, 1480px); }
}
@media (max-width: 430px) {
  .app-nav a[href="/api/snapshot"] { display: none; }
  .metric-grid { grid-template-columns: 1fr 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("classic cockpit markup changed unexpectedly")
    return page.replace(old, new, 1)


def _inject_theme(page: str) -> str:
    start = page.find("<style>")
    end = page.find("</style>", start)
    if start < 0 or end < 0:
        raise ValueError("classic cockpit style boundary is missing")
    return page[: start + len("<style>")] + _THEME_CSS + page[end:]


def _shell_open() -> str:
    return (
        '<body><a class="skip-link" href="#main">Skip to content</a>'
        '<header class="app-header"><div class="app-header-inner">'
        '<div class="brand"><span class="brand-mark" aria-hidden="true">OF</span>'
        '<span class="brand-copy"><span class="brand-name">Origin Forge</span>'
        '<span class="brand-subtitle">Production Cockpit</span></span></div>'
        '<nav class="app-nav" aria-label="Primary">'
        '<a href="/" aria-current="page">Overview</a>'
        '<a href="/api/snapshot">Snapshot JSON</a></nav>'
        '<span class="mode-badge"><span class="mode-dot" aria-hidden="true"></span>'
        'Read only</span></div></header>'
        '<main id="main" class="cockpit-main">'
    )


def _decorate_shell(page: str) -> str:
    page = _inject_theme(page)
    page = _replace_once(page, _CLASSIC_NAV, _shell_open())
    return _replace_once(
        page,
        "</body></html>",
        '</main><footer class="app-footer"><div class="app-footer-inner">'
        'Local inspection surface · no production mutation authority'
        '</div></footer></body></html>',
    )


def _wrap_tables(page: str) -> str:
    page = page.replace("<table>", '<div class="table-shell"><table>')
    return page.replace("</table>", "</table></div>")


def _metric(label: str, value: int) -> str:
    return (
        '<div class="metric"><span class="metric-value">'
        f'{value}</span><span class="metric-label">{_e(label)}</span></div>'
    )


def _overview_index() -> str:
    return (
        '<nav class="section-nav" aria-label="Cockpit sections">'
        '<a href="#goals">Work</a><a href="#verification">Verification</a>'
        '<a href="#causal">Causal history</a><a href="#intelligence">Intelligence</a>'
        '<a href="#resources">Models &amp; resources</a><a href="#provenance">Provenance</a>'
        '<a href="#memory">Dream / memory</a></nav>'
    )


def decorate_overview(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    page = _decorate_shell(page)
    page = _replace_once(
        page,
        "<h1>Origin Forge Production Cockpit</h1>",
        '<div class="eyebrow">Local production infrastructure</div>'
        "<h1>Origin Forge Production Cockpit</h1>",
    )
    identity = (
        f'<p>Project <code>{_e(snapshot.project_id)}</code></p>'
        f'<p>Snapshot <code>{_e(snapshot.content_hash)}</code></p>'
    )
    identity_ui = (
        '<div class="identity-grid">'
        '<div class="identity-item"><span class="identity-label">Project</span>'
        f'<code>{_e(snapshot.project_id)}</code></div>'
        '<div class="identity-item"><span class="identity-label">Snapshot</span>'
        f'<code>{_e(snapshot.content_hash)}</code></div></div>'
    )
    page = _replace_once(page, identity, identity_ui)
    page = _replace_once(
        page,
        _READ_ONLY_COPY,
        '<div class="authority-banner"><strong>Read-only projection.</strong> '
        'Visible evidence does not grant mutation or verification authority.</div>',
    )
    verification_count = len(snapshot.task_verifications) + len(
        snapshot.artifact_verifications
    )
    metrics = (
        '<div class="metric-grid" aria-label="Snapshot summary">'
        + _metric("Goals", len(snapshot.goals))
        + _metric("Tasks", len(snapshot.tasks))
        + _metric("Runs", len(snapshot.runs))
        + _metric("Verifications", verification_count)
        + _metric("Artifacts", len(snapshot.artifacts))
        + "</div>"
        + _overview_index()
    )
    page = _replace_once(page, "<h2>Goals</h2>", metrics + '<h2 id="goals">Goals</h2>')
    anchors = (
        ("<h2>Task Verifications</h2>", '<h2 id="verification">Task Verifications</h2>'),
        ("<h2>Causal History — Decisions</h2>", '<h2 id="causal">Causal History — Decisions</h2>'),
        ("<h2>Project Intelligence — Entities</h2>", '<h2 id="intelligence">Project Intelligence — Entities</h2>'),
        ("<h2>Model / Resource Monitor</h2>", '<h2 id="resources">Model / Resource Monitor</h2>'),
        ("<h2>Provenance Inspector</h2>", '<h2 id="provenance">Provenance Inspector</h2>'),
        ("<h2>Dream / Memory Inspector</h2>", '<h2 id="memory">Dream / Memory Inspector</h2>'),
    )
    for old, new in anchors:
        page = _replace_once(page, old, new)
    return _wrap_tables(page)


def decorate_detail(page: str, *, kind: str, object_id: str) -> str:
    page = _decorate_shell(page)
    heading = f"<h1>{_e(kind.title())}</h1>"
    detail_heading = (
        '<div class="breadcrumb"><a href="/">Overview</a><span aria-hidden="true">/</span>'
        f"<span>{_e(kind.title())}</span></div>"
        '<div class="detail-heading">'
        f"<h1>{_e(kind.title())}</h1>"
        f'<p class="detail-id"><code>{_e(object_id)}</code></p></div>'
    )
    page = _replace_once(page, heading, detail_heading)
    return _wrap_tables(page)
