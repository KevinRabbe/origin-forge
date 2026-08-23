# Phase 55 — Governed Pixelorama Production Provenance Signing

Status: **architecture gate**

Planning base: `b1e19cb904f6ce55d02b85badbfc4aad645c017c`

Phase 55 composes the already-governed Pixelorama production chain from Phases 48–50 with the existing Phase-18 cryptographic provenance service. It is the Pixelorama-specific counterpart to the accepted Phase-54 Blender production provenance boundary; it does **not** create a generic multi-media signing dispatcher, redesign cryptography, invent another production-acceptance authority, change the adopted production Artifact lifecycle state, or grant release authority.

The intended production path is:

```text
DISPEXEC-*                                public production identity
  ↓
Phase 48 reviewed Pixelorama production dispatch/execution
  ↓
Phase 49 immutable Pixelorama dispatch-output binding
  ↓
Phase 49 exact PUBLISHED production adoption
  ↓
canonical SPRITESHEET_EXPORT Artifact, status ADOPTED
  ↓
Phase 50 exact HUMAN_OPERATOR Task acceptance
  ↓
Task exact terminal state SUCCEEDED
  ↓
Phase 55 governed provenance eligibility/currentness
  ↓
Phase 18 ProvenanceService.sign_artifact(...)
  ↓
trusted signed provenance manifest
```

The signature proves authorship/integrity of the exact provenance claim. It does not make production correct, accepted, releasable, merged, deployed, or published.

---

## 1. Source-of-truth findings that freeze this design

### 1.1 Phase 49 creates the canonical Pixelorama production Artifact as `ADOPTED`

Current Phase-49 production adoption derives the source only from the immutable dispatch-output binding and publishes exact verified bytes create-only into one new canonical project destination.

The canonical adopted relation is:

```text
artifact.type             SPRITESHEET_EXPORT
artifact.status           ADOPTED
artifact.parent_artifact  exact Phase-49 bound output Artifact
artifact.created_by_run   exact production PIXELORAMA Run
artifact.path_or_uri      exact Phase-49 destination
artifact.content_hash     sha256:<bound output digest>
```

The Phase-49 PUBLISHED receipt and production-adoption PASS Verification bind that exact relation. Existing adoption evidence explicitly records:

```text
production_dispatch_output_bound = true
production_task_verified          = false
semantic_visual_quality_verified  = false
provenance_signed                 = false
existing_asset_overwritten        = false
```

`ADOPTED` is production truth. Phase 55 must not call generic `accept_artifact()` or change that lifecycle state merely to sign provenance.

### 1.2 Phase 50 is the semantic production-acceptance authority

Current `GovernedPixeloramaProductionTaskAcceptor` accepts only one exact `DISPEXEC-*` relation and terminalizes the already-governed production Task through the existing runtime transition.

The immutable Phase-50 acceptance relation binds:

```text
execution_id
production Task
adopted Artifact
Phase-49 adoption Verification
Phase-50 Task PASS Verification
accepted destination
accepted content hash
accepted byte count
acceptance_authority == HUMAN_OPERATOR
```

Its currentness projection has one terminal accepted state:

```text
PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
```

Phase 55 is downstream of that state. It may never call the acceptor, publish acceptance, recover a pending Task transition, or infer semantic acceptance from structural output/adoption evidence.

### 1.3 Current Pixelorama currentness already proves the exact canonical PNG relation

Phase-50 currentness revalidates the exact Phase-49 binding and PUBLISHED adoption, requires the canonical adopted Artifact to remain:

```text
type            SPRITESHEET_EXPORT
status          ADOPTED
parent          exact bound output Artifact
run             exact production Run
path            exact adopted destination
content_hash    exact accepted SHA-256
```

It also reopens the canonical destination under project-root/symlink protections and requires the current bytes to match the exact bound hash and byte count and remain valid RGBA8 PNG.

Phase 55 may reuse these durable readers/currentness semantics, but signing still performs its own immediate current-byte validation before delegating to Phase 18. Terminal historical acceptance is not permission to sign drifted bytes.

### 1.4 The reviewed Pixelorama production owner is exact and media-specific

The immutable dispatch-output binding freezes:

```text
execution_owner_id = originforge.execution.pixelorama.spritesheet-export@1
```

The binding also carries the exact DISPEXEC, claim, Task revision/content hash, WorkOrder/hash, dispatch binding/hash, Run, request/result/output Artifacts, output/run Verifications, output digest, and output byte count.

Phase 55 must resolve production identity through those existing Pixelorama readers. It must not infer media type from a file extension, Artifact type alone, newest-row selection, or same-content coincidence.

### 1.5 Phase 18 already provides the required cryptographic primitive

Current `ProvenanceService.sign_artifact(...)`:

- requires the project to trust exactly one Company Root;
- loads an explicit existing `KEYCERT-*` certificate;
- builds a canonical provenance manifest from durable project lineage;
- independently revalidates the current Artifact bytes;
- signs using an explicitly supplied operational private-key handle;
- permits only an `ARTIFACT_SIGNING` operational certificate for manifest signing;
- requires the private key to match the certified public key;
- verifies the resulting trust chain before persistence;
- publishes immutable provenance state only after the new signature is trusted;
- does not change Artifact, Task, production Verification, Flow, Goal, or release state.

Phase 55 must delegate to this service rather than copying Phase-18 cryptographic policy.

### 1.6 Phase 54 is a composition precedent, not a shared media authority

Phase 54 proved that a production-aware signer can sit downstream of terminal human Task acceptance, derive one canonical `ADOPTED` Artifact from a media-specific `DISPEXEC-*`, revalidate current bytes, delegate exactly once to Phase 18, verify the returned manifest, and leave production state unchanged.

Phase 55 follows those authority principles for Pixelorama but does not route Pixelorama through the Blender signer and does not refactor both into a generic production-signing bus in this phase.

The media-specific validators and durable relations remain independently authoritative:

```text
Blender     → BLENDER_GLB_EXPORT / GLB validation / Blender lineage
Pixelorama  → SPRITESHEET_EXPORT / RGBA8 PNG validation / Pixelorama lineage
```

### 1.7 There is no installed Pixelorama signing command today

Current installed package scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Current `origin_forge.pixelorama_admin_cli` is module-only and exposes:

```text
adopt-new
adopt-production-new
accept-production-task
```

There is no Pixelorama provenance-signing command and no fourth package entrypoint. Phase 55B may extend this existing module-only administrative family after 55A is accepted; Phase 55 does not add an installed script.

---

## 2. Architectural goal

Add one narrow Pixelorama-production-aware signing boundary that accepts one exact `DISPEXEC-*`, proves that it still names the exact Phase-48/49 production relation whose Task was terminally accepted by Phase 50, derives the canonical adopted `SPRITESHEET_EXPORT` internally, revalidates the current PNG bytes, and delegates signing to Phase 18.

Conceptually:

```text
sign_governed_pixelorama_production_provenance(
    runtime,
    execution_id,
    certificate_id,
    *,
    operational_private_key_handle,
) -> GovernedPixeloramaProductionProvenanceResult
```

Exact implementation naming may differ, but these semantics are frozen.

The public production identity is `DISPEXEC-*`. Callers do not supply Task IDs, Artifact IDs, adoption Verification IDs, Task Verification IDs, paths, hashes, byte counts, Run IDs, WorkOrder IDs, dispatch-binding IDs, acceptance status, media type, or release flags.

---

## 3. Permanent authority boundary

### 3.1 What Phase 55 may do

Phase 55 may:

- validate one canonical `DISPEXEC-*`;
- read the exact immutable Phase-49 Pixelorama dispatch-output binding;
- prove the reviewed Pixelorama execution owner;
- read the exact Phase-49 PUBLISHED production-adoption receipt;
- inspect exact Phase-50 Task-acceptance currentness;
- read the exact Phase-50 acceptance receipt only after terminal currentness is established;
- derive the exact canonical `ADOPTED` `SPRITESHEET_EXPORT` from durable production identity;
- revalidate the exact canonical destination and current RGBA8 PNG bytes;
- select that already-derived adopted Artifact ID as the Phase-18 signing target;
- accept one explicit existing Phase-18 `KEYCERT-*` certificate identity;
- accept one explicit external operational private-key handle;
- call the existing Phase-18 Artifact-signing service;
- inspect the signed manifest and Phase-18 freshness result;
- return one bounded typed result.

### 3.2 What Phase 55 may never do

Phase 55 must not:

- call `accept_artifact()`;
- change the adopted Artifact from `ADOPTED` to `ACCEPTED` or any other status;
- synthesize an `ARTIFACT_ACCEPTED` event;
- call `GovernedPixeloramaProductionTaskAcceptor.accept(...)`;
- publish, repair, or recover Phase-50 acceptance;
- create, rewrite, repair, or recover Phase-49 adoption state;
- transition Task, Flow, or Goal state;
- create production Verifications;
- rerun Pixelorama or any model/specialist/tool production execution;
- rewrite, replace, move, delete, optimize, or re-encode the adopted PNG;
- provision a Company Root identity;
- issue or revoke an operational certificate;
- generate a private key;
- copy private-key material into project state;
- expose a private-key handle to a model, specialist, Manager, browser, conversation, Tool Search, or provenance manifest;
- sign with the Company Root private key;
- grant merge, deploy, publish, or release authority;
- infer release authorization from a valid signature;
- create a generic production-signing owner registry, bus, plugin surface, or media dispatcher;
- reuse Blender acceptance/currentness as Pixelorama truth;
- treat a Blender execution as Pixelorama because an Artifact/path/hash appears compatible.

---

## 4. Exact signing-eligibility relation

A Pixelorama production execution is Phase-55 signing-eligible only when every reviewed durable relation is exact and current.

### 4.1 Exact dispatch/output identity

The `DISPEXEC-*` must resolve through the existing Pixelorama binding reader to exactly one immutable production output binding containing at least:

```text
execution_id
claim_id
task_id
task_revision
task_content_hash
work_order_id
work_order_hash
dispatch_binding_id
dispatch_binding_hash
execution_owner_id == originforge.execution.pixelorama.spritesheet-export@1
run_id
request_artifact_id
result_artifact_id
output_artifact_id
output_verification_id
run_verification_id
output_content_hash
output_byte_count
```

The execution must remain the exact reviewed returned/consumed production relation required by existing Pixelorama currentness.

No production identity may be reconstructed from Task metadata, filename, destination, Run-only lookup, Artifact-only lookup, same bytes, or latest-row heuristics.

### 4.2 Exact Phase-49 PUBLISHED adoption

The execution must resolve to one exact PUBLISHED Pixelorama production-adoption receipt.

The canonical adopted Artifact must remain exact:

```text
artifact.id              == adoption.adopted_artifact_id
artifact.type            == SPRITESHEET_EXPORT
artifact.status          == ADOPTED
artifact.parent_artifact == binding.output_artifact_id
artifact.created_by_run  == binding.run_id
artifact.path_or_uri     == adoption.destination_path
artifact.content_hash    == sha256:<binding.output_content_hash>
```

The exact Phase-49 production-adoption PASS Verification must still target the same adopted Artifact and bind the same execution/output relation.

A same-content or same-path alternate Artifact is not equivalent and must not become a signing target.

### 4.3 Exact terminal Phase-50 human Task acceptance

Phase 55 requires exactly:

```text
PixeloramaProductionTaskAcceptanceCurrentnessStatus.ACCEPTED_TASK_SUCCEEDED
```

The following are all non-signable:

```text
NOT_ACCEPTED
ACCEPTED_PENDING_TASK_TRANSITION
STALE_OR_CONFLICTING
```

Signing is downstream of terminal acceptance and may not call the acceptor to make an execution eligible.

The Phase-50 acceptance receipt and Task PASS Verification must name the same:

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

The Task must remain the exact accepted terminal `SUCCEEDED` state/revision required by Phase-50 currentness.

---

## 5. Current PNG bytes are revalidated immediately before signing

Terminal Task acceptance is necessary but not sufficient for a current governed signature.

Immediately before Phase-18 signing, the governed Pixelorama signer must require that the canonical adopted destination:

- remains under the exact project root;
- contains no symlink component;
- resolves to a regular file;
- has the exact accepted byte count;
- has the exact accepted SHA-256;
- remains valid under the existing `inspect_rgba8_png(...)` validation rules;
- remains the exact canonical destination from the Phase-49/50 relation.

Phase 55 does not restore or rewrite bytes to make this validation pass.

The Phase-18 manifest builder then independently hashes the Artifact bytes before constructing the provenance manifest. This double boundary is deliberate:

```text
Phase 55 proves Pixelorama production eligibility/currentness
Phase 18 proves the Artifact bytes it is about to attest match durable Artifact truth
```

---

## 6. Phase-18 delegation boundary

After exact Pixelorama production eligibility is proven, Phase 55 delegates conceptually as:

```text
ProvenanceService(runtime).sign_artifact(
    adopted_artifact_id,
    certificate_id,
    operational_private_key_handle=external_handle,
    parent_manifest_ids=(),
)
```

Tests may inject the existing `ProvenanceService`/backend, but production code must not fork the cryptographic policy.

### 6.1 Parent provenance remains closed

The Phase-55 surface does not accept caller-, browser-, Manager-, or model-selected parent-manifest IDs.

`parent_manifest_ids` is fixed empty unless a later separately reviewed architecture defines an exact production-derived provenance-parent relation.

### 6.2 Existing trust policy remains authoritative

Phase 18 remains authoritative for:

- exactly one trusted Company Root;
- certificate identity/loading;
- `ARTIFACT_SIGNING` purpose enforcement;
- Ed25519 rules;
- root/certificate identity matching;
- operational-key revocation;
- private-key handle containment and permissions;
- private-key/certificate public-key matching;
- signature creation;
- trust-chain verification;
- immutable provenance-store publication;
- manifest freshness verification.

Phase 55 must not implement a second trust policy.

---

## 7. Signed-manifest postconditions

A normal Phase-55 success result is valid only if the newly signed manifest binds the same exact production relation.

At minimum the implementation must prove:

```text
manifest.artifact_ref.record_id  == adopted_artifact_id
manifest.artifact_content_hash   == accepted_content_hash
manifest.artifact_type           == SPRITESHEET_EXPORT
manifest.artifact_location       == accepted_destination_path
manifest.task_ref.record_id      == accepted task_id
manifest.run_ref.record_id       == exact production run_id
```

The manifest Verification refs must include the exact:

- Phase-49 production-adoption PASS Verification;
- Phase-50 production Task-acceptance PASS Verification.

The Artifact record ref must cryptographically pin the normalized canonical Artifact row whose lifecycle status remains `ADOPTED`.

`manifest.parent_manifest_refs` must remain empty in Phase 55.

After persistence, the signer must call the existing Phase-18 manifest inspection/freshness path and require the new manifest to be trusted and current before returning normal success.

A cryptographically valid but immediately stale manifest is immutable historical evidence; it must not be reported as a current governed production signature, deleted, rewritten, or used to repair production state.

---

## 8. Zero production-state mutation proof

Signing must not alter governed production truth.

The implementation must take a bounded production-state snapshot before Phase-18 signing and prove the same snapshot remains exact afterward. At minimum the proof covers:

- production Task row/status/revision;
- canonical adopted Artifact row/status/path/hash;
- Task/Artifact production Verifications relevant to the exact relation.

Normal provenance-store additions are expected and are not production-state mutation.

A success result must expose fixed false authority indicators analogous to:

```text
artifact_status_changed          false
task_status_changed              false
production_verification_changed  false
release_authorized               false
```

---

## 9. Result model

The bounded typed service result should expose only service-derived identities needed for audit/operator confirmation, conceptually:

```text
GovernedPixeloramaProductionProvenanceResult
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
- artifact_status_changed          False
- task_status_changed              False
- production_verification_changed  False
- release_authorized               False
```

Exact field names may differ.

The result must not contain private-key bytes, root private-key handles, unbounded OpenSSL diagnostics, or secret-derived material not already part of the existing public certificate/signature model.

---

## 10. Replay, rotation, and idempotence semantics

Phase 18 intentionally creates a fresh `PROVMAN-*` identity and timestamp for each explicit signing invocation.

Phase 55 therefore does not add a one-manifest-per-execution receipt and must not pretend signing is semantically idempotent.

Repeated explicit signing of the same exact current accepted Pixelorama production result may create multiple immutable manifests. This is allowed for deliberate operator-driven cases such as operational-key rotation or re-attestation under current trust configuration.

The invariant is:

```text
each successful invocation signs the same exact current Pixelorama production truth
and mutates no production state
```

No retry or re-signing occurs automatically after exception, reconnect, process startup, Manager tick, conversation event, browser poll, or recovery path.

---

## 11. Key and invocation authority

Phase 55 is explicit human/operator-triggered cryptographic administration.

The operator may supply only:

```text
execution_id
certificate_id
operational_private_key_handle
```

All production identities beyond `execution_id` are derived internally.

The private-key handle is host-local deterministic input and remains subject to all Phase-18 containment rules. The project does not store the private key.

Models, vision, specialists, Manager, conversation processing, browser/UI, and background recovery cannot select the key, certificate, Artifact, or signing target and cannot invoke signing automatically.

Company Root provisioning, operational certificate issuance/rotation/revocation, and key lifecycle remain separate Phase-18 administrative responsibilities.

---

## 12. Failure model

Failures must be bounded and must not leak private-key material or raw unbounded backend diagnostics.

The service should distinguish at least these semantic classes where useful:

```text
INVALID_EXECUTION_ID
TASK_NOT_TERMINALLY_ACCEPTED
ADOPTED_ARTIFACT_DRIFT
PROVENANCE_TRUST_NOT_READY
SIGNING_REJECTED
SIGNED_MANIFEST_CONFLICT
SIGNED_MANIFEST_NOT_CURRENT
```

Exact enum names may differ.

Existing reader/currentness failures may be conservatively projected into those public classes rather than exposing internal filesystem/database detail.

No failure path may broaden authority, recover acceptance, republish adoption, rerun Pixelorama, rewrite the canonical asset, provision trust, or authorize release.

---

## 13. Security and adversarial acceptance matrix

Tests must prove at least:

- malformed/non-`DISPEXEC` input fails before signing;
- another project’s execution cannot be signed;
- a real Blender production execution cannot enter the Pixelorama signing path;
- the reviewed Pixelorama execution owner is required;
- missing/tampered immutable Pixelorama binding fails closed;
- an execution without exact Phase-49 PUBLISHED adoption cannot be signed;
- a same-content alternate Artifact cannot replace the canonical Phase-49 adopted Artifact;
- wrong adoption Verification identity fails closed;
- `NOT_ACCEPTED` Phase-50 currentness cannot be signed;
- `ACCEPTED_PENDING_TASK_TRANSITION` cannot be signed and is not auto-recovered;
- `STALE_OR_CONFLICTING` cannot be signed;
- terminally accepted Task relation with mismatched receipt/Verification fails closed;
- modified, missing, non-file, escaped, or symlinked canonical adopted destination fails closed;
- malformed/non-RGBA8 PNG canonical bytes fail closed even if other metadata is manipulated;
- current PNG hash/byte count must equal the accepted relation;
- signed manifest targets exactly the canonical `ADOPTED` `SPRITESHEET_EXPORT`;
- exact Phase-49 adoption PASS and Phase-50 acceptance PASS are present in manifest Verification refs;
- exact production Task and Run are present in manifest refs;
- parent manifest refs remain empty;
- non-`ARTIFACT_SIGNING` certificates, including `RELEASE_SIGNING`, are rejected by Phase-18 policy;
- untrusted, mismatched, or revoked certificate/key relations do not produce normal success;
- invalid, project-contained, or symlink private-key handles are rejected by existing Phase-18 policy;
- no private-key bytes enter database records, Artifact records, manifests, logs, or result objects;
- signing creates no new production Run;
- signing creates no production Verification;
- signing does not change Task, Flow, or Goal state;
- signing does not change the `ADOPTED` Artifact row;
- signing does not rewrite the canonical PNG bytes;
- signing does not invoke Pixelorama;
- signing does not call a model, vision service, specialist, Manager, Task acceptor, adoption coordinator, or release path;
- signing does not call `accept_artifact()`;
- no `ARTIFACT_ACCEPTED` event is synthesized;
- a second explicit invocation may create a second immutable Phase-18 manifest while governed production state remains unchanged;
- the installed package script set remains exactly the existing three scripts;
- no automatic signing/retry is reachable from Manager, conversation processing, browser/UI polling, startup, recovery, or dispatch completion.

---

## 14. Operator surface

After the service gate is accepted, the operator surface remains module-only under the existing Pixelorama administrative family.

Conceptually:

```text
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /absolute/external/key.pem
```

The signing subcommand should follow the already-accepted Phase-54 explicit option shape even though older Pixelorama adoption/acceptance subcommands use positional execution identities. This keeps secret-bearing cryptographic administration unambiguous and makes the three authorized signing inputs visible at the parser boundary.

The command must not accept:

- Artifact ID;
- Task ID;
- Run ID;
- Verification ID;
- destination/source path;
- expected hash/byte count;
- acceptance override;
- force/bypass/overwrite;
- parent manifest IDs;
- root private-key handle;
- key-generation/certificate-issuance inputs;
- media selector;
- release/publish/deploy flag;
- model/tool/specialist selection.

No new installed package entrypoint is allowed in Phase 55.

A browser/HTTP provenance-signing action is out of scope and would require a separate reviewed architecture. Browser state must never receive a host private-key path.

---

## 15. Implementation gates

Phase 55 proceeds in three separately reviewable slices after this planning PR is accepted.

### 55A — governed Pixelorama production provenance service

Implement only:

- a narrow Pixelorama-specific production provenance signer, expected at `src/origin_forge/production_pixelorama_provenance_signer.py`;
- exact `DISPEXEC-*` validation;
- immutable Pixelorama binding/owner proof;
- Phase-49 PUBLISHED adoption identity composition;
- terminal Phase-50 `ACCEPTED_TASK_SUCCEEDED` requirement;
- canonical `ADOPTED` `SPRITESHEET_EXPORT` derivation;
- current project-contained RGBA8 PNG byte/hash/size validation;
- one reviewed Phase-18 `sign_artifact(...)` delegation site;
- exact signed-manifest Artifact/Task/Run/Verification relation checks;
- fixed-empty parent-manifest semantics;
- immediate Phase-18 trust/freshness inspection;
- bounded typed result/error projection;
- focused tests proving zero production-state mutation and real Blender cross-media rejection.

55A must not modify CLI, package entrypoints, schema, config, workflows, acceptance/adoption services, or Phase-18/54 cryptographic policy.

### 55B — module-only operator surface and adversarial hardening

Implement only:

- one bounded `pixelorama_admin_cli sign-production-provenance` command;
- exact `--execution-id + --certificate-id + --operational-private-key` signing input surface;
- no installed package entrypoint;
- wrong project/media/currentness/trust/key-purpose/key-path rejection;
- manifest-binding and exact Verification-ref assertions;
- repeated explicit signing semantics;
- drift/concurrency tests where relevant without inventing automatic recovery;
- package/parser/source-level guards proving no acceptance/release/model/Manager/browser authority.

55B must not redesign older Pixelorama command grammar beyond adding this one signing subcommand.

### 55C — documentation closure

Documentation-only closure:

- Phase-55 implementation closure evidence;
- operator-guide update;
- canonical roadmap Phase-55 DONE insertion immediately before the v1.0 milestone;
- exact accepted CI/merge evidence;
- no runtime/schema/config/packaging/workflow/UI mutation.

Each gate requires the canonical repository-wide Python 3.12/3.13 matrix with `ResourceWarning` treated as error on its exact final head before merge.

---

## 16. Explicit non-goals

Phase 55 does not add:

- Phase-18 schema/format redesign;
- a new cryptographic algorithm;
- a new provenance store;
- Company Root provisioning;
- operational key generation;
- certificate issuance/revocation UI;
- HSM/keychain/remote-signing integration;
- Artifact lifecycle acceptance;
- Pixelorama production Task acceptance;
- Pixelorama execution or adoption;
- Blender provenance changes;
- a generic Blender+Pixelorama media-signing abstraction;
- generic production-signing dispatch;
- parent provenance selection/composition;
- automatic signing after acceptance;
- background signing/recovery;
- signing from Manager, conversation processing, browser, or UI polling;
- release signing;
- release authorization from provenance;
- merge/deploy/publish/release commands;
- canonical asset rewrite/optimization/re-encoding;
- a fourth installed CLI script;
- schema/config/workflow changes merely to expose signing.

Those remain separate architecture questions.

---

## 17. Planning PR acceptance gate

This architecture PR is documentation-only.

Allowed diff:

```text
docs/phase-55-governed-pixelorama-production-provenance-signing.md
```

It must not modify roadmap state yet; Phase 55 becomes DONE only in 55C after implementation acceptance.

The exact planning head must pass the canonical Python 3.12/3.13 matrix with `ResourceWarning` treated as error before ready-for-review and SHA-guarded squash merge.

Before merge, revalidate:

- current `main` still equals the planning base or the architecture has been explicitly revalidated against the new base;
- candidate is not behind `main`;
- diff is exactly the one allowed architecture document;
- no unresolved review/comment authority blockers exist;
- the CI run belongs to the exact head being merged.

Only after this architecture is accepted on `main` may 55A implementation begin.

---

## 18. Permanent invariant

> Phase 55 may cryptographically attest one exact current Pixelorama production Artifact only after Phase 50 has terminally accepted its Task. The canonical Phase-49 `SPRITESHEET_EXPORT` remains `ADOPTED`; Phase 55 derives it from the immutable media-specific `DISPEXEC-*` relation, revalidates the current RGBA8 PNG bytes, delegates signing to Phase 18 with an explicit external operational key, leaves governed production state unchanged, and grants no acceptance, generic media-dispatch, or release authority.
