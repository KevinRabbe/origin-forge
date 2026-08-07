from __future__ import annotations

import json
from typing import Iterable

from .ids import IdKind, new_id
from .service import OriginForgeStore, utc_now


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def create_decision(
    store: OriginForgeStore,
    project_id: str,
    *,
    title: str,
    decision: str,
    context: str | None = None,
    rationale: str | None = None,
    alternatives: Iterable[str] = (),
    goal_id: str | None = None,
    task_id: str | None = None,
    supersedes_decision_id: str | None = None,
    actor_type: str = "HUMAN",
    actor_id: str | None = None,
) -> str:
    decision_id = new_id(IdKind.DECISION)
    now = utc_now()
    with store.session() as conn:
        conn.execute(
            """INSERT INTO decisions(
                   id, project_id, goal_id, task_id, title, context, decision,
                   rationale, alternatives_json, status,
                   supersedes_decision_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)""",
            (
                decision_id,
                project_id,
                goal_id,
                task_id,
                title,
                context,
                decision,
                rationale,
                _json(list(alternatives)),
                supersedes_decision_id,
                now,
            ),
        )
        store._append_event(
            conn,
            "DECISION",
            decision_id,
            "DECISION_CREATED",
            None,
            "ACTIVE",
            0,
            actor_type,
            actor_id,
            {"title": title, "goal_id": goal_id, "task_id": task_id},
            now,
        )
    return decision_id


def create_change(
    store: OriginForgeStore,
    task_id: str,
    *,
    summary: str,
    change_type: str,
    decision_id: str | None = None,
    run_id: str | None = None,
    before_ref: str | None = None,
    after_ref: str | None = None,
    status: str = "RECORDED",
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> str:
    change_id = new_id(IdKind.CHANGE)
    now = utc_now()
    with store.session() as conn:
        conn.execute(
            """INSERT INTO changes(
                   id, task_id, decision_id, run_id, summary, change_type,
                   before_ref, after_ref, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                change_id,
                task_id,
                decision_id,
                run_id,
                summary,
                change_type,
                before_ref,
                after_ref,
                status,
                now,
            ),
        )
        store._append_event(
            conn,
            "CHANGE",
            change_id,
            "CHANGE_CREATED",
            None,
            status,
            0,
            actor_type,
            actor_id,
            {
                "task_id": task_id,
                "decision_id": decision_id,
                "run_id": run_id,
                "change_type": change_type,
            },
            now,
        )
    return change_id


def create_artifact(
    store: OriginForgeStore,
    project_id: str,
    *,
    artifact_type: str,
    path_or_uri: str,
    content_hash: str | None = None,
    change_id: str | None = None,
    parent_artifact_id: str | None = None,
    created_by_run_id: str | None = None,
    model_id: str | None = None,
    skill_versions: Iterable[str] = (),
    tool_versions: Iterable[str] = (),
    status: str = "PRODUCED",
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> str:
    artifact_id = new_id(IdKind.ARTIFACT)
    now = utc_now()
    with store.session() as conn:
        conn.execute(
            """INSERT INTO artifacts(
                   id, project_id, change_id, type, path_or_uri, content_hash,
                   parent_artifact_id, created_by_run_id, model_id,
                   skill_versions_json, tool_versions_json, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                project_id,
                change_id,
                artifact_type,
                path_or_uri,
                content_hash,
                parent_artifact_id,
                created_by_run_id,
                model_id,
                _json(list(skill_versions)),
                _json(list(tool_versions)),
                status,
                now,
            ),
        )
        store._append_event(
            conn,
            "ARTIFACT",
            artifact_id,
            "ARTIFACT_CREATED",
            None,
            status,
            0,
            actor_type,
            actor_id,
            {
                "project_id": project_id,
                "change_id": change_id,
                "path_or_uri": path_or_uri,
                "content_hash": content_hash,
            },
            now,
        )
    return artifact_id
