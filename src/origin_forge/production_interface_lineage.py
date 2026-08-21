from __future__ import annotations

from html import escape
from typing import Iterable, Mapping

from .production_interface_snapshot import ProductionInterfaceSnapshot


_STYLE_MARKER = "</style>"
_NAV_MARKER = '<a href="#provenance">Provenance</a>'
_PROVENANCE_MARKER = '<h2 id="provenance">Provenance Inspector</h2>'
_LINEAGE_CSS = """
.lineage-panel {
  margin: 3.1rem 0 1.35rem;
  scroll-margin-top: 90px;
}
.lineage-panel-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 1.25rem;
  margin-bottom: 1rem;
}
.lineage-panel-head h2 {
  margin: 0;
  padding: 0;
}
.lineage-panel-copy {
  max-width: 760px;
  margin: 0;
  color: var(--subtle);
  font-size: .78rem;
  text-align: right;
}
.lineage-list {
  display: grid;
  gap: .8rem;
}
.lineage-card {
  min-width: 0;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: .78rem;
  background: rgba(16, 20, 25, .82);
  box-shadow: var(--shadow);
}
.lineage-card-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .85rem;
}
.lineage-artifact {
  min-width: 0;
}
.lineage-artifact-label,
.lineage-step-label {
  display: block;
  color: var(--subtle);
  font-size: .65rem;
  font-weight: 760;
  letter-spacing: .075em;
  text-transform: uppercase;
}
.lineage-artifact a {
  display: block;
  margin-top: .24rem;
  overflow: hidden;
  color: #f1b985;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-decoration: none;
}
.lineage-artifact-meta {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: .72rem;
  text-align: right;
}
.lineage-chain {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: .55rem;
}
.lineage-step {
  min-width: 0;
  min-height: 82px;
  padding: .72rem .75rem;
  border: 1px solid var(--line);
  border-radius: .58rem;
  background: rgba(255, 255, 255, .018);
}
.lineage-step-value {
  display: block;
  margin-top: .34rem;
  min-width: 0;
  color: var(--text);
  font-size: .76rem;
}
.lineage-step a {
  color: #e9eef3;
  text-decoration: none;
}
.lineage-step code {
  display: block;
  overflow: hidden;
  color: #f1b985;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lineage-listing {
  display: grid;
  gap: .22rem;
  margin-top: .32rem;
}
.lineage-listing-item {
  min-width: 0;
  color: var(--muted);
  font-size: .7rem;
}
.lineage-listing-item a {
  display: inline;
}
.lineage-listing-item code {
  display: inline;
}
.lineage-empty,
.lineage-missing {
  color: var(--subtle);
  font-size: .72rem;
}
.lineage-caveat {
  margin: .9rem 0 0;
  padding: .78rem .9rem;
  border-left: 3px solid var(--line-strong);
  background: rgba(255, 255, 255, .018);
  color: var(--muted);
  font-size: .75rem;
}
@media (max-width: 1180px) {
  .lineage-chain { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .lineage-panel-head, .lineage-card-head { align-items: start; flex-direction: column; }
  .lineage-panel-copy, .lineage-artifact-meta { text-align: left; }
  .lineage-chain { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 430px) {
  .lineage-chain { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("cockpit lineage marker is missing")
    return page.replace(old, new, 1)


def _by_id(rows: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        object_id = row.get("id")
        if object_id is not None:
            result[str(object_id)] = row
    return result


def _typed_ref(
    kind: str,
    object_id: object,
    available: Mapping[str, Mapping[str, object]],
) -> str:
    if object_id is None:
        return '<span class="lineage-missing">No reference</span>'
    value = str(object_id)
    if value not in available:
        return f'<code title="Referenced record is outside this snapshot">{_e(value)}</code>'
    return f'<a href="/{_e(kind)}/{_e(value)}"><code>{_e(value)}</code></a>'


def _step(label: str, value: str) -> str:
    return (
        '<div class="lineage-step">'
        f'<span class="lineage-step-label">{_e(label)}</span>'
        f'<span class="lineage-step-value">{value}</span></div>'
    )


def _verification_step(
    artifact_id: str,
    rows: tuple[Mapping[str, object], ...],
) -> str:
    matching = tuple(row for row in rows if str(row.get("target_id")) == artifact_id)
    if not matching:
        return _step("Verification", '<span class="lineage-empty">No records</span>')
    items = []
    for row in matching:
        object_id = row.get("id")
        status = row.get("status")
        verification_type = row.get("verification_type")
        items.append(
            '<span class="lineage-listing-item">'
            f'<a href="/verification/{_e(object_id)}"><code>{_e(object_id)}</code></a> '
            f'· {_e(verification_type)} · {_e(status)}</span>'
        )
    return _step(
        "Verification",
        f'{len(matching)} record(s)<span class="lineage-listing">'
        + "".join(items)
        + "</span>",
    )


def _manifest_rows(snapshot: ProductionInterfaceSnapshot) -> tuple[Mapping[str, object], ...]:
    values = snapshot.provenance.get("manifests")
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, Mapping))


def _provenance_step(
    artifact_id: str,
    manifests: tuple[Mapping[str, object], ...],
) -> str:
    matching = tuple(row for row in manifests if str(row.get("artifact_id")) == artifact_id)
    if not matching:
        return _step("Provenance", '<span class="lineage-empty">No manifest in snapshot</span>')
    items = []
    for row in matching:
        manifest_id = row.get("manifest_id")
        signing_key_id = row.get("signing_key_id")
        items.append(
            '<span class="lineage-listing-item">'
            f'<code>{_e(manifest_id)}</code> · key <code>{_e(signing_key_id)}</code>'
            "</span>"
        )
    return _step(
        "Provenance",
        f'{len(matching)} manifest(s)<span class="lineage-listing">'
        + "".join(items)
        + "</span>",
    )


def _artifact_card(
    artifact: Mapping[str, object],
    *,
    tasks: Mapping[str, Mapping[str, object]],
    runs: Mapping[str, Mapping[str, object]],
    changes: Mapping[str, Mapping[str, object]],
    verifications: tuple[Mapping[str, object], ...],
    manifests: tuple[Mapping[str, object], ...],
) -> str:
    artifact_id = str(artifact.get("id"))
    change_id = artifact.get("change_id")
    change = changes.get(str(change_id)) if change_id is not None else None
    task_id = change.get("task_id") if change is not None else None
    run_id = artifact.get("created_by_run_id")
    if run_id is None and change is not None:
        run_id = change.get("run_id")
    artifact_type = artifact.get("type")
    artifact_status = artifact.get("status")
    return (
        '<article class="lineage-card">'
        '<div class="lineage-card-head">'
        '<div class="lineage-artifact"><span class="lineage-artifact-label">Artifact lineage</span>'
        f'<a href="/artifact/{_e(artifact_id)}"><code>{_e(artifact_id)}</code></a></div>'
        f'<div class="lineage-artifact-meta">{_e(artifact_type)} · {_e(artifact_status)}</div>'
        '</div><div class="lineage-chain">'
        + _step("Task", _typed_ref("task", task_id, tasks))
        + _step("Run", _typed_ref("run", run_id, runs))
        + _step("Change", _typed_ref("change", change_id, changes))
        + _step(
            "Artifact",
            f'<a href="/artifact/{_e(artifact_id)}"><code>{_e(artifact_id)}</code></a>',
        )
        + _verification_step(artifact_id, verifications)
        + _provenance_step(artifact_id, manifests)
        + "</div></article>"
    )


def _panel(snapshot: ProductionInterfaceSnapshot) -> str:
    tasks = _by_id(snapshot.tasks)
    runs = _by_id(snapshot.runs)
    changes = _by_id(snapshot.changes)
    verifications = tuple(snapshot.artifact_verifications)
    manifests = _manifest_rows(snapshot)
    if snapshot.artifacts:
        cards = "".join(
            _artifact_card(
                artifact,
                tasks=tasks,
                runs=runs,
                changes=changes,
                verifications=verifications,
                manifests=manifests,
            )
            for artifact in snapshot.artifacts
        )
    else:
        cards = (
            '<div class="lineage-card"><span class="lineage-empty">'
            'No artifact records are present in this snapshot.</span></div>'
        )
    truncation_note = ""
    if snapshot.truncated.get("artifacts") or snapshot.truncated.get("provenance_manifests"):
        truncation_note = (
            '<p class="lineage-caveat">One or more lineage inputs are truncated by cockpit '
            'snapshot limits; a missing related record may exist outside this projection.</p>'
        )
    return (
        '<section id="lineage" class="lineage-panel" aria-label="Evidence and lineage">'
        '<div class="lineage-panel-head"><h2>Evidence &amp; lineage</h2>'
        '<p class="lineage-panel-copy">Snapshot-derived joins across production records. '
        'Visibility does not grant execution, verification, mutation, or trust authority.</p>'
        '</div><div class="lineage-list">'
        + cards
        + "</div>"
        + truncation_note
        + '<p class="lineage-caveat">Provenance shown here is display context only. The cockpit '
        'does not perform Ed25519 trust verification, artifact-currentness verification, or '
        'artifact-byte reads.</p></section>'
    )


def decorate_lineage(page: str, snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    page = _replace_once(page, _STYLE_MARKER, _LINEAGE_CSS + _STYLE_MARKER)
    page = _replace_once(
        page,
        _NAV_MARKER,
        '<a href="#lineage">Evidence &amp; lineage</a>' + _NAV_MARKER,
    )
    return _replace_once(page, _PROVENANCE_MARKER, _panel(snapshot) + _PROVENANCE_MARKER)
