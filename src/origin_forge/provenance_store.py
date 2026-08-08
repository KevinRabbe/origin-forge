from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4

from .ids import IdKind, validate_id
from .provenance_models import (
    CompanyRootIdentity,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
)
from .provenance_serialization import (
    ProvenanceSerializationError,
    parse_root_identity,
    parse_signed_certificate,
    parse_signed_manifest,
    parse_signed_revocation,
)
from .runtime import OriginForgeRuntime


_T = TypeVar("_T")


class ProvenanceStoreError(RuntimeError):
    pass


class ProvenanceStore:
    """Immutable public trust/provenance objects. This store has no secret API."""

    FORMAT_VERSION = 1

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_roots: int = 1,
        max_certificates: int = 256,
        max_revocations: int = 256,
        max_signed_manifests: int = 8192,
        max_root_bytes: int = 64 * 1024,
        max_certificate_bytes: int = 128 * 1024,
        max_revocation_bytes: int = 128 * 1024,
        max_manifest_bytes: int = 2 * 1024 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        for value, name in (
            (max_roots, "max_roots"),
            (max_certificates, "max_certificates"),
            (max_revocations, "max_revocations"),
            (max_signed_manifests, "max_signed_manifests"),
            (max_root_bytes, "max_root_bytes"),
            (max_certificate_bytes, "max_certificate_bytes"),
            (max_revocation_bytes, "max_revocation_bytes"),
            (max_manifest_bytes, "max_manifest_bytes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.runtime = runtime
        self.root = runtime.state_dir / "provenance"
        self.roots_dir = self.root / "root"
        self.certificates_dir = self.root / "certificates"
        self.revocations_dir = self.root / "revocations"
        self.signed_manifests_dir = self.root / "signed-manifests"
        self.max_roots = max_roots
        self.max_certificates = max_certificates
        self.max_revocations = max_revocations
        self.max_signed_manifests = max_signed_manifests
        self.max_root_bytes = max_root_bytes
        self.max_certificate_bytes = max_certificate_bytes
        self.max_revocation_bytes = max_revocation_bytes
        self.max_manifest_bytes = max_manifest_bytes

    @classmethod
    def _canonical_bytes(cls, kind: str, payload: dict[str, object]) -> bytes:
        return (
            json.dumps(
                {
                    "format_version": cls.FORMAT_VERSION,
                    "kind": kind,
                    "payload": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def _validate_dir(self, path: Path, *, create: bool) -> Path:
        state = self.runtime.state_dir.resolve()
        if path.is_symlink():
            raise ProvenanceStoreError(
                f"provenance store path may not be a symlink: {path.name}"
            )
        if create:
            path.mkdir(parents=True, exist_ok=True)
        try:
            resolved = path.resolve()
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProvenanceStoreError(
                "provenance store path escapes protected project state"
            ) from exc
        if path.exists() and not path.is_dir():
            raise ProvenanceStoreError(
                f"provenance store path must be a directory: {path}"
            )
        return resolved

    def ensure(self) -> None:
        for path in (
            self.root,
            self.roots_dir,
            self.certificates_dir,
            self.revocations_dir,
            self.signed_manifests_dir,
        ):
            self._validate_dir(path, create=True)

    @staticmethod
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise ProvenanceStoreError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise ProvenanceStoreError(
                f"{label} exceeds byte limit ({len(data)} > {maximum})"
            )
        return data

    @staticmethod
    def _atomic_publish(path: Path, data: bytes) -> bool:
        """Publish immutable bytes without replacing an existing target.

        Returns True if this caller published the target. False means another
        publisher won the race and the caller must compare winner bytes.
        """

        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, path)
                return True
            except FileExistsError:
                return False
        finally:
            temp.unlink(missing_ok=True)

    def _list_ids(
        self,
        directory: Path,
        *,
        maximum: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> tuple[str, ...]:
        self.ensure()
        values: list[str] = []
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ProvenanceStoreError(
                    f"{label} registry contains unsupported entry: {path.name}"
                )
            object_id = path.stem
            if not validator(object_id):
                raise ProvenanceStoreError(
                    f"{label} registry contains invalid ID: {object_id}"
                )
            values.append(object_id)
            if len(values) > maximum:
                raise ProvenanceStoreError(
                    f"{label} catalog exceeds limit ({len(values)} > {maximum})"
                )
        return tuple(sorted(values))

    def _put(
        self,
        directory: Path,
        *,
        object_id: str,
        kind: str,
        payload: dict[str, object],
        maximum_count: int,
        maximum_bytes: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> Path:
        self.ensure()
        if not validator(object_id):
            raise ProvenanceStoreError(f"invalid {label} ID: {object_id}")
        data = self._canonical_bytes(kind, payload)
        if len(data) > maximum_bytes:
            raise ProvenanceStoreError(
                f"{label} exceeds byte limit ({len(data)} > {maximum_bytes})"
            )
        path = directory / f"{object_id}.json"
        if path.exists() or path.is_symlink():
            current = self._bounded_read(path, maximum_bytes, label)
            if current != data:
                raise ProvenanceStoreError(
                    f"{label} ID is immutable and already exists: {object_id}"
                )
            return path
        if len(
            self._list_ids(
                directory,
                maximum=maximum_count,
                validator=validator,
                label=label,
            )
        ) >= maximum_count:
            raise ProvenanceStoreError(
                f"{label} catalog exceeds limit ({maximum_count + 1} > {maximum_count})"
            )
        if not self._atomic_publish(path, data):
            current = self._bounded_read(path, maximum_bytes, label)
            if current != data:
                raise ProvenanceStoreError(
                    f"{label} ID was published concurrently with different bytes: {object_id}"
                )
        return path

    def _load(
        self,
        directory: Path,
        *,
        object_id: str,
        kind: str,
        maximum_bytes: int,
        validator: Callable[[str], bool],
        parser: Callable[[object], _T],
        loaded_id: Callable[[_T], str],
        label: str,
    ) -> _T:
        self.ensure()
        if not validator(object_id):
            raise ProvenanceStoreError(f"invalid {label} ID: {object_id}")
        path = directory / f"{object_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(object_id)
        data = self._bounded_read(path, maximum_bytes, label)
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProvenanceStoreError(f"invalid {label} JSON: {object_id}") from exc
        if not isinstance(raw, dict) or set(raw) != {"format_version", "kind", "payload"}:
            raise ProvenanceStoreError(f"invalid {label} envelope fields")
        if raw["format_version"] != self.FORMAT_VERSION or raw["kind"] != kind:
            raise ProvenanceStoreError(f"invalid {label} envelope metadata")
        try:
            value = parser(raw["payload"])
        except ProvenanceSerializationError as exc:
            raise ProvenanceStoreError(f"{label} validation failed") from exc
        if loaded_id(value) != object_id:
            raise ProvenanceStoreError(f"{label} filename/ID mismatch: {object_id}")
        return value

    def list_root_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.roots_dir,
            maximum=self.max_roots,
            validator=lambda value: validate_id(value, IdKind.COMPANY_IDENTITY),
            label="Company Root identity",
        )

    def put_root(self, root: CompanyRootIdentity) -> Path:
        if not isinstance(root, CompanyRootIdentity):
            raise TypeError("root must be a CompanyRootIdentity")
        existing = self.list_root_ids()
        if existing and root.company_id not in existing:
            raise ProvenanceStoreError(
                "project provenance store already trusts a different Company Root identity"
            )
        return self._put(
            self.roots_dir,
            object_id=root.company_id,
            kind="COMPANY_ROOT_IDENTITY",
            payload=root.to_dict(),
            maximum_count=self.max_roots,
            maximum_bytes=self.max_root_bytes,
            validator=lambda value: validate_id(value, IdKind.COMPANY_IDENTITY),
            label="Company Root identity",
        )

    def load_root(self, company_id: str) -> CompanyRootIdentity:
        return self._load(
            self.roots_dir,
            object_id=company_id,
            kind="COMPANY_ROOT_IDENTITY",
            maximum_bytes=self.max_root_bytes,
            validator=lambda value: validate_id(value, IdKind.COMPANY_IDENTITY),
            parser=parse_root_identity,
            loaded_id=lambda value: value.company_id,
            label="Company Root identity",
        )

    def list_certificate_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.certificates_dir,
            maximum=self.max_certificates,
            validator=lambda value: validate_id(value, IdKind.KEY_CERTIFICATE),
            label="operational key certificate",
        )

    def put_certificate(self, certificate: SignedOperationalKeyCertificate) -> Path:
        if not isinstance(certificate, SignedOperationalKeyCertificate):
            raise TypeError("certificate must be a SignedOperationalKeyCertificate")
        return self._put(
            self.certificates_dir,
            object_id=certificate.certificate.certificate_id,
            kind="SIGNED_OPERATIONAL_KEY_CERTIFICATE",
            payload=certificate.to_dict(),
            maximum_count=self.max_certificates,
            maximum_bytes=self.max_certificate_bytes,
            validator=lambda value: validate_id(value, IdKind.KEY_CERTIFICATE),
            label="operational key certificate",
        )

    def load_certificate(self, certificate_id: str) -> SignedOperationalKeyCertificate:
        return self._load(
            self.certificates_dir,
            object_id=certificate_id,
            kind="SIGNED_OPERATIONAL_KEY_CERTIFICATE",
            maximum_bytes=self.max_certificate_bytes,
            validator=lambda value: validate_id(value, IdKind.KEY_CERTIFICATE),
            parser=parse_signed_certificate,
            loaded_id=lambda value: value.certificate.certificate_id,
            label="operational key certificate",
        )

    def list_revocation_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.revocations_dir,
            maximum=self.max_revocations,
            validator=lambda value: validate_id(value, IdKind.KEY_REVOCATION),
            label="operational key revocation",
        )

    def put_revocation(self, revocation: SignedOperationalKeyRevocation) -> Path:
        if not isinstance(revocation, SignedOperationalKeyRevocation):
            raise TypeError("revocation must be a SignedOperationalKeyRevocation")
        return self._put(
            self.revocations_dir,
            object_id=revocation.revocation.revocation_id,
            kind="SIGNED_OPERATIONAL_KEY_REVOCATION",
            payload=revocation.to_dict(),
            maximum_count=self.max_revocations,
            maximum_bytes=self.max_revocation_bytes,
            validator=lambda value: validate_id(value, IdKind.KEY_REVOCATION),
            label="operational key revocation",
        )

    def load_revocation(self, revocation_id: str) -> SignedOperationalKeyRevocation:
        return self._load(
            self.revocations_dir,
            object_id=revocation_id,
            kind="SIGNED_OPERATIONAL_KEY_REVOCATION",
            maximum_bytes=self.max_revocation_bytes,
            validator=lambda value: validate_id(value, IdKind.KEY_REVOCATION),
            parser=parse_signed_revocation,
            loaded_id=lambda value: value.revocation.revocation_id,
            label="operational key revocation",
        )

    def list_manifest_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.signed_manifests_dir,
            maximum=self.max_signed_manifests,
            validator=lambda value: validate_id(value, IdKind.PROVENANCE_MANIFEST),
            label="signed provenance manifest",
        )

    def put_manifest(self, manifest: SignedProvenanceManifest) -> Path:
        if not isinstance(manifest, SignedProvenanceManifest):
            raise TypeError("manifest must be a SignedProvenanceManifest")
        return self._put(
            self.signed_manifests_dir,
            object_id=manifest.manifest.manifest_id,
            kind="SIGNED_PROVENANCE_MANIFEST",
            payload=manifest.to_dict(),
            maximum_count=self.max_signed_manifests,
            maximum_bytes=self.max_manifest_bytes,
            validator=lambda value: validate_id(value, IdKind.PROVENANCE_MANIFEST),
            label="signed provenance manifest",
        )

    def load_manifest(self, manifest_id: str) -> SignedProvenanceManifest:
        return self._load(
            self.signed_manifests_dir,
            object_id=manifest_id,
            kind="SIGNED_PROVENANCE_MANIFEST",
            maximum_bytes=self.max_manifest_bytes,
            validator=lambda value: validate_id(value, IdKind.PROVENANCE_MANIFEST),
            parser=parse_signed_manifest,
            loaded_id=lambda value: value.manifest.manifest_id,
            label="signed provenance manifest",
        )
