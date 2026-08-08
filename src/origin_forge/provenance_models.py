from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable

from .ids import IdKind, new_id, validate_id


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PUBLIC_KEY_BYTES = 4096
_MAX_TEXT = 16 * 1024
_MAX_RECORD_REFS = 512
_MAX_PARENT_MANIFESTS = 128
_MAX_SKILL_TOOL_REFS = 256


class ProvenanceModelError(ValueError):
    pass


class SignatureAlgorithm(StrEnum):
    ED25519 = "ED25519"


class OperationalKeyPurpose(StrEnum):
    ARTIFACT_SIGNING = "ARTIFACT_SIGNING"
    BUILD_SIGNING = "BUILD_SIGNING"
    RELEASE_SIGNING = "RELEASE_SIGNING"
    ASSET_SIGNING = "ASSET_SIGNING"


class ProvenanceRecordType(StrEnum):
    PROJECT = "PROJECT"
    ENTITY = "ENTITY"
    DESIGN_RULE = "DESIGN_RULE"
    GOAL = "GOAL"
    FLOW = "FLOW"
    TASK = "TASK"
    RUN = "RUN"
    DECISION = "DECISION"
    CHANGE = "CHANGE"
    ARTIFACT = "ARTIFACT"
    VERIFICATION = "VERIFICATION"


_RECORD_ID_KIND = {
    ProvenanceRecordType.PROJECT: IdKind.PROJECT,
    ProvenanceRecordType.ENTITY: IdKind.ENTITY,
    ProvenanceRecordType.DESIGN_RULE: IdKind.DESIGN_RULE,
    ProvenanceRecordType.GOAL: IdKind.GOAL,
    ProvenanceRecordType.FLOW: IdKind.FLOW,
    ProvenanceRecordType.TASK: IdKind.TASK,
    ProvenanceRecordType.RUN: IdKind.RUN,
    ProvenanceRecordType.DECISION: IdKind.DECISION,
    ProvenanceRecordType.CHANGE: IdKind.CHANGE,
    ProvenanceRecordType.ARTIFACT: IdKind.ARTIFACT,
    ProvenanceRecordType.VERIFICATION: IdKind.VERIFICATION,
}


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProvenanceModelError("value is not canonical JSON serializable") from exc


def sha256_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("sha256_bytes requires bytes")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_hash(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def validate_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProvenanceModelError(f"{field} must be a lowercase sha256: digest")
    return value


def _text(value: str, field: str, *, allow_empty: bool = False, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ProvenanceModelError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ProvenanceModelError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ProvenanceModelError(f"{field} exceeds character limit ({len(value)} > {maximum})")
    if "\x00" in value:
        raise ProvenanceModelError(f"{field} may not contain NUL")
    return value


def _timestamp(value: str, field: str) -> str:
    _text(value, field, maximum=64)
    if not value.endswith("Z"):
        raise ProvenanceModelError(f"{field} must use UTC Z format")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProvenanceModelError(f"{field} is not a valid timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ProvenanceModelError(f"{field} must be UTC")
    return value


def _decode_b64(value: str, field: str, *, maximum: int) -> bytes:
    _text(value, field, maximum=((maximum + 2) // 3) * 4 + 8)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ProvenanceModelError(f"{field} must be strict Base64") from exc
    if not decoded or len(decoded) > maximum:
        raise ProvenanceModelError(f"{field} decoded byte length is invalid")
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ProvenanceModelError(f"{field} must use canonical Base64")
    return decoded


def public_key_b64(public_key_der: bytes) -> str:
    if not isinstance(public_key_der, bytes) or not public_key_der or len(public_key_der) > _MAX_PUBLIC_KEY_BYTES:
        raise ProvenanceModelError("public key DER byte length is invalid")
    return base64.b64encode(public_key_der).decode("ascii")


def public_key_fingerprint(public_key_der: bytes) -> str:
    if not isinstance(public_key_der, bytes) or not public_key_der or len(public_key_der) > _MAX_PUBLIC_KEY_BYTES:
        raise ProvenanceModelError("public key DER byte length is invalid")
    return sha256_bytes(public_key_der)


def decode_public_key(value: str) -> bytes:
    return _decode_b64(value, "public_key_der_b64", maximum=_MAX_PUBLIC_KEY_BYTES)


@dataclass(frozen=True)
class CompanyRootIdentity:
    company_id: str
    display_name: str
    root_key_id: str
    algorithm: SignatureAlgorithm
    public_key_der_b64: str
    public_key_fingerprint: str
    created_at: str

    def __post_init__(self) -> None:
        if not validate_id(self.company_id, IdKind.COMPANY_IDENTITY):
            raise ProvenanceModelError("company_id must be a COMPANY ID")
        if not validate_id(self.root_key_id, IdKind.PROVENANCE_KEY):
            raise ProvenanceModelError("root_key_id must be a PKEY ID")
        _text(self.display_name, "display_name", maximum=512)
        if not isinstance(self.algorithm, SignatureAlgorithm):
            raise ProvenanceModelError("algorithm must be a SignatureAlgorithm")
        public_key = decode_public_key(self.public_key_der_b64)
        expected = public_key_fingerprint(public_key)
        if self.public_key_fingerprint != expected:
            raise ProvenanceModelError("root public_key_fingerprint mismatch")
        _timestamp(self.created_at, "created_at")

    @classmethod
    def create(
        cls,
        display_name: str,
        public_key_der: bytes,
        *,
        created_at: str,
    ) -> "CompanyRootIdentity":
        return cls(
            company_id=new_id(IdKind.COMPANY_IDENTITY),
            display_name=display_name,
            root_key_id=new_id(IdKind.PROVENANCE_KEY),
            algorithm=SignatureAlgorithm.ED25519,
            public_key_der_b64=public_key_b64(public_key_der),
            public_key_fingerprint=public_key_fingerprint(public_key_der),
            created_at=created_at,
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "company_id": self.company_id,
            "display_name": self.display_name,
            "root_key_id": self.root_key_id,
            "algorithm": self.algorithm.value,
            "public_key_der_b64": self.public_key_der_b64,
            "public_key_fingerprint": self.public_key_fingerprint,
            "created_at": self.created_at,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class DetachedSignature:
    key_id: str
    algorithm: SignatureAlgorithm
    signed_payload_hash: str
    signature_b64: str

    def __post_init__(self) -> None:
        if not validate_id(self.key_id, IdKind.PROVENANCE_KEY):
            raise ProvenanceModelError("signature key_id must be a PKEY ID")
        if not isinstance(self.algorithm, SignatureAlgorithm):
            raise ProvenanceModelError("signature algorithm must be a SignatureAlgorithm")
        validate_sha256(self.signed_payload_hash, "signed_payload_hash")
        signature = _decode_b64(self.signature_b64, "signature_b64", maximum=512)
        if self.algorithm == SignatureAlgorithm.ED25519 and len(signature) != 64:
            raise ProvenanceModelError("Ed25519 signature must be exactly 64 bytes")

    @classmethod
    def create(
        cls,
        *,
        key_id: str,
        algorithm: SignatureAlgorithm,
        signed_payload_hash: str,
        signature: bytes,
    ) -> "DetachedSignature":
        return cls(
            key_id=key_id,
            algorithm=algorithm,
            signed_payload_hash=signed_payload_hash,
            signature_b64=base64.b64encode(signature).decode("ascii"),
        )

    @property
    def signature_bytes(self) -> bytes:
        return _decode_b64(self.signature_b64, "signature_b64", maximum=512)

    @property
    def signature_hash(self) -> str:
        return sha256_bytes(self.signature_bytes)

    def to_dict(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm.value,
            "signed_payload_hash": self.signed_payload_hash,
            "signature_b64": self.signature_b64,
            "signature_hash": self.signature_hash,
        }


@dataclass(frozen=True)
class OperationalKeyCertificate:
    certificate_id: str
    company_id: str
    root_identity_hash: str
    key_id: str
    purpose: OperationalKeyPurpose
    algorithm: SignatureAlgorithm
    public_key_der_b64: str
    public_key_fingerprint: str
    issued_at: str
    not_after: str | None = None

    def __post_init__(self) -> None:
        if not validate_id(self.certificate_id, IdKind.KEY_CERTIFICATE):
            raise ProvenanceModelError("certificate_id must be a KEYCERT ID")
        if not validate_id(self.company_id, IdKind.COMPANY_IDENTITY):
            raise ProvenanceModelError("company_id must be a COMPANY ID")
        validate_sha256(self.root_identity_hash, "root_identity_hash")
        if not validate_id(self.key_id, IdKind.PROVENANCE_KEY):
            raise ProvenanceModelError("key_id must be a PKEY ID")
        if not isinstance(self.purpose, OperationalKeyPurpose):
            raise ProvenanceModelError("purpose must be an OperationalKeyPurpose")
        if not isinstance(self.algorithm, SignatureAlgorithm):
            raise ProvenanceModelError("algorithm must be a SignatureAlgorithm")
        public_key = decode_public_key(self.public_key_der_b64)
        if self.public_key_fingerprint != public_key_fingerprint(public_key):
            raise ProvenanceModelError("operational public_key_fingerprint mismatch")
        _timestamp(self.issued_at, "issued_at")
        if self.not_after is not None:
            _timestamp(self.not_after, "not_after")
            if self.not_after <= self.issued_at:
                raise ProvenanceModelError("not_after must be later than issued_at")

    @classmethod
    def create(
        cls,
        root: CompanyRootIdentity,
        *,
        purpose: OperationalKeyPurpose,
        public_key_der: bytes,
        issued_at: str,
        not_after: str | None = None,
    ) -> "OperationalKeyCertificate":
        if not isinstance(root, CompanyRootIdentity):
            raise TypeError("root must be a CompanyRootIdentity")
        return cls(
            certificate_id=new_id(IdKind.KEY_CERTIFICATE),
            company_id=root.company_id,
            root_identity_hash=root.content_hash,
            key_id=new_id(IdKind.PROVENANCE_KEY),
            purpose=purpose,
            algorithm=SignatureAlgorithm.ED25519,
            public_key_der_b64=public_key_b64(public_key_der),
            public_key_fingerprint=public_key_fingerprint(public_key_der),
            issued_at=issued_at,
            not_after=not_after,
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "certificate_id": self.certificate_id,
            "company_id": self.company_id,
            "root_identity_hash": self.root_identity_hash,
            "key_id": self.key_id,
            "purpose": self.purpose.value,
            "algorithm": self.algorithm.value,
            "public_key_der_b64": self.public_key_der_b64,
            "public_key_fingerprint": self.public_key_fingerprint,
            "issued_at": self.issued_at,
            "not_after": self.not_after,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class SignedOperationalKeyCertificate:
    certificate: OperationalKeyCertificate
    root_signature: DetachedSignature

    def __post_init__(self) -> None:
        if not isinstance(self.certificate, OperationalKeyCertificate):
            raise ProvenanceModelError("certificate must be an OperationalKeyCertificate")
        if not isinstance(self.root_signature, DetachedSignature):
            raise ProvenanceModelError("root_signature must be a DetachedSignature")
        if self.root_signature.signed_payload_hash != self.certificate.content_hash:
            raise ProvenanceModelError("root signature does not bind certificate content hash")

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "certificate": self.certificate.to_dict(),
                "root_signature": self.root_signature.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "certificate": self.certificate.to_dict(),
            "root_signature": self.root_signature.to_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class OperationalKeyRevocation:
    revocation_id: str
    company_id: str
    root_identity_hash: str
    revoked_key_id: str
    revoked_key_fingerprint: str
    reason: str
    effective_at: str

    def __post_init__(self) -> None:
        if not validate_id(self.revocation_id, IdKind.KEY_REVOCATION):
            raise ProvenanceModelError("revocation_id must be a KEYREV ID")
        if not validate_id(self.company_id, IdKind.COMPANY_IDENTITY):
            raise ProvenanceModelError("company_id must be a COMPANY ID")
        validate_sha256(self.root_identity_hash, "root_identity_hash")
        if not validate_id(self.revoked_key_id, IdKind.PROVENANCE_KEY):
            raise ProvenanceModelError("revoked_key_id must be a PKEY ID")
        validate_sha256(self.revoked_key_fingerprint, "revoked_key_fingerprint")
        _text(self.reason, "revocation reason", maximum=4096)
        _timestamp(self.effective_at, "effective_at")

    @classmethod
    def create(
        cls,
        root: CompanyRootIdentity,
        certificate: OperationalKeyCertificate,
        *,
        reason: str,
        effective_at: str,
    ) -> "OperationalKeyRevocation":
        if certificate.company_id != root.company_id or certificate.root_identity_hash != root.content_hash:
            raise ProvenanceModelError("certificate does not belong to root identity")
        return cls(
            revocation_id=new_id(IdKind.KEY_REVOCATION),
            company_id=root.company_id,
            root_identity_hash=root.content_hash,
            revoked_key_id=certificate.key_id,
            revoked_key_fingerprint=certificate.public_key_fingerprint,
            reason=reason,
            effective_at=effective_at,
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "revocation_id": self.revocation_id,
            "company_id": self.company_id,
            "root_identity_hash": self.root_identity_hash,
            "revoked_key_id": self.revoked_key_id,
            "revoked_key_fingerprint": self.revoked_key_fingerprint,
            "reason": self.reason,
            "effective_at": self.effective_at,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class SignedOperationalKeyRevocation:
    revocation: OperationalKeyRevocation
    root_signature: DetachedSignature

    def __post_init__(self) -> None:
        if not isinstance(self.revocation, OperationalKeyRevocation):
            raise ProvenanceModelError("revocation must be an OperationalKeyRevocation")
        if not isinstance(self.root_signature, DetachedSignature):
            raise ProvenanceModelError("root_signature must be a DetachedSignature")
        if self.root_signature.signed_payload_hash != self.revocation.content_hash:
            raise ProvenanceModelError("root signature does not bind revocation content hash")

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "revocation": self.revocation.to_dict(),
                "root_signature": self.root_signature.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "revocation": self.revocation.to_dict(),
            "root_signature": self.root_signature.to_dict(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ProvenanceRecordRef:
    record_type: ProvenanceRecordType
    record_id: str
    record_hash: str
    revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_type, ProvenanceRecordType):
            raise ProvenanceModelError("record_type must be a ProvenanceRecordType")
        if not validate_id(self.record_id, _RECORD_ID_KIND[self.record_type]):
            raise ProvenanceModelError(
                f"record_id does not match {self.record_type.value} ID contract"
            )
        validate_sha256(self.record_hash, "record_hash")
        if self.revision is not None and (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 0
        ):
            raise ProvenanceModelError("record revision must be a non-negative integer or null")

    def to_dict(self) -> dict[str, object]:
        return {
            "record_type": self.record_type.value,
            "record_id": self.record_id,
            "record_hash": self.record_hash,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ProvenanceManifestRef:
    manifest_id: str
    content_hash: str

    def __post_init__(self) -> None:
        if not validate_id(self.manifest_id, IdKind.PROVENANCE_MANIFEST):
            raise ProvenanceModelError("manifest_id must be a PROV ID")
        validate_sha256(self.content_hash, "manifest content_hash")

    def to_dict(self) -> dict[str, object]:
        return {"manifest_id": self.manifest_id, "content_hash": self.content_hash}


def _unique_record_refs(values: Iterable[ProvenanceRecordRef], field: str) -> tuple[ProvenanceRecordRef, ...]:
    refs = tuple(values)
    if len(refs) > _MAX_RECORD_REFS:
        raise ProvenanceModelError(f"{field} exceeds item limit")
    if any(not isinstance(value, ProvenanceRecordRef) for value in refs):
        raise ProvenanceModelError(f"{field} must contain ProvenanceRecordRef values")
    keys = [(value.record_type.value, value.record_id) for value in refs]
    if len(keys) != len(set(keys)):
        raise ProvenanceModelError(f"{field} contains duplicate record refs")
    return tuple(sorted(refs, key=lambda value: (value.record_type.value, value.record_id)))


def _bounded_strings(values: Iterable[str], field: str, maximum: int = _MAX_SKILL_TOOL_REFS) -> tuple[str, ...]:
    items = tuple(values)
    if len(items) > maximum or len(items) != len(set(items)):
        raise ProvenanceModelError(f"{field} is duplicate or exceeds item limit")
    for value in items:
        _text(value, field, maximum=512)
    return tuple(sorted(items))


@dataclass(frozen=True)
class ProvenanceManifest:
    manifest_id: str
    schema_version: int
    company_id: str
    root_identity_hash: str
    project_ref: ProvenanceRecordRef
    artifact_ref: ProvenanceRecordRef
    artifact_content_hash: str
    artifact_type: str
    artifact_location: str
    entity_refs: tuple[ProvenanceRecordRef, ...] = ()
    design_rule_refs: tuple[ProvenanceRecordRef, ...] = ()
    task_ref: ProvenanceRecordRef | None = None
    run_ref: ProvenanceRecordRef | None = None
    change_ref: ProvenanceRecordRef | None = None
    decision_refs: tuple[ProvenanceRecordRef, ...] = ()
    verification_refs: tuple[ProvenanceRecordRef, ...] = ()
    model_id: str | None = None
    model_hash: str | None = None
    model_profile: str | None = None
    skill_refs: tuple[str, ...] = ()
    tool_refs: tuple[str, ...] = ()
    parent_manifest_refs: tuple[ProvenanceManifestRef, ...] = ()
    created_at: str = ""

    def __post_init__(self) -> None:
        if not validate_id(self.manifest_id, IdKind.PROVENANCE_MANIFEST):
            raise ProvenanceModelError("manifest_id must be a PROV ID")
        if self.schema_version != 1:
            raise ProvenanceModelError("unsupported provenance manifest schema_version")
        if not validate_id(self.company_id, IdKind.COMPANY_IDENTITY):
            raise ProvenanceModelError("company_id must be a COMPANY ID")
        validate_sha256(self.root_identity_hash, "root_identity_hash")
        if self.project_ref.record_type != ProvenanceRecordType.PROJECT:
            raise ProvenanceModelError("project_ref must target PROJECT")
        if self.artifact_ref.record_type != ProvenanceRecordType.ARTIFACT:
            raise ProvenanceModelError("artifact_ref must target ARTIFACT")
        validate_sha256(self.artifact_content_hash, "artifact_content_hash")
        _text(self.artifact_type, "artifact_type", maximum=512)
        _text(self.artifact_location, "artifact_location", maximum=4096)
        entity_refs = _unique_record_refs(self.entity_refs, "entity_refs")
        if any(ref.record_type != ProvenanceRecordType.ENTITY for ref in entity_refs):
            raise ProvenanceModelError("entity_refs must target ENTITY")
        design_rule_refs = _unique_record_refs(self.design_rule_refs, "design_rule_refs")
        if any(ref.record_type != ProvenanceRecordType.DESIGN_RULE for ref in design_rule_refs):
            raise ProvenanceModelError("design_rule_refs must target DESIGN_RULE")
        for ref, expected, field in (
            (self.task_ref, ProvenanceRecordType.TASK, "task_ref"),
            (self.run_ref, ProvenanceRecordType.RUN, "run_ref"),
            (self.change_ref, ProvenanceRecordType.CHANGE, "change_ref"),
        ):
            if ref is not None and (
                not isinstance(ref, ProvenanceRecordRef) or ref.record_type != expected
            ):
                raise ProvenanceModelError(f"{field} must target {expected.value} or be null")
        decisions = _unique_record_refs(self.decision_refs, "decision_refs")
        if any(ref.record_type != ProvenanceRecordType.DECISION for ref in decisions):
            raise ProvenanceModelError("decision_refs must target DECISION")
        verifications = _unique_record_refs(self.verification_refs, "verification_refs")
        if any(ref.record_type != ProvenanceRecordType.VERIFICATION for ref in verifications):
            raise ProvenanceModelError("verification_refs must target VERIFICATION")
        for value, field in (
            (self.model_id, "model_id"),
            (self.model_hash, "model_hash"),
            (self.model_profile, "model_profile"),
        ):
            if value is not None:
                _text(value, field, maximum=512)
        skills = _bounded_strings(self.skill_refs, "skill_refs")
        tools = _bounded_strings(self.tool_refs, "tool_refs")
        parents = tuple(self.parent_manifest_refs)
        if len(parents) > _MAX_PARENT_MANIFESTS or any(
            not isinstance(value, ProvenanceManifestRef) for value in parents
        ):
            raise ProvenanceModelError("parent_manifest_refs are invalid or exceed item limit")
        parent_keys = [(value.manifest_id, value.content_hash) for value in parents]
        if len(parent_keys) != len(set(parent_keys)):
            raise ProvenanceModelError("parent_manifest_refs contains duplicates")
        _timestamp(self.created_at, "created_at")
        object.__setattr__(self, "entity_refs", entity_refs)
        object.__setattr__(self, "design_rule_refs", design_rule_refs)
        object.__setattr__(self, "decision_refs", decisions)
        object.__setattr__(self, "verification_refs", verifications)
        object.__setattr__(self, "skill_refs", skills)
        object.__setattr__(self, "tool_refs", tools)
        object.__setattr__(
            self,
            "parent_manifest_refs",
            tuple(sorted(parents, key=lambda value: (value.manifest_id, value.content_hash))),
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
            "company_id": self.company_id,
            "root_identity_hash": self.root_identity_hash,
            "project_ref": self.project_ref.to_dict(),
            "artifact_ref": self.artifact_ref.to_dict(),
            "artifact_content_hash": self.artifact_content_hash,
            "artifact_type": self.artifact_type,
            "artifact_location": self.artifact_location,
            "entity_refs": [value.to_dict() for value in self.entity_refs],
            "design_rule_refs": [value.to_dict() for value in self.design_rule_refs],
            "task_ref": None if self.task_ref is None else self.task_ref.to_dict(),
            "run_ref": None if self.run_ref is None else self.run_ref.to_dict(),
            "change_ref": None if self.change_ref is None else self.change_ref.to_dict(),
            "decision_refs": [value.to_dict() for value in self.decision_refs],
            "verification_refs": [value.to_dict() for value in self.verification_refs],
            "model_id": self.model_id,
            "model_hash": self.model_hash,
            "model_profile": self.model_profile,
            "skill_refs": list(self.skill_refs),
            "tool_refs": list(self.tool_refs),
            "parent_manifest_refs": [value.to_dict() for value in self.parent_manifest_refs],
            "created_at": self.created_at,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "content_hash": self.content_hash}


@dataclass(frozen=True)
class SignedProvenanceManifest:
    manifest: ProvenanceManifest
    signing_key_id: str
    signing_certificate_hash: str
    signature: DetachedSignature

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ProvenanceManifest):
            raise ProvenanceModelError("manifest must be a ProvenanceManifest")
        if not validate_id(self.signing_key_id, IdKind.PROVENANCE_KEY):
            raise ProvenanceModelError("signing_key_id must be a PKEY ID")
        validate_sha256(self.signing_certificate_hash, "signing_certificate_hash")
        if not isinstance(self.signature, DetachedSignature):
            raise ProvenanceModelError("signature must be a DetachedSignature")
        if self.signature.key_id != self.signing_key_id:
            raise ProvenanceModelError("signature key_id does not match signing_key_id")
        if self.signature.signed_payload_hash != self.manifest.content_hash:
            raise ProvenanceModelError("signature does not bind manifest content hash")

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "manifest": self.manifest.to_dict(),
                "signing_key_id": self.signing_key_id,
                "signing_certificate_hash": self.signing_certificate_hash,
                "signature": self.signature.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "signing_key_id": self.signing_key_id,
            "signing_certificate_hash": self.signing_certificate_hash,
            "signature": self.signature.to_dict(),
            "content_hash": self.content_hash,
        }
