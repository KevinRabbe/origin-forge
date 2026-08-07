from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from origin_forge.adapters.llamacpp import LlamaCppAdapter
from origin_forge.model import ModelRequest


class _Handler(BaseHTTPRequestHandler):
    request_json = None

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).request_json = json.loads(self.rfile.read(length))
        body = json.dumps(
            {
                "model": "test-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"summary":"ok","changes":[],"notes":[]}',
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LlamaCppAdapterTests(unittest.TestCase):
    def test_remote_endpoint_requires_explicit_opt_in(self) -> None:
        with self.assertRaises(ValueError):
            LlamaCppAdapter(base_url="https://example.com")

    def test_chat_completion_uses_json_schema_and_parses_usage(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = LlamaCppAdapter(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="test-model",
                timeout_seconds=2,
            )
            request = ModelRequest(
                run_id="RUN-test",
                task_id="TASK-test",
                instructions="bounded",
                context={"task": {"objective": "test"}, "files": []},
                response_schema={"type": "object"},
            )
            response = adapter.generate(request)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(response.model_id, "test-model")
        self.assertEqual(response.input_tokens, 12)
        self.assertEqual(response.output_tokens, 7)
        payload = _Handler.request_json
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["response_format"]["schema"], {"type": "object"})
        self.assertFalse(payload["stream"])


class WorkerCliTests(unittest.TestCase):
    def test_worker_propose_cli_does_not_apply_patch(self) -> None:
        import tempfile
        from contextlib import redirect_stdout
        from io import StringIO
        from pathlib import Path

        from origin_forge.cli import main
        from origin_forge.runtime import OriginForgeRuntime
        from origin_forge.state import TaskStatus

        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime = OriginForgeRuntime(root)
            runtime.initialize("cli-worker")
            source = root / "hello.py"
            source.write_text("print('old')\n", encoding="utf-8")
            goal = runtime.create_goal("test")
            flow = runtime.create_flow(goal)
            task = runtime.create_task(flow, "propose only")
            revision = runtime.transition_task(task, TaskStatus.READY, expected_revision=0)
            runtime.transition_task(task, TaskStatus.RUNNING, expected_revision=revision)

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--project-root",
                        str(root),
                        "worker",
                        "propose",
                        task,
                        "--file",
                        "hello.py",
                        "--base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--model",
                        "test-model",
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertFalse(result["applied"])
            self.assertEqual(source.read_text(encoding="utf-8"), "print('old')\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
