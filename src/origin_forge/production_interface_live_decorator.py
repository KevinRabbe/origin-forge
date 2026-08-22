from __future__ import annotations

from html import escape

from .conversation_live import ConversationLiveState
from .production_interface_live import (
    CONVERSATION_LIVE_SCRIPT,
    live_payload,
    render_live_activity,
    render_live_telemetry,
)


_STYLE_END = "</style>"
_BODY_END = "</body>"
_CHAT_START = '<section class="workspace-panel" aria-label="Chat workspace">'
_USAGE_START = '<aside class="workspace-usage" aria-label="Task token telemetry">'
_COMPOSER_START = '<div class="workspace-composer">'
_SCRIPT_PATH = "/assets/conversation-live.js"
_LIVE_CSS = """
.workspace-live-connection {
  display: inline-flex;
  margin: .42rem 0 0;
  color: var(--subtle);
  font-size: .67rem;
}
.workspace-live-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr);
  gap: .7rem;
  margin-top: .75rem;
}
.workspace-live-block {
  min-width: 0;
  padding: .68rem .72rem;
  border: 1px solid var(--line);
  border-radius: .62rem;
  background: rgba(255,255,255,.018);
}
.workspace-live-block h3 {
  margin: 0 0 .5rem;
  font-size: .72rem;
  color: var(--muted);
}
.workspace-live-empty,
.workspace-live-note {
  margin: .35rem 0 0;
  color: var(--subtle);
  font-size: .67rem;
  line-height: 1.45;
}
.workspace-live-list,
.workspace-live-runs {
  display: grid;
  gap: .38rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.workspace-live-list li {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: center;
  gap: .38rem;
  min-width: 0;
}
.workspace-live-list strong { font-size: .68rem; }
.workspace-live-list small {
  overflow: hidden;
  color: var(--subtle);
  font-size: .61rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workspace-live-status {
  display: inline-flex;
  width: max-content;
  padding: .14rem .3rem;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--muted);
  font-size: .57rem;
  font-weight: 760;
  letter-spacing: .045em;
}
.workspace-live-status.responded { border-color: #365442; color: #a8ddb9; }
.workspace-live-status.processing { border-color: #6b592f; color: #ecd28d; }
.workspace-live-status.failed { border-color: #70403e; color: #efaaa5; }
.workspace-live-task + .workspace-live-task {
  margin-top: .58rem;
  padding-top: .58rem;
  border-top: 1px solid var(--line);
}
.workspace-live-task-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .42rem;
}
.workspace-live-task-head a {
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: .67rem;
}
.workspace-live-runs { margin-top: .45rem; }
.workspace-live-runs li {
  display: grid;
  grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr);
  gap: .4rem;
  color: var(--subtle);
  font-size: .61rem;
}
.workspace-live-runs code { overflow-wrap: anywhere; color: var(--muted); }
@media (max-width: 760px) {
  .workspace-live-grid { grid-template-columns: 1fr; }
  .workspace-live-list li { grid-template-columns: auto auto; }
  .workspace-live-list small { grid-column: 1 / -1; }
  .workspace-live-runs li { grid-template-columns: 1fr; }
}
"""


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("live conversation marker is missing")
    return page.replace(old, new, 1)


def decorate_live_conversation(page: str, state: ConversationLiveState) -> str:
    if not isinstance(page, str):
        raise TypeError("page must be a string")
    if not isinstance(state, ConversationLiveState):
        raise TypeError("state must be a ConversationLiveState")

    start = page.find(_CHAT_START)
    usage = page.find(_USAGE_START, start + len(_CHAT_START))
    if start < 0 or usage < 0 or usage <= start:
        raise ValueError("live conversation workspace boundaries are missing")
    panel = page[start:usage]
    composer = panel.find(_COMPOSER_START)
    if composer < 0:
        raise ValueError("live conversation composer marker is missing")

    payload = live_payload(state)
    content_hash = payload["content_hash"]
    if not isinstance(content_hash, str):
        raise ValueError("live conversation hash is invalid")
    session_id = escape(state.session.id, quote=True)
    enhanced_start = (
        '<section class="workspace-panel" aria-label="Chat workspace" '
        f'data-conversation-live-url="/api/conversation/live/{session_id}" '
        f'data-live-hash="{escape(content_hash, quote=True)}">'
    )
    panel = panel.replace(_CHAT_START, enhanced_start, 1)
    composer = panel.find(_COMPOSER_START)
    live_markup = (
        '<span class="workspace-live-connection" data-live-connection '
        'aria-live="polite">Live ready</span>'
        '<div class="workspace-live-grid">'
        f"{render_live_activity(state)}"
        f"{render_live_telemetry(state)}"
        "</div>"
    )
    panel = panel[:composer] + live_markup + panel[composer:]
    page = page[:start] + panel + page[usage:]
    page = _replace_once(page, _STYLE_END, _LIVE_CSS + _STYLE_END)
    page = _replace_once(
        page,
        _BODY_END,
        f'<script src="{_SCRIPT_PATH}" defer></script>{_BODY_END}',
    )
    return page


def live_script_bytes() -> bytes:
    return CONVERSATION_LIVE_SCRIPT.encode("utf-8")
