from __future__ import annotations

from .provenance_models import (
    CompanyRootIdentity,
    DetachedSignature,
    OperationalKeyCertificate,
    OperationalKeyPurpose,
    OperationalKeyRevocation,
    ProvenanceManifest,
    ProvenanceManifestRef,
    ProvenanceModelError,
    ProvenanceRecordRef,
    ProvenanceRecordType,
    SignatureAlgorithm,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
)


class ProvenanceSerializationError(ValueError):
    pass


def _exact(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProvenanceSerializationError(f"invalid {label} fields")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProvenanceSerializationError(f"{field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ProvenanceSerializationError(f"{field} must be a string or null")
    return value


def _optional_int(value: object, field: str) -> int | None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise ProvenanceSerializationError(f"{field} must be an integer or null")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProvenanceSerializationError(f"{field} must be an array of strings")
    return tuple(value)


def parse_root_identity(payload: object) -> CompanyRootIdentity:
    raw = _exact(
        payload,
        {
            "company_id",
            "display_name",
            "root_key_id",
            "algorithm",
            "public_key_der_b64",
            "public_key_fingerprint",
            "created_at",
            "content_hash",
        },
        "Company Root identity",
    )
    try:
        value = CompanyRootIdentity(
            company_id=_string(raw["company_id"], "company_id"),
            display_name=_string(raw["display_name"], "display_name"),
            root_key_id=_string(raw["root_key_id"], "root_key_id"),
            algorithm=SignatureAlgorithm(_string(raw["algorithm"], "algorithm")),
            public_key_der_b64=_string(raw["public_key_der_b64"], "public_key_der_b64"),
            public_key_fingerprint=_string(
                raw["public_key_fingerprint"], "public_key_fingerprint"
            ),
            created_at=_string(raw["created_at"], "created_at"),
        )
    except (ProvenanceModelError, ValueError) as exc:
        raise ProvenanceSerializationError("Company Root identity validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("Company Root identity content hash mismatch")
    return value


def parse_signature(payload: object) -> DetachedSignature:
    raw = _exact(
        payload,
        {"key_id", "algorithm", "signed_payload_hash", "signature_b64", "signature_hash"},
        "detached signature",
    )
    try:
        value = DetachedSignature(
            key_id=_string(raw["key_id"], "signature key_id"),
            algorithm=SignatureAlgorithm(_string(raw["algorithm"], "signature algorithm")),
            signed_payload_hash=_string(
                raw["signed_payload_hash"], "signed_payload_hash"
            ),
            signature_b64=_string(raw["signature_b64"], "signature_b64"),
        )
    except (ProvenanceModelError, ValueError) as exc:
        raise ProvenanceSerializationError("detached signature validation failed") from exc
    if raw["signature_hash"] != value.signature_hash:
        raise ProvenanceSerializationError("detached signature hash mismatch")
    return value


def parse_certificate(payload: object) -> OperationalKeyCertificate:
    raw = _exact(
        payload,
        {
            "certificate_id",
            "company_id",
            "root_identity_hash",
            "key_id",
            "purpose",
            "algorithm",
            "public_key_der_b64",
            "public_key_fingerprint",
            "issued_at",
            "not_after",
            "content_hash",
        },
        "operational key certificate",
    )
    try:
        value = OperationalKeyCertificate(
            certificate_id=_string(raw["certificate_id"], "certificate_id"),
            company_id=_string(raw["company_id"], "company_id"),
            root_identity_hash=_string(raw["root_identity_hash"], "root_identity_hash"),
            key_id=_string(raw["key_id"], "key_id"),
            purpose=OperationalKeyPurpose(_string(raw["purpose"], "purpose")),
            algorithm=SignatureAlgorithm(_string(raw["algorithm"], "algorithm")),
            public_key_der_b64=_string(raw["public_key_der_b64"], "public_key_der_b64"),
            public_key_fingerprint=_string(
                raw["public_key_fingerprint"], "public_key_fingerprint"
            ),
            issued_at=_string(raw["issued_at"], "issued_at"),
            not_after=_optional_string(raw["not_after"], "not_after"),
        )
    except (ProvenanceModelError, ValueError) as exc:
        raise ProvenanceSerializationError("operational key certificate validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("operational key certificate content hash mismatch")
    return value


def parse_signed_certificate(payload: object) -> SignedOperationalKeyCertificate:
    raw = _exact(
        payload,
        {"certificate", "root_signature", "content_hash"},
        "signed operational key certificate",
    )
    try:
        value = SignedOperationalKeyCertificate(
            parse_certificate(raw["certificate"]),
            parse_signature(raw["root_signature"]),
        )
    except (ProvenanceModelError, ProvenanceSerializationError) as exc:
        raise ProvenanceSerializationError("signed operational certificate validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("signed operational certificate content hash mismatch")
    return value


def parse_revocation(payload: object) -> OperationalKeyRevocation:
    raw = _exact(
        payload,
        {
            "revocation_id",
            "company_id",
            "root_identity_hash",
            "revoked_key_id",
            "revoked_key_fingerprint",
            "reason",
            "effective_at",
            "content_hash",
        },
        "operational key revocation",
    )
    try:
        value = OperationalKeyRevocation(
            revocation_id=_string(raw["revocation_id"], "revocation_id"),
            company_id=_string(raw["company_id"], "company_id"),
            root_identity_hash=_string(raw["root_identity_hash"], "root_identity_hash"),
            revoked_key_id=_string(raw["revoked_key_id"], "revoked_key_id"),
            revoked_key_fingerprint=_string(
                raw["revoked_key_fingerprint"], "revoked_key_fingerprint"
            ),
            reason=_string(raw["reason"], "reason"),
            effective_at=_string(raw["effective_at"], "effective_at"),
        )
    except ProvenanceModelError as exc:
        raise ProvenanceSerializationError("operational key revocation validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("operational key revocation content hash mismatch")
    return value


def parse_signed_revocation(payload: object) -> SignedOperationalKeyRevocation:
    raw = _exact(
        payload,
        {"revocation", "root_signature", "content_hash"},
        "signed operational key revocation",
    )
    try:
        value = SignedOperationalKeyRevocation(
            parse_revocation(raw["revocation"]),
            parse_signature(raw["root_signature"]),
        )
    except (ProvenanceModelError, ProvenanceSerializationError) as exc:
        raise ProvenanceSerializationError("signed operational revocation validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("signed operational revocation content hash mismatch")
    return value


def parse_record_ref(payload: object) -> ProvenanceRecordRef:
    raw = _exact(
        payload,
        {"record_type", "record_id", "record_hash", "revision"},
        "provenance record ref",
    )
    try:
        return ProvenanceRecordRef(
            record_type=ProvenanceRecordType(_string(raw["record_type"], "record_type")),
            record_id=_string(raw["record_id"], "record_id"),
            record_hash=_string(raw["record_hash"], "record_hash"),
            revision=_optional_int(raw["revision"], "revision"),
        )
    except (ProvenanceModelError, ValueError) as exc:
        raise ProvenanceSerializationError("provenance record ref validation failed") from exc


def _record_refs(payload: object, field: str) -> tuple[ProvenanceRecordRef, ...]:
    if not isinstance(payload, list):
        raise ProvenanceSerializationError(f"{field} must be an array")
    return tuple(parse_record_ref(value) for value in payload)


def _optional_ref(payload: object, field: str) -> ProvenanceRecordRef | None:
    if payload is None:
        return None
    try:
        return parse_record_ref(payload)
    except ProvenanceSerializationError as exc:
        raise ProvenanceSerializationError(f"{field} validation failed") from exc


def parse_manifest_ref(payload: object) -> ProvenanceManifestRef:
    raw = _exact(payload, {"manifest_id", "content_hash"}, "provenance manifest ref")
    try:
        return ProvenanceManifestRef(
            _string(raw["manifest_id"], "manifest_id"),
            _string(raw["content_hash"], "content_hash"),
        )
    except ProvenanceModelError as exc:
        raise ProvenanceSerializationError("provenance manifest ref validation failed") from exc


def parse_manifest(payload: object) -> ProvenanceManifest:
    raw = _exact(
        payload,
        {
            "manifest_id",
            "schema_version",
            "company_id",
            "root_identity_hash",
            "project_ref",
            "artifact_ref",
            "artifact_content_hash",
            "artifact_type",
            "artifact_location",
            "entity_refs",
            "design_rule_refs",
            "task_ref",
            "run_ref",
            "change_ref",
            "decision_refs",
            "verification_refs",
            "model_id",
            "model_hash",
            "model_profile",
            "skill_refs",
            "tool_refs",
            "parent_manifest_refs",
            "created_at",
            "content_hash",
        },
        "provenance manifest",
    )
    schema_version = raw["schema_version"]
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ProvenanceSerializationError("schema_version must be an integer")
    parent_raw = raw["parent_manifest_refs"]
    if not isinstance(parent_raw, list):
        raise ProvenanceSerializationError("parent_manifest_refs must be an array")
    try:
        value = ProvenanceManifest(
            manifest_id=_string(raw["manifest_id"], "manifest_id"),
            schema_version=schema_version,
            company_id=_string(raw["company_id"], "company_id"),
            root_identity_hash=_string(raw["root_identity_hash"], "root_identity_hash"),
            project_ref=parse_record_ref(raw["project_ref"]),
            artifact_ref=parse_record_ref(raw["artifact_ref"]),
            artifact_content_hash=_string(
                raw["artifact_content_hash"], "artifact_content_hash"
            ),
            artifact_type=_string(raw["artifact_type"], "artifact_type"),
            artifact_location=_string(raw["artifact_location"], "artifact_location"),
            entity_refs=_record_refs(raw["entity_refs"], "entity_refs"),
            design_rule_refs=_record_refs(raw["design_rule_refs"], "design_rule_refs"),
            task_ref=_optional_ref(raw["task_ref"], "task_ref"),
            run_ref=_optional_ref(raw["run_ref"], "run_ref"),
            change_ref=_optional_ref(raw["change_ref"], "change_ref"),
            decision_refs=_record_refs(raw["decision_refs"], "decision_refs"),
            verification_refs=_record_refs(raw["verification_refs"], "verification_refs"),
            model_id=_optional_string(raw["model_id"], "model_id"),
            model_hash=_optional_string(raw["model_hash"], "model_hash"),
            model_profile=_optional_string(raw["model_profile"], "model_profile"),
            skill_refs=_string_tuple(raw["skill_refs"], "skill_refs"),
            tool_refs=_string_tuple(raw["tool_refs"], "tool_refs"),
            parent_manifest_refs=tuple(parse_manifest_ref(value) for value in parent_raw),
            created_at=_string(raw["created_at"], "created_at"),
        )
    except (ProvenanceModelError, ProvenanceSerializationError) as exc:
        raise ProvenanceSerializationError("provenance manifest validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("provenance manifest content hash mismatch")
    return value


def parse_signed_manifest(payload: object) -> SignedProvenanceManifest:
    raw = _exact(
        payload,
        {
            "manifest",
            "signing_key_id",
            "signing_certificate_hash",
            "signature",
            "content_hash",
        },
        "signed provenance manifest",
    )
    try:
        value = SignedProvenanceManifest(
            manifest=parse_manifest(raw["manifest"]),
            signing_key_id=_string(raw["signing_key_id"], "signing_key_id"),
            signing_certificate_hash=_string(
                raw["signing_certificate_hash"], "signing_certificate_hash"
            ),
            signature=parse_signature(raw["signature"]),
        )
    except (ProvenanceModelError, ProvenanceSerializationError) as exc:
        raise ProvenanceSerializationError("signed provenance manifest validation failed") from exc
    if raw["content_hash"] != value.content_hash:
        raise ProvenanceSerializationError("signed provenance manifest content hash mismatch")
    return value
