from __future__ import annotations

import hashlib
import struct
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
from origin_forge.audio_profiles import AudioProfileKind, GovernedAudioProfile
from origin_forge.audio_wav import encode_pcm16_wav, inspect_pcm16_wav
from origin_forge.config import DEFAULT_CONFIG
from origin_forge.lineage import OriginForgeLineage
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
from origin_forge.production_dispatch_invocation_ffmpeg_owner import (
    recover_ffmpeg_dispatch_execution_once,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_read import (
    inspect_dispatch_binding_currentness_readonly,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_execution_owner_audio import FFMPEG_EXECUTION_OWNER_ID
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


class _FakeFfmpegAdapter:
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
        data = encode_pcm16_wav(
            channels=request.target_channels,
            sample_rate=request.target_sample_rate,
            pcm_bytes=b"".join(struct.pack("<h", value) for value in (10, 20, 30, 40)),
        )
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
            model_id=None,
            model_hash=None,
            outputs=(output,),
        )
        return SimpleNamespace(request=request, result=result, workspace_path=workspace)


class FfmpegDispatchVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeFfmpegAdapter.calls = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("ffmpeg-dispatch-vertical")
        goal = self.runtime.create_goal("process one governed audio source")
        flow = self.runtime.create_flow(goal)
        self.task_id = self.runtime.create_task(
            flow, "normalize a source WAV", required_capabilities=("media.audio.process",)
        )
        activate_dependency_ready_task(self.runtime, self.task_id, 0)

        self.executable = self.root / "tools" / "ffmpeg.exe"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"bounded fake ffmpeg executable")
        config_path = self.root / ".origin-forge" / "config.toml"
        config_path.write_text(
            DEFAULT_CONFIG + f'ffmpeg = "{self.executable.as_posix()}"\n',
            encoding="utf-8",
        )
        self.profile = GovernedAudioProfile.create(
            kind=AudioProfileKind.FFMPEG_PCM16,
            operation=AudioOperation.PROCESS_AUDIO,
            backend_id="ffmpeg",
            backend_version="8.1.2",
            runtime_hash="sha256:" + hashlib.sha256(self.executable.read_bytes()).hexdigest(),
            target_sample_rate=8_000,
            target_channels=1,
        )
        from origin_forge.audio_profiles import AudioProfileStore

        AudioProfileStore(self.runtime).put(self.profile)
        source_path = self.root / "exports" / "source.wav"
        source_path.parent.mkdir()
        source_path.write_bytes(
            encode_pcm16_wav(channels=1, sample_rate=8_000, pcm_bytes=b"\x01\x00\x02\x00")
        )
        self.source_artifact_id = OriginForgeLineage(self.runtime).create_artifact(
            artifact_type="TEST_AUDIO_WAV", path_or_uri=str(source_path), status="PRODUCED"
        )
        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.audio.process"),),
            (full.adapter("originforge.audio.ffmpeg"),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.audio.ffmpeg",),
            allowed_capability_ids=("media.audio.process",),
        )
        self.cap_store = ProductionCapabilityStore(self.runtime)
        self.cap_store.publish_catalog(catalog)
        self.cap_store.publish_policy(policy, catalog)
        route = self.cap_store.resolve_and_publish(
            self.task_id, catalog.catalog_id, policy.routing_policy_id
        )
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, self.cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        payload = {
            "operation": "PROCESS_AUDIO",
            "target_sample_rate": 8_000,
            "target_channels": 1,
            "max_duration_ms": 10_000,
            "timeout_seconds": 30,
            "output_relative_path": "exports/processed.wav",
        }
        source_ref = WorkOrderInputRef(
            WorkOrderRefType.ARTIFACT,
            self.source_artifact_id,
            inspect_pcm16_wav(source_path.read_bytes()).content_hash.removeprefix("sha256:"),
            "audio_source",
        )
        profile_ref = WorkOrderInputRef(
            WorkOrderRefType.AUDIO_PROFILE,
            self.profile.profile_id,
            self.profile.profile_hash.removeprefix("sha256:"),
            "audio_profile",
        )
        work_order = create_current_work_order(
            self.runtime,
            self.cap_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            payload=payload,
            input_refs=(source_ref, profile_ref),
        )
        work_audit = audit_work_order_frozen(self.cap_store, dispatch_catalog, validators, work_order)
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(work_audit)
        resolver = build_dispatch_input_resolver_registry()
        binder_registry = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(wo_store, resolver, work_order.work_order_id, work_audit.work_order_audit_id)
        binding = create_dispatch_binding(wo_store, resolver, binder_registry, bundle)
        binding_audit = audit_dispatch_binding_frozen(wo_store, resolver, binder_registry, bundle, binding)
        dispatch_store = ProductionDispatchStore(wo_store, resolver, binder_registry)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        if binding_audit.status.value != "PASS":
            raise AssertionError(binding_audit.to_dict())
        currentness = inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            bundle.input_resolution_id,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            resolver,
            binder_registry,
        )
        if currentness.status.value != "CURRENT_READY":
            raise AssertionError(currentness.to_dict())
        self.claim = acquire_dispatch_claim(self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_governed_ffmpeg_dispatch_and_recovery_do_not_replay(self) -> None:
        with patch(
            "origin_forge.production_dispatch_invocation_ffmpeg_owner.FfmpegAudioAdapter",
            _FakeFfmpegAdapter,
        ):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(_FakeFfmpegAdapter.calls, 1)
        self.assertEqual(completed.execution.execution_owner_id, FFMPEG_EXECUTION_OWNER_ID)
        self.assertEqual(completed.execution.status.value, "RETURNED")
        binding = read_audio_dispatch_output_binding(
            self.runtime, completed.execution.execution_id
        )
        self.assertEqual(binding.output_relative_path, "exports/processed.wav")
        recovered = recover_ffmpeg_dispatch_execution_once(
            self.runtime, completed.execution.execution_id
        )
        self.assertEqual(recovered.audio_result, completed.audio_result)
        self.assertEqual(_FakeFfmpegAdapter.calls, 1)

    def test_recovery_after_binding_publication_does_not_replay_ffmpeg(self) -> None:
        with (
            patch(
                "origin_forge.production_dispatch_invocation_ffmpeg_owner.FfmpegAudioAdapter",
                _FakeFfmpegAdapter,
            ),
            patch(
                "origin_forge.production_dispatch_invocation._record_returned_or_recovery",
                side_effect=RuntimeError("interrupted before terminalization"),
            ),
            self.assertRaises(RuntimeError),
        ):
            dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(_FakeFfmpegAdapter.calls, 1)
        with self.runtime.store.session() as conn:
            execution_id = conn.execute(
                "SELECT execution_id FROM dispatch_executions ORDER BY rowid DESC LIMIT 1"
            ).fetchone()["execution_id"]
        recovered = recover_ffmpeg_dispatch_execution_once(self.runtime, execution_id)
        self.assertEqual(recovered.execution.status.value, "RETURNED")
        self.assertEqual(_FakeFfmpegAdapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
