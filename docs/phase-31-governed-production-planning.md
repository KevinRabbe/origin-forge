# Phase 31 — Governed Production Planning & Dependency Graph

Status: **PLANNED — post-v0.1 architecture contract**

Phase 31 implements the missing Manager-side planning substrate between a durable Goal and the already-proven bounded Task execution layers.

Origin Forge already has durable Goal / Flow / Task state, isolated execution, verification, Project Intelligence, media/runtime evidence, bounded retry policy, resource scheduling, and a read-only production cockpit. The remaining structural gap for integrated production is that one high-level Goal still lacks a governed, reconstructable mechanism for proposing a multi-step cross-domain work graph, validating that graph independently, materializing it into canonical Flow / Task state only under explicit authority, and determining which Tasks are eligible to execute from durable dependency evidence.

The architecture baseline already assigns these responsibilities to the Manager: read the Goal and verified project state, decompose work into bounded Tasks, determine dependencies and priority, assign budgets/capabilities, and handle blocked work. Phase 31 makes that responsibility explicit and testable without turning a planning model into production authority.

Core rule:

```text
planner proposes structure
infrastructure validates structure
explicit authority materializes canonical work
durable verified state determines readiness
```

A plan is not a Task, a Verification, an approval, or execution authority.

---

## 1. Goals

Phase 31 v1 must provide:

1. **Frozen planning input** bound to one existing Goal revision and exact project-state evidence.
2. **Bounded plan proposals** describing proposed Task contracts and dependency edges without canonical Task IDs or direct state mutation.
3. **Independent structural plan audit** that recomputes proposal identity, validates bounds, rejects cycles/unknown references, and prevents authority amplification.
4. **Canonical same-Flow Task dependency state** in Origin Forge's durable truth store.
5. **Explicit materialization authority** that atomically creates the approved Flow / Tasks / dependency edges through normal infrastructure-owned state APIs.
6. **Deterministic readiness resolution** from canonical dependency outcomes, without a hidden autonomous queue or planner-controlled state transition.
7. **Read-only inspection** of planning inputs, proposals, audits, dependency graphs, and readiness reasons.
8. **Restart/replay safety**: the same durable state reconstructs the same dependency eligibility after process restart.

Phase 31 does **not** need to execute the resulting Tasks automatically to satisfy v1.

---

## 2. Explicit non-goals

Phase 31 does not add:

- direct model writes to Goal / Flow / Task state;
- planner authority to verify or complete a Task;
- automatic merge or release;
- generic model-facing tool execution;
- recursive planner → planner delegation;
- hidden background workers or an unbounded autonomous queue;
- cross-project dependencies;
- arbitrary dependency expressions or model-written predicates;
- dependency edges based on hidden model reasoning;
- automatic Artifact adoption/signing;
- automatic Design Bible or Project Intelligence mutation;
- automatic Skill/routing/context/model activation;
- live self-improvement or model-weight mutation;
- a second workflow database parallel to canonical Origin Forge state.

The Planner remains proposal-only.

---

## 3. Phase 31 identities

Infrastructure owns all durable identities.

Recommended v1 prefixes:

```text
PLINPUT-*   frozen planning input
PLPROP-*    immutable plan proposal
PLAUD-*     independent structural plan audit
PLMAT-*     materialization evidence record
```

Canonical production work continues to use the existing:

```text
GOAL-*
FLOW-*
TASK-*
RUN-*
VERIFY-*
```

A model may use short proposal-local `step_key` values such as `design`, `code`, `sprite`, or `runtime-test` only for references inside one proposal. It may not choose canonical `FLOW-*` or `TASK-*` identities.

---

## 4. Frozen planning input

`PlanningInput` is an immutable content-addressed package for one planning pass.

Minimum binding:

```text
planning_input_id
project_id
goal_id
goal_revision
goal_content_hash
existing_flow_refs
verified_task_summary_refs
active_design_rule_refs
project_intelligence_snapshot_hash
capability_catalog_hash
model_policy_snapshot_hash
resource_policy_snapshot_hash
created_at
content_hash
```

The input package contains bounded projections, not arbitrary database rows or repository bytes.

The v1 Planner context may include:

- exact Goal objective / success criteria / constraints / budgets;
- current terminal Task outcome summaries relevant to that Goal;
- bounded active Project Intelligence Entities / relations relevant to the Goal;
- applicable active Design Rules;
- a bounded infrastructure-owned capability catalog describing currently supported production surfaces;
- bounded configured model/resource policy summaries where planning depends on capability availability.

The planning package must exclude by default:

- secret key material;
- raw Phase-18 private signing state;
- arbitrary Artifact bytes;
- arbitrary repository file contents;
- unrestricted Verification evidence blobs;
- mutable runtime handles or resource leases;
- direct database access.

Every included evidence item must carry an exact stable identity/hash/revision sufficient for later revalidation.

---

## 5. Bounded model-facing proposal shape

A Planner model may propose only inert structured data.

Conceptual v1 shape:

```json
{
  "summary": "Implement and verify the requested feature across code and media.",
  "steps": [
    {
      "step_key": "code",
      "objective": "Implement gameplay behavior.",
      "acceptance_criteria": ["..."],
      "constraints": ["..."],
      "required_capabilities": ["code"],
      "priority": 50,
      "budget_hint": {"attempts": 2},
      "depends_on": []
    },
    {
      "step_key": "runtime-test",
      "objective": "Verify runtime behavior.",
      "acceptance_criteria": ["..."],
      "constraints": ["..."],
      "required_capabilities": ["runtime-observation"],
      "priority": 40,
      "budget_hint": {"attempts": 1},
      "depends_on": ["code"]
    }
  ]
}
```

The exact schema is infrastructure-owned.

The proposal must not contain:

- canonical Goal / Flow / Task status assignments;
- canonical IDs selected by the model;
- SQL;
- shell commands;
- executable code;
- arbitrary filesystem paths as authority grants;
- model/tool credentials;
- approval flags;
- verification outcomes;
- merge/release/signing/adoption actions;
- model profile overrides outside an explicitly disclosed allowed policy surface;
- nested sub-plans, loops, recursion, callbacks, or conditional executable expressions.

---

## 6. Proposal bounds

Initial v1 hard bounds should be conservative and covered by regression tests.

Recommended ceilings:

```text
max planning-input bytes           512 KiB
max Planner response bytes         256 KiB
max proposed Tasks                 64
max dependency edges               192
max dependency depth               16
max acceptance criteria / Task     32
max constraints / Task             32
max required capabilities / Task   16
max text field bytes               bounded per schema
max Planner calls / proposal       1
```

The implementation may select smaller limits when source-level constraints justify them.

All limits are enforced before expensive graph processing or durable publication where practical.

---

## 7. Strict proposal parser

The parser is infrastructure-owned and fail-closed.

It must reject at least:

- malformed or noncanonical JSON;
- duplicate JSON keys;
- unknown top-level or step fields;
- duplicate `step_key` values;
- missing dependency targets;
- self-dependencies;
- duplicate dependency edges;
- cycles;
- depth/edge/task-count overflow;
- empty objectives or acceptance contracts;
- unknown capability identifiers;
- illegal priority/budget values;
- oversized scalar/string/list values;
- model-supplied canonical IDs;
- authority/status/verification/adoption/signing/merge/release fields;
- pathological numeric values.

Normalization may canonicalize representation but must not silently strengthen authority or invent missing acceptance criteria.

---

## 8. Independent structural audit

Every publishable `PlanProposal` requires an independently computed `PlanAudit`.

The Auditor recomputes:

- planning-input hash and exact Goal binding;
- proposal canonical hash;
- all local step references;
- graph acyclicity;
- graph depth;
- task/edge counts;
- capability membership;
- all schema/resource bounds;
- absence of forbidden authority fields;
- deterministic topological ordering evidence;
- materialization eligibility prerequisites.

Audit outcomes:

```text
PASS
FAIL
```

A structural `PASS` means only that the plan is internally valid and bounded. It does **not** prove the plan is semantically good, sufficient, optimal, or approved.

A Planner may not audit its own proposal for authority purposes.

---

## 9. Canonical Task dependency graph

Phase 31 adds explicit canonical dependency relationships to the existing durable production state instead of hiding them in `Flow.state_json` or model context.

V1 supports one dependency semantic:

```text
REQUIRES_SUCCESS
```

Meaning:

> the dependent Task is not eligible for execution until the required Task has reached the existing canonical successful terminal state and its required production verification contract is satisfied.

V1 dependency constraints:

- both Tasks belong to the same Project;
- both Tasks belong to the same materialized Flow;
- no self-edge;
- no duplicate active edge;
- no cycle;
- deterministic ordering;
- dependency mutations are infrastructure-owned and revision/event tracked;
- a materialized graph cannot be silently rewritten by a Planner.

More expressive dependency kinds are deferred until there is a measured requirement.

---

## 10. Materialization boundary

A valid audited proposal remains inert until an authorized caller explicitly materializes it.

Materialization must:

1. re-load and revalidate the exact PlanningInput, PlanProposal, and PlanAudit;
2. confirm the bound Goal still exists at the expected revision/identity or fail stale;
3. confirm the proposal has not already been materialized;
4. allocate canonical infrastructure-owned Flow / Task IDs;
5. map proposal-local `step_key` values to those new canonical Task IDs;
6. create Task contracts using existing runtime/store authority checks;
7. create dependency edges using canonical Task IDs;
8. record an immutable `PLMAT-*` mapping from proposal identity to the created canonical objects;
9. commit atomically or leave no partial Flow / Task graph.

A materialization call is an explicit authority action. It is not triggered by reading a proposal, completing a Planner Run, or obtaining a structural audit `PASS`.

The v1 CLI should not expose model-driven implicit materialization.

---

## 11. Deterministic readiness resolution

Phase 31 provides a read-side resolver that explains whether a materialized Task is dependency-eligible.

Conceptual outcomes:

```text
READY
WAITING_ON_DEPENDENCIES
BLOCKED_BY_FAILED_DEPENDENCY
TERMINAL
INVALID_GRAPH
```

The exact names may align with existing runtime enums rather than introducing duplicate Task states.

The resolver must derive its answer from canonical durable state each time. It must not depend on an in-memory queue, Planner memory, or prior conversation.

For every non-ready result it should provide bounded exact reasons such as:

```text
required_task_id
required_task_status
required_verification_status
```

Readiness inspection itself performs no Task transition and starts no execution.

Any later scheduler integration must consume this deterministic resolver rather than reimplement dependency semantics inside a model loop.

---

## 12. Planner model boundary

If Phase 31 wires a real Planner model invocation, it must reuse existing governed model infrastructure.

Requirements:

- fresh one-shot model context;
- configured Planner-capable semantic role/policy;
- resource admission through existing Phase-14 policy;
- bounded request/response/token/time accounting;
- no direct tool execution;
- no direct filesystem/database access;
- exact PlanningInput hash in Run evidence;
- exact raw-response hash and parsed-proposal hash;
- ordinary model/transport/parser failures represented as bounded failure evidence;
- Planner completion never materializes work by itself.

A deterministic/manual proposal path should remain available for unit/adversarial tests so Phase 31 contracts do not depend on a live model service.

---

## 13. Persistence

Planning evidence must be durable and reconstructable.

Preferred placement:

- canonical Goal / Flow / Task / dependency state: existing protected SQLite truth store;
- immutable planning input/proposal/audit/materialization evidence: either normalized protected SQLite records or a dedicated immutable protected store, selected based on current repository conventions.

Whichever representation is chosen must provide:

- no silent overwrite of immutable evidence;
- exact content hashes;
- project/Goal binding;
- referential validation;
- bounded load/list behavior;
- duplicate-key/canonical JSON validation for file-backed evidence;
- protected-root/symlink/alias containment where filesystem persistence is used;
- deterministic ordering;
- restart reconstruction.

Phase 31 must not create a second source of truth for Task status.

---

## 14. Operator surfaces

The initial operator surface should separate read-only inspection from explicit mutation.

Read-only examples:

```text
origin-forge plan status
origin-forge plan show <PLPROP-ID>
origin-forge plan audit-show <PLAUD-ID>
origin-forge plan graph <FLOW-ID>
origin-forge plan readiness <TASK-ID>
```

Explicit materialization, if exposed through CLI in v1, must be unmistakably operator-authorized and require an exact proposal identity plus audit identity. It must never be combined with Planner execution in one implicit command.

The Phase-30 cockpit remains read-only. Phase 31 does not add cockpit mutation controls.

---

## 15. Cross-domain planning semantics

Phase 31 is intentionally media/software neutral.

A plan may propose bounded Tasks requiring existing capabilities such as:

```text
code
project-intelligence
pixelorama-2d
image-generation
vision-inspection
model3d
blender-3d
audio
runtime-observation
playtesting
simulation
provenance
```

Capability names are infrastructure-owned catalog identifiers, not arbitrary model-defined strings.

The planner may express ordering/dependency structure across those capabilities but does not gain their execution permissions.

Example:

```text
specification
   ├─→ gameplay-code ─→ integration-test ─→ runtime-observation
   ├─→ visual-design ─→ 2d/3d-assets ─────┘
   └─→ audio-design ─→ audio-assets ───────┘
                                   ↓
                              playtest
```

This is dependency evidence, not a hidden agent swarm.

---

## 16. Staleness and re-planning

A frozen plan may become stale after materialization or after unrelated verified project changes.

V1 rules:

- an unmaterialized proposal must fail closed if its bound Goal revision no longer matches;
- planning-input evidence drift invalidates materialization;
- already materialized canonical Tasks remain historical durable state and are not deleted/replaced automatically;
- replanning creates a new PlanningInput / PlanProposal / PlanAudit lineage;
- a new plan may supersede a prior planning Decision/evidence record only through explicit infrastructure/human authority;
- Planner output cannot silently rewrite active Tasks or dependencies.

Automatic dynamic replanning after every failure is deferred.

---

## 17. Failure and blocked semantics

Phase 31 distinguishes:

- Planner/model failure;
- proposal parser failure;
- structural audit failure;
- stale planning evidence;
- materialization conflict;
- dependency waiting;
- failed prerequisite;
- production Task failure.

These classes must not collapse into a generic "agent failed" state.

A failed prerequisite does not authorize deletion, bypass, or automatic replacement of the dependency edge.

Recovery must be explicit and durable.

---

## 18. Security and authority invariants

Mandatory regressions should prove:

- model-selected canonical IDs are rejected;
- a Planner cannot set Task/Flow status;
- a Planner cannot claim Verification PASS;
- a Planner cannot authorize merge/release/signing/adoption;
- cyclic graphs are rejected before publication/materialization;
- unknown/missing dependency refs fail closed;
- same-Flow/project dependency constraints are enforced;
- stale Goal/input evidence cannot materialize;
- duplicate materialization cannot create a second graph;
- materialization is atomic under injected failures;
- readiness inspection never mutates state;
- restart yields the same readiness classification from the same durable state;
- failed prerequisite Tasks cannot be bypassed by Planner output;
- no model call is required to determine dependency readiness.

---

## 19. Acceptance test plan

Phase 31 closure requires normal Python 3.12 and 3.13 coverage for at least:

### Contracts

- content-addressed PlanningInput;
- strict PlanProposal parser;
- canonical proposal hashing;
- graph bounds and acyclicity;
- structural audit recomputation.

### Durable dependency state

- create/read/list dependency edges;
- same-project / same-Flow enforcement;
- duplicate/self/cycle rejection;
- deterministic graph traversal/topological ordering;
- persistence across restart.

### Materialization

- exact evidence revalidation;
- canonical ID allocation outside model control;
- atomic Flow/Task/edge creation;
- stale Goal rejection;
- duplicate materialization rejection;
- rollback/no partial graph on failure.

### Readiness

- root Task eligible when otherwise runnable;
- dependent Task waits while prerequisites are nonterminal;
- dependent Task becomes eligible only after canonical successful prerequisite evidence;
- failed prerequisite produces blocked evidence;
- multi-parent dependency requires every prerequisite;
- restart preserves identical result.

### Authority

- no Planner self-verification;
- no model-triggered materialization;
- no cockpit mutation;
- no merge/release/adoption/signing authority;
- bounded parser/model/persistence failure behavior.

### Optional real model evidence

If a trusted Planner model path is enabled during Phase 31, one separately governed evidence workflow may prove the real adapter against a frozen small planning fixture. The normal CI matrix must remain independent of that external model service.

---

## 20. Phased implementation order

Recommended internal sequence:

```text
31A  identities + frozen planning contracts
 ↓
31B  strict parser + independent structural auditor
 ↓
31C  canonical Task dependency persistence + graph queries
 ↓
31D  explicit atomic materialization
 ↓
31E  deterministic readiness resolver
 ↓
31F  bounded Planner model adapter/evidence
 ↓
31G  read-only operator inspection + closure hardening
```

Each slice must preserve the proposal/evidence/authority separation before the next slice begins.

---

## 21. Exit condition

Phase 31 is complete when one immutable repository head proves that Origin Forge can:

- freeze bounded exact planning evidence for a durable Goal;
- accept a bounded Planner proposal without canonical state authority;
- independently validate and audit a finite cross-domain Task dependency graph;
- explicitly and atomically materialize an approved plan into canonical Flow / Task / dependency state with infrastructure-owned IDs;
- reconstruct deterministic Task dependency eligibility from durable verified state across restart;
- inspect the entire planning/dependency chain without requiring old model conversation state;
- preserve all existing verification, Artifact adoption/signing, merge, release, Project Intelligence, model/resource, and cockpit authority boundaries.

The final immutable Phase-31 head must pass the normal Python 3.12 and Python 3.13 matrix with unrelated heavyweight evidence workflows skipped/disarmed before ready-for-review transition and SHA-guarded merge.
