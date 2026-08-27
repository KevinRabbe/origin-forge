from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from .production_capability_models import CapabilityCatalog
from .production_work_order_audio import (
    FFMPEG_ADAPTER_ID,
    FFMPEG_CONTRACT_ID,
    PIPER_ADAPTER_ID,
    PIPER_CONTRACT_ID,
    FfmpegAudioDispatchValidator,
    PiperSpeechDispatchValidator,
)
from .production_work_order_blender import (
    BLENDER_ADAPTER_ID,
    BLENDER_CONTRACT_ID,
    BlenderExportGLBDispatchValidator,
)
from .production_work_order_build import (
    BUILD_ADAPTER_ID,
    BUILD_CONTRACT_ID,
    BuildIntegrationDispatchValidator,
)
from .production_work_order_image import (
    IMAGE_ADAPTER_ID,
    IMAGE_CONTRACT_ID,
    ImageGenerationDispatchValidator,
)
from .production_work_order_models import (
    DispatchContract,
    DispatchContractCatalog,
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from .production_work_order_pixelorama import (
    PIXELORAMA_ADAPTER_ID,
    PIXELORAMA_CONTRACT_ID,
    PixeloramaSpritesheetExportDispatchValidator,
)
from .production_work_order_playtest import (
    PLAYTEST_ADAPTER_ID,
    PLAYTEST_CONTRACT_ID,
    CooperativePlaytestDispatchValidator,
)
from .production_work_order_runtime import (
    RUNTIME_ADAPTER_ID,
    RUNTIME_CONTRACT_ID,
    RuntimeObservationDispatchValidator,
)
from .production_work_order_simulation import (
    SIMULATION_ADAPTER_ID,
    SIMULATION_CONTRACT_ID,
    DeterministicSimulationDispatchValidator,
)
from .production_work_order_validators import (
    DispatchContractValidatorRegistry,
    DispatchPayloadValidator,
    DispatchValidatorError,
    PayloadFieldKind,
    PayloadFieldRule,
    StaticObjectPayloadValidator,
)

_CODE_ADAPTER_ID = "originforge.code.bounded-retry"
_CODE_VALIDATOR_ID = "validator.code.bounded-retry@1"
_CODE_SCHEMA_ID = "schema.code.bounded-retry@1"
_MAX_CONTEXT_PATHS = 64
_MAX_PATH_CHARS = 512


class BuiltinDispatchReviewStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    DEFERRED_INPUT_EVIDENCE_RESOLUTION = "DEFERRED_INPUT_EVIDENCE_RESOLUTION"
    NO_PHASE32_ADAPTER = "NO_PHASE32_ADAPTER"
    DEFERRED_BACKEND = "DEFERRED_BACKEND"


@dataclass(frozen=True)
class BuiltinDispatchReview:
    adapter_id: str
    status: BuiltinDispatchReviewStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "status": self.status.value,
            "reason": self.reason,
        }


def builtin_dispatch_review() -> tuple[BuiltinDispatchReview, ...]:
    """Document the reviewed dispatch-contract inclusion boundary."""

    deferred = (
        "originforge.vision.inspect",
        "originforge.audio.piper",
    )
    rows = [
        BuiltinDispatchReview(
            BUILD_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "build integration accepts only the inert BUILD selector; approved commands, sandbox, workspace, and environment remain infrastructure-owned",
        ),
        BuiltinDispatchReview(
            _CODE_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "bounded retry drive inputs are finite context-selection data; model and sandbox authority remain infrastructure-injected",
        ),
        BuiltinDispatchReview(
            SIMULATION_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "deterministic simulation accepts a self-contained bounded declarative Phase-25 semantic template with no input refs or runtime authority",
        ),
        BuiltinDispatchReview(
            PIXELORAMA_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "Pixelorama spritesheet export accepts one exact Artifact ref and an inert payload while editor/profile/process authority remains downstream and infrastructure-owned",
        ),
        BuiltinDispatchReview(
            BLENDER_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "Blender GLB export accepts one exact protected MODEL3D_REQUEST ref and an inert payload while operation/workspace/path/profile/process authority remains downstream and infrastructure-owned",
        ),
        BuiltinDispatchReview(
            IMAGE_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "ComfyUI generation accepts an exact local-only workflow projection while backend execution and output evidence remain infrastructure-owned",
        ),
        BuiltinDispatchReview(
            FFMPEG_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "FFmpeg processing accepts one exact typed PCM16 source and one governed audio profile while executable and output evidence remain infrastructure-owned",
        ),
        BuiltinDispatchReview(
            RUNTIME_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "runtime observation accepts one exact protected OBS request while target execution and evidence remain evidence-only infrastructure-owned",
        ),
        BuiltinDispatchReview(
            PLAYTEST_ADAPTER_ID,
            BuiltinDispatchReviewStatus.SUPPORTED,
            "cooperative playtesting accepts one exact protected PLAYSCEN request while harness execution and evidence remain evidence-only infrastructure-owned",
        ),
    ]
    rows.extend(
        BuiltinDispatchReview(
            adapter_id,
            BuiltinDispatchReviewStatus.DEFERRED_INPUT_EVIDENCE_RESOLUTION,
            "backend requires exact phase-specific request/spec/profile/source evidence that Phase 33 does not yet resolve generically",
        )
        for adapter_id in deferred
    )
    rows.extend(
        (
            BuiltinDispatchReview(
                "design.specify",
                BuiltinDispatchReviewStatus.NO_PHASE32_ADAPTER,
                "Phase 32 intentionally defines the capability without a built-in executor",
            ),
            BuiltinDispatchReview(
                "blockbench",
                BuiltinDispatchReviewStatus.DEFERRED_BACKEND,
                "Phase 20B remains deferred and Phase 32 exposes no Blockbench adapter",
            ),
        )
    )
    return tuple(sorted(rows, key=lambda value: value.adapter_id))


def _portable_context_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PATH_CHARS
        or "\\" in value
        or value.startswith("/")
    ):
        raise DispatchValidatorError("coding context path is not a bounded POSIX-relative path")
    path = PurePosixPath(value)
    parts = path.parts
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0] in {".git", ".origin-forge"}
    ):
        raise DispatchValidatorError("coding context path is protected or non-portable")
    normalized = path.as_posix()
    if normalized != value:
        raise DispatchValidatorError("coding context path is not canonical")
    return normalized


class CodeBoundedRetryDispatchValidator:
    """Pure WorkOrder validator for `BoundedRetryPolicy.drive()` input only."""

    _IMPLEMENTATION_ID = "origin-forge-code-bounded-retry-work-order-validator@1"

    def __init__(self) -> None:
        self._base = StaticObjectPayloadValidator(
            validator_id=_CODE_VALIDATOR_ID,
            payload_schema_id=_CODE_SCHEMA_ID,
            fields=(
                PayloadFieldRule(
                    "context_mode",
                    PayloadFieldKind.STRING,
                    allowed_values=("auto", "manual"),
                    max_string_chars=16,
                ),
                PayloadFieldRule(
                    "context_seed_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=_MAX_PATH_CHARS,
                    max_items=_MAX_CONTEXT_PATHS,
                ),
                PayloadFieldRule(
                    "selected_paths",
                    PayloadFieldKind.STRING_LIST,
                    required=False,
                    max_string_chars=_MAX_PATH_CHARS,
                    max_items=_MAX_CONTEXT_PATHS,
                ),
                PayloadFieldRule(
                    "semantic_context",
                    PayloadFieldKind.BOOLEAN,
                    required=False,
                ),
                PayloadFieldRule(
                    "structural_context",
                    PayloadFieldKind.BOOLEAN,
                    required=False,
                ),
            ),
        )
        self._fingerprint = content_hash(
            {
                "implementation_id": self._IMPLEMENTATION_ID,
                "base_validator_fingerprint": self._base.validator_fingerprint,
                "cross_field_contract": {
                    "auto": "selected_paths empty; context_seed_paths optional",
                    "manual": "selected_paths non-empty; context_seed_paths empty",
                    "paths": "canonical bounded POSIX-relative; .git/.origin-forge protected",
                    "defaults": {
                        "selected_paths": [],
                        "context_seed_paths": [],
                        "structural_context": False,
                        "semantic_context": False,
                    },
                },
            }
        )

    @property
    def validator_id(self) -> str:
        return self._base.validator_id

    @property
    def validator_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def payload_schema_id(self) -> str:
        return self._base.payload_schema_id

    @property
    def payload_schema_hash(self) -> str:
        return self._base.payload_schema_hash

    def schema_dict(self) -> dict[str, object]:
        return self._base.schema_dict()

    def validate(
        self,
        payload: dict[str, Any],
        input_refs: tuple[WorkOrderInputRef, ...],
    ) -> dict[str, Any]:
        if input_refs:
            raise DispatchValidatorError(
                "bounded coding WorkOrder accepts no generic evidence refs in v1"
            )
        normalized = self._base.validate(payload, input_refs)
        selected = [
            _portable_context_path(value)
            for value in normalized.get("selected_paths", [])
        ]
        seeds = [
            _portable_context_path(value)
            for value in normalized.get("context_seed_paths", [])
        ]
        mode = normalized["context_mode"]
        if mode == "manual":
            if not selected:
                raise DispatchValidatorError(
                    "manual coding context requires selected_paths"
                )
            if seeds:
                raise DispatchValidatorError(
                    "manual coding context cannot contain context_seed_paths"
                )
        elif mode == "auto":
            if selected:
                raise DispatchValidatorError(
                    "automatic coding context cannot contain selected_paths"
                )
        else:
            raise AssertionError(mode)
        return {
            "context_mode": mode,
            "selected_paths": selected,
            "context_seed_paths": seeds,
            "structural_context": normalized.get("structural_context", False),
            "semantic_context": normalized.get("semantic_context", False),
        }


def builtin_dispatch_validators() -> tuple[DispatchPayloadValidator, ...]:
    return (
        BuildIntegrationDispatchValidator(),
        CodeBoundedRetryDispatchValidator(),
        DeterministicSimulationDispatchValidator(),
        PixeloramaSpritesheetExportDispatchValidator(),
        BlenderExportGLBDispatchValidator(),
        ImageGenerationDispatchValidator(),
        FfmpegAudioDispatchValidator(),
        PiperSpeechDispatchValidator(),
        RuntimeObservationDispatchValidator(),
        CooperativePlaytestDispatchValidator(),
    )


def build_builtin_dispatch_validator_registry() -> DispatchContractValidatorRegistry:
    return DispatchContractValidatorRegistry(builtin_dispatch_validators())


def _code_contract(adapter) -> DispatchContract:
    validator = CodeBoundedRetryDispatchValidator()
    return DispatchContract(
        contract_id="code.bounded-retry@1",
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(),
        max_payload_bytes=64 * 1024,
        max_input_refs=0,
    )


def _simulation_contract(adapter) -> DispatchContract:
    validator = DeterministicSimulationDispatchValidator()
    return DispatchContract(
        contract_id=SIMULATION_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(),
        max_payload_bytes=256 * 1024,
        max_input_refs=0,
    )


def _pixelorama_contract(adapter) -> DispatchContract:
    validator = PixeloramaSpritesheetExportDispatchValidator()
    return DispatchContract(
        contract_id=PIXELORAMA_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.ARTIFACT,),
        max_payload_bytes=2,
        max_input_refs=1,
    )


def _blender_contract(adapter) -> DispatchContract:
    validator = BlenderExportGLBDispatchValidator()
    return DispatchContract(
        contract_id=BLENDER_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.MODEL3D_REQUEST,),
        max_payload_bytes=2,
        max_input_refs=1,
    )


def _build_contract(adapter) -> DispatchContract:
    validator = BuildIntegrationDispatchValidator()
    return DispatchContract(
        contract_id=BUILD_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.WORKSPACE,),
        max_payload_bytes=128,
        max_input_refs=1,
    )


def _image_contract(adapter) -> DispatchContract:
    validator = ImageGenerationDispatchValidator()
    return DispatchContract(
        contract_id=IMAGE_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(),
        max_payload_bytes=256 * 1024,
        max_input_refs=0,
    )


def _piper_contract(adapter) -> DispatchContract:
    validator = PiperSpeechDispatchValidator()
    return DispatchContract(
        contract_id=PIPER_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.AUDIO_PROFILE,),
        max_payload_bytes=64 * 1024,
        max_input_refs=1,
    )


def _ffmpeg_contract(adapter) -> DispatchContract:
    validator = FfmpegAudioDispatchValidator()
    return DispatchContract(
        contract_id=FFMPEG_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.ARTIFACT, WorkOrderRefType.AUDIO_PROFILE),
        max_payload_bytes=64 * 1024,
        max_input_refs=2,
    )


def _runtime_contract(adapter) -> DispatchContract:
    validator = RuntimeObservationDispatchValidator()
    return DispatchContract(
        contract_id=RUNTIME_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.RUNTIME_OBSERVATION_REQUEST,),
        max_payload_bytes=2,
        max_input_refs=1,
    )


def _playtest_contract(adapter) -> DispatchContract:
    validator = CooperativePlaytestDispatchValidator()
    return DispatchContract(
        contract_id=PLAYTEST_CONTRACT_ID,
        contract_version="1",
        adapter_id=adapter.adapter_id,
        adapter_fingerprint=adapter.implementation_fingerprint,
        validator_id=validator.validator_id,
        validator_fingerprint=validator.validator_fingerprint,
        payload_schema_id=validator.payload_schema_id,
        payload_schema_hash=validator.payload_schema_hash,
        allowed_input_ref_types=(WorkOrderRefType.PLAYTEST_SCENARIO,),
        # The payload is intentionally only the operation selector; keep a
        # small bounded envelope while allowing canonical JSON overhead.
        max_payload_bytes=128,
        max_input_refs=1,
    )


def build_builtin_dispatch_catalog(
    phase32_catalog: CapabilityCatalog,
) -> DispatchContractCatalog:
    """Build only reviewed contracts while preserving Phase-45 code authority.

    The historic full built-in Phase-32 catalog contains the code adapter and is
    deliberately kept code-only here because Phase 45 freezes that exact v1
    dispatch boundary. A single reviewed non-code adapter may receive its exact
    contract. Mixed reviewed non-code catalogs fail closed instead of choosing
    by ordering.
    """

    if not isinstance(phase32_catalog, CapabilityCatalog):
        raise TypeError("phase32_catalog must be a CapabilityCatalog")
    adapters = {value.adapter_id: value for value in phase32_catalog.adapters}
    build = adapters.get(BUILD_ADAPTER_ID)
    code = adapters.get(_CODE_ADAPTER_ID)
    if code is not None:
        return DispatchContractCatalog.create(phase32_catalog, (_code_contract(code),))
    simulation = adapters.get(SIMULATION_ADAPTER_ID)
    pixelorama = adapters.get(PIXELORAMA_ADAPTER_ID)
    blender = adapters.get(BLENDER_ADAPTER_ID)
    image = adapters.get(IMAGE_ADAPTER_ID)
    ffmpeg = adapters.get(FFMPEG_ADAPTER_ID)
    piper = adapters.get(PIPER_ADAPTER_ID)
    runtime_observer = adapters.get(RUNTIME_ADAPTER_ID)
    playtest = adapters.get(PLAYTEST_ADAPTER_ID)
    reviewed_non_code = tuple(
        value
        for value in (
            build,
            simulation,
            pixelorama,
            blender,
            image,
            ffmpeg,
            piper,
            runtime_observer,
            playtest,
        )
        if value is not None
    )
    if len(reviewed_non_code) > 1:
        raise ValueError(
            "Phase-32 catalog contains multiple reviewed non-code Phase-33 adapters"
        )
    if build is not None:
        return DispatchContractCatalog.create(phase32_catalog, (_build_contract(build),))
    if simulation is not None:
        return DispatchContractCatalog.create(
            phase32_catalog,
            (_simulation_contract(simulation),),
        )
    if pixelorama is not None:
        return DispatchContractCatalog.create(
            phase32_catalog,
            (_pixelorama_contract(pixelorama),),
        )
    if blender is not None:
        return DispatchContractCatalog.create(
            phase32_catalog,
            (_blender_contract(blender),),
        )
    if image is not None:
        return DispatchContractCatalog.create(
            phase32_catalog,
            (_image_contract(image),),
        )
    if ffmpeg is not None:
        return DispatchContractCatalog.create(phase32_catalog, (_ffmpeg_contract(ffmpeg),))
    if piper is not None:
        return DispatchContractCatalog.create(phase32_catalog, (_piper_contract(piper),))
    if runtime_observer is not None:
        return DispatchContractCatalog.create(
            phase32_catalog, (_runtime_contract(runtime_observer),)
        )
    if playtest is not None:
        return DispatchContractCatalog.create(phase32_catalog, (_playtest_contract(playtest),))
    raise ValueError("Phase-32 catalog lacks a reviewed Phase-33 dispatch adapter")
