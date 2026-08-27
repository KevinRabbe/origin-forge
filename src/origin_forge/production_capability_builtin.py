from __future__ import annotations

import hashlib

from .production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    ProductionCapability,
    TrustedProductionAdapter,
)


def _contract_fingerprint(adapter_id: str, contract: str) -> str:
    """Fingerprint one reviewed Origin Forge routing contract identity.

    This is deliberately a contract-identity fingerprint, not a claim that it is
    a source-tree hash or executable hash. Actual backends retain their own
    stronger runtime/version/hash verification at execution time.
    """

    identity = f"origin-forge:production-adapter:v1:{adapter_id}:{contract}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _capability(
    capability_id: str,
    name: str,
    summary: str,
    domain: CapabilityDomain,
) -> ProductionCapability:
    return ProductionCapability(capability_id, name, summary, domain, "1")


def _adapter(
    adapter_id: str,
    family: str,
    capability_ids: tuple[str, ...],
    effect: AdapterExecutionEffect,
    replay: AdapterReplayClass,
    contract: str,
) -> TrustedProductionAdapter:
    return TrustedProductionAdapter(
        adapter_id=adapter_id,
        adapter_family=family,
        adapter_version="1",
        implementation_fingerprint=_contract_fingerprint(adapter_id, contract),
        capability_ids=capability_ids,
        execution_effect=effect,
        replay_class=replay,
    )


def builtin_production_capabilities() -> tuple[ProductionCapability, ...]:
    """Return reviewed semantic capabilities; this grants no routing authority."""

    return (
        _capability(
            "build.integration",
            "Build integration",
            "Run project-approved build commands in the governed sandbox.",
            CapabilityDomain.GENERAL,
        ),
        _capability(
            "design.specify",
            "Design specification",
            "Produce bounded design/specification evidence without implementation authority.",
            CapabilityDomain.DESIGN,
        ),
        _capability(
            "code.change",
            "Code change",
            "Execute the bounded snapshot-first coding/retry production contract.",
            CapabilityDomain.CODE,
        ),
        _capability(
            "media.2d.export",
            "2D media export",
            "Run the governed Pixelorama export boundary over isolated media state.",
            CapabilityDomain.MEDIA_2D,
        ),
        _capability(
            "media.2d.source",
            "2D source production",
            "Create governed Pixelorama source and animation state from accepted design evidence.",
            CapabilityDomain.MEDIA_2D,
        ),
        _capability(
            "media.3d.blender",
            "Blender 3D production",
            "Run the governed Blender backend behind the canonical 3D contract.",
            CapabilityDomain.MEDIA_3D,
        ),
        _capability(
            "image.generate",
            "Image generation",
            "Run a governed isolated image-generation workflow.",
            CapabilityDomain.IMAGE,
        ),
        _capability(
            "image.inspect",
            "Image inspection",
            "Run governed advisory visual inspection without Task-verification authority.",
            CapabilityDomain.IMAGE,
        ),
        _capability(
            "media.audio.process",
            "Audio processing",
            "Run governed deterministic/FFmpeg audio processing.",
            CapabilityDomain.AUDIO,
        ),
        _capability(
            "media.audio.tts",
            "Text to speech",
            "Run the governed Piper TTS boundary.",
            CapabilityDomain.AUDIO,
        ),
        _capability(
            "runtime.observe",
            "Runtime observation",
            "Run the governed runtime-observation evidence boundary.",
            CapabilityDomain.RUNTIME,
        ),
        _capability(
            "runtime.playtest",
            "Automated playtest",
            "Run the governed cooperative automated-playtesting boundary.",
            CapabilityDomain.PLAYTEST,
        ),
        _capability(
            "simulation.run",
            "Deterministic simulation",
            "Run the governed cheap deterministic simulation substrate.",
            CapabilityDomain.SIMULATION,
        ),
    )


def builtin_trusted_production_adapters() -> tuple[TrustedProductionAdapter, ...]:
    """Return inert descriptors for proven infrastructure-owned production surfaces.

    These descriptors contain no callable/process/model dispatch. A routing policy
    must still list an adapter explicitly, and a later coordinator must map the
    selected ID to trusted code after independent readiness/preflight checks.
    """

    return (
        _adapter(
            "originforge.build.integration",
            "originforge.build",
            ("build.integration",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
            "build integration sandbox boundary",
        ),
        _adapter(
            "originforge.code.bounded-retry",
            "originforge.code",
            ("code.change",),
            AdapterExecutionEffect.WORKSPACE_MUTATION,
            AdapterReplayClass.REVISION_BOUND,
            "orchestration_policy.BoundedRetryPolicy",
        ),
        _adapter(
            "originforge.pixelorama.export",
            "originforge.pixelorama",
            ("media.2d.export",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "pixelorama governed export boundary",
        ),
        _adapter(
            "originforge.pixelorama.source",
            "originforge.pixelorama",
            ("media.2d.source",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "pixelorama governed source creation boundary",
        ),
        _adapter(
            "originforge.blender.model3d",
            "originforge.blender",
            ("media.3d.blender",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "blender governed 3d backend",
        ),
        _adapter(
            "originforge.image.generate",
            "originforge.image",
            ("image.generate",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "image governed generation workflow",
        ),
        _adapter(
            "originforge.vision.inspect",
            "originforge.vision",
            ("image.inspect",),
            AdapterExecutionEffect.OBSERVATION_ONLY,
            AdapterReplayClass.RUNTIME_BOUND,
            "vision governed advisory inspection",
        ),
        _adapter(
            "originforge.audio.ffmpeg",
            "originforge.audio",
            ("media.audio.process",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "audio governed ffmpeg processing",
        ),
        _adapter(
            "originforge.audio.piper",
            "originforge.audio",
            ("media.audio.tts",),
            AdapterExecutionEffect.MEDIA_WORKSPACE_MUTATION,
            AdapterReplayClass.RUNTIME_BOUND,
            "audio governed piper tts",
        ),
        _adapter(
            "originforge.runtime.observe",
            "originforge.runtime",
            ("runtime.observe",),
            AdapterExecutionEffect.OBSERVATION_ONLY,
            AdapterReplayClass.RUNTIME_BOUND,
            "runtime_observation governed target execution",
        ),
        _adapter(
            "originforge.playtest.cooperative",
            "originforge.playtest",
            ("runtime.playtest",),
            AdapterExecutionEffect.OBSERVATION_ONLY,
            AdapterReplayClass.RUNTIME_BOUND,
            "playtest governed cooperative harness",
        ),
        _adapter(
            "originforge.simulation.deterministic",
            "originforge.simulation",
            ("simulation.run",),
            AdapterExecutionEffect.SIMULATION_ONLY,
            AdapterReplayClass.DETERMINISTIC,
            "simulation deterministic engine v1",
        ),
    )


def build_builtin_capability_catalog() -> CapabilityCatalog:
    """Build a fresh immutable snapshot of reviewed built-in routing inventory."""

    return CapabilityCatalog.create(
        builtin_production_capabilities(),
        builtin_trusted_production_adapters(),
    )
