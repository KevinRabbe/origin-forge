# Phase 32 — Governed Production Capability Catalog & Routing

Status: **IMPLEMENTED — final exact-head closure CI required before merge**

Phase 32 closes the authority gap between Phase 31's durable production plan and any future dependency-aware Manager execution layer.

Phase 31 can materialize a bounded cross-domain Task DAG and deterministically determine dependency readiness. Phase 32 now determines, without executing anything, which exact infrastructure-owned production adapter is statically authorized to own a Task's declared capability set.

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
immutable route evidence
        ↓
STOP
```

A route is not execution authority. A model cannot create capabilities, register executable adapters, choose an unapproved backend, or trigger the selected adapter.

---

## 1. Implemented identities

Infrastructure now owns:

```text
CAPCAT-*   immutable production capability catalog snapshot
CAPPOL-*   immutable capability routing policy
CAPROUTE-* immutable Task route-decision evidence
```

Canonical production state continues to use the existing Goal / Flow / Task / Run / Verification and Phase-31 planning identities.

Individual `capability_id` and `adapter_id` values are bounded stable tokens inside immutable catalog/policy evidence. A string never grants authority merely by existing.

---

## 2. ProductionCapability

`ProductionCapability` is an infrastructure-owned semantic production responsibility.

Implemented fields:

```text
capability_id
name
summary
media_domain
contract_version
```

Implemented domains:

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

Capability IDs are exact bounded tokens. There is no fuzzy matching, alias expansion, model-created capability, or implicit coercion.

A capability is not a tool call, model profile, Python function, shell command, executable path, or permission escalation.

---

## 3. TrustedProductionAdapter descriptors

A `TrustedProductionAdapter` is inert routing inventory for one reviewed infrastructure-owned production boundary.

Implemented fields:

```text
adapter_id
adapter_family
adapter_version
implementation_fingerprint
capability_ids
execution_effect
replay_class
```

Implemented descriptive effects:

```text
WORKSPACE_MUTATION
MEDIA_WORKSPACE_MUTATION
OBSERVATION_ONLY
SIMULATION_ONLY
PROPOSAL_ONLY
```

Implemented replay classes:

```text
DETERMINISTIC
REVISION_BOUND
RUNTIME_BOUND
NON_REPLAYABLE
```

Descriptors deliberately contain no:

- arbitrary import path;
- callable/function name supplied by a model/caller;
- shell string;
- argv array;
- environment block;
- container image;
- endpoint/URL;
- secret;
- executable bytes;
- Task transition command.

The implementation fingerprint is a governed identity commitment. Built-in Phase-32 fingerprints are explicit contract-identity fingerprints, not claims that they are source-tree or executable hashes. Backend execution continues to enforce its own stronger runtime/version/hash boundary.

---

## 4. CapabilityCatalog

`CapabilityCatalog` is immutable bounded inventory.

It provides:

- infrastructure-owned `CAPCAT-*` identity;
- deterministic capability ordering;
- deterministic adapter ordering;
- exact content hash;
- unique capability IDs;
- unique adapter IDs;
- exact adapter→capability reference validation;
- bounded counts/text/bytes;
- schema version validation.

A catalog is inventory only.

It does **not** decide which adapter a Task may use.

---

## 5. CapabilityRoutingPolicy

`CapabilityRoutingPolicy` is separate from catalog inventory, mirroring Phase 14's separation between model inventory and model-selection policy.

It binds:

```text
routing_policy_id
catalog_id
catalog_hash
ordered_adapter_ids
allowed_capability_ids
```

Rules enforced:

- every adapter must exist in the bound catalog;
- every allowed capability must exist in the bound catalog;
- duplicate adapter/capability authority is rejected;
- policy binds exact catalog ID/hash;
- adapter order remains explicit and stable;
- omitted catalog adapters are not eligible;
- omitted capabilities are not routable;
- there is no registry-driven or installation-driven implicit fallback.

---

## 6. Exact Task routing input

Phase 32 derives a `TaskRouteInput` from canonical Task state.

The routing-relevant content hash covers:

```text
task_id
flow_id
parent_task_id
objective
acceptance_criteria
constraints
required_capabilities
budget
priority
revision
```

Task JSON is strict and bounded. Duplicate keys, malformed arrays/objects, invalid canonical IDs, pathological text/budget data, and malformed revisions fail closed.

A later Task revision produces a different route input/hash. Historical route evidence remains immutable; currentness is separately recomputed.

---

## 7. Deterministic static route resolver

The resolver performs no model call and no production mutation.

Given exact `TaskRouteInput + CapabilityCatalog + CapabilityRoutingPolicy`, it:

1. revalidates exact catalog/policy binding;
2. requires at least one Task capability;
3. rejects unknown capabilities;
4. rejects policy-disallowed capabilities;
5. considers only adapters listed in policy order;
6. requires one adapter to cover the **entire** Task capability set;
7. selects the first complete match in explicit policy order;
8. otherwise emits bounded fail-closed reasons.

Implemented outcomes:

```text
ROUTABLE
UNKNOWN_CAPABILITY
CAPABILITY_NOT_ALLOWED
NO_ELIGIBLE_ADAPTER
INVALID_TASK_CONTRACT
```

Implemented reason classes include:

```text
NO_REQUIRED_CAPABILITY
UNKNOWN_CAPABILITY
CAPABILITY_NOT_ALLOWED
ADAPTER_MISSING_CAPABILITY
```

No adapter composition occurs in v1.

For example, if one Task requires two capabilities and two different adapters each satisfy only one, the Task is `NO_ELIGIBLE_ADAPTER`. The plan should decompose that work into separate dependency-linked Tasks rather than letting the router become a hidden workflow engine.

---

## 8. Meaning of ROUTABLE

`ROUTABLE` means only:

> one trusted adapter descriptor is statically authorized by the exact catalog/policy for the exact Task contract.

It does **not** mean:

- the Task is dependency-ready;
- the Task may transition `READY → RUNNING`;
- the backend is installed/healthy;
- the backend can run right now;
- model/resources are available;
- external editor state is valid;
- execution will succeed;
- verification will pass.

Authority remains separated:

```text
Phase 31 → dependency readiness
Phase 32 → static production-adapter authorization
Phase 14 → model/resource admission where relevant
backend preflight → runtime/tool availability
later coordinator → explicit bounded dispatch
```

---

## 9. Immutable evidence persistence

Phase 32 persists immutable evidence under:

```text
.origin-forge/production-capabilities/
├── catalogs/
├── policies/
└── routes/
```

This is intentionally separate from canonical Task state in SQLite.

Persistence enforces:

- strict UTF-8 canonical JSON;
- duplicate-key rejection;
- exact content hashes;
- 2 MiB per-object bound;
- bounded object count per category;
- protected-root containment;
- symlink/alias rejection;
- atomic no-overwrite publication;
- fsync before publication completes;
- typed reconstruction on load;
- catalog/policy relationship revalidation;
- Task currentness recomputation for current route checks.

`resolve_and_publish()` computes route evidence from canonical Task state itself. Callers do not supply the outcome/selected adapter.

Read-side route inspection additionally recomputes the stored outcome from the frozen route input + catalog + policy, so a self-consistently rehashed forged selected adapter/fingerprint still fails closed.

---

## 10. Phase-31 PlanningInput integration

Phase 31 already had stable fields:

```text
capability_catalog_hash
capability_ids
```

The new governed freeze path preserves that shape while removing caller control over those values.

`freeze_governed_planning_input()`:

- accepts only an already-persisted `CAPCAT-*` + `CAPPOL-*` pair;
- verifies they belong to the same Origin Forge project root;
- reloads/revalidates both objects;
- derives `capability_catalog_hash` from the exact catalog;
- derives the Planner-visible capability set from policy `allowed_capability_ids`;
- automatically adds exact `CAPCAT-*` and `CAPPOL-*` evidence refs to the frozen PlanningInput;
- rejects caller attempts to pre-bind/forge those governed refs.

The low-level Phase-31 freeze helper remains for compatibility, but the Phase-32 governed path is the production capability authority boundary.

---

## 11. Reviewed built-in capability inventory

Phase 32 includes reviewed semantic capabilities for:

```text
design.specify
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

`design.specify` intentionally has no built-in executor in v1. It is known semantic work, not silently routable work.

Reviewed inert adapter descriptors cover the already-proven boundaries:

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

Descriptor existence does not enable a route. An exact policy must still list the adapter and capability.

**Blockbench is absent.** Phase 20B remains deferred and cannot become routable merely because a 3D capability exists.

---

## 12. Static routing vs runtime availability

Phase 32 is deliberately a static authority resolver.

It answers:

```text
is this adapter authorized for this exact Task contract?
```

It does not answer:

```text
can this backend successfully run right now?
```

Runtime availability may depend on local executable presence, sandbox availability, model runtime, CPU/RAM/VRAM contention, editor state, project files, or backend-specific pins.

Phase 32 inspection therefore performs no downloads, subprocess launches, model loads, leases, editor probes, or environment mutation.

---

## 13. Read-only inspection

`production_capability_read.py` uses non-creating filesystem inspection for immutable Phase-32 evidence and Phase 30's `production_read_connection()` for canonical Task reads.

Read-side guarantees:

- no project initialization;
- no SQLite migration;
- no SQLite journal creation/checkpoint;
- immutable/query-only SQLite Task reads;
- evidence-root absence reported without creating it;
- protected-root/symlink/alias validation;
- canonical/hash/relationship revalidation;
- frozen route-outcome recomputation;
- deterministic current Task route derivation through the same pure resolver.

The module CLI exposes only:

```text
status
catalog-show
policy-show
route-show
task-route
```

There is no Phase-32 CLI command for publication, registration, installation, execution, dispatch, Task transition, model loading, tool calls, adoption/signing, merge, or release.

No new v0.1 package entrypoint is introduced.

---

## 14. Authority regression coverage

Phase-32 tests prove, among other cases:

- infrastructure ID families validate and model-like forged IDs do not;
- duplicate capability/adapter identities fail closed;
- unknown adapter capability references fail closed;
- descriptor schemas contain no executable payload surface;
- policy cannot reference unknown inventory;
- policy order controls deterministic selection;
- unlisted installed/catalog adapters never become implicit fallback;
- unknown Task capabilities fail before adapter consideration;
- policy-disallowed capabilities fail before adapter consideration;
- two partial adapters are never composed;
- no-capability Tasks fail closed for routing;
- exact Task revision/content changes route identity;
- route resolution does not transition Task state or start Runs;
- restart reconstructs the same route from the same canonical inputs;
- immutable catalog/policy/route evidence round-trips and rejects overwrite;
- canonical/hash/duplicate-key/symlink tampering fails closed;
- stale current Task revisions invalidate current route evidence;
- self-consistently rehashed forged route outcomes fail frozen-input recomputation;
- governed PlanningInput derives its capability hash/set from persisted Phase-32 authority;
- caller cannot inject capability hash/IDs into the governed freeze API;
- cross-project capability authority is rejected;
- uninitialized read-only status/help creates no `.origin-forge` state;
- initialized read-only status does not create a missing evidence root;
- read-only Task route output equals the authoritative resolver for the same exact inputs;
- read-only inspection preserves database/evidence bytes and creates no SQLite sidecars;
- inspection/CLI source contains no publish/Task-run/model/resource/process/adoption/signing/merge authority;
- Blockbench is absent from built-in routing inventory.

---

## 15. Exact slice evidence

The Phase-32 architecture planning contract first passed normal GitHub Actions run:

```text
31490931777
Python 3.12 PASS
Python 3.13 PASS
```

It was then SHA-guarded squash-merged, producing planning base:

```text
7d5020c2e31f9f60d8a4aa59d0d253e765e19f69
```

Implementation slice gates:

```text
32A + 32B
head 7d74dfdca4805ff27135bd3a733fe7de30568e97
run  31491349999
3.12 PASS / 3.13 PASS

32C
head a78e19c7e328c741934e1c09cc3405679d9d2632
run  31491663589
3.12 PASS / 3.13 PASS

32D
head f8d2ecb29d9e623324758f8152f4bc5e2f9a3759
run  31492041581
3.12 PASS / 3.13 PASS

32E
head 33c514a62b83c2812a2d7959852cb286e4af90de
run  31492254418
3.12 PASS / 3.13 PASS

32F implementation candidate
head 52e74952ef6b7b182893f6b478a9b097f0fc1ebb
run  31493232013
3.12 PASS / 3.13 PASS
```

Unrelated heavyweight Pixelorama / Blender / image / vision / FFmpeg / Piper workflows are not part of the normal Phase-32 gate and were skipped/disarmed on these standard heads.

---

## 16. Explicit non-goals preserved

Phase 32 does not add:

- automatic Task execution;
- background Manager queues;
- recursive plan execution/replanning;
- automatic Task state transitions;
- model-controlled adapter registration;
- generic `call_tool` authority;
- shell/argv execution chosen by catalog/policy/model;
- dynamic plugin installation;
- hidden cross-adapter workflows;
- fuzzy capability matching;
- implicit installed-backend fallback;
- automatic model/profile loading;
- resource lease acquisition during routing inspection;
- automatic Artifact adoption/signing;
- automatic Project Intelligence / Design Bible mutation;
- cockpit mutation;
- automatic merge/release;
- live self-training/self-modification.

---

## 17. Exit condition

Phase 32's implementation exit condition is met when the final documentation/roadmap closure head passes the normal exact-head Python 3.12/3.13 matrix.

The implementation already proves that Origin Forge can take one canonical Task with exact `required_capabilities`, one immutable infrastructure-owned production capability catalog, and one exact routing policy and deterministically produce either:

```text
ROUTABLE → exact trusted adapter identity/fingerprint
```

or a bounded fail-closed routing reason, while leaving production execution authority unchanged.

The same durable inputs reconstruct the same route after restart, and read-only route inspection has zero execution/mutation authority.

The next future orchestration boundary can therefore consume:

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

## 18. Final merge gate

Code implementation head `52e74952ef6b7b182893f6b478a9b097f0fc1ebb` is green on the normal Python 3.12/3.13 matrix.

The documentation/roadmap closure commit created after that proof changes the SHA and must independently pass:

```text
normal GitHub Actions Python 3.12 PASS
normal GitHub Actions Python 3.13 PASS
```

Then, and only then:

```text
unchanged exact head
clean reviews / review threads
        ↓
ready-for-review
        ↓
SHA-guarded squash merge
        ↓
verify actual main commit
```

No post-CI repository self-edit is required after the final closure proof; final workflow/merge metadata can remain in the PR closure record.