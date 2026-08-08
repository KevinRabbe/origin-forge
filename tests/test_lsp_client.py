from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from origin_forge.lsp_client import (
    LspInitializationError,
    LspWorkspaceError,
    LspWorkspaceMapper,
    initialize_lsp_session,
    parse_server_capabilities,
)
from origin_forge.lsp_protocol import LspPositionEncoding


class FakeSession:
    def __init__(self, result: object):
        self.result = result
        self.requests: list[tuple[str, object | None, float]] = []
        self.notifications: list[tuple[str, object | None]] = []

    def request(
        self,
        method: str,
        params: object | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> object | None:
        self.requests.append((method, params, timeout_seconds))
        return self.result

    def notify(self, method: str, params: object | None = None) -> None:
        self.notifications.append((method, params))


class LspWorkspaceMapperTests(unittest.TestCase):
    def test_relative_path_round_trip_is_workspace_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src" / "hello world.py"
            source.parent.mkdir()
            source.write_text("VALUE = '🐈'\n", encoding="utf-8")
            mapper = LspWorkspaceMapper(root)

            uri = mapper.path_to_uri("src/hello world.py")
            self.assertTrue(uri.startswith("file:"))
            self.assertEqual(mapper.uri_to_path(uri), "src/hello world.py")

    def test_server_visible_root_can_differ_from_local_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src" / "hello world.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            mapper = LspWorkspaceMapper(
                root,
                server_root_uri="file:///workspace",
            )

            self.assertEqual(mapper.server_root_uri, "file:///workspace")
            self.assertEqual(
                mapper.path_to_uri("src/hello world.py"),
                "file:///workspace/src/hello%20world.py",
            )
            self.assertEqual(
                mapper.uri_to_path("file:///workspace/src/hello%20world.py"),
                "src/hello world.py",
            )
            with self.assertRaises(LspWorkspaceError):
                mapper.uri_to_path("file:///other/src/hello%20world.py")

    def test_server_visible_root_round_trips_unicode_percent_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src" / "Grüße 猫.py"
            source.parent.mkdir()
            source.write_text("VALUE = 1\n", encoding="utf-8")
            mapper = LspWorkspaceMapper(root, server_root_uri="file:///workspace")

            uri = mapper.path_to_uri("src/Grüße 猫.py")
            self.assertEqual(
                uri,
                "file:///workspace/src/Gr%C3%BC%C3%9Fe%20%E7%8C%AB.py",
            )
            self.assertEqual(mapper.uri_to_path(uri), "src/Grüße 猫.py")

    def test_non_file_and_external_file_uris_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            mapper = LspWorkspaceMapper(temp)
            with self.assertRaises(LspWorkspaceError):
                mapper.uri_to_path("https://example.com/a.py")
            with self.assertRaises(LspWorkspaceError):
                mapper.uri_to_path(Path(outside, "outside.py").resolve().as_uri())
            with self.assertRaises(LspWorkspaceError):
                mapper.uri_to_path("file://remote-host/tmp/a.py")

    def test_protected_roots_and_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (root / ".origin-forge").mkdir()
            mapper = LspWorkspaceMapper(root)
            with self.assertRaises(LspWorkspaceError):
                mapper.path_to_uri(".origin-forge/project.db")

            target = Path(outside) / "secret.py"
            target.write_text("SECRET = 1\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(LspWorkspaceError):
                mapper.path_to_uri("linked.py")
            with self.assertRaises(LspWorkspaceError):
                mapper.uri_to_path(link.absolute().as_uri())


class LspInitializationTests(unittest.TestCase):
    def test_capability_parser_defaults_to_utf16_legacy_position_encoding(self) -> None:
        capabilities = parse_server_capabilities(
            {
                "capabilities": {
                    "workspaceSymbolProvider": True,
                    "definitionProvider": {},
                    "referencesProvider": False,
                }
            }
        )
        self.assertEqual(capabilities.position_encoding, LspPositionEncoding.UTF16)
        self.assertTrue(capabilities.workspace_symbols)
        self.assertTrue(capabilities.definitions)
        self.assertFalse(capabilities.references)
        self.assertFalse(capabilities.diagnostics)

    def test_unsupported_position_encoding_is_rejected(self) -> None:
        with self.assertRaises(LspInitializationError):
            parse_server_capabilities(
                {"capabilities": {"positionEncoding": "utf-7"}}
            )

    def test_initialize_advertises_bounded_origin_forge_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            mapper = LspWorkspaceMapper(temp)
            session = FakeSession(
                {
                    "capabilities": {
                        "positionEncoding": "utf-8",
                        "workspaceSymbolProvider": True,
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "diagnosticProvider": {"identifier": "test"},
                    }
                }
            )
            capabilities = initialize_lsp_session(
                session,
                mapper,
                timeout_seconds=3.0,
            )

            self.assertEqual(capabilities.position_encoding, LspPositionEncoding.UTF8)
            self.assertTrue(capabilities.workspace_symbols)
            self.assertTrue(capabilities.definitions)
            self.assertTrue(capabilities.references)
            self.assertTrue(capabilities.diagnostics)
            self.assertEqual(session.requests[0][0], "initialize")
            params = session.requests[0][1]
            self.assertEqual(
                params["capabilities"]["general"]["positionEncodings"],
                ["utf-8", "utf-16", "utf-32"],
            )
            self.assertEqual(params["rootUri"], mapper.server_root_uri)
            self.assertIsNone(params["workspaceFolders"])
            self.assertNotIn("workspaceFolders", params["capabilities"]["workspace"])
            self.assertEqual(session.notifications, [("initialized", {})])

    def test_initialize_uses_container_visible_root_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            mapper = LspWorkspaceMapper(
                temp,
                server_root_uri="file:///workspace",
            )
            session = FakeSession({"capabilities": {}})

            initialize_lsp_session(session, mapper)

            params = session.requests[0][1]
            self.assertEqual(params["rootUri"], "file:///workspace")
            self.assertIsNone(params["workspaceFolders"])


if __name__ == "__main__":
    unittest.main()
