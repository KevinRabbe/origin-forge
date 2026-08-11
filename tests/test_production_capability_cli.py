from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from origin_forge.production_capability_cli import build_parser, main
from origin_forge.production_capability_models import (
    AdapterExecutionEffect,
    AdapterReplayClass,
    CapabilityCatalog,
    CapabilityDomain,
    CapabilityRoutingPolicy,
    ProductionCapability,
    TrustedProductionAdapter,
)
from origin_forge.production_capability_store import ProductionCapabilityStore
from origin_forge.runtime import OriginForgeRuntime


class ProductionCapabilityCliTests(unittest.TestCase):
    def test_help_and_uninitialized_status_create_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            with self.assertRaises(SystemExit) as help_exit:
                with redirect_stdout(StringIO()):
                    build_parser().parse_args(["--help"])
            self.assertEqual(help_exit.exception.code, 0)
            self.assertFalse(state.exists())

            output = StringIO()
            with redirect_stdout(output):
                code = main(["--project-root", str(root), "status"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["initialized"])
            self.assertFalse(state.exists())

    def test_cli_surface_is_strictly_inspection_only(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for forbidden in (
            "publish",
            "register",
            "install",
            "execute",
            "dispatch",
            "transition",
            "adopt",
            "sign",
            "merge",
            "release",
        ):
            self.assertNotIn(forbidden, help_text.lower())
        self.assertIn("status", help_text)

    def test_cli_can_show_persisted_authority_and_static_task_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = OriginForgeRuntime(temp)
            runtime.initialize("capability-cli")
            goal = runtime.create_goal("route work")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(
                flow,
                "change code",
                required_capabilities=("code.change",),
            )
            capability = ProductionCapability(
                "code.change",
                "Code change",
                "bounded coding",
                CapabilityDomain.CODE,
                "1",
            )
            adapter = TrustedProductionAdapter(
                "code.bounded",
                "code",
                "1",
                "a" * 64,
                ("code.change",),
                AdapterExecutionEffect.WORKSPACE_MUTATION,
                AdapterReplayClass.REVISION_BOUND,
            )
            catalog = CapabilityCatalog.create((capability,), (adapter,))
            policy = CapabilityRoutingPolicy.create(
                catalog,
                ordered_adapter_ids=("code.bounded",),
                allowed_capability_ids=("code.change",),
            )
            store = ProductionCapabilityStore(runtime)
            store.publish_catalog(catalog)
            store.publish_policy(policy, catalog)
            decision = store.resolve_and_publish(
                task,
                catalog.catalog_id,
                policy.routing_policy_id,
            )

            commands = (
                ("catalog-show", catalog.catalog_id),
                ("policy-show", policy.routing_policy_id),
                ("route-show", decision.route_decision_id),
            )
            for command in commands:
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["--project-root", temp, *command])
                self.assertEqual(code, 0)
                self.assertIn("content_hash", json.loads(output.getvalue()))

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--project-root",
                        temp,
                        "task-route",
                        task,
                        catalog.catalog_id,
                        policy.routing_policy_id,
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["outcome"], "ROUTABLE")
            self.assertEqual(payload["selected_adapter_id"], "code.bounded")
            self.assertEqual(runtime.list_runs(task), [])


if __name__ == "__main__":
    unittest.main()
