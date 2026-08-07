from __future__ import annotations

from .lineage import OriginForgeLineage
from .patches import PatchProposal, parse_patch_proposal
from .runtime import OriginForgeRuntime, RuntimeInvariantError


def load_patch_proposal_artifact(
    runtime: OriginForgeRuntime,
    artifact_id: str,
    *,
    expected_task_id: str | None = None,
) -> PatchProposal:
    """Load an integrity-checked persisted PatchProposal and validate its task lineage."""

    lineage = OriginForgeLineage(runtime)
    artifact = lineage.get_artifact(artifact_id)
    if artifact["type"] != "PATCH_PROPOSAL":
        raise RuntimeInvariantError(
            f"artifact {artifact_id} is {artifact['type']}, expected PATCH_PROPOSAL"
        )
    run_id = artifact["created_by_run_id"]
    if run_id is None:
        raise RuntimeInvariantError("patch proposal artifact has no creating Run")
    run = runtime.get_run(run_id)
    if expected_task_id is not None and run["task_id"] != expected_task_id:
        raise RuntimeInvariantError(
            f"patch proposal belongs to task {run['task_id']}, expected {expected_task_id}"
        )
    return parse_patch_proposal(lineage.read_artifact_text(artifact_id))
