from __future__ import annotations

import hashlib
import inspect
import json
import os
import socket
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from origin_forge.adapters.llamacpp import LlamaCppAdapter
from origin_forge.managed_llamacpp_loader import (
    ManagedLlamaCppCpuLoader,
    ManagedLlamaCppLoaderError,
)
from origin_forge.model_runtime_config import parse_model_runtime_config
from origin_forge.resource_model_config import parse_resource_model_config
from origin_forge.resource_scheduler import AssignedGpuResources, ResourceLease


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


_FAKE_SERVER = textwrap.dedent(
    f"""\
    #!{sys.executable}
    import json
    import os
    import sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    args = sys.argv[1:]
    def value(name):
        index = args.index(name)
        return args[index + 1]

    model = Path(value("--model"))
    observed = model.with_suffix(".observed.json")
    observed.write_text(json.dumps({{"argv": args, "env": dict(os.environ)}}), encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            body = b'{{"status":"ok"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args):
            pass

    HTTPServer((value("--host"), int(value("--port"))), Handler).serve_forever()
    """
)


_STALLED_SERVER = textwrap.dedent(
    f"""\
    #!{sys.executable}
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    args = sys.argv[1:]
    model = Path(args[args.index("--model") + 1])
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    model.with_suffix(".pids").write_text(f"{{os.getpid()}} {{child.pid}}", encoding="utf-8")
    time.sleep(60)
    """
)


class ManagedLlamaCppCpuLoaderTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        executable: Path | None = None,
        model: Path | None = None,
        port: int | None = None,
        startup_timeout: float = 2.0,
        shutdown_timeout: float = 1.0,
    ):
        executable = executable or root / "llama-server"
        model = model or root / "model.gguf"
        if not executable.exists() and not executable.is_symlink():
            _write_executable(executable, _FAKE_SERVER)
        if not model.exists() and not model.is_symlink():
            model.write_bytes(b"fake-governed-gguf-model")
        model_hash = _sha256(model.resolve())
        executable_hash = _sha256(executable.resolve())
        resources = parse_resource_model_config(
            {
                "enabled": True,
                "cpu_slots": 8,
                "ram_mib": 16384,
                "max_active_leases": 8,
                "gpus": [],
            },
            {
                "profiles": [
                    {
                        "profile_id": "strong",
                        "role": "coder_strong",
                        "model_id": "test-model",
                        "model_hash": model_hash,
                        "runtime_id": "llamacpp-cpu",
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
        runtime_config = parse_model_runtime_config(
            {
                "providers": [
                    {
                        "runtime_id": "llamacpp-cpu",
                        "provider_kind": "originforge.llamacpp-managed-cpu@1",
                        "provider_contract_version": "1",
                        "executable_path": str(executable),
                        "executable_sha256": executable_hash,
                        "port": port or _free_port(),
                        "startup_timeout_seconds": startup_timeout,
                        "request_timeout_seconds": 3,
                        "shutdown_timeout_seconds": shutdown_timeout,
                        "profile_bindings": [
                            {
                                "profile_id": "strong",
                                "model_path": str(model),
                                "model_sha256": model_hash,
                            }
                        ],
                    }
                ]
            },
            resources,
        )
        profile = resources.registry().profile("strong")
        provider = runtime_config.provider("llamacpp-cpu")
        lease = ResourceLease(
            lease_id="LEASE-test",
            owner_id="RUN-test",
            cpu_slots=2,
            ram_mib=4096,
            gpu=None,
        )
        return profile, provider, lease, executable, model

    @unittest.skipUnless(os.name == "posix", "fake executable fixture requires POSIX")
    def test_fixed_cpu_argv_minimal_environment_readiness_and_owned_unload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile, provider, lease, executable, model = self._fixture(root)
            loader = ManagedLlamaCppCpuLoader(root, provider)
            old_secret = os.environ.get("ORIGIN_FORGE_TEST_SECRET")
            os.environ["ORIGIN_FORGE_TEST_SECRET"] = "must-not-leak"
            try:
                adapter = loader.load(profile, lease)
            finally:
                if old_secret is None:
                    os.environ.pop("ORIGIN_FORGE_TEST_SECRET", None)
                else:
                    os.environ["ORIGIN_FORGE_TEST_SECRET"] = old_secret

            self.assertIsInstance(adapter, LlamaCppAdapter)
            self.assertEqual(adapter.model_id, "test-model")
            self.assertEqual(adapter.settings.model_hash, profile.model_hash)
            self.assertEqual(adapter.settings.base_url, f"http://127.0.0.1:{provider.port}")
            self.assertFalse(adapter.settings.allow_remote)
            self.assertEqual(loader.active_instance_count(), 1)

            observed = json.loads(model.with_suffix(".observed.json").read_text(encoding="utf-8"))
            self.assertEqual(
                observed["argv"],
                [
                    "--model",
                    str(model),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(provider.port),
                    "--threads",
                    "2",
                    "--threads-batch",
                    "2",
                    "--device",
                    "none",
                    "--n-gpu-layers",
                    "0",
                    "--offline",
                    "--no-webui",
                    "--no-slots",
                    "--no-mmproj",
                ],
            )
            self.assertNotIn("ORIGIN_FORGE_TEST_SECRET", observed["env"])
            self.assertEqual(observed["env"].get("LANG"), "C.UTF-8")
            self.assertEqual(observed["env"].get("LC_ALL"), "C.UTF-8")
            self.assertFalse(any(key.startswith("LLAMA_ARG_") for key in observed["env"]))
            self.assertNotIn("HF_TOKEN", observed["env"])

            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "already owns"):
                loader.load(profile, lease)
            loader.unload(adapter)
            self.assertEqual(loader.active_instance_count(), 0)
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "not owned"):
                loader.unload(adapter)
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", provider.port), timeout=0.1)

    def test_hash_drift_symlink_protected_state_and_lease_mismatch_fail_before_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile, provider, lease, executable, model = self._fixture(root)
            model.write_bytes(b"tampered")
            loader = ManagedLlamaCppCpuLoader(root, provider)
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "model SHA-256"):
                loader.load(profile, lease)
            self.assertFalse(model.with_suffix(".observed.json").exists())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "real-llama-server"
            _write_executable(target, _FAKE_SERVER)
            link = root / "llama-server"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink capability unavailable: {exc}")
            profile, provider, lease, _, model = self._fixture(root, executable=link)
            loader = ManagedLlamaCppCpuLoader(root, provider)
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "symlink"):
                loader.load(profile, lease)
            self.assertFalse(model.with_suffix(".observed.json").exists())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / ".origin-forge"
            protected.mkdir()
            model = protected / "model.gguf"
            model.write_bytes(b"protected-model")
            profile, provider, lease, _, _ = self._fixture(root, model=model)
            loader = ManagedLlamaCppCpuLoader(root, provider)
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "protected Origin Forge state"):
                loader.load(profile, lease)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile, provider, lease, _, _ = self._fixture(root)
            loader = ManagedLlamaCppCpuLoader(root, provider)
            wrong = ResourceLease(
                lease_id=lease.lease_id,
                owner_id=lease.owner_id,
                cpu_slots=1,
                ram_mib=lease.ram_mib,
                gpu=None,
            )
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "exactly match"):
                loader.load(profile, wrong)
            gpu = ResourceLease(
                lease_id=lease.lease_id,
                owner_id=lease.owner_id,
                cpu_slots=lease.cpu_slots,
                ram_mib=lease.ram_mib,
                gpu=AssignedGpuResources("gpu0", 1, 1, False),
            )
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "rejects GPU"):
                loader.load(profile, gpu)

    def test_fixed_port_collision_fails_without_starting_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            port = _free_port()
            profile, provider, lease, _, model = self._fixture(root, port=port)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
                blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                blocker.bind(("127.0.0.1", port))
                blocker.listen(1)
                loader = ManagedLlamaCppCpuLoader(root, provider)
                with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "port is already in use"):
                    loader.load(profile, lease)
            self.assertFalse(model.with_suffix(".observed.json").exists())

    @unittest.skipUnless(os.name == "posix", "process-group proof requires POSIX")
    def test_startup_timeout_kills_owned_process_group_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "llama-server"
            _write_executable(executable, _STALLED_SERVER)
            profile, provider, lease, _, model = self._fixture(
                root,
                executable=executable,
                startup_timeout=0.3,
                shutdown_timeout=0.3,
            )
            loader = ManagedLlamaCppCpuLoader(root, provider)
            with self.assertRaisesRegex(ManagedLlamaCppLoaderError, "startup timeout"):
                loader.load(profile, lease)
            pid_path = model.with_suffix(".pids")
            self.assertTrue(pid_path.exists())
            parent_pid, child_pid = (int(value) for value in pid_path.read_text().split())
            for pid in (parent_pid, child_pid):
                with self.subTest(pid=pid):
                    deadline = time.monotonic() + 2.0
                    while _pid_exists(pid) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertFalse(_pid_exists(pid))
            self.assertEqual(loader.active_instance_count(), 0)

    def test_loader_api_contains_no_caller_runtime_authority(self) -> None:
        constructor = inspect.signature(ManagedLlamaCppCpuLoader)
        self.assertEqual(tuple(constructor.parameters), ("project_root", "provider"))
        load = inspect.signature(ManagedLlamaCppCpuLoader.load)
        self.assertEqual(tuple(load.parameters), ("self", "profile", "lease"))
        unload = inspect.signature(ManagedLlamaCppCpuLoader.unload)
        self.assertEqual(tuple(unload.parameters), ("self", "instance"))
        for forbidden in (
            "argv",
            "endpoint",
            "base_url",
            "environment",
            "runner",
            "process_factory",
            "loader",
            "model_path",
            "api_key",
        ):
            self.assertNotIn(forbidden, constructor.parameters)
            self.assertNotIn(forbidden, load.parameters)


if __name__ == "__main__":
    unittest.main()
