from __future__ import annotations

import unittest

from origin_forge.model_runtime_config import (
    ModelRuntimeConfigError,
    ModelRuntimeProviderKind,
    parse_model_runtime_config,
)
from origin_forge.resource_model_config import parse_resource_model_config


class ModelRuntimeConfigTests(unittest.TestCase):
    def _resource_models(self, *, gpu: bool = False, include_unbound: bool = False):
        profile = {
            "profile_id": "coder-strong",
            "role": "coder_strong",
            "model_id": "qwen-strong",
            "runtime_id": "llamacpp-cpu",
            "model_hash": "a" * 64,
            "resources": {"cpu_slots": 4, "ram_mib": 8192},
        }
        if gpu:
            profile["resources"]["gpu"] = {
                "vram_mib": 4096,
                "compute_slots": 1,
            }
        profiles = [profile]
        if include_unbound:
            profiles.append(
                {
                    "profile_id": "coder-fast-unbound",
                    "role": "coder_fast",
                    "model_id": "qwen-fast",
                    "runtime_id": "other-runtime",
                    "model_hash": "b" * 64,
                    "resources": {"cpu_slots": 2, "ram_mib": 4096},
                }
            )
        resources = {
            "enabled": True,
            "cpu_slots": 16,
            "ram_mib": 32768,
            "max_active_leases": 16,
            "gpus": (
                [{"device_id": "gpu0", "vram_mib": 16384}]
                if gpu
                else []
            ),
        }
        models = {
            "profiles": profiles,
            "policies": [
                {
                    "role": "coder_strong",
                    "primary_profile_id": "coder-strong",
                    "fallback_profile_ids": [],
                }
            ],
        }
        return parse_resource_model_config(resources, models)

    def _raw(self):
        return {
            "providers": [
                {
                    "runtime_id": "llamacpp-cpu",
                    "provider_kind": "originforge.llamacpp-managed-cpu@1",
                    "provider_contract_version": "1",
                    "executable_path": "/opt/origin-forge/llama-server",
                    "executable_sha256": "c" * 64,
                    "port": 18080,
                    "startup_timeout_seconds": 30,
                    "request_timeout_seconds": 300,
                    "shutdown_timeout_seconds": 10,
                    "profile_bindings": [
                        {
                            "profile_id": "coder-strong",
                            "model_path": "/models/qwen.gguf",
                            "model_sha256": "a" * 64,
                        }
                    ],
                }
            ]
        }

    def test_missing_or_empty_section_is_safe_disabled(self) -> None:
        resource_models = parse_resource_model_config(None, None)
        for raw in (None, {}, {"providers": []}):
            config = parse_model_runtime_config(raw, resource_models)
            self.assertEqual(config.providers, ())
            self.assertRegex(config.fingerprint, r"^[0-9a-f]{64}$")

    def test_valid_cpu_provider_binds_exact_existing_profile(self) -> None:
        resource_models = self._resource_models(include_unbound=True)
        config = parse_model_runtime_config(self._raw(), resource_models)
        self.assertEqual(len(config.providers), 1)
        provider = config.provider("llamacpp-cpu")
        self.assertEqual(
            provider.provider_kind,
            ModelRuntimeProviderKind.LLAMACPP_MANAGED_CPU_V1,
        )
        self.assertEqual(provider.provider_contract_version, "1")
        self.assertEqual(provider.port, 18080)
        self.assertEqual(provider.to_dict()["loopback_host"], "127.0.0.1")
        self.assertEqual(provider.binding("coder-strong").model_sha256, "a" * 64)
        self.assertEqual(
            config.provider_for_profile("coder-strong").runtime_id,
            "llamacpp-cpu",
        )
        with self.assertRaises(KeyError):
            config.provider_for_profile("coder-fast-unbound")
        self.assertRegex(provider.fingerprint, r"^[0-9a-f]{64}$")
        self.assertRegex(config.fingerprint, r"^[0-9a-f]{64}$")

    def test_fingerprints_are_deterministic_and_order_canonical(self) -> None:
        resources = self._resource_models()
        first = parse_model_runtime_config(self._raw(), resources)
        second = parse_model_runtime_config(self._raw(), resources)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.providers[0].fingerprint, second.providers[0].fingerprint)

    def test_unknown_provider_or_authority_fields_fail_closed(self) -> None:
        resources = self._resource_models()
        unknown_kind = self._raw()
        unknown_kind["providers"][0]["provider_kind"] = "external.runtime@1"
        with self.assertRaisesRegex(ModelRuntimeConfigError, "unsupported"):
            parse_model_runtime_config(unknown_kind, resources)

        for field, value in (
            ("endpoint", "http://127.0.0.1:8080"),
            ("argv", ["--danger"]),
            ("environment", {"TOKEN": "secret"}),
            ("api_key", "secret"),
            ("import_path", "some.module:loader"),
        ):
            raw = self._raw()
            raw["providers"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ModelRuntimeConfigError, "unknown fields"):
                    parse_model_runtime_config(raw, resources)

    def test_binding_requires_existing_profile_runtime_and_exact_model_hash(self) -> None:
        resources = self._resource_models()
        cases = (
            ("profile_id", "missing", "unknown model profile"),
            ("model_sha256", "b" * 64, "does not match model profile model_hash"),
        )
        for field, value, message in cases:
            raw = self._raw()
            raw["providers"][0]["profile_bindings"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ModelRuntimeConfigError, message):
                    parse_model_runtime_config(raw, resources)

        raw = self._raw()
        raw["providers"][0]["runtime_id"] = "wrong-runtime"
        with self.assertRaisesRegex(ModelRuntimeConfigError, "runtime_id does not match"):
            parse_model_runtime_config(raw, resources)

    def test_cpu_provider_rejects_gpu_model_profile(self) -> None:
        resources = self._resource_models(gpu=True)
        with self.assertRaisesRegex(ModelRuntimeConfigError, "CPU provider cannot bind"):
            parse_model_runtime_config(self._raw(), resources)

    def test_profile_can_be_bound_by_only_one_provider_and_runtime_ids_are_unique(self) -> None:
        resources = self._resource_models()
        raw = self._raw()
        duplicate_runtime = dict(raw["providers"][0])
        duplicate_runtime["executable_path"] = "/opt/other/llama-server"
        raw["providers"].append(duplicate_runtime)
        with self.assertRaisesRegex(ModelRuntimeConfigError, "duplicate model runtime provider"):
            parse_model_runtime_config(raw, resources)

        resources = self._resource_models(include_unbound=True)
        raw = self._raw()
        other = dict(raw["providers"][0])
        other["runtime_id"] = "other-runtime"
        other["profile_bindings"] = [dict(raw["providers"][0]["profile_bindings"][0])]
        raw["providers"].append(other)
        with self.assertRaisesRegex(ModelRuntimeConfigError, "runtime_id does not match"):
            parse_model_runtime_config(raw, resources)

    def test_paths_hashes_ports_timeouts_and_contract_version_are_bounded(self) -> None:
        resources = self._resource_models()
        cases = (
            ("executable_path", "https://example.com/llama-server", "local path"),
            ("executable_sha256", "C" * 64, "SHA-256"),
            ("port", 0, "integer from"),
            ("startup_timeout_seconds", 0, "must be > 0"),
            ("request_timeout_seconds", 3601, "must be > 0"),
            ("shutdown_timeout_seconds", True, "positive number"),
            ("provider_contract_version", "2", "exactly '1'"),
        )
        for field, value, message in cases:
            raw = self._raw()
            raw["providers"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ModelRuntimeConfigError, message):
                    parse_model_runtime_config(raw, resources)

        raw = self._raw()
        raw["providers"][0]["profile_bindings"][0]["model_path"] = "https://example.com/model"
        with self.assertRaisesRegex(ModelRuntimeConfigError, "local path"):
            parse_model_runtime_config(raw, resources)

    def test_persistable_runtime_config_exposes_no_remote_or_dynamic_authority(self) -> None:
        config = parse_model_runtime_config(self._raw(), self._resource_models())
        payload = config.to_dict()
        provider = payload["providers"][0]
        self.assertEqual(provider["loopback_host"], "127.0.0.1")
        self.assertEqual(
            set(provider),
            {
                "runtime_id",
                "provider_kind",
                "provider_contract_version",
                "executable_path",
                "executable_sha256",
                "loopback_host",
                "port",
                "startup_timeout_seconds",
                "request_timeout_seconds",
                "shutdown_timeout_seconds",
                "profile_bindings",
            },
        )
        for forbidden in (
            "endpoint",
            "argv",
            "environment",
            "api_key",
            "credentials",
            "import_path",
            "callable",
            "shell",
            "host",
        ):
            if forbidden == "host":
                self.assertEqual(provider["loopback_host"], "127.0.0.1")
                continue
            self.assertNotIn(forbidden, provider)


if __name__ == "__main__":
    unittest.main()
