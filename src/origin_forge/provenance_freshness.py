from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from .path_policy import portable_relative_path
from .provenance_models import ProvenanceRecordRef, SignedProvenanceManifest
from .provenance_records import ProvenanceRecordResolver
from .runtime import OriginForgeRuntime


class ProvenanceFreshnessFinding(StrEnum):
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_INVALID_PATH = "ARTIFACT_INVALID_PATH"
    ARTIFACT_TOO_LARGE = "ARTIFACT_TOO_LARGE"
    ARTIFACT_DRIFT = "ARTIFACT_DRIFT"
    RECORD_MISSING = "RECORD_MISSING"
    RECORD_DRIFT = "RECORD_DRIFT"


@dataclass(frozen=True)
class RecordFreshnessFinding:
    code: ProvenanceFreshnessFinding
    record_type: str
    record_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "record_type": self.record_type,
            "record_id": self.record_id,
        }


@dataclass(frozen=True)
class ProvenanceFreshnessResult:
    artifact_hash_matches: bool
    record_refs_current: bool
    findings: tuple[RecordFreshnessFinding, ...]

    @property
    def current(self) -> bool:
        return self.artifact_hash_matches and self.record_refs_current and not self.findings

    def to_dict(self) -> dict[str, object]:
        return {
            "current": self.current,
            "artifact_hash_matches": self.artifact_hash_matches,
            "record_refs_current": self.record_refs_current,
            "findings": [value.to_dict() for value in self.findings],
            "historical_signed_manifest_changed": False,
            "canonical_project_state_changed": False,
        }


class ProvenanceFreshnessVerifier:
    """Compare a historical signed claim with current local Origin Forge state."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        max_artifact_bytes: int = 512 * 1024 * 1024,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(max_artifact_bytes, int) or isinstance(max_artifact_bytes, bool) or max_artifact_bytes <= 0:
            raise ValueError("max_artifact_bytes must be a positive integer")
        self.runtime = runtime
        self.records = ProvenanceRecordResolver(runtime)
        self.max_artifact_bytes = max_artifact_bytes

    @staticmethod
    def _all_refs(manifest) -> tuple[ProvenanceRecordRef, ...]:
        refs = [manifest.project_ref, manifest.artifact_ref]
        refs.extend(manifest.entity_refs)
        refs.extend(manifest.design_rule_refs)
        for value in (manifest.task_ref, manifest.run_ref, manifest.change_ref):
            if value is not None:
                refs.append(value)
        refs.extend(manifest.decision_refs)
        refs.extend(manifest.verification_refs)
        return tuple(refs)

    def _artifact_status(
        self, signed: SignedProvenanceManifest
    ) -> tuple[bool, RecordFreshnessFinding | None]:
        manifest = signed.manifest
        try:
            relative = portable_relative_path(manifest.artifact_location)
        except ValueError:
            return False, RecordFreshnessFinding(
                ProvenanceFreshnessFinding.ARTIFACT_INVALID_PATH,
                "ARTIFACT_FILE",
                manifest.artifact_ref.record_id,
            )
        path = self.runtime.project_root / relative
        current = self.runtime.project_root.resolve()
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False, RecordFreshnessFinding(
                    ProvenanceFreshnessFinding.ARTIFACT_INVALID_PATH,
                    "ARTIFACT_FILE",
                    manifest.artifact_ref.record_id,
                )
        if not path.exists():
            return False, RecordFreshnessFinding(
                ProvenanceFreshnessFinding.ARTIFACT_MISSING,
                "ARTIFACT_FILE",
                manifest.artifact_ref.record_id,
            )
        if not path.is_file():
            return False, RecordFreshnessFinding(
                ProvenanceFreshnessFinding.ARTIFACT_INVALID_PATH,
                "ARTIFACT_FILE",
                manifest.artifact_ref.record_id,
            )
        size = path.stat().st_size
        if size > self.max_artifact_bytes:
            return False, RecordFreshnessFinding(
                ProvenanceFreshnessFinding.ARTIFACT_TOO_LARGE,
                "ARTIFACT_FILE",
                manifest.artifact_ref.record_id,
            )
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_artifact_bytes:
                    return False, RecordFreshnessFinding(
                        ProvenanceFreshnessFinding.ARTIFACT_TOO_LARGE,
                        "ARTIFACT_FILE",
                        manifest.artifact_ref.record_id,
                    )
                digest.update(chunk)
        current_hash = "sha256:" + digest.hexdigest()
        if current_hash != manifest.artifact_content_hash:
            return False, RecordFreshnessFinding(
                ProvenanceFreshnessFinding.ARTIFACT_DRIFT,
                "ARTIFACT_FILE",
                manifest.artifact_ref.record_id,
            )
        return True, None

    def verify(self, signed: SignedProvenanceManifest) -> ProvenanceFreshnessResult:
        if not isinstance(signed, SignedProvenanceManifest):
            raise TypeError("signed must be a SignedProvenanceManifest")
        findings: list[RecordFreshnessFinding] = []
        artifact_matches, artifact_finding = self._artifact_status(signed)
        if artifact_finding is not None:
            findings.append(artifact_finding)

        record_refs_current = True
        for ref in self._all_refs(signed.manifest):
            try:
                current = self.records.resolve(ref.record_type, ref.record_id)
            except KeyError:
                record_refs_current = False
                findings.append(
                    RecordFreshnessFinding(
                        ProvenanceFreshnessFinding.RECORD_MISSING,
                        ref.record_type.value,
                        ref.record_id,
                    )
                )
                continue
            if current != ref:
                record_refs_current = False
                findings.append(
                    RecordFreshnessFinding(
                        ProvenanceFreshnessFinding.RECORD_DRIFT,
                        ref.record_type.value,
                        ref.record_id,
                    )
                )

        ordered = tuple(
            sorted(
                findings,
                key=lambda value: (value.code.value, value.record_type, value.record_id),
            )
        )
        return ProvenanceFreshnessResult(
            artifact_hash_matches=artifact_matches,
            record_refs_current=record_refs_current,
            findings=ordered,
        )
