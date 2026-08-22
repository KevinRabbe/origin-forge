from __future__ import annotations

import hashlib
import json
from html import escape

from .conversation_live import ConversationLiveState


LIVE_SCHEMA_VERSION = 1
MAX_LIVE_RENDERED_TURN_CONTENT_BYTES = 8 * 1024


CONVERSATION_LIVE_SCRIPT = r'''(() => {
  "use strict";
  const panel = document.querySelector("[data-conversation-live-url]");
  if (!panel) return;
  const url = panel.dataset.conversationLiveUrl;
  if (!url || !url.startsWith("/api/conversation/live/")) return;

  const stream = panel.querySelector("[data-conversation-stream]");
  const activity = panel.querySelector("[data-live-activity]");
  const telemetry = panel.querySelector("[data-live-telemetry]");
  const connection = panel.querySelector("[data-live-connection]");
  let lastHash = panel.dataset.liveHash || "";
  let timer = null;
  let inFlight = false;

  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value;
    return node;
  };

  const tokenText = (value) => value === null ? "unreported" : String(value);

  const renderTurns = (turns) => {
    if (!stream) return;
    stream.replaceChildren();
    if (!turns.length) {
      stream.append(text("div", "No durable conversation Turns yet.", "workspace-conversation-empty"));
      return;
    }
    for (const turn of turns) {
      const actor = String(turn.actor_type || "SYSTEM");
      const article = document.createElement("article");
      article.className = `workspace-message workspace-turn ${actor.toLowerCase()}`;
      const avatar = text("div", actor, "workspace-avatar");
      avatar.setAttribute("aria-hidden", "true");
      const bubble = document.createElement("div");
      bubble.className = "workspace-bubble";
      const head = document.createElement("div");
      head.className = "workspace-message-head";
      head.append(text("span", actor === "FORGE" ? "Forge" : actor === "HUMAN" ? "Human" : "System", "workspace-message-label"));
      head.append(text("span", `#${turn.sequence} · ${turn.created_at}`, "workspace-message-meta"));
      bubble.append(head);
      bubble.append(text("p", turn.content, "workspace-message-body"));
      if (turn.content_clipped) {
        bubble.append(text("span", "Display clipped to 8 KiB; the durable Turn remains unchanged.", "workspace-turn-clipped"));
      }
      const id = document.createElement("div");
      id.className = "workspace-conversation-id";
      id.append(text("code", turn.id));
      bubble.append(id);
      article.append(avatar, bubble);
      stream.append(article);
    }
  };

  const renderActivity = (submissions) => {
    if (!activity) return;
    activity.replaceChildren();
    activity.append(text("h3", "Processing activity"));
    if (!submissions.length) {
      activity.append(text("p", "No durable submissions yet.", "workspace-live-empty"));
      return;
    }
    const list = document.createElement("ul");
    list.className = "workspace-live-list";
    for (const item of submissions) {
      const row = document.createElement("li");
      row.append(text("strong", `Turn #${item.human_turn_sequence}`));
      row.append(text("span", item.status, `workspace-live-status ${String(item.status).toLowerCase()}`));
      const detail = item.failure_code ? ` · ${item.failure_code}` : "";
      row.append(text("small", `${item.id}${detail}`));
      list.append(row);
    }
    activity.append(list);
  };

  const renderTelemetry = (tasks, referencesTruncated) => {
    if (!telemetry) return;
    telemetry.replaceChildren();
    telemetry.append(text("h3", "Conversation Run telemetry"));
    if (referencesTruncated) {
      telemetry.append(text("p", "Only the most recent referenced Tasks are shown.", "workspace-live-note"));
    }
    if (!tasks.length) {
      telemetry.append(text("p", "No Task RESULT references are linked to this conversation yet.", "workspace-live-empty"));
      return;
    }
    for (const task of tasks) {
      const section = document.createElement("section");
      section.className = "workspace-live-task";
      const heading = document.createElement("div");
      heading.className = "workspace-live-task-head";
      const link = document.createElement("a");
      link.href = `/task/${encodeURIComponent(task.task_id)}`;
      link.textContent = task.task_id;
      heading.append(link);
      heading.append(text("span", task.task_status, "workspace-live-status"));
      section.append(heading);
      const coverage = task.runs_truncated
        ? `${task.visible_run_count} of ${task.total_run_count} Runs visible`
        : `${task.total_run_count} Runs`;
      section.append(text("p", `${task.reported_tokens} reported tokens · ${coverage} · ${task.missing_token_counters} missing token counters`, "workspace-live-note"));
      if (task.runs.length) {
        const runs = document.createElement("ul");
        runs.className = "workspace-live-runs";
        for (const run of task.runs) {
          const row = document.createElement("li");
          row.append(text("code", run.id));
          row.append(text("span", `${run.status} · in ${tokenText(run.input_token_count)} · out ${tokenText(run.output_token_count)}`));
          runs.append(row);
        }
        section.append(runs);
      }
      telemetry.append(section);
    }
  };

  const apply = (state) => {
    if (!state || state.schema_version !== 1 || !state.session) return;
    renderTurns(Array.isArray(state.turns) ? state.turns : []);
    renderActivity(Array.isArray(state.submissions) ? state.submissions : []);
    renderTelemetry(Array.isArray(state.task_telemetry) ? state.task_telemetry : [], Boolean(state.task_references_truncated));
    const revision = panel.querySelector('input[name="expected_revision"]');
    if (revision) revision.value = String(state.session.revision);
    const status = panel.querySelector(".workspace-conversation-status");
    if (status) status.textContent = state.session.status;
  };

  const schedule = (delay) => {
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(poll, delay);
  };

  const poll = async () => {
    if (inFlight) return;
    inFlight = true;
    try {
      const response = await fetch(url, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
      });
      if (!response.ok) throw new Error("live read failed");
      const state = await response.json();
      if (typeof state.content_hash !== "string") throw new Error("live hash missing");
      if (state.content_hash !== lastHash) {
        apply(state);
        lastHash = state.content_hash;
        panel.dataset.liveHash = lastHash;
      }
      if (connection) connection.textContent = "Live";
    } catch (_error) {
      if (connection) connection.textContent = "Reconnecting";
    } finally {
      inFlight = false;
      schedule(document.hidden ? 10000 : 2500);
    }
  };

  document.addEventListener("visibilitychange", () => schedule(0));
  poll();
})();
'''


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _clip_content(content: str) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= MAX_LIVE_RENDERED_TURN_CONTENT_BYTES:
        return content, False
    return (
        encoded[:MAX_LIVE_RENDERED_TURN_CONTENT_BYTES].decode("utf-8", "ignore"),
        True,
    )


def live_payload(state: ConversationLiveState) -> dict[str, object]:
    if not isinstance(state, ConversationLiveState):
        raise TypeError("state must be a ConversationLiveState")
    turns: list[dict[str, object]] = []
    for turn in state.turns:
        content, clipped = _clip_content(turn.content)
        turns.append(
            {
                "id": turn.id,
                "sequence": turn.sequence,
                "actor_type": turn.actor_type.value,
                "content": content,
                "content_clipped": clipped,
                "created_at": turn.created_at,
            }
        )
    payload: dict[str, object] = {
        "schema_version": LIVE_SCHEMA_VERSION,
        "session": {
            "id": state.session.id,
            "status": state.session.status.value,
            "revision": state.session.revision,
            "updated_at": state.session.updated_at,
        },
        "turns": turns,
        "submissions": [item.to_dict() for item in state.submissions],
        "task_telemetry": [item.to_dict() for item in state.task_telemetry],
        "task_references_truncated": state.task_references_truncated,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


def live_json_bytes(state: ConversationLiveState) -> bytes:
    return (
        json.dumps(
            live_payload(state),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def render_live_activity(state: ConversationLiveState) -> str:
    if not state.submissions:
        body = '<p class="workspace-live-empty">No durable submissions yet.</p>'
    else:
        rows = []
        for item in state.submissions:
            detail = f" · {_e(item.failure_code)}" if item.failure_code else ""
            rows.append(
                "<li>"
                f"<strong>Turn #{item.human_turn_sequence}</strong>"
                f'<span class="workspace-live-status {item.status.value.lower()}">{_e(item.status.value)}</span>'
                f"<small>{_e(item.id)}{detail}</small>"
                "</li>"
            )
        body = '<ul class="workspace-live-list">' + "".join(rows) + "</ul>"
    return (
        '<section class="workspace-live-block" data-live-activity '
        'aria-label="Conversation processing activity">'
        "<h3>Processing activity</h3>"
        f"{body}</section>"
    )


def render_live_telemetry(state: ConversationLiveState) -> str:
    notes = (
        '<p class="workspace-live-note">Only the most recent referenced Tasks are shown.</p>'
        if state.task_references_truncated
        else ""
    )
    if not state.task_telemetry:
        body = (
            '<p class="workspace-live-empty">No Task RESULT references are linked to this '
            "conversation yet.</p>"
        )
    else:
        sections = []
        for task in state.task_telemetry:
            coverage = (
                f"{len(task.runs)} of {task.total_run_count} Runs visible"
                if task.runs_truncated
                else f"{task.total_run_count} Runs"
            )
            run_rows = "".join(
                "<li>"
                f"<code>{_e(run.id)}</code>"
                f"<span>{_e(run.status)} · in {_e(run.input_token_count if run.input_token_count is not None else 'unreported')} · "
                f"out {_e(run.output_token_count if run.output_token_count is not None else 'unreported')}</span>"
                "</li>"
                for run in task.runs
            )
            runs = (
                f'<ul class="workspace-live-runs">{run_rows}</ul>' if run_rows else ""
            )
            sections.append(
                '<section class="workspace-live-task">'
                '<div class="workspace-live-task-head">'
                f'<a href="/task/{_e(task.task_id)}">{_e(task.task_id)}</a>'
                f'<span class="workspace-live-status">{_e(task.task_status)}</span>'
                "</div>"
                f'<p class="workspace-live-note">{task.reported_tokens} reported tokens · '
                f"{_e(coverage)} · {task.missing_token_counters} missing token counters</p>"
                f"{runs}</section>"
            )
        body = "".join(sections)
    return (
        '<section class="workspace-live-block" data-live-telemetry '
        'aria-label="Conversation Run telemetry">'
        "<h3>Conversation Run telemetry</h3>"
        f"{notes}{body}</section>"
    )
