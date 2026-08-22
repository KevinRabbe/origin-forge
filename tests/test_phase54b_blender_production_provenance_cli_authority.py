from __future__ import annotations

import argparse
import inspect
import tomllib
import unittest
from pathlib import Path

import origin_forge.production_blender_provenance_signer as signer_module
from origin_forge import blender_admin_cli


class Phase54BBlenderProductionProvenanceCliAuthorityTests(unittest.TestCase):
    @staticmethod
    def _signing_parser() -> argparse.ArgumentParser:
        parser = blender_admin_cli.build_parser()
        subparsers = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        if len(subparsers) != 1:
            raise AssertionError("Blender admin CLI must have one subcommand registry")
        signing = subparsers[0].choices.get("sign-production-provenance")
        if signing is None:
            raise AssertionError("sign-production-provenance command is missing")
        return signing

    def test_signing_parser_accepts_only_execution_certificate_and_external_key(self) -> None:
        signing = self._signing_parser()
        option_strings = {
            option
            for action in signing._actions
            for option in action.option_strings
        }
        self.assertEqual(
            option_strings,
            {
                "-h",
                "--help",
                "--execution-id",
                "--certificate-id",
                "--operational-private-key",
            },
        )
        required = {
            action.dest
            for action in signing._actions
            if getattr(action, "required", False)
        }
        self.assertEqual(
            required,
            {"execution_id", "certificate_id", "operational_private_key"},
        )
        forbidden = {
            "artifact_id",
            "task_id",
            "verification_id",
            "destination",
            "expected_hash",
            "expected_byte_count",
            "accept",
            "force",
            "bypass",
            "parent_manifest_id",
            "root_private_key",
            "release",
            "publish",
            "merge",
        }
        self.assertTrue(forbidden.isdisjoint({action.dest for action in signing._actions}))

    def test_forbidden_signing_authority_flags_are_rejected_by_parser(self) -> None:
        parser = blender_admin_cli.build_parser()
        prefix = [
            "sign-production-provenance",
            "--execution-id",
            "DISPEXEC-00000000000000000000000000",
            "--certificate-id",
            "KEYCERT-00000000000000000000000000",
            "--operational-private-key",
            "/external/key.pem",
        ]
        for flag, value in (
            ("--artifact-id", "ARTF-00000000000000000000000000"),
            ("--task-id", "TASK-00000000000000000000000000"),
            ("--verification-id", "VERIF-00000000000000000000000000"),
            ("--destination", "assets/alternate.glb"),
            ("--expected-hash", "sha256:" + "0" * 64),
            ("--expected-byte-count", "1"),
            ("--parent-manifest-id", "PROVMAN-00000000000000000000000000"),
            ("--root-private-key", "/external/root.pem"),
        ):
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                parser.parse_args(prefix + [flag, value])
        for flag in ("--accept", "--force", "--bypass", "--release", "--publish", "--merge"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                parser.parse_args(prefix + [flag])

    def test_package_surface_remains_exact_three_installed_scripts(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data["project"]["scripts"]
        self.assertEqual(
            scripts,
            {
                "origin-forge": "origin_forge.cli:main",
                "origin-forge-attempt": "origin_forge.orchestration_cli:main",
                "origin-forge-cockpit": "origin_forge.production_interface_cli:main",
            },
        )
        self.assertNotIn("origin_forge.blender_admin_cli:main", scripts.values())

    def test_governed_signer_has_no_acceptance_execution_or_lifecycle_mutation_calls(self) -> None:
        source = inspect.getsource(signer_module)
        for forbidden in (
            "accept_artifact(",
            "GovernedBlenderProductionTaskAcceptor",
            "BlenderExportService",
            "PixeloramaCliExportService",
            "dispatch_claim_once(",
            "transition_task(",
            "transition_flow(",
            "transition_goal(",
            "create_run(",
            "start_run(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("parent_manifest_ids=()", source)
        self.assertIn("ProvenanceService", source)

    def test_module_command_is_explicit_and_not_background_reachable(self) -> None:
        cli_source = inspect.getsource(blender_admin_cli)
        self.assertIn('elif args.command == "sign-production-provenance":', cli_source)
        self.assertIn("GovernedBlenderProductionProvenanceSigner(runtime).sign(", cli_source)
        for forbidden in (
            "threading",
            "asyncio",
            "schedule",
            "Manager",
            "conversation",
            "browser",
            "startup",
            "retry_sign",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, cli_source)


if __name__ == "__main__":
    unittest.main()
