from __future__ import annotations

from .media_fingerprint_models import (
    FingerprintComparison,
    FingerprintComparisonOutcome,
    MediaFingerprint,
    MediaFingerprintModelError,
)


def validate_fingerprint_comparison(
    comparison: FingerprintComparison,
    left: MediaFingerprint,
    right: MediaFingerprint,
) -> None:
    if not isinstance(comparison, FingerprintComparison):
        raise TypeError("comparison must be a FingerprintComparison")
    if not isinstance(left, MediaFingerprint) or not isinstance(right, MediaFingerprint):
        raise TypeError("left/right must be MediaFingerprint values")
    if (
        comparison.left_fingerprint_id != left.fingerprint_id
        or comparison.left_fingerprint_hash != left.content_hash
        or comparison.right_fingerprint_id != right.fingerprint_id
        or comparison.right_fingerprint_hash != right.content_hash
    ):
        raise MediaFingerprintModelError(
            "fingerprint comparison does not bind exact left/right evidence"
        )
    comparable = (
        left.media_class is right.media_class
        and left.algorithm.identity == right.algorithm.identity
    )
    if not comparable:
        expected = FingerprintComparisonOutcome.INCOMPARABLE
    elif left.canonical_content_hash == right.canonical_content_hash:
        expected = FingerprintComparisonOutcome.EXACT_MATCH
    else:
        expected = FingerprintComparisonOutcome.DIFFERENT
    if comparison.comparable_algorithm != comparable or comparison.outcome is not expected:
        raise MediaFingerprintModelError(
            "fingerprint comparison classification is inconsistent with bound evidence"
        )
