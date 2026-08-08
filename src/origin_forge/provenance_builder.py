from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .ids import IdKind, new_id, validate_id
from .path_policy import portable_relative_path
from .provenance_models import (
    CompanyRootIdentity,
    ProvenanceManifest,
    ProvenanceManifestRef,
    ProvenanceRecordRef,
    ProvenanceRecordType,
)
from .provenance_records import ProvenanceRecordError, ProvenanceRecordResolver
from .provenance_store import ProvenanceStore
from .runtime import OriginForgeRuntime
from .service import utc_now


class ProvenanceBuildError(RuntimeError):
    pass


class ProvenanceManifestBuilder:
    """Deterministically derive a manifest from existing Origin Forge truth."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        root: CompanyRootIdentity,
        *,
        store: ProvenanceStore | None = None,
        max_artifact_bytes: int = 512 * 1024 * 1024,
        max_verifications: int = 128,
        max_entities: int = 128,
        max_design_rules: int = 256,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        if not isinstance(root, CompanyRootIdentity):
            raise TypeError("root must be a CompanyRootIdentity")
        for value, name, maximum in (
            (max_artifact_bytes, "max_artifact_bytes", 8 * 1024 * 1024 * 1024),
            (max_verifications, "max_verifications", 4096),
            (max_entities, "max_entities", 4096),
            (max_design_rules, "max_design_rules", 4096),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        self.runtime = runtime
        self.root = root
        self.store = store
        if store is not None:
            if not isinstance(store, ProvenanceStore):
                raise TypeError("store must be a ProvenanceStore")
            if store.runtime.project_root != runtime.project_root:
                raise ValueError("provenance store and runtime must belong to the same project")
            try:
                trusted = store.load_root(root.company_id)
            except KeyError as exc:
                raise ProvenanceBuildError(
                    "Company Root identity must be present in the project provenance store"
                ) from exc
            if trusted != root:
                raise ProvenanceBuildError("project provenance store Root identity mismatch")
        self.records = ProvenanceRecordResolver(runtime)
        self.max_artifact_bytes = max_artifact_bytes
        self.max_verifications = max_verifications
        self.max_entities = max_entities
        self.max_design_rules = max_design_rules

    def _local_artifact_hash(self, path_or_uri: str) -> tuple[str, str]:
        parsed = urlparse(path_or_uri)
        if parsed.scheme in {"http", "https"}:
            raise ProvenanceBuildError(
                "Phase 18 v0 signs only locally revalidated Artifact bytes"
            )
        path = Path(path_or_uri)
        if not path.is_absolute():
            path = self.runtime.project_root / path
        if path.is_symlink():
            raise ProvenanceBuildError("Artifact path may not be a symlink")
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(self.runtime.project_root.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProvenanceBuildError(
                "Artifact path is missing or escapes the project root"
            ) from exc
        portable = portable_relative_path(relative.as_posix()).as_posix()
        if not resolved.is_file():
            raise ProvenanceBuildError("Artifact provenance requires a regular file")
        size = resolved.stat().st_size
        if size > self.max_artifact_bytes:
            raise ProvenanceBuildError(
                f"Artifact exceeds signing byte limit ({size} > {self.max_artifact_bytes})"
            )
        digest = hashlib.sha256()
        total = 0
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_artifact_bytes:
                    raise ProvenanceBuildError("Artifact grew beyond signing byte limit while hashing")
                digest.update(chunk)
        return "sha256:" + digest.hexdigest(), portable

    def _lineage_ids(self, artifact: dict[str, object]) -> tuple[str | None, str | None, str | None, tuple[str, ...]]:
        change_id = artifact["change_id"]
        creating_run_id = artifact["created_by_run_id"]
        task_id: str | None = None
        decision_ids: list[str] = []
        change_run_id: str | None = None
        if change_id is not None:
            if not isinstance(change_id, str) or not validate_id(change_id, IdKind.CHANGE):
                raise ProvenanceBuildError("Artifact change_id is invalid")
            change = self.records.normalized_snapshot(
                ProvenanceRecordType.CHANGE, change_id
            )
            task_id = change["task_id"]
            change_run_id = change["run_id"]
            decision_id = change["decision_id"]
            if decision_id is not None:
                decision_ids.append(decision_id)

        run_id = creating_run_id or change_run_id
        if run_id is not None:
            if not isinstance(run_id, str) or not validate_id(run_id, IdKind.RUN):
                raise ProvenanceBuildError("Artifact creating Run ID is invalid")
            run = self.records.normalized_snapshot(ProvenanceRecordType.RUN, run_id)
            run_task_id = run["task_id"]
            if task_id is not None and run_task_id != task_id:
                raise ProvenanceBuildError(
                    "Artifact Change Task and creating Run Task do not match"
                )
            task_id = run_task_id

        return change_id, run_id, task_id, tuple(sorted(set(decision_ids)))

    def _verification_refs(
        self,
        *,
        artifact_id: str,
        task_id: str | None,
        run_id: str | None,
        change_id: str | None,
    ) -> tuple[ProvenanceRecordRef, ...]:
        targets = {("ARTIFACT", artifact_id)}
        if task_id is not None:
            targets.add(("TASK", task_id))
        if run_id is not None:
            targets.add(("RUN", run_id))
        if change_id is not None:
            targets.add(("CHANGE", change_id))
        with self.runtime.store.session() as conn:
            rows = list(
                conn.execute(
                    "SELECT id, target_type, target_id FROM verifications ORDER BY created_at, id"
                )
            )
        ids = [
            row["id"]
            for row in rows
            if (str(row["target_type"]).upper(), row["target_id"]) in targets
        ]
        if len(ids) > self.max_verifications:
            raise ProvenanceBuildError(
                f"provenance Verification count exceeds limit ({len(ids)} > {self.max_verifications})"
            )
        refs: list[ProvenanceRecordRef] = []
        for verification_id in ids:
            try:
                refs.append(
                    self.records.resolve(
                        ProvenanceRecordType.VERIFICATION, verification_id
                    )
                )
            except KeyError as exc:
                raise ProvenanceBuildError(
                    "selected Verification is not project-owned"
                ) from exc
        return tuple(refs)

    def _entity_and_rule_refs(
        self, artifact_id: str
    ) -> tuple[tuple[ProvenanceRecordRef, ...], tuple[ProvenanceRecordRef, ...]]:
        project_id = self.records.project_id
        with self.runtime.store.session() as conn:
            entity_rows = list(
                conn.execute(
                    """SELECT e.id FROM entity_bindings b
                       JOIN entities e ON e.id = b.entity_id AND e.project_id = b.project_id
                       WHERE b.project_id = ? AND b.status = 'ACTIVE'
                         AND b.binding_type = 'ARTIFACT' AND b.target_ref = ?
                         AND e.status != 'RETIRED'
                       ORDER BY e.kind, e.name, e.id""",
                    (project_id, artifact_id),
                )
            )
            entity_ids = tuple(row["id"] for row in entity_rows)
            if len(entity_ids) > self.max_entities:
                raise ProvenanceBuildError(
                    f"provenance Entity count exceeds limit ({len(entity_ids)} > {self.max_entities})"
                )
            visited = set(entity_ids)
            rule_ids: list[str] = []
            for row in conn.execute(
                """SELECT id, scope_entity_ids_json FROM design_rules
                   WHERE project_id = ? AND status = 'ACTIVE'
                   ORDER BY category, title, id""",
                (project_id,),
            ):
                try:
                    scopes = json.loads(row["scope_entity_ids_json"])
                except json.JSONDecodeError as exc:
                    raise ProvenanceBuildError("stored Design Rule scopes are invalid JSON") from exc
                if not isinstance(scopes, list) or any(not isinstance(value, str) for value in scopes):
                    raise ProvenanceBuildError("stored Design Rule scopes are invalid")
                if scopes and not visited.intersection(scopes):
                    continue
                rule_ids.append(row["id"])
                if len(rule_ids) > self.max_design_rules:
                    raise ProvenanceBuildError(
                        f"provenance Design Rule count exceeds limit ({len(rule_ids)} > {self.max_design_rules})"
                    )

        entity_refs = tuple(
            self.records.resolve(ProvenanceRecordType.ENTITY, entity_id)
            for entity_id in entity_ids
        )
        rule_refs = tuple(
            self.records.resolve(ProvenanceRecordType.DESIGN_RULE, rule_id)
            for rule_id in rule_ids
        )
        return entity_refs, rule_refs

    def _parent_refs(
        self, refs: Iterable[ProvenanceManifestRef]
    ) -> tuple[ProvenanceManifestRef, ...]:
        values = tuple(refs)
        if self.store is None:
            return values
        for ref in values:
            stored = self.store.load_manifest(ref.manifest_id)
            if stored.manifest.content_hash != ref.content_hash:
                raise ProvenanceBuildError("parent provenance manifest hash mismatch")
            if (
                stored.manifest.company_id != self.root.company_id
                or stored.manifest.root_identity_hash != self.root.content_hash
            ):
                raise ProvenanceBuildError("parent provenance manifest trust identity mismatch")
        return values

    def build(
        self,
        artifact_id: str,
        *,
        parent_manifest_refs: Iterable[ProvenanceManifestRef] = (),
        created_at: str | None = None,
    ) -> ProvenanceManifest:
        if not validate_id(artifact_id, IdKind.ARTIFACT):
            raise ValueError("artifact_id must be an ART ID")
        try:
            artifact = self.records.normalized_snapshot(
                ProvenanceRecordType.ARTIFACT, artifact_id
            )
        except (KeyError, ProvenanceRecordError) as exc:
            raise ProvenanceBuildError("Artifact is unavailable in this project") from exc
        stored_hash = artifact["content_hash"]
        if not isinstance(stored_hash, str):
            raise ProvenanceBuildError("Artifact has no recorded content hash")
        current_hash, portable_location = self._local_artifact_hash(
            str(artifact["path_or_uri"])
        )
        if current_hash != stored_hash:
            raise ProvenanceBuildError(
                "current Artifact bytes do not match recorded Artifact content hash"
            )

        change_id, run_id, task_id, decision_ids = self._lineage_ids(artifact)
        project_ref = self.records.resolve(
            ProvenanceRecordType.PROJECT, self.records.project_id
        )
        artifact_ref = self.records.resolve(ProvenanceRecordType.ARTIFACT, artifact_id)
        change_ref = (
            None
            if change_id is None
            else self.records.resolve(ProvenanceRecordType.CHANGE, change_id)
        )
        run_ref = (
            None
            if run_id is None
            else self.records.resolve(ProvenanceRecordType.RUN, run_id)
        )
        task_ref = (
            None
            if task_id is None
            else self.records.resolve(ProvenanceRecordType.TASK, task_id)
        )
        decision_refs = tuple(
            self.records.resolve(ProvenanceRecordType.DECISION, decision_id)
            for decision_id in decision_ids
        )
        verification_refs = self._verification_refs(
            artifact_id=artifact_id,
            task_id=task_id,
            run_id=run_id,
            change_id=change_id,
        )
        entity_refs, design_rule_refs = self._entity_and_rule_refs(artifact_id)

        model_id = artifact["model_id"] if isinstance(artifact["model_id"], str) else None
        model_hash = None
        model_profile = None
        if run_id is not None:
            run = self.records.normalized_snapshot(ProvenanceRecordType.RUN, run_id)
            model_hash = run["model_hash"] if isinstance(run["model_hash"], str) else None
            model_profile = (
                run["model_profile"] if isinstance(run["model_profile"], str) else None
            )
        skill_refs = artifact["skill_versions_json"]
        tool_refs = artifact["tool_versions_json"]
        if not isinstance(skill_refs, list) or any(not isinstance(value, str) for value in skill_refs):
            raise ProvenanceBuildError("Artifact skill_versions_json is invalid")
        if not isinstance(tool_refs, list) or any(not isinstance(value, str) for value in tool_refs):
            raise ProvenanceBuildError("Artifact tool_versions_json is invalid")

        return ProvenanceManifest(
            manifest_id=new_id(IdKind.PROVENANCE_MANIFEST),
            schema_version=1,
            company_id=self.root.company_id,
            root_identity_hash=self.root.content_hash,
            project_ref=project_ref,
            artifact_ref=artifact_ref,
            artifact_content_hash=current_hash,
            artifact_type=str(artifact["type"]),
            artifact_location=portable_location,
            entity_refs=entity_refs,
            design_rule_refs=design_rule_refs,
            task_ref=task_ref,
            run_ref=run_ref,
            change_ref=change_ref,
            decision_refs=decision_refs,
            verification_refs=verification_refs,
            model_id=model_id,
            model_hash=model_hash,
            model_profile=model_profile,
            skill_refs=tuple(skill_refs),
            tool_refs=tuple(tool_refs),
            parent_manifest_refs=self._parent_refs(parent_manifest_refs),
            created_at=created_at or utc_now(),
        )
