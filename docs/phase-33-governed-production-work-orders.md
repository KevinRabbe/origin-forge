# Phase 33 — Governed Production Work Orders & Dispatch Contracts

Status: **DONE — implementation complete, final exact-head closure gate pending**

Phase 33 closes the dispatch-input authority gap between Phase 31 dependency readiness, Phase 32 static adapter routing, and any later production coordinator.

Core rule:

```text
canonical Task
+ current CAPROUTE
+ exact DISPCAT contract
        ↓
bounded proposal-only WorkOrder construction
        ↓
trusted validator normalization
        ↓
independent frozen WORKAUD
        ↓
immutable currentness-inspectable evidence
        ↓
STOP
```

A WorkOrder is frozen input evidence. It does not execute an adapter, transition a Task, verify completion, adopt/sign an Artifact, or grant merge/release authority.

---

## Implemented substrate

Phase 33 implements three infrastructure-owned identity families:

```text
DISPCAT-*   immutable dispatch-contract catalog
WORKORD-*   immutable production WorkOrder
WORKAUD-*   independently recomputed WorkOrder audit
```

The implementation adds:

- immutable `DispatchContract` and `DispatchContractCatalog` models bound to the exact Phase-32 capability catalog and adapter fingerprints;
- bounded `WorkOrderInputRef` evidence references with finite reviewed ref classes;
- code-owned `DispatchContractValidatorRegistry` with no dynamic import/discovery;
- inert exact-object payload schemas and validator/schema fingerprints;
- immutable `ProductionWorkOrder` binding exact Task revision/content, Flow, `CAPROUTE-*`, selected adapter, `DISPCAT-*`, selected dispatch contract, evidence refs, and canonical normalized payload;
- independent `WorkOrderAudit` recomputation over frozen Phase-32 routing evidence, exact dispatch authority, validator identity, and normalized payload;
- separate `WorkOrderCurrentness` inspection that rechecks current routing plus Phase-31 dependency readiness without rewriting historical evidence;
- protected no-overwrite persistence under `.origin-forge/production-work-orders/`;
- non-creating read-only inspection over Phase-30's immutable SQLite guard;
- a one-shot `WORK_ORDER_PLANNER` model boundary that proposes inert WorkOrder data and stops before audit or dispatch.

---

## Dispatch authority

A dispatch contract contains only inert authority metadata:

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

Persisted contracts contain no import path, callable, function body, shell, argv, environment, executable path, endpoint, container image, credential, or secret.

The process-local validator registry maps exact infrastructure-owned validator IDs to already-imported pure validators. Unknown validators, fingerprint drift, schema drift, unsupported evidence-ref types, duplicate refs, payload overflow, and non-canonical payloads fail closed.

---

## WorkOrder construction

`create_current_work_order(...)` requires all of the following before a `WORKORD-*` can be constructed:

1. a current persisted Phase-32 `CAPROUTE-*`;
2. route outcome `ROUTABLE`;
3. the exact frozen Phase-32 capability catalog;
4. a `DISPCAT-*` bound to that exact catalog;
5. a dispatch contract for the route-selected adapter;
6. exact adapter fingerprint agreement;
7. a trusted validator whose ID/fingerprint/schema match the contract;
8. bounded allowed evidence refs;
9. payload validation and canonical normalization.

The caller cannot choose the selected adapter or substitute another dispatch contract. Construction does not transition the Task, start a Task-bound Run, or invoke the selected adapter.

---

## Historical audit vs current eligibility

Phase 33 deliberately separates two questions.

### Frozen validity

`WORKAUD-*` independently reconstructs the historical WorkOrder from its exact frozen Task routing input, Phase-32 catalog/policy/route, dispatch catalog/contract, validator, and normalized payload. A forged PASS audit is rejected when recomputation differs.

Historical evidence can remain valid after the Task later changes.

### Currentness

Dispatch currentness is derived separately. It requires the live Task routing input to still equal the frozen route and then reuses the canonical Phase-31 dependency resolver.

Currentness statuses are:

```text
CURRENT_READY
WAITING_ON_DEPENDENCIES
BLOCKED_BY_FAILED_DEPENDENCY
INVALID_DEPENDENCY_STATE
ACTIVE
TERMINAL
STALE_TASK_ROUTE
INVALID_AUDIT
```

Inspection changes no Task/Run/Flow state.

---

## Reviewed built-in dispatch boundary

The initial trusted dispatch catalog is intentionally narrower than the Phase-32 routing catalog.

Supported in Phase 33 v1:

```text
originforge.code.bounded-retry
  → code.bounded-retry@1
```

Its payload contains only bounded coding context-selection data:

- `context_mode`: `auto` or `manual`;
- bounded canonical POSIX-relative `selected_paths` / `context_seed_paths`;
- `structural_context` boolean;
- `semantic_context` boolean.

Model choice, sandbox authority, build/test commands, executable paths, and runtime authority remain infrastructure-owned outside the WorkOrder payload.

The following Phase-32 adapters remain deliberately unsupported by the Phase-33 dispatch catalog because their existing typed APIs require phase-specific request/spec/profile/source evidence that Phase 33 cannot yet resolve generically without weakening evidence authority:

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

`design.specify` still has no Phase-32 built-in executor. Blockbench remains outside the catalog while Phase 20B is deferred.

Incomplete dispatch coverage is intentional and fail-closed; inventory presence never grants execution authority.

---

## Proposal-only model worker

`BoundedProductionWorkOrderPlanner` uses either the existing Phase-14 `ScheduledModelAdapter` or an infrastructure-owned deterministic no-I/O fixture used by tests/manual evidence.

Preflight supplies exactly:

- the current canonical Task projection;
- the exact current `CAPROUTE-*`;
- infrastructure-selected dispatch catalog/contract;
- the inert exact payload schema;
- a finite infrastructure-owned allow-list of evidence refs.

The worker creates one taskless `WORK_ORDER_PLANNER` Run and makes exactly one bounded generation call. Model output is limited to:

```json
{
  "contract_id": "...",
  "input_refs": [],
  "payload": {}
}
```

The strict parser rejects duplicate keys, unknown top-level fields, canonical authority fields, approval/completion/status claims, shell/argv/command/environment/import/callable/executable/container/endpoint/secret fields, floats, pathological integers, oversized data, contract substitution, and evidence refs outside the infrastructure allow-list.

Infrastructure then revalidates the current route and selected contract and constructs the canonical WorkOrder. The Run records exact request, response, proposal, route, contract, validator/schema, model, and WorkOrder hashes plus the full inert proposal/WorkOrder evidence. The worker then stops with `audited=false` and `dispatched=false`.

Admission into the trusted protected WorkOrder registry and independent audit publication remain explicit infrastructure operations; model generation cannot self-audit or dispatch.

---

## Immutable persistence

Trusted Phase-33 objects are persisted under:

```text
.origin-forge/production-work-orders/
├── dispatch-catalogs/
├── work-orders/
└── audits/
```

The store enforces:

- strict canonical UTF-8 JSON envelopes;
- duplicate-key rejection;
- content hashes and typed object IDs;
- bounded object bytes/counts;
- exact Phase-32 and validator relation checks;
- symlink/root/alias containment;
- create-only atomic publication with no overwrite;
- frozen WorkOrder revalidation before trusted publication;
- exact audit recomputation before trusted audit publication;
- restart reconstruction with the same hashes.

No mutable dispatch queue or alternate Task-status truth store is introduced.

---

## Read-only inspection

The Phase-33 operator surface exposes only:

```text
status
dispatch-catalog-show
contract-show
work-order-show
work-order-audit-show
work-order-currentness
```

The read layer does not instantiate the writer store. Historical files are loaded through independent canonical/hash/relation validation. Live currentness opens the existing Phase-30 `mode=ro&immutable=1` SQLite boundary and derives Phase-31 readiness inside that same quiescent snapshot.

Tests prove uninitialized inspection creates no `.origin-forge` state and initialized inspection leaves the complete project-state file tree byte-identical, including SQLite and Phase-32/33 evidence.

There is no CLI command to generate, publish, audit, dispatch, execute, transition, adopt, sign, merge, or release.

---

## Authority exclusions

Phase 33 grants no authority for:

- automatic Task execution or `READY → RUNNING` transitions;
- background queues or hidden retries;
- generic `call_tool` execution;
- arbitrary model-authored shell/argv/environment/import/callable execution;
- dynamic plugin installation;
- implicit adapter fallback or multi-adapter composition;
- automatic backend/model downloads or activation;
- resource lease acquisition during WorkOrder construction/inspection;
- automatic Artifact adoption or provenance signing;
- Project Intelligence / Design Bible mutation;
- self-verification or Task completion;
- merge, release, or self-training authority.

A future coordinator must independently require Phase-31 readiness, a current Phase-32 route, and an audited current Phase-33 WorkOrder before it may invoke any explicitly supported adapter.

---

## CI evidence

Authority-expanding slices were frozen and gated on the normal Ubuntu Python matrix before the next slice advanced:

- 33A+33B contracts / IDs / validator registry — run `31495883607`, Python 3.12 PASS, Python 3.13 PASS;
- 33C current Task/route-bound WorkOrder construction — run `31496335009`, Python 3.12 PASS, Python 3.13 PASS;
- 33D independent frozen audit/currentness — run `31496850835`, Python 3.12 PASS, Python 3.13 PASS;
- 33E reviewed built-in dispatch boundary — initial raw-source authority test produced a deterministic false positive on docstring text; the unchanged rejected SHA was rerun to confirm reproduction, then the guard was corrected to inspect executable AST calls; run `31505500679` passed Python 3.12 and Python 3.13 on exact corrected head `72ef2dc7b5ff865626e0cd64360a69473203d8a6`;
- 33F proposal-only scheduled-model WorkOrder worker — run `31506544502`, Python 3.12 PASS, Python 3.13 PASS on exact head `cf605e81a7b4a38b1ee24b908ccaba82779fe46f`;
- 33G protected persistence + immutable read/CLI surface — run `31507855287`, Python 3.12 PASS, Python 3.13 PASS on exact head `5f124d64466405106390c2f93c97e0068becb89b`.

The final 33H documentation closure SHA still requires one final exact-head Python 3.12/3.13 matrix before merge.

---

## Exit condition

Phase 33 is complete when Origin Forge can take one canonical Task plus a current Phase-32 route, bind it to one exact trusted dispatch contract, construct a bounded infrastructure-owned WorkOrder from inert validated input, independently audit the frozen evidence, reconstruct it after restart, and report current dependency/route eligibility without invoking the adapter or mutating production state.

**Exit condition implemented. Final exact-head closure CI remains the merge gate.**
