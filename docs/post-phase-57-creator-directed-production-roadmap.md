# Origin Forge — Post-Phase-57 Creator-Directed Production Roadmap

Status: **STRATEGIC EXECUTION ROADMAP — PLANNING ONLY, NO RUNTIME OR RELEASE AUTHORITY**

Authoritative planning base:

```text
8cd2feb38d584875860d9775177b78f0c6cfabd5
```

This roadmap captures the revised production direction after the Phase-57 architecture was frozen. It does not rewrite or invalidate completed Phases 0–56, does not authorize Phase-57 implementation by itself, and does not grant new model, Manager, browser, editor, production, acceptance, signing, merge, deployment, or release authority.

This document supersedes only the **future-direction assumptions** after the current Phase-57 boundary. Historical roadmap entries remain authoritative records of what was actually built and accepted.

The central product shift is:

> **The creator manipulates intent as directly as possible; Origin Forge decomposes that intent into bounded work and makes it production-real.**

The normal path is no longer simulation-first and must not become one-prompt-whole-game automation.

---

## 1. Revised north star

Origin Forge should optimize for a tight creator feedback loop over real or production-near artifacts:

```text
creator intent
→ direct editor manipulation / explicit semantic instruction
→ scope analysis
→ recursive bounded decomposition when needed
→ durable dependency-aware local queue
→ cheap preview / bounded variants where useful
→ selective production execution
→ validation and checkpoint
→ creator review / refinement
→ integration
```

The creator should not need to know in advance whether a request that sounds small is operationally enormous. Origin Forge owns executable granularity.

The creator should also not be forced to translate spatial thoughts into precise prose when direct spatial input is clearer. Words remain valuable for semantics, mood, purpose, and high-level direction; spatial edits should carry geometry intent.

The system should prefer progress that produces reusable production state over expensive disposable rehearsals.

---

## 2. Core laws for future work

### 2.1 The user specifies intent; Origin Forge owns executable granularity

A short request may represent a large work graph. A long request may still describe one bounded operation. Task size must therefore be established from actual scope, dependencies, affected artifacts, tool transitions, validation requirements, resource cost, and destructive-change risk rather than prompt length.

No expensive worker execution should begin merely because a request was presented as one Task.

If the request is too broad to execute, validate, retry, and recover independently, it must become a parent intent whose executable children are bounded further.

Decomposition is recursive.

If hidden complexity is discovered only after work begins, the worker must be allowed to stop without silently widening authority or scope and return a durable result equivalent to:

```text
REQUIRES_DECOMPOSITION
```

The parent work remains valid intent; it is not treated as a user error.

### 2.2 One bounded worker job at a time, many queued intentions over time

Workers should receive one bounded job with exact inputs, explicit authority, exact output expectations, and independently checkable acceptance criteria.

The creator may queue many future intentions while local compute is occupied. Queueing must not imply that every queued item executes immediately or that all edits are collapsed into one giant generation request.

### 2.3 The interactive loop and production loop are separate

The editor should remain responsive while expensive local work runs.

```text
INTERACTIVE LOOP
creator ↔ editor
milliseconds / seconds

PRODUCTION LOOP
queue ↔ local models / Blender / tools / validators
seconds / minutes / longer
```

Cheap preview representations are permitted when needed for responsiveness, but preview state is not canonical production truth.

### 2.4 Direct manipulation is preferred when the intent is spatial

For geometry and composition, showing the desired change should be easier than describing it.

The initial 3D spatial-intent vocabulary should remain deliberately small:

```text
ADD          volume should exist here
SUBTRACT     volume should not exist here
PROTECT      preserve this region as closely as possible
REGENERATE   redesign this bounded region within its constraints
BLEND        permit local transition changes needed to integrate adjacent edits
```

Later operation families such as DETAIL or APPEARANCE may be added only as separately defined semantics rather than overloading the shape layer.

UI color may communicate the operation, but **color is never the authoritative meaning**. The durable semantic operation is authoritative. This preserves accessibility, theme independence, exportability, and future UI changes.

### 2.5 Selective regeneration is preferred to whole-asset regeneration

When a bounded region changes, the default production action should preserve unaffected regions and rebuild only:

```text
affected region
+ necessary transition/blend boundary
+ downstream production derivatives that are actually invalidated
```

A local edit must not become whole-asset regeneration merely because a backend makes that easier. If the change truly affects most of the artifact, the scope gate should classify it accordingly and decompose or explicitly authorize the wider realization.

### 2.6 Changes execute incrementally, not as one giant apply

A creator may paint or specify several changes rapidly. Origin Forge should convert those intentions into an ordered dependency graph and small compatible batches.

Independent changes may run concurrently where the governed resource scheduler permits. Dependent or overlapping changes must preserve explicit order.

Typical geometry ordering may resemble:

```text
PROTECT constraints remain active throughout
SUBTRACT / ADD / REGENERATE
→ BLEND
→ local cleanup
→ affected production derivatives
→ validation
```

This is not a mandatory universal ordering; each future contract must freeze its own exact semantics.

Every accepted batch should create a recoverable checkpoint so a later failed or rejected batch does not destroy earlier accepted progress.

### 2.7 Variants are bounded exploration, not whole-object drift

A creator should be able to mark one region and request alternatives for that region while protected surroundings remain stable.

Example:

```text
current realization
→ select horn region
→ generate bounded variants A/B/C/D
→ human selects C
→ C becomes the next reviewed base
→ optional ghost refinement
→ next bounded batch
```

Variant selection is a human creative decision unless a later explicit policy defines another authority. Unselected variants may be retained as provenance/history without becoming canonical production state.

### 2.8 Technical readiness and artistic readiness are separate

A system may establish that an asset is technically valid. It cannot infer that the creator actually wants that asset in the game.

Future game-ready publication must require both:

```text
current technical/provenance evidence
+
explicit current human art-direction acceptance
```

A technically passing result is not automatically `GAME_READY`.

A creative workflow also needs an explicit pause/checkpoint outcome. Work does not have to be forced into accepted/rejected merely because the creator wants to stop for now.

### 2.9 Provenance records facts, not human/AI percentage scores

Origin Forge should preserve exact realization lineage such as:

- source/reference evidence where applicable;
- model/tool identity and versions;
- generated proposal or candidate identity;
- exact base realization;
- human-authored spatial intent;
- selected variant;
- manual edits;
- scripts and parameters;
- topology/UV/material/texture/rig/LOD/collider transformations;
- technical audits;
- license/attribution obligations;
- human acceptance/publication evidence.

No human-vs-AI authorship percentage, contribution score, or social label is required by this roadmap.

If a future law, marketplace, platform policy, customer requirement, or product feature requires disclosure, it should derive a defensible disclosure from preserved provenance rather than inventing percentages now.

### 2.10 Simulation is an optional specialist capability, not a default stage

Existing simulation work remains valid infrastructure. This roadmap does **not** delete Phase-25 or Phase-47 capabilities.

However, future production planning must not insert simulation merely because a simulation capability exists.

The normal path is:

```text
intent
→ scope / decomposition
→ editor or direct manipulation
→ cheap preview / bounded variants when useful
→ bounded production
→ validation
→ human review when subjective
→ integration
```

Simulation is justified only when a concrete question depends materially on dynamic, temporal, emergent, or high-downstream-cost behavior and cannot be answered more cheaply and reliably by preview, bounded direct execution, validation, or rollback.

Useful specialist cases can include:

- cutscene and scene previsualization;
- camera choreography and staged sequences;
- trailers, advertising, or presentation scenes;
- physics and interaction behavior;
- economy/balance evolution;
- large-agent interaction;
- performance/load behavior;
- expensive production scenarios where a failed real attempt would cost substantially more than the simulation.

Definitions must remain distinct:

```text
PREVIEW             show an approximate proposed result
VARIANT EXPLORATION generate alternatives for human comparison
SIMULATION          execute a behavior model over time/interactions
```

The routing rule is:

> **Prefer the cheapest trustworthy operation that answers the question while producing the most reusable production progress.**

Simulation must be justified by the bounded question, not treated as ritual.

---

## 3. Immediate prerequisite — finish Phase 57 without widening it

Phase 57 remains the current architectural prerequisite and keeps its frozen scope:

```text
exact Task + Phase-31 lineage + accepted Phase-56 design
→ immutable semantic-translation input
→ proposal-only model translation
→ independent audit
→ HUMAN_OPERATOR publication approval
→ canonical MODEL3DREQ-* publication
→ exact Task/request relation
→ existing Phase-51 Blender production
```

The new content/editor roadmap must not be backported into Phase 57 merely because it will eventually consume the same Blender production chain.

Phase 57 must remain focused on the missing semantic-request publication authority boundary.

Only after Phase 57 is implemented, accepted, closed, and merged should the new roadmap phases begin unless a later explicit architecture decision proves a safe parallel slice.

---

# Proposed execution sequence

The phase numbers below are **roadmap reservations only**. They do not reserve database schema versions, durable ID families, CLI commands, browser authority, or implementation permission.

## Phase 58 — Governed Recursive Work Decomposition

**Goal:** make executable granularity an infrastructure responsibility rather than a user prerequisite.

Freeze and implement a general decomposition boundary that can determine when one apparent Task is too large for one safe execution unit.

Required properties:

- one exact parent intent / Task revision as input;
- deterministic infrastructure-owned scope facts where available;
- bounded model assistance may propose decomposition but cannot mint authoritative child work by itself;
- independent structural validation of decomposition;
- explicit limits on child count, dependency depth, fan-out, and total decomposition budget;
- exact parent→child lineage;
- child acceptance criteria and required capabilities remain explicit;
- no hidden scope widening;
- recursive decomposition of an oversized child;
- durable `REQUIRES_DECOMPOSITION` handling when hidden complexity is found mid-execution;
- no requirement that the creator understand operational complexity before asking for an outcome.

Scope signals may include:

- number and type of affected artifacts;
- number of semantic systems touched;
- tool/backend transitions;
- independent outputs;
- validation surfaces;
- expected resource/latency class;
- destructive or irreversible risk;
- dependency fan-out/depth;
- known production derivatives that will become stale.

**Exit condition:** no new expensive production worker must accept a known non-atomic unit merely because the original request was phrased as one Task.

## Phase 59 — Durable Dependency-Aware Local Work Queue

**Goal:** make long-running local production natural without blocking the creator or turning the Manager into an uncontrolled daemon.

Add a governed durable work graph/queue over bounded tasks from Phase 58 and existing production Tasks.

Required properties:

- explicit dependency edges rather than FIFO-only semantics;
- durable queue/checkpoint state reconstructable after restart;
- deterministic eligible-work selection under frozen policy;
- integration with existing Phase-14 resource admission rather than a second hardware scheduler;
- independent jobs may proceed while an unrelated job is blocked;
- dependency-blocked jobs never run early;
- explicit pause/resume/cancel semantics;
- human-selection gates can block only dependent work;
- no hidden retry storm or silent fallback worker;
- one bounded worker execution remains the atomic execution unit;
- creator/editor may queue future intentions while local processing continues;
- queue operation must remain inspectable and attributable.

A future UI may present simple states such as queued/running/waiting-for-selection/blocked/paused/failed/completed, but the durable backend relation remains authoritative.

**Exit condition:** local compute latency becomes a schedulable production fact rather than a reason to make user interaction synchronous or to collapse many changes into one giant job.

## Phase 60 — Governed Visual Direction, Semantic Asset Identity & Asset Specification

**Goal:** establish the content truth that the editor and AI realization loop will manipulate.

Introduce a governed content-production substrate containing at least:

### Visual direction

Versioned, addressable visual-direction evidence for concepts such as:

- palette;
- shape language;
- material rules;
- lighting profiles;
- canonical scale;
- reference constraints;
- target visual language.

A visual bible must be governed data with exact identity/hash/currentness, not merely an informal Markdown file.

Reference material should be treated as input evidence and interpreted into target creative constraints; reference images are not automatically production truth.

### Semantic asset identity

Gameplay/world logic should reference semantic content identity rather than one concrete mutable file path.

Conceptually:

```text
enemy.goblin.melee
prop.factory.valve.large
architecture.factory.window.broken
```

A semantic asset may bind a placeholder/blockout first and later a current game-ready realization without requiring upstream gameplay logic to be rewritten merely because the physical asset changed.

### Asset specification and decomposition

Represent content decomposition durably:

```text
reference / intent
→ large structure
→ components
→ production assets
```

The resulting graph should be compatible with Phase-58 recursive work decomposition and Phase-59 queue execution.

### Source and licensing provenance

External source/reference/license/attribution evidence and inherited obligations must survive transformations into later realizations.

**Exit condition:** Origin Forge can answer what visual rules govern an asset, what semantic content identity it realizes, what exact specification it implements, and what source/provenance obligations it inherits before any interactive regeneration is treated as production work.

## Phase 61 — Governed Spatial Shape Intent / Ghost Edit Contract

**Goal:** make direct human spatial direction a first-class immutable production input without giving the preview editor direct production authority.

Introduce a representation-independent spatial-intent artifact bound to one exact base realization/hash.

Initial semantic operations:

```text
ADD
SUBTRACT
PROTECT
REGENERATE
BLEND
```

The durable contract should capture, where appropriate:

- exact base asset/realization identity and hash;
- canonical coordinate/scale frame;
- one or more bounded regions/fields/masks;
- operation semantics;
- strength/influence;
- falloff/boundary semantics;
- protected regions;
- explicit relation between overlapping operations;
- creator identity/authority where required;
- creation time and immutable content hash.

The contract should not require direct vertex edits. A volumetric/SDF/voxel/mask-like internal representation is permitted if it preserves the intended semantic meaning and can be translated by different current/future 3D backends.

A shape intent created against an older realization must become historical/stale rather than silently rebasing itself onto unrelated geometry.

**Exit condition:** a creator can durably say “more here, less here, preserve this, redesign that region” against an exact current 3D realization without prose being the only source of geometric intent.

## Phase 62 — Interactive Preview Editor & Premove Editing Surface

**Goal:** provide the fast creative interaction that motivates the new content workflow while keeping the editor a projection/control surface rather than authority.

Implement a responsive 3D preview/editor surface over Phase-60/61 governed state.

Key UX target:

> **Edit intention, not topology.**

Expected interaction family:

- paint/select one semantic job over a 3D region;
- rapid brush-radius adjustment, e.g. mouse wheel;
- rapid strength/influence adjustment, e.g. a modifier gesture such as Shift;
- operation switching without opening deep dialogs;
- separately toggleable overlays/layers;
- operation colors for fast visual recognition;
- overlay-off inspection of the underlying asset;
- undo/redo of uncommitted editor intent;
- clear commit/apply boundary that publishes governed intent rather than mutating canonical production files directly.

Exact key bindings and colors are UX choices, not frozen authority contracts.

The creator should be able to continue marking or queuing later work while earlier production jobs run. This is the creative equivalent of a “premove”: intent may be authored ahead of available local compute, but it only executes when its exact dependencies/currentness permit.

The editor must surface stale-base conflicts rather than auto-applying old shape intent to a new realization.

**Exit condition:** common shape-direction changes can be communicated in seconds through spatial interaction and can enter the governed queue without giving the browser/editor a direct Blender mutation, acceptance, or publication bypass.

## Phase 63 — Bounded Local Regeneration, Variant Exploration & Incremental Integration

**Goal:** make AI-assisted 3D realization selective, branchable, and recoverable rather than whole-model regeneration by default.

Required capabilities:

- derive exact regeneration scope from current asset + accepted spatial intent;
- preserve PROTECT regions;
- constrain changes to marked/derived affected regions;
- add only the transition/blend zone required for integration;
- generate several bounded alternatives for one selected region when requested;
- preserve exact candidate lineage;
- require explicit human selection before a subjective variant becomes the chosen continuation;
- allow the selected candidate to become the next reviewed base;
- split large marked regions through Phase 58 instead of launching an unbounded generation;
- decompose multiple marked changes into dependency-aware semantic batches;
- checkpoint after each accepted batch;
- retry/regenerate only the failed or rejected bounded batch;
- avoid replaying already accepted expensive local generation solely for recovery;
- invalidate only production derivatives actually affected by the changed region.

The implementation may use Blender scripts, model-native 3D editing, image/multiview reconstruction, implicit fields, mesh operations, or future backends, but the user-facing governed input must remain the representation-independent intent contract.

**Exit condition:** the creator can repeatedly select → ghost-edit → request variants → choose → integrate → checkpoint without unrelated geometry drifting on every generation pass.

## Phase 64 — Content Realization Pipeline, Technical Validation & Provenance

**Goal:** turn a creatively selected realization into a technically trustworthy production asset without conflating technical validity with artistic approval.

Build governed realization lineage over the exact selected asset candidate and all required production transformations, such as:

- mesh/source realization;
- scripts and parameters;
- topology/retopology/decimation;
- UVs;
- materials;
- textures;
- rigging/retargeting;
- animations where applicable;
- colliders;
- LODs;
- engine import/export compatibility;
- technical budgets;
- deterministic validation;
- external source/license/attribution inheritance;
- model/tool/runtime version provenance;
- manual Blender/editor edits as explicit provenance steps rather than invisible exceptions.

Technical validators should be deterministic where possible. Models may assist where necessary but do not become technical truth by assertion.

A failed technical derivative should trigger only the smallest necessary repair/decomposition rather than whole-asset regeneration.

**Exit condition:** Origin Forge can prove exactly how the candidate became a production-compatible asset and whether every required technical/provenance gate currently passes.

## Phase 65 — Human Art-Direction Acceptance & Immutable GAME_READY Publication

**Goal:** create the content-specific acceptance boundary that says the technically valid realization is actually wanted in the game.

Art-direction acceptance must remain separate from existing production Task acceptance where those statements mean different things.

Conceptually, `GAME_READY` publication requires an exact current relation such as:

```text
semantic asset identity
+ exact asset specification
+ exact visual-direction revision/hash
+ exact realization lineage
+ current technical validation
+ current provenance/license validation
+ explicit HUMAN_OPERATOR art-direction acceptance
+ engine/runtime compatibility evidence where required
→ immutable GAME_READY publication
```

`GAME_READY` should be an immutable publication/evidence relation with derived currentness, not a mutable boolean/status field that silently survives upstream changes.

Creative workflow outcomes should support at least the concepts:

```text
continue refining
checkpoint / pause
publish game-ready
supersede with a later accepted realization
```

A pause/checkpoint is not failure and must not grant publication authority.

**Exit condition:** the system and creator must both have supplied their respective evidence before an asset is exposed as the current game-ready realization of a semantic content identity.

## Phase 66 — Governed World & Scene Composition Factory

**Goal:** separate “the asset is valid” from “the asset is placed and composed correctly in the world.”

Introduce a world/scene production lane that consumes semantic game-ready assets and produces governed composition evidence for:

- traversal/blockout;
- spatial layout;
- architecture and prop placement;
- lighting composition;
- camera/occlusion requirements;
- encounter/interaction anchors;
- scene dressing;
- semantic runtime bindings;
- scene/cutscene staging where appropriate.

Large world requests such as “build this dungeon/factory area” must decompose through Phase 58 into bounded world, asset, gameplay, lighting, audio, and integration work rather than becoming one giant scene-generation prompt.

World composition should use direct editor manipulation and cheap previews where possible. A correct asset placed badly remains a composition failure rather than an asset-production failure.

Temporal previsualization may be used for a specific scene/cutscene/camera question where justified; it does not restore simulation as a mandatory stage.

**Exit condition:** Origin Forge can assemble current game-ready semantic assets into a governed playable scene while preserving separate asset and composition authority.

---

## 4. Follow-on integrated-production priorities

After the creator-directed 3D/content vertical is proven end to end, the same architectural laws should be extended only where concrete v1.0 gaps remain.

Likely follow-on work includes:

### Cross-media content expansion

Reuse semantic identity, decomposition, queueing, provenance, acceptance, and game-ready publication patterns for:

- 2D source creation and textures;
- animation production;
- audio production;
- image/reference generation;
- other content families required by the representative v1.0 Goal.

Do not force all media through an identical payload schema merely because they share lifecycle concepts.

### Engine/runtime integration

Bind current game-ready semantic content to the target runtime/game project with exact currentness and verification evidence.

### Representative vertical acceptance

Re-run the v1.0 readiness matrix against a real integrated Goal and prove that the system can:

```text
accept high-level creator intent
→ decompose it safely
→ queue bounded production
→ let the creator directly steer subjective content
→ produce and validate real reusable artifacts
→ publish current game-ready content only with explicit human art acceptance
→ compose/integrate it into a playable build
→ surface failures as new bounded work
```

This is a stronger v1.0 target than “one prompt creates a game.”

---

## 5. Factory model

The long-term production organization should be understood as cooperating factories rather than one giant agent:

```text
ENGINEERING FACTORY
bounded code/config/test work

CONTENT FACTORY
visual direction → asset spec → shape/content intent → realization → validation → art acceptance → GAME_READY

WORLD FACTORY
traversal/layout/composition → semantic content binding → playable scene

                ↓
        governed integration
                ↓
          playable build
                ↓
          human evaluation
                ↓
     problems become bounded work
```

The factories share durable governed evidence, semantic identities, decomposition, queueing, resource scheduling, and currentness rules. They do not share a fictional universal “AI builds the game” authority.

---

## 6. Cost-aware execution policy

Local compute latency is expected and should influence routing.

For a bounded question, compare the available trustworthy paths:

```text
cheap preview
bounded direct production
variant exploration
simulation
full production / integration
```

Prefer the lowest-cost path that answers the question sufficiently and preserves the most reusable work.

A checkpoint + small reversible real edit may be cheaper than a simulation of the same edit.

A simulation that prevents an expensive multi-hour or real-world production mistake may be highly valuable.

The policy must remain capability- and evidence-driven rather than hardcoding one permanent cost threshold, because hardware and models will change.

---

## 7. Explicit non-goals of this roadmap

This roadmap does not currently require:

- human/AI authorship percentages or contribution scores;
- a generic “AI-generated” social classification system;
- automatic whole-asset regeneration after every edit;
- one giant apply for all painted changes;
- a universal simulation step;
- simulation removal from the repository;
- one-prompt whole-game generation;
- model self-approval of subjective art;
- browser/editor direct production authority;
- mutable `game_ready=true` truth without immutable evidence;
- a single universal media schema;
- giant autonomous agent swarms;
- automatic queue draining without explicit governed operating policy;
- changing completed historical phases merely to match the new product emphasis.

---

## 8. Product acceptance principles

Future architecture slices should be evaluated against these questions:

1. Can the creator express the intent faster by manipulating the object than by describing it? If yes, prefer direct manipulation.
2. Is the apparent Task actually small enough to execute, validate, retry, and recover independently? If not, decompose it.
3. Can an unaffected region remain untouched? If yes, do not regenerate it.
4. Can several changes be executed as smaller dependency-aware batches? If yes, do not collapse them into one generation.
5. Can the creator queue more intent while local compute runs? If yes, do not block the interactive loop.
6. Does a preview answer the question? If yes, do not simulate it.
7. Does bounded direct production answer the question cheaply and reversibly? If yes, prefer real progress over disposable rehearsal.
8. Does simulation provide information that materially justifies its cost? If not, keep it out.
9. Is a technical PASS being mistaken for artistic acceptance? If yes, stop before game-ready publication.
10. Is provenance being reduced to a subjective human/AI percentage? If yes, preserve facts instead.
11. Can a failure be retried without repeating already accepted work? If not, the work unit or checkpoint boundary is too large.
12. Can the system explain exactly what current evidence makes this realization game-ready? If not, publication is incomplete.

---

## 9. Revised v1.0 interpretation

The representative v1.0 Goal remains useful, but the desired interaction model is now more explicit.

Origin Forge should not attempt to autonomously generate the entire enemy from one prompt and then ask the creator whether the result is acceptable.

Instead it should support a creator-directed production cycle:

```text
high-level Goal
→ governed design/specification
→ recursive decomposition
→ bounded queue
→ engineering/content/world work
→ direct human steering for subjective visual/spatial decisions
→ local AI/tool realization of bounded jobs
→ technical/provenance validation
→ explicit human art-direction acceptance
→ current game-ready publication
→ world/runtime integration
→ playable build
→ human evaluation
→ new bounded corrections
```

For 3D art specifically, the defining interaction should become:

> **The creator shows the desired spatial change; Origin Forge determines the smallest safe production work needed to realize it.**

That is the core product requirement this revised roadmap is intended to preserve.