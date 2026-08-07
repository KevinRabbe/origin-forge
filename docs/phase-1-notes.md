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
- status summary
- local runtime database isolation under `.origin-forge/`
- GitHub Actions test matrix for Python 3.12 and 3.13

## Validation performed before publishing the latest branch state

```text
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Result:

```text
Ran 11 tests
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

A CLI smoke test also verified:

```text
python -m origin_forge --project-root <temp>/demo init --name demo
python -m origin_forge --project-root <temp>/demo status
python -m origin_forge --project-root <temp>/demo recover
```

The recovery command also supports:

```text
python -m origin_forge --project-root <temp>/demo recover --apply
```

`recover` without `--apply` is inspection-only. `recover --apply` reconciles stale `RUNNING` records conservatively rather than assuming they succeeded.

Observed behavior:

- project state initializes correctly
- schema version reports `1`
- reopening the store preserves state
- a clean initialized project reports no recovery findings
- interrupted execution is moved into explicit non-success states
- running recovery repeatedly does not create further mutations after reconciliation

## Remaining Phase 1 work

The durable substrate is now useful enough to continue, but Phase 1 should still add:

- Goal / Flow / Task CLI operations for exercising state without direct Python calls
- richer Run querying and status reporting
- recovery tests around mixed/partially terminal state
- explicit configuration bootstrap under `.origin-forge/config.toml`
- migration organization that remains maintainable beyond schema version 1
- invariants around parent/child Tasks and Flow completion
- additional database integrity constraints where they improve correctness

No model runtime belongs in this phase until these durable-state behaviors are stable.
