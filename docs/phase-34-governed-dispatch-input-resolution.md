# Phase 34 — Governed Dispatch Input Resolution & Binding

Status: **IMPLEMENTED — backend invocation intentionally remains out of scope**

Phase 34 closes the evidence-resolution and request-binding gap between an audited/current Phase-33 WorkOrder and any later production coordinator. It resolves only exact infrastructure-owned evidence, reconstructs only code-owned typed backend request projections, independently audits those bindings, persists them as immutable evidence, and stops before adapter/process/model/resource invocation.

Core boundary:

```text
audited/current WORKORD
+ exact WorkOrderInputRefs
+ trusted resolver registry
        ↓
INRES-* exact resolved evidence bundle
        ↓
trusted typed binder
        ↓
DISPBIND-* inert backend-native request projection
        ↓
BINDAUD-* independent binding audit/currentness
        ↓
STOP — no adapter invocation
```

## Implemented identities and contracts

Phase 34 adds infrastructure-owned `INRES-*`, `DISPBIND-*`, and `BINDAUD-*` identities using the existing typed opaque-ID contract. Frozen models bind exact WorkOrder/Audit/Task/route/catalog/contract identities, resolver and binder fingerprints, canonical projections, request schema identity, content hashes, and explicit currentness states.

Resolvers and binders are code-owned already-imported infrastructure objects. Persisted/model-visible evidence contains inert IDs, hashes, roles, schemas, and canonical data only; it never carries import paths, callables, source code, shell/argv, environment, endpoint, credentials, executable handles, or dynamic plugin metadata.

## Trusted input resolution

The resolver registry is deterministic, content-addressed, and fail-closed on duplicate or ambiguous claims. Every resolved input must bind exactly to the original `WorkOrderInputRef` ID/hash/revision/role and to the resolver identity/fingerprint that produced its projection.

The accepted v1 core resolvers are:

- `ARTIFACT` / `ART-*` / role `source`: exact project-local Artifact metadata bound to the stored Artifact content hash; Artifact bytes are not read.
- `VERIFICATION` / `VERIFY-*` / role `verification`: exact project-owned canonical Verification-record hash with bounded metadata plus evidence/metrics hashes; raw evidence/metrics are not disclosed.
- `PROJECT_ENTITY` / `ENTITY-*` / role `entity`: exact current revision plus canonical Phase-17 read projection hash.
- `DESIGN_RULE` / `RULE-*` / role `design_rule`: exact current revision plus canonical Phase-17 read projection hash.
- `AUDIO_PROFILE` / `AUDPROF-*` / role `audio_profile`: exact immutable governed Audio Profile ID/hash through its protected non-creating canonical reader.

Phase-specific evidence review is deliberately conservative. `MEDIA_PROFILE`, simulation specs, playtest scenarios, image workflow tokens, 3D request/project evidence, runtime-observation requests, and generic `PHASE_SPECIFIC_EVIDENCE` remain deferred where the repository lacks an exact typed ID, direct non-creating ID-addressed reader, or exact unambiguous claim. Resolver scanning, path guessing, registry fallback, and wildcard phase evidence are forbidden.

## Typed dispatch binding

The accepted binder registry contains exactly one production binding:

```text
originforge.code.bounded-retry
→ code.bounded-retry@1
→ binder.code.bounded-retry@1
→ BoundedRetryPolicy.drive@1 request projection
```

The binder reconstructs only the existing bounded retry input projection:

```text
task_id
selected_paths
auto_context
context_seed_paths
structural_context
semantic_context
```

It does not import or call `BoundedRetryPolicy.drive()`. Model adapters, sandbox backend, Workspace manager, runtime instance, and all execution-owned dependencies remain absent from the binding and are reserved for a later coordinator authority boundary.

Binding creation requires an independently reconstructable `INRES-*`; binder selection requires an exact adapter/dispatch-contract relation and exact resolved-role set; request projection is canonical and content-addressed. `BINDAUD-*` independently reconstructs the trusted request rather than trusting a self-claimed PASS object.

Historical binding-audit validity and live currentness are deliberately separate. Historical audit relation checks use frozen evidence only. Live eligibility additionally checks resolver inventory drift, binder/schema drift, current Phase-33 WorkOrder readiness/currentness, source-input currentness where supported, and independent current trusted request reconstruction.

## Built-in adapter review

All ten Phase-32 built-in production adapters were explicitly reviewed. Only `originforge.code.bounded-retry` is bindable in Phase 34; the other nine remain fail-closed:

- Pixelorama export — no complete typed Pixelorama input.
- Blender 3D — no direct protected MODEL3D request reader.
- image generation — no typed image-workflow reference.
- vision inspection — generic Artifact metadata is insufficient to reconstruct the complete governed vision request/model relation.
- FFmpeg audio — Artifact plus Audio Profile resolution still lacks exact PCM hash, byte/frame counts, sample rate, and channel evidence required by `AudioSourceRef`.
- Piper audio — Audio Profile is resolvable, but `AudioOperationRequest` still requires execution-owned operation/workspace identity and a complete Phase-33 audio request contract.
- runtime observation — no direct exact runtime-observation request reader.
- cooperative playtesting — no direct exact `PLAYSCEN-*` reader.
- deterministic simulation — no direct exact `SIMSPEC-*` reader.

Adding one resolver therefore does not silently promote an adapter. A backend becomes bindable only when the exact Phase-33 dispatch contract, complete typed evidence resolution, and a code-owned independently reconstructable binder all exist together.

## Immutable evidence and read-only inspection

Trusted Phase-34 evidence is persisted under:

```text
.origin-forge/production-dispatch-bindings/
├── input-resolutions/   # INRES-*
├── dispatch-bindings/   # DISPBIND-*
└── binding-audits/      # BINDAUD-*
```

The store uses strict canonical UTF-8 JSON, duplicate-key rejection, bounded object/count limits, typed category IDs, exact hashes, symlink/alias containment, `xb` no-overwrite publication, fsync, and frozen cross-object relation revalidation. Binding/audit publication independently reconstructs the trusted request before evidence may enter the protected registry.

The read path is independent from the writer store. It performs non-creating protected evidence reads plus existing Phase-30/33 immutable-read boundaries. The accepted inspection-only CLI exposes exactly:

- `status`
- `input-resolution-show`
- `binding-show`
- `binding-audit-show`
- `binding-currentness`

There is no create/publish/resolve/bind/audit/dispatch/run CLI command.

## CI evidence

Each authority-expanding slice was frozen and independently gated on the normal Ubuntu Python 3.12/3.13 matrix before the next slice:

- 34A contracts: `ac202f673f935d4d5333281392f549731462793d`, run `31510982501` — PASS 3.12/3.13.
- 34B core resolvers: `2eae7c995e2ca869df8dc1601d4e5580cb7b02ef`, run `31512995734` — PASS 3.12/3.13.
- 34C protected phase-specific resolver review: `03a943a1cb4d454e4e49b14f7e0614286715ff55`, run `31514231880` — PASS 3.12/3.13.
- 34D typed binding/audit/currentness: `d0ffa43cc4690e3bbb74e14e9fc2b67eb307bab7`, run `31515949661` — PASS 3.12/3.13.
- 34E exact built-in binding review: `e2cc952243a88a54f4237ea20e421d3cf19e6177`, run `31516378852` — PASS 3.12/3.13.
- 34F immutable persistence/read/CLI: `b4ff1f5eb6c224c965cb7fa35a8ffffcbca72caa`, run `31517075735` — PASS 3.12/3.13.

Two rejected intermediate heads were corrected without advancing authority: the initial 34B source guard falsely classified immutable SQLite `conn.execute(SELECT...)` as backend execution, and the initial 34D test used an invalid Task test transition. Both corrections were minimal test-only changes followed by fresh full matrices.

The final 34G documentation/roadmap closure head is intentionally created after all implementation proofs and must itself pass the full normal Python 3.12/3.13 matrix before ready-for-review transition and SHA-guarded merge.

## Authority exclusions

Phase 34 does **not** add:

- adapter/backend invocation;
- process/model/tool execution;
- model loading or resource leases;
- Task/Flow/Goal transition or completion authority;
- background dispatch queues or recursive coordinators;
- caller/model-supplied shell, argv, imports, callables, endpoints, credentials, or arbitrary files/SQL/network access;
- Artifact adoption/signing;
- Project Intelligence mutation;
- merge/release/self-training authority.

## Exit condition

Phase 34 is complete when Origin Forge can take an exact audited Phase-33 WorkOrder, resolve every supported evidence ref through one trusted unambiguous resolver, reconstruct an exact typed request through one trusted binder, independently audit and persist that relation, inspect current eligibility without mutation, and stop before execution.

That condition is met for the deliberately narrow bounded-code production contract. Media/runtime contracts remain explicit fail-closed future work until their missing typed-reader/request substrates are supplied without weakening the authority model.
