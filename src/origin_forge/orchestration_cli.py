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
    parser.add_argument("--file", action="append", required=True, dest="files")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="local-model")
    parser.add_argument("--api-key", default="no-key")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--allow-remote", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
