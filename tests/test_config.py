from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.config import load_config


class ConfigV2Tests(unittest.TestCase):
    def test_default_config_is_v2_and_network_off(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = load_config(Path(temp))
            self.assertEqual(config.version, 2)
            self.assertFalse(config.sandbox_network)
            self.assertEqual(config.approved_build_commands, ())
            self.assertEqual(config.approved_test_commands, ())

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


if __name__ == "__main__":
    unittest.main()
