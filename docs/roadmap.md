# Origin Forge Roadmap

Status: **Current baseline**

The roadmap is ordered to prove dependable infrastructure before expanding autonomy or media production.

## Phase 0 — Specification and Foundations

Define before implementation:

- architectural laws
- core object model
- ID strategy
- state-transition semantics
- authority/security model
- company-root provenance design
- project layout
- tool contract
- model-profile contract
- execution lifecycle

Exit condition:

> A sufficiently precise implementation specification exists that the durable runtime can be built without inventing core semantics while coding.

## Phase 1 — Durable Runtime

Implement structured persistent state for:

- Goal
- Flow
- Task
- Decision
- Change
- Artifact
- Verification
- Run

Requirements:

- SQLite
- schema migrations
- revisioned Flow mutation
- restart recovery
- explicit state transitions
- appendable history

Exit condition:

> Create a multi-step Flow, kill/restart the process, and continue from exactly the persisted state without conversational memory.

## Phase 2 — Basic Local Coding Agent

Add:

- local model adapter
- filesystem read
- controlled shell
- Git inspection
- patch application
- bounded Task execution

Exit condition:

> Given a small coding Task, an Executor can inspect the repository and produce a valid isolated patch.

## Phase 3 — Manager / Executor / Auditor

Implement the long-horizon execution core:

```text
Manager
→ bounded Task contract
→ fresh Executor
→ independent Auditor
→ verified state
```

Exit condition:

> The system can complete several sequential Tasks using fresh Executor contexts while preserving only structured verified progress.

## Phase 4 — Safe Execution

Add:

- Git worktrees/task branches
- checkpoints
- rollback
- authority matrix
- permission enforcement
- lifecycle hooks
- loop/no-progress detection
- bounded retries
- quarantine/block states

Exit condition:

> A failing or maliciously confused Executor cannot damage known-good project state or silently expand its authority.

## Phase 5 — Code Intelligence

Add:

- ripgrep
- Tree-sitter
- Language Server Protocol
- symbol index
- definitions/references
- diagnostics

Exit condition:

> Repository understanding relies on structured symbol retrieval before broad file dumping, and LSP diagnostics participate in verification.

## Phase 6 — Skill System

Add:

- Skill registry
- `SKILL.md`
- metadata/schema
- versioning
- dependencies
- permissions
- progressive disclosure
- immutable historical versions

Exit condition:

> The Executor initially sees compact Skill metadata and loads full procedural knowledge only when relevant.

## Phase 7 — Skill Evaluation

Add:

- Skill test cases
- with-vs-without comparisons
- regression evaluation
- token/context metrics
- success-rate tracking

Exit condition:

> Skill changes can be accepted or rejected using measured task outcomes rather than intuition.

## Phase 8 — Context Manager

Add:

- context budgets
- relevant-state selection
- Entity/Decision/Task retrieval
- context compaction boundaries
- durable-state promotion rules
- fresh-session initialization

Exit condition:

> A fresh Executor receives a compact task-specific context from a project with substantially more history than the model context window.

## Phase 9 — Tool Search

Add:

```text
search_tools(query)
describe_tool(id)
call_tool(id, args)
```

Do not place the entire tool schema library in every context.

Exit condition:

> A model can reliably discover and use tools from a growing registry while only loading relevant schemas.

## Phase 10 — Model and Resource Scheduler

Add:

- model profiles
- capability routing
- escalation policy
- model load/unload
- VRAM/RAM accounting
- CPU/GPU scheduling
- task/model budgets

Exit condition:

> Origin Forge can choose between at least two model profiles and serialize incompatible GPU workloads without losing task state.

## Phase 11 — Isolated Specialist Roles

Introduce only roles that provide measurable value:

- Reviewer
- Researcher
- Tester
- Critic

Exit condition:

> Specialist contexts improve selected benchmarks without turning the system into an uncontrolled agent swarm.

## Phase 12 — Project Intelligence

Add:

- Entity graph
- Design Bible
- dependency edges
- impact analysis
- structured project rules

Exit condition:

> Origin Forge can reason about a feature/entity across multiple code and asset files and determine affected dependencies before modification.

## Phase 13 — Cryptographic Provenance

Add:

- Artifact IDs
- content hashes
- signed manifests
- operational signing keys
- model/Skill/Tool lineage
- company-root identity hierarchy

Exit condition:

> Every accepted Artifact can be traced to its Task, Run, model, Skill versions, tool versions, parent state, and Verification evidence.

## Phase 14 — Pixelorama Integration

Add 2D production:

- sprites
- layers
- palettes
- frames
- animations
- tilesets
- export
- validators

Exit condition:

> A bounded Task can create/modify a 2D game asset, validate it, and register it as a provenance-tracked Artifact.

## Phase 15 — Blockbench Integration

Add 3D production:

- geometry
- hierarchy/bones
- pivots
- UV
- textures
- animation
- export
- preview

Exit condition:

> A bounded Task can create/modify and validate a structured 3D game asset through deterministic Blockbench-facing operations.

## Phase 16 — Image and Vision

Add replaceable local adapters for:

- image generation
- image editing
- visual references/textures
- screenshot/asset inspection
- visual critic

Exit condition:

> Generation and independent visual inspection can participate in a closed production/verification loop.

## Phase 17 — Audio

Add:

- rFXGen SFX
- FFmpeg processing
- local music adapter
- local TTS adapter
- audio validation

Exit condition:

> Origin Forge can create/process/validate a game audio Artifact from a structured Task.

## Phase 18 — Runtime Observation

Add:

- launch/build automation
- screenshots/video capture
- log ingestion
- crash detection
- performance metrics
- visual regressions

Exit condition:

> The Auditor can inspect actual runtime behavior rather than relying only on source-level evidence.

## Phase 19 — Automated Playtesting

Add synthetic players/bots and telemetry.

Target metrics may include:

- deaths
- encounter duration
- damage taken
- resource shortages
- soft locks
- pathfinding failures
- progression stalls

Exit condition:

> Gameplay changes can be evaluated using repeatable runtime evidence.

## Phase 20 — Simulation Layer

Add cheap pre-implementation simulation for suitable systems:

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

## Phase 21 — Skill Workshop

Add governed improvement:

```text
observed pattern
→ Skill proposal
→ isolated evaluation
→ regression suite
→ approval
→ new signed Skill version
```

Exit condition:

> Origin Forge can improve operational knowledge without allowing active agents to silently rewrite their own instructions.

## Phase 22 — Code Mode Experiments

Benchmark sandboxed model-written mini-workflows that combine multiple tool operations without returning to the model between every step.

This phase is experimental and model-dependent.

Exit condition:

> Enable only if measured reliability/cost beats ordinary structured tool use for specific model profiles.

## Phase 23 — Cross-Media Watermarking

Develop watermark/fingerprint adapters for:

- source code
- images/pixel art
- audio
- 3D assets

All watermarks link back to the permanent company provenance identity.

Exit condition:

> At least one robust watermark scheme complements cryptographic manifests without making watermarking the sole proof of origin.

## Phase 24 — Training / Fine-Tuning Research

Only after enough verified trajectories exist, investigate:

- routing models
- specialized tool-use models
- coding-agent fine-tuning
- infrastructure-native agent models

Exit condition:

> Training is justified by measured evidence that software-level improvements alone have reached a meaningful limit.

## Phase 25 — Full Production Interface

Build a polished visual interface around the proven runtime.

Potential surfaces:

- project/entity browser
- Goal/Flow/Task graph
- Design Bible
- Artifact previews
- verification evidence
- provenance inspector
- resource/model monitor
- "why does this exist?" history

The UI comes late so early architecture is not distorted around a premature frontend.

---

# v0.1 — First Useful Release

The first genuinely useful release should do one thing exceptionally well:

> Given a real software Task, autonomously inspect a repository, select relevant context, modify code in an isolated workspace, compile/test it, recover from bounded failures, independently audit the result, show the final diff, and persist what happened.

Lifecycle:

```text
Human request
    ↓
Goal
    ↓
Flow / Task
    ↓
Manager
    ↓
Context retrieval
    ↓
Fresh Executor
    ↓
Patch
    ↓
Compile / tests
    ↓
Auditor
    ↓
FAIL → repair/escalate
PASS
    ↓
Provenance
    ↓
Review / merge
```

Success criteria:

- no dependency on long chat history
- process restart does not lose task state
- work is isolated from known-good branch
- model cannot self-verify completion
- repeated failure is bounded
- final diff is understandable
- meaningful changes have causal/provenance records

If v0.1 is dependable, Origin Forge has its nervous system.

# v0.5 — Integrated Development Infrastructure

Target capabilities:

- durable long-running work
- local coding models
- Skills
- LSP/code intelligence
- tool discovery
- model/resource scheduling
- project graph
- Design Bible
- provenance
- basic 2D production

# v1.0 — Integrated Game Production

A representative Goal:

> Create a slow heavily armored enemy that lives in abandoned factories and attacks with a large mechanical hammer.

Origin Forge should eventually be capable of coordinating:

- design specification
- gameplay implementation
- behavior
- tests
- 2D/3D asset
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
