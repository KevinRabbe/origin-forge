# Phase 17 — Project Intelligence

Status: **implementation starting after Phase 16**

Phase 17 gives Origin Forge a durable semantic model of the product it is building. The goal is not to add more conversational memory or another model-facing retrieval trick. The goal is to make project structure, cross-media relationships, design rules, and change impact explicit, queryable, versioned project truth.

The central distinction is:

```text
files and artifacts = implementation evidence
entities and rules   = semantic project structure
```

A feature such as a Stone Golem should be representable as one stable Entity linked to gameplay code, tests, models, textures, animations, audio, loot configuration, Decisions, and Design Rules without requiring a model to rediscover those relationships from filenames on every Task.

---

## 1. Architectural goal

Current Origin Forge already owns durable operational truth:

```text
Project
→ Goal / Flow / Task / Run
→ Decision / Change / Artifact / Verification
```

Phase 17 adds a semantic project layer in the **same protected SQLite database**:

```text
Project
  ↓
Entity ── EntityRelation ── Entity
  │
  ├── EntityBinding ── durable record / file / symbol / artifact
  │
  └── scoped DesignRule

changed Entity / binding / rule
        ↓
deterministic bounded impact analysis
        ↓
affected Entities + bindings + Design Rules + evidence
```

This semantic layer is infrastructure-owned. It is not an LLM-owned knowledge graph and not a vector database.

---

## 2. Fundamental rules

1. **One truth store.**
   Entity graph and Design Bible state live in the existing project database and use the existing migration, project-scoping, revision, and event-journal patterns.

2. **Models do not own semantic truth.**
   Models may later propose Entity/Relation/Rule candidates. They do not directly create, rewrite, retire, or supersede canonical project intelligence.

3. **Stable semantic identity.**
   An Entity keeps one infrastructure-owned ID even if its implementation moves between files or media.

4. **Bindings are evidence, not identity.**
   A source file, symbol, Artifact, test, or asset can move or be replaced without changing the semantic Entity it implements.

5. **Relations are typed and directional.**
   `DEPENDS_ON`, `IMPLEMENTS`, `TESTS`, and `CONTAINS` are not interchangeable generic links.

6. **Design rules are governed authority.**
   Design Bible rules are explicit structured project constraints/principles. Semantic rule changes use supersession rather than silent text replacement.

7. **Impact analysis is deterministic.**
   Graph traversal uses explicit relation semantics, stable ordering, cycle handling, and hard depth/node/output budgets. No model is required to determine reachability.

8. **Derived discovery never silently promotes itself.**
   AST/LSP/file-name/model inference may suggest candidate bindings or relations later, but canonical graph mutation requires an explicit governed path.

9. **Historical meaning remains inspectable.**
   Retired relations/bindings/rules remain queryable rather than being physically erased.

10. **No graph explosion.**
    Phase 17 is a bounded semantic layer, not a complete RDF ontology or exhaustive symbol graph.

---

## 3. Core objects

### 3.1 Entity

An Entity is a stable semantic thing in the product/project.

Initial fields:

```text
Entity
- id
- project_id
- kind
- name
- description
- status
- revision
- metadata_json
- created_at
- updated_at
```

Initial kinds should cover software and future media without becoming game-specific:

```text
FEATURE
SYSTEM
COMPONENT
CODE_SYMBOL
TEST
CONFIG
DATA
ASSET
IMAGE
MODEL
AUDIO
UI
SCENE
DOCUMENT
OTHER
```

Initial statuses:

```text
ACTIVE
DEPRECATED
RETIRED
```

Entity identity may outlive any one implementation binding.

Example:

```text
ENTITY-...
kind: FEATURE
name: Stone Golem
```

---

### 3.2 EntityRelation

A typed directed semantic edge between two Entities.

```text
EntityRelation
- id
- project_id
- source_entity_id
- relation_type
- target_entity_id
- status
- revision
- rationale
- evidence_refs_json
- created_at
- updated_at
```

Initial relation types:

```text
CONTAINS
DEPENDS_ON
IMPLEMENTS
TESTS
CONFIGURES
USES
PRODUCES
CONSUMES
REFERENCES
DERIVED_FROM
AFFECTS
```

Direction is part of the contract.

Examples:

```text
combat-system DEPENDS_ON damage-system
stone-golem IMPLEMENTS enemy-archetype
stone-golem TESTS?                 # invalid direction for this meaning
stone-golem-test TESTS stone-golem # valid
```

A relation cannot cross project boundaries.

Semantic duplicates such as the same active `(source, type, target)` edge are rejected.

Cycles are allowed where the domain permits them, but traversal is cycle-safe and bounded.

---

### 3.3 EntityBinding

Bindings connect a semantic Entity to concrete project evidence.

```text
EntityBinding
- id
- project_id
- entity_id
- binding_type
- target_ref
- target_hash
- metadata_json
- status
- revision
- created_at
- updated_at
```

Initial binding types:

```text
ARTIFACT
DECISION
TASK
VERIFICATION
FILE
SYMBOL
EXTERNAL_REF
```

Examples:

```text
Stone Golem → FILE src/enemies/stone_golem.py
Stone Golem → SYMBOL stone_golem.StoneGolem
Stone Golem → ARTIFACT ART-...
Stone Golem → DECISION DEC-...
Stone Golem → VERIFICATION VERIFY-...
```

For durable Origin Forge IDs, project ownership must be validated.

For file/symbol bindings, a hash may pin the known implementation snapshot. A later mismatch is reported as staleness; it is never silently rewritten.

Bindings are not a replacement for Artifact provenance. They are semantic pointers into that evidence.

---

### 3.4 DesignRule

The Design Bible becomes structured governed project state rather than one unstructured prompt document.

```text
DesignRule
- id
- project_id
- category
- title
- statement
- rationale
- authority
- scope_entity_ids_json
- status
- revision
- supersedes_rule_id
- created_at
- updated_at
```

Initial categories:

```text
VISUAL
GAMEPLAY
TECHNICAL
PERFORMANCE
AUDIO
UI
WORLD
NAMING
ACCESSIBILITY
PROCESS
OTHER
```

Initial authority levels:

```text
HARD_CONSTRAINT
PRINCIPLE
CONVENTION
TARGET
```

Initial statuses:

```text
ACTIVE
SUPERSEDED
RETIRED
```

A rule statement is not silently edited after it becomes authoritative. Meaningful semantic change creates a new rule that supersedes the prior rule. The previous rule remains historical evidence.

A model cannot lower a rule's authority or supersede it on its own.

---

## 4. Authority model

Phase 17 distinguishes three classes of project intelligence:

### Canonical

- accepted Entity identity/metadata
- accepted typed Entity relations
- accepted Entity bindings
- accepted Design Rules

These require an infrastructure/operator/governance write path.

### Derived deterministic

- reverse adjacency indexes
- impact traversal results
- stale-binding observations
- counts/search indexes/caches reconstructed from canonical state

These may be rebuilt automatically because they are derivable.

### Proposed

- model-suggested Entity candidates
- inferred relations
- inferred Design Rule changes
- suggested stale-binding repairs

These are evidence only and must enter a later governed acceptance path.

---

## 5. Project scoping

Every canonical Phase-17 object is project-scoped.

Required invariants:

- Entity belongs to exactly one project
- relation source/target belong to the same project as the relation
- binding Entity belongs to the binding project
- durable-ID binding targets must resolve to the same project
- Design Rule scopes may reference only Entities in the same project
- superseded Design Rule must belong to the same project

No lookup may accidentally return an object owned by another project database/project row.

---

## 6. Revision and history semantics

Entity, Relation, Binding, and Design Rule records use optimistic revisions where state can transition.

Expected behavior:

```text
read revision N
→ attempt state/metadata transition with expected_revision=N
→ success creates revision N+1 + state event
→ concurrent change fails with StaleRevision
```

No destructive delete API is required in Phase 17.

Relations and bindings become `RETIRED` rather than being removed.

Design Rules use supersession for semantic changes.

---

## 7. Event journal

Phase-17 canonical changes append normal `state_events` entries.

Examples:

```text
ENTITY_CREATED
ENTITY_UPDATED
ENTITY_STATUS_CHANGED
ENTITY_RELATION_CREATED
ENTITY_RELATION_RETIRED
ENTITY_BINDING_CREATED
ENTITY_BINDING_RETIRED
DESIGN_RULE_CREATED
DESIGN_RULE_SUPERSEDED
DESIGN_RULE_RETIRED
```

The event journal remains causal operational history; it is not the primary graph query store.

---

## 8. Deterministic impact analysis

Impact analysis answers questions such as:

> If this Entity changes or disappears, what known semantic project surface may be affected?

Input:

```text
ImpactQuery
- root_entity_ids[]
- relation_types[]
- direction
- max_depth
- max_entities
- include_bindings
- include_design_rules
```

Initial directions:

```text
OUTBOUND
INBOUND
BOTH
```

Typical dependency-impact query uses **INBOUND `DEPENDS_ON` traversal**:

```text
changed damage-system
← entities that DEPEND_ON damage-system
← entities that depend on those entities
```

Output:

```text
ImpactReport
- roots[]
- visited Entities with minimum depth
- traversed relation IDs
- relevant bindings
- relevant Design Rules
- cycle/limit flags
- deterministic content hash
```

The report is evidence, not permission to mutate every impacted object.

---

## 9. Traversal rules

Impact traversal must:

- validate every root Entity
- use only ACTIVE relations unless explicitly requested otherwise
- sort adjacency deterministically by relation type, target/source ID, relation ID
- track visited Entity IDs
- report but not recurse forever on cycles
- enforce depth before expansion
- enforce Entity/relation/output budgets incrementally
- never fall back to “all project Entities” when no relation matches

Default limits should be conservative.

Example v0 defaults:

```text
max_depth: 4
max_entities: 256
max_relations: 1024
max_bindings: 1024
max_rules: 256
```

---

## 10. Design Rule scoping

A Design Rule may be:

- global: empty scope means project-wide
- scoped: applies to one or more Entities

When producing impact/context evidence, relevant rules are:

1. all ACTIVE global rules
2. ACTIVE rules scoped directly to any visited Entity

No model decides whether a HARD_CONSTRAINT applies after that relationship is explicit.

Later phases may add hierarchical scope inheritance through `CONTAINS`, but v0 should not invent implicit inheritance rules without tests.

---

## 11. Context integration

Phase 17 should not immediately rewrite the current context selector.

First prove project intelligence independently through read-only queries and tests.

Later controlled integration may add:

```text
Task terms / selected Entity IDs
→ semantic Entity query
→ bounded relevant bindings + Design Rules
→ existing WorkspaceContextSelector
```

The model receives a bounded semantic package, not unrestricted graph traversal authority.

---

## 12. Relationship to code intelligence

Phase 10/11 structural/LSP intelligence and Phase 17 Project Intelligence solve different problems.

```text
AST/LSP graph:
what code symbol references what right now?

Project Entity graph:
what product concept is this implementation part of, and what else is semantically related?
```

AST/LSP may later produce binding/relation candidates, but canonical semantic links are not auto-created merely because one symbol references another.

---

## 13. Relationship to Dream and Reviewer

Dream Cycle may later identify repeated missing/stale semantic links and emit Project-Intelligence candidates.

Reviewer may inspect relevant Entity/Rule evidence and report inconsistencies.

Neither may directly mutate canonical Entities, Relations, Bindings, or Design Rules.

---

## 14. Security and containment

Project Intelligence introduces no new arbitrary filesystem, shell, network, or merge authority.

Rules:

- no executable content in graph metadata
- bounded JSON metadata only
- file/symbol bindings use portable contained project paths
- protected `.origin-forge` paths cannot become normal source bindings
- external refs are inert strings/identifiers, not automatically fetched/executed URLs
- Design Rule text is data, never executable instruction authority outside its explicit semantic category/authority field
- model text cannot create canonical graph rows through the model adapter

---

## 15. First implementation slice

Phase 17 v0 should proceed in this order:

1. add Phase-17 IDs/enums/models
2. schema migration for Entities, Relations, Bindings, Design Rules
3. project-scoped runtime/store CRUD with optimistic revisions
4. no-delete retirement/supersession transitions
5. deterministic graph query service
6. bounded impact analysis
7. read-only project-intelligence CLI
8. stale file-binding inspection
9. Design Rule query/scoping
10. tests for project isolation, revision races, graph cycles, deterministic traversal, budgets, stale bindings, rule supersession, and absence of model mutation authority

Do not integrate Project Intelligence into automatic model context until this substrate is independently green.

---

## 16. Initial database shape

A migration should add tables conceptually equivalent to:

```sql
entities(
  id PRIMARY KEY,
  project_id FK,
  kind,
  name,
  description,
  status,
  revision,
  metadata_json,
  created_at,
  updated_at
)

entity_relations(
  id PRIMARY KEY,
  project_id FK,
  source_entity_id FK,
  relation_type,
  target_entity_id FK,
  status,
  revision,
  rationale,
  evidence_refs_json,
  created_at,
  updated_at
)

entity_bindings(
  id PRIMARY KEY,
  project_id FK,
  entity_id FK,
  binding_type,
  target_ref,
  target_hash,
  metadata_json,
  status,
  revision,
  created_at,
  updated_at
)

design_rules(
  id PRIMARY KEY,
  project_id FK,
  category,
  title,
  statement,
  rationale,
  authority,
  scope_entity_ids_json,
  status,
  revision,
  supersedes_rule_id FK,
  created_at,
  updated_at
)
```

Useful indexes should support:

- Entities by project/kind/status/name
- inbound and outbound active relations
- bindings by Entity/type/status
- active Design Rules by project/category

A partial unique index should prevent duplicate ACTIVE `(project, source, relation_type, target)` relations.

---

## 17. Acceptance tests

### Entity identity

- stable infrastructure-owned Entity IDs
- same Entity may change name/metadata without changing ID
- stale expected revision fails
- retired Entity remains readable

### Relation integrity

- cross-project edges are impossible
- duplicate active semantic edge is rejected
- self-edge policy is explicit and tested
- retired edge remains readable but is excluded from default traversal

### Binding integrity

- durable-ID binding target ownership is validated
- file binding rejects protected/non-portable paths
- target hash drift is observable as stale evidence, not silently updated
- retiring a binding does not erase history

### Design Bible

- global and scoped rules are queryable deterministically
- scoped Entity must belong to the same project
- semantic change creates a superseding rule
- old rule remains readable
- model-facing components expose no direct rule mutation authority

### Impact analysis

- inbound dependency traversal identifies known dependents
- traversal order is deterministic
- cycles terminate safely
- depth/entity/relation/binding/rule limits fail closed or mark truncation explicitly
- unrelated Entities are never included as fallback
- report content hash changes when graph/rule/binding evidence changes

### Persistence and recovery

- migration upgrades existing Phase-16 databases without data loss
- all canonical Phase-17 records survive reopen/restart
- event journal records governed changes

### Authority

- deterministic graph service performs no source mutation
- no model adapter directly writes canonical project intelligence
- impact report cannot change Task/Entity/Rule status
- context integration remains disabled until separately benchmarked

---

## 18. Exit condition

Phase 17 exits when:

> Origin Forge can represent stable product/project Entities, their typed cross-media relationships and concrete implementation bindings, enforce/query structured Design Bible rules, and deterministically identify bounded change impact across that semantic graph without relying on a model to rediscover project meaning or granting model-generated graph claims canonical authority.

The resulting architecture is:

```text
canonical project records
+ semantic Entities
+ typed relationships
+ implementation bindings
+ governed Design Rules
        ↓
deterministic project intelligence
        ↓
bounded context / impact / review evidence
```
