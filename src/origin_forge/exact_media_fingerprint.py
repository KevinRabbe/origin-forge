from __future__ import annotations

import hashlib

from .audio_wav import decode_pcm16_wav
from .blockbench_glb import inspect_glb
from .image_png import decode_truecolor8_png, inspect_truecolor8_png
from .media_fingerprint_models import (
    FingerprintAlgorithm,
    FingerprintMediaClass,
    MediaFingerprint,
)
from .runtime_observation_models import content_hash


_VERSION = "1"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


_RASTER_CANONICALIZER_ID = "origin-forge-rgba8-raster"
_RASTER_CANONICALIZER_FINGERPRINT = content_hash(
    {
        "canonicalizer": _RASTER_CANONICALIZER_ID,
        "version": _VERSION,
        "validator": "origin_forge.image_png.decode_truecolor8_png",
        "accepted_png": "8-bit RGB/RGBA non-interlaced truecolor",
        "rgb_alpha": 255,
        "canonical_content": "width,height,rgba8-pixel-bytes",
        "perceptual_similarity": False,
    }
)

_PCM_CANONICALIZER_ID = "origin-forge-pcm16-audio"
_PCM_CANONICALIZER_FINGERPRINT = content_hash(
    {
        "canonicalizer": _PCM_CANONICALIZER_ID,
        "version": _VERSION,
        "validator": "origin_forge.audio_wav.decode_pcm16_wav",
        "accepted_wav": "RIFF/WAVE signed PCM16 mono/stereo",
        "canonical_content": "channels,sample-rate,frame-count,interleaved-pcm16",
        "ancillary_chunks": "ignored-for-canonical-content",
        "acoustic_similarity": False,
    }
)

_GLB_CANONICALIZER_ID = "origin-forge-glb-v2-validated-bytes"
_GLB_CANONICALIZER_FINGERPRINT = content_hash(
    {
        "canonicalizer": _GLB_CANONICALIZER_ID,
        "version": _VERSION,
        "validator": "origin_forge.blockbench_glb.inspect_glb",
        "accepted_glb": "Phase-20 self-contained GLB v2 contract",
        "canonical_content": "exact-validated-glb-bytes",
        "structural_summary": True,
        "export_invariance": False,
        "mesh_reindex_invariance": False,
    }
)


def raster_fingerprint_algorithm() -> FingerprintAlgorithm:
    return FingerprintAlgorithm(
        algorithm_id="raster-rgba8-exact",
        version=_VERSION,
        canonicalizer_id=_RASTER_CANONICALIZER_ID,
        canonicalizer_fingerprint=_RASTER_CANONICALIZER_FINGERPRINT,
    )


def pcm16_fingerprint_algorithm() -> FingerprintAlgorithm:
    return FingerprintAlgorithm(
        algorithm_id="pcm16-audio-exact",
        version=_VERSION,
        canonicalizer_id=_PCM_CANONICALIZER_ID,
        canonicalizer_fingerprint=_PCM_CANONICALIZER_FINGERPRINT,
    )


def glb_fingerprint_algorithm() -> FingerprintAlgorithm:
    return FingerprintAlgorithm(
        algorithm_id="glb-v2-validated-exact",
        version=_VERSION,
        canonicalizer_id=_GLB_CANONICALIZER_ID,
        canonicalizer_fingerprint=_GLB_CANONICALIZER_FINGERPRINT,
    )


def fingerprint_raster_png(*, source_ref: str, source: bytes) -> MediaFingerprint:
    decoded = decode_truecolor8_png(source)
    inspection = inspect_truecolor8_png(source)
    plane = decoded.plane
    canonical_hash = content_hash(
        {
            "width": plane.width,
            "height": plane.height,
            "rgba_hash": plane.rgba_hash,
        }
    )
    return MediaFingerprint.create(
        media_class=FingerprintMediaClass.RASTER_IMAGE,
        source_ref=source_ref,
        source_hash=_sha256(source),
        algorithm=raster_fingerprint_algorithm(),
        canonical_content_hash=canonical_hash,
        structural_summary={
            "width": plane.width,
            "height": plane.height,
            "rgba_hash": plane.rgba_hash,
            "source_color_type": decoded.source_color_type,
            "nontransparent_pixels": inspection.nontransparent_pixels,
            "transparent_pixels": inspection.transparent_pixels,
            "opaque_pixels": inspection.opaque_pixels,
            "perceptual_similarity": False,
        },
    )


def fingerprint_pcm16_wav(*, source_ref: str, source: bytes) -> MediaFingerprint:
    decoded = decode_pcm16_wav(source)
    inspection = decoded.inspection
    canonical_hash = content_hash(
        {
            "channels": inspection.channels,
            "sample_rate": inspection.sample_rate,
            "frame_count": inspection.frame_count,
            "pcm_hash": inspection.pcm_hash,
        }
    )
    return MediaFingerprint.create(
        media_class=FingerprintMediaClass.PCM_AUDIO,
        source_ref=source_ref,
        source_hash=inspection.content_hash,
        algorithm=pcm16_fingerprint_algorithm(),
        canonical_content_hash=canonical_hash,
        structural_summary={
            "channels": inspection.channels,
            "sample_rate": inspection.sample_rate,
            "frame_count": inspection.frame_count,
            "sample_count": inspection.sample_count,
            "duration_ns": inspection.duration_ns,
            "pcm_hash": inspection.pcm_hash,
            "ancillary_chunk_ids": list(inspection.ancillary_chunk_ids),
            "acoustic_similarity": False,
        },
    )


def fingerprint_glb(*, source_ref: str, source: bytes) -> MediaFingerprint:
    inspection = inspect_glb(source)
    # The existing Phase-20 validator does not expose normalized geometry/buffer
    # component hashes. Preserve its exact validated-byte identity instead of
    # claiming an invariance that the validator cannot prove.
    return MediaFingerprint.create(
        media_class=FingerprintMediaClass.MODEL3D_GLB,
        source_ref=source_ref,
        source_hash=inspection.content_hash,
        algorithm=glb_fingerprint_algorithm(),
        canonical_content_hash=inspection.content_hash,
        structural_summary={
            "byte_count": inspection.byte_count,
            "node_count": inspection.node_count,
            "mesh_count": inspection.mesh_count,
            "material_count": inspection.material_count,
            "texture_count": inspection.texture_count,
            "animation_count": inspection.animation_count,
            "scene_count": inspection.scene_count,
            "embedded_bin_bytes": inspection.embedded_bin_bytes,
            "export_invariance": False,
            "mesh_reindex_invariance": False,
        },
    )
