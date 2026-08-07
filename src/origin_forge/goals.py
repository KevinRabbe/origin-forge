from __future__ import annotations

from .service import OriginForgeStore, StaleRevision, VerificationRequired, utc_now
from .state import GOAL_TRANSITIONS, GoalStatus, ensure_transition


def transition_goal(
    store: OriginForgeStore,
    goal_id: str,
    target: GoalStatus,
    *,
    expected_revision: int,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> int:
    now = utc_now()
    with store.session() as conn:
        row = conn.execute(
            "SELECT status, revision FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(goal_id)
        current = GoalStatus(row["status"])
        actual = int(row["revision"])
        if actual != expected_revision:
            raise StaleRevision(
                f"goal {goal_id} revision {actual} != expected {expected_revision}"
            )
        ensure_transition(current, target, GOAL_TRANSITIONS)
        if target == GoalStatus.SUCCEEDED:
            passed = conn.execute(
                """SELECT 1 FROM verifications
                   WHERE target_type = 'GOAL' AND target_id = ? AND status = 'PASS'
                   LIMIT 1""",
                (goal_id,),
            ).fetchone()
            if passed is None:
                raise VerificationRequired(
                    f"goal {goal_id} cannot succeed without a passing goal verification"
                )
        new_revision = actual + 1
        cursor = conn.execute(
            """UPDATE goals SET status = ?, revision = ?, updated_at = ?
               WHERE id = ? AND revision = ?""",
            (target.value, new_revision, now, goal_id, actual),
        )
        if cursor.rowcount != 1:
            raise StaleRevision(f"goal {goal_id} changed concurrently")
        store._append_event(
            conn,
            "GOAL",
            goal_id,
            "GOAL_STATUS_CHANGED",
            current.value,
            target.value,
            new_revision,
            actor_type,
            actor_id,
            {},
            now,
        )
        return new_revision
