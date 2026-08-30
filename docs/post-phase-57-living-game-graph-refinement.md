# Origin Forge — Living Game Graph & Cheap-First Observation Refinement

Status: **STRATEGIC ROADMAP REFINEMENT — PLANNING ONLY, NO RUNTIME OR RELEASE AUTHORITY**

Authoritative refinement base:

```text
55bef6896683935a1f93cff6507bf19b2cc7f5b0
```

Companion to:

```text
docs/post-phase-57-creator-directed-production-roadmap.md
```

This document refines the creator-facing and worker-coordination model of the accepted post-Phase-57 roadmap. It does not rewrite completed Phases 0–56, widen frozen Phase-57 authority, reserve a database schema version, mint a durable ID family, add a CLI, authorize browser/editor production, create autonomous acceptance authority, or alter release authority.

The refinement is based on one simple product observation:

> **Origin Forge should provide the structure needed to make any game without prescribing what the game must be.**

The creator should be able to begin with a small game idea. The project structure should then grow with the actual game as concepts, dependencies, assets, systems, scenes, and production work become concrete.

The same structure should also make work easier for one AI model, many specialized models, deterministic tools, local agents, and future worker types without making any worker the durable owner of project truth.

---

## 1. Core product model — the game is a living semantic dependency graph

Origin Forge should represent the evolving game as one durable semantic graph.

At the start, the graph may be nearly trivial:

```text
GAME IDEA
```

A creator might then add only a few concepts:

```text
GAME
├── World
├── Gameplay
└── Style
```

As the game is designed and produced, the graph gains resolution naturally:

```text
GAME
├── World
│   ├── Factory District
│   │   ├── Assembly Hall
│   │   ├── Courtyard
│   │   └── Maintenance Tunnels
│   └── Underground
│
├── Characters
│   ├── Player
│   └── Armored Enemy
│       ├── Visual Design
│       ├── Hammer
│       ├── Behavior
│       ├── Animation
│       └── Audio
│
├── Gameplay
│   ├── Combat
│   ├── Movement
│   └── Loot
│
└── Art Direction
    ├── Shape Language
    ├── Materials
    └── Lighting
```

This is not a required game taxonomy. It is only an example of how one particular game might grow.

A strategy game may grow factions, diplomacy, economy, technologies, regions, armies, logistics, and campaigns. A racing game may grow vehicles, tracks, physics, progression, opponents, audio, and tuning. A puzzle game may grow puzzle rules, levels, interactions, hints, progression, and presentation.

Origin Forge must not require all projects to fit a fixed catalog such as `Quest`, `Enemy`, `Weapon`, `Dialogue`, `Crafting`, or `Level` merely because those concepts are common in some games.

### 1.1 Universal structure, game-specific concepts

Origin Forge should understand a small set of broadly useful relationship semantics such as:

```text
CONTAINS
DEPENDS_ON
REALIZES
USES
BLOCKS
VALIDATES
DERIVES_FROM
SUPERSEDES
```

Exact durable relation names are not frozen by this planning document.

The concepts connected by those relations remain project-specific.

The universal system supplies:

- identity;
- relationships;
- decomposition;
- dependencies;
- currentness;
- bounded execution;
- queueing;
- evidence;
- validation;
- provenance;
- acceptance boundaries;
- recovery;
- capability routing.

The game supplies whatever semantic concepts the creator actually needs.

### 1.2 The structure grows in resolution instead of demanding complexity up front

The creator should not have to define the complete production hierarchy before work begins.

A node may begin as a loose concept:

```text
Armored factory enemy
```

Later it may become:

```text
Armored factory enemy
├── Body realization
├── Armor
├── Hammer
├── Rig
├── Behavior
├── Animation
├── Audio
└── Validation
```

And one branch may become more detailed again:

```text
Armor
├── Torso
├── Shoulders
├── Arms
└── Legs
```

The project therefore scales by adding semantic resolution where the game actually requires it.

> **The structure should emerge from the game rather than forcing the game into a predeclared structure.**

---

## 2. Creator projection — mind-map interaction over a governed graph

The creator-facing representation should be simple enough to behave like a mind map.

The internal durable representation should be a graph because real game development contains cross-dependencies that cannot remain a strict tree.

For example:

```text
Hammer Attack
    ├── depends on → Hammer realization
    ├── depends on → Enemy rig
    ├── depends on → Attack animation
    └── depends on → Damage system
```

The creator should normally see the semantic game structure rather than thousands of production IDs, Run records, hashes, validations, and provenance relations.

Those lower-level records remain authoritative and inspectable but should be progressively disclosed only when useful.

### 2.1 The mind map is a projection, not authority

The creator-facing graph surface may permit operations such as:

- create a concept;
- rename or refine a concept;
- move/reorganize conceptual grouping;
- add or remove semantic relationships;
- request decomposition;
- queue work;
- inspect blockers;
- open the relevant editor or artifact;
- inspect validation/evidence;
- supersede or refine a concept.

However:

> **The visual mind map must not become an authority bypass.**

A drag/drop UI operation, browser mutation, or visual connection cannot silently mint accepted production truth if the underlying operation requires governed validation, human publication, protected currentness checks, or another authority boundary.

### 2.2 Progressive disclosure

The project may eventually contain a very large internal graph while remaining understandable through selective expansion.

Example:

```text
Factory District
```

Expand:

```text
Factory District
├── Assembly Hall
├── Exterior Yard
├── Generator Room
└── Maintenance Tunnel
```

Expand `Assembly Hall`:

```text
Assembly Hall
├── Layout
├── Lighting
├── Props
├── Encounters
└── Audio
```

Only when the creator asks for production detail should the UI expose deeper work, realizations, dependency state, evidence, and provenance.

### 2.3 Simple project state projection

The UI should prefer a small number of understandable states rather than a project-management dashboard full of implementation detail.

Conceptually:

```text
✓ current/accepted
● active/running
○ planned/ready
! attention required
```

Exact symbols, labels, and colors are UX choices and are not frozen here.

The durable state underneath must remain explicit and independently reconstructable.

---

## 3. Recursive decomposition turns the graph into executable work

The semantic graph should connect directly to Phase-58 recursive work decomposition.

A creator may define:

```text
Armored factory enemy
```

Origin Forge may determine that the concept is not one executable job and derive bounded child work such as:

```text
Armored factory enemy
├── body shape
├── armor components
├── hammer
├── rig
├── behavior
├── animation set
└── audio
```

A child may still be too broad and require further decomposition.

For example:

```text
animation set
├── idle
├── locomotion
├── hammer attack
└── stagger
```

Eventually the graph reaches leaves that are sufficiently bounded to execute, validate, retry, and recover independently.

### 3.1 Semantic nodes and executable leaves are different concerns

Not every visible concept must become a Task.

A node may primarily express game meaning or organization. Executable work should be derived only when the concept requires production or change.

This prevents the mind map from degenerating into a giant task tracker.

### 3.2 Parent completion is derived, not asserted by worker success

A parent concept is not complete merely because every child process returned success.

Parent readiness must derive from current accepted child evidence, required integration relations, and relevant validation.

A failed or rejected bounded child should not invalidate accepted sibling work unless a dependency/currentness relation proves that it must.

---

## 4. The graph becomes the natural queue source

Once work is decomposed into small bounded leaves, a large share of production becomes naturally schedulable through Phase 59.

Example:

```text
Armored Enemy
├── Shoulder silhouette  → ready
├── Hammer material      → ready
├── Voice pass           → ready
└── Hammer attack        → blocked by rig + animation dependency
```

Independent work can execute concurrently when resources and policy permit.

Dependent work remains blocked until its exact prerequisites are current.

The creator can continue changing the project or queueing future intent while local workers run.

### 4.1 Change propagation should invalidate narrowly

If a higher-level concept changes, Origin Forge should determine the actual consequence rather than rebuilding everything beneath it automatically.

For example, changing an enemy from a giant armored brute to a smaller fast creature may invalidate body proportions, armor, animation, collision, and combat assumptions while leaving unrelated audio references, project-wide material libraries, or unaffected world assets valid.

The graph should make these consequences explicit.

The governing rule remains:

> **Invalidate and regenerate only what the proven dependency change actually invalidates.**

---

## 5. Worker model — project truth lives outside the workers

The living graph should become the common coordination structure between the creator, Origin Forge infrastructure, AI models, agents, deterministic tools, and human operators.

A worker should not need the whole game conversation merely to perform one bounded operation.

A worker assignment should contain the smallest sufficient context for its node, such as:

```text
Goal:
Refine shoulder armor silhouette

Semantic location:
Armored Enemy → Body → Armor → Shoulders

Exact dependencies:
- current torso proportions
- current armor visual direction
- exact base realization

Must preserve:
- head
- weapon
- lower body
- required rig anchors

Expected output:
one bounded shoulder-shape candidate/realization

Acceptance:
explicit bounded criteria + required validation
```

### 5.1 Smallest sufficient worker context

Origin Forge should prefer the smallest trustworthy context that lets the worker complete its bounded job.

Benefits include:

- lower model context cost;
- lower local inference cost;
- fewer unrelated instructions;
- reduced accidental scope widening;
- easier retries;
- easier model replacement;
- simpler auditing;
- clearer acceptance criteria.

A worker may request additional exact context when the original packet is insufficient, but should not silently absorb the whole project by default.

### 5.2 Workers are replaceable; project state is durable

Origin Forge must not depend on a particular model remembering the project.

Today a work node may route to one model. Tomorrow it may route to another model, an improved local model, a deterministic tool, or a human editor.

The durable graph and evidence preserve:

- what the concept means;
- what it depends on;
- what was attempted;
- what realization is current;
- what validation exists;
- what became stale;
- what requires human authority.

Therefore:

> **AI workers should be disposable; project structure and project truth should not be.**

### 5.3 Multiple models and agents use capability routing, not swarm authority

Different bounded nodes may be routed to different capabilities:

```text
semantic/design model → design/specification work
coding model          → engineering leaves
3D model/toolchain    → bounded asset realization
vision model          → visual observation analysis
audio model/toolchain → audio leaves
deterministic tools   → build/export/validation
human operator        → decisions that remain human authority
```

These are worker roles/capabilities, not autonomous project owners.

The system should not require a giant autonomous agent swarm to coordinate the project.

Workers operate through governed inputs, exact dependencies, bounded outputs, and explicit evidence.

---

## 6. Cheap-first evidence — do not overbuild observation

Origin Forge should use the simplest evidence mechanism that reliably answers the current bounded question.

The default escalation ladder should be conceptually:

```text
single screenshot
→ enough? stop

multiple screenshots / viewpoints
→ enough? stop

short screen capture / video
→ enough? stop

runtime telemetry / deeper instrumentation
→ enough? stop

specialized simulation
→ only if still necessary and justified
```

This refines the existing post-Phase-57 cost-aware policy.

> **Cheapest sufficient evidence first. Escalate only when the cheaper evidence cannot answer the question reliably.**

A floating prop may require one screenshot. An animation glitch may require a short video. A navigation deadlock may require movement history and runtime state. A systemic economy problem may require simulation and no visual capture at all.

The system must not capture or process richer evidence merely because the capability exists.

---

## 7. Governed runtime observer — one simple primitive, multiple uses

A future runtime observation capability should begin with a deliberately small mechanism rather than an elaborate autonomy framework.

Conceptually:

```text
spawn observer
→ move to bounded viewpoint / route
→ capture screenshot or short clip when needed
→ bind capture to exact runtime/project context
→ analyze observation
→ create bounded findings or follow-up work
```

The same substrate can support both scene inspection and playtesting.

### 7.1 Start deterministic

The first useful observer does not need sophisticated exploration intelligence.

A deterministic sequence may be sufficient:

```text
spawn at waypoint A
look north
capture
rotate
capture
move to waypoint B
capture
follow known route
capture only when useful
```

Only add adaptive exploration when fixed viewpoints prove insufficient.

This follows the general rule:

> **Solve the common case with the cheapest reliable mechanism; reserve sophisticated machinery for demonstrated gaps.**

### 7.2 Captured evidence and model interpretation must remain separate

The observer may capture factual evidence such as:

- exact project/build identity;
- scene/runtime identity;
- observer position/orientation;
- relevant game state;
- screenshot hash;
- short capture hash when video is justified;
- timestamp/sequence relation;
- optional telemetry references.

A model may interpret that evidence and propose findings such as:

- possible floating prop;
- broken visual seam;
- route unclear;
- object inaccessible;
- suspicious collision;
- lighting inconsistency;
- missing geometry;
- likely animation defect.

The model interpretation does not become authoritative fact merely because the model reported it.

Where required, findings should be confirmed by deterministic checks, repeated observation, bounded reproduction, or human review before they trigger authoritative production changes.

### 7.3 Observation coverage can remain simple

Origin Forge may later track what parts of a scene or route have actually been observed.

The first implementation does not require a sophisticated uncertainty field.

A simple coverage relation such as visited viewpoints/regions/routes may already answer an important question:

> “Does this area look correct?” is different from “we have not actually looked at this area.”

More advanced uncertainty-driven exploration should be added only when simple coverage is insufficient.

---

## 8. Playtesting is a natural consumer of the observer substrate

The runtime observer should not be limited to visual asset production.

A bounded playtest worker may perform actions in the actual game runtime, capture only the evidence required by the test, and attach findings back to the affected semantic graph nodes.

Possible bounded roles include:

```text
EXPECTED_PLAYER
follows intended progression

EXPLORER
checks reachable/unobserved routes

QA_WALKER
checks obvious collision, door, stair, and seam problems

COMBAT_TESTER
runs one bounded encounter/test case

VISUAL_INSPECTOR
checks representative player-facing viewpoints

STRESS_PLAYER
tries bounded adversarial interactions
```

These are policy/role definitions over the same observation substrate, not necessarily separate AI models.

### 8.1 The real game should be the default evidence source when cheap enough

For many visual, traversal, interaction, and basic playtest questions, running the actual bounded game state and observing it is more useful than building a separate simulated world model.

The normal loop can be:

```text
BUILD
→ OBSERVE
→ IDENTIFY
→ DECOMPOSE
→ FIX
→ VALIDATE
→ OBSERVE AGAIN WHEN NEEDED
```

Simulation remains available for questions whose relevant behavior cannot be answered cheaply by the real bounded runtime, preview, direct execution, telemetry, or rollback.

---

## 9. The graph connects findings back to production

Observation should not produce a generic issue pile disconnected from the game model.

A finding should attach to the most specific known semantic node or relation that it concerns.

Example:

```text
Factory District
└── Assembly Hall
    ├── Wall seam      ← visual finding
    ├── Local lighting ← visual finding
    ├── Prop access    ← playtest finding
    └── Rear section   ← composition finding
```

Those findings may decompose into independent bounded work:

```text
repair wall seam
adjust local light transition
resolve prop collision/accessibility
inspect rear-section composition
```

This makes the same graph useful for design, production, validation, QA, and iteration.

---

## 10. Cross-phase mapping

This refinement should be implemented by extending the already reserved post-Phase-57 phases rather than creating a parallel architecture stack merely because the UI metaphor became clearer.

### Phase 58 — Governed Recursive Work Decomposition

Add the requirement that decomposition may grow from semantic game concepts and should produce bounded executable leaves without forcing every semantic node to become a Task.

The graph must preserve parent/child/dependency lineage and support narrow invalidation when a concept changes.

### Phase 59 — Durable Dependency-Aware Local Work Queue

Treat the bounded leaves of the semantic graph as natural queue candidates.

Queue eligibility must derive from current dependency/evidence state rather than visual position in the mind-map UI.

### Phase 60 — Governed Visual Direction, Semantic Asset Identity & Asset Specification

Generalize the existing semantic asset work into the beginning of a wider semantic game graph without forcing all nodes to be assets.

Preserve game-specific concepts and generic relationship semantics.

Keep source/license provenance attached to the relevant nodes/realizations.

### Phase 61 — Governed Spatial Shape Intent

Spatial intent remains a specialized governed relation against exact realizations. It should attach naturally to semantic asset/world nodes without becoming the universal graph schema.

### Phase 62 — Interactive Preview Editor & Premove Surface

The 3D editor remains one specialized surface opened from relevant graph nodes.

The broader creator-facing project graph/mind-map projection should share the same premove principle: the creator may define and queue future intent while expensive workers remain busy.

This refinement does not require Phase 62 to become one giant universal editor.

### Phase 63–65 — Realization, validation, and publication

Candidate realizations, technical validation, human art-direction acceptance, and immutable `GAME_READY` publication remain attached to the semantic identities they realize.

The mind-map projection may display their state but cannot mint their authority.

### Phase 66 — Governed World & Scene Composition Factory

World/scene nodes should become natural consumers of both the living graph and the runtime observer.

Scene inspection, simple visual coverage, traversal checks, and bounded playtests should prefer screenshot-first or otherwise cheapest-sufficient evidence before escalating to video, telemetry, or simulation.

---

## 11. Product laws added by this refinement

Future architecture should preserve these additional laws:

1. **Origin Forge provides universal production structure without prescribing the game taxonomy.**
2. **The game begins simple and the semantic graph grows in resolution only where needed.**
3. **The creator-facing mind map is a projection of the governed graph, not production authority.**
4. **Not every semantic node is a Task; executable work is derived only when production/change is required.**
5. **Decomposition should continue until leaves are small enough to execute, validate, retry, and recover independently.**
6. **Small bounded leaves are the natural unit for queueing and worker assignment.**
7. **Workers receive the smallest sufficient exact context rather than the whole project by default.**
8. **Workers are replaceable; durable project truth remains outside model memory.**
9. **Multiple models/agents coordinate through the governed graph and capability routing, not swarm ownership.**
10. **Changes invalidate only proven downstream dependencies.**
11. **Use the cheapest sufficient evidence first.**
12. **A screenshot should be preferred when a screenshot is enough; video should be used only when temporal evidence is required.**
13. **Runtime observation should start deterministic and simple; add adaptive autonomy only for demonstrated gaps.**
14. **Captured evidence is distinct from model interpretation of that evidence.**
15. **Playtest findings should attach back to semantic game nodes and become bounded follow-up work.**
16. **The actual game/runtime is the preferred test surface when it can answer the bounded question cheaply and reliably.**

---

## 12. Explicit non-goals

This refinement does not require:

- a fixed genre-specific game ontology;
- a universal list of game systems every project must implement;
- every concept becoming a durable Task immediately;
- showing all provenance, Run, Artifact, and verification nodes in the creator UI;
- a giant project-management dashboard;
- one AI model holding the entire project in context;
- permanent assignment of project areas to one specific model;
- a giant autonomous multi-agent swarm;
- video capture for every observation;
- advanced active-learning camera planning before simple viewpoints have proven insufficient;
- full-world uncertainty fields as a prerequisite for useful observation;
- simulation for ordinary visual inspection or basic playtesting;
- automatic model acceptance of visual findings;
- browser/UI authority over technical validation, art acceptance, or publication.

---

## 13. Revised creator/worker loop

The combined post-Phase-57 direction can now be summarized as:

```text
small game idea
→ living semantic game graph
→ creator adds/refines concepts and relationships
→ Origin Forge derives dependencies and required production work
→ recursive decomposition into bounded leaves
→ dependency-aware queue
→ capability-routed models / tools / humans
→ bounded realizations and integration
→ cheapest-sufficient validation / observation
→ findings attach back to semantic nodes
→ narrow correction work
→ accepted current project state
→ graph grows only as the game requires
```

For the creator, the system should feel like a game idea becoming more concrete rather than like administering an AI workforce.

For workers, the same project becomes a set of small exact jobs with explicit dependencies and bounded context.

For Origin Forge infrastructure, the graph provides the durable coordination backbone connecting intent, decomposition, queueing, production, observation, validation, provenance, currentness, and human authority.

The resulting product principle is:

> **Origin Forge should let the creator shape a living model of the game while the system turns that evolving structure into the smallest safe production work needed to make it real.**
