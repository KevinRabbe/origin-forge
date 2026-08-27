from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from .provenance_models import (
    CompanyRootIdentity,
    DetachedSignature,
    OperationalKeyCertificate,
    OperationalKeyRevocation,
    ProvenanceManifest,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
    canonical_bytes,
)


CERTIFICATE_DOMAIN = b"origin-forge/operational-key-certificate/v1\x00"
REVOCATION_DOMAIN = b"origin-forge/operational-key-revocation/v1\x00"
PROVENANCE_MANIFEST_DOMAIN = b"origin-forge/provenance-manifest/v1\x00"


class SignatureBackendError(RuntimeError):
    pass


class SecretContainmentError(SignatureBackendError):
    pass


@runtime_checkable
class SignatureBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    def public_key_der(self, private_key_handle: Path) -> bytes: ...

    def sign(self, private_key_handle: Path, message: bytes) -> bytes: ...

    def verify(self, public_key_der: bytes, message: bytes, signature: bytes) -> bool: ...


def domain_message(domain: bytes, payload: dict[str, object], *, maximum: int = 1024 * 1024) -> bytes:
    if not isinstance(domain, bytes) or not domain.endswith(b"\x00") or not domain:
        raise ValueError("signature domain must be non-empty bytes ending in NUL")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("signature message maximum must be a positive integer")
    message = domain + canonical_bytes(payload)
    if len(message) > maximum:
        raise SignatureBackendError(
            f"signature message exceeds byte limit ({len(message)} > {maximum})"
        )
    return message


def certificate_message(certificate: OperationalKeyCertificate) -> bytes:
    if not isinstance(certificate, OperationalKeyCertificate):
        raise TypeError("certificate must be an OperationalKeyCertificate")
    return domain_message(CERTIFICATE_DOMAIN, certificate.to_dict())


def revocation_message(revocation: OperationalKeyRevocation) -> bytes:
    if not isinstance(revocation, OperationalKeyRevocation):
        raise TypeError("revocation must be an OperationalKeyRevocation")
    return domain_message(REVOCATION_DOMAIN, revocation.to_dict())


def provenance_manifest_message(manifest: ProvenanceManifest) -> bytes:
    if not isinstance(manifest, ProvenanceManifest):
        raise TypeError("manifest must be a ProvenanceManifest")
    return domain_message(PROVENANCE_MANIFEST_DOMAIN, manifest.to_dict())


class OpenSslEd25519Backend:
    """Local Ed25519 backend with no Python crypto dependency and no shell use."""

    def __init__(
        self,
        project_root: Path,
        *,
        openssl_executable: str = "openssl",
        max_message_bytes: int = 1024 * 1024,
        timeout_seconds: int = 10,
        max_diagnostic_bytes: int = 8192,
    ):
        self.project_root = Path(project_root).resolve()
        if not self.project_root.is_dir():
            raise ValueError("project_root must be an existing directory")
        resolved = shutil.which(openssl_executable)
        if resolved is None:
            raise SignatureBackendError("configured OpenSSL executable is unavailable")
        self.openssl_path = Path(resolved).resolve()
        if not self.openssl_path.is_file():
            raise SignatureBackendError("resolved OpenSSL executable is not a file")
        for value, name, maximum in (
            (max_message_bytes, "max_message_bytes", 16 * 1024 * 1024),
            (timeout_seconds, "timeout_seconds", 120),
            (max_diagnostic_bytes, "max_diagnostic_bytes", 1024 * 1024),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        self.max_message_bytes = max_message_bytes
        self.timeout_seconds = timeout_seconds
        self.max_diagnostic_bytes = max_diagnostic_bytes

    @property
    def backend_id(self) -> str:
        return "openssl-ed25519"

    def _run(self, args: list[str], *, verification: bool = False) -> subprocess.CompletedProcess[bytes]:
        command = [str(self.openssl_path), *args]
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SignatureBackendError("OpenSSL operation exceeded timeout") from exc
        if len(result.stdout) > self.max_diagnostic_bytes or len(result.stderr) > self.max_diagnostic_bytes:
            raise SignatureBackendError("OpenSSL diagnostic output exceeded byte limit")
        if verification:
            if result.returncode == 0:
                return result
            if result.returncode == 1:
                return result
            raise SignatureBackendError(
                f"OpenSSL verification operation failed with exit code {result.returncode}"
            )
        if result.returncode != 0:
            raise SignatureBackendError(
                f"OpenSSL operation failed with exit code {result.returncode}"
            )
        return result

    def available(self) -> bool:
        try:
            self._run(["version"])
        except SignatureBackendError:
            return False
        return True

    def _private_key_path(self, handle: Path) -> Path:
        path = Path(handle)
        if not path.is_absolute():
            raise SecretContainmentError("private key path must be absolute")
        if path.is_symlink():
            raise SecretContainmentError("private key path may not be a symlink")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SecretContainmentError("private key path is unavailable") from exc
        if not resolved.is_file():
            raise SecretContainmentError("private key path must be a regular file")
        try:
            resolved.relative_to(self.project_root)
        except ValueError:
            pass
        else:
            raise SecretContainmentError("private key path must stay outside the project root")
        if os.name != "nt":
            mode = stat.S_IMODE(resolved.stat().st_mode)
            if mode & 0o077:
                raise SecretContainmentError(
                    "private key file permissions must deny group/world access"
                )
        return resolved

    def _bounded_message(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise TypeError("signature message must be bytes")
        if not message:
            raise SignatureBackendError("signature message may not be empty")
        if len(message) > self.max_message_bytes:
            raise SignatureBackendError(
                f"signature message exceeds byte limit ({len(message)} > {self.max_message_bytes})"
            )
        return message

    @staticmethod
    def _write_private_temp(path: Path, data: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
        if os.name != "nt":
            path.chmod(0o600)

    def public_key_der(self, private_key_handle: Path) -> bytes:
        private_key = self._private_key_path(private_key_handle)
        with tempfile.TemporaryDirectory(prefix="origin-forge-ed25519-") as tempdir:
            root = Path(tempdir)
            if os.name != "nt":
                root.chmod(0o700)
            public_path = root / "public.der"
            self._run(
                [
                    "pkey",
                    "-in",
                    str(private_key),
                    "-passin",
                    "pass:",
                    "-pubout",
                    "-outform",
                    "DER",
                    "-out",
                    str(public_path),
                ]
            )
            try:
                data = public_path.read_bytes()
            except OSError as exc:
                raise SignatureBackendError("OpenSSL did not produce public key output") from exc
        if not data or len(data) > 4096:
            raise SignatureBackendError("OpenSSL public key output length is invalid")
        return data

    def sign(self, private_key_handle: Path, message: bytes) -> bytes:
        private_key = self._private_key_path(private_key_handle)
        message = self._bounded_message(message)
        with tempfile.TemporaryDirectory(prefix="origin-forge-ed25519-") as tempdir:
            root = Path(tempdir)
            if os.name != "nt":
                root.chmod(0o700)
            message_path = root / "message.bin"
            signature_path = root / "signature.bin"
            self._write_private_temp(message_path, message)
            self._run(
                [
                    "pkeyutl",
                    "-sign",
                    "-rawin",
                    "-inkey",
                    str(private_key),
                    "-passin",
                    "pass:",
                    "-in",
                    str(message_path),
                    "-out",
                    str(signature_path),
                ]
            )
            try:
                signature = signature_path.read_bytes()
            except OSError as exc:
                raise SignatureBackendError("OpenSSL did not produce signature output") from exc
        if len(signature) != 64:
            raise SignatureBackendError("OpenSSL Ed25519 signature length is invalid")
        return signature

    def verify(self, public_key_der: bytes, message: bytes, signature: bytes) -> bool:
        if not isinstance(public_key_der, bytes) or not public_key_der or len(public_key_der) > 4096:
            raise SignatureBackendError("public key DER byte length is invalid")
        message = self._bounded_message(message)
        if not isinstance(signature, bytes) or len(signature) != 64:
            return False
        with tempfile.TemporaryDirectory(prefix="origin-forge-ed25519-") as tempdir:
            root = Path(tempdir)
            if os.name != "nt":
                root.chmod(0o700)
            public_path = root / "public.der"
            message_path = root / "message.bin"
            signature_path = root / "signature.bin"
            self._write_private_temp(public_path, public_key_der)
            self._write_private_temp(message_path, message)
            self._write_private_temp(signature_path, signature)
            result = self._run(
                [
                    "pkeyutl",
                    "-verify",
                    "-rawin",
                    "-pubin",
                    "-keyform",
                    "DER",
                    "-inkey",
                    str(public_path),
                    "-sigfile",
                    str(signature_path),
                    "-in",
                    str(message_path),
                ],
                verification=True,
            )
            return result.returncode == 0


class RootAuthority:
    """Rare root-key operations. This object has no Artifact/Task mutation authority."""

    def __init__(
        self,
        root: CompanyRootIdentity,
        backend: SignatureBackend,
        root_private_key_handle: Path,
    ):
        if not isinstance(root, CompanyRootIdentity):
            raise TypeError("root must be a CompanyRootIdentity")
        if not isinstance(backend, SignatureBackend):
            raise TypeError("backend must satisfy SignatureBackend")
        actual_public = backend.public_key_der(root_private_key_handle)
        if actual_public != __import__("base64").b64decode(root.public_key_der_b64, validate=True):
            raise SecretContainmentError("root private key does not match trusted root public key")
        self.root = root
        self.backend = backend
        self._root_private_key_handle = Path(root_private_key_handle)

    def sign_certificate(self, certificate: OperationalKeyCertificate) -> SignedOperationalKeyCertificate:
        if certificate.company_id != self.root.company_id or certificate.root_identity_hash != self.root.content_hash:
            raise SignatureBackendError("operational certificate is not bound to this root identity")
        signature = self.backend.sign(
            self._root_private_key_handle,
            certificate_message(certificate),
        )
        return SignedOperationalKeyCertificate(
            certificate,
            DetachedSignature.create(
                key_id=self.root.root_key_id,
                algorithm=self.root.algorithm,
                signed_payload_hash=certificate.content_hash,
                signature=signature,
            ),
        )

    def sign_revocation(self, revocation: OperationalKeyRevocation) -> SignedOperationalKeyRevocation:
        if revocation.company_id != self.root.company_id or revocation.root_identity_hash != self.root.content_hash:
            raise SignatureBackendError("operational revocation is not bound to this root identity")
        signature = self.backend.sign(
            self._root_private_key_handle,
            revocation_message(revocation),
        )
        return SignedOperationalKeyRevocation(
            revocation,
            DetachedSignature.create(
                key_id=self.root.root_key_id,
                algorithm=self.root.algorithm,
                signed_payload_hash=revocation.content_hash,
                signature=signature,
            ),
        )


class OperationalManifestSigner:
    """Artifact-manifest signing only; no root-certification or project-state authority."""

    def __init__(
        self,
        certificate: SignedOperationalKeyCertificate,
        backend: SignatureBackend,
        private_key_handle: Path,
    ):
        if not isinstance(certificate, SignedOperationalKeyCertificate):
            raise TypeError("certificate must be a SignedOperationalKeyCertificate")
        if certificate.certificate.purpose.value != "ARTIFACT_SIGNING":
            raise SignatureBackendError("operational key is not authorized for Artifact signing")
        if not isinstance(backend, SignatureBackend):
            raise TypeError("backend must satisfy SignatureBackend")
        actual_public = backend.public_key_der(private_key_handle)
        expected_public = __import__("base64").b64decode(
            certificate.certificate.public_key_der_b64, validate=True
        )
        if actual_public != expected_public:
            raise SecretContainmentError(
                "operational private key does not match certified public key"
            )
        self.certificate = certificate
        self.backend = backend
        self._private_key_handle = Path(private_key_handle)

    def sign(self, manifest: ProvenanceManifest) -> SignedProvenanceManifest:
        certificate = self.certificate.certificate
        if manifest.company_id != certificate.company_id or manifest.root_identity_hash != certificate.root_identity_hash:
            raise SignatureBackendError("manifest trust identity does not match signing certificate")
        signature = self.backend.sign(
            self._private_key_handle,
            provenance_manifest_message(manifest),
        )
        return SignedProvenanceManifest(
            manifest=manifest,
            signing_key_id=certificate.key_id,
            signing_certificate_hash=self.certificate.content_hash,
            signature=DetachedSignature.create(
                key_id=certificate.key_id,
                algorithm=certificate.algorithm,
                signed_payload_hash=manifest.content_hash,
                signature=signature,
            ),
        )
