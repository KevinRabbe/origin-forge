from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from origin_forge.audio_models import (
    AudioOperation,
    AudioOperationResult,
    AudioOutputEvidence,
    AudioResultStatus,
    canonical_bytes,
)
from origin_forge.audio_profiles import (
    AudioProfileKind,
    AudioProfileStore,
    GovernedAudioProfile,
)
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.production_audio_dispatch_output_binding import (
    read_audio_dispatch_output_binding,
)
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import (
    CapabilityCatalog,
    CapabilityRoutingPolicy,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_binding import (
    audit_dispatch_binding_frozen,
    build_builtin_dispatch_binder_registry,
    create_dispatch_binding,
    create_input_resolution_bundle,
)
from origin_forge.production_dispatch_claims import acquire_dispatch_claim
from origin_forge.production_dispatch_invocation import dispatch_claim_once
from origin_forge.production_dispatch_invocation_piper_owner import (
    recover_piper_dispatch_execution_once,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_owner_audio import PIPER_EXECUTION_OWNER_ID
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.runtime import OriginForgeRuntime


class _FakePiperAdapter:
    calls = 0

    def __init__(self, runtime, profile, **_kwargs):
        self.runtime = runtime
        self.profile = profile

    def execute(self, request, _source_bytes):
        type(self).calls += 1
        workspace = self.runtime.state_dir / "audio-workspaces" / request.workspace_id
        for name in ("request", "inputs", "exports", "runtime"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        (workspace / "request" / "request.json").write_bytes(canonical_bytes(request.to_dict()))
        data = encode_pcm16_wav(channels=1, sample_rate=request.target_sample_rate, pcm_bytes=b"\x00\x00\x64\x00")
        output_path = workspace / request.output_relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        inspection = inspect_pcm16_wav(data)
        output = AudioOutputEvidence(
            relative_path=request.output_relative_path,
            content_hash=inspection.content_hash,
            pcm_hash=inspection.pcm_hash,
            byte_count=inspection.byte_count,
            frame_count=inspection.frame_count,
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
            peak_abs_sample=inspection.peak_abs_sample,
            clipped_sample_count=inspection.clipped_sample_count,
            nonzero_sample_count=inspection.nonzero_sample_count,
        )
        result = AudioOperationResult(
            operation_id=request.operation_id,
            workspace_id=request.workspace_id,
            request_hash=request.content_hash,
            status=AudioResultStatus.SUCCEEDED,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            profile_id=request.profile_id,
            profile_hash=request.profile_hash,
            model_id=request.model_id,
            model_hash=request.model_hash,
            outputs=(output,),
        )
        return SimpleNamespace(request=request, result=result, workspace_path=workspace)


class PiperDispatchVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakePiperAdapter.calls = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("piper-dispatch-vertical")
        goal = self.runtime.create_goal("produce one governed voice line")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(flow, "synthesize a voice line", required_capabilities=("media.audio.tts",))
        activate_dependency_ready_task(self.runtime, self.task_id, 0)
        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.PIPER_TTS,
            operation=AudioOperation.SYNTHESIZE_SPEECH,
            backend_id="piper",
            backend_version="1.6.0",
            runtime_hash="sha256:" + "1" * 64,
            target_sample_rate=22_050,
            target_channels=1,
            model_id="en_US-test-medium",
            model_hash="sha256:" + "2" * 64,
            model_config_hash="sha256:" + "3" * 64,
            license_id="CC0-1.0",
            license_hash="sha256:" + "4" * 64,
        )
        AudioProfileStore(self.runtime).put(self.profile)
        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create((full.capability("media.audio.tts"),), (full.adapter("originforge.audio.piper"),))
        policy = CapabilityRoutingPolicy.create(catalog, ordered_adapter_ids=("originforge.audio.piper",), allowed_capability_ids=("media.audio.tts",))
        self.cap_store = ProductionCapabilityStore(self.runtime)
        self.cap_store.publish_catalog(catalog)
        self.cap_store.publish_policy(policy, catalog)
        route = self.cap_store.resolve_and_publish(self.task_id, catalog.catalog_id, policy.routing_policy_id)
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, self.cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        payload = {
            "operation": "SYNTHESIZE_SPEECH",
            "text": "A bounded test voice line.",
            "max_duration_ms": 10_000,
            "timeout_seconds": 30,
            "output_relative_path": "exports/voice.wav",
        }
        ref = WorkOrderInputRef(WorkOrderRefType.AUDIO_PROFILE, self.profile.profile_id, self.profile.profile_hash.removeprefix("sha256:"), "audio_profile")
        work_order = create_current_work_order(self.runtime, self.cap_store, dispatch_catalog, validators, route.route_decision_id, payload=payload, input_refs=(ref,))
        work_audit = audit_work_order_frozen(self.cap_store, dispatch_catalog, validators, work_order)
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(work_audit)
        bundle = create_input_resolution_bundle(wo_store, build_dispatch_input_resolver_registry(), work_order.work_order_id, work_audit.work_order_audit_id)
        binding = create_dispatch_binding(wo_store, build_dispatch_input_resolver_registry(), build_builtin_dispatch_binder_registry(), bundle)
        self.binding = binding
        binding_audit = audit_dispatch_binding_frozen(wo_store, build_dispatch_input_resolver_registry(), build_builtin_dispatch_binder_registry(), bundle, binding)
        dispatch_store = ProductionDispatchStore(wo_store, build_dispatch_input_resolver_registry(), build_builtin_dispatch_binder_registry())
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        self.claim = acquire_dispatch_claim(self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_governed_dispatch_and_recovery_do_not_replay(self) -> None:
        paths = {
            "ORIGIN_FORGE_PIPER_RUNTIME_ROOT": self.root / "piper-runtime",
            "ORIGIN_FORGE_PIPER_EXECUTABLE": self.root / "piper-runtime" / "piper",
            "ORIGIN_FORGE_PIPER_ESPEAK_DATA": self.root / "piper-runtime" / "espeak",
            "ORIGIN_FORGE_PIPER_MODEL": self.root / "voice.onnx",
            "ORIGIN_FORGE_PIPER_MODEL_CONFIG": self.root / "voice.json",
            "ORIGIN_FORGE_PIPER_LICENSE": self.root / "voice.license",
        }
        with patch.dict("os.environ", {key: str(value) for key, value in paths.items()}), patch(
            "origin_forge.production_dispatch_invocation_piper_owner.PiperAudioAdapter", _FakePiperAdapter
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(_FakePiperAdapter.calls, 1)
        self.assertEqual(completed.execution.execution_owner_id, PIPER_EXECUTION_OWNER_ID)
        self.assertEqual(completed.execution.status.value, "RETURNED")
        binding = read_audio_dispatch_output_binding(self.runtime, completed.execution.execution_id)
        self.assertEqual(binding.output_relative_path, "exports/voice.wav")
        recovered = recover_piper_dispatch_execution_once(self.runtime, completed.execution.execution_id)
        self.assertEqual(recovered.audio_result, completed.audio_result)
        self.assertEqual(_FakePiperAdapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
