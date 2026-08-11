from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.config import load_config
from origin_forge.model_scheduler import ModelRole


class ConfigTests(unittest.TestCase):
    def test_default_config_is_v6_network_off_and_runtime_scheduling_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = load_config(Path(temp))
            self.assertEqual(config.version, 6)
            self.assertFalse(config.sandbox_network)
            self.assertEqual(config.sandbox_backend, "unconfigured")
            self.assertIsNone(config.sandbox_image)
            self.assertEqual(config.sandbox_memory, "2g")
            self.assertEqual(config.sandbox_cpus, 2.0)
            self.assertEqual(config.sandbox_pids_limit, 256)
            self.assertEqual(config.approved_build_commands, ())
            self.assertEqual(config.approved_test_commands, ())
            self.assertEqual(config.lsp_servers, ())
            self.assertFalse(config.resource_models.enabled)
            self.assertIsNone(config.resource_models.capacity)
            self.assertEqual(config.resource_models.profiles, ())
            self.assertEqual(config.resource_models.policies, ())
            self.assertEqual(config.model_runtimes.providers, ())

    def test_v1_empty_command_config_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 1\npolicy_profile = "legacy"\n[limits]\nmax_strategy_retries = 1\nmax_verification_failures = 2\n[commands]\nbuild = []\ntest = []\n''',
                encoding="utf-8",
            )
            config = load_config(root)
            self.assertEqual(config.version, 1)
            self.assertEqual(config.policy_profile, "legacy")
            self.assertFalse(config.sandbox_network)
            self.assertEqual(config.lsp_servers, ())
            self.assertFalse(config.resource_models.enabled)
            self.assertEqual(config.model_runtimes.providers, ())

    def test_v1_shell_command_strings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 1\n[commands]\nbuild = ["python -m compileall ."]\ntest = []\n''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "shell strings"):
                load_config(root)

    def test_structured_command_specs_are_parsed_without_shell_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 2\npolicy_profile = "local-default"\n[sandbox]\nnetwork = false\n[commands]\nbuild = [{ name = "compile", argv = ["python", "-m", "compileall", "."], timeout_seconds = 30, max_output_bytes = 4096, required = true }]\ntest = [{ name = "unit", argv = ["python", "-m", "unittest", "-q"], required = true }]\n''',
                encoding="utf-8",
            )
            config = load_config(root)
            command = config.command("build", "compile")
            self.assertEqual(command.argv, ("python", "-m", "compileall", "."))
            self.assertEqual(command.timeout_seconds, 30)
            self.assertEqual(command.max_output_bytes, 4096)
            self.assertFalse(config.sandbox_network)
            self.assertEqual(config.lsp_servers, ())
            self.assertFalse(config.resource_models.enabled)
            self.assertEqual(config.model_runtimes.providers, ())

    def test_v3_config_remains_readable_without_lsp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 3\n[sandbox]\nbackend = "podman"\nimage = "sandbox:local"\nnetwork = false\nmemory = "1g"\ncpus = 1.0\npids_limit = 64\n[commands]\nbuild = []\ntest = []\n''',
                encoding="utf-8",
            )
            config = load_config(root)
            self.assertEqual(config.version, 3)
            self.assertEqual(config.sandbox_backend, "podman")
            self.assertEqual(config.lsp_servers, ())
            self.assertFalse(config.resource_models.enabled)
            self.assertEqual(config.model_runtimes.providers, ())

    def test_duplicate_command_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 2\n[commands]\nbuild = []\ntest = [{ name = "unit", argv = ["a"] }, { name = "unit", argv = ["b"] }]\n''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_config(root)

    def test_v4_parses_trusted_podman_lsp_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "pyright", backend = "podman", image = "origin-forge/pyright:local", argv = ["pyright-langserver", "--stdio"], network = false, memory = "1g", cpus = 1.5, pids_limit = 64, initialize_timeout_seconds = 20, request_timeout_seconds = 4, max_protocol_message_bytes = 65536, max_pending_notifications = 32, max_stderr_bytes = 4096 }
]
''',
                encoding="utf-8",
            )
            config = load_config(root)
            server = config.lsp_server("pyright")
            self.assertEqual(server.backend, "podman")
            self.assertEqual(server.image, "origin-forge/pyright:local")
            self.assertEqual(server.argv, ("pyright-langserver", "--stdio"))
            self.assertFalse(server.network)
            self.assertEqual(server.memory, "1g")
            self.assertEqual(server.cpus, 1.5)
            self.assertEqual(server.pids_limit, 64)
            self.assertEqual(server.initialize_timeout_seconds, 20.0)
            self.assertEqual(server.request_timeout_seconds, 4.0)
            self.assertEqual(server.max_protocol_message_bytes, 65536)
            self.assertEqual(server.max_pending_notifications, 32)
            self.assertEqual(server.max_stderr_bytes, 4096)
            self.assertFalse(config.resource_models.enabled)
            self.assertEqual(config.model_runtimes.providers, ())

    def test_lsp_server_ids_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", image = "a", argv = ["server"] },
  { server_id = "python", image = "b", argv = ["server"] }
]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate LSP server_id"):
                load_config(root)

    def test_lsp_server_backend_is_explicitly_podman_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", backend = "native", image = "a", argv = ["server"] }
]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "backend must be 'podman'"):
                load_config(root)

    def test_lsp_servers_require_v4_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 3
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", image = "a", argv = ["server"] }
]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "require config version 4"):
                load_config(root)

    def test_invalid_lsp_resource_bounds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 4
[commands]
build = []
test = []
[code_intelligence]
lsp_servers = [
  { server_id = "python", image = "a", argv = ["server"], pids_limit = 0 }
]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "pids_limit must be positive"):
                load_config(root)

    def test_v5_resource_model_config_remains_readable_without_runtime_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 5
[commands]
build = []
test = []
[resources]
enabled = false
gpus = []
[models]
profiles = []
policies = []
''',
                encoding="utf-8",
            )
            config = load_config(root)
            self.assertEqual(config.version, 5)
            self.assertFalse(config.resource_models.enabled)
            self.assertEqual(config.model_runtimes.providers, ())

    def test_managed_model_runtime_bindings_require_v6(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                '''version = 5
[commands]
build = []
test = []
[resources]
enabled = false
gpus = []
[models]
profiles = []
policies = []
[model_runtimes]
providers = [{ runtime_id = "not-allowed-yet" }]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "require config version 6"):
                load_config(root)

    def test_v6_parses_exact_cpu_runtime_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".origin-forge"
            state.mkdir()
            (state / "config.toml").write_text(
                f'''version = 6
[commands]
build = []
test = []
[resources]
enabled = true
cpu_slots = 8
ram_mib = 16384
max_active_leases = 8
gpus = []
[[models.profiles]]
profile_id = "coder-strong"
role = "coder_strong"
model_id = "qwen"
model_hash = "{'a' * 64}"
runtime_id = "llamacpp-cpu"
[models.profiles.resources]
cpu_slots = 4
ram_mib = 8192
[[models.policies]]
role = "coder_strong"
primary_profile_id = "coder-strong"
fallback_profile_ids = []
[[model_runtimes.providers]]
runtime_id = "llamacpp-cpu"
provider_kind = "originforge.llamacpp-managed-cpu@1"
provider_contract_version = "1"
executable_path = "/opt/llama-server"
executable_sha256 = "{'b' * 64}"
port = 18080
startup_timeout_seconds = 30
request_timeout_seconds = 300
shutdown_timeout_seconds = 10
[[model_runtimes.providers.profile_bindings]]
profile_id = "coder-strong"
model_path = "/models/qwen.gguf"
model_sha256 = "{'a' * 64}"
''',
                encoding="utf-8",
            )
            config = load_config(root)
            provider = config.model_runtimes.provider("llamacpp-cpu")
            self.assertEqual(config.version, 6)
            self.assertEqual(provider.to_dict()["loopback_host"], "127.0.0.1")
            self.assertEqual(provider.binding("coder-strong").model_sha256, "a" * 64)
            self.assertEqual(
                config.resource_models.policy(ModelRole.CODER_STRONG).primary_profile_id,
                "coder-strong",
            )


if __name__ == "__main__":
    unittest.main()
