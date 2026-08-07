# Phase 1 Runtime Notes

The initial durable runtime branch establishes the first executable Origin Forge substrate without any LLM integration.

## Implemented

- Python package and CLI entry point
- SQLite schema version 1
- migration bootstrap
- typed infrastructure IDs
- Flow and Task state machines
- optimistic revision checks
- append-only state-event journal
- Goal / Flow / Task creation
- verification records
- Task success gated on passing Verification
- explicit Run lifecycle with attempt accounting
- recovery inspection for interrupted `RUNNING` Flow/Task/Run records
- idempotent recovery reconciliation:
  - interrupted Run → `INTERRUPTED`
  - running Task → `BLOCKED` with revision increment
  - running Flow → `BLOCKED` with revision increment
- `OriginForgeRuntime` application-service boundary above raw persistence
- project-local `.origin-forge/config.toml` bootstrap and validation
- project ownership checks for Goal / Flow / Task / Run access
- same-Flow parent/child Task invariant
- parent Task completion blocked while child work remains active
- Flow completion blocked while active/failed work remains unresolved
- CLI operations for Goal / Flow / Task / Run creation, inspection, and transitions
- status summary including active policy/retry configuration
- local runtime database isolation under `.origin-forge/`
- GitHub Actions test matrix for Python 3.12 and 3.13

## Validation performed before publishing the latest branch state

```text
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Result:

```text
Ran 16 tests
OK
```

The suite currently verifies:

1. typed unique infrastructure IDs
2. idempotent project initialization
3. Flow transitions and event journaling
4. stale revision rejection
5. terminal-state transition enforcement
6. Verification-gated Task success
7. repeatable recovery inspection
8. Run lifecycle and Task attempt accounting
9. idempotent interrupted-run reconciliation
10. SQLite foreign-key enforcement
11. durable state after database reopen
12. project configuration bootstrap/load
13. same-Flow parent/child enforcement
14. parent completion blocked by incomplete children
15. Flow completion blocked by incomplete Tasks
16. CLI Goal create/show round-trip

A CLI smoke path now includes:

```text
origin-forge --project-root <project> init --name demo
origin-forge --project-root <project> status

origin-forge --project-root <project> goal create "Build feature" \
  --success "tests pass"
origin-forge --project-root <project> goal list
origin-forge --project-root <project> goal show <GOAL-ID>

origin-forge --project-root <project> flow create <GOAL-ID>
origin-forge --project-root <project> flow show <FLOW-ID>
origin-forge --project-root <project> flow transition <FLOW-ID> RUNNING --revision 0

origin-forge --project-root <project> task create <FLOW-ID> "Implement bounded work"
origin-forge --project-root <project> task show <TASK-ID>
origin-forge --project-root <project> task transition <TASK-ID> READY --revision 0

origin-forge --project-root <project> run start <TASK-ID> --role EXECUTOR
origin-forge --project-root <project> run show <RUN-ID>
origin-forge --project-root <project> run finish <RUN-ID> SUCCEEDED

origin-forge --project-root <project> recover
origin-forge --project-root <project> recover --apply
```

`recover` without `--apply` is inspection-only. `recover --apply` reconciles stale `RUNNING` records conservatively rather than assuming they succeeded.

## Architectural boundary introduced in this slice

`OriginForgeStore` is the persistence mechanism. It owns SQLite mechanics, row-level state transitions, optimistic revisions, and the event journal.

`OriginForgeRuntime` is now the application-service boundary. It owns cross-record/project invariants and is the layer future Managers, schedulers, and user interfaces should call.

Conceptually:

```text
CLI / future Manager
        ↓
OriginForgeRuntime
        ↓
OriginForgeStore
        ↓
SQLite
```

This prevents future agent code from turning raw database access into the effective API.

## Remaining Phase 1 work

The durable substrate is now substantial, but Phase 1 should still harden it before model integration:

- richer list/status queries for Flows, Tasks, and Runs
- explicit Verification CLI/API through the Runtime boundary instead of test-only Store access
- Goal completion semantics tied to Flow/Verification evidence
- stronger Run/Task assignment invariants
- recovery tests around mixed and partially terminal state
- migration organization that remains maintainable beyond schema version 1
- configuration for project-approved build/test commands without embedding shell policy in model prompts
- additional database integrity constraints where they improve correctness
- structured error/exit-code behavior for CLI automation

No model runtime belongs in this phase until these durable-state behaviors are stable.
