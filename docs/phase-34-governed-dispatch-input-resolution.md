# Phase 34 — Governed Dispatch Input Resolution & Binding

Status: **PLANNED — post-Phase-33 architecture contract**

Phase 34 closes the evidence-resolution gap between an audited/current Phase-33 WorkOrder and any future production coordinator.

Phase 31 can determine dependency readiness. Phase 32 can select one exact trusted adapter for a canonical Task. Phase 33 can freeze and independently audit the exact bounded WorkOrder that adapter is allowed to receive. But most media/runtime adapters still require exact phase-specific typed request/spec/profile/source objects that cannot safely be reconstructed from generic strings or paths at dispatch time.

Core rule:

```text
audited/current WORKORD
+ exact WorkOrderInputRefs
+ code-owned resolver registry
+ exact dispatch contract
        ↓
resolved canonical evidence bundle
        ↓
code-owned typed dispatch binder
        ↓
exact backend-native request projection
        ↓
independent binding audit/currentness
        ↓
STOP
```

Phase 34 may resolve evidence and construct typed backend request objects/projections. It may not invoke the backend, start production execution, transition a Task, or grant completion authority.

---

## 1. New infrastructure identities

Phase 34 introduces:

```text
INRES-*     immutable resolved WorkOrder input bundle
DISPBIND-*  immutable typed dispatch binding
BINDAUD-*   independently recomputed dispatch-binding audit
```

All IDs are infrastructure-owned opaque IDs using the existing typed-ID contract.

---

## 2. Resolution is not execution

A Phase-34 resolver may:

- load one exact evidence object already named by a `WorkOrderInputRef`;
- prove project ownership and expected evidence class;
- revalidate exact ID/hash/revision/currentness semantics;
- return one bounded canonical projection required by a trusted binder;
- record its own resolver ID/fingerprint and source binding.

A resolver may not:

- search arbitrary paths or registries for a substitute object;
- choose another ref when the requested ref is missing/stale;
- execute a process/model/tool/backend;
- load a model or acquire a resource lease;
- mutate the source evidence;
- transition Goal/Flow/Task/Run state;
- adopt/sign an Artifact;
- perform arbitrary SQL/filesystem/network access supplied by the caller/model.

Resolution failure is fail-closed evidence, not permission to improvise.

---

## 3. Exact resolver contracts

Define a code-owned `WorkOrderInputResolver` contract with at least:

```text
resolver_id
resolver_fingerprint
supported_ref_types
supported_roles / evidence families
resolve(...)
```

The registry is infrastructure-owned and populated only with already-imported resolver implementations. Persisted/model-visible objects contain IDs and fingerprints, never import paths, callables, source code, shell, argv, environment, endpoint, credentials, or dynamic plugin metadata.

`WorkOrderInputResolverRegistry` must:

- reject duplicate resolver IDs;
- reject overlapping ambiguous claims for the same exact ref family/role unless an explicit deterministic selection rule is frozen in infrastructure;
- bind exact resolver fingerprint before use;
- expose deterministic inventory order;
- provide no fallback to unregistered readers;
- never dynamically import a resolver named in evidence/model output.

---

## 4. `PHASE_SPECIFIC_EVIDENCE` is not a generic escape hatch

Phase 33 intentionally includes `PHASE_SPECIFIC_EVIDENCE` as a finite ref type. Phase 34 must narrow it.

A `PHASE_SPECIFIC_EVIDENCE` ref is resolvable only when:

1. its exact ID family/prefix is explicitly claimed by a code-owned resolver;
2. the WorkOrder role is explicitly allowed by that resolver and selected dispatch contract/binder;
3. the exact object is independently loaded from its canonical protected store/read boundary;
4. project ownership/containment is proven;
5. content hash and revision/currentness semantics match the frozen ref;
6. the resolver emits only the bounded safe projection frozen by its contract.

Unknown IDs, unknown protected stores, arbitrary paths/URIs, ambiguous evidence classes, or generic JSON files fail closed.

---

## 5. `ResolvedWorkOrderInput`

Each resolved input binds at minimum:

```text
original WorkOrderInputRef
resolver_id
resolver_fingerprint
source_object_type
source_id
source_content_hash
source_revision (when applicable)
resolution_class
canonical_projection
canonical_projection_hash
currentness_class
```

The projection must contain only the subset required by the later typed binder. It is not permission to disclose arbitrary Artifact bytes, Verification evidence, secrets, model weights, executable paths, environment variables, or complete protected-store records.

The canonical projection must be bounded, finite JSON-compatible evidence even when the trusted binder later reconstructs a Python typed request object from it.

---

## 6. `INRES-*` input-resolution bundle

One immutable `InputResolutionBundle` binds:

```text
INRES ID
WORKORD ID/hash
WORKAUD ID/hash
Task ID/revision/hash
CAPROUTE ID/hash
selected adapter ID/fingerprint
DISPCAT ID/hash
contract ID/hash
ordered resolved inputs
resolver-registry fingerprint
bundle content hash
```

Creation requires an independently valid frozen `WORKAUD PASS` and a WorkOrder whose exact refs can all be resolved. There is no partial trusted bundle: if one required ref fails, no `INRES-*` is published.

Historical frozen validity and live currentness remain separate. A valid historical bundle may later become stale without being rewritten.

---

## 7. Core canonical resolvers

The first implementation should review and, where exact existing read boundaries permit, add resolvers for Phase-33 ref types such as:

```text
ARTIFACT
VERIFICATION
PROJECT_ENTITY
DESIGN_RULE
AUDIO_PROFILE
MEDIA_PROFILE
SIMULATION_SPEC
PLAYTEST_SCENARIO
PHASE_SPECIFIC_EVIDENCE
```

Acceptance is evidence-driven, not catalog-completeness-driven.

For SQLite-backed canonical state, use a bounded project-scoped read path and explicit projections rather than generic SQL supplied by a caller/model.

For protected phase-specific stores, reuse or factor their existing canonical/hash/symlink-safe read logic. Do not weaken a phase's own validator merely to make it resolvable.

If an evidence family lacks a safe independent reader or stable canonical projection, it remains unsupported.

---

## 8. Typed dispatch binders

Define a code-owned `DispatchInputBinder` contract with at least:

```text
binder_id
binder_fingerprint
adapter_id
contract_id
accepted resolution roles/families
request_type_id
request_schema_hash
bind(...)
```

The binder registry is infrastructure-owned and already-imported. There is no model/caller-selected import path or callable.

A binder receives only:

- exact audited WorkOrder;
- exact `INRES-*` resolved inputs;
- infrastructure-owned protected configuration explicitly allowed by that binder;
- exact selected adapter/dispatch contract identity.

It produces one exact backend-native typed request object or a canonical request projection from which that typed object is deterministically reconstructable.

The binder may not invoke the adapter.

---

## 9. `DISPBIND-*` dispatch binding

A `DispatchBinding` freezes at minimum:

```text
DISPBIND ID
WORKORD ID/hash
WORKAUD ID/hash
INRES ID/hash
Task/Flow identity
CAPROUTE ID/hash
adapter ID/fingerprint
DISPCAT ID/hash
contract ID/hash
binder ID/fingerprint
request type ID
request schema hash
canonical typed-request projection
request content hash
```

A binding is evidence that infrastructure can construct the exact adapter request. It is not an execution permit and does not imply the backend is currently installed/available or that resources are currently admissible.

---

## 10. Independent `BINDAUD-*`

`BindingAudit` independently reloads/revalidates:

- frozen `WORKORD-*` and `WORKAUD-*`;
- every original WorkOrder ref;
- exact resolver selection/fingerprints;
- `INRES-*` projections/hashes;
- exact Phase-32/33 adapter/contract relation;
- exact binder selection/fingerprint/schema;
- deterministic typed-request reconstruction/hash.

A forged audit status or self-consistently rehashed forged binding must fail when independent recomputation differs.

The audit may return `PASS` / `FAIL` frozen structural evidence only. It cannot execute the adapter or complete the Task.

---

## 11. Currentness

Live dispatch-binding currentness is separate from historical frozen validity.

A binding is currently eligible for a later coordinator only when all required facts are still true:

```text
Phase-33 WORKAUD still valid
Phase-33 WorkOrder currentness = CURRENT_READY
Task revision/hash unchanged
Phase-31 dependencies READY
Phase-32 route still current and ROUTABLE
Phase-32 catalog/policy relation still valid
Phase-33 dispatch catalog/contract still exact
every current-sensitive input ref still current
resolver registry identities unchanged
binder identity/schema unchanged
BINDAUD PASS still independently recomputes
```

Currentness inspection must be read-only and must not "refresh" a stale binding in place. A changed Task/ref requires a new upstream route/WorkOrder/resolution/binding chain.

---

## 12. Built-in binding review

Phase 34 should revisit the Phase-33 deferred built-in adapters one by one:

```text
originforge.pixelorama.export
originforge.blender.model3d
originforge.image.generate
originforge.vision.inspect
originforge.audio.ffmpeg
originforge.audio.piper
originforge.runtime.observe
originforge.playtest.cooperative
originforge.simulation.deterministic
```

For each backend, add a Phase-33 dispatch contract plus Phase-34 resolver/binder only when the existing typed API can be reconstructed completely from exact governed evidence and infrastructure-owned configuration without introducing generic executable authority.

The review should prefer the smallest provable subset. Unsupported adapters remain explicitly deferred.

`originforge.code.bounded-retry` remains valid and may gain a trivial zero-ref binder first to prove the end-to-end contract.

`design.specify` has no Phase-32 executor and therefore cannot become dispatch-bindable.

Blockbench remains absent while Phase 20B is deferred.

---

## 13. Persistence

Use one protected immutable no-overwrite evidence representation, preferably:

```text
.origin-forge/production-dispatch-bindings/
├── input-resolutions/
├── bindings/
└── audits/
```

Required guarantees:

- strict canonical UTF-8 JSON;
- duplicate-key rejection;
- typed IDs and content hashes;
- bounded object bytes/counts;
- no-overwrite atomic publication;
- project/root/symlink/alias containment;
- exact upstream relation validation;
- resolver/binder fingerprint revalidation;
- independent resolution/binding/audit recomputation on load;
- deterministic restart reconstruction;
- no mutable dispatch queue or alternate Task-status truth.

---

## 14. Read-only inspection

Provide a non-creating inspection facade using the Phase-30 immutable SQLite guard and protected immutable-file reads.

A possible module CLI is limited to:

```text
status
input-resolution-show
binding-show
binding-audit-show
binding-currentness
```

No model-generation, resolution-publication, binding-publication, audit-publication, dispatch, execute, retry, Task-transition, adoption, signing, merge, or release command belongs on this read-only surface.

Uninitialized inspection must create no `.origin-forge` state. Initialized inspection must leave SQLite and all protected evidence bytes unchanged.

---

## 15. Model boundary

Phase 34 does not require a new model role.

Phase 33 already permits a bounded model to propose inert WorkOrder payload/ref selection. Resolution and typed binding are infrastructure-deterministic operations. A model must not choose resolver implementations, binder implementations, evidence-reader paths, backend constructors, resource/runtime instances, or executable configuration.

---

## 16. Security/adversarial requirements

Tests must prove at minimum:

- unknown/ref-type/role/prefix mismatch fails before trusted resolution;
- cross-project evidence fails closed;
- hash/revision/currentness drift is explicit;
- arbitrary path/URI evidence cannot be smuggled through `PHASE_SPECIFIC_EVIDENCE`;
- resolver IDs/fingerprints cannot be caller/model substituted;
- dynamic import/callback/entry-point discovery is absent;
- two resolvers cannot ambiguously claim one exact ref family;
- partial resolution failure publishes no trusted `INRES-*`;
- self-consistently rehashed forged resolution projections are rejected by source recomputation;
- binder IDs/fingerprints/request schema cannot be caller/model substituted;
- binding uses the exact adapter selected by current Phase-32/33 authority;
- typed request hash is deterministic across restart;
- self-consistently rehashed forged typed requests are rejected by independent binder recomputation;
- stale live input makes currentness stale without corrupting historical frozen validity;
- no resolver/binder/auditor/reader calls adapter execution methods;
- no Task/Run/Flow state changes occur during resolution, binding, audit, or inspection;
- authority-source tests inspect executable AST/call surfaces rather than raw documentation substrings.

---

## 17. Implementation slices

Suggested dependency order:

### 34A — IDs and frozen contracts

Add `INRES-*`, `DISPBIND-*`, `BINDAUD-*`; resolver/binder contracts; resolved-input/bundle/binding/audit/currentness models and bounded canonical identities.

### 34B — code-owned resolver registry + core canonical evidence resolvers

Implement deterministic registry and safe project-scoped resolvers for the exact Phase-33 ref families already supported by existing canonical read boundaries.

### 34C — phase-specific protected evidence resolvers

Review audio/media/simulation/playtest/image/3D/runtime evidence stores and add only independently revalidatable resolver families. Unsupported evidence remains fail-closed.

### 34D — typed binder registry + binding/audit/currentness

Construct exact backend request projections with code-owned binders, independently recompute binding audits, and keep historical validity separate from live eligibility.

### 34E — reviewed built-in binding expansion

Start with the Phase-33 bounded-code contract and add only the deferred adapters for which 34B/34C provide complete trusted input reconstruction. Record every still-deferred backend explicitly.

### 34F — immutable persistence + read-only inspection

Add protected no-overwrite stores, restart/tamper/containment tests, Phase-30 immutable currentness reads, and inspection-only CLI.

### 34G — canonical closure

Synchronize the Phase-34 implementation contract and canonical roadmap, then run one final exact-head Python 3.12/3.13 matrix before SHA-guarded merge.

Every authority-expanding slice must pass the exact-head normal matrix before the next slice begins.

---

## 18. Explicit non-goals

Phase 34 does **not** add:

- a dependency-aware production coordinator;
- adapter invocation or generic dispatch;
- automatic Task `READY → RUNNING` transitions;
- production Run creation;
- hidden queues, retries, escalation, or recursive replanning;
- generic Phase-13 `call_tool` authority;
- model-authored shell/argv/environment/import/callable/container/endpoint configuration;
- automatic runtime/model/backend downloads or installation;
- resource lease acquisition or model loading;
- automatic Artifact adoption/signing;
- automatic Verification/Task completion;
- Project Intelligence/Design Bible mutation;
- merge/release authority;
- live self-training or candidate activation.

A future coordinator may be considered only after Phase 34 proves that every dispatchable backend receives an exact independently audited typed request without coordinator-invented parameters.

---

## 19. Exit condition

Phase 34 is complete when Origin Forge can take an audited/current Phase-33 WorkOrder, independently resolve every permitted exact evidence reference through code-owned bounded resolvers, construct one exact typed request projection through an infrastructure-owned binder, persist/reconstruct/audit that chain, and report current eligibility — **without invoking the selected adapter or mutating production state**.
