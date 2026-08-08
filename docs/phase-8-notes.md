# Phase 8 — Deterministic Context Discovery

Phase 8 improves the quality and usability of a bounded coding attempt without increasing agent authority.

Origin Forge can now select relevant source context automatically from the same isolated Git Workspace snapshot used by the Executor and deterministic applier.

The selector is conventional deterministic software. It is not another model and it does not receive filesystem authority from the coding model.

## Context boundary

Phase 6 established the snapshot-first invariant:

```text
create Workspace first
    ↓
model reads Workspace snapshot
    ↓
proposal applies to same Workspace
```

Phase 8 preserves that invariant for automatic context:

```text
create isolated Git Workspace
        ↓
TaskContextDiscoverer scans that Workspace only
        ↓
select bounded tracked text files
        ↓
normal ContextBuilder captures exact selected contents/hashes
        ↓
model receives ContextPackage
        ↓
proposal applies to same Workspace
```

Automatic discovery never scans the user's live working checkout.

Uncommitted user changes therefore remain outside the model's view exactly as they do in manual-context mode.

## Two explicit context modes

The one-shot Manager now supports two mutually exclusive modes.

### Manual context

Existing behavior remains valid:

```text
selected_paths = ["src/example.py", "tests/test_example.py"]
```

The caller explicitly determines every context file.

### Automatic context

The caller explicitly opts in:

```text
auto_context = true
```

The Manager creates the Workspace first and runs deterministic discovery inside it.

Manual file paths and `auto_context` cannot be supplied together.

## Task-derived query

The discoverer derives lexical terms only from durable Task state:

- objective
- acceptance criteria
- constraints
- required capabilities

It does not ask the coding model which files it wants to search.

Terms are normalized deterministically, including snake_case and camelCase splitting, with a small fixed stop-word set.

## Repository inventory

Candidate enumeration uses:

```text
git ls-files -z --cached
```

This gives the selector the tracked-file set for the Workspace snapshot.

The selector then:

- sorts deterministically
- skips symlinks
- applies the existing `RepositoryReader` containment rules
- rejects protected roots
- skips oversized files
- accepts UTF-8 text only

Ordinary untracked files are not discovered.

## Bounded scan

Discovery has independent scan limits:

```text
max_scan_files = 2000
max_scan_bytes = 8 MiB
```

It also inherits the `RepositoryReader` per-file limit.

A hard scan-file cap does not simply inspect the alphabetically first files. Before content scanning, tracked paths are ranked by Task-term matches in their path/name so likely relevant files receive priority under the scan budget.

The final file extension is excluded from path token scoring. A Task mentioning a `.py` path therefore cannot boost every Python file merely because they share the extension.

## Deterministic relevance score

For indexed files, Phase 8 uses a small deterministic lexical ranking function.

Signals include:

- Task-term frequency in file content
- inverse document frequency across the bounded indexed set
- stronger boost for Task terms appearing in path components
- additional filename-stem boost

The result is deterministic for the same:

```text
Task state + Git snapshot + discovery settings
```

No embeddings, remote search, or model ranking are required.

## No arbitrary fallback context

If no tracked file has positive relevance evidence, discovery returns an empty selection.

The Manager then:

1. does not call the coding model
2. abandons the unused clean Workspace snapshot
3. records an `INCONCLUSIVE` Task Verification at stage `CONTEXT`
4. moves the Task to `BLOCKED`

Origin Forge does not fill the context window with arbitrary repository files merely so an attempt can continue.

## Selection budgets

The final selected context has separate limits:

```text
max_files = 12
max_total_bytes = 512 KiB
```

Files that would exceed the remaining byte budget are skipped.

The ordinary `ContextBuilder` still applies its own context package budget when the selected paths are materialized for the Executor.

## Seed files

Automatic discovery supports explicit seed files.

A seed is a deterministic caller/operator override that says:

```text
include this file even if lexical relevance is low
```

Seeds:

- are placed before automatically ranked files
- remain subject to repository containment/text checks
- remain subject to selected-file and selected-byte budgets
- are allowed only with `auto_context`

This is useful for known architecture/specification files without giving the model a free-form filesystem search tool.

## Persisted context truth

`OrchestrationResult` now includes:

```text
context_paths
```

Task attempt evidence also records the selected paths.

Most importantly, the existing `ContextPackage` Artifact still captures the exact file contents and SHA-256 hashes that the model actually received.

Discovery output is therefore a selection mechanism; the ContextPackage remains the authoritative model-input evidence.

## CLI

The development orchestration CLI now requires one explicit context mode:

```text
python -m origin_forge.orchestration_cli \
  --project-root <project> \
  <TASK-ID> \
  --file src/example.py \
  --file tests/test_example.py
```

or:

```text
python -m origin_forge.orchestration_cli \
  --project-root <project> \
  <TASK-ID> \
  --auto-context
```

Optional deterministic seeds:

```text
--auto-context --seed-file docs/architecture.md
```

`--seed-file` is rejected unless automatic context mode is selected.

## Retry-policy boundary

Phase 8 deliberately does not duplicate or fork the Phase-7 retry-control loop.

`BoundedRetryPolicy` continues to use explicit context paths in this phase.

Automatic context is integrated into `BoundedTaskOrchestrator`, the single-attempt execution primitive. A later refactor can let retry policy carry a reusable context-selection specification without maintaining two divergent copies of the retry state machine.

This is a deliberate reliability tradeoff: one clean control loop is more valuable than prematurely wiring the feature everywhere through duplicated logic.

## Validation

GitHub Actions validates Python 3.12 and Python 3.13.

Current integrated Phase-8 result:

```text
Ran 119 tests in 11.949s
OK
```

Phase-8-specific coverage includes:

- deterministic relevant source/test ranking
- untracked-file exclusion
- unrelated Task returns empty context
- scan file/byte limits
- selected file/byte limits
- relevant path priority under `max_scan_files`
- explicit seed inclusion and seed budget errors
- symlink exclusion
- deterministic repeated discovery
- one-shot auto-context success
- discovered paths come from the Workspace snapshot
- dirty live checkout remains invisible and untouched
- empty discovery blocks before model invocation
- seed files flow into the actual model ContextPackage
- manual and automatic modes are mutually exclusive
- CLI `--auto-context` path

## Next step

The next high-value code-intelligence layer is structural discovery:

- symbol extraction
- imports/references
- test-to-source relationships
- Tree-sitter/LSP adapters where they provide measurable value

Those deterministic relationships can improve context selection beyond lexical matching while preserving the same bounded, snapshot-local authority model.
