from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .context import ContextBuilder
from .context_selection import WorkspaceContextSelector
from .production_read_guard import ensure_production_runtime_readable
from .repository import RepositoryReader
from .runtime import OriginForgeRuntime


def build_context_preview(
    runtime: OriginForgeRuntime,
    task_id: str,
    *,
    selected_paths: Iterable[str] | None = None,
    auto_context: bool = False,
    seed_paths: Iterable[str] = (),
    structural_context: bool = False,
    semantic_context: bool = False,
) -> dict[str, Any]:
    """Return the exact bounded context projection without starting an attempt."""
    ensure_production_runtime_readable(runtime)
    repository = RepositoryReader(runtime.project_root)
    selection = WorkspaceContextSelector(runtime, repository).select(
        task_id,
        selected_paths=selected_paths,
        auto_context=auto_context,
        seed_paths=seed_paths,
        structural_context=structural_context,
        semantic_context=semantic_context,
    )
    builder = ContextBuilder(runtime, repository)
    package = builder.build(task_id, selection.paths)
    files = [
        {
            "path": item.path,
            "content_hash": item.content_hash,
            "byte_count": item.byte_count,
        }
        for item in package.files
    ]
    snapshot_payload = {
        "task_id": package.task_id,
        "task_revision": package.task_revision,
        "mode": selection.mode,
        "files": files,
    }
    snapshot_id = "sha256:" + hashlib.sha256(
        json.dumps(snapshot_payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "task": package.to_dict()["task"],
        "context": {
            "mode": selection.mode,
            "paths": list(selection.paths),
            "files": files,
            "snapshot_id": snapshot_id,
            "limits": {
                "max_file_bytes": repository.max_file_bytes,
                "max_total_bytes": builder.max_total_bytes,
            },
        },
    }
