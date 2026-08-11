from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, TypeVar

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
_FORMAT_VERSION = 1
_MAX_ROOT_BYTES = 64 * 1024
_MAX_CERTIFICATE_BYTES = 128 * 1024
_MAX_REVOCATION_BYTES = 128 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_ROOTS = 1
_MAX_CERTIFICATES = 256
_MAX_REVOCATIONS = 256
_MAX_MANIFESTS = 8192


class ProvenanceReadError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceReadError(f"duplicate provenance JSON key: {key}")
        result[key] = value
    return result


def _canonical_bytes(kind: str, payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            {"format_version": _FORMAT_VERSION, "kind": kind, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


class ProvenanceReadService:
    """Non-creating read-only projection over stored public Phase-18 provenance.

    This inspector validates stored object structure/content hashes, but it does not
    perform Ed25519 trust verification, artifact-currentness checks, or artifact
    byte reads. Those remain Phase-18 verification concerns.
    """

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.root = runtime.state_dir / "provenance"
        self.roots_dir = self.root / "root"
        self.certificates_dir = self.root / "certificates"
        self.revocations_dir = self.root / "revocations"
        self.manifests_dir = self.root / "signed-manifests"

    def _registry_root(self) -> Path | None:
        state = self.runtime.state_dir.resolve(strict=True)
        if not self.root.exists() and not self.root.is_symlink():
            return None
        if self.root.is_symlink() or not self.root.is_dir():
            raise ProvenanceReadError("invalid provenance registry root")
        try:
            resolved = self.root.resolve(strict=True)
            resolved.relative_to(state)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProvenanceReadError("provenance registry escaped protected state") from exc
        return resolved

    def _directory(self, path: Path) -> Path | None:
        root = self._registry_root()
        if root is None:
            return None
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_dir():
            raise ProvenanceReadError(f"invalid provenance directory: {path.name}")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProvenanceReadError("provenance directory escaped registry root") from exc
        return resolved

    @staticmethod
    def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise ProvenanceReadError(f"invalid {label} path: {path.name}")
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if not data or len(data) > maximum:
            raise ProvenanceReadError(f"{label} byte size is outside bounds")
        return data

    def _list_ids(
        self,
        directory: Path,
        *,
        maximum: int,
        validator: Callable[[str], bool],
        label: str,
    ) -> tuple[str, ...]:
        resolved = self._directory(directory)
        if resolved is None:
            return ()
        values: list[str] = []
        for path in resolved.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ProvenanceReadError(
                    f"{label} registry contains unsupported entry: {path.name}"
                )
            object_id = path.stem
            if not validator(object_id):
                raise ProvenanceReadError(f"{label} registry contains invalid ID")
            values.append(object_id)
            if len(values) > maximum:
                raise ProvenanceReadError(f"{label} catalog exceeds bound")
        return tuple(sorted(values))

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
        to_dict: Callable[[_T], dict[str, object]],
        label: str,
    ) -> _T:
        if not validator(object_id):
            raise KeyError(object_id)
        resolved = self._directory(directory)
        if resolved is None:
            raise KeyError(object_id)
        path = resolved / f"{object_id}.json"
        if not path.exists() and not path.is_symlink():
            raise KeyError(object_id)
        data = self._bounded_read(path, maximum_bytes, label)
        try:
            envelope = json.loads(
                data.decode("utf-8"), object_pairs_hook=_strict_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProvenanceReadError(f"invalid {label} JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {
            "format_version",
            "kind",
            "payload",
        }:
            raise ProvenanceReadError(f"invalid {label} envelope")
        if envelope["format_version"] != _FORMAT_VERSION or envelope["kind"] != kind:
            raise ProvenanceReadError(f"invalid {label} envelope metadata")
        try:
            value = parser(envelope["payload"])
        except ProvenanceSerializationError as exc:
            raise ProvenanceReadError(f"{label} validation failed") from exc
        if loaded_id(value) != object_id:
            raise ProvenanceReadError(f"{label} filename/ID mismatch")
        if _canonical_bytes(kind, to_dict(value)) != data:
            raise ProvenanceReadError(f"{label} bytes are not canonical")
        return value

    def root_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.roots_dir,
            maximum=_MAX_ROOTS,
            validator=lambda value: validate_id(value, IdKind.COMPANY_IDENTITY),
            label="Company Root identity",
        )

    def certificate_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.certificates_dir,
            maximum=_MAX_CERTIFICATES,
            validator=lambda value: validate_id(value, IdKind.KEY_CERTIFICATE),
            label="operational certificate",
        )

    def revocation_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.revocations_dir,
            maximum=_MAX_REVOCATIONS,
            validator=lambda value: validate_id(value, IdKind.KEY_REVOCATION),
            label="operational revocation",
        )

    def manifest_ids(self) -> tuple[str, ...]:
        return self._list_ids(
            self.manifests_dir,
            maximum=_MAX_MANIFESTS,
            validator=lambda value: validate_id(value, IdKind.PROVENANCE_MANIFEST),
            label="signed provenance manifest",
        )

    def counts(self) -> dict[str, int]:
        return {
            "roots": len(self.root_ids()),
            "certificates": len(self.certificate_ids()),
            "revocations": len(self.revocation_ids()),
            "manifests": len(self.manifest_ids()),
        }

    def load_root(self, company_id: str) -> CompanyRootIdentity:
        return self._load(
            self.roots_dir,
            object_id=company_id,
            kind="COMPANY_ROOT_IDENTITY",
            maximum_bytes=_MAX_ROOT_BYTES,
            validator=lambda value: validate_id(value, IdKind.COMPANY_IDENTITY),
            parser=parse_root_identity,
            loaded_id=lambda value: value.company_id,
            to_dict=lambda value: value.to_dict(),
            label="Company Root identity",
        )

    def load_certificate(self, certificate_id: str) -> SignedOperationalKeyCertificate:
        return self._load(
            self.certificates_dir,
            object_id=certificate_id,
            kind="SIGNED_OPERATIONAL_KEY_CERTIFICATE",
            maximum_bytes=_MAX_CERTIFICATE_BYTES,
            validator=lambda value: validate_id(value, IdKind.KEY_CERTIFICATE),
            parser=parse_signed_certificate,
            loaded_id=lambda value: value.certificate.certificate_id,
            to_dict=lambda value: value.to_dict(),
            label="operational certificate",
        )

    def load_revocation(self, revocation_id: str) -> SignedOperationalKeyRevocation:
        return self._load(
            self.revocations_dir,
            object_id=revocation_id,
            kind="SIGNED_OPERATIONAL_KEY_REVOCATION",
            maximum_bytes=_MAX_REVOCATION_BYTES,
            validator=lambda value: validate_id(value, IdKind.KEY_REVOCATION),
            parser=parse_signed_revocation,
            loaded_id=lambda value: value.revocation.revocation_id,
            to_dict=lambda value: value.to_dict(),
            label="operational revocation",
        )

    def load_manifest(self, manifest_id: str) -> SignedProvenanceManifest:
        return self._load(
            self.manifests_dir,
            object_id=manifest_id,
            kind="SIGNED_PROVENANCE_MANIFEST",
            maximum_bytes=_MAX_MANIFEST_BYTES,
            validator=lambda value: validate_id(value, IdKind.PROVENANCE_MANIFEST),
            parser=parse_signed_manifest,
            loaded_id=lambda value: value.manifest.manifest_id,
            to_dict=lambda value: value.to_dict(),
            label="signed provenance manifest",
        )

    def roots(self) -> tuple[dict[str, object], ...]:
        return tuple(self._root_projection(self.load_root(value)) for value in self.root_ids())

    def certificates(self) -> tuple[dict[str, object], ...]:
        return tuple(
            self._certificate_projection(self.load_certificate(value))
            for value in self.certificate_ids()
        )

    def revocations(self) -> tuple[dict[str, object], ...]:
        return tuple(
            self._revocation_projection(self.load_revocation(value))
            for value in self.revocation_ids()
        )

    def manifests(self, *, limit: int = 256) -> tuple[dict[str, object], ...]:
        if type(limit) is not int or not 1 <= limit <= _MAX_MANIFESTS:
            raise ValueError(f"provenance manifest limit must be 1..{_MAX_MANIFESTS}")
        return tuple(
            self._manifest_projection(self.load_manifest(value))
            for value in self.manifest_ids()[:limit]
        )

    @staticmethod
    def _root_projection(value: CompanyRootIdentity) -> dict[str, object]:
        return {
            "company_id": value.company_id,
            "display_name": value.display_name,
            "root_key_id": value.root_key_id,
            "algorithm": value.algorithm.value,
            "public_key_fingerprint": value.public_key_fingerprint,
            "created_at": value.created_at,
            "content_hash": value.content_hash,
            "public_key_der_disclosed": False,
        }

    @staticmethod
    def _certificate_projection(
        value: SignedOperationalKeyCertificate,
    ) -> dict[str, object]:
        certificate = value.certificate
        return {
            "certificate_id": certificate.certificate_id,
            "company_id": certificate.company_id,
            "key_id": certificate.key_id,
            "purpose": certificate.purpose.value,
            "algorithm": certificate.algorithm.value,
            "public_key_fingerprint": certificate.public_key_fingerprint,
            "issued_at": certificate.issued_at,
            "not_after": certificate.not_after,
            "content_hash": value.content_hash,
            "root_signature_hash": value.root_signature.signature_hash,
            "public_key_der_disclosed": False,
            "signature_bytes_disclosed": False,
        }

    @staticmethod
    def _revocation_projection(
        value: SignedOperationalKeyRevocation,
    ) -> dict[str, object]:
        revocation = value.revocation
        return {
            "revocation_id": revocation.revocation_id,
            "company_id": revocation.company_id,
            "revoked_key_id": revocation.revoked_key_id,
            "revoked_key_fingerprint": revocation.revoked_key_fingerprint,
            "reason": revocation.reason,
            "effective_at": revocation.effective_at,
            "content_hash": value.content_hash,
            "root_signature_hash": value.root_signature.signature_hash,
            "signature_bytes_disclosed": False,
        }

    @staticmethod
    def _manifest_projection(value: SignedProvenanceManifest) -> dict[str, object]:
        manifest = value.manifest
        return {
            "manifest_id": manifest.manifest_id,
            "content_hash": value.content_hash,
            "manifest_content_hash": manifest.content_hash,
            "company_id": manifest.company_id,
            "artifact_id": manifest.artifact_ref.record_id,
            "artifact_record_hash": manifest.artifact_ref.record_hash,
            "artifact_content_hash": manifest.artifact_content_hash,
            "artifact_type": manifest.artifact_type,
            "artifact_location": manifest.artifact_location,
            "task_id": None if manifest.task_ref is None else manifest.task_ref.record_id,
            "run_id": None if manifest.run_ref is None else manifest.run_ref.record_id,
            "change_id": None if manifest.change_ref is None else manifest.change_ref.record_id,
            "entity_ref_count": len(manifest.entity_refs),
            "design_rule_ref_count": len(manifest.design_rule_refs),
            "decision_ref_count": len(manifest.decision_refs),
            "verification_ref_count": len(manifest.verification_refs),
            "parent_manifest_count": len(manifest.parent_manifest_refs),
            "model_id": manifest.model_id,
            "model_hash": manifest.model_hash,
            "model_profile": manifest.model_profile,
            "skill_ref_count": len(manifest.skill_refs),
            "tool_ref_count": len(manifest.tool_refs),
            "signing_key_id": value.signing_key_id,
            "signing_certificate_hash": value.signing_certificate_hash,
            "signature_hash": value.signature.signature_hash,
            "created_at": manifest.created_at,
            "signature_bytes_disclosed": False,
            "cryptographic_trust_verified_by_cockpit": False,
            "artifact_currentness_verified_by_cockpit": False,
            "artifact_bytes_read": False,
        }
