# Phase 18 — Cryptographic Provenance

Status: **implementation starting after Phase 17**

Phase 18 adds cryptographic identity and signatures to Origin Forge's existing causal provenance. The purpose is not to replace Git, Artifact hashes, verified state, or Project Intelligence. It is to make accepted provenance independently verifiable: a recipient should be able to prove which Origin Forge identity signed an exact manifest, which operational key was authorized by that identity, and which exact Artifact/Task/Run/model/Skill/tool evidence the manifest binds.

The core distinction is:

```text
provenance records explain what happened
cryptographic signatures prove who authorized the exact provenance bytes
```

A signature does not make a false claim true. It only makes authorship/integrity of the signed claim verifiable.

---

## 1. Architectural goal

Origin Forge already has:

```text
Task / Run
→ Decision / Change
→ Artifact + SHA-256
→ Verification
→ Project Intelligence bindings
```

Phase 18 wraps selected accepted outputs in a signed trust chain:

```text
manually trusted Company Root public identity
              ↓ signs
Operational Key Certificate
              ↓ signs
Provenance Manifest
              ↓ binds
Artifact + Task + Run + Change + Decision + Verification
+ model/profile/hash + Skills + tools + parent manifests
```

Verification is possible offline from public trust material plus the signed manifest and referenced local evidence.

---

## 2. Fundamental rules

1. **Private keys are never model context.**
   No model request, Skill, Tool Search result, Dream package, Reviewer package, Artifact manifest, log, or provenance record may contain private-key bytes, passphrases, or signer handles.

2. **The Company Root is a trust anchor, not a daily signing key.**
   The root private key is used only for rare operational-key authorization/revocation. Ordinary Artifact manifests are signed by operational keys.

3. **Root identity is stable while operational keys rotate.**
   Compromise/retirement of an operational key must not require changing the Company Root identity.

4. **Sign exact canonical bytes.**
   JSON key order, whitespace, locale, and map insertion order must never affect signature verification.

5. **Domain separation is mandatory.**
   A signature over one Origin Forge object type cannot be replayed as another object type.

6. **SHA-256 remains the content hash.**
   Signatures bind canonical object bytes; SHA-256 identifies those bytes and existing Artifact content.

7. **Ed25519 is the Phase-18 signing algorithm.**
   The implementation remains backend-neutral, but v0 uses an OpenSSL-backed Ed25519 provider so Origin Forge can keep zero Python runtime dependencies.

8. **Public verification is read-only.**
   Verification never updates Artifact/Task/Rule state automatically.

9. **Cryptographic validity and current-state freshness are different.**
   A historical manifest can remain cryptographically authentic while its referenced file or mutable database record has since changed. Verification reports both dimensions separately.

10. **Revocation is conservative.**
    A root-signed operational-key revocation invalidates trust in signatures from that key under the v0 policy. Trusted timestamping is deferred.

11. **No watermark conflation.**
    Phase 18 implements cryptographic identity/signatures. Cross-media watermarking remains a later independent layer.

12. **No automatic release authority.**
    A valid signature does not merge, publish, release, or mark work verified.

---

## 3. Trust hierarchy

### 3.1 Company Root Identity

The root identity is a manually trusted public anchor.

```text
CompanyRootIdentity
- company_id
- display_name
- root_key_id
- algorithm
- public_key_der_b64
- public_key_fingerprint
- created_at
- content_hash
```

The public-key fingerprint is SHA-256 over the exact DER SubjectPublicKeyInfo bytes.

The root identity is not made trustworthy by self-signing. Trust comes from the operator/user deliberately accepting the root fingerprint through an out-of-band process.

The root private key is never stored in a repository and is not required for ordinary production work.

---

### 3.2 Operational Key Certificate

An operational key is authorized by a root-signed certificate.

```text
OperationalKeyCertificate
- certificate_id
- company_id
- root_identity_hash
- key_id
- purpose
- algorithm
- public_key_der_b64
- public_key_fingerprint
- issued_at
- not_after
- content_hash
```

Initial purposes:

```text
ARTIFACT_SIGNING
BUILD_SIGNING
RELEASE_SIGNING
ASSET_SIGNING
```

Phase 18 should initially implement `ARTIFACT_SIGNING`; additional purposes may exist in the schema but do not gain authority automatically.

The root signs the certificate body using the domain:

```text
origin-forge/operational-key-certificate/v1\0
```

A signed certificate envelope contains the root key ID, algorithm, certificate hash, and detached signature.

---

### 3.3 Operational key rotation

Rotation means:

```text
root identity stays constant
→ root signs a new operational key certificate
→ new manifests use the new key
→ old signed manifests remain inspectable
```

A key may simply stop being selected for new signing without invalidating its historical signatures.

Compromise is different from routine rotation and uses explicit revocation.

---

### 3.4 Root-signed revocation

```text
OperationalKeyRevocation
- revocation_id
- company_id
- root_identity_hash
- revoked_key_id
- revoked_key_fingerprint
- reason
- effective_at
- content_hash
```

The root signs the revocation under:

```text
origin-forge/operational-key-revocation/v1\0
```

V0 policy is conservative: when a trusted valid revocation exists for an operational key, provenance verification does not accept that key's manifests as trusted.

This avoids pretending that local wall-clock timestamps provide a trusted historical timestamp service.

More nuanced compromise windows/trusted timestamping may be added later as a separately designed feature.

---

## 4. Cryptographic algorithms

### 4.1 Hashing

Canonical object hashes use:

```text
SHA-256
```

Serialized representation:

```text
sha256:<64 lowercase hex characters>
```

### 4.2 Signatures

V0 signatures use:

```text
Ed25519 / PureEdDSA
```

Origin Forge signs the complete small canonical protocol message, not a separately prehashed Ed25519 digest.

Canonical signed messages are bounded. Phase 18 does not sign arbitrarily large Artifact files directly with Ed25519; the manifest contains the Artifact SHA-256 and the small manifest is signed.

### 4.3 Public-key representation

Public keys are stored as DER SubjectPublicKeyInfo bytes encoded with standard Base64.

The fingerprint is:

```text
sha256(DER SubjectPublicKeyInfo)
```

Private keys remain external signer-backend material and never enter canonical Origin Forge objects.

---

## 5. Domain-separated signature messages

Each signed object uses a fixed ASCII prefix followed by a NUL byte and exact canonical JSON bytes.

Examples:

```text
origin-forge/operational-key-certificate/v1\0 + canonical_certificate_bytes
origin-forge/operational-key-revocation/v1\0 + canonical_revocation_bytes
origin-forge/provenance-manifest/v1\0 + canonical_manifest_bytes
```

The signed message has a hard byte limit before it reaches the backend.

This prevents cross-protocol signature confusion even if two payloads accidentally serialize to similar data.

---

## 6. Signer backend boundary

Phase 18 defines a small backend-neutral protocol:

```text
SignatureBackend
- public_key_der(private_key_handle) -> bytes
- sign(private_key_handle, message) -> bytes
- verify(public_key_der, message, signature) -> bool
```

The `private_key_handle` exists only in deterministic host code. It is not serializable provenance data.

The backend has no authority to:

- inspect model prompts
- change canonical project records
- select which Artifact should be trusted
- change Task/Verification state
- merge/release

It only performs explicit cryptographic operations requested by governed infrastructure.

---

## 7. OpenSSL Ed25519 backend

Origin Forge currently has no Python runtime dependencies. Phase 18 therefore starts with an optional local OpenSSL backend rather than silently adding a crypto package.

V0 backend requirements:

- local `openssl` executable only
- Ed25519 key type
- subprocess argument arrays; never `shell=True`
- bounded input/output
- hard timeout
- temporary files created with restrictive permissions
- cleanup on success/failure
- no network
- no implicit key generation
- no private-key path inside the project root
- no symlink private-key path
- reject insecure POSIX private-key permissions

OpenSSL 3.0 compatibility requires raw one-shot Ed25519 signing/verification. The backend uses the equivalent of:

```text
openssl pkeyutl -sign -rawin ...
openssl pkeyutl -verify -rawin -pubin ...
```

No digest option is supplied for Pure Ed25519.

Operator key generation is deliberately separate from ordinary signing. A typical externally managed Ed25519 key may be created by the operator with OpenSSL, but Origin Forge v0 does not let a model generate or choose keys.

---

## 8. Private-key containment

Private keys are secrets, not project state.

Initial rules:

- private key paths must be absolute
- path must resolve outside the project root
- path itself may not be a symlink
- target must be a regular file
- on POSIX, group/world permission bits must be zero
- private-key contents are never copied into `.origin-forge`
- private-key contents are never hashed into logs or reports
- errors identify only a safe path label/key ID, not key contents
- no generic Tool Registry/Tool Search entry exposes signing to a model

The Company Root private key should normally be offline/removable and absent during ordinary Artifact signing.

Operational private keys may later move behind OS keychains, hardware tokens, HSMs, or agent processes without changing provenance object formats.

---

## 9. Canonical record references

A provenance manifest should not merely name mutable database IDs. It pins the exact observed durable state.

```text
ProvenanceRecordRef
- record_type
- record_id
- record_hash
- revision
```

Initial record types:

```text
PROJECT
ENTITY
DESIGN_RULE
GOAL
FLOW
TASK
RUN
DECISION
CHANGE
ARTIFACT
VERIFICATION
```

`record_hash` is SHA-256 over a canonical normalized snapshot of the exact durable row/evidence object used to construct the manifest.

Revision is included where the underlying record has one.

A later database update therefore produces `RECORD_DRIFT` rather than silently changing what the old signed manifest claimed.

---

## 10. Provenance Manifest

The primary signed object is an immutable canonical Artifact provenance manifest.

```text
ProvenanceManifest
- manifest_id
- schema_version
- company_id
- root_identity_hash
- project_ref
- artifact_ref
- artifact_content_hash
- artifact_type
- artifact_location
- entity_refs[]
- task_ref
- run_ref
- change_ref
- decision_refs[]
- verification_refs[]
- model_id
- model_hash
- model_profile
- skill_refs[]
- tool_refs[]
- parent_manifest_refs[]
- created_at
- content_hash
```

Not every optional lineage field must exist for every Artifact. Missing optional ancestry remains explicit `null`/empty state; it is never invented.

The manifest builder uses existing Origin Forge durable records as source of truth. A model cannot supply arbitrary provenance fields directly.

---

## 11. Signed provenance envelope

```text
SignedProvenanceManifest
- manifest
- signing_key_id
- signing_certificate_hash
- algorithm
- signature_b64
- signature_hash
```

The signature binds the exact canonical manifest bytes under the provenance-manifest domain separator.

The envelope itself is immutable and content-addressed for storage.

---

## 12. Existing lineage integration

Phase 18 builds on `OriginForgeLineage` rather than replacing it.

Existing Artifact records already provide:

- project ownership
- change ID
- path/URI
- Artifact content hash
- parent Artifact
- creating Run
- model ID
- Skill versions
- tool versions
- status

The provenance builder enriches that with exact canonical references to Task/Run/Change/Decision/Verification/Entity/DesignRule evidence where available.

If an Artifact is local, its current bytes must match the Artifact record's stored SHA-256 before a new manifest can be signed.

Signing stale/missing local Artifact bytes fails closed.

---

## 13. Project Intelligence integration

Phase 17 provides semantic Entity bindings and Design Rules.

For a manifest, Phase 18 may include:

- Entities actively bound to the Artifact
- active Design Rules explicitly relevant to those Entities

These are exact record refs, not free-form model summaries.

V0 should not recursively dump the whole Entity graph into every manifest.

---

## 14. Verification result model

Verification must separate cryptographic trust from freshness.

Example result:

```text
ProvenanceVerificationResult
- cryptographic_signature_valid
- root_trusted
- operational_certificate_valid
- operational_key_revoked
- artifact_hash_matches
- record_refs_current
- findings[]
- trusted
```

Potential findings:

```text
INVALID_MANIFEST_HASH
INVALID_SIGNATURE
UNKNOWN_ROOT
CERTIFICATE_SIGNATURE_INVALID
CERTIFICATE_KEY_MISMATCH
KEY_REVOKED
ARTIFACT_MISSING
ARTIFACT_DRIFT
RECORD_MISSING
RECORD_DRIFT
UNSUPPORTED_ALGORITHM
MALFORMED_TRUST_OBJECT
```

`trusted` means the configured trust policy accepts the signature chain and exact manifest.

`artifact_hash_matches` / `record_refs_current` answer whether the current local state still matches that historical claim.

A cryptographically valid historical manifest is never rewritten just because current state moved on.

---

## 15. Trust store

Public trust/provenance objects are protected project-local copies under:

```text
.origin-forge/provenance/
├── root/
├── certificates/
├── revocations/
├── manifests/
└── signed-manifests/
```

All are public/non-secret cryptographic objects.

Store rules mirror other Origin Forge immutable stores:

- canonical envelope
- bounded byte/count limits
- path containment
- no symlink roots/objects
- atomic no-overwrite publication
- same ID may be idempotently re-put only for identical bytes
- load recomputes content hash/signature binding
- unsupported files fail closed

Private keys never appear in this tree.

---

## 16. Company identity and multiple projects

The Company Root exists conceptually above a Project.

Phase 18 v0 may copy the same public Company Root identity/trust certificate set into multiple project-local provenance stores. Equality is established by the root identity content hash/public-key fingerprint, not by trusting a project-local filename.

A later Company/Product registry can centralize discovery without changing signed formats.

---

## 17. Manifest creation authority

Creating a manifest is deterministic infrastructure work.

The builder:

1. validates Project ownership
2. loads Artifact record
3. revalidates local Artifact bytes when applicable
4. loads linked Change/Task/Run/Decision/Verification refs
5. loads explicitly bound Phase-17 Entities/Rules when configured
6. canonicalizes exact row snapshots
7. creates immutable manifest
8. asks an explicitly selected operational signer to sign
9. persists the signed envelope

No model decides that an Artifact is verified/releasable merely because it can be signed.

---

## 18. Key-purpose enforcement

A certificate purpose constrains what it can sign.

V0 rules:

- `ARTIFACT_SIGNING` may sign Artifact provenance manifests
- root key may sign only operational certificates/revocations through the root-authority service
- an Artifact-signing operational key may not sign root-authority objects
- a future RELEASE_SIGNING key does not automatically gain Artifact-signing authority unless explicitly specified by policy

Purpose checks happen before backend signing and during verification.

---

## 19. Revocation and rotation semantics

Routine rotation:

```text
issue new operational certificate
→ select new key for future signatures
→ keep old certificate for historical verification
```

Compromise:

```text
root signs revocation
→ trust store publishes revocation
→ verifier rejects revoked operational key under v0 conservative policy
```

Deletion of old certificates/revocations is forbidden as a normal operation.

Revocation cannot be created by the operational key it revokes.

---

## 20. Trusted time is explicitly out of scope

`created_at`, `issued_at`, and `effective_at` are signed assertions from local infrastructure, not externally trusted timestamps.

Therefore Phase 18 does not claim to prove that a signature existed before a particular real-world time.

RFC 3161/time-stamping services, transparency logs, or hardware attestation may be considered later if required.

---

## 21. Relationship to Git

Git and signed provenance solve different problems.

Git provides:

- source history
- commits/branches/merges
- content-addressed repository objects

Origin Forge provenance provides:

- Task/Run/Decision/Verification causality
- model/Skill/tool lineage
- semantic Entity/Design Rule links
- project/company signature chain
- cross-media Artifact manifests

A manifest may reference a Git commit/hash where useful, but Phase 18 does not replace Git history or rewrite it.

---

## 22. Relationship to Forge Mark / watermarking

Phase 18 is the cryptographic identity/signature foundation of Forge Mark.

Later watermarking may embed evidence into code/image/audio/3D outputs, but the trust hierarchy remains:

```text
signed manifest = primary cryptographic proof
embedded watermark = supplemental discovery/evidence
```

A watermark alone never becomes proof of authorship.

---

## 23. Initial implementation order

Phase 18 v0 should proceed in this order:

1. Phase-18 IDs/enums/canonical models
2. domain-separated signing protocol
3. backend-neutral signature interface
4. hardened OpenSSL Ed25519 backend
5. public root identity model/import
6. root-signed operational key certificates
7. root-signed operational key revocations
8. immutable protected provenance store
9. exact durable record snapshot refs
10. Artifact provenance manifest builder
11. operational-key manifest signing
12. offline trust/signature verification
13. Artifact/record freshness verification
14. read-only trust/provenance inspection CLI
15. explicit operator-only signing/issuance surfaces only after secret-path tests are green

Do not expose signer/key handles through Tool Search or model-facing APIs.

---

## 24. Initial implementation constraints

- keep `pyproject.toml` runtime dependencies empty
- no private-key generation inside a model path
- no secret storage in Git or `.origin-forge`
- no remote signing service
- no cloud KMS dependency
- no release signing yet
- no watermark algorithms
- no trusted timestamping claims
- no automatic signature-based Task PASS

---

## 25. Acceptance tests

### Canonical cryptographic objects

- semantically identical object construction produces identical content hashes
- opaque IDs/signatures do not accidentally alter the wrong payload hash domain
- malformed base64/public keys/hashes fail closed
- unknown fields fail strict parsers

### Root identity

- root public fingerprint is derived from exact DER bytes
- root identity is manually trusted by exact hash/fingerprint
- root private key is never persisted in the project

### Operational certificate

- certificate signature verifies against the configured root
- wrong root/key/hash/purpose fails
- operational key cannot self-authorize
- certificate bytes are immutable/content-addressed

### Secret containment

- relative private-key paths are rejected
- project-contained private-key paths are rejected
- private-key symlinks are rejected
- insecure POSIX permissions are rejected
- no secret bytes appear in durable objects or errors

### OpenSSL backend

- real Ed25519 sign/verify round trip passes when compatible OpenSSL is available
- altered message fails verification
- altered signature fails verification
- wrong public key fails verification
- byte limits/timeouts fail closed
- subprocess execution never uses a shell

### Provenance manifest

- builder pins exact Artifact hash/Task/Run/Change/model/Skill/tool lineage that exists
- missing optional lineage remains explicit rather than guessed
- local Artifact drift prevents creating a new signed current manifest
- Project/Entity/Rule references are same-project
- parent manifest refs are exact and bounded

### Verification

- exact signed manifest verifies offline
- manifest tampering fails cryptographic validation
- certificate tampering fails chain validation
- root mismatch fails trust
- revoked operational key fails trust
- later Artifact drift is reported without rewriting historical manifest
- later durable-record drift is reported separately from signature validity

### Store

- no-overwrite publication under competing writers
- symlink roots/object files fail closed
- count/byte bounds are hard
- same ID is idempotent only for identical canonical bytes

### Authority

- signer/verifier expose no model-generation or Task/merge methods
- read-only verification changes no canonical project state
- valid signature cannot mark Task/Goal/Flow/Artifact verified automatically
- root signer cannot be invoked through a model-facing tool surface

---

## 26. Exit condition

Phase 18 exits when:

> Origin Forge can create an immutable canonical provenance manifest for an existing Artifact, sign it with an explicitly authorized operational Ed25519 key whose public key is certified by a manually trusted Company Root, verify that chain offline including revocation policy, and independently report whether the current Artifact/project evidence still matches the signed historical claim — without exposing private keys to models or allowing signature validity to redefine production verification authority.

The resulting trust path is:

```text
human-trusted root fingerprint
        ↓
root-signed operational key certificate
        ↓
operational-key signed provenance manifest
        ↓
exact Artifact + causal/project evidence
        ↓
read-only offline verification
```
