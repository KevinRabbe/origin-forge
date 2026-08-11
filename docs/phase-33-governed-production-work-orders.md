# Phase 33 — Governed Production Work Orders & Dispatch Contracts

Status: **PLANNED — post-Phase-32 architecture contract**

Phase 33 closes the final input-authority gap before Origin Forge can safely add a dependency-aware multi-Task production coordinator.

Phase 31 can turn one Goal into a bounded durable Task dependency graph and determine dependency readiness. Phase 32 can deterministically prove which trusted production adapter is statically authorized for one exact Task. But a route does not contain the adapter-specific invocation data required to execute that adapter.

For example, a governed FFmpeg execution requires an exact `AudioOperationRequest` plus exact source-byte evidence, while the bounded coding orchestrator requires explicit context/model/sandbox choices. Those values are not reconstructable from a generic Task objective/capability without inventing new authority at dispatch time.

Core rule:

```text
Task + current Phase-32 route
        ↓
proposal-only work-order construction
        ↓
trusted dispatch contract validation
        ↓
independent work-order audit
        ↓
immutable dispatchable evidence
        ↓
STOP
```

A work order is not execution. It is a frozen, independently validated statement of exactly what a later trusted coordinator may hand to one already-authorized adapter.

---

## 1. Goals

Phase 33 v1 must provide:

1. **Infrastructure-owned dispatch-contract identity** for the input contract associated with one Phase-32 adapter.
2. **Immutable dispatch-contract catalog snapshots** separate from Phase-32 capability/routing inventory.
3. **Bounded typed work-order envelopes** binding one exact Task, one current `CAPROUTE-*`, one dispatch contract, and exact input-evidence refs.
4. **Strict adapter-specific payload validation** through trusted infrastructure validators rather than arbitrary model-authored JSON interpretation.
5. **Independent work-order audit** that recomputes Task/route/contract/input binding and rejects authority-shaped fields or stale evidence.
6. **Proposal-only model work-order construction** using the existing bounded/scheduled model boundary, with no execution side effect.
7. **Immutable work-order/audit evidence** with exact content hashes and restart reconstruction.
8. **Reviewed built-in dispatch contracts** for the Phase-32 built-in adapters that have sufficient governed input boundaries.
9. **Read-only inspection** of dispatch contracts, work orders, audits, and currentness.
10. **No adapter invocation in Phase 33**. A later coordinator may execute only an audited current work order after Phase-31 readiness and Phase-32 routing are independently revalidated.

---

## 2. Explicit non-goals

Phase 33 does not add:

- automatic Task execution;
- automatic Task `READY → RUNNING` transitions;
- a background production queue;
- recursive plan/work-order generation;
- arbitrary model-facing `call_tool`;
- model-controlled Python/import/callable dispatch;
- shell/argv/environment/container-image authority;
- model-selected executable paths or endpoints;
- dynamic plugin installation;
- implicit adapter fallback;
- hidden multi-adapter workflows;
- automatic backend downloads;
- automatic model/profile activation;
- resource lease acquisition during work-order construction/inspection;
- automatic Artifact adoption/signing;
- automatic Project Intelligence / Design Bible mutation;
- automatic merge/release;
- live self-training/self-modification.

Phase 33 freezes dispatch input. It does not dispatch.

---

## 3. Why a work order is required

Phase-32 route evidence answers:

```text
which adapter is authorized for this Task?
```

It does not answer:

```text
what exact governed request should be sent to that adapter?
```

Those concerns must remain separate.

Examples:

### Coding

The existing bounded coding path needs choices such as:

- automatic/manual context mode;
- explicit seed/selected paths where applicable;
- structural/semantic context flags;
- model profile/policy;
- change-required semantics;
- existing sandbox/config authority.

### Audio processing

The governed FFmpeg path requires:

- one exact `AudioOperationRequest`;
- exact governed audio profile identity/hash;
- exact source evidence identity/hash/byte count/PCM structure;
- output relative path and bounded target sample format.

### 3D / image / runtime / playtest / simulation

Each has its own already-proven typed request/specification surface.

A future coordinator must never infer or fabricate those fields from `Task.objective` at the moment of execution.

Therefore Phase 33 introduces a frozen boundary between semantic Task intent and backend-specific request input.

---

## 4. Phase 33 identities

Infrastructure owns all durable identities.

Recommended v1 prefixes:

```text
DISPCAT-*   immutable dispatch-contract catalog snapshot
WORKORD-*   immutable production work order
WORKAUD-*   independent work-order audit
```

Existing Phase-32 identities remain authoritative for routing:

```text
CAPCAT-*
CAPPOL-*
CAPROUTE-*
```

A model may not choose any Phase-33 canonical ID.

---

## 5. DispatchContract

A `DispatchContract` describes one trusted input contract for one exact Phase-32 adapter family.

Minimum fields:

```text
contract_id
contract_version
adapter_id
adapter_fingerprint
validator_id
validator_fingerprint
payload_schema_id
payload_schema_hash
allowed_input_ref_types
max_payload_bytes
max_input_refs
```

Rules:

- adapter ID/fingerprint must bind one reviewed Phase-32 adapter descriptor;
- validator identity is infrastructure-owned;
- persisted data contains no import path/callable/function body;
- payload schema is an inert exact schema identity, not executable code;
- input reference types are an explicit finite allow-list;
- size/ref bounds are finite;
- contract identity is content-addressed through the enclosing catalog.

Actual validator implementations live in trusted source code and are registered by exact `validator_id` in a process-local registry. A catalog entry cannot register executable code.

---

## 6. DispatchContractCatalog

`DispatchContractCatalog` is immutable content-addressed inventory.

It binds:

```text
dispatch_catalog_id
phase32_catalog_id
phase32_catalog_hash
contracts
schema_version
content_hash
```

Validation requires:

- exact current Phase-32 capability catalog relation when used for new work;
- unique contract IDs;
- at most one default v1 contract per adapter ID unless explicit version selection is added later;
- every contract adapter exists in the bound Phase-32 catalog;
- contract adapter fingerprint exactly matches the Phase-32 descriptor;
- bounded deterministic ordering;
- no executable authority fields;
- exact content hash.

A dispatch catalog is inventory only. It does not route or execute.

---

## 7. WorkOrderInputRef

Backend input should be referenced, not copied arbitrarily into a generic work order.

A bounded `WorkOrderInputRef` contains at least:

```text
ref_type
ref_id
content_hash
revision? 
role
```

Possible v1 ref classes should be finite and reviewed, for example:

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

The generic envelope validates identity/hash/role/limits. The adapter-specific validator decides which exact ref types/roles are meaningful for that contract.

Raw arbitrary filesystem paths, URLs, executable paths, secrets, shell commands, and environment blocks are forbidden generic input refs.

---

## 8. ProductionWorkOrder

A `ProductionWorkOrder` is immutable proposal/evidence for one exact Task route.

Minimum fields:

```text
work_order_id
task_id
task_revision
task_content_hash
flow_id
route_decision_id
route_decision_hash
selected_adapter_id
selected_adapter_fingerprint
dispatch_catalog_id
dispatch_catalog_hash
dispatch_contract_id
dispatch_contract_hash
input_refs
payload
```

Rules:

- infrastructure allocates `WORKORD-*`;
- Task identity/revision/hash must equal the current route input at creation time;
- route must be current and `ROUTABLE`;
- selected adapter identity/fingerprint is derived from the route, not caller/model fields;
- dispatch contract must exactly bind that selected adapter;
- input refs are bounded exact evidence refs;
- payload must fit the selected contract's exact schema/bounds;
- no approval/verification/completion/merge/release/Task-transition fields are permitted;
- work order construction does not transition Task state or start a Run unless explicitly using the proposal-only model worker described later.

A work order can become stale without being rewritten.

---

## 9. Strict work-order proposal format

When a model proposes a work order, it does not emit canonical IDs or route authority.

Model output should be limited to an inert object such as:

```json
{
  "contract_id": "audio.ffmpeg.process@1",
  "input_refs": [
    {
      "role": "source_audio",
      "ref_type": "ARTIFACT",
      "ref_id": "ART-...",
      "content_hash": "..."
    }
  ],
  "payload": {
    "target_sample_rate": 48000,
    "target_channels": 2,
    "output_name": "hammer-impact.wav"
  }
}
```

Infrastructure supplies and verifies:

- WorkOrder ID;
- Task binding;
- current route binding;
- selected adapter identity/fingerprint;
- exact dispatch catalog/contract hashes;
- canonical ordering/serialization.

The strict parser rejects:

- duplicate JSON keys;
- unknown top-level fields;
- canonical WorkOrder/Task/route IDs where not explicitly allowed as evidence refs;
- status/approval/completion fields;
- shell/argv/command/environment/import/callable/container/executable fields;
- pathological integers/floats/strings;
- oversized payloads/ref arrays.

---

## 10. Trusted validator registry

Phase 33 needs a process-local `DispatchContractValidatorRegistry`.

It maps exact infrastructure-owned `validator_id` values to already-imported pure validator implementations.

The registry:

- is code-owned, not model/catalog-owned;
- rejects unknown validators;
- does not import by caller string;
- does not execute subprocesses;
- does not load models;
- does not access network;
- does not mutate Task/project state;
- receives bounded inert payload + exact evidence metadata;
- returns canonical validated/normalized payload evidence or a controlled validation failure.

The persisted dispatch contract contains only validator identity/fingerprint, never the callable itself.

---

## 11. Validation vs runtime preflight

Phase 33 validation is static/evidence-based.

It may prove:

- payload schema is valid;
- required input roles exist;
- declared evidence hashes/revisions are structurally valid;
- values are within contract bounds;
- output names/relative paths are portable/protected as appropriate;
- request semantics are sufficient for a later adapter builder.

It does not prove:

- the executable/model/editor exists;
- source bytes are currently readable/unchanged unless explicitly revalidated through a governed evidence reader;
- CPU/RAM/VRAM is currently available;
- sandbox/editor runtime is healthy;
- execution will succeed.

Those remain later coordinator/backend preflight responsibilities.

---

## 12. WorkOrderAudit

`WorkOrderAudit` is independent immutable evidence.

Minimum binding:

```text
work_order_audit_id
work_order_id
work_order_hash
task_id
task_revision
task_content_hash
route_decision_id
route_decision_hash
dispatch_catalog_id
dispatch_catalog_hash
dispatch_contract_id
dispatch_contract_hash
validator_id
validator_fingerprint
status
normalized_payload_hash
failure_reason
```

Recommended status:

```text
PASS
FAIL
```

A PASS audit requires independent recomputation of:

1. Task ↔ current Phase-32 route binding;
2. route outcome/selected adapter;
3. dispatch catalog ↔ Phase-32 catalog relation;
4. contract ↔ selected adapter fingerprint;
5. WorkOrder hashes/identity/bounds;
6. exact input-ref structure;
7. trusted validator selection/fingerprint;
8. adapter-specific payload validation/normalization.

A WorkOrder cannot become dispatch-eligible merely because its own payload claims `approved=true` or similar.

---

## 13. Currentness

Historical work orders/audits remain immutable evidence.

A later dispatch eligibility check must require all of the following to still be current:

```text
Task revision/hash unchanged
Phase-31 dependency readiness currently READY
CAPROUTE still current and ROUTABLE
Phase-32 catalog/policy relation still valid
dispatch catalog/contract still exact
WORKAUD PASS still recomputes from exact frozen inputs
input refs still satisfy required currentness rules
```

Phase 33 itself should provide currentness inspection but not dispatch.

---

## 14. Proposal-only model worker

To support eventual autonomous production without letting the coordinator invent backend parameters, Phase 33 should provide one bounded model worker that proposes a work order.

It should:

- use a taskless or Task-associated `WORK_ORDER_PLANNER` Run with no production completion authority;
- use the existing `ModelAdapter` / Phase-14 scheduled model boundary;
- receive exact Task projection, current route, selected dispatch contract schema, and bounded allowed input evidence;
- make exactly one bounded generation call;
- parse only the strict inert proposal format;
- persist request/response/proposal hashes/evidence;
- construct/persist the WorkOrder only after infrastructure validation;
- stop before audit/dispatch unless those are separately explicit operations.

No model response can directly transition the Task or invoke the adapter.

---

## 15. Built-in dispatch contracts

Phase 33 should review the Phase-32 built-in adapters one by one.

Candidate contracts:

```text
originforge.code.bounded-retry
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

A contract is added only if Phase 33 can define a bounded payload/input-ref schema sufficient for later adapter construction without introducing generic executable authority.

`design.specify` still has no Phase-32 built-in adapter, so it cannot have an executable dispatch contract.

Blockbench remains absent while Phase 20B is deferred.

If one adapter's existing API requires unsafe/unbounded invocation information, that adapter remains unroutable-to-dispatch until its boundary is refined; Phase 33 must not weaken the backend to make the catalog complete.

---

## 16. Example contract shapes

The exact implementation may refine these after reviewing source APIs, but the architectural direction is:

### bounded coding/retry

Payload may include only governed context-selection mode/flags, bounded seed/selected path refs, model policy/profile identity, and change-required semantics. It must not contain arbitrary shell/build/test commands; those remain protected config authority.

### FFmpeg audio processing

Payload may include only values already represented by `AudioOperationRequest`, such as output role/name, target sample rate/channels, duration/timeout bounds, plus exact source/profile evidence refs. It cannot contain ffmpeg argv or executable path.

### Piper TTS

Payload may contain bounded text/speaker/output parameters allowed by the governed Piper profile, with exact voice/profile evidence refs. It cannot contain model/runtime paths or arbitrary CLI flags.

### Blender / Pixelorama

Payload references exact canonical media/project specifications and declared output roles through their existing governed contracts; no Python/JS code, plugin path, arbitrary editor command, or GUI automation.

### runtime observation / playtesting / simulation

Payload references exact pre-existing target/scenario/spec evidence plus bounded existing contract options. It cannot manufacture arbitrary executable/argv/process/environment authority.

---

## 17. Persistence

Phase 33 should use one immutable no-overwrite evidence representation, preferably under:

```text
.origin-forge/production-work-orders/
├── dispatch-catalogs/
├── work-orders/
└── audits/
```

Required guarantees:

- strict canonical JSON;
- duplicate-key rejection;
- content hashes;
- bounded bytes/counts;
- symlink/root/alias containment;
- atomic no-overwrite publication;
- relational revalidation on load;
- frozen audit recomputation;
- separate currentness checks against live Task/route/evidence state.

No mutable queue/state table should be introduced in Phase 33.

---

## 18. Read-only inspection

Inspection should expose only bounded non-creating views such as:

```text
status
dispatch-catalog-show
contract-show
work-order-show
work-order-audit-show
work-order-currentness
```

Inspection must not:

- create/migrate project state;
- start a model Run;
- generate a work order;
- publish/audit a work order;
- transition a Task;
- invoke an adapter;
- start a subprocess;
- load a model;
- acquire a resource lease;
- adopt/sign Artifacts;
- merge/release.

Phase 30's immutable SQLite guard should be reused for current Task/readiness state.

---

## 19. Authority/adversarial tests

Regression coverage must prove at least:

- infrastructure owns DISPCAT/WORKORD/WORKAUD IDs;
- model/caller cannot choose canonical work-order/audit identity;
- dispatch catalog cannot contain import/callable/shell/argv/executable/endpoint/secret authority;
- unknown validator IDs fail closed;
- validator fingerprint drift fails closed;
- dispatch contract cannot bind unknown/wrong Phase-32 adapter/fingerprint;
- model proposal parser rejects authority-shaped fields and duplicate keys;
- current route must be `ROUTABLE` before WorkOrder creation;
- caller cannot select a different adapter than CAPROUTE;
- caller cannot select a contract for another adapter;
- stale Task/route rejects new WorkOrder construction;
- input-ref type/role/count/hash bounds are exact;
- adapter-specific validator rejects malformed/unsupported payload;
- forged `PASS` audit/outcome cannot survive recomputation;
- historical evidence remains loadable after Task changes while currentness fails;
- model worker performs one generation and zero adapter calls;
- invalid model output fails the Run without creating a WorkOrder;
- read-only inspection creates no state/SQLite sidecars;
- Blockbench remains absent;
- Phase 33 source contains no adapter invocation or generic dynamic dispatch authority.

---

## 20. Proposed implementation slices

### 33A — IDs and dispatch-contract models

Add `DISPCAT-*`, `WORKORD-*`, `WORKAUD-*`, bounded `DispatchContract`, `DispatchContractCatalog`, and `WorkOrderInputRef` contracts.

### 33B — Trusted validator registry + safe schema substrate

Add code-owned validator registry, validator fingerprinting, strict payload limits, and no dynamic import/execution surface.

### 33C — WorkOrder construction and Phase-32 binding

Add immutable WorkOrder contracts plus exact current Task/CAPROUTE/dispatch-contract binding. No model yet.

### 33D — Independent WorkOrder audit/currentness

Add recomputed PASS/FAIL audit evidence and explicit historical-vs-current semantics, including Phase-31 dependency-readiness checks for dispatch eligibility inspection.

### 33E — Reviewed built-in dispatch contracts

Review current Phase-32 built-ins and implement only bounded contract validators that preserve each backend's existing authority boundary. Unsupported surfaces remain absent rather than weakened.

### 33F — One-shot model work-order proposer

Add exact bounded scheduled-model proposal generation/evidence with one model call and no adapter execution.

### 33G — Immutable persistence + read-only inspection

Add protected no-overwrite evidence persistence and non-creating status/show/currentness CLI.

### 33H — Documentation / roadmap closure

Synchronize canonical docs only after the code candidate passes normal Python 3.12/3.13 CI.

Every authority-expanding implementation slice must pass the exact-head normal matrix before the next slice begins.

---

## 21. Exit condition

Phase 33 is complete when Origin Forge can take:

```text
canonical Task
+ current Phase-32 ROUTABLE decision
+ exact dispatch-contract catalog
+ bounded exact input evidence
```

and produce an immutable independently audited `WORKORD-*` proving exactly what one trusted adapter may receive, while performing no adapter invocation or Task transition.

The same frozen evidence must reconstruct after restart, and a currentness check must fail closed after relevant Task/route/contract/input drift.

Only after that boundary is proven should a future coordinator be allowed to perform:

```text
Phase-31 dependency READY
+ current Phase-32 route
+ current Phase-33 PASS-audited work order
+ backend/model/resource preflight
        ↓
explicit bounded adapter invocation
```

---

## 22. Merge gate

The Phase-33 planning contract merges first as architecture-only evidence.

Implementation starts only from the exact resulting planning merge on `main`.

Final closure requires:

```text
exact immutable implementation/documentation head
        ↓
normal GitHub Actions Python 3.12 PASS
normal GitHub Actions Python 3.13 PASS
        ↓
unchanged head
clean reviews / review threads
        ↓
SHA-guarded squash merge
        ↓
verify actual main commit
```

Unrelated heavyweight editor/media evidence workflows remain outside the normal Phase-33 gate unless a later implementation slice explicitly changes those external execution boundaries.