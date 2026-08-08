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

This matters for LSP because a language server can use negotiated position encodings such as UTF-8, UTF-16 or UTF-32 code units. Protocol-specific encoding semantics stay inside the LSP adapter.

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

## Bounded JSON-RPC session

`LspJsonRpcSession` runs over caller-supplied byte streams.

Current rules:

- exactly one outstanding client request
- exact response-ID correlation
- request timeout
- timeout makes the session terminal
- bounded pending notifications
- wrong/missing JSON-RPC 2.0 protocol state fails closed
- server-to-client requests are rejected with `MethodNotFound` until a specific safe handler exists
- protocol/message size limits remain active for every read/write

The one-outstanding-request rule is intentional. Origin Forge does not need multiplexing complexity before it has evidence that concurrent LSP requests improve throughput.

## Workspace URI containment

`LspWorkspaceMapper` is the trust boundary for file locations.

It converts between relative Workspace paths and `file://` URIs while enforcing:

- Workspace-root containment after resolution
- `.git` protection
- `.origin-forge` protection
- symlink-escape rejection
- non-file URI rejection
- remote-host file URI rejection
- query/fragment rejection

A language server returning one unsafe location causes the query to fail rather than silently adding that path to model context.

## Initialization and capability negotiation

`initialize_lsp_session` advertises the small code-intelligence capabilities Origin Forge intends to use and parses the server response into `LspServerCapabilities`.

Position encoding is explicit:

- `utf-8`
- `utf-16`
- `utf-32`

If the server omits position-encoding negotiation, the compatibility fallback is UTF-16.

Normalized capability flags currently cover:

- workspace symbols
- definitions
- references
- pull diagnostics

## Process-neutral LSP provider

`LspCodeIntelligenceProvider` connects an already-initialized bounded LSP session to the same `CodeIntelligenceProvider` interface as the Python AST implementation.

It supports:

- `workspace/symbol`
- `textDocument/definition`
- `textDocument/references`
- `textDocument/diagnostic`

All raw results are normalized into Origin Forge data types. Returned URIs are revalidated through `LspWorkspaceMapper`, and LSP character offsets are converted from the negotiated encoding back to Origin Forge Unicode-codepoint positions.

The model never receives a raw LSP session or arbitrary LSP method surface.

## Why process execution is still separate

Phase 11 can now speak and normalize LSP without deciding how the server process is hosted.

That separation is deliberate. Starting a language server is a security boundary because some servers can invoke compilers, build systems, plugins, proc macros, project interpreters, or network-dependent tooling depending on configuration.

Origin Forge should not accidentally turn "code intelligence" into general project-code execution.

## Future trusted-server boundary

Before Origin Forge itself launches an LSP server, the process layer must define at least:

- exact trusted executable/argv policy
- Workspace root passed explicitly
- `shell=False`
- clean/bounded environment
- startup and request timeouts
- stdout protocol message bounds
- independently bounded stderr drain
- capability negotiation
- request-ID correlation
- explicit safe server-request handlers only
- graceful shutdown plus forced termination fallback
- URI/path containment on every returned location
- enforceable network policy
- no model control over server executable or arguments

For language servers that can execute project code, a persistent isolated/sandboxed hosting backend is preferable to a native-host process.

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

## Current regression surface

Phase-11 tests cover:

- provider protocol/capabilities
- Python class/method/function scope classification
- Python definition/reference lookup
- Python syntax diagnostics
- tracked-only and symlink-safe indexing
- scan budgets/determinism
- byte-accurate LSP framing
- LSP message/header bounds
- UTF-8 content enforcement
- UTF-8/UTF-16/UTF-32 position conversion
- split-codepoint rejection
- JSON-RPC request/response correlation
- remote errors
- server-request rejection
- terminal request timeouts
- bounded notification queues
- JSON-RPC version enforcement
- Workspace URI round-trip and containment
- external/non-file/symlink URI rejection
- capability negotiation and UTF-16 fallback
- process-neutral workspace-symbol/definition/reference/diagnostic normalization
- external result location rejection

## Deferred

Not included in the current substrate:

- spawning a language server
- arbitrary host shell execution
- project-controlled LSP executable selection
- language-server plugins downloaded from the internet
- model-controlled raw LSP queries
- unbounded workspace symbol/reference requests
- automatic file mutation from code-action/edit responses
- trusting diagnostics as the only verification oracle
