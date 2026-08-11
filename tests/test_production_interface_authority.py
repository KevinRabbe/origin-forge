from __future__ import annotations

import inspect
import unittest

import origin_forge.production_interface_cli as cli_module
import origin_forge.production_interface_html as html_module
import origin_forge.production_interface_server as server_module
import origin_forge.production_interface_snapshot as snapshot_module


class ProductionInterfaceAuthorityTests(unittest.TestCase):
    def test_cockpit_modules_expose_no_generic_execution_or_production_mutation_hooks(self) -> None:
        source = "\n".join(
            inspect.getsource(module)
            for module in (
                snapshot_module,
                html_module,
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
            "adopt",
            "sign_manifest",
            "merge_pull_request",
            "release",
        ):
            self.assertNotIn(forbidden, source)

    def test_http_surface_has_no_successful_non_get_dispatch(self) -> None:
        source = inspect.getsource(server_module.ProductionInterfaceRouter.route)
        self.assertIn('if method != "GET"', source)
        self.assertNotIn('method == "POST"', source)
        self.assertNotIn('method == "PUT"', source)
        self.assertNotIn('method == "PATCH"', source)
        self.assertNotIn('method == "DELETE"', source)


if __name__ == "__main__":
    unittest.main()
