# Origin Forge Roadmap

Status: **Implementation baseline aligned with repository history**

This roadmap uses the phase numbers that actually exist in the repository. Earlier planning documents described several capabilities under different phase numbers; this file is the canonical execution order.

The ordering rule is unchanged: prove durable, reversible, independently verified infrastructure before expanding autonomy or media production.

## Phase 0 — Specification and Foundations — DONE

Defined:

- architectural laws
- core object model
- ID strategy
- state-transition semantics
- authority/security model
- company-root provenance design
- project layout
- tool/model contracts
- execution lifecycle

Exit condition met: the durable runtime could be implemented without inventing its fundamental semantics during coding.

## Phase 1 — Durable Runtime — DONE

Implemented:

- SQLite durable state
- Goal / Flow / Task / Run lifecycle
- Decision / Change / Artifact / Verification lineage
- schema migrations
- optimistic revisions
- event journal
- restart recovery
- verification-gated completion

Exit condition met: work survives process restart without conversational memory.

## Phase 2 — Bounded Local Worker — DONE

Implemented:

- replaceable local model adapter
- llama.cpp-compatible local HTTP adapter
- bounded read-only repository context
- protected project state
- content hashes
- structured PatchProposal output
- proposal-only worker
- model response/context/proposal provenance

Exit condition met: a local model can produce a bounded, hash-preconditioned patch proposal without receiving write authority.

## Phase 3 — Isolated Apply and Audit — DONE

Implemented:

- durable Git worktrees
- deterministic patch application
- rollback/cleanup
- persisted Git diff evidence
- independent content audit
- proposal artifact integrity checks
- workspace recovery

Exit condition met: model-generated mutations occur only inside disposable isolated workspaces and are independently audited.

## Phase 4 — Sandboxed Verification Contract — DONE

Implemented:

- `CREATED → APPLIED → AUDITED → VERIFIED` semantics
- structured approved command specs
- backend-neutral sandbox contract
- explicit isolation guarantees
- required build/test verification
- blocked-vs-failed infrastructure semantics

Exit condition met: AI-modified code cannot become VERIFIED without acceptable isolated execution evidence.

## Phase 5 — Podman Sandbox Backend — DONE

Implemented:

- Podman backend behind the sandbox contract
- local content-addressed image resolution
- no automatic image pulls
- disposable workspace copies
- network-off default
- capability dropping / no-new-privileges
- memory/CPU/PID bounds
- bounded stdout/stderr
- timeout/container cleanup

Exit condition met: required approved commands can execute in a real constrained sandbox without mounting the authoritative worktree writable.

## Phase 6 — Snapshot-First Bounded Orchestration — DONE

Implemented the first complete single-attempt production loop:

```text
READY Task
→ isolated Git snapshot
→ bounded Executor
→ Patch Proposal
→ deterministic apply
→ independent audit
→ sandbox verification
→ Task PASS
```

The Workspace is created before repository context is read, so the model and applier operate on the same immutable base snapshot.

Exit condition met: one bounded coding attempt can complete end-to-end without touching the user's main working tree.

## Phase 7 — Bounded Retry, Resume, Loop Detection and Model Escalation — DONE

Implemented:

- durable retry accounting
- independent verification-failure budgets
- deterministic model escalation
- exact repeated-proposal loop detection
- resume from CREATED / APPLIED / AUDITED / VERIFIED checkpoints
- quarantine semantics
- infrastructure-failure boundedness

Exit condition met: recovery and retries are explicit bounded policy rather than an endless agent loop.

## Phase 8 — Deterministic Context Discovery — DONE

Implemented:

- tracked-file discovery inside the isolated Workspace
- UTF-8/text and symlink safety
- hard scan/selection budgets
- deterministic Task-term ranking
- explicit seed files
- manual vs automatic context modes
- no arbitrary fallback context
- dirty-live-checkout isolation

Exit condition met: a bounded Executor can receive automatically selected task-relevant context without model-controlled filesystem search.

## Phase 9 — Governed Skills — DONE

Implemented instruction-only project Skills:

```text
.origin-forge/skills/<name>/
├── SKILL.md
└── skill.toml
```

Implemented:

- deterministic selection from durable Task evidence
- progressive disclosure
- semantic versions
- SHA-256 fingerprints
- Run/Artifact provenance
- hard catalog/instruction/read budgets
- fail-closed package containment and symlink rejection
- single-snapshot Skill loading per selection pass
- no executable Skill content
- no new authority granted by a Skill

Exit condition met: the Executor sees full procedural instructions only for relevant Skills, while the exact Skill versions/fingerprints used by a Run remain reconstructable.

## Phase 10 — Structural Context Graph — DONE

Implemented deterministic structural context on top of Phase-8 lexical discovery:

- bounded Python AST index
- definitions
- direct imports
- reverse importers
- source ↔ test relationships
- Task-symbol evidence
- one-hop bounded expansion
- shared `WorkspaceContextSelector`
- retry-time reselection inside every fresh Workspace

The selector composes:

```text
manual OR lexical auto-context
        ↓
optional structural expansion
        ↓
final bounded context
```

Exit condition met: one-shot and retry orchestration use one deterministic Workspace-local context-selection boundary, and structural relationships improve context without recursive repository dumping.

## Phase 11 — LSP and General Code Intelligence — REVALIDATING

Implementation exists in PR #16 and is being revalidated against the current mainline after Phases 12 and 13 landed first.

Implemented on the Phase-11 branch:

- provider-neutral code-intelligence interface
- deterministic Python AST provider
- semantic context expansion through the shared selector
- bounded LSP JSON-RPC client/session
- UTF-8/16/32 position conversion
- Workspace URI containment using the shared portable path policy
- normalized definitions/references/workspace symbols/diagnostics
- diagnostics as supplementary evidence, not a correctness oracle
- config-v4 trusted LSP server registry
- sandboxed Podman language-server hosting
- worktree-only LSP source policy
- operator-only configured server status surface

The model receives normalized query results, not unrestricted control of a language server.

Merge condition:

> The complete Python 3.12 + 3.13 matrix must pass on the exact current-main PR merge ref before Phase 11 is merged.

## Phase 12 — Governed Skill Evaluation and Benchmarks — DONE

Implemented measurable Skill quality control:

- immutable eval cases
- exact fixture/scorer/environment fingerprints
- paired with-vs-without Skill trials
- identical paired seeds and alternating execution order
- regression-dominant verdicts
- success-rate / score / duration / model-call / token metrics
- bounded experiment design
- exact Skill snapshot refs
- immutable content-addressed reports
- replayability checks against current Skills/cases
- evidence-only operator CLI

Exit condition met: a Skill version can be accepted or rejected using repeatable task outcomes rather than intuition, without granting the benchmark system Skill-promotion authority.

## Phase 13 — Tool Registry and Tool Search — DONE

Implemented deterministic capability inventory and progressive disclosure:

- immutable governed `ToolDescriptor` catalog
- bounded input/output schemas and metadata
- permissions/side effects/determinism/reversibility/resource/timeout/verifier metadata
- content-addressed catalog snapshots
- authority filtering before discovery
- constant `search_tools` / `describe_tool` model-facing gateway
- deterministic bounded lexical/capability ranking
- hydration and cumulative response budgets
- hidden/unknown tool denial equivalence
- disclosure-footprint metrics

Phase 13 deliberately does **not** add generic `call_tool` authority.

Exit condition met: a model can discover and hydrate relevant authorized tool contracts from a growing registry without loading every schema into context or gaining new authority through search.

## Phase 14 — Model and Resource Scheduler — IN REVIEW

PR #21 currently implements the config-independent scheduler substrate while Phase 11's config-v4 merge gate is completed.

Implemented on the Phase-14 branch:

- atomic process-local CPU/RAM/GPU leases
- VRAM headroom and GPU compute-slot accounting
- exclusive GPU leases
- deterministic multi-GPU best-fit placement
- static incompatibility vs temporary contention distinction
- read-only resource admission inspection
- empirical/governed model resource profiles
- semantic model roles
- explicit primary + fallback policy chains
- no implicit model downgrade
- model load/use/unload lifecycle
- trusted runtime-loader dispatch
- `ModelAdapter` / existing Worker integration
- Run-level model/resource selection provenance
- read-only model-policy inspection
- bounded standalone resource/model config parser
- safe-disabled scheduler construction factory

Remaining before merge:

- inherit Phase-11 config v4 and wire the standalone parser as backward-compatible config v5
- add safe configured operator inventory/resource status
- exact-head Python 3.12 + 3.13 hosted matrix

Exit condition:

> Origin Forge can choose between explicitly governed local model profiles and safely schedule incompatible CPU/GPU workloads without losing durable Task state or creating a hidden retry queue.

## Phase 15 — Offline Dream Cycle / Memory Consolidation — PLANNED

Separate production-time cognition from offline cross-session learning.

Add:

- bounded frozen Dream input manifests over verified Runs/Tasks/Decisions/Verifications
- immutable content-addressed derived `MemoryEntry` objects
- parent-linked immutable `MemoryGeneration` snapshots
- deterministic duplicate/staleness/contradiction preprocessing
- model-optional cross-run Dream Analyzer
- independent Dream Auditor
- proposal-only Dream candidates
- candidate classes for memory, Skills, routing, context strategy, process/architecture, and data quality
- safe deterministic derived-index maintenance only
- routing of Skill candidates into Phase-12 evaluation / later Skill Workshop
- routing/context candidates into benchmark gates
- explicit model/resource budgets through Phase 14
- first-class Dream observability/provenance

Core rule:

```text
Dreaming may discover candidate knowledge.
It may not redefine canonical truth.
```

Dreaming cannot modify source code, canonical Decisions, Design Bible content, Task/Verification outcomes, active Skills, routing policy, permissions, company identity, or merge state.

See `docs/phase-15-dream-cycle.md` for the full architecture and acceptance tests.

Exit condition:

> Origin Forge can inspect bounded completed verified work, discover cross-session patterns and stale derived knowledge, independently audit those findings, create an immutable new memory generation, and emit improvement candidates into existing evaluation/governance gates without granting the Dream process self-modification authority.

## Phase 16 — Isolated Specialist Roles

Introduce only roles that measurably improve outcomes:

- Reviewer
- Researcher
- Tester
- Visual Critic

Each role gets an isolated context and restricted capabilities.

Exit condition:

> Specialist isolation improves selected benchmarks without creating an uncontrolled agent swarm.

## Phase 17 — Project Intelligence

Add semantic product state:

- Entity graph
- Design Bible
- dependency edges
- implementation/artifact/test relationships
- impact analysis
- structured project rules

Exit condition:

> Origin Forge can reason about a feature/entity across multiple files and media and identify affected dependencies before modification.

## Phase 18 — Cryptographic Provenance

Build on the existing Artifact hashes and causal lineage:

- signed manifests
- operational signing keys
- company-root identity hierarchy
- model/Skill/Tool lineage
- key rotation/revocation
- release/build provenance

Exit condition:

> Every accepted Artifact can be cryptographically traced to its Task, Run, parent state, model, Skills, tools and Verification evidence.

## Phase 19 — Pixelorama Integration

Add deterministic 2D production:

- sprites
- layers
- palettes
- frames
- animations
- tilesets
- export
- validators

Exit condition:

> A bounded Task can create or modify a 2D game asset, validate it, and register it as a provenance-tracked Artifact.

## Phase 20 — Blockbench Integration

Add structured 3D production:

- geometry
- hierarchy/bones
- pivots
- UV
- textures
- animation
- export
- previews

Exit condition:

> A bounded Task can create/modify and validate a structured 3D asset through deterministic Blockbench-facing operations.

## Phase 21 — Image and Vision

Add replaceable local adapters for:

- image generation/editing
- concept/reference generation
- textures/UI exploration
- screenshot/asset inspection
- visual critic

Exit condition:

> Generation and independent visual inspection participate in a closed production/verification loop.

## Phase 22 — Audio

Add:

- rFXGen SFX
- FFmpeg processing
- local music adapter
- local TTS adapter
- audio validation

Exit condition:

> Origin Forge can create, process, validate and provenance-track a game audio Artifact from a structured Task.

## Phase 23 — Runtime Observation

Add:

- game/application launch automation
- screenshots/video capture
- log ingestion
- crash detection
- performance metrics
- visual regression evidence

Exit condition:

> The Auditor can inspect actual runtime behavior rather than relying only on source-level evidence.

## Phase 24 — Automated Playtesting

Add synthetic players/bots and telemetry for suitable games.

Potential metrics:

- deaths
- encounter duration
- damage taken
- resource shortages
- soft locks
- pathfinding failures
- progression stalls

Exit condition:

> Gameplay changes can be evaluated using repeatable runtime evidence.

## Phase 25 — Simulation Layer

Add cheap pre-implementation simulation for systems such as:

- economy
- loot
- crafting
- progression
- spawning
- combat balance
- skill trees
- resource distribution

Exit condition:

> At least one game-system design can be statistically evaluated before full implementation.

## Phase 26 — Skill Workshop

Add governed operational learning:

```text
observed reusable pattern
→ Skill proposal
→ isolated evaluation
→ regression suite
→ approval
→ new signed Skill version
```

Dream Cycle candidates may enter this pipeline, but active agents and Dream processes may never silently replace governing Skills.

Exit condition:

> Origin Forge can improve procedural knowledge while preserving review, provenance and rollback.

## Phase 27 — Code Mode Experiments

Benchmark sandboxed model-written mini-workflows that combine multiple tool operations without returning to the model between every operation.

This remains model-dependent and optional.

Exit condition:

> Enable only for model/task profiles where measured reliability or cost is better than ordinary structured tool calls.

## Phase 28 — Cross-Media Watermarking

Develop watermark/fingerprint adapters for:

- source code
- images/pixel art
- audio
- 3D assets

Watermarks complement cryptographic manifests; they never become the sole proof of origin.

Exit condition:

> At least one robust media watermark can be resolved back to the permanent company provenance identity.

## Phase 29 — Training / Fine-Tuning Research

Only after a substantial verified trajectory dataset exists, investigate:

- routing models
- specialized tool-use models
- coding-agent fine-tuning
- infrastructure-native agent models
- offline distillation from verified trajectories and audited Dream outcomes

Training remains separate from symbolic Dream consolidation. No production model rewrites its own weights.

Exit condition:

> Training is justified by measured evidence that software-level improvements alone have reached a meaningful limit.

## Phase 30 — Full Production Interface

Build the polished visual environment around proven infrastructure.

Potential surfaces:

- project/entity browser
- Goal/Flow/Task graph
- Design Bible
- Artifact previews
- verification evidence
- provenance inspector
- model/resource monitor
- Dream/memory-generation inspector
- `why does this exist?` history

The UI stays late so early architecture is not distorted around a premature frontend.

---

# v0.1 — First Useful Release

Target lifecycle:

```text
Human request
    ↓
Goal / Flow / Task
    ↓
Workspace snapshot
    ↓
Context selection
    ↓
Governed Skills
    ↓
Fresh Executor
    ↓
Patch Proposal
    ↓
Deterministic Apply
    ↓
Independent Audit
    ↓
Sandbox Build / Tests
    ↓
FAIL → bounded repair / escalation
PASS
    ↓
Verified durable state + provenance
    ↓
Human review / eventual merge
```

Success criteria:

- no dependency on long chat history
- process restart does not lose work state
- known-good project state remains isolated
- model cannot self-verify completion
- retries and no-progress loops are bounded
- selected context is reconstructable
- final diff is understandable
- meaningful changes have causal/provenance records

# v0.5 — Integrated Development Infrastructure

Target capabilities:

- durable long-running work
- local coding models
- governed Skills + Skill evaluation
- structural/LSP code intelligence
- tool discovery
- model/resource scheduling
- offline memory consolidation and audited improvement proposals
- specialist review
- project graph + Design Bible
- cryptographic provenance
- basic 2D production

# v1.0 — Integrated Game Production

Representative Goal:

> Create a slow heavily armored enemy that lives in abandoned factories and attacks with a large mechanical hammer.

Origin Forge should eventually coordinate:

- design specification
- gameplay implementation
- behavior
- tests
- 2D/3D assets
- textures
- animation
- sound
- loot/configuration
- integration
- runtime verification
- provenance

while allowing the human creator to inspect, reject, refine, or replace any part.

# Explicit early non-goals

Do not prioritize early:

- polished GUI
- Kubernetes
- microservice decomposition
- giant agent swarms
- giant vector database
- custom foundation-model training
- arbitrary internet plugin marketplace
- fully autonomous one-prompt game creation

Build the smallest reliable production loop first.
