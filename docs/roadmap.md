# Origin Forge Roadmap

Status: **Canonical execution order aligned with merged repository state**

Origin Forge is built in dependency order: durable verified state first, then bounded autonomous execution, then intelligence/discovery, then learning and multi-media production. Models may reason, propose, create, and repair; Origin Forge owns identity, authority, state, history, and truth.

---

## Phase 0 — Specification and Foundations — DONE

Defined the architectural laws, object model, ID strategy, state transitions, authority/security model, company-root provenance concept, repository layout, tool/model contracts, and execution lifecycle.

**Exit condition met:** later runtime code could be implemented without inventing fundamental semantics during execution.

## Phase 1 — Durable Runtime — DONE

Implemented SQLite-backed Goal / Flow / Task / Run state, Decision / Change / Artifact / Verification lineage, schema migrations, optimistic revisions, event journal, restart recovery, and verification-gated completion.

**Exit condition met:** work survives process restart without depending on conversation history.

## Phase 2 — Bounded Local Worker — DONE

Implemented replaceable local model adapters, llama.cpp-compatible local HTTP execution, bounded repository reads, protected project state, content hashes, structured PatchProposal output, proposal-only Worker behavior, and model/context/proposal provenance.

**Exit condition met:** a local model can produce a bounded hash-preconditioned patch proposal without write authority.

## Phase 3 — Isolated Apply and Audit — DONE

Implemented durable Git Workspaces, deterministic patch application, rollback/cleanup, persisted diff evidence, independent content audit, proposal-artifact integrity checks, and Workspace recovery.

**Exit condition met:** model-generated mutations occur only inside disposable isolated Workspaces and are independently audited.

## Phase 4 — Sandboxed Verification Contract — DONE

Implemented `CREATED → APPLIED → AUDITED → VERIFIED`, approved structured commands, backend-neutral sandbox contracts, isolation guarantees, required build/test verification, and blocked-vs-failed infrastructure semantics.

**Exit condition met:** modified code cannot become VERIFIED without acceptable isolated execution evidence.

## Phase 5 — Podman Sandbox Backend — DONE

Implemented local-image-only Podman verification with `--pull=never`, disposable source copies, network-off default, dropped capabilities, no-new-privileges, CPU/RAM/PID bounds, bounded output, timeouts, and cleanup.

**Exit condition met:** approved verification commands execute in a real constrained sandbox without writable access to authoritative project state.

## Phase 6 — Snapshot-First Bounded Orchestration — DONE

Implemented the first complete single-attempt production loop:

```text
READY Task
→ isolated Git Workspace
→ bounded Executor
→ Patch Proposal
→ deterministic apply
→ independent audit
→ sandbox verification
→ Task PASS
```

The Workspace is created before context selection, so the model and applier operate on the same base snapshot.

## Phase 7 — Bounded Retry, Resume, Loop Detection and Model Escalation — DONE

Implemented durable retry accounting, verification-failure budgets, deterministic model escalation, repeated-proposal loop detection, checkpoint resume, quarantine, and bounded infrastructure-failure handling.

**Exit condition met:** retries and recovery are explicit policy rather than an endless agent loop.

## Phase 8 — Deterministic Context Discovery — DONE

Implemented tracked-file discovery inside the Workspace, UTF-8/text/symlink safety, scan/selection budgets, deterministic Task-term ranking, explicit seed files, manual/automatic modes, no arbitrary fallback context, and dirty-live-checkout isolation.

**Exit condition met:** a bounded Executor receives reconstructable task-relevant context without model-controlled filesystem search.

## Phase 9 — Governed Skills — DONE

Implemented instruction-only project Skills with deterministic selection, progressive disclosure, semantic versions, SHA-256 fingerprints, Run/Artifact provenance, hard catalog/read/instruction budgets, fail-closed containment, symlink rejection, and no executable Skill authority.

```text
.origin-forge/skills/<name>/
├── SKILL.md
└── skill.toml
```

**Exit condition met:** relevant procedural knowledge can be disclosed without allowing a Skill to grant new authority.

## Phase 10 — Structural Context Graph — DONE

Implemented bounded Python AST indexing, definitions, imports/reverse-importers, source↔test relationships, Task-symbol evidence, one-hop expansion, shared `WorkspaceContextSelector`, and fresh retry-time reselection.

```text
manual OR lexical auto-context
        ↓
optional structural expansion
        ↓
final bounded context
```

**Exit condition met:** structural relationships improve deterministic Workspace-local context without recursive repository dumping.

## Phase 11 — LSP and General Code Intelligence — DONE

Implemented provider-neutral read-only code intelligence, deterministic Python AST intelligence, semantic context expansion, bounded LSP JSON-RPC, UTF-8/16/32 position conversion, Workspace URI containment, normalized definitions/references/symbols/diagnostics, config-v4 trusted LSP registry, and sandboxed Podman language servers.

Important authority rules:

- the model receives normalized evidence, not unrestricted LSP control
- no native-host LSP backend
- only configured server IDs may be used
- LSP execution accepts only canonical isolated `.origin-forge/workspaces/<WSPACE-ID>` roots
- diagnostics are supplementary evidence, not a correctness oracle

**Exit condition met:** code intelligence extends context and audit evidence without gaining mutation or completion authority.

## Phase 12 — Governed Skill Evaluation and Benchmarks — DONE

Implemented immutable eval cases, fixture/scorer/environment fingerprints, paired with-vs-without Skill trials, stable paired seeds, alternating execution order, regression-dominant verdicts, success/score/duration/model-call/token metrics, exact Skill refs, content-addressed reports, replayability checks, and evidence-only CLI surfaces.

**Exit condition met:** Skill versions can be judged using repeatable outcomes rather than intuition, without automatic promotion authority.

## Phase 13 — Tool Registry and Tool Search — DONE

Implemented governed `ToolDescriptor` catalogs, bounded schemas/metadata, permissions/effects/determinism/reversibility/resource/timeout/verifier metadata, content-addressed catalog snapshots, authority filtering, bounded `search_tools` / `describe_tool`, hydration/response budgets, hidden/unknown denial equivalence, and disclosure-footprint metrics.

Phase 13 deliberately does **not** add generic model-facing `call_tool` authority.

**Exit condition met:** models can progressively discover authorized tool contracts without loading the entire catalog or gaining authority through discovery.

## Phase 14 — Model and Resource Scheduler — DONE

Implemented:

- atomic process-local CPU/RAM/GPU leases
- VRAM headroom and GPU compute-slot accounting
- exclusive GPU leases and explicit device pinning
- deterministic multi-GPU best-fit placement
- static incompatibility vs temporary contention
- read-only resource admission inspection
- governed model profiles and semantic roles
- explicit primary + fallback policy chains
- no implicit model downgrade
- model load/use/unload lifecycle
- trusted runtime-loader registry/dispatch
- unchanged `ModelAdapter` / Worker integration
- Run-level model/resource evidence
- read-only model/policy inspection
- config v5 protected `[resources]` / `[models]` sections
- v1–v4 config compatibility
- safe-disabled v5 defaults
- read-only `model_resource_cli status`

Hardware leases are ephemeral; durable Task/Run state remains authoritative across restart. Resource contention creates no hidden retry queue. A fallback model is considered only when explicitly authorized by policy.

**Exit condition met:** Origin Forge can choose between governed local model profiles and safely schedule incompatible CPU/GPU workloads without losing durable Task state or silently changing model quality.

---

## Phase 15 — Offline Dream Cycle / Memory Consolidation — NEXT

Separate production-time cognition from offline cross-session learning.

Planned components:

- bounded frozen Dream input manifests over verified Runs/Tasks/Decisions/Verifications
- immutable content-addressed `MemoryEntry` objects
- parent-linked immutable `MemoryGeneration` snapshots
- deterministic duplicate/staleness/contradiction preprocessing
- model-optional cross-run Dream Analyzer
- independent Dream Auditor
- proposal-only Dream candidates
- candidate classes for memory, Skills, routing, context strategy, process/architecture, and data quality
- deterministic derived-index/cache maintenance only
- Skill candidates routed into Skill Evaluation / later Skill Workshop
- routing/context candidates routed into benchmark gates
- explicit Dream model/resource budgets through Phase 14
- first-class Dream observability and provenance

Core rule:

```text
Dreaming may discover candidate knowledge.
It may not redefine canonical truth.
```

The Dream process cannot modify source code, canonical Decisions, Design Bible content, Goal/Flow/Task/Verification outcomes, active Skills, routing/context policy, permissions, company identity, model weights, or merge state.

See `docs/phase-15-dream-cycle.md` for the detailed architecture and acceptance tests.

**Exit condition:** Origin Forge can inspect bounded completed verified work, discover cross-session patterns and stale derived knowledge, independently audit findings, create an immutable new memory generation, and emit improvement candidates into existing evaluation/governance gates without self-modification authority.

## Phase 16 — Isolated Specialist Roles — PLANNED

Introduce only specialist roles that measurably improve outcomes, such as Reviewer, Researcher, Tester, and Visual Critic. Each receives isolated context and restricted capabilities.

**Exit condition:** specialist isolation improves selected benchmarks without creating an uncontrolled agent swarm.

## Phase 17 — Project Intelligence — PLANNED

Add Entity graph, Design Bible, dependency edges, implementation/artifact/test relationships, impact analysis, and structured project rules.

**Exit condition:** Origin Forge can reason about a feature/entity across files and media and identify affected dependencies before modification.

## Phase 18 — Cryptographic Provenance — PLANNED

Add signed manifests, operational signing keys, company-root identity hierarchy, model/Skill/Tool lineage, key rotation/revocation, and release/build provenance.

**Exit condition:** accepted Artifacts can be cryptographically traced to their Task, Run, parent state, model, Skills, tools, and Verification evidence.

## Phase 19 — Pixelorama Integration — PLANNED

Add deterministic 2D production for sprites, layers, palettes, frames, animations, tilesets, export, and validation.

## Phase 20 — Blockbench Integration — PLANNED

Add structured 3D production for geometry, hierarchy/bones, pivots, UVs, textures, animation, export, and previews.

## Phase 21 — Image and Vision — PLANNED

Add replaceable local image generation/editing and vision inspection adapters for concepts, references, textures/UI exploration, screenshots/assets, and independent visual critique.

## Phase 22 — Audio — PLANNED

Add deterministic/local SFX, FFmpeg processing, music generation, TTS, and audio validation/provenance.

## Phase 23 — Runtime Observation — PLANNED

Add application/game launch automation, screenshots/video capture, logs, crash detection, performance metrics, and visual-regression evidence.

## Phase 24 — Automated Playtesting — PLANNED

Add synthetic players/bots and telemetry for suitable games: deaths, encounter duration, damage, shortages, soft locks, pathfinding failures, progression stalls, and related runtime outcomes.

## Phase 25 — Simulation Layer — PLANNED

Add cheap pre-implementation simulation for economy, loot, crafting, progression, spawning, combat balance, skill trees, and resource distribution.

## Phase 26 — Skill Workshop — PLANNED

Govern operational learning:

```text
observed reusable pattern
→ Skill proposal
→ isolated evaluation
→ regression suite
→ approval
→ new signed Skill version
```

Dream Cycle candidates may enter this pipeline, but active agents and Dream processes never silently replace governing Skills.

## Phase 27 — Code Mode Experiments — PLANNED

Benchmark sandboxed model-written mini-workflows that combine multiple tool operations without returning to the model between every operation. Enable only where measured reliability or cost improves.

## Phase 28 — Cross-Media Watermarking — PLANNED

Develop source/image/audio/3D watermark and fingerprint adapters. Watermarks complement cryptographic manifests and never become the sole proof of origin.

## Phase 29 — Training / Fine-Tuning Research — PLANNED

Only after a substantial verified trajectory dataset exists, investigate routing models, specialized tool-use models, coding-agent fine-tuning, infrastructure-native agents, and offline distillation from verified trajectories and audited Dream outcomes.

Symbolic Dream consolidation remains separate from neural weight training. Production models do not rewrite their own weights.

## Phase 30 — Full Production Interface — PLANNED

Build the polished visual environment around proven infrastructure: project/entity browser, Goal/Flow/Task graph, Design Bible, Artifact previews, verification evidence, provenance inspector, model/resource monitor, Dream/memory-generation inspector, and causal “why does this exist?” history.

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
- progressive tool discovery
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
