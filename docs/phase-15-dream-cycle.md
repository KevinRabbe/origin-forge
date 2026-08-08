# Phase 15 — Offline Dream Cycle / Memory Consolidation

Status: **implemented; Phase 16 is next**

Phase 15 introduces a separate offline consolidation process that learns from many completed Origin Forge sessions without allowing the active Executor, the Dream process, or a language model to redefine verified project truth.

Implementation note: the v0 architecture described here is now implemented with deterministic and optional model-backed proposal analysis, independent auditing, immutable versioned memory, durable Dream lifecycle/observability, and non-promoting operator `status` / `plan` / deterministic `run` surfaces. Generative Dream execution is intentionally not exposed through the CLI until a trusted runtime model loader is explicitly wired; the bounded model planner already uses the existing `ModelAdapter` contract.

The core distinction is:

```text
production-time cognition != offline consolidation
```

Normal production should optimize for the current bounded Task. Consolidation should inspect many completed Runs later, detect repeated patterns, stale derived knowledge, and candidate improvements, then route those candidates through the appropriate deterministic or human-governed validation path.

The Dream Cycle is therefore not a larger chat memory and not a self-modifying agent.

---

## 1. Architectural goal

Origin Forge already separates ephemeral reasoning from durable verified state:

```text
Goal / Task
   ↓
Manager
   ↓
Fresh Executor
   ↓
Tools / model
   ↓
Auditor
   ↓
Verification
   ↓
Durable state + trajectory
```

Phase 15 adds an offline layer beside that production loop:

```text
Verified Runs / Tasks / Decisions / Changes / Artifacts
+ failures / audits / model selections / context selections
+ governed Skills / Skill evaluations
+ current derived memory generation
             ↓
       Dream Analyzer
             ↓
  cross-run pattern discovery
             ↓
   Consolidation Candidates
             ↓
      Dream Auditor
             ↓
versioned proposal/evidence set
             ↓
appropriate downstream gate
```

The objective is continuous **infrastructure learning**, not autonomous rewriting of truth.

---

## 2. Fundamental rules

1. **Verified state remains authoritative.**
   Dream output is derived evidence and proposals. It cannot override verified Decisions, Artifacts, Verifications, Task outcomes, Design Bible rules, permissions, or company identity.

2. **Dreaming is out-of-band.**
   The active Executor solves its current Task. It is not responsible for simultaneously curating long-term memory.

3. **Cross-run evidence, not one-session intuition.**
   Pattern claims must reference bounded sets of durable Runs/Tasks/Verifications and remain reconstructable.

4. **No direct self-modification.**
   Dreaming may propose a Skill change, routing change, context-policy change, or process change. It cannot promote or apply one itself.

5. **Memory is versioned and reversible.**
   Consolidation creates a new immutable memory generation instead of mutating the previous generation in place.

6. **Historical evidence is append-only.**
   Dreaming may mark derived memory as stale/superseded but cannot erase historical Runs, Decisions, Verifications, or previous memory generations.

7. **Model output is never sufficient evidence.**
   A Dream model may discover a candidate pattern. Acceptance requires deterministic evidence, an independent auditor, an evaluation framework, or human approval according to candidate type.

8. **Bounded offline work.**
   Every Dream Cycle has explicit limits for input Runs, bytes, model calls, tokens, elapsed time, candidates, and repair/retry attempts.

9. **No arbitrary network or host authority.**
   Dreaming uses the same protected-state, tool, sandbox, and model-resource boundaries as production infrastructure.

10. **Neural continual learning is a later layer.**
    Phase 15 performs symbolic consolidation. Fine-tuning/distillation from verified trajectories remains a later research phase.

---

## 3. The memory model

Origin Forge should not depend on one mutable `memory.md` file.

Phase 15 introduces immutable memory generations:

```text
MEMGEN-000001
MEMGEN-000002
MEMGEN-000003
...
```

A generation contains only derived operational knowledge. It never replaces canonical project records.

Example generation manifest:

```json
{
  "id": "MEMGEN-000003",
  "parent_id": "MEMGEN-000002",
  "dream_run_id": "RUN-0002011",
  "input_window": {
    "run_ids": ["RUN-0001800", "RUN-0001942"],
    "from": "2026-08-07T00:00:00Z",
    "to": "2026-08-08T00:00:00Z"
  },
  "accepted_entry_ids": ["MEM-0004812"],
  "superseded_entry_ids": ["MEM-0001892"],
  "deferred_candidate_ids": ["DREAM-000091"],
  "content_hash": "sha256:...",
  "verification_id": "VERIFY-..."
}
```

A memory entry is content-addressed and provenance-backed:

```json
{
  "id": "MEM-0004812",
  "kind": "ARCHITECTURAL_FACT",
  "claim": "All configured language servers execute through the sandboxed Podman backend.",
  "evidence_refs": ["DEC-...", "CHG-...", "VERIFY-..."],
  "valid_from": "2026-08-08T00:00:00Z",
  "supersedes": ["MEM-0003107"],
  "status": "VERIFIED_DERIVED",
  "content_hash": "sha256:..."
}
```

The important distinction is:

```text
canonical record → authority
memory entry     → indexed/derived knowledge about canonical records
```

If memory conflicts with canonical state, canonical state wins and the memory entry becomes a staleness candidate.

---

## 4. Dream Cycle lifecycle

A Dream Cycle is a durable Flow/Run-like operation with an explicit input snapshot.

Proposed lifecycle:

```text
PLANNED
  ↓
SNAPSHOTTED
  ↓
ANALYZING
  ↓
AUDITING
  ↓
PROPOSED
  ↓
CONSOLIDATED
```

Terminal alternatives:

```text
BLOCKED
FAILED
QUARANTINED
CANCELLED
```

Detailed loop:

1. **Select input window**
   - recent completed Runs
   - relevant Task/Flow outcomes
   - verification evidence
   - failure signatures
   - Skills used
   - context modes/paths
   - model/resource selections
   - current memory generation

2. **Freeze an input manifest**
   - stable IDs
   - hashes/revisions
   - bounded transcript/trajectory references
   - exact model/Skill/tool versions used by the Dream Analyzer

3. **Deterministic preprocessing**
   - duplicate references
   - stale entity links
   - repeated failure signatures
   - aggregate success/failure metrics
   - routing/context/Skill usage statistics

4. **Dream Analyzer**
   - receives only the bounded frozen evidence package
   - identifies candidate patterns/corrections
   - cannot write project state

5. **Dream Auditor**
   - independently checks every candidate against canonical evidence
   - removes unsupported claims
   - detects contradictions/staleness
   - classifies the required downstream gate

6. **Candidate persistence**
   - candidates are immutable evidence objects
   - no semantic candidate auto-applies merely because the analyzer produced it

7. **Safe deterministic maintenance**
   - optionally rebuild derived indexes/backlinks/hashes/caches
   - no semantic project truth changes

8. **Memory generation construction**
   - accepted derived-memory updates create a new generation
   - previous generation remains intact

9. **Route improvement candidates**
   - Skill → Phase-12 Skill evaluation / later Skill Workshop
   - routing → benchmark policy
   - context strategy → retrieval benchmark
   - architecture/process → human/engineering review

---

## 5. Candidate types

### 5.1 Memory candidate

Examples:

- newly stable project convention
- repeated factual preference backed by durable Decisions
- stale/superseded derived fact
- duplicate derived knowledge
- frequently needed entity relationship

```text
DREAM_MEMORY_PROPOSAL
```

A memory candidate must include:

- claim
- candidate action: ADD / SUPERSEDE / MERGE / RETIRE
- source evidence refs
- contradiction refs, if any
- confidence/evidence class
- target memory generation

Semantic memory changes require Dream Auditor approval before becoming part of a new memory generation.

### 5.2 Skill candidate

Repeated successful procedure:

```text
observed pattern
→ DREAM_SKILL_PROPOSAL
→ candidate Skill snapshot
→ paired Skill benchmark
→ regression checks
→ later promotion gate
```

Dreaming cannot modify the live Skill package.

### 5.3 Model-routing candidate

Example:

```text
Task class: simple config edits
coder_fast success: 94%
coder_strong success: 96%
resource cost: 3.8×

proposal:
prefer coder_fast for this bounded task class
```

This produces a policy proposal only. Phase-14 model scheduling policy remains operator/governance-owned.

### 5.4 Context-strategy candidate

Example:

```text
Task class: state-machine debugging
lexical only         62%
+ structural         81%
+ semantic           91%
```

Candidate actions may propose changing retrieval defaults for a measured task class, but must pass a replay/benchmark suite before promotion.

### 5.5 Process / architecture candidate

Example:

```text
Repeated finding:
Executor edits implementation before inspecting existing tests.

candidate:
Debugging Skill should require failing-test inspection before implementation changes.
```

These remain proposals for engineering or Skill-evaluation review.

### 5.6 Data-quality candidate

Examples:

- stale derived index
- broken backlink
- duplicated identical reference
- missing hash cache
- orphaned non-authoritative cache record

Only strictly deterministic/derived repairs may be auto-applied, and they must be reconstructable from canonical state.

---

## 6. Evidence hierarchy

Dreaming uses the same Origin Forge truth hierarchy:

```text
runtime / tests / compiler / deterministic verification
    > canonical project state + signed/hashed artifacts
    > accepted Decisions / Design Bible / operator policy
    > trusted external references
    > model-generated interpretation
```

A candidate must cite the highest available evidence.

A quote/snippet from a trajectory may explain a candidate, but it is not sufficient to override later verified state.

---

## 7. Staleness and contradiction handling

Every derived memory entry should be periodically checked against canonical references.

Example:

```text
MEM-001892:
"Project config schema is version 3"

canonical evidence:
CHG-0182 + VERIFY-9182 establishes config version 4
```

Dream output:

```text
candidate: SUPERSEDE MEM-001892
replacement claim: "Project config schema is version 4"
evidence: CHG-0182, VERIFY-9182
```

The old memory entry is not deleted. The new memory generation records the supersession edge.

Contradictions that cannot be resolved from authority order become `DEFERRED` rather than guessed.

---

## 8. Safe auto-application boundary

Phase 15 may eventually auto-apply only deterministic derived maintenance such as:

- rebuild an index from canonical records
- rebuild backlinks
- recompute a cache
- deduplicate byte-identical derived references
- recompute content hashes
- remove expired cache entries

It may **not** automatically:

- change source code
- change a Decision
- change Design Bible content
- alter Task/Flow/Goal outcomes
- mark a Task verified
- edit active Skills
- promote a Skill candidate
- change model-routing policy
- change context policy
- add/remove permissions
- alter authority rules
- alter company identity/keys
- merge branches
- install tools/plugins/models
- train/fine-tune a production model

---

## 9. Separation of roles

Use three distinct roles rather than one self-editing agent:

### Dream Selector

Deterministic software selecting bounded canonical evidence.

### Dream Analyzer

May use a local model to discover cross-run patterns and formulate structured candidates.

Permissions:

- read frozen Dream input package
- read selected derived memory
- emit candidate objects

No project writes.

### Dream Auditor

Fresh independent context.

Checks:

- evidence references exist
- evidence still matches hash/revision
- claim follows from evidence
- contradiction/staleness handling
- candidate type and required gate
- no forbidden authority change

No repair of production files and no candidate promotion.

---

## 10. Input selection and boundedness

Initial defaults should remain conservative.

Example limits:

- maximum 100 completed Runs per cycle
- maximum 24-hour or explicitly selected time window
- maximum trajectory bytes per Run
- maximum total evidence bytes
- maximum candidate count
- maximum model calls
- maximum analysis tokens
- maximum wall-clock duration
- zero automatic retry on identical failure signature

The first implementation should favor deterministic aggregates over feeding full raw trajectories to a model.

Operational context should use:

```text
verified facts + compact metrics + selected evidence
```

rather than replaying every token from every Executor session.

Full raw trajectories may remain archived for audit/training research but should not become the default Dream input.

---

## 11. Scheduling

The Dream Cycle is a durable **capability**, not inherently a 3 AM cron job.

Possible triggers:

- operator command
- idle-window policy
- after N newly verified Runs
- daily local schedule
- before a major planning/release checkpoint

Scheduling belongs outside the Dream Analyzer.

Phase 14 resource scheduling should control Dream model admission. Production work can have higher priority than consolidation.

A Dream Cycle blocked by unavailable GPU resources should remain `WAITING/BLOCKED`, not steal capacity from a higher-priority production Task.

---

## 12. Observability

Every Dream Cycle should produce a first-class trajectory containing:

- Dream cycle ID / Run ID
- parent memory generation
- input Run/Task/Decision/Verification IDs
- input hashes/revisions
- selected time window
- deterministic aggregate metrics
- analyzer model/profile/hash
- Skill/tool versions
- input/output tokens
- CPU/RAM/VRAM usage
- elapsed time
- proposed candidate count/type
- audited accepted/rejected/deferred counts
- resulting memory generation ID/hash
- downstream benchmark IDs

This makes self-improvement itself measurable.

---

## 13. Relationship to existing Origin Forge layers

### Phase 1 durable state

Provides canonical records and recovery-safe truth.

### Phases 6–8/10–11 execution and context

Provide the trajectories and context-selection outcomes Dreaming can compare.

### Phase 9 Skills

Provide procedural knowledge snapshots that may become candidate improvement targets.

### Phase 12 Skill Evaluation

Becomes the mandatory evidence gate for Dream-generated Skill candidates.

### Phase 13 Tool Search

Provides tool-discovery metrics and potential tool-routing patterns.

### Phase 14 Resource Scheduler

Controls offline model admission and prevents Dream work from hiding GPU contention.

### Later Skill Workshop

Owns actual candidate Skill promotion. Dreaming only proposes.

### Later training/fine-tuning research

May consume verified Dream/Run datasets, but training remains separate from symbolic memory consolidation.

---

## 14. Neural Dreaming is explicitly deferred

Karpathy's deeper continual-learning analogy involves distilling accumulated experience back into model parameters.

Origin Forge should not start there.

The progression should be:

```text
verified trajectories
→ symbolic Dream Cycle
→ better memory / Skills / routing / retrieval
→ benchmark infrastructure improvements
→ mature verified dataset
→ offline training candidate
→ benchmark candidate model
→ promote only with evidence
```

No production model may rewrite its own weights or replace itself through Phase 15.

---

## 15. Implemented v0 scope

Phase 15 v0 implements:

1. `DreamInputManifest`
   - bounded canonical IDs/hashes/revisions
   - parent memory generation

2. `MemoryEntry`
   - immutable content-addressed derived knowledge
   - evidence refs
   - supersession edges

3. `MemoryGeneration`
   - immutable parent-linked generation manifest

4. `DreamCandidate`
   - MEMORY / SKILL / ROUTING / CONTEXT / PROCESS / DATA_QUALITY
   - structured evidence refs
   - required downstream gate

5. deterministic stale/duplicate detector

6. model-optional `DreamAnalyzer` interface

7. independent `DreamAuditor`

8. proposal-only persistence

9. generation construction from audited memory changes

10. operator CLI:

```text
origin-forge dream status
origin-forge dream plan
origin-forge dream run
origin-forge dream candidates
origin-forge dream show <candidate-id>
origin-forge memory generations
origin-forge memory show <generation-id>
```

No `dream promote`, `dream apply-skill`, `dream change-policy`, or self-modification command exists in the initial phase.

---

## 16. Acceptance tests

Phase 15 is complete only when all of the following are demonstrably true.

### Isolation

- a Dream Analyzer cannot modify project source files
- a Dream Analyzer cannot modify canonical Decisions/Tasks/Verifications
- a Dream Auditor cannot promote a candidate

### Versioned memory

- Dreaming creates a new memory generation rather than modifying the parent
- old generations remain readable and hash-verifiable
- rollback means selecting an earlier generation, not reconstructing overwritten text

### Staleness

- a derived memory claim contradicted by later verified state is detected
- replacement includes exact evidence refs
- unresolved contradiction is deferred rather than guessed

### Cross-run pattern

- at least one repeated pattern can be detected from multiple completed Runs
- the candidate records all supporting Run/Verification refs
- removing the supporting evidence changes/rejects the candidate deterministically

### Skill boundary

- a Dream-generated Skill candidate cannot change the live Skill registry
- it can be exported to the existing Skill-evaluation path
- a regressed benchmark prevents promotion

### Routing/context boundary

- a routing/context candidate cannot change live policy
- candidate evidence includes measured success/cost/context metrics

### Determinism and bounds

- input selection is reconstructable
- duplicate/stale deterministic preprocessing is repeatable
- input/candidate/model-call/resource budgets fail closed

### Provenance

- every accepted derived memory entry traces to canonical evidence
- every generation has a parent, input manifest, content hash and Dream/Audit records

---

## 17. Exit condition

Phase 15 exits when:

> Origin Forge can inspect a bounded set of completed verified work, discover cross-session patterns and stale derived knowledge, independently audit those findings, create an immutable new memory generation, and emit improvement candidates into existing evaluation/governance gates — without allowing the Dream process to change canonical truth, active Skills, routing policy, permissions, or production code.

The result should be the first complete Origin Forge self-improvement loop:

```text
production work
   ↓
verified trajectories
   ↓
offline consolidation
   ↓
audited candidates
   ↓
benchmark / approval
   ↓
measured infrastructure improvement
   ↓
better future production work
```
