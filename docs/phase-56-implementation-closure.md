# Phase 56 — Governed Design Specification Production Substrate — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-56-governed-design-specification-production-substrate.md`. Phase 56 is the first implementation phase created from the accepted v1.0 R1 gap matrix. It closes the earliest representative-lifecycle blocker by giving Origin Forge a governed pre-planning design-specification evidence family without weakening Phase-17 semantic truth or replacing the existing Phase-31 Planner/Task-DAG authority.

Phase 56 deliberately stops at **one exact current HUMAN_OPERATOR-accepted design specification becoming valid input evidence for the existing Phase-31 PlanningInput boundary**. It does not automatically execute the Planner, materialize Tasks, mutate canonical Project Intelligence or Design Rules, create media sources, invoke Pixelorama/Blender/audio/runtime/playtest production, sign provenance, merge, deploy, publish, or authorize release.

## Final governed design-specification boundary

The accepted sequence is:

```text
exact current high-level Goal revision/hash
+ exact current Phase-17 semantic evidence
+ exact governed Phase-32 capability/policy evidence
→ immutable DESIGNIN
→ one governed Task-less DESIGN_SPECIFIER model Run
→ strict bounded DESIGNSPEC proposal
→ independently recomputed DESIGNAUD structural audit
→ explicit HUMAN_OPERATOR selects one exact PASS-audited DESIGNSPEC
→ immutable DESIGNACC
→ read-only exact currentness/recovery validation
→ exact current DESIGNACC may be bridged into one Phase-31 PlanningInput
→ normal Phase-31 planning remains separately invoked and separately governed
→ STOP
```

The model is proposal-only. A successful design-generation Run does not mean semantic acceptance. Structural audit proves bounded format/binding validity, not design quality. The only Phase-56 semantic acceptance authority is `HUMAN_OPERATOR`.

An accepted design specification is immutable **derived production evidence**, never canonical Phase-17 semantic truth. Goal, Design Rule, Project Intelligence, or governed capability drift makes the old acceptance stale for new planning use; historical DESIGNIN/DESIGNSPEC/DESIGNAUD/DESIGNACC bytes remain immutable.

## 56A — immutable design evidence and governed proposal generation

56A introduced the Phase-56 schema-v21 evidence substrate and infrastructure identity families:

```text
DESIGNIN-*
DESIGNSPEC-*
DESIGNAUD-*
DESIGNACC-*
```

Schema v21 adds immutable normalized tables for design inputs, candidate specifications, audits, and the reserved acceptance relation. Database triggers enforce source-relation consistency, one accepted candidate per exact input/specification relation, `HUMAN_OPERATOR` acceptance authority, and update/delete rejection for immutable evidence.

`DESIGNIN` is derived by infrastructure from one exact current Goal, active Design Rules, deterministic Project Intelligence, bounded verified semantic state, capability catalog/routing policy, and model/resource policy hashes. Callers cannot substitute semantic hashes or arbitrary context.

The proposal producer opens exactly one governed Task-less Run with role `DESIGN_SPECIFIER`. Only the governed scheduled-model path or deterministic no-I/O fixture may be used. The strict parser rejects duplicate JSON keys, unknown/authority-bearing fields, unsupported capabilities, malformed payloads, and bounded-size/count violations. The model cannot allocate canonical authority identities or mark its own output accepted.

`DESIGNAUD` is independently recomputed from durable canonical input/specification evidence. Audit PASS is necessary for acceptance but is not semantic acceptance.

56A intentionally exposed no acceptance publisher, accepted-currentness reader, PlanningInput bridge, UI authority, signing authority, or release authority.

## 56B — accepted-design currentness, recovery, and Phase-31 bridge

56B added strict read-only validation for the schema-v21 DESIGNACC relation before any publisher existed. The reader independently reconstructs and validates the acceptance/input/specification/audit hashes and exact source relation.

Currentness requires the bound Goal revision/hash, active Design Rule set/revisions/hashes, Project Intelligence hash, bounded semantic verification evidence, and governed capability catalog/policy relation to remain exact. Read-only inspection does not recreate missing capability-state files or otherwise repair authority to make historical evidence current.

Recovery is durable-evidence-first and model-free. Existing candidates, PASS audits, and acceptances are inspected from exact persisted bytes; recovery never reruns a completed design model call merely to reconstruct evidence.

56B also added the infrastructure-owned bridge:

```text
current DESIGNACC
→ exact accepted DESIGNIN/DESIGNSPEC/DESIGNAUD relation
→ one exact Phase-31 PlanningInput
```

The bridge takes only an `acceptance_id`. It independently revalidates currentness and cannot accept replacement Goal/specification text/hashes or Planner authority from the caller. It never executes the Planner.

The Phase-31 evidence-size invariant remains protected. A DESIGNIN may contain the full 128-ref bound, so the bridge first validates the complete DESIGNIN semantic evidence and then emits only exact DESIGNACC + CAPCAT + CAPPOL in `PlanningInput.verified_state_refs`. Goal, active Design Rules, Project Intelligence, capability IDs/catalog, and model/resource policy hashes remain independently bound in their existing PlanningInput fields. No evidence bound was widened or weakened.

## 56C — explicit HUMAN_OPERATOR acceptance

56C activated the already-reserved schema-v21 DESIGNACC relation through one narrow application service:

```text
GovernedDesignSpecificationAcceptor.accept(design_specification_id)
```

The public mutation input is exactly one canonical `DESIGNSPEC-*`. Infrastructure derives the specification's DESIGNIN, exact single audit, project/Goal relation, all source hashes, acceptance identity, fixed `HUMAN_OPERATOR` authority, and timestamp.

Before first publication, the acceptor requires:

- exact durable DESIGNSPEC/DesignInput binding;
- exactly one durable structural audit for the candidate;
- exact independently validated `PASS` audit;
- exact current project/Goal ownership;
- exact current Goal revision/hash;
- exact current Design Rules and Project Intelligence relation;
- exact current bounded semantic verification state;
- exact governed capability catalog/routing-policy relation.

Publication is serialized with `BEGIN IMMEDIATE`. Candidate/source validation is connection-local inside the write transaction. Exact retry returns the canonical existing DESIGNACC; a competing candidate that attempts to occupy the already-accepted DESIGNIN relation fails closed. The schema's unique and immutable triggers remain the final database backstop.

Acceptance invokes no model and creates no PlanningInput automatically. It does not run the Planner, materialize a Task DAG, modify Phase-17 semantics, create a generic Verification acceptance substitute, invoke Manager, mutate media, sign provenance, or authorize release.

## Current explicit operator command

56C added one module-only HUMAN_OPERATOR command:

```bash
python -m origin_forge.design_specification_admin_cli \
  --project-root /path/to/project \
  accept-design-specification \
  --design-specification-id DESIGNSPEC-...
```

The parser accepts no Goal ID, DESIGNIN ID/hash, audit ID/hash/status, acceptance ID, acceptance authority, timestamp, specification replacement text, capability override, force/bypass flag, Planner/Task switch, model selector, signing material, merge/deploy/release flag, or background/watch/retry mode.

A successful result reports the canonical DESIGNACC relation and its currentness only. It does **not** imply that a Phase-31 PlanningInput has been created or that planning has run.

No fourth installed package script was added. Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

## Currentness, staleness, and recovery semantics

Phase 56 never mutates an old acceptance into a new current one.

If Goal, Design Rule, Project Intelligence, verified semantic state, or required capability authority drifts:

```text
historical DESIGNACC remains immutable
currentness = stale
new DESIGNIN required
new proposal/audit/HUMAN_OPERATOR acceptance required
```

The read path reports stale/conflicting state without repair. Missing capability authority is not recreated by inspection. A stale acceptance cannot cross the Phase-31 bridge.

Multiple historical proposal candidates may exist for one DESIGNIN, but only one candidate may own the accepted relation. Recovery may inspect competing durable candidates without invoking the model. Once one candidate is accepted, another candidate cannot replace it through retry or caller-selected hashes.

## Phase-17 and Phase-31 authority preserved

Phase 17 remains canonical semantic truth. Phase 56 may derive from Entities, EntityRelations, EntityBindings, Design Rules, and governed verification evidence; it may not create, edit, retire, supersede, or silently reinterpret those objects.

Phase 31 remains the only normal production Planner/Task-DAG materialization authority. Phase 56 does not allocate Task IDs, choose dependencies, mark Tasks READY/RUNNING/SUCCEEDED, invoke Manager dispatch, or bypass Phase-31 proposal/audit/materialization laws.

The dependency direction remains:

```text
Phase-17 semantics + Goal
→ Phase-56 accepted design evidence
→ Phase-31 PlanningInput
→ separately governed Phase-31 Planner/audit/materialization
→ downstream production
```

No reverse mutation from an accepted design specification into Phase-17 semantic truth is permitted.

## Explicit non-authority preserved

Phase 56 adds no:

- automatic semantic acceptance or model-authored HUMAN_OPERATOR decision;
- aesthetic/game-quality oracle;
- direct Project Intelligence, Entity, EntityRelation, EntityBinding, or Design Rule mutation;
- generic Task-less production execution outside the dedicated design-specifier boundary;
- automatic PlanningInput creation during acceptance;
- automatic Planner execution or Task-DAG materialization;
- Task/Flow/Goal transition authority;
- Manager/background queue processing;
- browser/conversation/UI acceptance or planning authority;
- 2D source creation, Pixelorama source creation/import/edit/save, texture generation, animation production, 3D semantic-request creation, Blender execution changes, or audio production promotion;
- runtime observation/playtest production integration;
- integrated human refine/replace UI;
- Artifact adoption/acceptance substitution;
- provenance signing or private-key access;
- package-version transition or fourth installed entrypoint;
- merge, deployment, publish, release, or tag authority;
- mutation of immutable v0.1 or v0.5 release records.

## Accepted adversarial coverage

The merged Phase-56 tests prove, across the slices, fail-closed behavior for the important authority boundaries including:

- wrong/stale Goal and project binding;
- Design Rule/Project Intelligence/semantic evidence drift;
- capability catalog/routing-policy and model/resource-policy mismatch;
- arbitrary unscheduled adapter rejection;
- bounded one-model-call proposal behavior;
- malformed/duplicate/unknown/authority-bearing proposal fields;
- unsupported capabilities;
- exact independent audit recomputation;
- immutable schema evidence;
- canonical acceptance-hash tamper rejection;
- read-only inspection byte stability and zero model replay;
- missing capability authority without filesystem recreation;
- stale acceptance blocking the Phase-31 bridge;
- bridge idempotence and zero Planner execution;
- maximal 128-ref DESIGNIN compatibility;
- competing durable candidate recovery without generation;
- acceptance requiring exactly one PASS audit;
- explicit HUMAN_OPERATOR publication from only `DESIGNSPEC-*`;
- exact acceptance retry idempotence;
- competing candidate acceptance rejection;
- zero automatic PlanningInput/Planner/Task creation during acceptance;
- module-only CLI/parser authority isolation;
- exact current DESIGNACC consumption through the existing Phase-31 PlanningInput bridge.

## Exact-head accepted evidence

- **Phase-56 architecture — PR #183:** exact accepted head `3f943929ecd8eda413a64bb067ea903158380bc8` / canonical run `32672973261`; Python 3.12 job `97276518663` and Python 3.13 job `97276518776` passed; merged as `148e1b8fbbd3442052366c62199de79bdd5e71f8`.
- **56A — immutable input/spec/audit substrate — PR #184:** exact accepted head `41dc73ccfdb5fe79c227ab09cb2c2518e45fae2b` / canonical run `32758404242`; Python 3.12 job `97531279433` and Python 3.13 job `97531279709` passed; merged as `8c0f00680477879ae131f25d0a9fbdf40cbe7b88`.
- **56B — currentness/recovery/PlanningInput bridge — PR #185:** exact accepted head `5cb7fd58796fcd8960ca3d426fa34816d0900535` / canonical run `32773615675`; Python 3.13 job `97579582658` and Python 3.12 job `97579582849` passed; merged as `c907102f31c3d90612eddaf4bda9a58963f960fe`.
- **56C — explicit HUMAN_OPERATOR acceptance — PR #186:** exact accepted head `dca118f4a223b6818ac3069fb4e546dbaa706f49` / canonical run `32775766311`; Python 3.13 job `97586427493` and Python 3.12 job `97586427606` passed; merged as `924232ae8fdcb83b1020b16db9e0fc796b8b4676`.

The final 56C head includes the pre-CI correction that keeps semantic-currentness validation connection-local inside the serialized acceptance transaction. The correction did not widen schema, public acceptance inputs, Planner authority, packaging, UI, signing, or release scope.

## Phase-56 exit condition

The frozen architecture exit condition is now met in implementation:

> Origin Forge can freeze one exact current high-level Goal plus its current governed semantic evidence, obtain one bounded proposal-only design specification through the governed model/resource boundary, independently audit the proposal, require explicit HUMAN_OPERATOR semantic acceptance, preserve the accepted specification as immutable derived production evidence with deterministic currentness/recovery, and feed only that exact current accepted evidence into the existing Phase-31 planning boundary without granting the model, Manager, browser, or generic Artifact/Verification records semantic authority.

Phase 56 does **not** make v1.0 release-ready. The accepted R1 matrix's remaining media/audio/runtime/refinement blockers remain independent and require fresh audit from the resulting exact mainline before later architecture or implementation is authorized.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact accepted Phase-56 implementation `main`:

```text
924232ae8fdcb83b1020b16db9e0fc796b8b4676
```

The intended final net diff is documentation only:

```text
docs/phase-56-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

The frozen planning document `docs/phase-56-governed-design-specification-production-substrate.md` remains unchanged as the historical architecture contract.

The closure may not modify production source, tests, schema, config, packaging, workflows, model/resource policy, Phase-17 semantic authority, Phase-31 Planner/materialization authority, Manager/Goal-bootstrap authority, cockpit/server/browser/conversation/GUI code, media production authority, provenance/signing policy, merge/release authority, or immutable release records.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.