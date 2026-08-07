from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4


class IdKind(StrEnum):
    PROJECT = "PROJECT"
    GOAL = "GOAL"
    FLOW = "FLOW"
    TASK = "TASK"
    DECISION = "DEC"
    CHANGE = "CHG"
    ARTIFACT = "ART"
    VERIFICATION = "VERIFY"
    RUN = "RUN"
    EVENT = "EVENT"


def new_id(kind: IdKind) -> str:
    """Create an opaque infrastructure-owned ID.

    UUIDv4 is intentionally used in Phase 1 because it is available in the
    standard library. The ID contract allows a later migration to UUIDv7
    without changing the type-prefixed external representation.
    """

    return f"{kind.value}-{uuid4()}"


def validate_id(value: str, kind: IdKind) -> bool:
    prefix = f"{kind.value}-"
    if not value.startswith(prefix):
        return False
    try:
        UUID(value[len(prefix) :])
    except (ValueError, AttributeError):
        return False
    return True
