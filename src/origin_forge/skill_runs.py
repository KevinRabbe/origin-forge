from __future__ import annotations

import json

from .runtime import OriginForgeRuntime
from .skills import SkillError, SkillSelection
from .state import RunStatus


def bind_run_skills(
    runtime: OriginForgeRuntime,
    run_id: str,
    selection: SkillSelection,
) -> None:
    """Persist the exact selected Skill references on a still-running Run."""

    run = runtime.get_run(run_id)
    if run["status"] != RunStatus.RUNNING.value:
        raise SkillError(f"cannot bind Skills to terminal Run {run_id}: {run['status']}")
    if run["task_id"] != selection.task_id:
        raise SkillError("Skill selection Task does not match Run Task")
    payload = json.dumps(list(selection.refs), separators=(",", ":"), sort_keys=True)
    with runtime.store.session() as conn:
        cursor = conn.execute(
            "UPDATE runs SET skills_json = ? WHERE id = ? AND status = ?",
            (payload, run_id, RunStatus.RUNNING.value),
        )
        if cursor.rowcount != 1:
            raise SkillError(f"Run changed while binding Skills: {run_id}")
