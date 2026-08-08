from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .adapters.llamacpp import LlamaCppAdapter
from .config import load_config
from .orchestration import AttemptOutcome, BoundedTaskOrchestrator
from .runtime import OriginForgeRuntime
from .sandbox_factory import create_sandbox_backend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m origin_forge.orchestration_cli")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("task_id")
    context = parser.add_mutually_exclusive_group(required=True)
    context.add_argument("--file", action="append", dest="files")
    context.add_argument("--auto-context", action="store_true")
    parser.add_argument(
        "--seed-file",
        action="append",
        default=[],
        dest="seed_files",
        help="force a file into automatic context selection; requires --auto-context",
    )
    parser.add_argument(
        "--structural-context",
        action="store_true",
        help="expand selected context with bounded Python structural relationships",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="local-model")
    parser.add_argument("--api-key", default="no-key")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--allow-remote", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.seed_files and not args.auto_context:
        parser.error("--seed-file requires --auto-context")

    runtime = OriginForgeRuntime(args.project_root)
    config = load_config(runtime.project_root)
    backend = create_sandbox_backend(runtime, config)
    model = LlamaCppAdapter(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        timeout_seconds=args.timeout,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        allow_remote=args.allow_remote,
    )
    result = BoundedTaskOrchestrator(runtime, model, backend).execute(
        args.task_id,
        selected_paths=args.files,
        auto_context=args.auto_context,
        context_seed_paths=args.seed_files,
        structural_context=args.structural_context,
        model_profile=args.model,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))
    if result.outcome == AttemptOutcome.SUCCEEDED:
        return 0
    if result.outcome == AttemptOutcome.BLOCKED:
        return 13
    return 12


if __name__ == "__main__":
    raise SystemExit(main())
