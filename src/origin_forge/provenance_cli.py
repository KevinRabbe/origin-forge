from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provenance_crypto import SignatureBackendError
from .provenance_service import ProvenanceService, ProvenanceServiceError
from .provenance_store import ProvenanceStore, ProvenanceStoreError
from .runtime import OriginForgeRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.provenance_cli",
        description="Read-only inspection and verification of Origin Forge cryptographic provenance.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="show public provenance catalog status")
    commands.add_parser("root-show", help="show the trusted Company Root identity")
    commands.add_parser("certificate-list", help="list operational key certificates")
    certificate_show = commands.add_parser(
        "certificate-show", help="show one operational key certificate"
    )
    certificate_show.add_argument("certificate_id")
    commands.add_parser("revocation-list", help="list operational key revocations")
    revocation_show = commands.add_parser(
        "revocation-show", help="show one operational key revocation"
    )
    revocation_show.add_argument("revocation_id")
    commands.add_parser("manifest-list", help="list signed provenance manifests")
    manifest_show = commands.add_parser(
        "manifest-show", help="show one signed provenance manifest"
    )
    manifest_show.add_argument("manifest_id")
    verify = commands.add_parser(
        "verify", help="verify signature trust and current local freshness"
    )
    verify.add_argument("manifest_id")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)
    store = ProvenanceStore(runtime)

    try:
        if args.command == "status":
            _print(
                {
                    "root_ids": list(store.list_root_ids()),
                    "certificate_ids": list(store.list_certificate_ids()),
                    "revocation_ids": list(store.list_revocation_ids()),
                    "manifest_ids": list(store.list_manifest_ids()),
                    "private_keys_stored": False,
                    "model_signing_enabled": False,
                    "automatic_task_verification_enabled": False,
                    "automatic_release_enabled": False,
                    "mutation_commands_enabled": False,
                }
            )
            return 0

        if args.command == "root-show":
            roots = store.list_root_ids()
            if len(roots) != 1:
                raise ProvenanceServiceError(
                    "project must trust exactly one Company Root identity"
                )
            _print(store.load_root(roots[0]).to_dict())
            return 0

        if args.command == "certificate-list":
            _print({"certificates": list(store.list_certificate_ids())})
            return 0
        if args.command == "certificate-show":
            _print(store.load_certificate(args.certificate_id).to_dict())
            return 0

        if args.command == "revocation-list":
            _print({"revocations": list(store.list_revocation_ids())})
            return 0
        if args.command == "revocation-show":
            _print(store.load_revocation(args.revocation_id).to_dict())
            return 0

        if args.command == "manifest-list":
            _print({"manifests": list(store.list_manifest_ids())})
            return 0
        if args.command == "manifest-show":
            _print(store.load_manifest(args.manifest_id).to_dict())
            return 0
        if args.command == "verify":
            inspection = ProvenanceService(runtime, store=store).verify_manifest(
                args.manifest_id
            )
            _print(inspection.to_dict())
            return 0 if inspection.cryptographic.trusted else 4

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        ProvenanceServiceError,
        ProvenanceStoreError,
        SignatureBackendError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
