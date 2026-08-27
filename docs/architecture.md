# Origin Forge Architecture

Status: **Phase 0 baseline**

This document defines the current top-level architecture for Origin Forge.

## 1. System purpose

Origin Forge is an autonomous production infrastructure, not a single agent. Its job is to convert high-level human intent into verified product changes while preserving project state, history, authority boundaries, and provenance outside the model context.

The system should eventually support complete game-production workflows, including code, 2D assets, 3D assets, textures, animation, audio, UI, simulation, build/test, runtime observation, and playtesting.

## 2. Top-level architecture

```text
                         HUMAN
                           │
                           ▼
                 ┌───────────────────┐
                 │   INTENT LAYER    │
                 │ goals             │
                 │ feedback          │
                 │ constraints       │
                 │ approvals         │
                 └─────────┬─────────┘
                           │
                           ▼
              ┌──────────────────────────┐
              │   PRODUCTION HARNESS     │
              │ project state            │
              │ project graph            │
              │ durable flows            │
              │ authority                │
              │ scheduler                │
              │ provenance               │
              │ resource management      │
              └────────────┬─────────────┘
                           │
                           ▼
                    PROJECT MANAGER
                           │
                    task contract
                           │
                           ▼
                     FRESH EXECUTOR
                           │
                  skills + context
                           │
                     tool/model use
                           │
                           ▼
                       AUDITOR
                           │
                    read-only checks
                           │
                           ▼
                    VERIFIED STATE
                           │
                    next iteration
```

## 3. Long-horizon execution model

Origin Forge adopts **Manager → Executor → Auditor → Verified State** as a foundational execution pattern.

### Manager

The Manager:

- reads the Goal and current verified project state
- decomposes work into bounded Tasks
- determines dependencies and priority
- chooses an appropriate Executor/model profile
- assigns budgets and constraints
- handles blocked work and escalation

The Manager does not directly edit production artifacts.

### Executor

The Executor receives one bounded task plus only the context required to perform it:

- current Goal
- Task contract
- relevant Entities
- relevant Decisions
- selected Skills
- relevant source symbols/files
- available Tools
- authority limits
- current verification state

The Executor's reasoning context is disposable. It may propose changes and invoke permitted tools but cannot declare its own work verified.

### Auditor

The Auditor independently determines what actually happened. It should be read-only wherever practical.

Audits may include:

- compiler/build results
- unit/integration tests
- LSP diagnostics
- static analysis
- artifact validation
- runtime smoke tests
- visual inspection
- audio checks
- project-rule compliance

Only audited facts are promoted into durable verified state.

## 4. State layers

Origin Forge separates state into three classes.

### Ephemeral context

Disposable information:

- chain-of-thought/reasoning state
- temporary hypotheses
- tool chatter
- failed intermediate approaches
- scratch summaries

### Working state

Short-lived execution state:

- current patch
- current task attempt
- recent failures
- temporary files
- active worktree

### Durable verified state

Canonical project truth:

- Goals and Flow state
- accepted Decisions
- Entity relationships
- Changes
- Artifacts
- Verification results
- known bugs
- trusted Skill versions
- provenance and hashes

The project must be recoverable from durable state without requiring old model conversations.

## 5. Durable flows

Long-running work is represented as a Flow with explicit state and revisioning.

Recommended states:

```text
QUEUED
RUNNING
WAITING
BLOCKED
FAILED
QUARANTINED
SUCCEEDED
CANCELLED
```

A Flow survives:

- process restarts
- model unload/reload
- context resets
- workstation reboot

Concurrent Flow updates must use revision/version checks so stale workers cannot overwrite newer state.

## 6. Project graph

The harness maintains semantic relationships between product Entities rather than treating the repository as only a set of files.

Example:

```text
Stone Golem
├── implemented_by → StoneGolem.cs
├── visual → stone_golem.bbmodel
├── texture → stone_golem.png
├── animation → golem_attack.anim
├── sound → stone_hit.ogg
├── drops → StoneCore
├── governed_by → DEC-0041
├── tested_by → GolemCombatTest
└── belongs_to → AncientFactoryBiome
```

This graph powers impact analysis, context selection, provenance, and targeted modification.

## 7. Skills and tools

Origin Forge distinguishes procedural knowledge from actions.

### Tool

A Tool performs an operation.

Examples:

- `code.read_file`
- `code.apply_patch`
- `git.create_worktree`
- `pixelorama.create_sprite`
- `blockbench.add_element`
- `audio.normalize`

### Skill

A Skill explains how and when to combine tools to accomplish a reusable objective.

Examples:

- create a melee enemy
- debug a failing build
- create an animated pixel character
- produce a verified game sound effect

Skills are versioned, progressively disclosed, benchmarked, permission-aware, and governed. Active skills may not silently rewrite themselves.

## 8. Tool discovery

The tool surface may eventually contain hundreds of operations. The full schema set must not be injected into every model call.

The preferred interface is:

```text
search_tools(query)
describe_tool(id)
call_tool(id, args)
```

Only relevant tool schemas enter working context.

## 9. Code intelligence

The initial coding stack should combine:

```text
ripgrep
+ Tree-sitter
+ Language Server Protocol
+ Git
```

Responsibilities:

- ripgrep: fast lexical search
- Tree-sitter: syntax-aware structural parsing
- LSP: definitions, references, types, symbols, diagnostics, refactors
- Git: history, isolation, diff, rollback

The system should select the cheapest exact method before asking a model to inspect large files manually.

## 10. Model abstraction

The architecture uses capability roles, not model names.

Example roles:

```text
router_fast
coder_fast
coder_strong
vision
image_generator
audio_generator
speech
```

A model profile records measured characteristics such as:

- tool-use reliability
- planning quality
- debugging quality
- useful context target
- VRAM/RAM requirements
- tokens per second
- code-mode capability
- task classes where it performs well

Scheduling decisions are empirical and replaceable.

## 11. Resource-aware scheduling

Origin Forge is designed to operate on constrained local hardware.

The scheduler tracks:

- VRAM
- RAM
- CPU load
- estimated duration
- model load/unload cost
- task priority
- dependencies

Large models need not remain loaded simultaneously. For example:

```text
load coding model
→ reason
→ unload
→ load image model
→ generate
→ unload
→ load vision model
→ inspect
```

CPU-bound deterministic work may continue while GPU models are swapped.

## 12. Hooks

Lifecycle guarantees are implemented by hooks rather than relying on prompts.

Initial hook points:

```text
before_task
after_task
before_model_call
after_model_call
before_tool_call
after_tool_call
before_file_write
after_file_write
before_verification
after_verification
before_merge
after_merge
before_context_compaction
after_context_compaction
```

Example:

```text
after_file_write
→ formatter
→ LSP diagnostics
→ provenance update
```

## 13. Loop detection and escalation

The harness detects no-progress behavior using signals such as:

- repeated identical tool calls
- repeated identical test failures
- repeated patches with no verification improvement
- no new information acquired

Escalation policy is capability-based:

```text
deterministic tool
→ small model
→ strong model
→ specialized reviewer/critic
→ human
```

Repeated failure should not become unbounded retry.

## 14. Specialized agents

Origin Forge avoids large conversational agent swarms.

Initial specialized roles may include:

- Manager
- Executor
- Auditor
- Reviewer
- Researcher
- Visual Critic

Each role exists only when context isolation or permission separation improves results.

## 15. Production adapters

Planned production surfaces:

### 2D

Pixelorama:

- sprites
- layers
- palettes
- frames
- animations
- tilesets
- export and validation

### 3D

Blockbench:

- geometry
- groups/bones
- pivots
- UV
- textures
- animations
- export and preview

### Image / vision

Replaceable local models for:

- concept generation
- textures/references
- image editing
- visual inspection

### Audio

- rFXGen for structured SFX
- FFmpeg for deterministic processing

Governed FFmpeg production dispatch uses a typed `audio_source` resolver for
protected PCM16 evidence, an explicit `audio_profile`, and the shared audio
Artifact/Verification/output-binding lifecycle. Schema v29 permits the
FFmpeg execution owner alongside the historical Piper owner while preserving
existing rows. Recovery revalidates durable evidence and never replays an
uncertain STARTED execution.
- replaceable local music model
- replaceable local TTS

## 16. Verification as a subsystem

Verification is not an optional agent behavior. It is a first-class service.

### Code

- compile/build
- tests
- type checking
- lint/static analysis
- runtime smoke tests

### 2D

- dimensions
- palette constraints
- frame counts
- animation tags
- tile seams
- export validity

### 3D

- scale
- geometry validity
- pivots
- UV bounds
- texture references
- animation bones
- asset budgets

### Audio

- duration
- sample rate
- clipping
- silence
- loudness
- loop seams
- format

### Runtime

Later phases add:

- launch automation
- screenshots/video
- crash detection
- performance telemetry
- automated interaction
- playtesting

## 17. Creator/critic separation

Creative output should use a separate critic when subjective evaluation matters.

```text
Creator
→ artifact
→ Critic
→ findings
→ Creator revision
```

The critic evaluates against requirements, the Design Bible, technical constraints, existing project style, and objective verification evidence.

## 18. Learning without immediate model training

Origin Forge should first improve through software-level learning:

```text
production trajectory
→ measured outcome
→ reusable lesson
→ skill/tool/context proposal
→ benchmark
→ promote if improved
```

Only after a large corpus of verified trajectories exists should fine-tuning or training a harness-native model be considered.

## 19. Architectural boundary

The permanent invariant is:

> The model may reason, propose, create, and repair. The infrastructure owns identity, authority, state, history, and truth.

## 20. Governed image-generation vertical

The integrated image path is now a first-class production vertical:

```text
WorkOrder → resolution → binding → claim → dependency assembly
→ DISPATCH_EXECUTION_STARTED → ComfyUI adapter
→ PNG Artifacts/Verifications → image output binding → RETURNED
```

The WorkOrder freezes the exact workflow, model identity, prompt, dimensions,
seed, generation limits, output paths, and request hash. The protected
`ImageWorkflowStore` supplies the immutable workflow graph and local-only
ComfyUI profile. Runtime operation and workspace IDs are allocated only after
the durable STARTED boundary. The image service validates request bytes,
workspace containment, PNG bytes, dimensions, pixel hashes, Artifact parentage,
and Verification evidence before the output binding is published.

Image output bindings are stored in schema v24, one row per declared output,
so multi-output generations retain exact per-output lineage. Recovery consumes
that binding and revalidates its relations; it may finish terminalization but
never invokes ComfyUI again. An interrupted STARTED execution without complete
durable output evidence fails closed and requires explicit operator recovery.
Image generation and visual inspection remain evidence production only: neither
can accept a Task, adopt an Artifact, sign provenance, merge, or release.

## 21. Governed Pixelorama source and animation vertical

Accepted design evidence can also feed a bounded Pixelorama source-creation
WorkOrder without requiring hidden pre-existing `.pxo` state:

```text
accepted DESIGNACC → PlanningInput lineage → WorkOrder → resolution → binding
→ claim → dependency assembly → DISPATCH_EXECUTION_STARTED
→ trusted Pixelorama bridge → project/PNG Artifacts and Verifications
→ source output binding → RETURNED
```

The source request freezes the exact accepted-design projection, sprite and
animation specification, export declarations, budget, and request hash. A
trusted, explicitly configured bridge profile supplies the executable and
package identity; it cannot be selected by the caller or model. Schema v30
stores one immutable output-binding row per generated project or export and
preserves exact Artifact and Verification parentage.

Recovery independently validates the request/result JSON, bridge result,
output paths, byte hashes, dimensions, and PASS Verifications. A durable
binding can finish terminalization without invoking the bridge again; an
interrupted STARTED execution without complete evidence fails closed. Source
creation and animation production produce evidence only: they do not accept
Tasks, adopt canonical assets, sign provenance, merge, or release.
