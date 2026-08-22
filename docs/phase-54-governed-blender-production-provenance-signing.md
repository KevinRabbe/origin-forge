# Phase 54 — Governed Blender Production Provenance Signing

Status: **architecture gate**

Planning base: `8220a54c18c93ba3efa511e360bc737f83f5afa2`

Phase 54 composes the already-governed Blender production chain from Phases 51–53 with the existing Phase-18 cryptographic provenance service. It does **not** redesign cryptography, invent another production-acceptance authority, convert the adopted production Artifact into a different lifecycle state, or grant release authority.

The intended production path is:

```text
DISPEXEC-*                                public production identity
  ↓
Phase 51 exact Blender dispatch/output binding
  ↓
Phase 52 exact PUBLISHED production adoption
  ↓
canonical BLENDER_GLB_EXPORT Artifact, status ADOPTED
  ↓
Phase 53 exact HUMAN_OPERATOR Task acceptance
  ↓
Task exact terminal state SUCCEEDED
  ↓
Phase 54 governed provenance eligibility/currentness
  ↓
Phase 18 ProvenanceService.sign_artifact(...)
  ↓
trusted signed provenance manifest
```

The signature proves authorship/integrity of the exact provenance claim. It does not make production correct, accepted, releasable, merged, deployed, or published.

---

## 1. Source-of-truth findings that freeze this design

### 1.1 Phase 52 intentionally creates an `ADOPTED` Artifact

The canonical Blender production output is a new project Artifact with the reviewed production identity:

```text
type                 BLENDER_GLB_EXPORT
status               ADOPTED
parent_artifact_id   Phase-51 output Artifact
created_by_run_id    exact production Run
path_or_uri           canonical Phase-52 destination
content_hash          exact production output SHA-256
```

The Phase-52 PUBLISHED adoption receipt and adoption PASS Verification both bind that exact relation.

`ADOPTED` is therefore production truth. Phase 54 must not call generic `accept_artifact()` merely to make the record resemble an older Phase-18 fixture.

### 1.2 Phase 18 does not require generic Artifact `ACCEPTED`

Current `ProvenanceManifestBuilder`:

- resolves the project-owned Artifact record;
- requires a recorded content hash;
- resolves the local path under the project root;
- rejects symlinks/escapes/non-files;
- hashes the current bytes under a fixed byte bound;
- requires the current bytes to match the Artifact record hash;
- derives exact lineage and Verification record references;
- creates an immutable canonical provenance manifest.

There is no builder rule requiring `artifact.status == ACCEPTED` or an `ARTIFACT_ACCEPTED` event.

Current `ProvenanceService.sign_artifact(...)` likewise takes the Artifact ID directly, delegates to the builder, signs with an explicitly supplied operational-key handle, verifies the trust chain, and persists only a trusted signed manifest. It does not change Artifact or Task state.

### 1.3 There is no hidden provenance CLI lifecycle wrapper

The installed package entrypoints are currently:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The main `origin-forge` CLI has no provenance/sign command. Phase-18 provenance is currently an in-process governed service capability. There is therefore no public wrapper imposing an additional `ACCEPTED` prerequisite.

### 1.4 Phase 18 explicitly has no release authority

Phase-18 architecture and service semantics freeze:

```text
artifact_status_changed        False
task_status_changed            False
automatic_release_enabled      False
```

A trusted signature is not a release authorization.

---

## 2. Architectural goal

Add one narrow production-aware signing boundary that accepts an exact Blender production `DISPEXEC-*`, proves that it still names the exact Phase-51/52 relation whose Task was terminally accepted by Phase 53, derives the canonical adopted Artifact internally, and delegates signing to Phase 18.

Conceptually:

```text
sign_governed_blender_production_provenance(
    runtime,
    execution_id,
    certificate_id,
    *,
    operational_private_key_handle,
) -> GovernedBlenderProductionProvenanceResult
```

Exact naming may differ, but these semantics are frozen.

The public production identity is `DISPEXEC-*`. Callers do not supply Task IDs, Artifact IDs, adoption Verification IDs, Task Verification IDs, paths, hashes, byte counts, Run IDs, work-order IDs, MODEL3D IDs, acceptance status, or release flags.

---

## 3. Permanent authority boundary

### 3.1 What Phase 54 may do

Phase 54 may:

- validate one canonical `DISPEXEC-*`;
- read the exact Phase-51 Blender output binding;
- read the exact Phase-52 PUBLISHED adoption receipt;
- inspect exact Phase-53 acceptance currentness;
- read the exact Phase-53 acceptance receipt after terminal currentness is established;
- revalidate the canonical adopted GLB relation and current bytes;
- select the already-derived adopted Artifact ID as the Phase-18 signing target;
- accept an explicit existing Phase-18 `KEYCERT-*` certificate identity;
- accept an explicit external operational private-key handle;
- call the existing Phase-18 Artifact-signing service;
- inspect the signed manifest and Phase-18 freshness result;
- return a bounded typed result.

### 3.2 What Phase 54 may never do

Phase 54 must not:

- call `accept_artifact()`;
- change the adopted Artifact from `ADOPTED` to `ACCEPTED` or any other status;
- synthesize an `ARTIFACT_ACCEPTED` event;
- call `GovernedBlenderProductionTaskAcceptor.accept(...)`;
- recover or publish Phase-53 acceptance;
- create or rewrite Phase-52 adoption state;
- transition Task, Flow, or Goal state;
- create production Verifications;
- rerun Blender or any model/specialist/tool execution;
- rewrite, replace, move, or delete the adopted GLB;
- provision a Company Root identity;
- issue or revoke an operational certificate;
- generate a private key;
- copy private-key material into project state;
- expose a private-key handle to a model, specialist, Manager, browser, conversation, Tool Search, or provenance manifest;
- sign with the Company Root private key;
- grant merge, deploy, publish, or release authority;
- infer release authorization from a valid signature;
- create a generic production-signing bus;
- reuse Pixelorama acceptance/signing semantics implicitly.

---

## 4. Exact eligibility relation

A Blender production execution is Phase-54 signing-eligible only if all reviewed relations are exact and current.

### 4.1 Phase 51

The `DISPEXEC-*` must resolve to one exact Blender production output binding whose durable identities include:

```text
execution_id
claim_id
task_id
task_revision
task_content_hash
work_order_id / work_order_hash
dispatch_binding_id / dispatch_binding_hash
execution_owner_id == originforge.execution.blender.export-glb@1
run_id
output_artifact_id
output_verification_id
output_content_hash
output_byte_count
```

Existing Phase-51 readers/currentness remain authoritative. Phase 54 must not reconstruct production identity from filenames or newest-row heuristics.

### 4.2 Phase 52

The execution must resolve to one exact PUBLISHED Blender production adoption receipt.

Its canonical adopted Artifact must be exact:

```text
artifact.id              == adoption.adopted_artifact_id
artifact.type            == BLENDER_GLB_EXPORT
artifact.status          == ADOPTED
artifact.parent_artifact == Phase-51 output_artifact_id
artifact.created_by_run  == Phase-51 run_id
artifact.path_or_uri     == adoption.destination_path
artifact.content_hash    == sha256:<Phase-51 output_content_hash>
```

The Phase-52 adoption PASS Verification must remain exact and must name the same adopted Artifact/output relation.

No alternate Artifact may be selected because it has the same bytes, same path, same parent, or a later creation timestamp.

### 4.3 Phase 53

Phase 54 requires:

```text
BlenderProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
```

`NOT_ACCEPTED`, `ACCEPTED_PENDING_TASK_TRANSITION`, and `STALE_OR_CONFLICTING` are all non-signable.

Phase 54 does not call the acceptor to make an execution eligible. Signing is downstream of terminal acceptance, never a recovery path for acceptance.

The exact Phase-53 acceptance receipt and Task PASS Verification must name the same:

```text
execution_id
task_id
adopted_artifact_id
adoption_verification_id
accepted_destination_path
accepted_content_hash
accepted_byte_count
task_revision_at_acceptance
acceptance_authority == HUMAN_OPERATOR
```

The Task must remain the exact accepted terminal `SUCCEEDED` revision required by Phase-53 currentness.

---

## 5. Current GLB bytes are revalidated before signing

Terminal Task acceptance is necessary but is not a substitute for current-byte validation.

Immediately before Phase-18 signing, the governed signer must require that the canonical adopted destination:

- remains project-root confined;
- contains no symlink component;
- resolves to a regular file;
- has the exact accepted byte count;
- has the exact accepted SHA-256;
- remains a valid GLB under the existing Blender/GLB validation rules.

The Phase-18 builder then independently hashes the Artifact bytes again before constructing the manifest.

This deliberate double boundary is not duplicate acceptance logic:

```text
Phase 54 proves production eligibility/currentness
Phase 18 proves the Artifact bytes it is about to sign match durable Artifact truth
```

If bytes drift, signing fails closed. Phase 54 does not restore or overwrite them.

---

## 6. Phase-18 delegation boundary

After exact production eligibility is proven, Phase 54 delegates to the existing service conceptually as:

```text
ProvenanceService(runtime).sign_artifact(
    adopted_artifact_id,
    certificate_id,
    operational_private_key_handle=external_handle,
    parent_manifest_ids=(),
)
```

The implementation may inject an existing `ProvenanceService`/backend for tests, but Phase 54 does not fork or copy Phase-18 cryptographic policy.

### 6.1 No arbitrary parent provenance in v0

The initial Phase-54 surface does not accept browser/operator-supplied parent-manifest IDs.

`parent_manifest_ids` is fixed empty unless a later architecture defines an exact production-derived parent provenance relation.

This prevents Phase 54 from becoming an arbitrary provenance-claim compositor.

### 6.2 Existing trust policy remains authoritative

Phase 18 remains authoritative for:

- exactly one trusted Company Root;
- certificate loading;
- `ARTIFACT_SIGNING` purpose enforcement;
- Ed25519 algorithm rules;
- root/certificate identity matching;
- operational-key revocation;
- private-key handle containment and permissions;
- signature creation;
- signature-chain verification;
- immutable provenance-store publication.

Phase 54 must not implement a second cryptographic trust policy.

---

## 7. Signed manifest postconditions

A Phase-54 success result is valid only if the returned signed manifest still binds the exact production relation.

At minimum the implementation must prove:

```text
manifest.artifact_ref.record_id     == adopted_artifact_id
manifest.artifact_content_hash      == accepted_content_hash
manifest.artifact_type              == BLENDER_GLB_EXPORT
manifest.artifact_location          == adoption.destination_path
manifest.task_ref.record_id         == accepted task_id
manifest.run_ref.record_id          == production run_id
```

The manifest Verification refs must include the exact:

- Phase-52 adoption PASS Verification;
- Phase-53 Task acceptance PASS Verification.

The Artifact record ref must cryptographically pin the normalized Artifact row whose status is `ADOPTED`; Phase 54 does not need to mutate the row to make that status visible in provenance.

After persistence, Phase 54 should call the existing Phase-18 manifest inspection/freshness path and require the new manifest to be trusted and current before returning normal success.

A signature that is cryptographically valid but immediately stale must not be reported as a current governed production signature.

---

## 8. Result model

The typed result should expose only service-derived, bounded identities needed by an operator, conceptually:

```text
GovernedBlenderProductionProvenanceResult
- execution_id
- task_id
- adopted_artifact_id
- adopted_destination_path
- accepted_content_hash
- accepted_byte_count
- acceptance_verification_id
- manifest_id
- manifest_content_hash
- signing_certificate_id
- signing_key_id
- signature_hash
- trusted
- current
- artifact_status_changed      False
- task_status_changed          False
- production_verification_changed False
- release_authorized           False
```

Exact field names may differ.

The result does not include private-key bytes, private-key fingerprints derived from secret material, root private-key handles, or unbounded raw exceptions.

---

## 9. Replay, rotation, and idempotence semantics

Phase 18 intentionally creates a new `PROVMAN-*` identity and `created_at` for each signing invocation.

Phase 54 therefore does **not** add a one-manifest-per-execution receipt or pretend signing is semantically idempotent.

Repeated explicit signing of the same exact production result may create multiple immutable manifests. This supports legitimate cases such as:

- operational-key rotation;
- deliberate re-signing after trust configuration changes;
- distinct signed historical attestations over the same still-current Artifact.

The invariant is instead:

```text
each successful invocation signs the same exact current production truth
and mutates no production state
```

No retry/re-sign happens automatically after an exception, reconnect, startup, Manager tick, conversation event, or UI poll.

If a sign call persisted a manifest but a subsequent freshness check observes drift, the immutable historical manifest is not deleted or rewritten. The operation reports the non-current state and requires a later explicit operator decision after the underlying production truth is independently corrected/re-established.

---

## 10. Key and trust authority

Phase 54 is an explicit operator-triggered cryptographic action.

The operator supplies only:

```text
execution_id
certificate_id
operational_private_key_handle
```

The key handle remains deterministic host input and must obey all Phase-18 containment rules.

Models, specialists, Manager, conversation processing, browser polling, and background recovery cannot select the key, certificate, or signing target and cannot invoke signing automatically.

Company Root provisioning, operational certificate issuance, rotation, and revocation remain separate Phase-18 administrative responsibilities.

Phase 54 does not make a missing/misconfigured trust store valid by creating trust material on demand.

---

## 11. Failure model

Failures should be bounded and distinguish at least these classes without leaking secrets:

```text
INVALID_EXECUTION_ID
EXECUTION_NOT_CURRENT
ADOPTION_NOT_CURRENT
TASK_NOT_TERMINALLY_ACCEPTED
ADOPTED_ARTIFACT_DRIFT
PROVENANCE_TRUST_NOT_READY
SIGNING_REJECTED
SIGNED_MANIFEST_CONFLICT
SIGNED_MANIFEST_NOT_CURRENT
```

Exact enum names may differ.

Production-domain errors, OpenSSL stderr, filesystem details, and private-key diagnostics must be mapped to conservative operator-safe failures where necessary.

No failure path may broaden authority or perform production recovery automatically.

---

## 12. Security and adversarial acceptance matrix

Tests must prove at least:

- malformed/non-`DISPEXEC` input fails before signing;
- another project’s execution cannot be signed;
- a Pixelorama execution cannot enter the Blender path;
- an execution without Phase-52 PUBLISHED adoption cannot be signed;
- an execution with `NOT_ACCEPTED` Phase-53 currentness cannot be signed;
- `ACCEPTED_PENDING_TASK_TRANSITION` cannot be signed and is not auto-recovered;
- `STALE_OR_CONFLICTING` cannot be signed;
- a terminally accepted execution with modified/missing/symlinked adopted GLB fails closed;
- a same-content alternate Artifact cannot replace the canonical Phase-52 adopted Artifact;
- a mismatched Task/adoption/acceptance relation fails closed;
- the signed manifest targets the exact `ADOPTED` Artifact without changing its status;
- the exact Phase-52 adoption PASS and Phase-53 acceptance PASS are present in manifest Verification refs;
- the exact production Run/Task are present in manifest refs;
- current Artifact bytes equal the signed Artifact content hash;
- a non-`ARTIFACT_SIGNING` certificate is rejected by Phase-18 policy;
- an untrusted/mismatched/revoked certificate chain does not produce a successful governed result;
- an invalid or project-contained/symlink private-key handle is rejected by Phase-18 policy;
- no private-key bytes enter the database, Artifact records, manifests, logs, or result object;
- signing creates no new Run;
- signing creates no production Verification;
- signing does not transition Task/Flow/Goal state;
- signing does not change the `ADOPTED` Artifact record;
- signing does not rewrite the adopted GLB bytes;
- signing does not call Blender;
- signing does not call a model, specialist, Manager, acceptance service, or release path;
- signing does not call `accept_artifact()`;
- no `ARTIFACT_ACCEPTED` event is synthesized;
- a second explicit invocation may create a second immutable Phase-18 manifest while production state remains byte-for-byte/durable-state unchanged;
- no automatic signing/retry is reachable from Manager, conversation processing, GUI polling, or startup recovery.

---

## 13. Operator surface

The first operator surface is module-only and local, following the established bounded Blender administrative pattern rather than adding a generic installed command or browser authority.

Conceptually:

```text
python -m origin_forge.blender_admin_cli \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /absolute/external/key.pem
```

Exact option spelling may vary with the existing module conventions.

The command must not accept:

- Artifact ID;
- Task ID;
- Verification ID;
- destination path;
- expected hash/byte count;
- acceptance override;
- force/bypass;
- parent manifest IDs;
- root private-key handle;
- release/publish/deploy flag;
- model/tool/specialist selection.

No new package entrypoint is required in Phase 54.

A browser provenance-signing action is out of scope. If desired later, it requires its own reviewed action architecture and must never expose private-key paths to browser state.

---

## 14. Implementation gates

Phase 54 proceeds in three separately reviewable implementation slices after this planning PR.

### 54A — governed production provenance service

Implement only:

- exact `DISPEXEC-*` validation;
- Phase-51/52/53 currentness/identity composition;
- terminal `ACCEPTED_TASK_SUCCEEDED` requirement;
- canonical `ADOPTED` Artifact derivation;
- current GLB byte/hash/size validation;
- one reviewed Phase-18 `sign_artifact(...)` delegation site;
- exact signed-manifest relation checks;
- immediate Phase-18 trust/freshness inspection;
- bounded typed result/error projection;
- focused tests proving zero production-state mutation.

No CLI changes in 54A.

### 54B — module-only operator surface and adversarial hardening

Implement only:

- one bounded `blender_admin_cli sign-production-provenance` command;
- exact `execution-id + certificate-id + external private-key handle` input surface;
- no installed package entrypoint;
- wrong project/type/currentness/trust/key-purpose/key-path rejection;
- manifest-binding and Verification-ref assertions;
- explicit repeated-signing semantics;
- concurrency/drift tests where relevant;
- source-level guards proving no acceptance/release/model/Manager/browser authority.

### 54C — documentation closure

Documentation-only closure:

- implementation closure evidence;
- operator guide update;
- canonical roadmap Phase-54 DONE insertion;
- exact CI/merge evidence;
- no runtime/schema/config/packaging/UI mutation.

Each implementation gate requires the canonical Python 3.12/3.13 matrix on its exact final head before merge.

---

## 15. Explicit non-goals

Phase 54 does not add:

- Phase-18 schema/format redesign;
- a new signature algorithm;
- key generation;
- root trust provisioning;
- operational certificate issuance/revocation UI;
- Artifact lifecycle acceptance;
- production Task acceptance;
- Blender execution/adoption;
- Pixelorama provenance signing;
- generic multi-media signing dispatch;
- provenance parent-manifest selection;
- automatic signing after acceptance;
- background signing/recovery;
- signing from Manager/conversation/UI polling;
- remote signing service;
- HSM/keychain integration;
- transparency logs/trusted timestamping;
- release signing;
- merge/deploy/publish/release commands;
- automatic release authorization from provenance.

Those are separate architecture questions.

---

## 16. Planning PR acceptance gate

This architecture PR is documentation-only.

Allowed diff:

```text
docs/phase-54-governed-blender-production-provenance-signing.md
```

The exact planning head must pass the canonical Python 3.12/3.13 matrix before ready-for-review and SHA-guarded squash merge.

If `main` advances before merge, this architecture must be revalidated against the new base and a fresh exact-head matrix must authorize the merge. Stale CI is never sufficient.

Only after this architecture is accepted may 54A implementation begin.

---

## 17. Permanent invariant

> Phase 54 may cryptographically attest one exact current Blender production Artifact only after Phase 53 has terminally accepted its Task. The canonical Phase-52 Artifact remains `ADOPTED`; Phase 54 derives it from `DISPEXEC-*`, revalidates its current bytes, delegates signing to Phase 18, and grants no acceptance or release authority.
