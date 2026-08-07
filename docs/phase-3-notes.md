# Phase 3 — Isolated Apply and Audit

Phase 3 allows Origin Forge to materialize a validated model proposal for the first time, but only inside a durable disposable Git worktree. The user's main working tree remains unchanged.

## Trust boundary

```text
persisted PATCH_PROPOSAL artifact
        ↓ integrity + Task lineage check
Durable Workspace record
        ↓
Git worktree + dedicated branch
        ↓
Deterministic APPLIER Run
        ↓
complete staged Git diff
        ↓
independent deterministic AUDITOR
        ↓
PASS → VERIFIED workspace
FAIL → FAILED workspace

main working tree: untouched
```

There is still no arbitrary shell command execution and no automatic merge.

## Durable workspace model

Schema versions 3 and 4 add:

- `WSPACE-*` infrastructure IDs
- workspace Task ownership
- dedicated branch name and worktree path
- immutable base commit
- revisioned workspace lifecycle
- one non-abandoned workspace per Task

Workspace states:

```text
CREATED
  ├─→ APPLIED
  ├─→ FAILED
  └─→ ABANDONED

APPLIED
  ├─→ VERIFIED
  ├─→ FAILED
  └─→ ABANDONED

VERIFIED / FAILED
  └─→ ABANDONED
```

## Git isolation

`GitWorkspaceManager`:

- requires the Origin Forge project root to equal the Git toplevel in this phase
- creates a dedicated worktree and branch under `.origin-forge/workspaces/`
- adds `/.origin-forge/` to the repository-local `.git/info/exclude`
- never modifies the tracked `.gitignore` merely to host Origin Forge state
- runs Git through argument arrays, never `shell=True`
- uses bounded subprocess timeouts
- provides deterministic staged diffs and changed-path inspection
- removes ignored as well as untracked files when rolling back a failed disposable workspace

## Proposal provenance

Worker artifacts now form an explicit causal chain:

```text
CONTEXT_PACKAGE
      ↓
MODEL_RESPONSE
      ↓
PATCH_PROPOSAL
      ↓
GIT_DIFF
```

A proposal can be applied through its Artifact ID. Before application Origin Forge:

1. verifies the Artifact type is `PATCH_PROPOSAL`
2. verifies the creating Run belongs to the Workspace Task
3. re-hashes the stored proposal file and compares it with its durable Artifact hash
4. parses the structured proposal again
5. re-checks file SHA-256 preconditions against the isolated worktree

Tampering with the persisted proposal therefore fails before mutation.

## Deterministic application

`IsolatedPatchApplier` supports the existing structured operations:

- `CREATE`
- `UPDATE`
- `DELETE`

It applies them only inside the selected worktree.

After mutation it stages the disposable worktree in order to capture a complete binary Git diff, including newly created files. The staging area belongs to the isolated worktree and does not stage changes in the user's main checkout.

If application fails after mutation begins, Origin Forge:

- resets the worktree to `HEAD`
- removes untracked and ignored material created by the failed attempt
- marks the Workspace `FAILED`
- marks the APPLIER Run `FAILED`

## Independent audit

`WorkspaceAuditor` does not write the requested product changes.

It independently verifies:

- Workspace state
- actual changed paths exactly match proposal paths
- deleted files are absent
- created/updated file content exactly matches the proposal

It records a Workspace Verification and transitions:

```text
PASS → VERIFIED
FAIL → FAILED
```

This is the first concrete implementation of Origin Forge's separation between creator and judge.

## Crash recovery

A process may die while a `CREATED` workspace is partially modified.

Workspace recovery detects dirty `CREATED` worktrees. Applying recovery:

- resets/cleans the disposable worktree
- records a recovery event
- transitions it to `FAILED`

Partial work is therefore never silently treated as reusable or successful.

## Validation

Local validation:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
```

Current result:

```text
Ran 50 tests
OK
```

Phase-3-specific coverage includes:

- schema v1 → v4 migration
- worktree-only mutation
- complete diff evidence including new files
- Task must be RUNNING before Workspace creation
- one active Workspace per Task
- rollback of ignored/untracked files
- failed audit → failed Workspace
- dirty-workspace crash recovery
- Artifact integrity checking before apply
- proposal Task-lineage enforcement
- causal Artifact parentage
- main working tree remains unchanged

## Deliberate non-goals

Phase 3 still does not add:

- arbitrary shell execution
- build/test command execution
- automatic commit or merge
- Manager planning
- model-driven tool loops
- Skills
- LSP
- automatic repository context discovery

The next security-sensitive layer is a constrained command runner for project-approved build/test commands inside a verified isolated Workspace. It should be introduced as a separate capability rather than granting the model general shell access.
