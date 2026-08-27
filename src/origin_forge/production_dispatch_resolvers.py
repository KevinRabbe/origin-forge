from __future__ import annotations

import json
from collections.abc import Sequence
from typing import ClassVar, Protocol

from .dream_evidence import canonical_verification_record
from .production_design_specification_currentness import (
    AcceptedDesignError,
    inspect_accepted_design,
)
from .production_dispatch_resolution_models import (
    DispatchResolutionModelError,
    InputResolverDescriptor,
    ResolvedWorkOrderInput,
    ResolverClaim,
)
from .production_evidence_read import ProductionEvidenceReadService
from .production_read_guard import production_read_connection
from .production_work_order_models import (
    WorkOrderInputRef,
    WorkOrderRefType,
    content_hash,
)
from .project_intelligence_read import ProjectIntelligenceReadService
from .runtime import OriginForgeRuntime
from .state import WorkspaceStatus
from .workspaces import GitWorkspaceManager


class DispatchInputResolutionError(RuntimeError):
    pass


class WorkOrderInputResolver(Protocol):
    @property
    def descriptor(self) -> InputResolverDescriptor: ...

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput: ...


def _resolver_fingerprint(implementation_id: str, claim: ResolverClaim, projection: object) -> str:
    return content_hash(
        {
            "implementation_id": implementation_id,
            "claim": claim.to_dict(),
            "projection_contract": projection,
        }
    )


def _require_ref(
    ref: WorkOrderInputRef,
    ref_type: WorkOrderRefType,
    prefix: str,
) -> None:
    if not isinstance(ref, WorkOrderInputRef):
        raise TypeError("ref must be a WorkOrderInputRef")
    if ref.ref_type is not ref_type or not ref.ref_id.startswith(prefix):
        raise DispatchInputResolutionError("WorkOrder ref does not match resolver claim")


def _project_id(runtime: OriginForgeRuntime, conn) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE root_path = ?",
        (str(runtime.project_root),),
    ).fetchone()
    if row is None:
        raise DispatchInputResolutionError("current project is not initialized")
    return str(row["id"])


class ArtifactInputResolver:
    _CLAIM = ResolverClaim(WorkOrderRefType.ARTIFACT, "ART-", "ARTIFACT")
    _FIELDS = (
        "id",
        "change_id",
        "type",
        "path_or_uri",
        "content_hash",
        "parent_artifact_id",
        "created_by_run_id",
        "model_id",
        "status",
        "created_at",
    )
    _PROJECTION: ClassVar[dict[str, object]] = {
        "fields": _FIELDS,
        "artifact_bytes": False,
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.artifact@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-artifact-resolver@1",
            _CLAIM,
            _PROJECTION,
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        _require_ref(ref, WorkOrderRefType.ARTIFACT, "ART-")
        if ref.revision is not None:
            raise DispatchInputResolutionError("Artifact refs are not revision-numbered")
        try:
            projection = ProductionEvidenceReadService(runtime).get_artifact(ref.ref_id)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Artifact ref is not available in the current project"
            ) from exc
        actual_hash = projection.get("content_hash")
        if actual_hash != ref.content_hash:
            raise DispatchInputResolutionError("Artifact content hash drifted")
        safe_projection = {
            key: projection[key]
            for key in self._FIELDS
        }
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="ARTIFACT",
            resolution_class="CANONICAL_ARTIFACT",
            projection=safe_projection,
        )


class WorkspaceInputResolver:
    """Resolve one exact audited Workspace for governed build execution."""

    _CLAIM = ResolverClaim(
        WorkOrderRefType.WORKSPACE, "WSPACE-", "WORKSPACE", "build_workspace"
    )
    _FIELDS = ("id", "task_id", "path", "base_commit", "status", "revision")
    _PROJECTION = {"fields": _FIELDS, "required_status": WorkspaceStatus.AUDITED.value}
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.workspace@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-workspace-resolver@1", _CLAIM, _PROJECTION
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self, runtime: OriginForgeRuntime, ref: WorkOrderInputRef
    ) -> ResolvedWorkOrderInput:
        _require_ref(ref, WorkOrderRefType.WORKSPACE, "WSPACE-")
        if ref.revision is None:
            raise DispatchInputResolutionError("Workspace refs must be revision-numbered")
        try:
            workspace = GitWorkspaceManager(runtime).get(ref.ref_id)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Workspace ref is not available in the current project"
            ) from exc
        projection = {key: workspace[key] for key in self._FIELDS}
        if workspace["status"] != WorkspaceStatus.AUDITED.value:
            raise DispatchInputResolutionError("build Workspace ref must be AUDITED")
        if int(workspace["revision"]) != ref.revision:
            raise DispatchInputResolutionError("Workspace revision drifted")
        if content_hash(projection) != ref.content_hash:
            raise DispatchInputResolutionError("Workspace content hash drifted")
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="WORKSPACE",
            resolution_class="AUDITED_WORKSPACE",
            projection=projection,
        )


class VerificationInputResolver:
    _CLAIM = ResolverClaim(
        WorkOrderRefType.VERIFICATION,
        "VERIFY-",
        "VERIFICATION",
    )
    _PROJECTION: ClassVar[dict[str, object]] = {
        "fields": [
            "id",
            "target_type",
            "target_id",
            "verification_type",
            "verifier",
            "status",
            "run_id",
            "created_at",
            "record_hash",
            "evidence_hash",
            "metrics_hash",
        ],
        "raw_evidence": False,
        "raw_metrics": False,
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.verification@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-verification-resolver@1",
            _CLAIM,
            _PROJECTION,
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    @staticmethod
    def _owned(runtime: OriginForgeRuntime, conn, row) -> bool:
        project_id = _project_id(runtime, conn)
        target_type = str(row["target_type"])
        target_id = str(row["target_id"])
        if target_type == "ARTIFACT":
            owner = conn.execute(
                "SELECT project_id FROM artifacts WHERE id = ?",
                (target_id,),
            ).fetchone()
        elif target_type == "GOAL":
            owner = conn.execute(
                "SELECT project_id FROM goals WHERE id = ?",
                (target_id,),
            ).fetchone()
        elif target_type == "FLOW":
            owner = conn.execute(
                """SELECT g.project_id FROM flows f
                   JOIN goals g ON g.id = f.goal_id WHERE f.id = ?""",
                (target_id,),
            ).fetchone()
        elif target_type == "TASK":
            owner = conn.execute(
                """SELECT g.project_id FROM tasks t
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id WHERE t.id = ?""",
                (target_id,),
            ).fetchone()
        elif target_type == "RUN":
            owner = conn.execute(
                """SELECT g.project_id FROM runs r
                   JOIN tasks t ON t.id = r.task_id
                   JOIN flows f ON f.id = t.flow_id
                   JOIN goals g ON g.id = f.goal_id WHERE r.id = ?""",
                (target_id,),
            ).fetchone()
        else:
            return False
        return owner is not None and owner["project_id"] == project_id

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        _require_ref(ref, WorkOrderRefType.VERIFICATION, "VERIFY-")
        if ref.revision is not None:
            raise DispatchInputResolutionError("Verification refs are not revision-numbered")
        try:
            with production_read_connection(runtime) as conn:
                row = conn.execute(
                    "SELECT * FROM verifications WHERE id = ?",
                    (ref.ref_id,),
                ).fetchone()
                if row is None or not self._owned(runtime, conn, row):
                    raise DispatchInputResolutionError(
                        "Verification ref is not project-owned"
                    )
                row_dict = dict(row)
        except DispatchInputResolutionError:
            raise
        except (RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Verification ref could not be read safely"
            ) from exc
        record = canonical_verification_record(row_dict)
        record_hash = content_hash(record)
        if record_hash != ref.content_hash:
            raise DispatchInputResolutionError("Verification record hash drifted")
        try:
            evidence = json.loads(str(row_dict["evidence_json"]))
            metrics = json.loads(str(row_dict["metrics_json"]))
        except json.JSONDecodeError as exc:
            raise DispatchInputResolutionError(
                "Verification evidence or metrics JSON is invalid"
            ) from exc
        projection = {
            "id": row_dict["id"],
            "target_type": row_dict["target_type"],
            "target_id": row_dict["target_id"],
            "verification_type": row_dict["verification_type"],
            "verifier": row_dict["verifier"],
            "status": row_dict["status"],
            "run_id": row_dict["run_id"],
            "created_at": row_dict["created_at"],
            "record_hash": record_hash,
            "evidence_hash": content_hash(evidence),
            "metrics_hash": content_hash(metrics),
        }
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="VERIFICATION",
            resolution_class="CANONICAL_VERIFICATION_METADATA",
            projection=projection,
        )


class ProjectEntityInputResolver:
    _CLAIM = ResolverClaim(
        WorkOrderRefType.PROJECT_ENTITY,
        "ENTITY-",
        "PROJECT_ENTITY",
    )
    _PROJECTION: ClassVar[dict[str, object]] = {
        "fields": [
            "id",
            "kind",
            "name",
            "description",
            "status",
            "revision",
            "created_at",
            "updated_at",
        ]
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.project-entity@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-project-entity-resolver@1",
            _CLAIM,
            _PROJECTION,
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        _require_ref(ref, WorkOrderRefType.PROJECT_ENTITY, "ENTITY-")
        if ref.revision is None:
            raise DispatchInputResolutionError("Project Entity ref requires exact revision")
        try:
            projection = ProjectIntelligenceReadService(runtime).get_entity(ref.ref_id)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Project Entity ref is not available in the current project"
            ) from exc
        if int(projection["revision"]) != ref.revision:
            raise DispatchInputResolutionError("Project Entity revision drifted")
        if content_hash(projection) != ref.content_hash:
            raise DispatchInputResolutionError("Project Entity record hash drifted")
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="PROJECT_ENTITY",
            resolution_class="CANONICAL_PROJECT_ENTITY",
            projection=projection,
        )


class DesignRuleInputResolver:
    _CLAIM = ResolverClaim(
        WorkOrderRefType.DESIGN_RULE,
        "RULE-",
        "DESIGN_RULE",
    )
    _PROJECTION: ClassVar[dict[str, object]] = {
        "fields": [
            "id",
            "category",
            "title",
            "statement",
            "rationale",
            "authority",
            "scope_entity_ids",
            "status",
            "revision",
            "supersedes_rule_id",
            "created_at",
            "updated_at",
        ]
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.design-rule@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-design-rule-resolver@1",
            _CLAIM,
            _PROJECTION,
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        _require_ref(ref, WorkOrderRefType.DESIGN_RULE, "RULE-")
        if ref.revision is None:
            raise DispatchInputResolutionError("Design Rule ref requires exact revision")
        try:
            projection = ProjectIntelligenceReadService(runtime).get_design_rule(ref.ref_id)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "Design Rule ref is not available in the current project"
            ) from exc
        if int(projection["revision"]) != ref.revision:
            raise DispatchInputResolutionError("Design Rule revision drifted")
        if content_hash(projection) != ref.content_hash:
            raise DispatchInputResolutionError("Design Rule record hash drifted")
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="DESIGN_RULE",
            resolution_class="CANONICAL_DESIGN_RULE",
            projection=projection,
        )


class AcceptedDesignInputResolver:
    """Resolve one current, immutable accepted design for production planning."""

    _CLAIM = ResolverClaim(
        WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE,
        "DESIGNACC-",
        "ACCEPTED_DESIGN",
        "accepted_design",
    )
    _PROJECTION = {
        "fields": (
            "acceptance_id",
            "acceptance_hash",
            "design_input_id",
            "design_input_hash",
            "design_specification_id",
            "design_specification_hash",
            "goal_id",
            "goal_revision",
            "goal_content_hash",
        ),
        "currentness": "inspect_accepted_design.current == true",
        "artifact_bytes": False,
    }
    _DESCRIPTOR = InputResolverDescriptor(
        "resolver.core.accepted-design@1",
        _resolver_fingerprint(
            "origin-forge-dispatch-accepted-design-resolver@1",
            _CLAIM,
            _PROJECTION,
        ),
        (_CLAIM,),
    )

    @property
    def descriptor(self) -> InputResolverDescriptor:
        return self._DESCRIPTOR

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        _require_ref(
            ref,
            WorkOrderRefType.DESIGN_SPECIFICATION_ACCEPTANCE,
            "DESIGNACC-",
        )
        if ref.revision is not None:
            raise DispatchInputResolutionError(
                "accepted design refs are immutable and must not carry a revision"
            )
        try:
            inspection = inspect_accepted_design(runtime, ref.ref_id)
        except (AcceptedDesignError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                "accepted design ref is not available in the current project"
            ) from exc
        if not inspection.current:
            raise DispatchInputResolutionError(
                f"accepted design ref is stale: {inspection.stale_reason or 'unknown reason'}"
            )
        projection = {
            "acceptance_id": inspection.acceptance.acceptance_id,
            "acceptance_hash": inspection.acceptance.content_hash,
            "design_input_id": inspection.design_input.design_input_id,
            "design_input_hash": inspection.design_input.content_hash,
            "design_specification_id": inspection.specification.design_specification_id,
            "design_specification_hash": inspection.specification.content_hash,
            "goal_id": inspection.design_input.goal_id,
            "goal_revision": inspection.design_input.goal_revision,
            "goal_content_hash": inspection.design_input.goal_content_hash,
        }
        if content_hash(projection) != ref.content_hash:
            raise DispatchInputResolutionError("accepted design projection hash drifted")
        return ResolvedWorkOrderInput.create(
            ref,
            resolver_id=self.descriptor.resolver_id,
            resolver_fingerprint=self.descriptor.resolver_fingerprint,
            source_object_type="ACCEPTED_DESIGN",
            resolution_class="CURRENT_ACCEPTED_DESIGN",
            projection=projection,
        )


class WorkOrderInputResolverRegistry:
    def __init__(self, resolvers: Sequence[WorkOrderInputResolver]):
        values = tuple(resolvers)
        if not values:
            raise ValueError("resolver registry must not be empty")
        descriptors: list[InputResolverDescriptor] = []
        for value in values:
            descriptor = getattr(value, "descriptor", None)
            if not isinstance(descriptor, InputResolverDescriptor) or not callable(
                getattr(value, "resolve", None)
            ):
                raise TypeError("resolver registry values must implement WorkOrderInputResolver")
            descriptors.append(descriptor)
        ids = [value.resolver_id for value in descriptors]
        if len(ids) != len(set(ids)):
            raise ValueError("resolver registry contains duplicate resolver IDs")
        claims: list[tuple[InputResolverDescriptor, ResolverClaim]] = []
        for descriptor in descriptors:
            for claim in descriptor.claims:
                for other_descriptor, other in claims:
                    if (
                        claim.ref_type is other.ref_type
                        and claim.source_id_prefix == other.source_id_prefix
                        and (
                            (claim.role is None and other.role is None)
                            or (
                                claim.role is not None
                                and other.role is not None
                                and claim.role == other.role
                            )
                        )
                    ):
                        raise ValueError(
                            "resolver registry contains ambiguous claims: "
                            f"{descriptor.resolver_id} vs {other_descriptor.resolver_id}"
                        )
                claims.append((descriptor, claim))
        paired = sorted(
            zip(values, descriptors),
            key=lambda value: value[1].resolver_id,
        )
        self._resolvers = tuple(value[0] for value in paired)
        self._descriptors = tuple(value[1] for value in paired)
        self._by_id = {
            descriptor.resolver_id: resolver
            for resolver, descriptor in paired
        }
        self._fingerprint = content_hash(
            {"resolvers": [value.to_dict() for value in self._descriptors]}
        )

    @property
    def descriptors(self) -> tuple[InputResolverDescriptor, ...]:
        return self._descriptors

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def resolver_for(self, ref: WorkOrderInputRef) -> WorkOrderInputResolver:
        if not isinstance(ref, WorkOrderInputRef):
            raise TypeError("ref must be a WorkOrderInputRef")
        matches: list[tuple[bool, str]] = []
        for descriptor in self._descriptors:
            if any(
                claim.ref_type is ref.ref_type
                and ref.ref_id.startswith(claim.source_id_prefix)
                and (claim.role is None or claim.role == ref.role)
                for claim in descriptor.claims
            ):
                exact_role = any(
                    claim.ref_type is ref.ref_type
                    and ref.ref_id.startswith(claim.source_id_prefix)
                    and claim.role is not None
                    and claim.role == ref.role
                    for claim in descriptor.claims
                )
                matches.append((exact_role, descriptor.resolver_id))
        if not matches:
            raise DispatchInputResolutionError(
                f"no trusted input resolver for {ref.ref_type.value}:{ref.ref_id}:{ref.role}"
            )
        exact_matches = [value for exact, value in matches if exact]
        selected = exact_matches if exact_matches else [value for _, value in matches]
        if len(selected) != 1:
            raise DispatchInputResolutionError("input resolver selection is ambiguous")
        return self._by_id[selected[0]]

    def resolve(
        self,
        runtime: OriginForgeRuntime,
        ref: WorkOrderInputRef,
    ) -> ResolvedWorkOrderInput:
        resolver = self.resolver_for(ref)
        descriptor = resolver.descriptor
        try:
            result = resolver.resolve(runtime, ref)
        except DispatchInputResolutionError:
            raise
        except (DispatchResolutionModelError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise DispatchInputResolutionError(
                f"trusted resolver failed for {ref.ref_id}"
            ) from exc
        if (
            result.original_ref != ref
            or result.resolver_id != descriptor.resolver_id
            or result.resolver_fingerprint != descriptor.resolver_fingerprint
        ):
            raise DispatchInputResolutionError(
                "resolver returned evidence under the wrong resolver/ref identity"
            )
        return result

    def resolve_all(
        self,
        runtime: OriginForgeRuntime,
        refs: Sequence[WorkOrderInputRef],
    ) -> tuple[ResolvedWorkOrderInput, ...]:
        values = tuple(refs)
        if len(values) > 128 or not all(
            isinstance(value, WorkOrderInputRef) for value in values
        ):
            raise DispatchInputResolutionError("WorkOrder refs are outside resolution bounds")
        identities = [
            (value.ref_type.value, value.role, value.ref_id)
            for value in values
        ]
        if len(identities) != len(set(identities)):
            raise DispatchInputResolutionError("WorkOrder refs contain duplicate identities")
        return tuple(
            self.resolve(runtime, value)
            for value in sorted(
                values,
                key=lambda value: (value.ref_type.value, value.role, value.ref_id),
            )
        )


def build_core_input_resolver_registry() -> WorkOrderInputResolverRegistry:
    return WorkOrderInputResolverRegistry(
        (
            ArtifactInputResolver(),
            VerificationInputResolver(),
            ProjectEntityInputResolver(),
            DesignRuleInputResolver(),
        )
    )
