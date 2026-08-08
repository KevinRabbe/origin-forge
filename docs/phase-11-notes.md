# Phase 11 — Code Intelligence and LSP Notes

Status: **stacked development branch; depends on Phase 10**

Phase 11 extends Origin Forge from lexical/structural context selection toward a provider-neutral code-intelligence layer.

## Design rule

Code intelligence is evidence, not authority.

A language server or parser may report definitions, references, symbols and diagnostics. It does not receive permission to mutate project state, change policy, merge work, or decide Task completion.

## Provider boundary

Origin Forge exposes one normalized read-only contract:

```text
CodeIntelligenceProvider
├── workspace_symbols
├── definitions
├── references
└── diagnostics
```

Normalized values use Origin Forge types rather than raw LSP structures.

This allows providers to be replaced or combined:

```text
Python AST
Tree-sitter
LSP
future static-analysis provider
```

without changing Manager/Executor semantics.

## Internal positions

Origin Forge uses:

```text
line       zero-based
character  zero-based Unicode codepoint index
```

Provider adapters are responsible for converting their native representation.

This matters for LSP because a language server can use negotiated position encodings such as UTF-8, UTF-16 or UTF-32 code units. Protocol-specific encoding semantics must stay inside the LSP adapter.

## Deterministic Python provider

`PythonAstCodeIntelligence` is the first provider.

It:

- executes no project code
- scans only tracked Python files
- reads through `RepositoryReader`
- skips symlinks
- applies scan-file and scan-byte budgets
- returns bounded deterministic results
- extracts class/function/method symbols
- supports simple definition/reference lookup
- reports Python syntax diagnostics

It is intentionally conservative. It does not pretend to have full semantic knowledge of dynamic Python.

## LSP protocol codec

The first LSP layer is deliberately process-free.

`lsp_protocol.py` implements:

- header-delimited JSON-RPC framing
- mandatory byte-count `Content-Length`
- UTF-8 content enforcement
- header/message size bounds
- JSON object validation
- UTF-8 / UTF-16 / UTF-32 position conversion
- rejection of code-unit offsets that split Unicode characters

This lets protocol mechanics be verified independently of any external server process.

## Future trusted-server boundary

A later Phase-11 increment may launch an LSP server only through an explicit trusted configuration.

Before that is allowed, the process layer must define at least:

- exact executable/argv allowlist
- Workspace root passed explicitly
- `shell=False`
- clean/bounded environment
- startup and request timeouts
- stdout protocol message bounds
- independently bounded stderr drain
- capability negotiation
- request-ID correlation
- server-request policy
- graceful shutdown plus forced termination fallback
- URI/path containment on every returned location
- no network unless explicitly required/allowed
- no model control over server executable or arguments

Project code must never be executed merely to obtain code intelligence.

## Relationship to Phase 10

Phase 10 decides **which files are relevant** using lexical and structural evidence.

Phase 11 supplies richer evidence about those files and their relationships.

Expected direction:

```text
Task
 ↓
WorkspaceContextSelector
 ↓
lexical + structural candidates
 ↓
CodeIntelligenceProvider
 ↓
definition/reference/diagnostic evidence
 ↓
final bounded ContextPackage / Auditor evidence
```

The implementation should be benchmarked before structural/LSP expansion becomes a default behavior.

## Deferred

Not included in the current substrate:

- spawning a language server
- arbitrary host shell execution
- project-controlled LSP executable selection
- language-server plugins downloaded from the internet
- model-controlled LSP queries
- unbounded workspace symbol/reference requests
- automatic file mutation from code-action/edit responses
- trusting diagnostics as the only verification oracle
