from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_forge.model_scheduler import ModelRole
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.production_goal_bootstrap_authority import (
    GoalBootstrapAuthorityError,
    acquire_current_goal_bootstrap,
    build_builtin_goal_bootstrap_owner,
    goal_planner_policy_hashes,
    prepare_goal_bootstrap_input,
    project_intelligence_projection_hash,
)
from origin_forge.production_goal_bootstrap_models import (
    GoalBootstrapStage,
    GoalBootstrapStatus,
)
from origin_forge.production_goal_bootstrap_store import read_goal_bootstrap_receipt
from origin_forge.production_planning_evidence import ProductionPlanningEvidenceStore
from origin_forge.production_work_order_builtin import build_builtin_dispatch_validator_registry
from origin_forge.production_work_order_store import ProductionWorkOrderStore
from origin_forge.runtime import OriginForgeRuntime


_VALID_CONFIG = '''version = 6
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
  { runtime_id = "llamacpp-cpu", provider_kind = "originforge.llamacpp-managed-cpu@1", provider_contract_version = "1", executable_path = "missing/llama-server", executable_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", port = 18081, startup_timeout_seconds = 30, request_timeout_seconds = 300, shutdown_timeout_seconds = 10, profile_bindings = [ { profile_id = "strong", model_path = "missing/model.gguf", model_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" } ] }
]
'''


_DISABLED_CONFIG = '''version = 6
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
enabled = false
gpus = []

[models]
profiles = []
policies = []

[model_runtimes]
providers = []
'''


class SimulatedCrash(BaseException):
    pass


class GoalBootstrapAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("phase45b-governed-input")
        self.goal_id = self.runtime.create_goal("plan one bounded code change")
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _VALID_CONFIG,
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _counts(self) -> dict[str, int]:
        with self.runtime.store.session() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "runs",
                    "planning_inputs",
                    "plan_proposals",
                    "plan_audits",
                    "plan_materializations",
                )
            }

    def test_owner_is_stable_and_cross_checks_current_code_authorities(self) -> None:
        first = build_builtin_goal_bootstrap_owner()
        second = build_builtin_goal_bootstrap_owner()
        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 64)
        self.assertEqual(first.owner_id, "originforge.bootstrap.goal-planner@1")
        self.assertEqual(first.bootstrap_contract_version, "1")
        self.assertEqual(first.planner_contract_id, "BoundedProductionPlanner.propose@1")
        self.assertEqual(first.semantic_model_role, ModelRole.CODER_STRONG)
        self.assertEqual(first.supported_capability_id, "code.change")
        self.assertEqual(first.supported_adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(first.supported_dispatch_contract_id, "code.bounded-retry@1")

    def test_prepares_exact_code_only_authority_and_input_without_planner(self) -> None:
        receipt = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        before = self._counts()
        durable, planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            receipt.bootstrap_id,
        )

        self.assertEqual(durable.stage, GoalBootstrapStage.PLANNING_INPUT_PUBLISHED)
        self.assertEqual(durable.status, GoalBootstrapStatus.ACTIVE)
        self.assertEqual(durable.revision, 2)
        self.assertEqual(durable.planning_input_id, planning_input.planning_input_id)
        self.assertEqual(durable.planning_input_hash, planning_input.content_hash)
        self.assertEqual(planning_input.capability_ids, ("code.change",))
        self.assertEqual(planning_input.active_design_rule_refs, ())

        capability_store = ProductionCapabilityStore(self.runtime)
        catalog = capability_store.load_catalog(durable.capability_catalog_id)
        policy = capability_store.load_policy(durable.capability_routing_policy_id)
        self.assertEqual(catalog.content_hash, durable.capability_catalog_hash)
        self.assertEqual(policy.content_hash, durable.capability_routing_policy_hash)
        self.assertEqual(policy.allowed_capability_ids, ("code.change",))
        self.assertEqual(
            policy.ordered_adapter_ids,
            ("originforge.code.bounded-retry",),
        )

        work_orders = ProductionWorkOrderStore(
            self.runtime,
            capability_store,
            build_builtin_dispatch_validator_registry(),
        )
        dispatch = work_orders.load_dispatch_catalog(
            durable.dispatch_contract_catalog_id
        )
        self.assertEqual(dispatch.content_hash, durable.dispatch_contract_catalog_hash)
        self.assertEqual(len(dispatch.contracts), 1)
        contract = dispatch.contracts[0]
        self.assertEqual(contract.adapter_id, "originforge.code.bounded-retry")
        self.assertEqual(contract.contract_id, "code.bounded-retry@1")

        expected_refs = {
            (durable.capability_catalog_id, durable.capability_catalog_hash),
            (
                durable.capability_routing_policy_id,
                durable.capability_routing_policy_hash,
            ),
        }
        self.assertEqual(
            {(ref.ref_id, ref.content_hash) for ref in planning_input.verified_state_refs},
            expected_refs,
        )
        self.assertEqual(
            planning_input.project_intelligence_hash,
            project_intelligence_projection_hash(self.runtime),
        )
        model_hash, resource_hash = goal_planner_policy_hashes(self.runtime)
        self.assertEqual(planning_input.model_policy_hash, model_hash)
        self.assertEqual(planning_input.resource_policy_hash, resource_hash)

        after = self._counts()
        self.assertEqual(after["runs"], before["runs"])
        self.assertEqual(after["plan_proposals"], before["plan_proposals"])
        self.assertEqual(after["plan_audits"], before["plan_audits"])
        self.assertEqual(after["plan_materializations"], before["plan_materializations"])
        self.assertEqual(after["planning_inputs"], before["planning_inputs"] + 1)

    def test_restart_reuses_exact_receipt_authority_and_planning_input(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        first_receipt, first_input = prepare_goal_bootstrap_input(
            self.runtime,
            acquired.bootstrap_id,
        )
        before_files = {
            path.relative_to(self.runtime.state_dir).as_posix(): path.read_bytes()
            for path in self.runtime.state_dir.rglob("*.json")
        }
        before_counts = self._counts()

        restarted = OriginForgeRuntime(self.root)
        second_receipt, second_input = prepare_goal_bootstrap_input(
            restarted,
            acquired.bootstrap_id,
        )
        after_files = {
            path.relative_to(restarted.state_dir).as_posix(): path.read_bytes()
            for path in restarted.state_dir.rglob("*.json")
        }
        with restarted.store.session() as conn:
            after_counts = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in before_counts
            }

        self.assertEqual(second_receipt, first_receipt)
        self.assertEqual(second_input, first_input)
        self.assertEqual(after_files, before_files)
        self.assertEqual(after_counts, before_counts)

    def test_crash_after_authority_publish_before_checkpoint_leaves_only_orphans(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        with patch(
            "origin_forge.production_goal_bootstrap_authority."
            "checkpoint_goal_bootstrap_authority_published",
            side_effect=SimulatedCrash("after authority publish"),
        ):
            with self.assertRaises(SimulatedCrash):
                prepare_goal_bootstrap_input(self.runtime, acquired.bootstrap_id)

        crashed = read_goal_bootstrap_receipt(self.runtime, acquired.bootstrap_id)
        self.assertEqual(crashed.stage, GoalBootstrapStage.CLAIMED)
        self.assertEqual(crashed.revision, 0)
        orphan_catalogs = {
            path.stem
            for path in self.runtime.state_dir.joinpath(
                "production-capabilities", "catalogs"
            ).glob("CAPCAT-*.json")
        }
        self.assertTrue(orphan_catalogs)

        recovered, planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            acquired.bootstrap_id,
        )
        self.assertEqual(recovered.stage, GoalBootstrapStage.PLANNING_INPUT_PUBLISHED)
        self.assertNotIn(recovered.capability_catalog_id, orphan_catalogs)
        self.assertEqual(planning_input.planning_input_id, recovered.planning_input_id)
        self.assertEqual(self._counts()["runs"], 0)

    def test_crash_after_planning_input_publish_before_checkpoint_leaves_orphan_input(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        with patch(
            "origin_forge.production_goal_bootstrap_authority."
            "checkpoint_goal_bootstrap_planning_input_published",
            side_effect=SimulatedCrash("after planning input publish"),
        ):
            with self.assertRaises(SimulatedCrash):
                prepare_goal_bootstrap_input(self.runtime, acquired.bootstrap_id)

        crashed = read_goal_bootstrap_receipt(self.runtime, acquired.bootstrap_id)
        self.assertEqual(crashed.stage, GoalBootstrapStage.AUTHORITY_PUBLISHED)
        self.assertEqual(crashed.revision, 1)
        with self.runtime.store.session() as conn:
            orphan_ids = {
                str(row["planning_input_id"])
                for row in conn.execute(
                    "SELECT planning_input_id FROM planning_inputs"
                ).fetchall()
            }
        self.assertEqual(len(orphan_ids), 1)

        recovered, planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            acquired.bootstrap_id,
        )
        self.assertEqual(recovered.stage, GoalBootstrapStage.PLANNING_INPUT_PUBLISHED)
        self.assertNotIn(recovered.planning_input_id, orphan_ids)
        with self.runtime.store.session() as conn:
            ids = {
                str(row["planning_input_id"])
                for row in conn.execute(
                    "SELECT planning_input_id FROM planning_inputs"
                ).fetchall()
            }
        self.assertEqual(len(ids), 2)
        self.assertEqual(planning_input.planning_input_id, recovered.planning_input_id)
        self.assertEqual(self._counts()["runs"], 0)

    def test_disabled_model_configuration_fails_closed_before_planner(self) -> None:
        self.runtime.state_dir.joinpath("config.toml").write_text(
            _DISABLED_CONFIG,
            encoding="utf-8",
        )
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        with self.assertRaisesRegex(
            GoalBootstrapAuthorityError,
            "freezing governed PlanningInput",
        ):
            prepare_goal_bootstrap_input(self.runtime, acquired.bootstrap_id)

        durable = read_goal_bootstrap_receipt(self.runtime, acquired.bootstrap_id)
        self.assertEqual(durable.stage, GoalBootstrapStage.AUTHORITY_PUBLISHED)
        self.assertEqual(durable.status, GoalBootstrapStatus.FAILED_PRE_PLANNER)
        self.assertIsNone(durable.planning_input_id)
        self.assertEqual(self._counts()["runs"], 0)
        self.assertEqual(self._counts()["planning_inputs"], 0)

    def test_projection_and_policy_hashes_are_stable_without_state_change(self) -> None:
        self.assertEqual(
            project_intelligence_projection_hash(self.runtime),
            project_intelligence_projection_hash(self.runtime),
        )
        self.assertEqual(
            goal_planner_policy_hashes(self.runtime),
            goal_planner_policy_hashes(self.runtime),
        )

    def test_receipt_planning_input_reload_is_exact(self) -> None:
        acquired = acquire_current_goal_bootstrap(self.runtime, self.goal_id)
        durable, planning_input = prepare_goal_bootstrap_input(
            self.runtime,
            acquired.bootstrap_id,
        )
        loaded = ProductionPlanningEvidenceStore(self.runtime).load_input(
            durable.planning_input_id
        )
        self.assertEqual(loaded, planning_input)
        self.assertEqual(loaded.content_hash, durable.planning_input_hash)


if __name__ == "__main__":
    unittest.main()
