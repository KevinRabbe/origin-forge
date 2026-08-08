# Phase 10 — Structural Context and Shared Selection

Status: **completion candidate; CI required before merge**

Phase 10 extends Phase 8's deterministic lexical discovery with bounded Python structural evidence and moves all one-shot/retry context mode handling behind one Workspace-local selector.

## Inherited boundaries

Phase 10 is intentionally layered on the hardened repository boundary and Phase-9 governed Skills.

That means:

- repository paths already use the portable cross-platform identity policy
- protected `.git` / `.origin-forge` roots remain inaccessible to model patch/context paths
- case-colliding path identities fail closed
- Skills may augment Executor procedure but do not alter context-selection, repository, sandbox, retry, verification, or merge authority
- structural context selection remains independent deterministic infrastructure

Phase 10 therefore improves **which evidence is shown** without granting either the model or a Skill new actions.

## Core invariant

Context is selected only after the isolated Git Workspace exists.

```text
Task
 ↓
create immutable Workspace snapshot
 ↓
WorkspaceContextSelector
 ├─ manual paths
 └─ lexical auto-context
        ↓
optional Python structural expansion
        ↓
ContextBuilder captures exact files + hashes
        ↓
Executor
```

A retry does not reuse a context package computed against another Workspace. The retry policy carries selection **intent** (`manual`, `auto`, seeds, structural flag) into the next attempt; the new attempt performs selection against its own new snapshot.

## Shared WorkspaceContextSelector

`WorkspaceContextSelector` owns context-selection policy but does not:

- create Workspaces
- invoke models
- mutate files
- decide Task completion

Inputs:

- explicit `selected_paths`, or
- `auto_context=True`
- optional automatic seed paths
- optional `structural_context=True`

Manual and automatic modes are mutually exclusive. Seed paths require automatic mode.

## Structural graph

`PythonStructuralContext` indexes only tracked Python files from the supplied Workspace-local `RepositoryReader`.

It derives one-hop evidence from:

- conventional source ↔ test filename pairing
- internal direct imports
- reverse importers
- Task terms matching class/function definitions

Current evidence weights:

```text
test/source pair   +100
direct dependency   +80
reverse importer    +70
task symbol          +30 + matched-term evidence
```

Evidence may combine. Ranking is deterministic by score then path.

Structural expansion is intentionally one hop. It does not recursively follow dependency chains and therefore cannot pull an entire repository into context merely because one seed imports a large subsystem.

## Budgets and containment

Structural indexing and final context remain bounded by:

- tracked files only
- UTF-8 repository reads
- symlink exclusion
- maximum scanned files
- maximum scanned bytes
- maximum selected files
- maximum selected bytes

Malformed Python counts against scan I/O before being skipped, so syntax errors cannot bypass the scan-byte budget.

## One-shot orchestration integration

`BoundedTaskOrchestrator.execute` now accepts:

```text
selected_paths=...
auto_context=...
context_seed_paths=...
structural_context=...
```

The Workspace is created before `WorkspaceContextSelector` runs.

The selected mode is recorded in Task Verification evidence as `context_mode` and the exact selected paths remain recorded in the durable ContextPackage.

A deterministic context-selection failure or empty automatic selection:

1. does not call the model
2. abandons an unused clean Workspace
3. records Task Verification at stage `CONTEXT`
4. moves the Task to `BLOCKED`

## Retry-policy integration

`BoundedRetryPolicy.drive` accepts the same selection intent.

For every fresh strategy attempt it forwards that intent to `BoundedTaskOrchestrator`, which creates a new Workspace and performs context selection inside that Workspace.

This avoids a second retry-specific context-discovery state machine.

A `BLOCKED` result at stage `CONTEXT` is terminal for the current policy drive. Recreating the same committed snapshot cannot manufacture missing deterministic context and therefore must not consume model retry budget.

Existing explicit-path callers remain compatible.

## CLI

The one-shot development CLI supports:

```text
--file path.py
```

or:

```text
--auto-context
```

plus:

```text
--seed-file path.py
--structural-context
```

`--structural-context` expands whichever valid base selection mode was chosen.

## Regression coverage

Phase-10-specific coverage includes:

- direct relative/import dependency expansion
- reverse importer expansion
- source ↔ test pairing
- Task-symbol evidence
- untracked-file exclusion
- malformed Python accounting
- tracked symlink exclusion
- structural selection budgets
- deterministic repeated expansion
- manual selector compatibility
- lexical auto-context composition
- manual + structural composition
- auto + structural composition
- no arbitrary fallback context
- one-shot structural context reaching the Executor
- retry auto-context no-match stopping before a model call
- retry escalation reselecting auto+structural context inside fresh Workspaces

## Scope boundary

Phase 10 adds no:

- language server process
- model-controlled repository search
- recursive dependency crawl
- arbitrary shell execution
- merge authority
- new model write authority

The next layer is a provider-neutral code-intelligence interface followed by carefully bounded LSP integration.
