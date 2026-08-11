# Phase 31 — Governed Production Planning & Dependency Graph

Status: **IMPLEMENTED — final exact-head closure gate pending**

Phase 31 adds the missing Manager-side planning substrate between a durable Goal and Origin Forge's already-governed Task execution layers.

The implementation preserves the architectural split:

```text
planner proposes structure
        ↓
infrastructure parses + independently audits
        ↓
explicit authority materializes canonical work
        ↓
durable Task + Verification state determines dependency readiness
```

A plan is evidence. It is not a Task, a Verification, approval, execution authority, Artifact adoption, merge, or release authority.

---

## 1. Implemented boundary

Phase 31 v1 now provides:

1. infrastructure-owned `PLINPUT-*`, `PLPROP-*`, `PLAUD-*`, and `PLMAT-*` identities;
2. bounded frozen `PlanningInput` evidence bound to an exact Goal revision/hash and bounded project/capability/policy evidence;
3. inert bounded `PlanStep` / `PlanProposal` contracts with proposal-local keys only;
4. strict duplicate-key-aware JSON proposal parsing;
5. deterministic finite DAG validation with bounded task count, edge count, depth, text, capabilities, and attempt hints;
6. independently recomputed `PlanAudit` evidence;
7. canonical same-Flow `REQUIRES_SUCCESS` Task dependency state in SQLite;
8. atomic audited-plan materialization into canonical Flow / Task / dependency state with infrastructure-owned IDs;
9. immutable `PLMAT-*` materialization evidence linking proposal-local step keys to canonical Task IDs;
10. deterministic dependency readiness derived from canonical Task and Task-Verification state;
11. one-shot proposal-only Planner model execution behind the existing governed model/resource scheduler;
12. non-creating, non-migrating read-only planning inspection over the Phase-30 immutable SQLite guard;
13. a read-only `origin-forge-plan` module CLI for planning evidence, graph, and readiness inspection.

Phase 31 does **not** automatically execute materialized Tasks.

---

## 2. Authority invariants

The following remain outside Phase 31 Planner authority:

- direct Goal / Flow / Task writes;
- canonical ID selection by a model;
- Task state transitions;
- Task Verification PASS or Task completion;
- arbitrary shell, SQL, filesystem, process, or generic tool execution;
- Artifact adoption or provenance signing;
- Design Bible / Project Intelligence mutation;
- Skill, context, routing, or model-profile activation;
- automatic retry recursion or hidden autonomous queues;
- automatic merge or release;
- Phase-30 cockpit mutation;
- live self-training or model-weight mutation.

The Planner may produce exactly one inert structured proposal per Planner Run. A successful Planner Run does not audit or materialize the proposal automatically.

---

## 3. Frozen planning evidence

`PlanningInput` is bound to:

```text
PLINPUT identity
project identity
Goal identity
Goal revision
canonical Goal planning hash
bounded verified-state refs
bounded active Design Rule refs
Project Intelligence snapshot hash
capability-catalog hash
infrastructure-owned capability IDs
model-policy hash
resource-policy hash
```

The Planner context exposes a bounded semantic projection rather than arbitrary database rows, repository bytes, secrets, or runtime handles.

The current Goal planning hash covers the canonical planning-relevant Goal projection:

```text
id
project_id
objective
success criteria
constraints
budgets
priority
status
revision
```

An unmaterialized PlanningInput becomes stale if the bound Goal revision/hash changes. Staleness fails before a Planner model call or before materialization.

---

## 4. Proposal contract

A PlanStep contains only:

```text
step_key
objective
acceptance_criteria
constraints
required_capabilities
priority
budget_hint.attempts
depends_on
```

Proposal-local `step_key` values are inert references. They never become canonical IDs.

Implemented v1 bounds include:

```text
Planner response             <= 256 KiB before JSON parsing
proposed Tasks               1..64
dependency edges             <= 192
dependency depth             <= 16
acceptance criteria / Task   <= 32
constraints / Task           <= 32
required capabilities / Task <= 16
attempt hint                 1..16
Planner calls / Run          exactly 1
```

Text/token fields are independently bounded by the model contract.

The strict parser rejects:

- malformed UTF-8/JSON;
- duplicate JSON keys;
- unknown fields;
- model-supplied canonical ID fields;
- approval/status/verification/authority fields;
- duplicate step keys;
- unknown dependencies;
- self-dependencies;
- duplicate edges;
- cycles;
- depth/task/edge overflow;
- unknown capability identifiers;
- bool-as-integer ambiguity;
- pathological JSON integers;
- oversized output.

---

## 5. Independent structural audit

`PlanAudit` recomputes the proposal/input relationship and records:

```text
PLAUD identity
PlanningInput ID/hash
PlanProposal ID/hash
PASS / FAIL
task count
edge count
max depth
deterministic topological step order
bounded failure reason when applicable
```

A structural `PASS` means only that the proposal is bounded and structurally valid against the frozen PlanningInput. It is not semantic proof, Task Verification, approval, or materialization authority.

Published audit evidence is revalidated against an independently recomputed audit before use.

---

## 6. Canonical Task dependencies

Schema v6 introduced canonical `task_dependencies` state.

V1 supports exactly:

```text
REQUIRES_SUCCESS
```

For an edge:

```text
dependent Task -> required Task
```

both Tasks must belong to the same Flow.

Durable defenses include:

- foreign keys to canonical Tasks;
- composite uniqueness;
- self-edge rejection;
- exact dependency-type constraint;
- same-Flow trigger;
- recursive cycle-rejection trigger;
- deterministic dependency/dependent listing;
- deterministic topological graph reconstruction;
- dependency creation state events;
- restart persistence.

No second Task-status source of truth exists.

---

## 7. Immutable planning evidence persistence

Schema v7 added normalized immutable evidence tables:

```text
planning_inputs
plan_proposals
plan_audits
plan_materializations
```

Each persisted object carries:

```text
schema version
canonical payload
content hash
relational foreign-key bindings
creation timestamp
```

Read paths reparse canonical JSON, reconstruct typed contracts, recompute hashes, and revalidate relationships before returning evidence.

Duplicate publication fails closed rather than overwriting historical evidence.

---

## 8. Explicit atomic materialization

`ProductionPlanningEvidenceStore.materialize(...)` requires exact identities for:

```text
PLINPUT
PLPROP
PLAUD
```

Materialization re-loads and revalidates every object, requires an independently recomputed structural PASS, rechecks the current Goal revision/hash, and rejects duplicate materialization.

Only then does infrastructure allocate:

```text
FLOW-*
TASK-*
PLMAT-*
```

The proposal cannot choose those canonical IDs.

One SQLite transaction creates:

- the canonical Flow;
- every canonical Task contract;
- exact step-key -> Task-ID bindings;
- canonical dependency edges;
- Flow / Task / dependency state events;
- immutable `PLMAT-*` evidence.

Any failure rolls the entire transaction back. Adversarial tests inject a mid-transaction event-ID collision after writes have begun and prove that no partial Flow, Task, dependency, materialization, or associated event survives.

---

## 9. Deterministic dependency readiness

Readiness is recomputed from durable canonical state every time. It never depends on Planner memory, an in-memory queue, or an LLM call.

Read-side classifications are:

```text
READY
WAITING_ON_DEPENDENCIES
BLOCKED_BY_FAILED_DEPENDENCY
INVALID_DEPENDENCY_STATE
ACTIVE
TERMINAL
```

For `REQUIRES_SUCCESS`, a prerequisite is satisfied only when:

```text
required Task status == SUCCEEDED
AND
at least one canonical Task Verification status == PASS
```

A prerequisite in `FAILED`, `QUARANTINED`, or `CANCELLED` yields blocked dependency evidence.

A corrupted prerequisite recorded as `SUCCEEDED` without a PASS Task Verification is classified `INVALID_DEPENDENCY_STATE` rather than being treated as satisfied.

Inspection produces bounded reasons containing the exact required Task ID, status, verification condition, and reason kind. It performs no Task transition and starts no Run.

---

## 10. Governed Planner model boundary

`BoundedProductionPlanner` supports only:

1. the existing Phase-14 `ScheduledModelAdapter` for governed real inference; or
2. an infrastructure-owned deterministic no-I/O fixture adapter for unit/manual evidence.

Arbitrary unscheduled `ModelAdapter` instances are rejected.

A pre-materialization Planner Run is legitimately Task-less:

```text
role = PLANNER
task_id = null
```

`ModelRequest.task_id` was widened to `str | None` for this governed case; existing Task-bound worker paths continue to pass canonical Task IDs.

The real scheduled path retains Phase-14 behavior:

- explicit profile/policy selection;
- resource admission before model load;
- lease held through generation;
- selected-profile evidence;
- unload before resource release.

Planner generation records Run-level evidence for:

```text
PlanningInput ID/hash
request hash
raw response hash
PlanProposal ID/hash
model ID/hash
response bytes
token counts
model_calls = 1
materialized = false
```

Malformed model output fails the Planner Run and creates no proposal, Flow, Task, audit, or materialization.

---

## 11. Read-only inspection

Phase 31 reuses Phase 30's `production_read_connection` instead of the normal create/migrate store lifecycle.

Planning inspection therefore requires:

- existing protected config/database state;
- exact current schema;
- project-root binding;
- no active WAL/SHM/rollback-journal state;
- immutable/query-only SQLite access;
- unchanged database identity/size/mtime through the inspection.

The inspector revalidates:

- PlanningInput canonical hash and project/Goal relationship;
- PlanProposal canonical hash and exact input binding;
- PlanAudit canonical hash and independent recomputation;
- PlanMaterialization hashes and relational input/proposal/audit/Goal/Flow bindings;
- exact materialized Task contracts against the frozen PlanSteps;
- exact materialized dependency graph against the frozen proposal.

It also exposes connection-bound canonical Flow graph and Task readiness inspection without entering the normal writer store path.

---

## 12. Read-only module CLI

The module CLI is intentionally not added as a new v0.1 package entrypoint.

It may be invoked as:

```text
python -m origin_forge.production_planning_cli --project-root <project> status
python -m origin_forge.production_planning_cli --project-root <project> input-show <PLINPUT-ID>
python -m origin_forge.production_planning_cli --project-root <project> proposal-show <PLPROP-ID>
python -m origin_forge.production_planning_cli --project-root <project> audit-show <PLAUD-ID>
python -m origin_forge.production_planning_cli --project-root <project> materialization-show <PLMAT-ID>
python -m origin_forge.production_planning_cli --project-root <project> graph <FLOW-ID>
python -m origin_forge.production_planning_cli --project-root <project> readiness <TASK-ID>
```

There is no CLI command for:

```text
generate
approve
materialize
run
verify
adopt
sign
merge
release
```

Help and uninitialized inspection create no `.origin-forge` state.

---

## 13. Implementation modules

Primary Phase-31 implementation:

```text
src/origin_forge/ids.py
src/origin_forge/state.py
src/origin_forge/migrations.py
src/origin_forge/model.py
src/origin_forge/production_planning_models.py
src/origin_forge/production_planning_proposal.py
src/origin_forge/task_dependencies.py
src/origin_forge/production_planning_evidence.py
src/origin_forge/task_readiness.py
src/origin_forge/production_planner.py
src/origin_forge/production_planning_inspection.py
src/origin_forge/production_planning_cli.py
```

The implementation deliberately reuses existing runtime/store, Run, Verification, Phase-14 model scheduling, and Phase-30 immutable read boundaries.

---

## 14. Verification coverage

Phase-31 regressions cover:

- new infrastructure ID families;
- canonical PlanningInput hashing/bounds;
- strict proposal parser and authority-field rejection;
- duplicate JSON key rejection;
- finite DAG validation/cycle rejection/topological evidence;
- exact capability binding;
- canonical dependency persistence and database defenses;
- same-Flow/self/duplicate/cycle rejection;
- restart graph reconstruction;
- immutable evidence publication and tamper detection;
- stale Goal rejection;
- infrastructure-owned canonical materialization IDs;
- duplicate materialization rejection;
- atomic rollback under injected mid-transaction failure;
- deterministic multi-parent readiness;
- failed prerequisite evidence;
- SUCCEEDED-without-PASS fail-closed handling;
- restart-identical readiness;
- one-shot taskless Planner Runs;
- scheduled-model resource evidence and lease release;
- generic unscheduled model rejection;
- invalid-model-output cleanup;
- non-creating immutable planning inspection;
- materialized Task/dependency drift detection;
- read-only CLI authority surface;
- source-level absence of mutation/model/materialization authority in inspection paths.

---

## 15. Exact-head evidence so far

Each completed implementation slice passed the normal Ubuntu matrix before the next slice began:

```text
31A + 31B  run 31486070627  Python 3.12 PASS / Python 3.13 PASS
31C        run 31486512755  Python 3.12 PASS / Python 3.13 PASS
31D        run 31486992452  Python 3.12 PASS / Python 3.13 PASS
31E        run 31487242234  Python 3.12 PASS / Python 3.13 PASS
31F        run 31487871034  Python 3.12 PASS / Python 3.13 PASS
31G code   run 31488574588  Python 3.12 PASS / Python 3.13 PASS
```

Unrelated heavyweight Pixelorama / Blender / image / vision / FFmpeg / Piper evidence workflows remained skipped/disarmed on the normal implementation heads.

The documentation/roadmap closure edit creates a new immutable candidate SHA and therefore requires its own final Python 3.12/3.13 matrix before ready-for-review and merge.

---

## 16. Explicit non-goals retained

Phase 31 does not add:

- automatic Task execution after materialization;
- automatic retry/replanning recursion;
- hidden Manager queues;
- cross-project dependencies;
- arbitrary dependency expressions;
- dynamic model-written predicates;
- production Task self-verification;
- automatic Artifact adoption/signing;
- automatic Project Intelligence / Design Bible mutation;
- arbitrary model tool execution;
- cockpit mutation;
- automatic merge/release;
- live self-training/self-modification.

Any later orchestration layer must consume Phase 31's durable dependency/readiness contracts rather than reimplementing those semantics inside a model loop.

---

## 17. Closure condition

Phase 31 is implementation-complete when one immutable repository head contains the code, tests, this implementation contract, and the synchronized canonical roadmap, and that exact head passes the normal Python 3.12 and Python 3.13 matrix with unrelated heavyweight evidence workflows skipped/disarmed.

After that exact-head proof, closure is mechanical:

```text
clean review/thread state
        ↓
SHA-guarded squash merge
        ↓
verify actual main commit
```

No post-CI documentation edit is required; the pull request, workflow run, and merge result are the external closure record.
