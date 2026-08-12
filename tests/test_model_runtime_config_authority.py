from __future__ import annotations

import ast
import inspect
import unittest

import origin_forge.model_runtime_config as runtime_config_module
from origin_forge.model_runtime_config import (
    ModelRuntimeConfigError,
    parse_model_runtime_config,
)
from origin_forge.resource_model_config import parse_resource_model_config


class ModelRuntimeConfigAuthorityTests(unittest.TestCase):
    def _resource_models(self):
        return parse_resource_model_config(
            {
                "enabled": True,
                "cpu_slots": 8,
                "ram_mib": 16384,
                "gpus": [],
            },
            {
                "profiles": [
                    {
                        "profile_id": "strong",
                        "role": "coder_strong",
                        "model_id": "model",
                        "model_hash": "a" * 64,
                        "runtime_id": "runtime",
                        "resources": {"cpu_slots": 2, "ram_mib": 4096},
                    }
                ],
                "policies": [
                    {
                        "role": "coder_strong",
                        "primary_profile_id": "strong",
                        "fallback_profile_ids": [],
                    }
                ],
            },
        )

    def _raw(self):
        return {
            "providers": [
                {
                    "runtime_id": "runtime",
                    "provider_kind": "originforge.llamacpp-managed-cpu@1",
                    "provider_contract_version": "1",
                    "executable_path": "/opt/llama-server",
                    "executable_sha256": "b" * 64,
                    "port": 18080,
                    "startup_timeout_seconds": 10,
                    "request_timeout_seconds": 20,
                    "shutdown_timeout_seconds": 5,
                    "profile_bindings": [
                        {
                            "profile_id": "strong",
                            "model_path": "/models/model.gguf",
                            "model_sha256": "a" * 64,
                        }
                    ],
                }
            ]
        }

    def test_nonfinite_timeouts_fail_closed(self) -> None:
        resources = self._resource_models()
        for field, value in (
            ("startup_timeout_seconds", float("nan")),
            ("request_timeout_seconds", float("inf")),
            ("shutdown_timeout_seconds", float("-inf")),
        ):
            raw = self._raw()
            raw["providers"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ModelRuntimeConfigError, "must be > 0"):
                    parse_model_runtime_config(raw, resources)

    def test_config_parser_has_no_filesystem_process_network_or_loader_authority(self) -> None:
        source = inspect.getsource(runtime_config_module)
        for forbidden in (
            "subprocess",
            "socket",
            "urllib",
            "http.client",
            "importlib",
            "pathlib",
            "open(",
            "os.environ",
            "LlamaCppAdapter",
            "ScheduledModelAdapter",
            "ManagedModelLoader",
            "ModelScheduler",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        forbidden_calls = {
            "load",
            "unload",
            "generate",
            "drive",
            "Popen",
            "run",
            "start_run",
            "create_run",
            "transition_task",
            "lease",
            "use",
        }
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))


if __name__ == "__main__":
    unittest.main()
