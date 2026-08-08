from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .pixelorama_bridge import (
    PixeloramaBridgeAdapter,
    PixeloramaBridgeIntegrityError,
    PixeloramaBridgeProfile,
    PixeloramaOperationResult,
)
from .pixelorama_models import PixeloramaBridgeRequest
from .runtime import OriginForgeRuntime


class PixeloramaInstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrustedPixeloramaInstallation:
    profile: PixeloramaBridgeProfile
    pixelorama_fingerprint: str
    expected_pixelorama_version: str
    max_executable_bytes: int = 2 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PixeloramaBridgeProfile):
            raise TypeError("profile must be a PixeloramaBridgeProfile")
        if (
            not isinstance(self.pixelorama_fingerprint, str)
            or not self.pixelorama_fingerprint.startswith("sha256:")
            or len(self.pixelorama_fingerprint) != 71
        ):
            raise ValueError("pixelorama_fingerprint must be a sha256: digest")
        try:
            int(self.pixelorama_fingerprint.split(":", 1)[1], 16)
        except ValueError as exc:
            raise ValueError("pixelorama_fingerprint must be lowercase hexadecimal") from exc
        if self.pixelorama_fingerprint.lower() != self.pixelorama_fingerprint:
            raise ValueError("pixelorama_fingerprint must be lowercase hexadecimal")
        if (
            not isinstance(self.expected_pixelorama_version, str)
            or not self.expected_pixelorama_version.strip()
            or len(self.expected_pixelorama_version) > 256
            or "\x00" in self.expected_pixelorama_version
        ):
            raise ValueError(
                "expected_pixelorama_version must be a bounded non-empty string"
            )
        if (
            not isinstance(self.max_executable_bytes, int)
            or isinstance(self.max_executable_bytes, bool)
            or self.max_executable_bytes <= 0
            or self.max_executable_bytes > 8 * 1024 * 1024 * 1024
        ):
            raise ValueError("max_executable_bytes must be between 1 and 8 GiB")

    @staticmethod
    def _hash_file(path: Path, maximum: int) -> tuple[str, int]:
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise PixeloramaInstallationError(
                        f"Pixelorama executable exceeds byte limit ({total} > {maximum})"
                    )
                digest.update(chunk)
        return "sha256:" + digest.hexdigest(), total

    def verify_files(self) -> dict[str, object]:
        executable, package = self.profile.verify_installation()
        fingerprint, byte_count = self._hash_file(
            executable,
            self.max_executable_bytes,
        )
        if fingerprint != self.pixelorama_fingerprint:
            raise PixeloramaInstallationError(
                "Pixelorama executable fingerprint mismatch"
            )
        return {
            "pixelorama_executable": str(executable),
            "pixelorama_fingerprint": fingerprint,
            "pixelorama_byte_count": byte_count,
            "bridge_package": str(package),
            "bridge_fingerprint": self.profile.bridge_fingerprint,
            "bridge_version": self.profile.bridge_version,
            "protocol_version": self.profile.protocol_version,
            "expected_pixelorama_version": self.expected_pixelorama_version,
        }


class TrustedPixeloramaBridgeAdapter:
    """Require exact editor + bridge identity around one bounded bridge operation."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        installation: TrustedPixeloramaInstallation,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(installation, TrustedPixeloramaInstallation):
            raise TypeError("installation must be a TrustedPixeloramaInstallation")
        self.runtime = runtime
        self.installation = installation
        self.adapter = PixeloramaBridgeAdapter(runtime, installation.profile)

    def execute(
        self,
        request: PixeloramaBridgeRequest,
        *,
        staged_inputs: dict[str, Path] | None = None,
    ) -> PixeloramaOperationResult:
        before = self.installation.verify_files()
        result = self.adapter.execute(
            request,
            staged_inputs=staged_inputs or {},
        )
        after = self.installation.verify_files()
        if before != after:
            raise PixeloramaInstallationError(
                "Pixelorama/bridge installation changed during operation"
            )
        if (
            result.bridge_result.pixelorama_version
            != self.installation.expected_pixelorama_version
        ):
            raise PixeloramaBridgeIntegrityError(
                "bridge-reported Pixelorama version does not match trusted installation"
            )
        return result
