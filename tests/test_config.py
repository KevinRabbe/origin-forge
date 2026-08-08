from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.config import load_config


class ConfigTests(unittest.TestCase):
    def test_default_config_is_v5_network_off_and_resource_scheduling_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = load_config(Path(temp))
            self.assertEqual(config.version, 5)
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


if __name__ == "__main__":
    unittest.main()
