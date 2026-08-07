# Phase 2 — Bounded Local Worker

Phase 2 connects Origin Forge's durable Phase-1 control plane to a replaceable local coding model without granting the model write authority.

## Trust boundary

```text
RUNNING Task
    ↓
explicit file selection
    ↓
read-only RepositoryReader
    ↓
immutable ContextPackage
    ↓
local ModelAdapter
    ↓
structured PatchProposal
    ↓
SHA-256 precondition validation
    ↓
persisted proposal artifact

NO PATCH APPLICATION
NO SHELL
NO AUTOMATIC TASK SUCCESS
```

The worker may propose repository changes. It cannot apply them.

## Implemented

- `RepositoryReader`
  - read-only access
  - project-root containment
  - `.git` and `.origin-forge` protection
  - UTF-8 text requirement
  - per-file and total context byte budgets
  - SHA-256 content hashes
- `ContextPackage`
  - Task ID and revision
  - objective
  - acceptance criteria
  - constraints
  - required capabilities
  - explicitly selected repository files only
- replaceable `ModelAdapter` protocol
- structured `PatchProposal`
  - `CREATE`, `UPDATE`, `DELETE`
  - protected path rejection
  - duplicate-path rejection
  - output size limits
  - exact hash preconditions for `UPDATE` / `DELETE`
- deterministic precondition checking against the current repository
- `LocalPatchWorker`
  - requires a pre-existing `RUNNING` Task
  - creates a durable Executor Run
  - persists the exact ContextPackage
  - persists the raw ModelResponse
  - persists the validated PatchProposal
  - marks invalid/stale proposals as failed Runs
  - never modifies source files
- llama.cpp adapter
  - OpenAI-compatible `/v1/chat/completions`
  - schema-constrained JSON output
  - token usage capture
  - loopback-only endpoint by default
  - remote endpoints require explicit opt-in
- CLI entry point:

```text
origin-forge --project-root <project> worker propose <TASK-ID> \
  --file src/example.py \
  --base-url http://127.0.0.1:8080 \
  --model local-coder
```

The CLI result explicitly includes:

```json
{"applied": false}
```

## Persisted Run evidence

A successful proposal Run creates local artifacts under:

```text
.origin-forge/runs/<RUN-ID>/
├── context.json
├── model-response.txt
└── patch-proposal.json
```

Each file is also registered in Origin Forge's Artifact lineage with a SHA-256 hash.

This makes the model interaction reproducible without treating raw conversation history as durable project truth.

## Validation

Local validation command:

```text
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Current local result:

```text
Ran 36 tests
OK
```

New Phase-2 coverage verifies:

1. repository containment and protected-state blocking
2. explicit context selection
3. context size limits
4. protected patch-path rejection
5. valid proposal persistence without source mutation
6. stale hash rejection and failed-Run cleanup
7. llama.cpp remote-endpoint opt-in requirement
8. schema-constrained chat-completion request shape
9. usage parsing
10. end-to-end CLI proposal flow against a fake local HTTP server

## Deliberate non-goals

This phase does not yet provide:

- patch application
- shell execution
- Git worktree automation
- test execution by the worker
- repository search/tool loops
- Manager planning
- independent Auditor
- Skills
- LSP
- automatic context selection

Those capabilities will be layered above this proposal-only trust boundary rather than weakening it.
