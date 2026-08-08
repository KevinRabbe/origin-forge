from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .provenance_builder import ProvenanceBuildError, ProvenanceManifestBuilder
from .provenance_crypto import (
    OpenSslEd25519Backend,
    OperationalManifestSigner,
    RootAuthority,
    SignatureBackend,
    SignatureBackendError,
    certificate_message,
    revocation_message,
)
from .provenance_freshness import (
    ProvenanceFreshnessResult,
    ProvenanceFreshnessVerifier,
)
from .provenance_key_format import require_ed25519_public_key_der
from .provenance_models import (
    CompanyRootIdentity,
    OperationalKeyCertificate,
    OperationalKeyPurpose,
    OperationalKeyRevocation,
    ProvenanceManifestRef,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
)
from .provenance_store import ProvenanceStore, ProvenanceStoreError
from .provenance_verifier import (
    CryptographicProvenanceResult,
    ProvenanceTrustVerifier,
)
from .runtime import OriginForgeRuntime
from .service import utc_now


class ProvenanceServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvenanceInspectionResult:
    manifest_id: str
    cryptographic: CryptographicProvenanceResult
    freshness: ProvenanceFreshnessResult

    @property
    def trusted_and_current(self) -> bool:
        return self.cryptographic.trusted and self.freshness.current

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "trusted_and_current": self.trusted_and_current,
            "cryptographic": self.cryptographic.to_dict(),
            "freshness": self.freshness.to_dict(),
            "production_verification_changed": False,
            "artifact_status_changed": False,
            "task_status_changed": False,
        }


class ProvenanceService:
    """Governed public trust/signature operations with no production completion authority."""

    def __init__(
        self,
        runtime: OriginForgeRuntime,
        *,
        store: ProvenanceStore | None = None,
        backend: SignatureBackend | None = None,
    ):
        if not isinstance(runtime, OriginForgeRuntime):
            raise TypeError("runtime must be an OriginForgeRuntime")
        self.runtime = runtime
        self.store = store or ProvenanceStore(runtime)
        if self.store.runtime.project_root != runtime.project_root:
            raise ValueError("provenance store and runtime must belong to the same project")
        self.backend = backend or OpenSslEd25519Backend(runtime.project_root)
        if not isinstance(self.backend, SignatureBackend):
            raise TypeError("backend must satisfy SignatureBackend")

    def _root(self) -> CompanyRootIdentity:
        roots = self.store.list_root_ids()
        if len(roots) != 1:
            raise ProvenanceServiceError(
                "project must trust exactly one Company Root identity"
            )
        return self.store.load_root(roots[0])

    def trust_root_public(
        self,
        display_name: str,
        public_key_der: bytes,
        *,
        created_at: str | None = None,
    ) -> CompanyRootIdentity:
        try:
            public_key_der = require_ed25519_public_key_der(public_key_der)
        except ValueError as exc:
            raise ProvenanceServiceError(
                "Company Root public key is not canonical Ed25519"
            ) from exc
        existing = self.store.list_root_ids()
        if existing:
            root = self.store.load_root(existing[0])
            if (
                base64.b64decode(root.public_key_der_b64, validate=True) == public_key_der
                and root.display_name == display_name
            ):
                return root
            raise ProvenanceServiceError(
                "project already trusts a different Company Root identity"
            )
        root = CompanyRootIdentity.create(
            display_name,
            public_key_der,
            created_at=created_at or utc_now(),
        )
        self.store.put_root(root)
        return root

    def _verify_root_signature(
        self,
        root: CompanyRootIdentity,
        message: bytes,
        signature: bytes,
    ) -> bool:
        return self.backend.verify(
            base64.b64decode(root.public_key_der_b64, validate=True),
            message,
            signature,
        )

    def issue_operational_certificate(
        self,
        operational_public_key_der: bytes,
        *,
        root_private_key_handle: Path,
        purpose: OperationalKeyPurpose = OperationalKeyPurpose.ARTIFACT_SIGNING,
        issued_at: str | None = None,
        not_after: str | None = None,
    ) -> SignedOperationalKeyCertificate:
        root = self._root()
        try:
            operational_public_key_der = require_ed25519_public_key_der(
                operational_public_key_der
            )
        except ValueError as exc:
            raise ProvenanceServiceError(
                "operational public key is not canonical Ed25519"
            ) from exc
        certificate = OperationalKeyCertificate.create(
            root,
            purpose=purpose,
            public_key_der=operational_public_key_der,
            issued_at=issued_at or utc_now(),
            not_after=not_after,
        )
        signed = RootAuthority(
            root,
            self.backend,
            root_private_key_handle,
        ).sign_certificate(certificate)
        if not self._verify_root_signature(
            root,
            certificate_message(certificate),
            signed.root_signature.signature_bytes,
        ):
            raise ProvenanceServiceError(
                "new operational certificate failed root-signature self-check"
            )
        self.store.put_certificate(signed)
        return signed

    def _load_revocations(self) -> tuple[SignedOperationalKeyRevocation, ...]:
        return tuple(
            self.store.load_revocation(revocation_id)
            for revocation_id in self.store.list_revocation_ids()
        )

    def revoke_operational_certificate(
        self,
        certificate_id: str,
        *,
        root_private_key_handle: Path,
        reason: str,
        effective_at: str | None = None,
    ) -> SignedOperationalKeyRevocation:
        root = self._root()
        certificate = self.store.load_certificate(certificate_id)
        for existing in self._load_revocations():
            if existing.revocation.revoked_key_id == certificate.certificate.key_id:
                raise ProvenanceServiceError(
                    "operational key already has a stored revocation"
                )
        revocation = OperationalKeyRevocation.create(
            root,
            certificate.certificate,
            reason=reason,
            effective_at=effective_at or utc_now(),
        )
        signed = RootAuthority(
            root,
            self.backend,
            root_private_key_handle,
        ).sign_revocation(revocation)
        if not self._verify_root_signature(
            root,
            revocation_message(revocation),
            signed.root_signature.signature_bytes,
        ):
            raise ProvenanceServiceError(
                "new operational revocation failed root-signature self-check"
            )
        self.store.put_revocation(signed)
        return signed

    def _certificate_for_signed_manifest(
        self,
        signed: SignedProvenanceManifest,
    ) -> SignedOperationalKeyCertificate:
        matches: list[SignedOperationalKeyCertificate] = []
        for certificate_id in self.store.list_certificate_ids():
            certificate = self.store.load_certificate(certificate_id)
            if (
                certificate.content_hash == signed.signing_certificate_hash
                and certificate.certificate.key_id == signed.signing_key_id
            ):
                matches.append(certificate)
        if len(matches) != 1:
            raise ProvenanceServiceError(
                "signed provenance manifest does not resolve to exactly one stored certificate"
            )
        return matches[0]

    def sign_artifact(
        self,
        artifact_id: str,
        certificate_id: str,
        *,
        operational_private_key_handle: Path,
        parent_manifest_ids: Iterable[str] = (),
        created_at: str | None = None,
    ) -> SignedProvenanceManifest:
        root = self._root()
        certificate = self.store.load_certificate(certificate_id)
        parents: list[ProvenanceManifestRef] = []
        for manifest_id in parent_manifest_ids:
            parent = self.store.load_manifest(manifest_id)
            parents.append(
                ProvenanceManifestRef(
                    parent.manifest.manifest_id,
                    parent.manifest.content_hash,
                )
            )
        builder = ProvenanceManifestBuilder(
            self.runtime,
            root,
            store=self.store,
        )
        try:
            manifest = builder.build(
                artifact_id,
                parent_manifest_refs=parents,
                created_at=created_at,
            )
        except (ProvenanceBuildError, ProvenanceStoreError) as exc:
            raise ProvenanceServiceError("provenance manifest build failed") from exc
        signed = OperationalManifestSigner(
            certificate,
            self.backend,
            operational_private_key_handle,
        ).sign(manifest)
        verification = ProvenanceTrustVerifier(root, self.backend).verify(
            signed,
            certificate,
            revocations=self._load_revocations(),
        )
        if not verification.trusted:
            raise ProvenanceServiceError(
                "new provenance signature chain is not trusted; manifest was not persisted"
            )
        self.store.put_manifest(signed)
        return signed

    def verify_manifest(self, manifest_id: str) -> ProvenanceInspectionResult:
        root = self._root()
        signed = self.store.load_manifest(manifest_id)
        certificate = self._certificate_for_signed_manifest(signed)
        cryptographic = ProvenanceTrustVerifier(root, self.backend).verify(
            signed,
            certificate,
            revocations=self._load_revocations(),
        )
        freshness = ProvenanceFreshnessVerifier(self.runtime).verify(signed)
        return ProvenanceInspectionResult(
            manifest_id=signed.manifest.manifest_id,
            cryptographic=cryptographic,
            freshness=freshness,
        )

    def status(self) -> dict[str, object]:
        return {
            "root_ids": list(self.store.list_root_ids()),
            "certificate_ids": list(self.store.list_certificate_ids()),
            "revocation_ids": list(self.store.list_revocation_ids()),
            "manifest_ids": list(self.store.list_manifest_ids()),
            "private_keys_stored": False,
            "model_signing_enabled": False,
            "automatic_task_verification_enabled": False,
            "automatic_release_enabled": False,
        }
