from __future__ import annotations

from .programmatic_context_interpreter import ContextExecutionResult
from .programmatic_context_models import (
    ContextExecutionTrace,
    ContextOperationCatalog,
    ContextPackage,
    ContextReplayClass,
)


class ContextReplayVerificationError(RuntimeError):
    pass


def _assert_trace_package_binding(
    trace: ContextExecutionTrace,
    package: ContextPackage,
    *,
    label: str,
) -> None:
    if (
        trace.request_id != package.request_id
        or trace.request_hash != package.request_hash
        or trace.program_id != package.program_id
        or trace.program_hash != package.program_hash
        or trace.catalog_id != package.catalog_id
        or trace.catalog_hash != package.catalog_hash
        or trace.package_id != package.package_id
        or trace.package_hash != package.content_hash
    ):
        raise ContextReplayVerificationError(
            f"{label} trace/package binding is inconsistent"
        )


def verify_deterministic_replay(
    *,
    catalog: ContextOperationCatalog,
    original_trace: ContextExecutionTrace,
    original_package: ContextPackage,
    replay: ContextExecutionResult,
) -> None:
    """Verify exact replay evidence without treating replay as production authority."""

    if not isinstance(catalog, ContextOperationCatalog):
        raise TypeError("catalog must be a ContextOperationCatalog")
    if not isinstance(original_trace, ContextExecutionTrace):
        raise TypeError("original_trace must be a ContextExecutionTrace")
    if not isinstance(original_package, ContextPackage):
        raise TypeError("original_package must be a ContextPackage")
    if not isinstance(replay, ContextExecutionResult):
        raise TypeError("replay must be a ContextExecutionResult")

    _assert_trace_package_binding(original_trace, original_package, label="original")
    _assert_trace_package_binding(replay.trace, replay.package, label="replay")

    if (
        original_trace.catalog_id != catalog.catalog_id
        or original_trace.catalog_hash != catalog.content_hash
        or replay.trace.catalog_id != catalog.catalog_id
        or replay.trace.catalog_hash != catalog.content_hash
    ):
        raise ContextReplayVerificationError(
            "replay evidence does not bind the exact operation catalog"
        )

    identity_fields = (
        "request_id",
        "request_hash",
        "program_id",
        "program_hash",
        "catalog_id",
        "catalog_hash",
    )
    for field in identity_fields:
        if getattr(original_trace, field) != getattr(replay.trace, field):
            raise ContextReplayVerificationError(
                f"replay changed frozen execution identity: {field}"
            )

    if len(original_trace.steps) != len(replay.trace.steps):
        raise ContextReplayVerificationError("replay changed step count")

    for original_step, replay_step in zip(
        original_trace.steps,
        replay.trace.steps,
        strict=True,
    ):
        if original_step.index != replay_step.index:
            raise ContextReplayVerificationError("replay changed step index")
        descriptor = catalog.descriptor(
            original_step.operation_id,
            original_step.operation_version,
        )
        if descriptor.replay_class is not ContextReplayClass.DETERMINISTIC:
            raise ContextReplayVerificationError(
                f"exact replay is not authorized for {descriptor.operation_id}@{descriptor.version}"
            )
        if original_step.adapter_fingerprint != descriptor.adapter_fingerprint:
            raise ContextReplayVerificationError(
                "original trace adapter fingerprint disagrees with catalog"
            )
        if replay_step.adapter_fingerprint != descriptor.adapter_fingerprint:
            raise ContextReplayVerificationError(
                "replay adapter fingerprint disagrees with catalog"
            )
        original_signature = (
            original_step.binding,
            original_step.operation_id,
            original_step.operation_version,
            original_step.adapter_fingerprint,
            original_step.input_hash,
            original_step.output_hash,
            original_step.output_bytes,
        )
        replay_signature = (
            replay_step.binding,
            replay_step.operation_id,
            replay_step.operation_version,
            replay_step.adapter_fingerprint,
            replay_step.input_hash,
            replay_step.output_hash,
            replay_step.output_bytes,
        )
        if replay_signature != original_signature:
            raise ContextReplayVerificationError(
                f"deterministic replay drifted at step {original_step.index}"
            )

    if replay.trace.total_result_bytes != original_trace.total_result_bytes:
        raise ContextReplayVerificationError("replay changed aggregate result bytes")
    if replay.package.values_json != original_package.values_json:
        raise ContextReplayVerificationError("replay changed final context package bytes")
