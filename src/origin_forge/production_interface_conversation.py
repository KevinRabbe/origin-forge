from __future__ import annotations

from html import escape

from .conversation_service import (
    MAX_CLIENT_SUBMISSION_ID_BYTES,
    ConversationActorType,
    ConversationSession,
    ConversationSessionStatus,
    ConversationTurn,
)


_STYLE_MARKER = "</style>"
_CHAT_START = '<section class="workspace-panel" aria-label="Chat workspace">'
_USAGE_START = '<aside class="workspace-usage" aria-label="Task token telemetry">'
_MAX_RENDERED_TURN_CONTENT_BYTES = 8 * 1024
_MAX_RENDERED_TURNS = 48
_CONVERSATION_CSS = """
.workspace-conversation-status {
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
.workspace-conversation-id {
  margin: .38rem 0 0;
  color: var(--subtle);
  font-size: .68rem;
}
.workspace-conversation-id code { color: var(--muted); }
.workspace-turn.human .workspace-avatar {
  border-color: #315c78;
  color: #a8d7f2;
  background: rgba(65, 137, 180, .08);
}
.workspace-turn.forge .workspace-avatar {
  border-color: #714a2b;
  color: #f1b985;
  background: rgba(240, 163, 91, .08);
}
.workspace-turn.system .workspace-avatar {
  border-color: #4c4f61;
  color: #c4c6d6;
}
.workspace-turn-clipped {
  display: block;
  margin-top: .45rem;
  color: var(--subtle);
  font-size: .67rem;
}
.workspace-composer form { display: grid; gap: .55rem; }
.workspace-composer label {
  color: var(--muted);
  font-size: .7rem;
  font-weight: 730;
}
.workspace-composer textarea {
  width: 100%;
  min-height: 84px;
  box-sizing: border-box;
  resize: vertical;
  padding: .72rem .78rem;
  border: 1px solid var(--line-strong);
  border-radius: .62rem;
  color: var(--text);
  background: rgba(255, 255, 255, .025);
  font: inherit;
  line-height: 1.45;
}
.workspace-composer textarea:focus-visible,
.workspace-composer button:focus-visible {
  outline: 2px solid #f0a35b;
  outline-offset: 2px;
}
.workspace-composer button {
  justify-self: start;
  padding: .55rem .8rem;
  border: 1px solid #714a2b;
  border-radius: .55rem;
  color: #f5bd88;
  background: rgba(240, 163, 91, .1);
  font: inherit;
  font-size: .76rem;
  font-weight: 760;
  cursor: pointer;
}
.workspace-composer button:hover { background: rgba(240, 163, 91, .16); }
.workspace-conversation-empty {
  display: grid;
  place-items: center;
  min-height: 220px;
  padding: 2rem;
  color: var(--subtle);
  text-align: center;
  font-size: .82rem;
}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _replace_once(page: str, old: str, new: str) -> str:
    if old not in page:
        raise ValueError("conversation workspace marker is missing")
    return page.replace(old, new, 1)


def _client_submission_id(value: str | None) -> str:
    if not isinstance(value, str):
        raise ValueError("open conversation requires a client submission id")
    encoded = value.encode("utf-8")
    if (
        not value
        or value.strip() != value
        or len(encoded) > MAX_CLIENT_SUBMISSION_ID_BYTES
    ):
        raise ValueError("client submission id is invalid")
    return value


def _clip_content(content: str) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= _MAX_RENDERED_TURN_CONTENT_BYTES:
        return content, False
    return encoded[:_MAX_RENDERED_TURN_CONTENT_BYTES].decode("utf-8", "ignore"), True


def _actor_label(actor: ConversationActorType) -> tuple[str, str]:
    if actor is ConversationActorType.HUMAN:
        return "HUMAN", "Human"
    if actor is ConversationActorType.FORGE:
        return "FORGE", "Forge"
    return "SYSTEM", "System"


def _turn_markup(turn: ConversationTurn) -> str:
    badge, label = _actor_label(turn.actor_type)
    content, clipped = _clip_content(turn.content)
    clipped_markup = (
        '<span class="workspace-turn-clipped">Display clipped to 8 KiB; '
        "the durable Turn remains unchanged.</span>"
        if clipped
        else ""
    )
    return (
        f'<article class="workspace-message workspace-turn {turn.actor_type.value.lower()}">'
        f'<div class="workspace-avatar" aria-hidden="true">{badge}</div>'
        '<div class="workspace-bubble">'
        '<div class="workspace-message-head">'
        f'<span class="workspace-message-label">{label}</span>'
        f'<span class="workspace-message-meta">#{turn.sequence} · {_e(turn.created_at)}</span>'
        "</div>"
        f'<p class="workspace-message-body">{_e(content)}</p>'
        f"{clipped_markup}"
        f'<div class="workspace-conversation-id"><code>{_e(turn.id)}</code></div>'
        "</div></article>"
    )


def _stream(turns: tuple[ConversationTurn, ...]) -> str:
    if not turns:
        return (
            '<div class="workspace-conversation-empty">'
            "No durable conversation Turns yet.</div>"
        )
    return "".join(_turn_markup(turn) for turn in turns)


def _start_session_composer() -> str:
    return (
        '<div class="workspace-composer">'
        '<form method="post" action="/conversation/session" accept-charset="UTF-8">'
        '<button type="submit">Start conversation</button>'
        "</form>"
        '<p class="workspace-composer-note">Starting a conversation creates only durable '
        "operator history. It does not create or execute production work.</p>"
        "</div>"
    )


def _send_composer(session: ConversationSession, client_submission_id: str) -> str:
    key = _client_submission_id(client_submission_id)
    return (
        '<div class="workspace-composer">'
        f'<form method="post" action="/conversation/{_e(session.id)}/turn" '
        'accept-charset="UTF-8">'
        '<label for="conversation-content">Message</label>'
        '<textarea id="conversation-content" name="content" required '
        'maxlength="65536" autocomplete="off"></textarea>'
        f'<input type="hidden" name="client_submission_id" value="{_e(key)}">'
        f'<input type="hidden" name="expected_revision" value="{session.revision}">'
        '<button type="submit">Send</button>'
        "</form>"
        '<p class="workspace-composer-note">Send commits durable human intent only. '
        "Governed application and Manager authorities remain downstream owners of "
        "production work.</p>"
        "</div>"
    )


def _conversation_panel(
    session: ConversationSession | None,
    turns: tuple[ConversationTurn, ...],
    client_submission_id: str | None,
) -> str:
    if session is None:
        if turns:
            raise ValueError("conversation Turns require a session")
        return (
            '<section class="workspace-panel" aria-label="Chat workspace">'
            '<div class="workspace-heading"><div><h2>Chat workspace</h2>'
            "<p>Durable operator conversation. Start a session before submitting intent.</p>"
            '</div><span class="workspace-conversation-status">Not started</span></div>'
            '<div class="workspace-conversation-empty">No durable conversation session '
            "exists for this project.</div>"
            f"{_start_session_composer()}</section>"
        )

    if len(turns) > _MAX_RENDERED_TURNS:
        raise ValueError("conversation Turn render limit exceeded")
    previous_sequence = 0
    for turn in turns:
        if not isinstance(turn, ConversationTurn) or turn.session_id != session.id:
            raise ValueError("conversation Turn does not belong to selected session")
        if turn.sequence <= previous_sequence:
            raise ValueError("conversation Turns are not strictly ordered")
        previous_sequence = turn.sequence

    status = session.status.value
    if session.status is ConversationSessionStatus.OPEN:
        composer = _send_composer(session, _client_submission_id(client_submission_id))
    else:
        if client_submission_id is not None:
            raise ValueError("archived conversation may not carry a submission id")
        composer = (
            '<div class="workspace-composer">'
            '<p class="workspace-composer-note">This conversation is archived and cannot '
            "accept new Turns.</p></div>"
            + _start_session_composer()
        )
    return (
        '<section class="workspace-panel" aria-label="Chat workspace">'
        '<div class="workspace-heading"><div><h2>Chat workspace</h2>'
        "<p>Durable human and Forge Turns from the governed conversation service.</p>"
        f'<p class="workspace-conversation-id">Session <code>{_e(session.id)}</code></p>'
        f'</div><span class="workspace-conversation-status">{_e(status)}</span></div>'
        f'<div class="workspace-stream">{_stream(turns)}</div>'
        f"{composer}</section>"
    )


def decorate_conversation_workspace(
    page: str,
    *,
    session: ConversationSession | None,
    turns: tuple[ConversationTurn, ...],
    client_submission_id: str | None,
) -> str:
    if not isinstance(page, str):
        raise TypeError("page must be a string")
    if session is not None and not isinstance(session, ConversationSession):
        raise TypeError("session must be a ConversationSession or None")
    if not isinstance(turns, tuple):
        raise TypeError("turns must be a tuple")

    start = page.find(_CHAT_START)
    usage = page.find(_USAGE_START, start + len(_CHAT_START))
    if start < 0 or usage < 0 or usage <= start:
        raise ValueError("conversation workspace boundaries are missing")

    panel = _conversation_panel(session, turns, client_submission_id)
    page = page[:start] + panel + page[usage:]
    return _replace_once(page, _STYLE_MARKER, _CONVERSATION_CSS + _STYLE_MARKER)
