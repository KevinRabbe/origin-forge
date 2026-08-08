from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from origin_forge.model import ModelRequest, ModelResponse
from origin_forge.model_scheduler import (
    ModelProfileRegistry,
    ModelResourceProfile,
    ModelRole,
    ModelScheduler,
    ModelSelectionPolicy,
)
from origin_forge.repository import RepositoryReader
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
from origin_forge.worker import LocalPatchWorker


class ProposalModel:
    def __init__(self, model_id: str, expected_hash: str):
        self._model_id = model_id
        self.expected_hash = expected_hash
        self.requests: list[ModelRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            json.dumps(
                {
                    "summary": "update greeting",
                    "changes": [
                        {
                            "operation": "UPDATE",
                            "path": "hello.py",
                            "expected_hash": self.expected_hash,
                            "content": "print('scheduled')\n",
                        }
                    ],
                    "notes": [],
                }
            ),
            self.model_id,
            model_hash="sha256:actual-model",
            input_tokens=17,
            output_tokens=23,
        )


class ProposalLoader:
    def __init__(self, expected_hash: str):
        self.expected_hash = expected_hash
        self.instances: list[ProposalModel] = []
        self.unloaded: list[str] = []

    def load(self, profile, lease):
        model = ProposalModel(profile.model_id, self.expected_hash)
        self.instances.append(model)
        return model

    def unload(self, instance):
        self.unloaded.append(instance.model_id)


class ScheduledWorkerIntegrationTests(unittest.TestCase):
    def test_worker_uses_scheduled_fallback_without_learning_resource_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "hello.py").write_text("print('old')\n", encoding="utf-8")
            runtime = OriginForgeRuntime(root)
            runtime.initialize("scheduled-worker")
            goal = runtime.create_goal("scheduled worker integration")
            flow = runtime.create_flow(goal)
            runtime.transition_flow(flow, FlowStatus.RUNNING, expected_revision=0)
            task = runtime.create_task(flow, "change greeting")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

            repository = RepositoryReader(root)
            expected_hash = repository.hash_file("hello.py")
            resources = ResourceScheduler(
                ResourceCapacity(
                    cpu_slots=8,
                    ram_mib=32768,
                    gpus=(GpuCapacity("gpu0", 8192, reserve_vram_mib=1024),),
                )
            )
            registry = ModelProfileRegistry(
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
            loader = ProposalLoader(expected_hash)
            adapter = ScheduledModelAdapter(
                ModelScheduler(registry, resources),
                ModelSelectionPolicy(
                    ModelRole.CODER_STRONG,
                    "strong",
                    ("strong-small",),
                ),
                loader,
                recorder=RuntimeModelScheduleRecorder(runtime),
            )

            result = LocalPatchWorker(
                runtime,
                adapter,
                repository=repository,
            ).execute(task, selected_paths=["hello.py"])

            self.assertEqual(result.proposal.changes[0].content, "print('scheduled')\n")
            self.assertEqual(len(loader.instances), 1)
            self.assertEqual(loader.instances[0].model_id, "model-small")
            self.assertEqual(loader.unloaded, ["model-small"])
            self.assertEqual(resources.status().active_leases, ())
            self.assertEqual((root / "hello.py").read_text(encoding="utf-8"), "print('old')\n")

            run = runtime.get_run(result.run_id)
            # Existing Worker records the requested primary model profile. The
            # exact selected fallback is independent Run verification evidence.
            self.assertEqual(run["model_profile"], "model-strong")
            records = [
                item
                for item in runtime.list_verifications("RUN", result.run_id)
                if item["verification_type"] == "model-resource-selection"
            ]
            self.assertEqual(len(records), 1)
            evidence = json.loads(records[0]["evidence_json"])
            self.assertEqual(evidence["requested_profile_id"], "strong")
            self.assertEqual(evidence["selected_profile_id"], "strong-small")
            self.assertTrue(evidence["fallback_used"])

            with runtime.store.session() as conn:
                response = conn.execute(
                    "SELECT model_id FROM artifacts WHERE id = ?",
                    (result.response_artifact_id,),
                ).fetchone()
            self.assertEqual(response["model_id"], "model-small")


if __name__ == "__main__":
    unittest.main()
