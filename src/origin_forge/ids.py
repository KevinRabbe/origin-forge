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
    WORKSPACE = "WSPACE"
    DREAM_MANIFEST = "DREAMIN"
    DREAM_CANDIDATE = "DREAM"
    MEMORY_ENTRY = "MEM"
    MEMORY_GENERATION = "MEMGEN"
    SPECIALIST_CONTRACT = "SPCON"
    SPECIALIST_REPORT = "SPREP"
    SPECIALIST_FINDING = "SPFIND"
    ENTITY = "ENTITY"
    ENTITY_RELATION = "REL"
    ENTITY_BINDING = "BIND"
    DESIGN_RULE = "RULE"
    COMPANY_IDENTITY = "COMPANY"
    PROVENANCE_KEY = "PKEY"
    KEY_CERTIFICATE = "KEYCERT"
    KEY_REVOCATION = "KEYREV"
    PROVENANCE_MANIFEST = "PROV"
    MEDIA_WORKSPACE = "MEDIA"
    PIXELORAMA_OPERATION = "PXOP"
    MODEL3D_WORKSPACE = "MODEL3D"
    BLOCKBENCH_OPERATION = "BBOP"
    BLENDER_OPERATION = "BLOP"
    IMAGE_WORKSPACE = "IMAGE"
    IMAGE_OPERATION = "IMGOP"
    VISION_INSPECTION = "VISION"
    AUDIO_WORKSPACE = "AUDIO"
    AUDIO_OPERATION = "AUDOP"
    AUDIO_PROFILE = "AUDPROF"
    RUNTIME_OBSERVATION_WORKSPACE = "OBSWS"
    RUNTIME_OBSERVATION = "OBS"
    PLAYTEST_SCENARIO = "PLAYSCEN"
    PLAYTEST_SESSION = "PLAY"
    PLAYTEST_WORKSPACE = "PLAYWS"
    SIMULATION_SPEC = "SIMSPEC"
    SIMULATION_SESSION = "SIM"
    SIMULATION_WORKSPACE = "SIMWS"


def new_id(kind: IdKind) -> str:
    """Create an opaque infrastructure-owned ID.

    UUIDv4 is intentionally used because it is available in the standard
    library. The ID contract allows a later migration to UUIDv7 without
    changing the type-prefixed external representation.
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
