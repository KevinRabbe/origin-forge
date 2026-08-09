from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ids import IdKind, validate_id
from .image_workflows import ImageWorkflowError, ImageWorkflowStore
from .lineage import OriginForgeLineage
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.image_vision_cli",
        description=(
            "Read-only inspection of governed image workflows and durable image/vision evidence. "
            "This CLI has no generation, model download, workflow installation, adoption, or Task mutation command."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="summarize Phase-21 workflow and evidence state")
    commands.add_parser("workflow-list", help="list immutable approved image workflows")
    show = commands.add_parser("workflow-show", help="show one exact approved image workflow")
    show.add_argument("workflow_id")
    show.add_argument("workflow_hash")
    artifact = commands.add_parser(
        "artifact-show", help="show one Artifact and its verification evidence"
    )
    artifact.add_argument("artifact_id")
    commands.add_parser("generation-runs", help="list image-generation Runs")
    commands.add_parser("vision-runs", help="list advisory vision-inspection Runs")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _runs(runtime: OriginForgeRuntime, role: str) -> list[dict[str, object]]:
    rows = []
    for run in runtime.list_runs():
        if run["role"] != role:
            continue
        rows.append(
            {
                "id": run["id"],
                "task_id": run["task_id"],
                "role": run["role"],
                "status": run["status"],
                "model_profile": run["model_profile"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "failure_reason": run["failure_reason"],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        store = ImageWorkflowStore(runtime)
        lineage = OriginForgeLineage(runtime)
        if args.command == "status":
            artifacts = lineage.list_artifacts()
            image_artifact_types = {
                "IMAGE_OPERATION_REQUEST",
                "IMAGE_OPERATION_RESULT",
                "GENERATED_RASTER_PNG",
                "ADOPTED_GENERATED_RASTER_PNG",
                "VISION_INSPECTION_REQUEST",
                "VISION_ADVISORY_REPORT",
            }
            by_type: dict[str, int] = {}
            for artifact in artifacts:
                artifact_type = artifact["type"]
                if artifact_type in image_artifact_types:
                    by_type[artifact_type] = by_type.get(artifact_type, 0) + 1
            _print(
                {
                    "status": "OK",
                    "approved_workflow_count": len(store.list()),
                    "image_generation_run_count": len(_runs(runtime, "IMAGE_GENERATOR")),
                    "vision_inspection_run_count": len(_runs(runtime, "VISION_INSPECTOR")),
                    "artifact_counts": dict(sorted(by_type.items())),
                    "model_execution_enabled": False,
                    "workflow_install_enabled": False,
                    "model_download_enabled": False,
                    "canonical_asset_adoption_enabled": False,
                    "task_mutation_enabled": False,
                }
            )
            return 0
        if args.command == "workflow-list":
            _print({"workflows": [value.to_dict() for value in store.list()]})
            return 0
        if args.command == "workflow-show":
            template = store.get(args.workflow_id, args.workflow_hash)
            _print(template.to_dict())
            return 0
        if args.command == "artifact-show":
            if not validate_id(args.artifact_id, IdKind.ARTIFACT):
                raise ValueError("artifact_id must be an ART ID")
            _print(
                {
                    "artifact": lineage.get_artifact(args.artifact_id),
                    "verifications": lineage.list_artifact_verifications(
                        args.artifact_id
                    ),
                }
            )
            return 0
        if args.command == "generation-runs":
            _print({"runs": _runs(runtime, "IMAGE_GENERATOR")})
            return 0
        if args.command == "vision-runs":
            _print({"runs": _runs(runtime, "VISION_INSPECTOR")})
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except (ImageWorkflowError, KeyError, OSError, RuntimeError, ValueError) as exc:
        _print({"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
