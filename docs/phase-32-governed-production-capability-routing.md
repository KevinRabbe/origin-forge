# Phase 32 — Governed Production Capability Catalog & Routing

Status: **PLANNED — post-Phase-31 architecture contract**

Phase 32 closes the authority gap between Phase 31's durable production plan and any future dependency-aware Manager execution layer.

Phase 31 can freeze a Goal-bound `PlanningInput`, validate a bounded cross-domain DAG, materialize canonical Flow / Task state, persist exact Task dependencies, and deterministically derive which Tasks are dependency-ready. It intentionally does not decide *which production executor is authorized to satisfy a Task*.

The current PlanningInput binds a `capability_catalog_hash` plus a bounded set of `capability_ids`, but that catalog identity is supplied by the caller. Before Origin Forge can safely coordinate code, 2D, 3D, image, audio, runtime observation, playtesting, simulation, or other production work, capability identity and route eligibility must become infrastructure-owned, inspectable, and replayable.

Core rule:

```text
Task declares required capability
        ↓
infrastructure-owned catalog defines capability meaning
        ↓
explicit routing policy limits eligible trusted adapters
        ↓
deterministic resolver selects one route or fails closed
        ↓
route evidence only
        ↓
STOP
```

A route is not execution authority. A model cannot create capabilities, register executable adapters, choose an unapproved backend, or trigger the selected adapter.

---

## 1. Goals

Phase 32 v1 must provide:

1. **Canonical production capability identity** owned by Origin Forge rather than ad-hoc planner strings.
2. **Immutable content-addressed capability catalog snapshots** describing stable semantic production responsibilities.
3. **Trusted adapter descriptors** for infrastructure-owned production entrypoints without storing arbitrary callables, argv, shell, source code, or model-authored execution data in the catalog.
4. **Explicit routing policy** separate from inventory, with an ordered allow-list of adapters and no implicit fallback.
5. **Deterministic Task routing** from canonical Task `required_capabilities` + exact catalog + exact policy.
6. **Fail-closed multi-capability semantics**: one v1 Task must be satisfiable by one trusted adapter; hidden adapter composition is forbidden.
7. **Immutable route-decision evidence** binding exact Task revision/content, catalog, policy, selected adapter, alternatives, and rejection reasons.
8. **Phase-31 integration** so new PlanningInputs derive `capability_catalog_hash` and allowed capability IDs from a validated canonical catalog instead of caller-invented identities.
9. **Read-only inspection** of catalog, policy, adapter descriptors, Task route decisions, and unsupported capabilities.
10. **No production execution in Phase 32**. A later Manager/coordinator must consume Phase-31 readiness plus Phase-32 routing evidence.

---

## 2. Explicit non-goals

Phase 32 does not add:

- automatic Task execution;
- a background Manager queue;
- recursive plan execution;
- automatic Task `READY → RUNNING` transitions;
- model-controlled adapter registration;
- model-selected shell/argv/container image/runtime path;
- generic `call_tool` authority;
- dynamic plugin installation;
- cross-adapter hidden workflows inside one Task;
- implicit capability coercion or fuzzy matching;
- implicit fallback to any installed backend;
- automatic model/profile loading;
- automatic Artifact adoption/signing;
- automatic Project Intelligence / Design Bible mutation;
- automatic merge/release;
- live self-training/self-modification.

The route resolver is a control-plane decision function, not an executor.

---

## 3. Why Phase 32 is separate from Phase 13 and Phase 14

Phase 13 answers:

```text
which governed tools may be disclosed?
```

Phase 14 answers:

```text
which explicitly allowed model profile may fit current resources?
```

Phase 32 answers:

```text
which trusted production adapter is permitted to own this Task class?
```

These are different authority domains.

A production capability is semantic responsibility, for example:

```text
code.change
media.2d.export
media.3d.blender
image.generate
image.inspect
media.audio.process
media.audio.tts
runtime.observe
runtime.playtest
simulation.run
```

A capability is not a tool call, model profile, Python function, shell command, or executable path.

---

## 4. Phase 32 identities

Infrastructure owns all durable identities.

Recommended v1 identity families:

```text
CAPCAT-*   immutable production capability catalog snapshot
CAPPOL-*   immutable capability routing policy
CAPROUTE-* immutable Task route-decision evidence
```

Individual `capability_id` and `adapter_id` values remain bounded stable tokens inside those immutable objects. They do not grant authority merely because a string exists.

Canonical production state continues to use existing:

```text
GOAL-*
FLOW-*
TASK-*
RUN-*
VERIFY-*
PLINPUT-*
PLPROP-*
PLAUD-*
PLMAT-*
```

---

## 5. ProductionCapability

`ProductionCapability` defines one infrastructure-owned semantic responsibility.

Minimum fields:

```text
capability_id
name
summary
media_domain
contract_version
```

Suggested bounded `media_domain` values:

```text
CODE
DESIGN
MEDIA_2D
MEDIA_3D
IMAGE
AUDIO
RUNTIME
PLAYTEST
SIMULATION
GENERAL
```

The catalog may grow later, but v1 capability IDs are exact tokens. There is no fuzzy alias resolution.

Capabilities do not contain executable code or runtime configuration.

---

## 6. TrustedProductionAdapter descriptor

A trusted adapter descriptor identifies one infrastructure-owned production entrypoint.

Minimum fields:

```text
adapter_id
adapter_family
adapter_version
implementation_fingerprint
capability_ids
execution_effect
replay_class
```

V1 `execution_effect` is descriptive governance metadata, for example:

```text
WORKSPACE_MUTATION
MEDIA_WORKSPACE_MUTATION
OBSERVATION_ONLY
SIMULATION_ONLY
PROPOSAL_ONLY
```

It is not a permission bit that can widen an underlying implementation's authority.

`implementation_fingerprint` must bind an infrastructure-controlled implementation identity. The catalog may not contain:

- arbitrary import paths;
- arbitrary function names supplied by a model/caller;
- shell strings;
- argv arrays;
- environment variables;
- container image names selected by a model;
- URLs/endpoints;
- secrets;
- executable bytes.

Executable dispatch remains code-owned and must explicitly map a known `adapter_id` to a trusted adapter implementation in a later execution layer.

---

## 7. CapabilityCatalog snapshot

`CapabilityCatalog` is immutable and content-addressed.

It contains bounded deterministic sets of:

```text
capabilities
trusted adapter descriptors
catalog schema version
```

Validation requires:

- unique exact capability IDs;
- unique exact adapter IDs;
- every adapter capability reference exists;
- bounded descriptor counts/text/bytes;
- exact stable ordering;
- no unknown fields;
- no authority-shaped executable payload;
- exact content hash.

The catalog is inventory only.

It does **not** decide which adapter a Task may use.

---

## 8. CapabilityRoutingPolicy

Routing policy is deliberately separate from the catalog, mirroring Phase 14's separation between model inventory and model selection policy.

Minimum fields:

```text
routing_policy_id
catalog_id
catalog_hash
ordered_adapter_ids
allowed_capability_ids
```

Rules:

- every listed adapter must exist in the bound catalog;
- every allowed capability must exist in the bound catalog;
- duplicate adapter/capability IDs are rejected;
- an adapter omitted from `ordered_adapter_ids` is not eligible even if it exists in inventory;
- a capability omitted from `allowed_capability_ids` is not routable under that policy;
- route order is explicit and stable;
- no registry-driven or installation-driven implicit fallback exists.

A future policy format may support richer project-specific constraints, but v1 remains intentionally finite and inspectable.

---

## 9. Task route input

Routing consumes existing canonical Task state.

The route input binds at least:

```text
task_id
task_revision
task_content_hash
flow_id
required_capabilities
catalog_id
catalog_hash
routing_policy_id
routing_policy_hash
```

Task content hashing must cover routing-relevant canonical fields, including:

- objective;
- acceptance criteria;
- constraints;
- required capabilities;
- priority;
- canonical Flow ownership;
- revision/status where relevant to route validity.

A stale Task revision invalidates prior route evidence.

---

## 10. Deterministic route resolution

The v1 resolver performs no model call.

Given one Task, one exact catalog, and one exact policy:

1. validate Task and project/Flow ownership;
2. validate exact catalog + policy hashes and relationship;
3. require at least one Task capability;
4. reject any capability not present in the catalog;
5. reject any capability not allowed by the policy;
6. consider only policy-listed adapters;
7. retain only adapters whose declared capability set covers **all** Task-required capabilities;
8. select the first eligible adapter in explicit policy order;
9. produce immutable route evidence.

No adapter composition is permitted in v1.

Therefore:

```text
Task requires {image.generate, image.inspect}
```

is routable only if one trusted adapter explicitly covers both capabilities. Otherwise the resolver fails closed and the Goal/plan should be decomposed into separate dependency-linked Tasks.

This prevents Phase 32 from quietly becoming another workflow engine.

---

## 11. Route outcomes

Recommended v1 route classifications:

```text
ROUTABLE
UNKNOWN_CAPABILITY
CAPABILITY_NOT_ALLOWED
NO_ELIGIBLE_ADAPTER
STALE_TASK
INVALID_CATALOG
INVALID_POLICY
```

`ROUTABLE` means only:

> one infrastructure-owned adapter is statically authorized by the exact catalog/policy for the exact Task contract.

It does not mean:

- the adapter is currently available;
- required external software is installed;
- resources are currently available;
- execution would succeed;
- the Task may transition state;
- the Task is dependency-ready.

Phase 31 remains authoritative for dependency readiness. Phase 14 remains authoritative for model/resource admission where relevant. Backend-specific execution remains authoritative for runtime/tool availability.

---

## 12. Route-decision evidence

`CapabilityRouteDecision` is immutable evidence.

Minimum binding:

```text
route_decision_id
task_id
task_revision
task_content_hash
flow_id
required_capabilities
catalog_id
catalog_hash
routing_policy_id
routing_policy_hash
outcome
selected_adapter_id
selected_adapter_fingerprint
considered_adapter_ids
rejection_reasons
content_hash
```

Rules:

- infrastructure allocates the route-decision ID;
- selected adapter must be null unless outcome is `ROUTABLE`;
- every considered adapter comes from policy order;
- rejection reasons are deterministic bounded structured evidence;
- decision publication re-runs resolver logic rather than trusting caller-provided outcome fields;
- a later Task/catalog/policy change makes old route evidence stale rather than rewriting it.

---

## 13. Phase-31 PlanningInput integration

Phase 31 already binds:

```text
capability_catalog_hash
capability_ids
```

Phase 32 should preserve that stable PlanningInput shape while removing caller authority over those values.

A new governed freeze helper should accept a validated `CapabilityCatalog` and derive:

```text
capability_catalog_hash = catalog.content_hash
capability_ids = catalog capability IDs permitted for planning
```

If project routing policy intentionally exposes only a subset of capabilities to the Planner, the frozen planning input must bind that exact allowed subset and the routing-policy hash through existing/future policy evidence rather than silently exposing the entire installation.

The Planner may choose only capability IDs disclosed in the frozen input. It still cannot create or register capabilities.

---

## 14. Trusted built-in adapter descriptors

Phase 32 may describe already-proven Origin Forge production surfaces, but only after each mapping is reviewed against its actual authority boundary.

Candidate families to inspect include:

```text
bounded coding/retry orchestration
Pixelorama governed 2D surface
Blender governed 3D surface
image generation
vision inspection
FFmpeg/audio processing
Piper TTS
runtime observation
cooperative playtesting
simulation
```

Descriptor existence does not automatically make a backend enabled in a routing policy.

Unsupported or deferred surfaces remain absent or explicitly unroutable.

In particular, Phase 20B Blockbench remains deferred and must not become routable merely because a 3D capability exists.

---

## 15. Static routing vs runtime availability

Phase 32 v1 is a **static authority resolver**.

It answers:

```text
is this adapter authorized for this Task contract?
```

It deliberately does not answer:

```text
can the adapter successfully run right now?
```

Runtime availability may depend on:

- local executable presence;
- sandbox backend availability;
- configured model runtime;
- CPU/RAM/VRAM contention;
- external editor/runtime state;
- project-specific files.

Those checks belong to the later coordinator and existing backend-specific preflight boundaries.

This separation avoids performing model loads, subprocess launches, downloads, leases, or environment mutation during route inspection.

---

## 16. Persistence

Phase 32 should use immutable content-addressed evidence with no overwrite.

V1 may use protected SQLite or protected immutable object persistence, but there must be exactly one canonical representation for each Phase-32 evidence class.

Required guarantees:

- strict canonical JSON representation where JSON is used;
- exact content hashes;
- bounded bytes/counts;
- no duplicate-key acceptance;
- no symlink/path escape if filesystem persistence is used;
- relational catalog/policy/Task revalidation on load;
- no mutable adapter-registration table that turns installation state into production truth.

Catalog/policy replacement creates a new immutable object/hash rather than mutating history.

---

## 17. Read-only inspection

Inspection should expose bounded views of:

```text
catalog status
capability show/list
adapter show/list
routing policy show
Task route resolve/inspect
route-decision show/list
```

Read-only inspection must not:

- create/migrate project state;
- probe by launching executables;
- load models;
- acquire resource leases;
- mutate Task state;
- publish new route decisions unless an explicit authoritative write API is invoked outside the read path;
- execute selected adapters.

Where SQLite is used, Phase 30's immutable read guard should be reused.

---

## 18. Authority tests

Regression coverage must explicitly prove:

- planner/caller strings cannot create capabilities;
- duplicate catalog identities fail closed;
- adapter descriptors cannot smuggle shell/argv/import/callable authority;
- policy cannot reference unknown catalog adapters/capabilities;
- adapters not explicitly listed in policy are never selected;
- deterministic policy order controls fallback;
- no implicit smaller/available/installed backend fallback occurs;
- unknown Task capabilities fail closed;
- policy-disallowed Task capabilities fail closed;
- one adapter must cover the complete Task capability set;
- multi-adapter composition does not happen;
- stale Task revision/hash invalidates route evidence;
- catalog/policy drift invalidates route evidence;
- forged caller outcome/selected-adapter fields are recomputed/rejected;
- route inspection starts no Run and performs no Task transition;
- route inspection loads no model and acquires no resource lease;
- read-only CLI/help on an uninitialized project creates no state;
- restart produces the same static route from the same canonical inputs.

---

## 19. Proposed implementation slices

### 32A — Capability/catalog contracts

Add bounded capability and trusted-adapter descriptors, immutable catalog identity, exact hashes, and adversarial schema validation.

### 32B — Explicit routing policy

Add immutable policy contracts, catalog binding, ordered adapter allow-list semantics, and no-implicit-fallback tests.

### 32C — Deterministic resolver

Add exact Task content binding and pure static route resolution with full multi-capability/fail-closed coverage.

### 32D — Immutable route evidence

Persist/reload/revalidate route decisions and reject Task/catalog/policy drift or forged outcomes.

### 32E — Phase-31 integration

Derive PlanningInput capability catalog hash/IDs from validated governed catalog/policy evidence rather than caller-authored identities.

### 32F — Built-in descriptor review + read-only inspection

Map only already-proven production surfaces whose actual authority contracts are compatible, then add non-creating bounded inspection/CLI and source-level authority regressions.

### 32G — Documentation / roadmap closure

Synchronize the canonical roadmap only after the implementation candidate passes the normal Python 3.12/3.13 matrix.

Every slice that changes the implementation SHA must pass the normal exact-head matrix before the next authority-expanding slice begins.

---

## 20. Exit condition

Phase 32 is complete when Origin Forge can take a canonical Task with exact `required_capabilities`, an immutable infrastructure-owned production capability catalog, and an explicit immutable routing policy and deterministically prove one of:

```text
ROUTABLE → exact trusted adapter identity/fingerprint
or
fail-closed structured routing reason
```

The same durable inputs must reconstruct the same result after restart, and route inspection must have zero execution/mutation authority.

A later dependency-aware Manager/coordinator may then combine:

```text
Phase 31 dependency readiness
        +
Phase 32 trusted route decision
        +
backend/model/resource preflight
        ↓
explicit bounded Task dispatch
```

without inventing routing semantics inside a model loop.

---

## 21. Merge gate

The planning contract is merged first as architecture-only evidence.

Implementation starts only from the exact resulting planning merge on `main`.

Final Phase-32 closure requires:

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

Unrelated heavyweight Pixelorama / Blender / image / vision / FFmpeg / Piper workflows remain outside the normal Phase-32 gate unless a later implementation slice explicitly changes one of those evidence boundaries.