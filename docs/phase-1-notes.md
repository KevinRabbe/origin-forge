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
- recovery inspection for interrupted `RUNNING` Flow/Task/Run records
- status summary
- local runtime database isolation under `.origin-forge/`

## Validation performed before publishing the branch

```text
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Result:

```text
Ran 9 tests
OK
```

A CLI smoke test also verified:

```text
python -m origin_forge --project-root <temp>/demo init --name demo
python -m origin_forge --project-root <temp>/demo status
python -m origin_forge --project-root <temp>/demo recover
```

Observed behavior:

- project state initializes correctly
- schema version reports `1`
- reopening the store preserves state
- a clean initialized project reports no recovery findings

## Important limitation

This is intentionally not yet the complete Phase 1 target. The next iteration should add explicit Run creation/lifecycle, richer recovery reconciliation, migration-file separation if warranted, Goal/Task CLI operations, and tests around interrupted Run recovery.

No model runtime belongs in this phase until the durable state layer is sufficiently stable.
