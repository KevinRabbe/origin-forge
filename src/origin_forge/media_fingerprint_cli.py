from __future__ import annotations

import argparse
import json
from pathlib import Path

from .media_fingerprint_store import MediaFingerprintStore
from .runtime import OriginForgeRuntime


_CATEGORY_COMMANDS = {
    "fingerprints": "fingerprints",
    "comparisons": "comparisons",
    "watermark-plans": "watermark-plans",
    "watermark-results": "watermark-results",
    "provenance-links": "provenance-links",
}
_SHOW_COMMANDS = {
    "fingerprint-show": "fingerprints",
    "comparison-show": "comparisons",
    "watermark-plan-show": "watermark-plans",
    "watermark-result-show": "watermark-results",
    "provenance-link-show": "provenance-links",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.media_fingerprint_cli",
        description=(
            "Read-only inspection of Phase-28 fingerprint/watermark evidence. "
            "This CLI cannot fingerprint files, embed/detect marks, sign, adopt, or mutate state."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="summarize immutable Phase-28 evidence")
    for command in _CATEGORY_COMMANDS:
        commands.add_parser(command, help=f"list {command}")
    for command in _SHOW_COMMANDS:
        show = commands.add_parser(command, help=f"show one {command[:-5]}")
        show.add_argument("object_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    try:
        runtime.project_id()
        store = MediaFingerprintStore(runtime)
        if args.command == "status":
            _print(
                {
                    "status": "OK",
                    "counts": {
                        category: len(store.list_objects(category))
                        for category in _CATEGORY_COMMANDS.values()
                    },
                    "phase18_is_trust_root": True,
                    "fingerprint_compute_enabled": False,
                    "arbitrary_path_hashing_enabled": False,
                    "watermark_embedding_enabled": False,
                    "watermark_detection_enabled": False,
                    "watermark_authorship_proof_enabled": False,
                    "cryptographic_provenance_verification_enabled": False,
                    "secret_key_access_enabled": False,
                    "canonical_asset_mutation_enabled": False,
                    "automatic_adoption_enabled": False,
                    "production_task_mutation_enabled": False,
                    "provenance_signing_enabled": False,
                    "merge_release_enabled": False,
                }
            )
            return 0
        category = _CATEGORY_COMMANDS.get(args.command)
        if category is not None:
            _print({"objects": list(store.list_objects(category))})
            return 0
        category = _SHOW_COMMANDS.get(args.command)
        if category is not None:
            _print(store.load(category, args.object_id))
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        _print({"status": "ERROR", "error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
