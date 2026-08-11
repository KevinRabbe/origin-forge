from __future__ import annotations

import http.client
import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import origin_forge.production_interface_server as server_module
from origin_forge.production_interface_html import ProductionInterfaceRenderError
from origin_forge.production_interface_server import (
    ProductionInterfaceRouter,
    create_production_interface_server,
)
from origin_forge.runtime import OriginForgeRuntime


class ProductionInterfaceServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = OriginForgeRuntime(self.root)
        self.runtime.initialize("production-interface-server-test")
        self.goal = self.runtime.create_goal('<script>alert("x")</script>')
        self.flow = self.runtime.create_flow(self.goal)
        self.task = self.runtime.create_task(self.flow, "task")
        self.router = ProductionInterfaceRouter(self.runtime)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_fixed_routes_and_typed_detail_ids(self) -> None:
        self.assertEqual(self.router.route("GET", "/").status, 200)
        health = self.router.route("GET", "/healthz")
        self.assertEqual(health.status, 200)
        snapshot_response = self.router.route("GET", "/api/snapshot")
        self.assertEqual(snapshot_response.status, 200)
        payload = json.loads(snapshot_response.body)
        self.assertEqual(payload["project_id"], self.runtime.project_id())
        self.assertIn("content_hash", payload)
        self.assertEqual(self.router.route("GET", f"/goal/{self.goal}").status, 200)
        self.assertEqual(self.router.route("GET", "/goal/GOAL-not-real").status, 404)
        self.assertEqual(self.router.route("GET", "/unknown/value").status, 404)

    def test_non_get_and_path_abuse_fail_closed(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.router.route(method, "/").status, 405)
        for target in (
            "/?x=1",
            "/#fragment",
            "http://example.com/",
            "/../../etc/passwd",
            "/goal/",
            "goal/x",
        ):
            self.assertNotEqual(self.router.route("GET", target).status, 200)

    def test_security_headers_and_escaped_html(self) -> None:
        response = self.router.route("GET", "/")
        headers = dict(response.headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")
        text = response.body.decode("utf-8")
        self.assertNotIn('<script>alert("x")</script>', text)
        self.assertIn("&lt;script&gt;", text)

    def test_server_snapshot_defaults_are_conservatively_truncated(self) -> None:
        for index in range(16):
            self.runtime.create_goal(f"extra goal {index}")
        response = self.router.route("GET", "/api/snapshot")
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload["total_counts"]["goals"], 17)
        self.assertEqual(len(payload["goals"]), 16)
        self.assertTrue(payload["truncated"]["goals"])

    def test_render_overflow_is_controlled_server_error(self) -> None:
        with patch(
            "origin_forge.production_interface_server.render_overview",
            side_effect=ProductionInterfaceRenderError("too large"),
        ):
            response = self.router.route("GET", "/")
        self.assertEqual(response.status, 500)
        self.assertEqual(
            response.body, b"rendered page exceeds interface byte limit\n"
        )

    def test_real_server_binds_loopback_and_serves_snapshot(self) -> None:
        server = create_production_interface_server(self.runtime, port=0)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            connection.request("GET", "/api/snapshot")
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
            payload = json.loads(body)
            self.assertEqual(payload["project_id"], self.runtime.project_id())
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            connection.request("POST", "/", body=b"ignored")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 405)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_server_source_has_no_generic_execution_or_file_serving_surface(self) -> None:
        source = inspect.getsource(server_module)
        for forbidden in (
            "subprocess",
            "os.system",
            "SimpleHTTPRequestHandler",
            "sendfile",
            "sqlite3",
            ".store",
            "ModelAdapter",
            "private_key",
            "merge_pull_request",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
