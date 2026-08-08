from __future__ import annotations


# RFC 8410 SubjectPublicKeyInfo for Ed25519 is exactly:
# SEQUENCE(42) { SEQUENCE { OID 1.3.101.112 }, BIT STRING(32-byte key) }
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_ED25519_SPKI_BYTES = 44


class ProvenanceKeyFormatError(ValueError):
    pass


def require_ed25519_public_key_der(value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise ProvenanceKeyFormatError("public key DER must be bytes")
    if len(value) != _ED25519_SPKI_BYTES or not value.startswith(_ED25519_SPKI_PREFIX):
        raise ProvenanceKeyFormatError(
            "public key DER is not canonical Ed25519 SubjectPublicKeyInfo"
        )
    return value
