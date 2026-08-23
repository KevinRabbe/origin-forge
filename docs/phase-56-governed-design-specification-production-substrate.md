# Phase 56 — Governed Design Specification Production Substrate

Status: **FROZEN ARCHITECTURE — implementation not yet authorized by this document alone**

Phase 56 closes the earliest v1.0 production-readiness blocker identified by the accepted R1 evidence matrix: Origin Forge can already preserve canonical project semantics and can already plan bounded production work, but it does not yet own a governed operation that turns one exact current high-level Goal into one independently accepted, durable, auditable design specification.

Phase 56 is deliberately upstream of ordinary production Task decomposition. It does **not** turn Planner output, conversation text, a Task objective, model prose, a browser submission, or a generic Artifact into design authority by implication.

The core law is:

```text
exact current Goal revision/hash
+ exact current Phase-17 Design Rule / Project Intelligence evidence
+ exact bounded capability/policy evidence
→ immutable design-specification input
→ one governed proposal-only model Run
→ strict parser + independent structural audit
→ explicit HUMAN_OPERATOR semantic acceptance
→ immutable accepted design-specification identity/hash
→ Phase-31 PlanningInput consumes that exact current accepted evidence
→ downstream production planning
→ STOP
```

A Phase-56 acceptance states only that the human operator accepted the exact immutable design specification against the exact source evidence bound into it. It does not mutate canonical Project Intelligence, supersede Design Rules, complete downstream production Tasks, adopt media, sign provenance, merge, deploy, or release.

---

## 1. Why Phase 56 is the next production slice

The accepted v1.0 R1 matrix classifies the first representative-lifecycle target as:

```text
high-level Goal → governed design specification
= BLOCKED_ON_IMPLEMENTATION
```

Current accepted strengths are intentionally separated:

- Phase 17 owns canonical Entity / relation / binding / Design Rule semantics;
- Phase 31 owns immutable Goal-bound PlanningInput, proposal, audit, Task-DAG materialization, and dependency readiness;
- Phase 32 knows semantic capability `design.specify` but deliberately gives it no built-in executor;
- later dispatch/Manager phases execute already-materialized production Tasks;
- current media production families consume already-governed semantic/source inputs rather than manufacturing missing semantic authority.

The missing boundary is therefore not another Planner and not another generic Artifact writer. It is a governed, pre-planning design-specification evidence family with explicit semantic acceptance.

R1 also identifies the immediately downstream gap:

```text
design specification → decomposed production Task DAG
```

Phase 56 must therefore end with a safe bridge into the existing Phase-31 PlanningInput boundary. It must not replace Phase 31 or create a second Task-DAG authority.

---

## 2. Exact repository facts this architecture binds

Phase 56 architecture starts from accepted `main` at:

```text
cfe72f86438e98d215f5e55906b203d5fdac5b97
```

The current database line is **schema v20**. `src/origin_forge/db.py` composes the current migration sequence and derives `SCHEMA_VERSION` from the final Blender production Task-acceptance migration. Phase 56 therefore reserves **schema v21** for the design-specification evidence family if and when implementation is authorized.

Phase 17 establishes the semantic distinction:

```text
files and artifacts = implementation evidence
entities and rules   = semantic project structure
```

Its canonical semantic objects remain infrastructure-governed Entities, EntityRelations, EntityBindings, and DesignRules. Phase 56 may read exact current projections of those objects; it may not create, edit, retire, supersede, or silently reinterpret them.

Phase 31 already defines the evidence shape required for deterministic planning context. `PlanningInput` binds:

- project identity;
- Goal identity;
- Goal revision;
- canonical Goal planning hash;
- bounded verified-state refs;
- bounded active Design Rule refs;
- Project Intelligence snapshot hash;
- capability-catalog hash and exact capability IDs;
- model-policy hash;
- resource-policy hash.

Phase 31 also proves an accepted pre-materialization precedent: a governed Planner Run may legitimately be Task-less. Phase 56 uses the same authority shape for design specification because the accepted design specification must exist **before** the downstream Phase-31 Task DAG that consumes it.

The current generic `artifacts` table is intentionally insufficient as the Phase-56 canonical object. Its contract contains project/change/type/path-or-URI/content-hash/lineage/tool metadata/status, but it does not intrinsically bind exact Goal revision/hash, exact Design Rule set, exact Project Intelligence hash, independent semantic acceptance, or derived currentness. `content_hash` is also not the sole semantic-currentness authority.

The generic `verifications` table is also insufficient by itself. It is append-only evidence around a target, but generic Verification does not define the Phase-56 source-currentness, uniqueness, or human semantic-acceptance relation.

Therefore Phase 56 freezes a deliberately separate immutable design-specification family. A later exported document may also be represented by an Artifact, but that Artifact is not the canonical design-specification authority.

---

## 3. Permanent authority model

### 3.1 Phase 17 remains semantic truth

Phase 56 derives from canonical project semantics; it does not become a second Design Bible.

A design specification may summarize, specialize, or organize the current Goal and current semantic evidence for production planning. It may not:

- create canonical Entities;
- change Entity identity;
- create/retire semantic relations;
- create/retire EntityBindings;
- create, lower, retire, or supersede Design Rules;
- write inferred model claims back into Phase-17 state.

If later human refinement requires a canonical semantic change, that change must use the separately governed Phase-17 authority first. The old design specification then becomes stale naturally.

### 3.2 Model output is proposal-only

The Phase-56 model boundary may produce exactly one bounded inert design-specification proposal per governed design Run.

The model may not choose or claim:

- canonical IDs;
- acceptance status;
- Verification PASS;
- Task status;
- semantic authority;
- currentness;
- Artifact adoption;
- provenance/signing state;
- merge/deploy/release state;
- Project Intelligence mutation;
- Design Rule mutation;
- arbitrary shell/filesystem/network/tool authority.

A successful model return is not an accepted specification.

### 3.3 Structural audit is not semantic acceptance

Infrastructure independently parses and audits the proposal against the exact frozen input. A structural PASS proves only that the proposal:

- is bounded canonical JSON;
- satisfies the frozen schema;
- contains no unknown/authority fields;
- uses only allowed capability identifiers;
- respects size/count/text limits;
- binds the exact DesignSpecificationInput;
- contains no caller/model-selected canonical project identities outside explicitly allowed inert evidence refs.

It does not prove that the design is good, complete, fun, aesthetically correct, or faithful enough to the creator's intent.

### 3.4 Human acceptance is explicit

The only Phase-56 semantic acceptance authority is:

```text
HUMAN_OPERATOR
```

Manager, Planner, Reviewer, specialist, vision, simulation, conversation processing, browser/UI, the design model, or a deterministic parser cannot synthesize this decision.

The operator selects one immutable design-specification proposal identity. Infrastructure derives every Goal/input/hash/model/audit relation from durable evidence. No caller-supplied replacement identities or hashes are accepted.

### 3.5 Accepted design specification is derived production evidence

An accepted Phase-56 specification is canonical **production evidence**, not canonical project semantics.

The distinction is permanent:

```text
Phase-17 semantic state = source truth
Phase-56 accepted design specification = immutable accepted derivation
Phase-31 plan = immutable production-structure evidence
```

No later subsystem may reverse this dependency and treat a Phase-56 specification as permission to rewrite Phase-17 truth.

---

## 4. Pre-planning rather than Task-bound execution

The accepted R1 dependency direction is:

```text
Goal
→ design specification
→ Phase-31 planning
→ downstream Tasks
```

Phase 56 therefore must not require a Phase-31-materialized `design.specify` Task as the source of its own authority; doing so would make the required lifecycle circular.

The Phase-56 design Run is pre-materialization and Task-less, using the already-accepted Phase-31 precedent for governed Task-less Planner Runs:

```text
task_id = null
role = DESIGN_SPECIFIER
```

The operation remains infrastructure-owned and bounded. `design.specify` is the semantic capability being executed, but Phase 56 does not widen ordinary Phase-33–36 Task dispatch or grant generic Task-less execution authority to other capability families.

Only the dedicated Phase-56 service may open this Task-less design operation, and only from one exact validated DesignSpecificationInput.

---

## 5. Frozen DesignSpecificationInput

Phase 56A must define an immutable input object with infrastructure-owned identity, proposed prefix:

```text
DESIGNIN-*
```

Minimum canonical fields:

```text
DesignSpecificationInput
- design_input_id
- project_id
- goal_id
- goal_revision
- goal_content_hash
- verified_state_refs[]
- active_design_rule_refs[]
- project_intelligence_hash
- capability_catalog_hash
- capability_ids[]
- model_policy_hash
- resource_policy_hash
```

The semantics deliberately mirror the proven Phase-31 PlanningInput evidence shape, but the object is a separate pre-planning record and must not alias or masquerade as `PLINPUT-*`.

### 5.1 Goal binding

The canonical Goal projection must use the same planning-relevant fields already protected by Phase 31:

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

The exact normalized projection is hashed canonically. Input publication fails unless the Goal belongs to the project and the captured revision/hash match the current durable Goal.

### 5.2 Semantic-state binding

Input construction must use infrastructure-owned reads to derive:

- exact active Design Rule refs with exact content hash/revision;
- exact bounded verified-state refs allowed by the existing semantic-context policy;
- exact deterministic Project Intelligence snapshot hash.

The caller may not supply replacement Design Rule IDs/hashes, Project Intelligence hash, or an arbitrary semantic JSON blob.

### 5.3 Capability/policy binding

The input binds the exact capability catalog and IDs visible to the design proposal plus the exact model/resource policy hashes used to admit the design model Run.

The proposal may mention only capability IDs present in this frozen set. It cannot register or activate capabilities.

### 5.4 Immutability

A published DesignSpecificationInput is write-once. Meaningful Goal/semantic/policy drift creates a new input identity; it never edits the old row.

---

## 6. Frozen design-specification proposal contract

Phase 56A must define one immutable proposal object with infrastructure-owned identity, proposed prefix:

```text
DESIGNSPEC-*
```

Minimum envelope:

```text
DesignSpecification
- design_specification_id
- design_input_id
- design_input_hash
- run_id
- model_id
- model_hash
- specification
```

The canonical `specification` payload is structured inert data. V1 should contain only bounded planning-facing semantic content, conceptually:

```text
summary
requirements[]
  - key
  - statement
  - acceptance_criteria[]
  - constraints[]
deliverables[]
  - key
  - objective
  - acceptance_criteria[]
  - constraints[]
  - required_capabilities[]
```

Proposal-local keys are inert strings, never canonical IDs. Deliverables are design requirements, not Tasks; they contain no dependency DAG, canonical Task ID, Run ID, executor ID, status, acceptance decision, or scheduling authority. Phase 31 remains the only Task-DAG planner/materializer.

Implementation must freeze conservative bounds for:

- raw model response bytes;
- total canonical proposal bytes;
- text field length;
- requirement count;
- deliverable count;
- acceptance criteria per item;
- constraints per item;
- required capability count.

Duplicate JSON keys, duplicate local keys, unknown fields, non-finite/ambiguous JSON values, unsupported capabilities, and authority-bearing fields fail closed.

---

## 7. Governed model Run

The design producer may use only:

1. the existing governed scheduled-model path; or
2. an infrastructure-owned deterministic no-I/O fixture for tests/evidence.

Arbitrary unscheduled ModelAdapter injection is forbidden.

One DesignSpecificationInput may produce multiple historical candidate Runs/specifications, but each Run performs at most one model generation. Invalid output fails the Run and publishes no accepted specification.

Run evidence must include at least:

```text
design_input_id/hash
request hash
raw response hash
parsed design_specification_id/hash
model id/hash
response byte count
token counts
model_calls = 1
accepted = false at generation time
```

The Run does not automatically audit or accept its own output.

---

## 8. Independent DesignSpecificationAudit

Phase 56A/B must define immutable independent audit evidence with infrastructure-owned identity, proposed prefix:

```text
DESIGNAUD-*
```

Minimum relation:

```text
DesignSpecificationAudit
- audit_id
- design_input_id/hash
- design_specification_id/hash
- status = PASS | FAIL
- bounded structural metrics
- bounded failure_reason
```

Audit recomputes from durable canonical bytes rather than trusting producer-provided metrics.

A PASS must prove exact input binding and structural validity only. Audit code may not call a model and may not make a HUMAN_OPERATOR acceptance decision.

---

## 9. Immutable HUMAN_OPERATOR acceptance

Phase 56B/C must define one immutable acceptance relation with infrastructure-owned identity, proposed prefix:

```text
DESIGNACC-*
```

Minimum fields:

```text
DesignSpecificationAcceptance
- acceptance_id
- project_id
- goal_id
- design_input_id
- design_input_hash
- design_specification_id
- design_specification_hash
- audit_id
- audit_hash
- acceptance_authority = HUMAN_OPERATOR
- schema_version = 1
- accepted_at
```

Database-level rules:

- one acceptance per DesignSpecification;
- one accepted DesignSpecification per exact DesignSpecificationInput;
- acceptance must reference a structural PASS audit over the exact same input/specification hashes;
- all referenced rows must belong to one project/Goal relation;
- acceptance rows are immutable and undeletable;
- no status field may be toggled later to manufacture acceptance;
- no model/backend/operator caller may supply replacement source hashes during acceptance.

The acceptance record's canonical hash is the downstream evidence hash.

No generic Task PASS is created because the design operation is pre-planning and Task-less.

---

## 10. Currentness and staleness

Currentness is derived every time. It is never a mutable `is_current` flag.

One accepted design specification is current only if all of the following reconstruct exactly:

1. acceptance/spec/audit/input immutable rows parse and hash correctly;
2. project and Goal ownership still match;
3. the current Goal revision and canonical Goal hash equal the DesignSpecificationInput binding;
4. current active Design Rule refs exactly equal the bound rule set, including revisions/hashes;
5. current deterministic Project Intelligence hash equals the bound hash;
6. any bound verified-state refs required by the input remain valid/current under their owning authority;
7. the capability catalog relation remains structurally valid for interpreting the proposal;
8. no conflicting acceptance exists for the exact input relation.

Model-policy/resource-policy drift after acceptance does not rewrite historical truth. It matters when deciding whether a new design Run may execute; the exact policies used by the accepted Run remain historical evidence.

### 10.1 Semantic drift

If Goal, Design Rule, or Project Intelligence state changes after acceptance:

```text
old DESIGNACC remains immutable historical evidence
currentness = stale
new DesignSpecificationInput required
new proposal/audit/human acceptance required
```

No automatic copy-forward, rehash, or silent supersession is permitted.

### 10.2 Competing candidates

Multiple proposal candidates may exist for one input, but only one can acquire the unique accepted relation for that exact input. Losing candidates remain inert historical evidence.

### 10.3 Recovery

If a crash occurs after durable proposal or audit publication, recovery resumes from those exact bytes and never reruns the model merely to reconstruct evidence.

If acceptance publication is uncertain, recovery first reads/revalidates the immutable acceptance relation. It must not create a second acceptance or regenerate the specification.

---

## 11. Phase-31 consumption boundary

Phase 56 must integrate accepted design evidence into Phase 31 without creating a second planner.

The only safe direction is:

```text
current DESIGNACC + current DESIGNSPEC
→ infrastructure resolves exact acceptance/spec bytes
→ new Phase-31 PlanningInput
→ exact accepted-design evidence included in verified_state_refs
→ bounded accepted design projection included in Planner context
→ normal Phase-31 proposal/audit/materialization
```

The caller may provide at most the accepted `DESIGNACC-*` identity. Infrastructure derives the referenced design specification, input, hashes, Goal, and currentness.

The injected Phase-31 evidence ref must bind the canonical acceptance hash. The PlanningInput continues to independently bind current Goal revision/hash, Design Rules, Project Intelligence, capability catalog, and policies under existing Phase-31 law.

The Planner context may expose only the bounded canonical design payload associated with that exact accepted/current relation. It must not fetch arbitrary historical specs or allow caller-supplied replacement text.

A stale design acceptance fails before a Planner model call and before materialization.

Phase 56 does not weaken Phase-31 structural audit, Task ID allocation, dependency validation, materialization transactionality, or readiness laws.

---

## 12. Relationship to generic Artifact and Verification

The accepted DesignSpecification family is intentionally separate from generic Artifact/Verification authority.

### Artifact

An optional later export such as a rendered Markdown/PDF design document may create an Artifact that points to exact accepted design bytes. Such an Artifact is a presentation/implementation evidence binding only.

Deleting, moving, or regenerating an export cannot change which `DESIGNACC-*` was accepted.

### Verification

Phase 56 may record generic Verification evidence for operator/read-side visibility if useful, but canonical acceptance is the immutable DesignSpecificationAcceptance relation. A generic Verification row alone cannot make a proposal accepted/current.

This prevents target-type strings or arbitrary evidence JSON from becoming a hidden semantic-authority bypass.

---

## 13. Read-only inspection and operator surface

Phase 56 implementation should expose read-only inspection for:

```text
input show
specification show
specification audit show
acceptance show
currentness/status
```

The inspection path must use the existing non-creating/non-migrating production read guard where applicable and must independently recompute hashes/currentness.

The mutation surface for semantic acceptance remains explicit and narrow. It must not accept:

- arbitrary specification text on an acceptance command;
- caller-selected source hashes;
- synthetic PASS/audit status;
- force/overwrite/bypass flags;
- model-generated acceptance authority;
- private signing keys;
- merge/deploy/release flags.

Phase 56 adds no browser/UI production authority. A future UI may call the reviewed application boundary but may not recreate these writes client-side.

No fourth installed package script is required. If an operator CLI is needed, it remains module-only unless a later packaging phase explicitly changes that decision.

---

## 14. Schema v21 reservation

If implementation is authorized, Phase 56 should append exactly one migration version after current v20 and may create normalized immutable tables conceptually equivalent to:

```text
design_specification_inputs
design_specifications
design_specification_audits
design_specification_acceptances
```

Each evidence row carries its own object schema version, canonical payload/hash where applicable, creation timestamp, and relational foreign keys.

Required database defenses include:

- project/Goal foreign-key consistency;
- input/spec/audit/acceptance uniqueness;
- exact one-acceptance-per-input/spec constraints;
- immutable UPDATE/DELETE rejection on evidence/acceptance rows;
- bounded/check-constrained authority/schema fields where representable;
- indexes supporting deterministic Goal/input/currentness inspection.

Phase 56 must not renumber or rewrite v1–v20 migrations.

Proposed infrastructure ID families are:

```text
DESIGN_SPECIFICATION_INPUT  = DESIGNIN
DESIGN_SPECIFICATION        = DESIGNSPEC
DESIGN_SPECIFICATION_AUDIT  = DESIGNAUD
DESIGN_SPEC_ACCEPTANCE      = DESIGNACC
```

Exact enum names/prefixes become implementation contract only when the v21 implementation slice is accepted; they must remain infrastructure-owned.

---

## 15. Implementation slices after architecture acceptance

Architecture acceptance authorizes no code by itself. If separately authorized, Phase 56 should proceed in bounded slices.

### 56A — immutable input/spec/audit substrate

- ID families and frozen models;
- schema v21 migration;
- deterministic canonical serialization/hashing;
- exact Goal/semantic-state input builder;
- governed one-shot Task-less design model Run;
- strict proposal parser;
- independent structural audit;
- persistence/readback validation;
- no acceptance yet.

### 56B — currentness / recovery / planning bridge

- exact Goal/Design Rule/Project Intelligence currentness recomputation;
- stale/competing candidate handling;
- no-replay recovery;
- read-only inspection;
- infrastructure-owned accepted-design-to-PlanningInput bridge prepared behind acceptance requirement;
- no human acceptance publication yet unless 56C is present.

### 56C — HUMAN_OPERATOR acceptance

- immutable DESIGNACC publication;
- explicit human-only acceptance application surface;
- exact acceptance revalidation/currentness;
- Phase-31 PlanningInput consumption of exact accepted/current evidence;
- adversarial authority tests;
- no UI, signing, media production, or release authority.

### 56D — documentation / closure

- synchronize Phase-56 implementation contract and canonical roadmap only after code is accepted;
- exact-scope diff proof;
- canonical Python 3.12/3.13 exact-head CI;
- clean review/thread state;
- SHA-guarded merge.

No later slice may be silently pulled into an earlier one to make a test convenient.

---

## 16. Required adversarial verification

Future implementation is not accepted without tests covering at least:

### Input authority

- wrong project;
- wrong Goal;
- stale Goal revision;
- Goal hash drift without trusted caller override;
- missing/changed Design Rule;
- Design Rule revision/hash drift;
- Project Intelligence drift;
- caller-supplied semantic hash substitution;
- capability catalog mismatch;
- policy-binding mismatch before model execution.

### Proposal/model boundary

- unscheduled arbitrary adapter rejected;
- more than one model call rejected;
- oversized response rejected before expensive parsing;
- malformed UTF-8/JSON;
- duplicate JSON keys;
- unknown fields;
- model-supplied canonical IDs;
- status/approval/verification/authority fields;
- duplicate local keys;
- unknown capability IDs;
- count/text/byte overflow;
- model failure leaves no accepted evidence.

### Audit

- forged proposal/input hash;
- audit replay across another input/spec;
- forged PASS metrics;
- audit recomputation disagreement;
- audit cannot call a model or mutate semantic state.

### Acceptance

- non-HUMAN_OPERATOR authority rejected;
- missing/non-PASS audit rejected;
- wrong audit/spec/input relation rejected;
- second acceptance for same input rejected;
- same spec accepted twice rejected;
- caller hash/Goal override rejected;
- acceptance cannot mutate Phase-17 state;
- acceptance cannot create Task PASS, Artifact adoption, provenance, merge, or release authority.

### Currentness/recovery

- accepted spec becomes stale on Goal revision/hash drift;
- stale on active Design Rule set/revision/hash drift;
- stale on Project Intelligence drift;
- historical accepted bytes remain readable;
- repeated recovery never reruns a completed model call;
- ambiguous post-acceptance crash resolves by durable evidence first;
- tampered canonical payload/hash fails closed.

### Phase-31 bridge

- only exact current accepted DESIGNACC may be consumed;
- stale acceptance fails before Planner model call;
- caller cannot replace accepted spec text/hash;
- PlanningInput binds exact acceptance evidence ref;
- Planner context uses exact accepted canonical payload;
- downstream Planner remains proposal-only;
- Task DAG materialization remains Phase-31 infrastructure authority.

---

## 17. Explicit non-goals

Phase 56 does **not** add or authorize:

- direct Phase-17 semantic mutation;
- a second Design Bible;
- automatic human acceptance;
- aesthetic/game-quality oracle;
- general Reviewer/vision/simulation acceptance;
- generic Task-less production execution for arbitrary capabilities;
- 2D source creation;
- Pixelorama source editing/saving;
- texture generation integration;
- animation production;
- 3D semantic-request creation;
- Blender execution changes;
- audio production promotion;
- runtime observation/playtest promotion;
- integrated human refinement/replacement UI;
- provenance signing;
- package-version transition;
- fourth package entrypoint;
- browser/conversation production authority;
- merge/deploy/release/tag authority.

Those remain separately planned v1.0 blockers or later release work.

---

## 18. Phase-56 exit condition

Phase 56 implementation may be considered complete only when one accepted exact repository head proves:

> Origin Forge can freeze one exact current high-level Goal plus its current governed semantic evidence, obtain one bounded proposal-only design specification through the governed model/resource boundary, independently audit the proposal, require explicit HUMAN_OPERATOR semantic acceptance, preserve the accepted specification as immutable derived production evidence with deterministic currentness/recovery, and feed only that exact current accepted evidence into the existing Phase-31 planning boundary without granting the model, Manager, browser, or generic Artifact/Verification records semantic authority.

The intended post-Phase-56 lifecycle becomes:

```text
Phase-17 canonical semantics
+ exact current Goal
        ↓
DESIGNIN
        ↓
governed proposal-only design Run
        ↓
DESIGNSPEC + DESIGNAUD
        ↓
explicit HUMAN_OPERATOR acceptance
        ↓
DESIGNACC
        ↓
current accepted design evidence
        ↓
Phase-31 PlanningInput
        ↓
Phase-31 proposal/audit/materialized Task DAG
        ↓
downstream governed production families
```

Closing Phase 56 does not make v1.0 release-ready. The R1 media/audio/runtime/refinement blockers remain independent and must be audited from the resulting exact mainline before their own architecture/implementation authority is granted.

---

## 19. Architecture-only merge gate

This Phase-56 architecture PR is limited to exactly:

```text
docs/phase-56-governed-design-specification-production-substrate.md
```

It must contain no source, test, migration, config, package, workflow, roadmap, UI, version, tag, or release mutation.

Before merge:

1. branch base must remain the exact accepted R1 mainline or be explicitly revalidated/rebased if main advances;
2. diff must be exactly this one architecture document;
3. normal canonical Python 3.12 and Python 3.13 CI must pass on the exact candidate SHA;
4. review/thread state must be clean;
5. merge must be SHA-guarded;
6. actual resulting `main` must be re-read after merge.

Only after this architecture is accepted may Phase 56A implementation be separately started.