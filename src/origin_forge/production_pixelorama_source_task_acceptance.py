from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .ids import IdKind, new_id, validate_id
from .production_dispatch_execution_models import DispatchExecutionStatus
from .production_dispatch_execution_read import read_dispatch_execution
from .production_pixelorama_source_adoption import (
    SourceAdoptionStatus,
    read_source_adoption_receipt,
)
from .production_pixelorama_source_dispatch_output_binding import (
    materialize_pixelorama_source_result,
    read_pixelorama_source_dispatch_output_binding,
)
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .service import StaleRevision, utc_now
from .state import TaskStatus

SOURCE_TASK_ACCEPTANCE_VERIFICATION = "pixelorama-source-task-acceptance"
SOURCE_TASK_ACCEPTANCE_VERIFIER = "OriginForge.GovernedPixeloramaSourceTaskAcceptor"
SOURCE_TASK_ACCEPTANCE_AUTHORITY = "HUMAN_OPERATOR"


class PixeloramaSourceTaskAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PixeloramaSourceTaskAcceptanceResult:
    execution_id: str
    task_id: str
    adopted_artifact_id: str
    task_verification_id: str
    task_revision: int
    actor_id: str
    accepted_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "adopted_artifact_id": self.adopted_artifact_id,
            "task_verification_id": self.task_verification_id,
            "task_revision": self.task_revision,
            "acceptance_actor_id": self.actor_id,
            "acceptance_authority": SOURCE_TASK_ACCEPTANCE_AUTHORITY,
            "task_status": TaskStatus.SUCCEEDED.value,
            "canonical_asset_adopted": True,
            "accepted_at": self.accepted_at,
        }


def _result(row) -> PixeloramaSourceTaskAcceptanceResult:
    return PixeloramaSourceTaskAcceptanceResult(
        execution_id=row["execution_id"],
        task_id=row["task_id"],
        adopted_artifact_id=row["adopted_artifact_id"],
        task_verification_id=row["task_verification_id"],
        task_revision=int(row["task_revision_at_acceptance"]),
        actor_id=row["acceptance_actor_id"],
        accepted_at=row["accepted_at"],
    )


class GovernedPixeloramaSourceTaskAcceptor:
    """Require explicit human identity before accepting one adopted source result."""

    def __init__(self, runtime: OriginForgeRuntime):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime

    def accept(self, execution_id: str, *, actor_id: str | None = None):
        if not validate_id(execution_id, IdKind.DISPATCH_EXECUTION):
            raise ValueError("execution_id must be a DISPEXEC ID")
        if (
            not isinstance(actor_id, str)
            or not actor_id
            or actor_id.strip() != actor_id
            or len(actor_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in actor_id)
        ):
            raise PixeloramaSourceTaskAcceptanceError(
                "source acceptance requires an explicit human actor_id"
            )
        execution = read_dispatch_execution(self.runtime, execution_id)
        if (
            execution.execution_owner_id != "originforge.execution.pixelorama.source-create@1"
            or execution.status is not DispatchExecutionStatus.RETURNED
        ):
            raise PixeloramaSourceTaskAcceptanceError(
                "source execution is not acceptance eligible"
            )
        binding = read_pixelorama_source_dispatch_output_binding(self.runtime, execution_id)
        materialize_pixelorama_source_result(self.runtime, binding)
        project_index = next(
            index
            for index, output in enumerate(binding.outputs)
            if output.output_type.value == "PIXELORAMA_PROJECT"
        )
        adoption = read_source_adoption_receipt(self.runtime, execution_id, project_index)
        if (
            adoption.status is not SourceAdoptionStatus.PUBLISHED
            or adoption.adopted_artifact_id is None
            or adoption.verification_id is None
        ):
            raise PixeloramaSourceTaskAcceptanceError(
                "source output must be canonically adopted before acceptance"
            )
        task = self.runtime.get_task(binding.task_id)
        expected_revision = binding.task_revision + 1
        with self.runtime.store.session() as conn:
            existing_row = conn.execute(
                "SELECT * FROM pixelorama_source_task_acceptances WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if existing_row is not None:
            existing = _result(existing_row)
            if existing.actor_id != actor_id:
                raise PixeloramaSourceTaskAcceptanceError(
                    "source execution was accepted by a different human actor"
                )
            if task["status"] == TaskStatus.SUCCEEDED.value:
                return existing
            if task["status"] != TaskStatus.RUNNING.value or int(task["revision"]) != existing.task_revision:
                raise PixeloramaSourceTaskAcceptanceError(
                    "source acceptance receipt requires explicit recovery"
                )
            try:
                self.runtime.transition_task(
                    binding.task_id, TaskStatus.SUCCEEDED, expected_revision=existing.task_revision
                )
            except (StaleRevision, RuntimeInvariantError) as exc:
                raise PixeloramaSourceTaskAcceptanceError(
                    "source Task changed during acceptance recovery"
                ) from exc
            return existing
        if task["status"] != TaskStatus.RUNNING.value or int(task["revision"]) != expected_revision:
            raise PixeloramaSourceTaskAcceptanceError(
                "source Task is not the exact current RUNNING revision"
            )
        project_output = binding.outputs[project_index]
        accepted_at = utc_now()
        task_verification_id = new_id(IdKind.VERIFICATION)
        evidence = {
            "execution_id": execution_id,
            "source_output_artifact_id": project_output.artifact_id,
            "adopted_artifact_id": adoption.adopted_artifact_id,
            "adoption_verification_id": adoption.verification_id,
            "accepted_destination_path": adoption.destination_path,
            "accepted_content_hash": "sha256:" + project_output.content_hash,
            "accepted_byte_count": project_output.byte_count,
            "task_revision_at_acceptance": expected_revision,
            "acceptance_actor_id": actor_id,
            "acceptance_authority": SOURCE_TASK_ACCEPTANCE_AUTHORITY,
        }
        with self.runtime.store.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO verifications(id, target_type, target_id, verification_type, verifier, status, evidence_json, metrics_json, run_id, created_at) VALUES (?, 'TASK', ?, ?, ?, 'PASS', ?, '{}', ?, ?)",
                    (
                        task_verification_id,
                        binding.task_id,
                        SOURCE_TASK_ACCEPTANCE_VERIFICATION,
                        SOURCE_TASK_ACCEPTANCE_VERIFIER,
                        json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                        binding.run_id,
                        accepted_at,
                    ),
                )
                conn.execute(
                    "INSERT INTO pixelorama_source_task_acceptances(execution_id, task_id, adopted_artifact_id, adoption_verification_id, task_verification_id, task_revision_at_acceptance, accepted_content_hash, accepted_byte_count, accepted_destination_path, acceptance_actor_id, acceptance_authority, schema_version, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'HUMAN_OPERATOR', 1, ?)",
                    (
                        execution_id,
                        binding.task_id,
                        adoption.adopted_artifact_id,
                        adoption.verification_id,
                        task_verification_id,
                        expected_revision,
                        "sha256:" + project_output.content_hash,
                        project_output.byte_count,
                        adoption.destination_path,
                        actor_id,
                        accepted_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PixeloramaSourceTaskAcceptanceError(
                    "source acceptance conflicts with existing durable evidence"
                ) from exc
        try:
            self.runtime.transition_task(
                binding.task_id, TaskStatus.SUCCEEDED, expected_revision=expected_revision
            )
        except (StaleRevision, RuntimeInvariantError) as exc:
            raise PixeloramaSourceTaskAcceptanceError(
                "source Task changed after acceptance publication; explicit recovery required"
            ) from exc
        with self.runtime.store.session() as conn:
            row = conn.execute(
                "SELECT * FROM pixelorama_source_task_acceptances WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise PixeloramaSourceTaskAcceptanceError("source acceptance receipt disappeared")
        return _result(row)
