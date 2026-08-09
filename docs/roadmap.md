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

## Phase 15 — Offline Dream Cycle / Memory Consolidation — DONE

Implemented a bounded offline consolidation layer that is explicitly separate from production-time execution.

Implemented components:

- frozen content-addressed Dream input manifests over terminal Run/Task/Decision/Verification evidence
- immutable content-addressed `MemoryEntry` objects
- parent-linked immutable `MemoryGeneration` snapshots
- exact evidence hashes/revisions/classes and active-memory revalidation
- deterministic duplicate/staleness/hash-drift/revision-drift and Decision-supersession preprocessing
- deterministic data-quality Analyzer
- optional bounded model-backed cross-run Analyzer using the existing `ModelAdapter` contract
- independent Dream Auditor with structural-vs-semantic authority separation
- proposal-only Dream candidates whose candidate type determines the mandatory downstream gate
- candidate classes for memory, Skills, routing, context strategy, process/architecture, and data quality
- exact `dream-audit` Verification binding before any new memory generation can be constructed
- ancestor audit revalidation so later durable-evidence tampering invalidates derived memory
- protected immutable Dream persistence with symlink/containment/size/count validation
- atomic no-overwrite object publication under competing writers
- bounded model-call/token/evidence/candidate budgets
- model context/response hashes and durable model-Dream observability Verifications
- durable deterministic Dream Cycle Goal/Flow/Task/Run lifecycle with verification-gated completion
- fail-closed Dream lifecycle cleanup on invalid evidence or planning failure
- operator `dream status`, `dream plan`, and deterministic `dream run` surfaces
- read-only manifest/candidate/audit/memory/generation inspection
- no CLI generative-model execution until a trusted runtime loader is explicitly wired
- no automatic memory generation, Skill promotion, routing/context policy mutation, source mutation, or merge authority

Core rule:

```text
Dreaming may discover candidate knowledge.
It may not redefine canonical truth.
```

The Dream process cannot modify source code, canonical Decisions, Design Bible content, Goal/Flow/Task/Verification outcomes from analyzed work, active Skills, routing/context policy, permissions, company identity, model weights, or merge state. Its own durable Dream lifecycle records are governed through the normal verified runtime.

See `docs/phase-15-dream-cycle.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can inspect bounded completed work including failed attempts, discover cross-session and stale-derived-memory patterns, independently audit findings, construct immutable audit-bound memory generations without mutating parents, and emit improvement candidates into existing governance gates without self-modification authority.

## Phase 16 — Isolated Specialist Roles — DONE

Implemented the first isolated specialist role, Reviewer, as an advisory sidecar rather than a new production authority path.

Implemented components:

- separate specialist authority roles from Phase-14 model capability/resource roles
- immutable bounded `SpecialistContract` objects and typed exact evidence references
- exact frozen evidence packages persisted for replay
- fresh one-shot `IsolatedReviewer` using the normal `ModelAdapter` contract
- strict Reviewer JSON output limited to findings, with infrastructure-owned finding/report IDs and computed risk
- independent structural `ReviewerReportAuditor`
- explicit structural-vs-semantic separation: a structurally valid report does not verify its semantic findings
- protected immutable specialist contract/evidence/report/audit persistence
- symlink/root containment, byte/count limits, tamper detection, and atomic no-overwrite publication
- dedicated existing RUNNING `REVIEWER` Run/Task requirement and Run-level model/context/response/report/audit provenance
- read-only specialist and Reviewer-evaluation inspection surfaces
- repeatable paired Reviewer evaluation with exact labeled issue signatures, true/false positives, critical misses, precision/recall/F1, token/time/context/resource metrics, optional downstream repair outcomes, regression-dominant verdicts, and replayability checks
- explicit fresh-context isolation proving Reviewer input contains only the frozen specialist package rather than Executor scratch/session state
- no default production blocking gate, model-execution CLI, repair authority, Task status authority, merge authority, peer-agent messaging, or recursive delegation

Core rule:

```text
specialist insight = evidence
infrastructure verification = authority
```

Researcher, Test Planner, and Visual Critic remain deferred until a measured need and relevant evidence surface exist. Reviewer findings can inform a human/Manager or a later governed repair Task, but they cannot directly change production state.

See `docs/phase-16-specialist-roles.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can invoke a fresh isolated Reviewer over exact bounded evidence, persist and independently structurally audit the report, prove the specialist has no production mutation or verification authority, and measure Reviewer value with a replayable evaluation protocol before any default integration is enabled.

## Phase 17 — Project Intelligence — DONE

Implemented the first durable semantic project layer in the existing protected SQLite truth store.

Implemented components:

- stable infrastructure-owned Entity identity across implementation changes
- software/media-neutral Entity kinds and governed lifecycle status/revisions
- typed directional Entity relations with same-project composite foreign keys
- explicit self-relation rejection and duplicate-active-edge prevention
- Entity bindings to files, symbols, Tasks, Decisions, Artifacts, Verifications, and inert external references
- portable/protected file-binding path validation and optional pinned SHA-256 hashes
- structured Design Bible `DesignRule` records with category, authority, global/scoped applicability, retirement, and append-only supersession
- project-scoped validation for durable binding targets, relation evidence, and Design Rule scopes
- optimistic revisions and state-event history for governed semantic changes
- deterministic bounded impact analysis with inbound/outbound/bidirectional traversal, relation filtering, cycle detection, stable ordering, content hashes, and explicit truncation flags
- active global/scoped Design Rules and implementation bindings included in impact evidence
- read-only stale file-binding inspection reporting CURRENT/STALE/MISSING/UNPINNED/INVALID/TOO_LARGE without rewriting canonical bindings
- read-only Project Intelligence CLI for status/list/show/binding-inspect/impact
- no automatic model-context integration, graph auto-discovery promotion, source mutation, Task verification, or merge authority

Core rule:

```text
semantic project structure = canonical infrastructure state
model inference             = proposal/evidence only
```

AST/LSP intelligence remains a live code-structure signal; Project Intelligence represents stable product meaning. Later controlled context integration can compose the two after separate measurement rather than making the model traverse or rewrite the semantic graph directly.

See `docs/phase-17-project-intelligence.md` for the detailed architecture and acceptance tests.

**Exit condition met:** Origin Forge can represent stable product/project Entities, typed cross-media relationships and implementation bindings, enforce/query structured Design Bible rules, detect stale file bindings, and deterministically identify bounded change impact without relying on a model to rediscover project meaning or granting model-generated graph claims canonical authority.

## Phase 18 — Cryptographic Provenance — DONE

Implemented company-root trust identity, Ed25519 operational certificates/signatures, revocation, signed provenance manifests, protected public provenance persistence, offline trust verification, and currentness/freshness inspection while keeping secret key material outside media/runtime authority.

**Exit condition met:** accepted Artifacts can be cryptographically traced through signed immutable provenance to their causal Task/Run/artifact state and governed tool/model/Skill evidence without making signatures a substitute for current verification.

## Phase 19 — Pixelorama Integration — DONE

Implemented the first bounded deterministic 2D media integration layer:

- canonical bounded sprite/project/layer/frame/animation/palette/pixel contracts
- deterministic standard-library RGBA8 PNG encoding/inspection and structural validators
- protected isolated `MEDIA-*` workspaces and `PXOP-*` operations
- strict bridge protocol and one-shot no-shell bounded process execution
- post-editor symlink/root/path containment revalidation and undeclared-output rejection
- media Run/Artifact/Verification evidence without production Task completion authority
- explicit create-only governed output adoption with no-overwrite/protected-root rules
- read-only Pixelorama status inspection
- Phase-18 provenance integration for explicitly adopted raster output
- direct Pixelorama v1.2 CLI spritesheet export over opaque `.pxo` input
- externally pinned `v1.2-stable` runtime/executable identity and frozen real upstream `.pxo` fixture
- opt-in supply-chain evidence workflow whose authoritative frozen-pin real-editor run completed successfully

The v0 direct CLI adapter deliberately exposes only the smallest proven export surface. Pixelorama project creation/import/save through Extension API 9, generic model-facing media tools, image generation, and aesthetic vision critique remain separately governed future capabilities.

See `docs/phase-19-pixelorama.md` and `docs/pixelorama-real-gate.md` for the implemented boundary and frozen real-editor evidence.

**Exit condition met:** Origin Forge can run a pinned real Pixelorama v1.2 headless spritesheet export over exact frozen input inside an isolated workspace, independently validate containment/hash/raster output, record evidence without transferring Task authority, and explicitly adopt a verified new media output without overwrite or signing authority.

## Phase 20 — Blockbench Integration — IN PROGRESS / BLOCKED

Implemented the deterministic editor-independent 3D substrate:

- infrastructure-owned `MODEL3D-*` workspace IDs and `BBOP-*` operation IDs
- bounded immutable project contracts for bones/hierarchy, cuboids, pivots/rotations, UV offsets, exact texture refs, animations, and keyframes
- deterministic ordering/content addressing with missing-reference, duplicate, numeric-bound, and hierarchy-cycle rejection
- strict content-addressed bridge request/result protocols with exact request/version/fingerprint/output binding and no production-authority fields
- protected one-shot no-shell bridge process execution with pinned executable identity, isolated runtime state, hard timeout/log/output bounds, strict result JSON, exact export-set matching, output rehashing, symlink/root containment, and undeclared-entry rejection
- independent standard-library GLB v2/glTF 2.0 structural inspection covering container framing, embedded buffers/images, graph references, hierarchy cycles, skins, and animation sampler/target references
- explicit rejection of external GLB asset URIs in the initial evidence surface
- fake-process adversarial integration coverage proving the Origin Forge side of the isolation/protocol/validation boundary

The intended real-editor boundary is a pinned governed JavaScript plugin using Blockbench's supported plugin/API surface. Origin Forge does not synthesize Blockbench's internal `.bbmodel` bytes, execute model-generated JavaScript, manipulate Electron/Chromium private state, or use GUI-coordinate automation.

**Current blocker:** Blockbench v5.1.4 exposes supported plugins and `--userData`, but the inspected upstream startup surface does not provide a supported non-interactive way to load an exact local side-loaded plugin, nor a documented headless create/edit/export CLI. Side-loaded plugin testing/loading is interactive; startup reloads plugins from persisted `installed_plugins` state stored through browser `localStorage`. Merely placing a plugin in the isolated `plugins/` directory is insufficient, while manufacturing Chromium LevelDB/localStorage would depend on undocumented private state. The web `plugins=` URL parameter prompts the user to install store plugin IDs rather than providing a governed local-plugin bootstrap.

See `docs/phase-20-blockbench.md` for the implemented contract and exact unblock conditions.

**Exit condition pending:** Phase 20 remains draft until a supported non-interactive Blockbench plugin/bootstrap or equivalent programmatic editor entry point can drive one pinned real Blockbench execution whose GLB output is independently validated by Origin Forge.

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
