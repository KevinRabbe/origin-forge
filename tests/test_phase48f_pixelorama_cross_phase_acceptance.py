from __future__ import annotations

import binascii
import hashlib
import json
import os
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import origin_forge.production_manager_advance_once as advance_once_module
from origin_forge.lineage import OriginForgeLineage
from origin_forge.model import ModelResponse
from origin_forge.pixelorama_cli_export import PixeloramaCliExportResult
from origin_forge.production_capability_builtin import build_builtin_capability_catalog
from origin_forge.production_capability_models import CapabilityCatalog, CapabilityRoutingPolicy
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_dispatch_claim_models import DispatchClaimStatus
from origin_forge.production_dispatch_execution_models import DispatchExecutionStatus
from origin_forge.production_manager_advance_bounded import (
    BoundedManagerAdvanceStopReason,
    advance_production_manager_bounded,
)
from origin_forge.production_manager_advance_once import (
    ManagerAdvanceOnceStatus,
    advance_production_manager_once,
)
from origin_forge.production_pixelorama_export import PixeloramaCliExportService
from origin_forge.production_planning_capabilities import freeze_governed_planning_input
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_planning_models import (
    PlanProposal,
    PlanStep,
    PlanningEvidenceRef,
    audit_plan,
)
from origin_forge.production_preparation_policy_store import (
    create_preparation_policy_binding,
    publish_preparation_policy,
)
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.records import create_artifact
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.scheduled_model_adapter import ScheduledModelAdapter
from origin_forge.state import RunStatus, TaskStatus


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_PIXELORAMA_ADAPTER_ID = "originforge.pixelorama.export"


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\x00\xff\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


class _FakeCliAdapter:
    def __init__(self, runtime: OriginForgeRuntime, version: str):
        self.runtime = runtime
        self.version = version

    def execute(self, request, *, source_path):
        workspace = self.runtime.state_dir / "media-workspaces" / request.workspace_id
        (workspace / "inputs").mkdir(parents=True)
        (workspace / "exports").mkdir()
        (workspace / "runtime").mkdir()
        output = workspace / request.output_relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        data = _png()
        output.write_bytes(data)
        return PixeloramaCliExportResult(
            request=request,
            workspace_path=workspace,
            pixelorama_version=self.version,
            process_exit_code=0,
            output_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            output_byte_count=len(data),
            width=1,
            height=1,
            stdout=b"ok\n",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class Phase48FPixeloramaCrossPhaseAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _write_model_config(runtime: OriginForgeRuntime) -> None:
        runtime.state_dir.joinpath("config.toml").write_text(
            '''version = 6
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []

[code_intelligence]
lsp_servers = []

[resources]
enabled = true
cpu_slots = 8
ram_mib = 16384
max_active_leases = 8
gpus = []

[models]
profiles = [
  { profile_id = "strong", role = "coder_strong", model_id = "test-model", model_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime_id = "llamacpp-cpu", resources = { cpu_slots = 2, ram_mib = 4096 } }
]
policies = [
  { role = "coder_strong", primary_profile_id = "strong", fallback_profile_ids = [] }
]

[model_runtimes]
providers = [
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18082, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
''',
            encoding="utf-8",
        )

    @staticmethod
    def _profile_env(root: Path) -> dict[str, str]:
        return {
            "ORIGIN_FORGE_PIXELORAMA_EXECUTABLE": str((root / "tools" / "Pixelorama").resolve()),
            "ORIGIN_FORGE_PIXELORAMA_SHA256": "sha256:" + "1" * 64,
            "ORIGIN_FORGE_PIXELORAMA_VERSION": "v1.2-stable",
        }

    @staticmethod
    def _planner_response(scenario) -> ModelResponse:
        return ModelResponse(
            text=json.dumps(
                {
                    "contract_id": "pixelorama.spritesheet-export@1",
                    "input_refs": [
                        {
                            "ref_type": "ARTIFACT",
                            "ref_id": scenario.source_artifact_id,
                            "content_hash": scenario.source_hash,
                            "role": "pixelorama_project",
                            "revision": None,
                        }
                    ],
                    "payload": {},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            model_id="test-model",
            model_hash=_HASH_A,
            input_tokens=10,
            output_tokens=5,
        )

    def _scenario(self, *, steps: int = 1):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        runtime = OriginForgeRuntime(root)
        runtime.initialize(f"phase48f-pixelorama-{steps}")
        goal_id = runtime.create_goal("prove governed Pixelorama production dispatch")

        source = root / "assets" / "player.pxo"
        source.parent.mkdir()
        source.write_bytes(b"opaque-pixelorama-project\n")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        source_artifact_id = create_artifact(
            runtime.store,
            runtime.project_id(),
            artifact_type="PIXELORAMA_PROJECT",
            path_or_uri="assets/player.pxo",
            content_hash=source_hash,
        )

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("media.2d.export"),),
            (full.adapter(_PIXELORAMA_ADAPTER_ID),),
        )
        routing_policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=(_PIXELORAMA_ADAPTER_ID,),
            allowed_capability_ids=("media.2d.export",),
        )
        capability_store = ProductionCapabilityStore(runtime)
        capability_store.publish_catalog(catalog)
        capability_store.publish_policy(routing_policy, catalog)
        planning_input = freeze_governed_planning_input(
            runtime,
            goal_id,
            capability_store=capability_store,
            catalog_id=catalog.catalog_id,
            routing_policy_id=routing_policy.routing_policy_id,
            verified_state_refs=(PlanningEvidenceRef(source_artifact_id, source_hash),),
            project_intelligence_hash=_HASH_A,
            model_policy_hash=_HASH_B,
            resource_policy_hash=_HASH_C,
        )
        proposal = PlanProposal.create(
            planning_input=planning_input,
            summary="Prepare governed Pixelorama export Tasks through the bounded Manager.",
            steps=tuple(
                PlanStep(
                    step_key=f"pixelorama{index}",
                    objective=f"Export governed Pixelorama project {index}.",
                    acceptance_criteria=("Produce structural spritesheet export evidence.",),
                    constraints=("Do not adopt or complete the Task.",),
                    required_capabilities=("media.2d.export",),
                )
                for index in range(steps)
            ),
        )
        plan_audit = audit_plan(planning_input, proposal)
        planning = ProductionPlanningEvidenceStore(runtime)
        planning.publish_input(planning_input)
        planning.publish_proposal(proposal)
        planning.publish_audit(plan_audit)
        materialization = planning.materialize(
            planning_input_id=planning_input.planning_input_id,
            proposal_id=proposal.proposal_id,
            audit_id=plan_audit.audit_id,
        )

        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        work_order_store = ProductionWorkOrderStore(runtime, capability_store, validators)
        work_order_store.publish_dispatch_catalog(dispatch_catalog)
        preparation_policy = create_preparation_policy_binding(
            runtime,
            materialization_id=materialization.materialization_id,
            capability_catalog_id=catalog.catalog_id,
            capability_routing_policy_id=routing_policy.routing_policy_id,
            dispatch_contract_catalog_id=dispatch_catalog.dispatch_catalog_id,
        )
        publish_preparation_policy(runtime, preparation_policy)
        self._write_model_config(runtime)
        return SimpleNamespace(
            root=root,
            runtime=runtime,
            source=source,
            source_hash=source_hash,
            source_artifact_id=source_artifact_id,
            task_ids=tuple(binding.task_id for binding in materialization.task_bindings),
        )

    @staticmethod
    def _dispatch_rows(runtime: OriginForgeRuntime, task_id: str) -> tuple[list[dict], list[dict]]:
        with runtime.store.session() as conn:
            claims = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM dispatch_claims WHERE task_id = ? ORDER BY created_at, rowid",
                    (task_id,),
                )
            ]
            executions = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM dispatch_executions WHERE task_id = ? ORDER BY created_at, rowid",
                    (task_id,),
                )
            ]
        return claims, executions

    def _service_once(self, scenario, service, task_id, request, *, source_path):
        self.assertEqual(source_path, scenario.source.resolve())
        self.assertEqual(request.source_hash, "sha256:" + scenario.source_hash)
        self.assertEqual(request.source_byte_count, scenario.source.stat().st_size)
        self.assertEqual(scenario.runtime.get_task(task_id)["status"], TaskStatus.RUNNING.value)
        _, executions = self._dispatch_rows(scenario.runtime, task_id)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.STARTED.value)
        service.adapter = _FakeCliAdapter(
            scenario.runtime,
            self._profile_env(scenario.root)["ORIGIN_FORGE_PIXELORAMA_VERSION"],
        )
        return self.original_service_execute(service, task_id, request, source_path=source_path)

    def _advance_to_dispatch_ready(self, scenario) -> str:
        with patch.object(
            ScheduledModelAdapter,
            "generate",
            return_value=self._planner_response(scenario),
        ) as generate:
            first = advance_production_manager_once(scenario.runtime)
            second = advance_production_manager_once(scenario.runtime)
            third = advance_production_manager_once(scenario.runtime)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(
            (first.status, second.status, third.status),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
            ),
        )
        self.assertEqual(first.task_id, second.task_id)
        self.assertEqual(second.task_id, third.task_id)
        self.assertIsNotNone(third.task_id)
        return third.task_id

    def test_full_manager_path_exports_once_and_stops_with_task_running(self) -> None:
        scenario = self._scenario(steps=2)
        self.original_service_execute = PixeloramaCliExportService.execute
        with (
            patch.dict(os.environ, self._profile_env(scenario.root), clear=False),
            patch.object(
                ScheduledModelAdapter,
                "generate",
                return_value=self._planner_response(scenario),
            ) as generate,
            patch.object(
                PixeloramaCliExportService,
                "execute",
                autospec=True,
                side_effect=lambda service, task_id, request, *, source_path: self._service_once(
                    scenario, service, task_id, request, source_path=source_path
                ),
            ) as execute,
        ):
            result = advance_production_manager_bounded(scenario.runtime)

        self.assertEqual(generate.call_count, 1)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(
            tuple(step.status for step in result.steps),
            (
                ManagerAdvanceOnceStatus.PREPARATION_PLANNER_RETURNED,
                ManagerAdvanceOnceStatus.WORK_ORDER_AUDITED,
                ManagerAdvanceOnceStatus.PHASE34_READY,
                ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
            ),
        )
        self.assertEqual(result.stop_reason, BoundedManagerAdvanceStopReason.NON_CONTINUABLE_RESULT)
        selected_task_id = result.final_result.task_id
        self.assertIsNotNone(selected_task_id)
        self.assertTrue(all(step.task_id == selected_task_id for step in result.steps))
        self.assertEqual(scenario.runtime.get_task(selected_task_id)["status"], TaskStatus.RUNNING.value)
        self.assertEqual(scenario.runtime.list_verifications("TASK", selected_task_id), [])

        claims, executions = self._dispatch_rows(scenario.runtime, selected_task_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], DispatchClaimStatus.CONSUMED.value)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], DispatchExecutionStatus.RETURNED.value)
        runs = scenario.runtime.list_runs(selected_task_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["role"], PixeloramaCliExportService.RUN_ROLE)
        self.assertEqual(runs[0]["status"], RunStatus.SUCCEEDED.value)
        artifacts = [
            artifact
            for artifact in OriginForgeLineage(scenario.runtime).list_artifacts()
            if artifact["created_by_run_id"] == runs[0]["id"]
        ]
        self.assertEqual(
            tuple(sorted(artifact["type"] for artifact in artifacts)),
            ("PIXELORAMA_CLI_EXPORT_REQUEST", "PIXELORAMA_CLI_EXPORT_RESULT", "SPRITESHEET_EXPORT"),
        )

        newer_task_id = next(task_id for task_id in scenario.task_ids if task_id != selected_task_id)
        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(int(newer["revision"]), 0)
        newer_claims, newer_executions = self._dispatch_rows(scenario.runtime, newer_task_id)
        self.assertEqual(newer_claims, [])
        self.assertEqual(newer_executions, [])
        self.assertEqual(scenario.runtime.list_runs(newer_task_id), [])

    def test_concurrent_managers_have_one_claim_loser_at_most_one_export_and_no_fallback(self) -> None:
        scenario = self._scenario(steps=2)
        selected_task_id = self._advance_to_dispatch_ready(scenario)
        newer_task_id = next(task_id for task_id in scenario.task_ids if task_id != selected_task_id)
        real_dispatch = advance_once_module._dispatch_selected_candidate_once
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        service_calls = 0
        failures: list[BaseException] = []
        results = []
        self.original_service_execute = PixeloramaCliExportService.execute

        def racing_dispatch(runtime, candidate):
            self.assertEqual(candidate.task_id, selected_task_id)
            barrier.wait(timeout=30)
            return real_dispatch(runtime, candidate)

        def service_once(service, task_id, request, *, source_path):
            nonlocal service_calls
            with lock:
                service_calls += 1
            self.assertEqual(task_id, selected_task_id)
            return self._service_once(scenario, service, task_id, request, source_path=source_path)

        def worker() -> None:
            runtime = OriginForgeRuntime(scenario.root)
            try:
                value = advance_production_manager_once(runtime)
            except BaseException as exc:
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(value)

        with (
            patch.dict(os.environ, self._profile_env(scenario.root), clear=False),
            patch.object(
                advance_once_module,
                "_dispatch_selected_candidate_once",
                side_effect=racing_dispatch,
            ),
            patch.object(
                PixeloramaCliExportService,
                "execute",
                autospec=True,
                side_effect=service_once,
            ),
        ):
            threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertLessEqual(service_calls, 1)
        self.assertTrue(all(result.task_id == selected_task_id for result in results))
        self.assertEqual(
            sum(result.status is ManagerAdvanceOnceStatus.DISPATCH_CLAIM_NOT_ACQUIRED for result in results),
            1,
        )
        winner_statuses = {
            ManagerAdvanceOnceStatus.DISPATCH_NOT_STARTED,
            ManagerAdvanceOnceStatus.DISPATCH_RETURNED,
            ManagerAdvanceOnceStatus.DISPATCH_RAISED,
            ManagerAdvanceOnceStatus.DISPATCH_RECOVERY_REQUIRED,
        }
        self.assertEqual(sum(result.status in winner_statuses for result in results), 1)

        claims, executions = self._dispatch_rows(scenario.runtime, selected_task_id)
        self.assertEqual(len(claims), 1)
        self.assertIn(
            claims[0]["status"],
            {DispatchClaimStatus.ACTIVE.value, DispatchClaimStatus.CONSUMED.value},
        )
        self.assertLessEqual(len(executions), 1)
        self.assertLessEqual(len(scenario.runtime.list_runs(selected_task_id)), 1)

        newer = scenario.runtime.get_task(newer_task_id)
        self.assertEqual(newer["status"], TaskStatus.QUEUED.value)
        self.assertEqual(int(newer["revision"]), 0)
        newer_claims, newer_executions = self._dispatch_rows(scenario.runtime, newer_task_id)
        self.assertEqual(newer_claims, [])
        self.assertEqual(newer_executions, [])
        self.assertEqual(scenario.runtime.list_runs(newer_task_id), [])


if __name__ == "__main__":
    unittest.main()
