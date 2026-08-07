# Phase 1 Runtime Notes

Status: **Completion candidate — pending final CI/review**

Phase 1 establishes the first executable Origin Forge substrate without any LLM integration. Its purpose is to prove that project truth, long-running work, recovery, verification, and causal history can exist independently of model conversation state.

## Implemented

### Durable control state

- Python package and CLI entry point
- SQLite durable state
- ordered schema migrations
- tested schema v1 → v2 upgrade
- typed infrastructure IDs
- Goal / Flow / Task state machines
- optimistic revision checks
- append-only state-event journal
- restart-safe state persistence

### Goal / Flow / Task semantics

- Goal / Flow / Task creation and inspection
- explicit Goal lifecycle
- Task success requires passing Verification
- Goal success requires:
  - completed/cancelled Flows
  - explicit passing Goal Verification
- same-Flow parent/child Task invariant
- parent Task completion blocked while child work remains active
- Flow completion blocked while active/failed work remains unresolved

### Run lifecycle and recovery

- explicit Run lifecycle
- Task attempt accounting
- one active Run lease per Task
- Run assignment cleared on normal completion
- recovery inspection for interrupted `RUNNING` Flow/Task/Run records
- idempotent recovery reconciliation:
  - interrupted Run → `INTERRUPTED`
  - running Task → `BLOCKED` with revision increment
  - running Flow → `BLOCKED` with revision increment
- Run assignment cleared during interruption recovery
- mixed-state recovery safety:
  - already-terminal Runs are not rewritten
  - already-blocked Tasks remain blocked while orphaned Runs are interrupted

### Runtime/API boundary

`OriginForgeStore` owns persistence mechanics.

`OriginForgeRuntime` is the application-service boundary for execution state and cross-record invariants.

```text
CLI / future Manager
        ↓
OriginForgeRuntime
        ↓
OriginForgeStore
        ↓
SQLite
```

Future agent code should not use arbitrary SQL as its effective API.

### Verification

- Verification records
- Runtime Verification APIs for Goal / Flow / Task / Run
- Verification listing
- machine-readable CLI operations for recording/inspecting Verification

### Causal lineage

`OriginForgeLineage` is a separate service for provenance-oriented records:

```text
Decision
   ↓
Change
   ↓
Artifact
   ↓
Verification
```

Implemented:

- Decisions linked to Project / Goal / Task
- Decision Goal/Task consistency checks
- Changes linked to Task / Decision / Run
- Run/Task consistency checks for Changes
- Artifacts linked to Project / Change / parent Artifact / Run
- automatic SHA-256 hashing of existing local Artifact files
- local Artifact paths cannot escape the project root
- Artifact Verification
- state events for Decision / Change / Artifact creation

This is the initial substrate for future questions such as:

> Why does this exist?

and for later cryptographic provenance/company-signature work.

### Project configuration

`origin-forge init` creates:

```text
.origin-forge/config.toml
```

Current configuration includes:

- policy profile
- maximum strategy retries
- maximum verification failures
- project-approved build commands
- project-approved test commands

The command lists are only configuration at this phase; actual shell/tool policy enforcement belongs to the safe-execution/tool phases.

### CLI

Current core CLI includes:

```text
origin-forge init
origin-forge status
origin-forge recover [--apply]

origin-forge goal create|list|show|transition
origin-forge flow create|list|show|transition
origin-forge task create|list|show|transition
origin-forge run start|list|show|finish
origin-forge verify record|list
```

CLI failures use structured JSON error classes and stable non-zero categories for automation instead of raw tracebacks for expected runtime errors.

### CI

GitHub Actions executes the unit-test suite on:

- Python 3.12
- Python 3.13

with `ResourceWarning` promoted to an error.

## Local validation

Command:

```text
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Current result:

```text
Ran 27 tests
OK
```

The suite covers:

1. typed unique IDs
2. idempotent project initialization
3. Flow transitions/event journaling
4. stale revision rejection
5. terminal-state enforcement
6. Verification-gated Task success
7. repeatable recovery inspection
8. Run lifecycle/attempt accounting
9. idempotent interruption recovery
10. foreign-key enforcement
11. durable state after reopen
12. configuration bootstrap/load
13. same-Flow parent/child enforcement
14. parent completion dependency enforcement
15. Flow completion dependency enforcement
16. Goal completion + Goal Verification
17. one-active-Run leasing
18. Run assignment cleanup
19. list/query Runtime APIs
20. Runtime Verification APIs
21. structured CLI error behavior
22. CLI Goal round-trip
23. schema v1 → v2 migration
24. Decision→Change→Artifact lineage
25. Artifact SHA-256 hashing and Verification
26. project-root Artifact path containment
27. mixed/partially-terminal recovery safety

## Phase 1 exit-condition assessment

The roadmap required Phase 1 to provide persistent structured state, migrations, revisioned mutation, restart recovery, and the durable objects needed before model execution.

This branch now provides those requirements plus the initial causal lineage service.

No LLM call is required to use or validate any Phase-1 behavior.

## Intentionally deferred

These belong to later phases rather than blocking Phase 1:

- shell/tool permission enforcement
- Git worktree isolation/checkpoints
- Manager / Executor / Auditor orchestration
- local model integration
- LSP / Tree-sitter / repository context selection
- Skills
- Tool Search
- model/resource scheduling
- Project Entity graph / Design Bible
- cryptographic signatures and company root keys
- media-specific watermarking
- Pixelorama / Blockbench / image / audio integrations

## Next phase

After this branch passes final CI/review, the next implementation phase is **Phase 2 — Basic Local Coding Agent**, but model access should still be deliberately narrow: one bounded Task, controlled repository reads, controlled patch output, and no broad autonomy yet.
