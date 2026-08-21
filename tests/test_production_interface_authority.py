from __future__ import annotations

import inspect
import unittest

import origin_forge.production_interface_accessibility as accessibility_module
import origin_forge.production_interface_classic as classic_module
import origin_forge.production_interface_cli as cli_module
import origin_forge.production_interface_conversation as conversation_module
import origin_forge.production_interface_detail_context as detail_context_module
import origin_forge.production_interface_html as html_module
import origin_forge.production_interface_lifecycle as lifecycle_module
import origin_forge.production_interface_lineage as lineage_module
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
        ):
            self.assertNotIn(forbidden, source)

    def test_http_surface_allows_only_exact_conversation_post_routes(self) -> None:
        route_source = inspect.getsource(server_module.ProductionInterfaceRouter.route)
        post_source = inspect.getsource(server_module.ProductionInterfaceRouter._route_post)
        server_source = inspect.getsource(server_module)

        self.assertIn('if method == "POST"', route_source)
        self.assertIn('path != "/conversation/session"', post_source)
        self.assertIn("_conversation_turn_session_id(path)", post_source)
        self.assertIn("create_conversation_session(", post_source)
        self.assertIn("submit_human_turn(", post_source)
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
        ):
            self.assertNotIn(forbidden_boundary, server_source)


if __name__ == "__main__":
    unittest.main()
