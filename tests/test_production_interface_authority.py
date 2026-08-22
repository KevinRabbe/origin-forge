from __future__ import annotations

import inspect
import unittest

import origin_forge.conversation_blender_task_acceptance_actions as blender_action_projection_module
import origin_forge.conversation_blender_task_acceptance_service as blender_action_service_module
import origin_forge.production_blender_dispatch_output_discovery as blender_discovery_module
import origin_forge.production_interface_accessibility as accessibility_module
import origin_forge.production_interface_blender_acceptance as blender_acceptance_module
import origin_forge.production_interface_classic as classic_module
import origin_forge.production_interface_cli as cli_module
import origin_forge.production_interface_conversation as conversation_module
import origin_forge.production_interface_detail_context as detail_context_module
import origin_forge.production_interface_html as html_module
import origin_forge.production_interface_lifecycle as lifecycle_module
import origin_forge.production_interface_lineage as lineage_module
import origin_forge.production_interface_live as live_module
import origin_forge.production_interface_live_decorator as live_decorator_module
import origin_forge.production_interface_project_tokens as project_tokens_module
import origin_forge.production_interface_run_timing as run_timing_module
import origin_forge.production_interface_server as server_module
import origin_forge.production_interface_snapshot as snapshot_module
import origin_forge.production_interface_task_switcher as task_switcher_module
import origin_forge.production_interface_task_workspace as task_workspace_module
import origin_forge.production_interface_theme as theme_module
import origin_forge.production_interface_workspace as workspace_module


class ProductionInterfaceAuthorityTests(unittest.TestCase):
    def test_cockpit_modules_expose_no_generic_execution_or_production_mutation_hooks(self) -> None:
        source = "\n".join(
            inspect.getsource(module)
            for module in (
                snapshot_module,
                classic_module,
                html_module,
                theme_module,
                accessibility_module,
                lifecycle_module,
                detail_context_module,
                lineage_module,
                workspace_module,
                conversation_module,
                live_module,
                live_decorator_module,
                blender_acceptance_module,
                task_workspace_module,
                task_switcher_module,
                project_tokens_module,
                run_timing_module,
                server_module,
                cli_module,
            )
        )
        for forbidden in (
            "subprocess",
            "os.system",
            "SimpleHTTPRequestHandler",
            "sendfile",
            "webbrowser",
            "sqlite3",
            ".store",
            "ModelAdapter",
            "private_key",
            "create_goal(",
            "create_flow(",
            "create_task(",
            "transition_goal(",
            "transition_flow(",
            "transition_task(",
            "start_run(",
            "record_verification(",
            ".adopt(",
            "adopt_new(",
            "sign_manifest(",
            "merge_pull_request(",
            "release_candidate(",
            "GovernedBlenderProductionTaskAcceptor",
        ):
            self.assertNotIn(forbidden, source)

    def test_http_surface_allows_only_exact_conversation_post_routes(self) -> None:
        route_source = inspect.getsource(server_module.ProductionInterfaceRouter.route)
        live_get_source = inspect.getsource(
            server_module.ProductionInterfaceRouter._route_live_get
        )
        post_source = inspect.getsource(server_module.ProductionInterfaceRouter._route_post)
        server_source = inspect.getsource(server_module)

        self.assertIn('if method == "POST"', route_source)
        self.assertIn('path != "/conversation/session"', post_source)
        self.assertIn("_conversation_turn_session_id(path)", post_source)
        self.assertIn("create_conversation_session(", post_source)
        self.assertIn("submit_human_turn(", post_source)
        self.assertIn('path == "/assets/conversation-live.js"', route_source)
        self.assertIn('path.startswith("/api/conversation/live/")', route_source)
        self.assertIn("_route_live_get(", route_source)
        self.assertIn("read_conversation_live_state(", live_get_source)
        self.assertNotIn("blender", post_source.lower())
        self.assertNotIn("accept", post_source.lower())
        for forbidden_method in (
            'method == "PUT"',
            'method == "PATCH"',
            'method == "DELETE"',
        ):
            self.assertNotIn(forbidden_method, route_source)

        for forbidden_boundary in (
            "conversation_production_processing",
            "process_production_conversation_submission",
            "production_manager_advance",
            "production_goal_bootstrap",
            "production_dispatch_execution",
            "production_dispatch_invocation",
            "production_blender_adoption",
            "production_pixelorama_adoption",
            "GovernedBlenderProductionTaskAcceptor",
            "conversation_blender_task_acceptance_service",
            "accept_conversation_blender_task",
        ):
            self.assertNotIn(forbidden_boundary, server_source)

    def test_live_browser_transport_is_read_only_same_origin_polling(self) -> None:
        script = live_module.CONVERSATION_LIVE_SCRIPT
        self.assertIn('method: "GET"', script)
        self.assertIn('credentials: "same-origin"', script)
        self.assertIn("fetch(url", script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn("WebSocket", script)
        self.assertNotIn("EventSource", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("outerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)
        self.assertNotIn("eval(", script)
        self.assertNotIn("accept-production-task", script)
        self.assertNotIn("blender", script.lower())

        server_source = inspect.getsource(server_module)
        self.assertNotIn("conversation_production", server_source)
        self.assertNotIn("conversation_processing", server_source)
        self.assertNotIn("production_manager", server_source)
        self.assertNotIn(".store", server_source)

    def test_blender_acceptance_action_gate_a_is_read_only_and_non_actionable(self) -> None:
        projection_source = inspect.getsource(blender_action_projection_module)
        discovery_source = inspect.getsource(blender_discovery_module)
        renderer_source = inspect.getsource(blender_acceptance_module)
        post_source = inspect.getsource(server_module.ProductionInterfaceRouter._route_post)

        self.assertIn(
            "discover_blender_dispatch_output_executions_for_task_readonly(",
            projection_source,
        )
        self.assertIn(
            "inspect_blender_production_task_acceptance_currentness_readonly(",
            projection_source,
        )
        self.assertIn("LIMIT ?", discovery_source)
        self.assertIn("_MAX_DISCOVERED_BINDINGS_PER_TASK = 2", discovery_source)
        self.assertIn("data-blender-acceptance-actions", renderer_source)
        self.assertIn("Confirmation controls are intentionally unavailable", renderer_source)

        combined = "\n".join((projection_source, discovery_source, renderer_source))
        for forbidden in (
            "GovernedBlenderProductionTaskAcceptor",
            "accept_production_task",
            "publish_blender_production_task_acceptance",
            "transition_task(",
            "record_verification(",
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "subprocess",
            "ModelAdapter",
            "private_key",
            "sign_manifest(",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertNotIn("<form", renderer_source)
        self.assertNotIn("<button", renderer_source)
        self.assertNotIn("blender", post_source.lower())
        self.assertNotIn("accept", post_source.lower())

    def test_blender_acceptance_action_gate_b_has_one_typed_phase53_delegation_site(self) -> None:
        service_source = inspect.getsource(blender_action_service_module)
        server_source = inspect.getsource(server_module)
        renderer_source = inspect.getsource(blender_acceptance_module)

        self.assertIn("read_conversation_live_state(", service_source)
        self.assertIn(
            "project_conversation_blender_task_acceptance_actions_readonly(",
            service_source,
        )
        self.assertEqual(
            service_source.count("GovernedBlenderProductionTaskAcceptor(runtime).accept("),
            1,
        )
        self.assertIn("LOCAL_GUI_BLENDER_ACCEPTANCE_ACTOR_ID", service_source)
        for forbidden in (
            ".store",
            "transition_task(",
            "publish_blender_production_task_acceptance",
            "record_verification(",
            "write_bytes(",
            "unlink(",
            "subprocess",
            "ModelAdapter",
            "Manager",
            "sign_manifest(",
            "merge_pull_request(",
            "release_candidate(",
        ):
            self.assertNotIn(forbidden, service_source)

        self.assertNotIn("conversation_blender_task_acceptance_service", server_source)
        self.assertNotIn("accept_conversation_blender_task", server_source)
        self.assertNotIn("<form", renderer_source)
        self.assertNotIn("<button", renderer_source)
        self.assertNotIn("blender", live_module.CONVERSATION_LIVE_SCRIPT.lower())


if __name__ == "__main__":
    unittest.main()
