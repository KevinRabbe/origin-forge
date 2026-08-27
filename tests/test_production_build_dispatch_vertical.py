from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.apply import IsolatedPatchApplier
from origin_forge.audit import WorkspaceAuditor
from origin_forge.patches import parse_patch_proposal
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
from origin_forge.production_dispatch_invocation import (
    ProductionDispatchInvocationError,
    ProductionDispatchInvocationRecoveryRequired,
    dispatch_claim_once,
)
from origin_forge.production_dispatch_invocation_build import (
    recover_build_dispatch_execution_once,
)
from origin_forge.production_dispatch_phase_resolvers import (
    build_dispatch_input_resolver_registry,
)
from origin_forge.production_dispatch_read import (
    inspect_dispatch_binding_currentness_readonly,
)
from origin_forge.production_dispatch_store import ProductionDispatchStore
from origin_forge.production_task_activation import activate_dependency_ready_task
from origin_forge.production_work_order_audit import audit_work_order_frozen
from origin_forge.production_work_order_builtin import (
    build_builtin_dispatch_catalog,
    build_builtin_dispatch_validator_registry,
)
from origin_forge.production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.production_work_orders import create_current_work_order
from origin_forge.repository import RepositoryReader
from origin_forge.runtime import OriginForgeRuntime
from origin_forge.sandbox import SandboxGuarantees, SandboxResult
from origin_forge.state import TaskStatus, WorkspaceStatus
from origin_forge.workspaces import GitWorkspaceManager


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL)


class _FakeBuildBackend:
    backend_id = "fake-build"
    guarantees = SandboxGuarantees(True, True, True, True)

    def __init__(self) -> None:
        self.calls = 0

    @property
    def provenance(self) -> dict[str, object]:
        return {"fake": True}

    def available(self) -> bool:
        return True

    def run(self, _job):
        self.calls += 1
        return SandboxResult(0, "built", "", False, 4)


class BuildDispatchVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "test@example.com")
        _git(self.root, "config", "user.name", "Origin Forge Test")
        (self.root / "main.py").write_text("print('build')\n", encoding="utf-8")
        _git(self.root, "add", "main.py")
        _git(self.root, "commit", "-qm", "initial")

        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("build-dispatch-vertical")
        goal = self.runtime.create_goal("run one governed build")
        flow = self.runtime.create_flow(goal)
        source_task = self.runtime.create_task(flow, "prepare build source")
        source_revision = self.runtime.transition_task(source_task, TaskStatus.READY, expected_revision=0)
        self.runtime.transition_task(source_task, TaskStatus.RUNNING, expected_revision=source_revision)
        workspaces = GitWorkspaceManager(self.runtime)
        workspace_id = workspaces.create(source_task)
        expected_hash = RepositoryReader(self.root).hash_file("main.py")
        proposal = parse_patch_proposal(json.dumps({
            "summary": "prepare source",
            "changes": [{"operation": "UPDATE", "path": "main.py", "expected_hash": expected_hash, "content": "print('prepared build')\n"}],
            "notes": [],
        }))
        IsolatedPatchApplier(self.runtime, workspaces)._apply(workspace_id, proposal)
        self.assertTrue(WorkspaceAuditor(self.runtime, workspaces)._audit(workspace_id, proposal).passed)
        workspace_row = workspaces.get(workspace_id)
        workspace_projection = {
            key: workspace_row[key]
            for key in ("id", "task_id", "path", "base_commit", "status", "revision")
        }
        task_id = self.runtime.create_task(
            flow, "build the project", required_capabilities=("build.integration",)
        )
        activate_dependency_ready_task(self.runtime, task_id, 0)
        self.task_id = task_id
        (self.root / ".origin-forge" / "config.toml").write_text(
            '''version = 2
policy_profile = "local-default"
[sandbox]
backend = "podman"
image = "origin-forge-test:build"
network = false
[commands]
build = [{ name = "compile", argv = ["python", "-m", "compileall", "."], required = true }]
test = []
''',
            encoding="utf-8",
        )

        full = build_builtin_capability_catalog()
        catalog = CapabilityCatalog.create(
            (full.capability("build.integration"),),
            (full.adapter("originforge.build.integration"),),
        )
        policy = CapabilityRoutingPolicy.create(
            catalog,
            ordered_adapter_ids=("originforge.build.integration",),
            allowed_capability_ids=("build.integration",),
        )
        cap_store = ProductionCapabilityStore(self.runtime)
        cap_store.publish_catalog(catalog)
        cap_store.publish_policy(policy, catalog)
        route = cap_store.resolve_and_publish(task_id, catalog.catalog_id, policy.routing_policy_id)
        validators = build_builtin_dispatch_validator_registry()
        dispatch_catalog = build_builtin_dispatch_catalog(catalog)
        wo_store = ProductionWorkOrderStore(self.runtime, cap_store, validators)
        wo_store.publish_dispatch_catalog(dispatch_catalog)
        work_order = create_current_work_order(
            self.runtime,
            cap_store,
            dispatch_catalog,
            validators,
            route.route_decision_id,
            payload={"operation": "BUILD"},
            input_refs=(WorkOrderInputRef(WorkOrderRefType.WORKSPACE, workspace_id, content_hash(workspace_projection), "build_workspace", revision=workspace_row["revision"]),),
        )
        work_audit = audit_work_order_frozen(cap_store, dispatch_catalog, validators, work_order)
        wo_store.publish_work_order(work_order)
        wo_store.publish_audit(work_audit)
        resolver = build_dispatch_input_resolver_registry()
        binders = build_builtin_dispatch_binder_registry()
        bundle = create_input_resolution_bundle(
            wo_store, resolver, work_order.work_order_id, work_audit.work_order_audit_id
        )
        binding = create_dispatch_binding(wo_store, resolver, binders, bundle)
        binding_audit = audit_dispatch_binding_frozen(
            wo_store, resolver, binders, bundle, binding
        )
        if binding_audit.status.value != "PASS":
            raise AssertionError(binding_audit.to_dict())
        dispatch_store = ProductionDispatchStore(wo_store, resolver, binders)
        dispatch_store.publish_input_resolution(bundle)
        dispatch_store.publish_binding(binding)
        dispatch_store.publish_audit(binding_audit)
        currentness = inspect_dispatch_binding_currentness_readonly(
            self.runtime,
            bundle.input_resolution_id,
            binding.dispatch_binding_id,
            binding_audit.binding_audit_id,
            resolver,
            binders,
        )
        if currentness.status.value != "CURRENT_READY":
            raise AssertionError(currentness.to_dict())
        self.claim = acquire_dispatch_claim(
            self.runtime, binding.dispatch_binding_id, binding_audit.binding_audit_id, 1
        )

    def tearDown(self) -> None:
        for row in GitWorkspaceManager(self.runtime).list():
            try:
                GitWorkspaceManager(self.runtime).abandon(row["id"])
            except Exception:
                pass
        self.tempdir.cleanup()

    def test_build_dispatch_and_recovery_do_not_replay(self) -> None:
        backend = _FakeBuildBackend()
        with patch("origin_forge.production_execution_assembly.create_sandbox_backend", return_value=backend):
            completed = dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        self.assertEqual(completed.execution.status.value, "RETURNED")
        self.assertTrue(completed.build_result.passed)
        self.assertEqual(backend.calls, 1)
        recovered = recover_build_dispatch_execution_once(
            self.runtime, completed.execution.execution_id
        )
        self.assertEqual(recovered.execution.execution_id, completed.execution.execution_id)
        self.assertEqual(recovered.build_result.workspace_id, completed.build_result.workspace_id)
        self.assertEqual(backend.calls, 1)
        rows = self.runtime.list_verifications("WORKSPACE", completed.build_result.workspace_id)
        build_rows = [row for row in rows if row["verification_type"].startswith("sandbox-build:")]
        self.assertEqual(build_rows[0]["status"], "PASS")
        self.assertIn(completed.execution.execution_id, build_rows[0]["evidence_json"])

    def test_terminalization_interruption_recovers_from_durable_evidence(self) -> None:
        backend = _FakeBuildBackend()
        with (
            patch("origin_forge.production_execution_assembly.create_sandbox_backend", return_value=backend),
            patch(
                "origin_forge.production_dispatch_invocation._record_returned_or_recovery",
                side_effect=RuntimeError("interrupted"),
            ),
            self.assertRaises(RuntimeError),
        ):
            dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        with self.runtime.store.session() as conn:
            execution_id = conn.execute(
                "SELECT execution_id FROM dispatch_executions WHERE claim_id = ?",
                (self.claim.claim_id,),
            ).fetchone()["execution_id"]
        with patch("origin_forge.production_execution_assembly.create_sandbox_backend", side_effect=AssertionError("must not assemble backend")):
            recovered = recover_build_dispatch_execution_once(self.runtime, execution_id)
        self.assertEqual(recovered.execution.status.value, "RETURNED")
        self.assertEqual(backend.calls, 1)

    def test_build_requires_configured_sandbox_before_start(self) -> None:
        with self.assertRaises(ProductionDispatchInvocationError):
            dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

    def test_stale_audited_workspace_rejects_dispatch_before_backend(self) -> None:
        workspaces = GitWorkspaceManager(self.runtime)
        row = workspaces.list()[0]
        workspaces.transition(
            row["id"],
            WorkspaceStatus.FAILED,
            expected_revision=int(row["revision"]),
            event_type="TEST_WORKSPACE_STALE",
        )
        with self.assertRaises(ProductionDispatchInvocationError):
            dispatch_claim_once(self.runtime, self.claim.claim_id, 0)

    def test_tampered_durable_build_evidence_is_not_recovered(self) -> None:
        backend = _FakeBuildBackend()
        with (
            patch("origin_forge.production_execution_assembly.create_sandbox_backend", return_value=backend),
            patch(
                "origin_forge.production_dispatch_invocation._record_returned_or_recovery",
                side_effect=RuntimeError("interrupted"),
            ),
            self.assertRaises(RuntimeError),
        ):
            dispatch_claim_once(self.runtime, self.claim.claim_id, 0)
        with self.runtime.store.session() as conn:
            execution_id = conn.execute(
                "SELECT execution_id FROM dispatch_executions WHERE claim_id = ?",
                (self.claim.claim_id,),
            ).fetchone()["execution_id"]
            conn.execute(
                "UPDATE verifications SET evidence_json = ? WHERE evidence_json LIKE ?",
                ("{}", f"%{execution_id}%"),
            )
        with self.assertRaises(ProductionDispatchInvocationRecoveryRequired):
            recover_build_dispatch_execution_once(self.runtime, execution_id)
        self.assertEqual(backend.calls, 1)


if __name__ == "__main__":
    unittest.main()
