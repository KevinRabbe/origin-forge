# Origin Forge Core Model

Status: **Phase 0 baseline**

This document defines the persistent objects that make up Origin Forge's canonical state.

## 1. Object hierarchy

```text
Company
  ↓
Product
  ↓
Project
  ↓
Goal
  ↓
Flow
  ↓
Entity
  ↓
Task
  ↓
Decision
  ↓
Change
  ↓
Artifact
  ↓
Verification
```

The arrows indicate the normal production relationship, not strict ownership in every case. Objects may reference each other many-to-many where required.

## 2. Stable identifiers

Recommended prefixes:

```text
COMPANY-...
PROD-...
PROJECT-...
GOAL-...
FLOW-...
ENTITY-...
TASK-...
DEC-...
CHG-...
ART-...
VERIFY-...
RUN-...
SKILL-...
TOOL-...
MODEL-...
```

IDs are opaque stable identifiers. Human-readable names are metadata and may change without changing identity.

Sequential display numbers may be used for readability, but internal identity should eventually use collision-resistant IDs such as UUIDv7/ULID or an equivalent ordered identifier.

## 3. Company

Represents the permanent maker/root identity above all products.

Minimum fields:

```text
id
name
created_at
root_public_identity
status
metadata
```

The company root private signing material must never be exposed to models.

## 4. Product

Represents a distinct product or product family.

```text
id
company_id
name
description
status
created_at
updated_at
```

Examples could include a game, developer tool, or other future software product.

## 5. Project

Represents one working repository/workspace under a Product.

```text
id
product_id
name
repository_uri
workspace_path
default_branch
status
created_at
updated_at
```

A Product may contain multiple Projects.

## 6. Goal

Defines what success means before execution begins.

```text
id
project_id
objective
success_criteria
constraints
budgets
priority
status
created_by
created_at
updated_at
```

Example:

```text
GOAL-0184
Objective: Create a playable Stone Golem enemy.

Success criteria:
- spawns correctly
- navigation works
- attacks player
- damage works
- attack is readable
- death works
- loot works
- required assets valid
- build passes
- integration tests pass
```

A Goal may not be silently redefined by an Executor.

## 7. Flow

Represents durable multi-step work for a Goal.

```text
id
goal_id
status
revision
controller
state_json
blocked_reason
created_at
updated_at
```

Recommended statuses:

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

Every mutation increments `revision`. Writers should use optimistic concurrency checks to prevent stale state from overwriting newer state.

## 8. Entity

Represents a logical product concept independent of its file representation.

Examples:

```text
Stone Golem
Iron Sword
Inventory System
Ancient Factory Biome
Main Menu
Crafting Recipe
```

Minimum fields:

```text
id
project_id
type
name
description
status
metadata
created_at
updated_at
```

Entity relationships are edges in the project graph.

Example:

```text
Stone Golem
├── implemented_by → StoneGolem.cs
├── visual → stone_golem.bbmodel
├── texture → stone_golem.png
├── drops → StoneCore
└── governed_by → DEC-0041
```

## 9. Task

Represents one bounded unit of execution.

```text
id
flow_id
parent_task_id
objective
acceptance_criteria
constraints
required_capabilities
budget
priority
status
attempt_count
assigned_run_id
created_at
updated_at
```

A Task should be small enough that an Executor can work on it with a fresh bounded context.

Task state should not depend on an LLM conversation object.

## 10. Decision

Records why the project intentionally chose something.

```text
id
project_id
goal_id
task_id
title
context
decision
rationale
alternatives
status
created_by
created_at
supersedes_decision_id
```

Decisions answer:

> Why does the project work this way?

Example:

```text
DEC-0041
Decision: Stone Golem attack windup must be >= 300 ms.
Rationale: Earlier runtime tests showed insufficient reaction time.
```

## 11. Change

Represents a concrete mutation made to the project.

```text
id
task_id
decision_id
run_id
summary
change_type
before_ref
after_ref
status
created_at
```

Changes connect intent to artifacts and allow fine-grained provenance.

## 12. Artifact

Represents a produced or modified object.

Artifact types may include:

```text
source_code
configuration
image
pixel_art
texture
3d_model
animation
audio
music
speech
binary
build
report
simulation_result
```

Minimum fields:

```text
id
project_id
entity_id
change_id
type
path_or_uri
content_hash
parent_artifact_id
created_by_run_id
model_id
skill_versions
tool_versions
status
created_at
```

An Artifact's identity is distinct from its current filename/path.

## 13. Verification

Represents objective evidence about a Goal, Task, Change, or Artifact.

```text
id
target_type
target_id
verification_type
verifier
status
evidence
metrics
run_id
created_at
```

Recommended statuses:

```text
PASS
FAIL
INCONCLUSIVE
SKIPPED
BLOCKED
```

Verification examples:

```text
compiler result
unit-test suite
integration test
LSP diagnostics
asset validator
visual audit
audio validator
runtime smoke test
playtest metric
```

A model statement such as "the feature works" is not a Verification record unless backed by an accepted verifier.

## 14. Run

A Run represents one execution attempt by a model, deterministic tool workflow, agent role, or verifier.

```text
id
task_id
role
model_profile
model_hash
skills
allowed_tools
started_at
ended_at
status
input_token_count
output_token_count
resource_metrics
failure_reason
```

Runs provide observability without making raw model history part of canonical project truth.

## 15. Skill

A Skill is versioned procedural knowledge.

```text
id
name
version
description
content_hash
required_tools
required_capabilities
permissions
dependencies
verification_rules
status
publisher_identity
signature
```

Skills are immutable by version. Improvement creates a new version rather than mutating historical behavior.

## 16. Tool

A Tool is a versioned executable capability.

```text
id
name
version
description
input_schema
output_schema
permissions
side_effects
deterministic
reversible
resource_requirements
verifier
publisher_identity
content_hash
signature
```

## 17. Model profile

A Model profile describes observed behavior rather than hardcoding architectural assumptions.

```text
id
name
runtime
model_hash
quantization
capabilities
context_limit
recommended_context
vram_requirement
ram_requirement
measured_tokens_per_second
benchmark_results
preferred_task_classes
status
```

## 18. Provenance links

The normal lineage is:

```text
Goal
→ Flow
→ Task
→ Run
→ Decision
→ Change
→ Artifact
→ Verification
```

This should allow Origin Forge to answer questions such as:

- Who or what created this artifact?
- Why does this line/value/asset exist?
- Which task introduced it?
- Which skill version was used?
- Which model/tool versions participated?
- What verified it?
- What did it replace?
- Which other Entities depend on it?

## 19. State authority

Canonical state must live in structured storage, initially SQLite.

The model may read authorized views of state and propose mutations through APIs. It does not receive direct unrestricted database write access.

## 20. Initial schema discipline

Phase 0 should define schemas before implementation, but avoid premature over-normalization. The initial database should favor:

- explicit foreign keys
- append-friendly history
- immutable IDs
- timestamped state transitions
- revision counters on mutable durable flows
- JSON metadata only where the structure is genuinely variable

The schema may evolve, but the semantic meanings defined in this document should remain stable unless changed through an explicit architecture decision.
