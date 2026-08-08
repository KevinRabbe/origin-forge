from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.model_scheduler import (
    ModelProfileError,
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelScheduler,
    ModelSelectionPolicy,
)
from origin_forge.resource_scheduler import (
    GpuCapacity,
    GpuResourceRequest,
    ResourceCapacity,
    ResourceRequest,
    ResourceScheduler,
)
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import (
    RuntimeModelScheduleRecorder,
    ScheduledModelAdapter,
)
from origin_forge.state import FlowStatus, TaskStatus


class RecordingModel:
    def __init__(self, model_id: str, resources: ResourceScheduler, recorder_events=None):
        self._model_id = model_id
        self.resources = resources
        self.requests = []
        self.recorder_events = recorder_events

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self.last_status = self.resources.status()
        if self.recorder_events is not None:
            self.recorder_seen_during_generate = bool(self.recorder_events)
        return ModelResponse("{}", self.model_id, input_tokens=10, output_tokens=2)


class RecordingLoader:
    def __init__(self, resources: ResourceScheduler, *, loaded_model_id: str | None = None):
        self.resources = resources
        self.loaded_model_id = loaded_model_id
        self.loaded = []
        self.unloaded = []

    def load(self, profile, lease):
        status = self.resources.status()
        self.loaded.append((profile.profile_id, lease.lease_id, status.used_ram_mib))
        return RecordingModel(self.loaded_model_id or profile.model_id, self.resources)

    def unload(self, instance):
        self.unloaded.append(instance.model_id)
        self.status_during_unload = self.resources.status()


class RecordingScheduleRecorder:
    def __init__(self):
        self.events = []

    def record(self, run_id, scheduled):
        self.events.append((run_id, scheduled.profile.profile_id, scheduled.fallback_used))
        return "VERIFY-test"


class ScheduledModelAdapterTests(unittest.TestCase):
    def _scheduler(self, *, gpu_vram: int = 8192):
        resources = ResourceScheduler(
            ResourceCapacity(
                cpu_slots=8,
                ram_mib=32768,
                gpus=(GpuCapacity("gpu0", gpu_vram, reserve_vram_mib=1024),),
            )
        )
        profiles = ModelProfileRegistry(
            (
                ModelResourceProfile(
                    "strong",
                    ModelRole.CODER_STRONG,
                    "model-strong",
                    "test-runtime",
                    ResourceRequest(
                        cpu_slots=2,
                        ram_mib=4096,
                        gpu=GpuResourceRequest(vram_mib=12288),
                    ),
                ),
                ModelResourceProfile(
                    "strong-small",
                    ModelRole.CODER_STRONG,
                    "model-small",
                    "test-runtime",
                    ResourceRequest(
                        cpu_slots=2,
                        ram_mib=4096,
                        gpu=GpuResourceRequest(vram_mib=4096),
                    ),
                ),
            )
        )
        return ModelScheduler(profiles, resources), resources

    @staticmethod
    def _request(run_id: str = "RUN-test") -> ModelRequest:
        return ModelRequest(
            run_id=run_id,
            task_id="TASK-test",
            instructions="test",
            context={},
            response_schema={"type": "object"},
        )

    def test_adapter_uses_explicit_fallback_and_holds_lease_through_generation(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        loader = RecordingLoader(resources)
        recorder = RecordingScheduleRecorder()
        adapter = ScheduledModelAdapter(
            scheduler,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
            loader,
            recorder=recorder,
        )

        self.assertEqual(adapter.model_id, "model-strong")
        response = adapter.generate(self._request())

        self.assertEqual(response.model_id, "model-small")
        self.assertEqual(recorder.events, [("RUN-test", "strong-small", True)])
        self.assertEqual(loader.loaded[0][0], "strong-small")
        self.assertEqual(loader.loaded[0][2], 4096)
        self.assertEqual(loader.unloaded, ["model-small"])
        self.assertEqual(resources.status().active_leases, ())

    def test_loaded_adapter_identity_must_match_selected_profile(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        loader = RecordingLoader(resources, loaded_model_id="wrong-model")
        adapter = ScheduledModelAdapter(
            scheduler,
            ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong-small"),
            loader,
        )
        with self.assertRaisesRegex(ModelProfileError, "identity does not match"):
            adapter.generate(self._request())
        self.assertEqual(loader.unloaded, ["wrong-model"])
        self.assertEqual(resources.status().active_leases, ())

    def test_profile_role_chain_is_validated_at_adapter_construction(self) -> None:
        scheduler, resources = self._scheduler(gpu_vram=8192)
        vision = ModelResourceProfile(
            "vision",
            ModelRole.VISION,
            "vision-model",
            "test-runtime",
            ResourceRequest(cpu_slots=1, ram_mib=1024),
        )
        scheduler = ModelScheduler(
            ModelProfileRegistry((*scheduler.registry.all(), vision)),
            resources,
        )
        with self.assertRaisesRegex(ModelProfileError, "does not match"):
            ScheduledModelAdapter(
                scheduler,
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong-small", ("vision",)),
                RecordingLoader(resources),
            )
        self.assertEqual(resources.status().active_leases, ())

    def test_runtime_recorder_persists_selected_profile_on_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = OriginForgeRuntime(root)
            runtime.initialize("schedule-provenance")
            goal = runtime.create_goal("test scheduling")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "run model")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)
            run_id = runtime.start_run(task, role="EXECUTOR", model_profile="model-strong")

            scheduler, resources = self._scheduler(gpu_vram=8192)
            scheduled = scheduler.acquire(
                run_id,
                ModelSelectionPolicy(ModelRole.CODER_STRONG, "strong", ("strong-small",)),
            )
            verification_id = RuntimeModelScheduleRecorder(runtime).record(run_id, scheduled)
            self.assertTrue(verification_id.startswith("VERIFY-"))

            records = runtime.list_verifications("RUN", run_id)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["verification_type"], "model-resource-selection")
            self.assertEqual(records[0]["status"], "PASS")
            evidence = json.loads(records[0]["evidence_json"])
            metrics = json.loads(records[0]["metrics_json"])
            self.assertEqual(evidence["requested_profile_id"], "strong")
            self.assertEqual(evidence["selected_profile_id"], "strong-small")
            self.assertTrue(evidence["fallback_used"])
            self.assertEqual(evidence["gpu_device_id"], "gpu0")
            self.assertEqual(metrics["ram_mib"], 4096)
            self.assertEqual(metrics["vram_mib"], 4096)
            scheduler.release(scheduled)
            self.assertEqual(resources.status().active_leases, ())


if __name__ == "__main__":
    unittest.main()
