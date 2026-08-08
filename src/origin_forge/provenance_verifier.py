from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .provenance_crypto import (
    SignatureBackend,
    certificate_message,
    provenance_manifest_message,
    revocation_message,
)
from .provenance_models import (
    CompanyRootIdentity,
    OperationalKeyPurpose,
    SignedOperationalKeyCertificate,
    SignedOperationalKeyRevocation,
    SignedProvenanceManifest,
)


class ProvenanceTrustFinding(StrEnum):
    ROOT_IDENTITY_MISMATCH = "ROOT_IDENTITY_MISMATCH"
    CERTIFICATE_ROOT_MISMATCH = "CERTIFICATE_ROOT_MISMATCH"
    CERTIFICATE_SIGNATURE_INVALID = "CERTIFICATE_SIGNATURE_INVALID"
    CERTIFICATE_PURPOSE_INVALID = "CERTIFICATE_PURPOSE_INVALID"
    SIGNING_CERTIFICATE_HASH_MISMATCH = "SIGNING_CERTIFICATE_HASH_MISMATCH"
    SIGNING_KEY_MISMATCH = "SIGNING_KEY_MISMATCH"
    MANIFEST_ROOT_MISMATCH = "MANIFEST_ROOT_MISMATCH"
    MANIFEST_SIGNATURE_INVALID = "MANIFEST_SIGNATURE_INVALID"
    KEY_REVOKED = "KEY_REVOKED"
    REVOCATION_SIGNATURE_INVALID = "REVOCATION_SIGNATURE_INVALID"


@dataclass(frozen=True)
class CryptographicProvenanceResult:
    trusted: bool
    root_trusted: bool
    certificate_valid: bool
    manifest_signature_valid: bool
    key_revoked: bool
    findings: tuple[ProvenanceTrustFinding, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "trusted": self.trusted,
            "root_trusted": self.root_trusted,
            "certificate_valid": self.certificate_valid,
            "manifest_signature_valid": self.manifest_signature_valid,
            "key_revoked": self.key_revoked,
            "findings": [value.value for value in self.findings],
            "canonical_project_state_changed": False,
        }


class ProvenanceTrustVerifier:
    """Offline public verification. It has no canonical-state mutation authority."""

    def __init__(self, root: CompanyRootIdentity, backend: SignatureBackend):
        if not isinstance(root, CompanyRootIdentity):
            raise TypeError("root must be a CompanyRootIdentity")
        if not isinstance(backend, SignatureBackend):
            raise TypeError("backend must satisfy SignatureBackend")
        self.root = root
        self.backend = backend

    @property
    def _root_public_key(self) -> bytes:
        return base64.b64decode(self.root.public_key_der_b64, validate=True)

    def _certificate_valid(self, signed: SignedOperationalKeyCertificate) -> tuple[bool, list[ProvenanceTrustFinding]]:
        findings: list[ProvenanceTrustFinding] = []
        certificate = signed.certificate
        if (
            certificate.company_id != self.root.company_id
            or certificate.root_identity_hash != self.root.content_hash
            or signed.root_signature.key_id != self.root.root_key_id
        ):
            findings.append(ProvenanceTrustFinding.CERTIFICATE_ROOT_MISMATCH)
        if certificate.purpose != OperationalKeyPurpose.ARTIFACT_SIGNING:
            findings.append(ProvenanceTrustFinding.CERTIFICATE_PURPOSE_INVALID)
        signature_valid = False
        if ProvenanceTrustFinding.CERTIFICATE_ROOT_MISMATCH not in findings:
            signature_valid = self.backend.verify(
                self._root_public_key,
                certificate_message(certificate),
                signed.root_signature.signature_bytes,
            )
            if not signature_valid:
                findings.append(ProvenanceTrustFinding.CERTIFICATE_SIGNATURE_INVALID)
        return not findings and signature_valid, findings

    def _revoked(
        self,
        certificate: SignedOperationalKeyCertificate,
        revocations: Iterable[SignedOperationalKeyRevocation],
    ) -> tuple[bool, list[ProvenanceTrustFinding]]:
        findings: list[ProvenanceTrustFinding] = []
        revoked = False
        target = certificate.certificate
        for signed in revocations:
            revocation = signed.revocation
            if (
                revocation.company_id != self.root.company_id
                or revocation.root_identity_hash != self.root.content_hash
                or signed.root_signature.key_id != self.root.root_key_id
            ):
                continue
            valid = self.backend.verify(
                self._root_public_key,
                revocation_message(revocation),
                signed.root_signature.signature_bytes,
            )
            if not valid:
                findings.append(ProvenanceTrustFinding.REVOCATION_SIGNATURE_INVALID)
                continue
            if (
                revocation.revoked_key_id == target.key_id
                and revocation.revoked_key_fingerprint == target.public_key_fingerprint
            ):
                revoked = True
        if revoked:
            findings.append(ProvenanceTrustFinding.KEY_REVOKED)
        return revoked, findings

    def verify(
        self,
        signed_manifest: SignedProvenanceManifest,
        certificate: SignedOperationalKeyCertificate,
        *,
        revocations: Iterable[SignedOperationalKeyRevocation] = (),
    ) -> CryptographicProvenanceResult:
        if not isinstance(signed_manifest, SignedProvenanceManifest):
            raise TypeError("signed_manifest must be a SignedProvenanceManifest")
        if not isinstance(certificate, SignedOperationalKeyCertificate):
            raise TypeError("certificate must be a SignedOperationalKeyCertificate")
        findings: list[ProvenanceTrustFinding] = []
        manifest = signed_manifest.manifest

        root_trusted = (
            manifest.company_id == self.root.company_id
            and manifest.root_identity_hash == self.root.content_hash
        )
        if not root_trusted:
            findings.append(ProvenanceTrustFinding.MANIFEST_ROOT_MISMATCH)

        certificate_valid, certificate_findings = self._certificate_valid(certificate)
        findings.extend(certificate_findings)

        if signed_manifest.signing_certificate_hash != certificate.content_hash:
            findings.append(ProvenanceTrustFinding.SIGNING_CERTIFICATE_HASH_MISMATCH)
            certificate_valid = False
        if (
            signed_manifest.signing_key_id != certificate.certificate.key_id
            or signed_manifest.signature.key_id != certificate.certificate.key_id
        ):
            findings.append(ProvenanceTrustFinding.SIGNING_KEY_MISMATCH)
            certificate_valid = False

        revoked, revocation_findings = self._revoked(certificate, revocations)
        findings.extend(revocation_findings)

        manifest_signature_valid = False
        if root_trusted and certificate_valid and not revoked:
            public_key = base64.b64decode(
                certificate.certificate.public_key_der_b64, validate=True
            )
            manifest_signature_valid = self.backend.verify(
                public_key,
                provenance_manifest_message(manifest),
                signed_manifest.signature.signature_bytes,
            )
            if not manifest_signature_valid:
                findings.append(ProvenanceTrustFinding.MANIFEST_SIGNATURE_INVALID)

        unique_findings = tuple(sorted(set(findings), key=lambda value: value.value))
        trusted = (
            root_trusted
            and certificate_valid
            and manifest_signature_valid
            and not revoked
            and not unique_findings
        )
        return CryptographicProvenanceResult(
            trusted=trusted,
            root_trusted=root_trusted,
            certificate_valid=certificate_valid,
            manifest_signature_valid=manifest_signature_valid,
            key_revoked=revoked,
            findings=unique_findings,
        )
