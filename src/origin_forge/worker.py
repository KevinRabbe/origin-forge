from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .context import ContextBuilder, ContextPackage
from .lineage import OriginForgeLineage
from .model import ModelAdapter, ModelRequest, ModelResponse
from .patches import (
    PATCH_PROPOSAL_SCHEMA,
    PatchProposal,
    parse_patch_proposal,
    validate_patch_preconditions,
)
from .repository import RepositoryReader
from .runtime import OriginForgeRuntime, RuntimeInvariantError
from .skill_runs import bind_run_skills
from .skills import SkillRegistry, SkillSelection
from .state import RunStatus, TaskStatus


EXECUTOR_INSTRUCTIONS = """You are an Origin Forge bounded coding executor.
You may reason only from the supplied task and repository snapshot.
Return exactly one JSON object matching the supplied PatchProposal schema.
Do not claim a change was applied. You are proposing changes only.
Every UPDATE or DELETE must use the exact SHA-256 precondition supplied with the file.
Do not target .git or .origin-forge.
If the context is insufficient, return an empty changes array and explain what is missing in notes.
"""


@dataclass(frozen=True)
class WorkerResult:
    run_id: str
    context_artifact_id: str
    response_artifact_id: str
    proposal_artifact_id: str
    proposal: PatchProposal
    skill_bundle_artifact_id: str | None = None
    skill_refs: tuple[str, ...] = ()


class LocalPatchWorker:
    """One-shot local model worker that can propose, but never apply, repository changes."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        model: ModelAdapter,
        *,
        repository: RepositoryReader | None = None,
        context_builder: ContextBuilder | None = None,
        skill_registry: SkillRegistry | None = None,
    ):
        self.runtime = runtime
        self.model = model
        self.repository = repository or RepositoryReader(runtime.project_root)
        self.context_builder = context_builder or ContextBuilder(
            runtime, self.repository
        )
        self.skill_registry = skill_registry or SkillRegistry(runtime)
        self.lineage = OriginForgeLineage(runtime)

    def _run_dir(self, run_id: str) -> Path:
        path = self.runtime.state_dir / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(value, encoding="utf-8")
        temp.replace(path)

    def _persist_context(
        self,
        run_id: str,
        context: ContextPackage,
        *,
        skill_refs: tuple[str, ...],
    ) -> tuple[Path, str]:
        path = self._run_dir(run_id) / "context.json"
        self._write_json(path, context.to_dict())
        artifact_id = self.lineage.create_artifact(
            artifact_type="CONTEXT_PACKAGE",
            path_or_uri=str(path),
            created_by_run_id=run_id,
            model_id=self.model.model_id,
            skill_versions=skill_refs,
            status="CAPTURED",
        )
        return path, artifact_id

    def _persist_skill_bundle(
        self,
        run_id: str,
        selection: SkillSelection,
        *,
        parent_artifact_id: str,
    ) -> tuple[Path, str] | None:
        if not selection.skills:
            return None
        path = self._run_dir(run_id) / "skill-bundle.json"
        self._write_json(path, selection.to_dict())
        artifact_id = self.lineage.create_artifact(
            artifact_type="SKILL_BUNDLE",
            path_or_uri=str(path),
            parent_artifact_id=parent_artifact_id,
            created_by_run_id=run_id,
            model_id=self.model.model_id,
            skill_versions=selection.refs,
            status="CAPTURED",
        )
        return path, artifact_id

    def _persist_response(
        self,
        run_id: str,
        response: ModelResponse,
        *,
        parent_artifact_id: str,
        skill_refs: tuple[str, ...],
    ) -> tuple[Path, str]:
        path = self._run_dir(run_id) / "model-response.txt"
        self._write_text(path, response.text)
        artifact_id = self.lineage.create_artifact(
            artifact_type="MODEL_RESPONSE",
            path_or_uri=str(path),
            parent_artifact_id=parent_artifact_id,
            created_by_run_id=run_id,
            model_id=response.model_id,
            skill_versions=skill_refs,
            status="CAPTURED",
        )
        return path, artifact_id

    def _persist_proposal(
        self,
        run_id: str,
        proposal: PatchProposal,
        model_id: str,
        *,
        parent_artifact_id: str,
        skill_refs: tuple[str, ...],
    ) -> tuple[Path, str]:
        path = self._run_dir(run_id) / "patch-proposal.json"
        self._write_json(path, proposal.to_dict())
        artifact_id = self.lineage.create_artifact(
            artifact_type="PATCH_PROPOSAL",
            path_or_uri=str(path),
            parent_artifact_id=parent_artifact_id,
            created_by_run_id=run_id,
            model_id=model_id,
            skill_versions=skill_refs,
            status="PROPOSED",
        )
        return path, artifact_id

    def execute(
        self,
        task_id: str,
        *,
        selected_paths: Iterable[str],
        model_profile: str | None = None,
        skill_names: Iterable[str] | None = None,
    ) -> WorkerResult:
        task = self.runtime.get_task(task_id)
        if task["status"] != TaskStatus.RUNNING.value:
            raise RuntimeInvariantError(
                f"executor requires RUNNING task; task {task_id} is {task['status']}"
            )

        selection = self.skill_registry.select(task_id, names=skill_names)
        run_id = self.runtime.start_run(
            task_id, role="EXECUTOR", model_profile=model_profile or self.model.model_id
        )
        try:
            bind_run_skills(self.runtime, run_id, selection)
            context = self.context_builder.build(task_id, selected_paths)
            _, context_artifact_id = self._persist_context(
                run_id, context, skill_refs=selection.refs
            )
            skill_bundle = self._persist_skill_bundle(
                run_id,
                selection,
                parent_artifact_id=context_artifact_id,
            )
            skill_bundle_artifact_id = skill_bundle[1] if skill_bundle else None
            model_parent_artifact_id = skill_bundle_artifact_id or context_artifact_id

            context_payload = context.to_dict()
            context_payload["selected_skills"] = selection.metadata_dicts()
            instructions = EXECUTOR_INSTRUCTIONS
            rendered_skills = selection.render_instructions()
            if rendered_skills:
                instructions = f"{instructions.rstrip()}\n\n{rendered_skills}"

            request = ModelRequest(
                run_id=run_id,
                task_id=task_id,
                instructions=instructions,
                context=context_payload,
                response_schema=PATCH_PROPOSAL_SCHEMA,
            )
            response = self.model.generate(request)
            _, response_artifact_id = self._persist_response(
                run_id,
                response,
                parent_artifact_id=model_parent_artifact_id,
                skill_refs=selection.refs,
            )
            proposal = parse_patch_proposal(response.text)
            validate_patch_preconditions(proposal, self.repository)
            _, proposal_artifact_id = self._persist_proposal(
                run_id,
                proposal,
                response.model_id,
                parent_artifact_id=response_artifact_id,
                skill_refs=selection.refs,
            )
            self.runtime.finish_run(run_id, RunStatus.SUCCEEDED)
            return WorkerResult(
                run_id,
                context_artifact_id,
                response_artifact_id,
                proposal_artifact_id,
                proposal,
                skill_bundle_artifact_id,
                selection.refs,
            )
        except Exception as exc:
            try:
                run = self.runtime.get_run(run_id)
                if run["status"] == RunStatus.RUNNING.value:
                    self.runtime.finish_run(
                        run_id,
                        RunStatus.FAILED,
                        failure_reason=f"{type(exc).__name__}: {exc}",
                    )
            except Exception:
                pass
            raise
