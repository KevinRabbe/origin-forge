from __future__ import annotations

from html import escape

from .conversation_blender_task_acceptance_actions import (
    BlenderTaskAcceptanceActionView,
    ConversationBlenderTaskAcceptanceActions,
)


_STYLE_END = "</style>"
_CHAT_START = '<section class="workspace-panel" aria-label="Chat workspace">'
_USAGE_START = '<aside class="workspace-usage" aria-label="Task token telemetry">'
_COMPOSER_START = '<div class="workspace-composer">'
_ACTION_CSS = """
.workspace-actions {
  margin-top: .75rem;
  padding: .72rem;
  border: 1px solid var(--line);
  border-radius: .62rem;
  background: rgba(255,255,255,.018);
}
.workspace-actions h3 {
  margin: 0;
  font-size: .72rem;
  color: var(--muted);
}
.workspace-actions-intro,
.workspace-action-note {
  margin: .38rem 0 0;
  color: var(--subtle);
  font-size: .67rem;
  line-height: 1.45;
}
.workspace-action-list {
  display: grid;
  gap: .58rem;
  margin-top: .58rem;
}
.workspace-action-card {
  min-width: 0;
  padding-top: .58rem;
  border-top: 1px solid var(--line);
}
.workspace-action-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .42rem;
}
.workspace-action-head a,
.workspace-action-head code,
.workspace-action-facts code {
  overflow-wrap: anywhere;
}
.workspace-action-head a { color: var(--text); font-size: .67rem; }
.workspace-action-head code { color: var(--subtle); font-size: .61rem; }
.workspace-action-status {
  display: inline-flex;
  width: max-content;
  padding: .14rem .3rem;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--muted);
  font-size: .57rem;
  font-weight: 760;
  letter-spacing: .035em;
}
.workspace-action-status.eligible { border-color: #6b592f; color: #ecd28d; }
.workspace-action-status.accepted { border-color: #365442; color: #a8ddb9; }
.workspace-action-status.conflict { border-color: #70403e; color: #efaaa5; }
.workspace-action-facts {
  display: grid;
  grid-template-columns: minmax(0, .65fr) minmax(0, 1.35fr);
  gap: .26rem .55rem;
  margin: .48rem 0 0;
  font-size: .61rem;
}
.workspace-action-facts dt { color: var(--subtle); }
.workspace-action-facts dd { min-width: 0; margin: 0; color: var(--muted); overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .workspace-action-facts { grid-template-columns: 1fr; }
}
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _status_class(action: BlenderTaskAcceptanceActionView) -> str:
    if action.status.value == "STALE_OR_CONFLICTING":
        return "conflict"
    if action.status.value == "ACCEPTED_TASK_SUCCEEDED":
        return "accepted"
    if action.acceptance_eligible:
        return "eligible"
    return ""


def _fact(label: str, value: object | None) -> str:
    if value is None:
        return ""
    return f"<dt>{_e(label)}</dt><dd><code>{_e(value)}</code></dd>"


def _render_action(action: BlenderTaskAcceptanceActionView) -> str:
    execution = (
        f"<code>{_e(action.execution_id)}</code>"
        if action.execution_id is not None
        else "<code>ambiguous execution</code>"
    )
    facts = "".join(
        (
            _fact("Adopted Artifact", action.adopted_artifact_id),
            _fact("Destination", action.adopted_destination_path),
            _fact("Accepted hash", action.accepted_content_hash),
            _fact("Byte count", action.accepted_byte_count),
            _fact("MODEL3D request", action.model3d_request_id),
            _fact("Task Verification", action.task_verification_id),
            _fact("Task revision", action.task_revision),
        )
    )
    detail = (
        f'<p class="workspace-action-note">{_e(action.detail)}</p>'
        if action.detail
        else ""
    )
    if action.status.value == "NOT_ACCEPTED":
        guidance = (
            '<p class="workspace-action-note">Eligible for explicit human acceptance. '
            "Confirmation controls are intentionally unavailable in this read-only gate. "
            "Acceptance does not sign provenance or authorize release.</p>"
        )
    elif action.status.value == "ACCEPTED_PENDING_TASK_TRANSITION":
        guidance = (
            '<p class="workspace-action-note">Recovery requires a separate explicit human '
            "action; this page will not retry automatically.</p>"
        )
    else:
        guidance = ""
    return (
        '<article class="workspace-action-card">'
        '<div class="workspace-action-head">'
        f'<a href="/task/{_e(action.task_id)}">{_e(action.task_id)}</a>'
        f"{execution}"
        f'<span class="workspace-action-status {_status_class(action)}">{_e(action.status.value)}</span>'
        "</div>"
        f'<dl class="workspace-action-facts">{facts}</dl>'
        f"{detail}{guidance}</article>"
    )


def render_blender_task_acceptance_actions(
    state: ConversationBlenderTaskAcceptanceActions,
) -> str:
    if not isinstance(state, ConversationBlenderTaskAcceptanceActions):
        raise TypeError("state must be ConversationBlenderTaskAcceptanceActions")
    if state.actions:
        body = '<div class="workspace-action-list">' + "".join(
            _render_action(action) for action in state.actions
        ) + "</div>"
    else:
        body = (
            '<p class="workspace-action-note">No conversation-linked Blender production '
            "Task acceptance state is available.</p>"
        )
    notes = ""
    if state.actions_truncated:
        notes += (
            '<p class="workspace-action-note">Only the bounded first set of Blender '
            "acceptance actions is shown.</p>"
        )
    if state.task_references_truncated:
        notes += (
            '<p class="workspace-action-note">Conversation Task references are truncated; '
            "only the bounded live Task set was considered.</p>"
        )
    return (
        '<section class="workspace-actions" data-blender-acceptance-actions '
        'aria-label="Blender Task acceptance status">'
        "<h3>Blender Task acceptance</h3>"
        '<p class="workspace-actions-intro">Read-only Phase-53 status derived from exact '
        "Tasks linked to this conversation.</p>"
        f"{body}{notes}</section>"
    )


def decorate_blender_task_acceptance_actions(
    page: str,
    state: ConversationBlenderTaskAcceptanceActions,
) -> str:
    if not isinstance(page, str):
        raise TypeError("page must be a string")
    if not isinstance(state, ConversationBlenderTaskAcceptanceActions):
        raise TypeError("state must be ConversationBlenderTaskAcceptanceActions")

    start = page.find(_CHAT_START)
    usage = page.find(_USAGE_START, start + len(_CHAT_START))
    if start < 0 or usage < 0 or usage <= start:
        raise ValueError("conversation action workspace boundaries are missing")
    panel = page[start:usage]
    composer = panel.find(_COMPOSER_START)
    if composer < 0:
        raise ValueError("conversation action composer marker is missing")
    markup = render_blender_task_acceptance_actions(state)
    panel = panel[:composer] + markup + panel[composer:]
    page = page[:start] + panel + page[usage:]
    if _STYLE_END not in page:
        raise ValueError("conversation action style marker is missing")
    return page.replace(_STYLE_END, _ACTION_CSS + _STYLE_END, 1)
