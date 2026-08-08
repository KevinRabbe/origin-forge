from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provenance_crypto import SecretContainmentError, SignatureBackendError
from .provenance_models import OperationalKeyPurpose
from .provenance_service import ProvenanceService, ProvenanceServiceError
from .provenance_store import ProvenanceStoreError
from .runtime import OriginForgeRuntime


_MAX_PUBLIC_KEY_BYTES = 4096


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m origin_forge.provenance_admin_cli",
        description=(
            "Explicit human-operated cryptographic provenance administration. "
            "This surface never generates keys, verifies Tasks, merges, releases, or serves models."
        ),
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    trust = commands.add_parser(
        "root-trust",
        help="trust one existing public Company Root Ed25519 key",
    )
    trust.add_argument("--display-name", required=True)
    trust.add_argument("--public-key-der", type=Path, required=True)

    issue = commands.add_parser(
        "certificate-issue",
        help="root-sign an existing operational Ed25519 public key",
    )
    issue.add_argument("--operational-public-key-der", type=Path, required=True)
    issue.add_argument("--root-private-key", type=Path, required=True)
    issue.add_argument(
        "--purpose",
        choices=[value.value for value in OperationalKeyPurpose],
        default=OperationalKeyPurpose.ARTIFACT_SIGNING.value,
    )
    issue.add_argument("--not-after")

    revoke = commands.add_parser(
        "certificate-revoke",
        help="root-sign a revocation for one stored operational certificate",
    )
    revoke.add_argument("certificate_id")
    revoke.add_argument("--root-private-key", type=Path, required=True)
    revoke.add_argument("--reason", required=True)

    sign = commands.add_parser(
        "sign-artifact",
        help="sign one current local Artifact provenance manifest",
    )
    sign.add_argument("artifact_id")
    sign.add_argument("--certificate", required=True, dest="certificate_id")
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--parent", action="append", default=[], dest="parent_manifest_ids")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _read_public_der(path: Path) -> bytes:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("public key path may not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("public key path is unavailable") from exc
    if not resolved.is_file():
        raise ValueError("public key path must be a regular file")
    with resolved.open("rb") as handle:
        data = handle.read(_MAX_PUBLIC_KEY_BYTES + 1)
    if not data or len(data) > _MAX_PUBLIC_KEY_BYTES:
        raise ValueError(
            f"public key DER exceeds byte limit ({len(data)} > {_MAX_PUBLIC_KEY_BYTES})"
        )
    return data


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = OriginForgeRuntime(args.project_root)

    try:
        service = ProvenanceService(runtime)
        if args.command == "root-trust":
            root = service.trust_root_public(
                args.display_name,
                _read_public_der(args.public_key_der),
            )
            _print(
                {
                    "root": root.to_dict(),
                    "private_key_stored": False,
                    "key_generated": False,
                }
            )
            return 0

        if args.command == "certificate-issue":
            certificate = service.issue_operational_certificate(
                _read_public_der(args.operational_public_key_der),
                root_private_key_handle=args.root_private_key,
                purpose=OperationalKeyPurpose(args.purpose),
                not_after=args.not_after,
            )
            _print(
                {
                    "certificate": certificate.to_dict(),
                    "private_key_stored": False,
                    "key_generated": False,
                }
            )
            return 0

        if args.command == "certificate-revoke":
            revocation = service.revoke_operational_certificate(
                args.certificate_id,
                root_private_key_handle=args.root_private_key,
                reason=args.reason,
            )
            _print(
                {
                    "revocation": revocation.to_dict(),
                    "private_key_stored": False,
                }
            )
            return 0

        if args.command == "sign-artifact":
            signed = service.sign_artifact(
                args.artifact_id,
                args.certificate_id,
                operational_private_key_handle=args.private_key,
                parent_manifest_ids=tuple(args.parent_manifest_ids),
            )
            _print(
                {
                    "signed_manifest": signed.to_dict(),
                    "private_key_stored": False,
                    "task_status_changed": False,
                    "artifact_status_changed": False,
                    "automatic_release_performed": False,
                }
            )
            return 0

    except KeyError as exc:
        _print({"error": "NOT_FOUND", "detail": str(exc)})
        return 3
    except (
        ProvenanceServiceError,
        ProvenanceStoreError,
        SecretContainmentError,
        SignatureBackendError,
        OSError,
        ValueError,
    ) as exc:
        _print({"error": type(exc).__name__, "detail": str(exc)})
        return 2

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
