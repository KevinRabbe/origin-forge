from __future__ import annotations

import hashlib

from .media_fingerprint_models import (
    FingerprintAlgorithm,
    FingerprintMediaClass,
    MediaFingerprint,
    MediaFingerprintModelError,
)
from .runtime_observation_models import content_hash


_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_CANONICALIZER_ID = "origin-forge-source-text-lf"
_ALGORITHM_ID = "source-text-exact"
_VERSION = "1"
_CANONICALIZER_FINGERPRINT = content_hash(
    {
        "canonicalizer": _CANONICALIZER_ID,
        "version": _VERSION,
        "input": "strict UTF-8 bytes",
        "line_endings": "CRLF/CR->LF",
        "reject_nul": True,
        "reject_controls": "C0 except TAB/LF/CR; DEL",
        "whitespace_folding": False,
        "trimming": False,
        "max_source_bytes": _MAX_SOURCE_BYTES,
    }
)


def source_text_fingerprint_algorithm() -> FingerprintAlgorithm:
    return FingerprintAlgorithm(
        algorithm_id=_ALGORITHM_ID,
        version=_VERSION,
        canonicalizer_id=_CANONICALIZER_ID,
        canonicalizer_fingerprint=_CANONICALIZER_FINGERPRINT,
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonicalize_source_text(source: bytes) -> bytes:
    if not isinstance(source, bytes):
        raise TypeError("source must be bytes")
    if not source or len(source) > _MAX_SOURCE_BYTES:
        raise MediaFingerprintModelError("source text byte size is outside bounds")
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MediaFingerprintModelError("source text must be strict UTF-8") from exc
    for character in text:
        codepoint = ord(character)
        if codepoint == 0:
            raise MediaFingerprintModelError("source text may not contain NUL")
        if (codepoint < 32 and character not in ("\t", "\n", "\r")) or codepoint == 127:
            raise MediaFingerprintModelError("source text contains forbidden control characters")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def fingerprint_source_text(*, source_ref: str, source: bytes) -> MediaFingerprint:
    canonical = canonicalize_source_text(source)
    line_count = canonical.count(b"\n") + (0 if canonical.endswith(b"\n") else 1)
    return MediaFingerprint.create(
        media_class=FingerprintMediaClass.SOURCE_TEXT,
        source_ref=source_ref,
        source_hash=_sha256(source),
        algorithm=source_text_fingerprint_algorithm(),
        canonical_content_hash=_sha256(canonical),
        structural_summary={
            "canonical_bytes": len(canonical),
            "line_count": line_count,
            "normalized_line_endings": True,
            "semantic_normalization": False,
        },
    )
