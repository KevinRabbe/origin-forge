from __future__ import annotations

import unittest

from origin_forge.media_fingerprint_models import (
    FingerprintComparison,
    FingerprintComparisonOutcome,
    FingerprintMediaClass,
    MediaFingerprintModelError,
    WatermarkMutationClass,
    WatermarkPlan,
    WatermarkRobustnessClass,
)
from origin_forge.source_text_fingerprint import (
    canonicalize_source_text,
    fingerprint_source_text,
    source_text_fingerprint_algorithm,
)


HASH_A = "sha256:" + "a" * 64


class SourceTextFingerprintTests(unittest.TestCase):
    def test_line_ending_variants_have_same_canonical_fingerprint_but_different_source_hash(self) -> None:
        lf = fingerprint_source_text(source_ref="ART-source-lf", source=b"alpha\nbeta\n")
        crlf = fingerprint_source_text(source_ref="ART-source-crlf", source=b"alpha\r\nbeta\r\n")
        self.assertNotEqual(lf.source_hash, crlf.source_hash)
        self.assertEqual(lf.canonical_content_hash, crlf.canonical_content_hash)
        comparison = FingerprintComparison.compare(lf, crlf)
        self.assertIs(comparison.outcome, FingerprintComparisonOutcome.EXACT_MATCH)
        self.assertFalse(comparison.to_dict()["authorship_proven"])
        self.assertFalse(comparison.to_dict()["cryptographic_provenance_verified"])

    def test_whitespace_is_not_semantically_folded(self) -> None:
        left = fingerprint_source_text(source_ref="ART-left", source=b"x = 1\n")
        right = fingerprint_source_text(source_ref="ART-right", source=b"x  = 1\n")
        comparison = FingerprintComparison.compare(left, right)
        self.assertIs(comparison.outcome, FingerprintComparisonOutcome.DIFFERENT)

    def test_source_text_rejects_non_utf8_nul_controls_empty_and_oversize(self) -> None:
        for data in (b"\xff", b"a\x00b", b"a\x01b", b""):
            with self.assertRaises(MediaFingerprintModelError):
                canonicalize_source_text(data)
        with self.assertRaisesRegex(MediaFingerprintModelError, "byte size"):
            canonicalize_source_text(b"x" * (8 * 1024 * 1024 + 1))

    def test_canonicalizer_only_normalizes_line_endings(self) -> None:
        self.assertEqual(
            canonicalize_source_text(b" a\r\nb \rc\n"),
            b" a\nb \nc\n",
        )
        algorithm = source_text_fingerprint_algorithm()
        self.assertEqual(algorithm.algorithm_id, "source-text-exact")
        self.assertEqual(algorithm.version, "1")

    def test_fingerprint_declares_non_authoritative_semantics(self) -> None:
        value = fingerprint_source_text(source_ref="ART-source", source=b"hello\n")
        payload = value.to_dict()
        self.assertIs(value.media_class, FingerprintMediaClass.SOURCE_TEXT)
        self.assertFalse(payload["cryptographic_provenance_verified"])
        self.assertFalse(payload["production_task_verified"])
        self.assertFalse(payload["canonical_asset_adopted"])
        self.assertFalse(value.structural_summary["semantic_normalization"])

    def test_different_algorithm_identity_is_incomparable_even_with_same_content_hash(self) -> None:
        left = fingerprint_source_text(source_ref="ART-left", source=b"same\n")
        algorithm = source_text_fingerprint_algorithm()
        changed = type(algorithm)(
            algorithm_id="source-text-other",
            version=algorithm.version,
            canonicalizer_id=algorithm.canonicalizer_id,
            canonicalizer_fingerprint=algorithm.canonicalizer_fingerprint,
        )
        right = type(left).create(
            media_class=left.media_class,
            source_ref="ART-right",
            source_hash=left.source_hash,
            algorithm=changed,
            canonical_content_hash=left.canonical_content_hash,
            structural_summary=left.structural_summary,
        )
        comparison = FingerprintComparison.compare(left, right)
        self.assertIs(comparison.outcome, FingerprintComparisonOutcome.INCOMPARABLE)
        self.assertFalse(comparison.comparable_algorithm)

    def test_watermark_plan_is_derivative_intent_only_and_never_trust_root(self) -> None:
        plan = WatermarkPlan.create(
            media_class=FingerprintMediaClass.RASTER_IMAGE,
            parent_ref="ART-parent",
            parent_hash=HASH_A,
            mark_payload=b"origin-forge-mark",
            embedder_id="png-fragile-content",
            embedder_version="1",
            embedder_fingerprint=HASH_A,
            detector_id="png-fragile-content-detector",
            detector_version="1",
            detector_fingerprint=HASH_A,
            robustness_class=WatermarkRobustnessClass.FRAGILE_CONTENT,
            mutation_class=WatermarkMutationClass.CONTENT_MUTATION,
        )
        payload = plan.to_dict()
        self.assertFalse(payload["robust_provenance_claim"])
        self.assertFalse(payload["canonical_asset_mutation_authorized"])
        self.assertFalse(payload["production_task_verified"])


if __name__ == "__main__":
    unittest.main()
