# Phase 11 — Code Intelligence and Sandboxed LSP

Status: **stacked development branch; depends on Phase 10**

Phase 11 extends Origin Forge from lexical/structural context selection into a provider-neutral code-intelligence layer while keeping code intelligence as evidence rather than authority.

## Inherited stack

Phase 11 is validated as the top of the current dependency chain, not as an isolated feature branch:

```text
hardened main
→ Phase 9 governed Skills
→ Phase 10 shared structural context
→ Phase 11 code intelligence / sandboxed LSP
```

It inherits the portable repository-path policy, governed Skill authority boundary, snapshot-first Workspace selection, and fresh-retry context semantics. Phase 11 may enrich evidence, but it does not replace any of those lower-layer controls.

## Design rule

A language server, parser, or static analyzer may report symbols, definitions, references, and diagnostics. It does not receive permission to mutate project state, change policy, merge work, decide Task completion, or bypass compiler/test/runtime verification.

## Provider boundary

Origin Forge exposes one normalized read-only contract:

```text
CodeIntelligenceProvider
├── workspace_symbols
├── definitions
├── references
└── diagnostics
```

Normalized values use Origin Forge types rather than raw LSP structures. Providers can therefore be replaced or combined without changing Manager/Executor semantics:

```text
Python AST
Tree-sitter
LSP
future static-analysis provider
```

## Internal positions

Origin Forge uses zero-based lines and zero-based Unicode-codepoint character positions. Provider adapters convert their native representation at the boundary.

For LSP this matters because character offsets may use UTF-8, UTF-16, or UTF-32 code units. Protocol-specific encoding semantics stay inside the LSP adapter.

## Deterministic Python provider

`PythonAstCodeIntelligence` is the first provider. It:

- executes no project code
- scans only tracked Python files
- reads through `RepositoryReader`
- skips symlinks
- applies scan-file and scan-byte budgets
- returns bounded deterministic results
- extracts class/function/method symbols
- supports conservative definition/reference lookup
- reports Python syntax diagnostics

It intentionally does not pretend to provide complete semantic knowledge for dynamic Python.

## LSP protocol codec

`lsp_protocol.py` implements the process-neutral wire layer:

- header-delimited JSON-RPC framing
- mandatory byte-count `Content-Length`
- UTF-8 content enforcement
- header/message size bounds
- JSON object validation
- UTF-8 / UTF-16 / UTF-32 position conversion
- rejection of offsets that split Unicode characters

## Bounded JSON-RPC session

`LspJsonRpcSession` runs over caller-supplied byte streams.

Current rules:

- exactly one outstanding client request
- exact response-ID correlation
- bounded request timeout
- timeout makes the session terminal
- bounded pending notifications
- wrong/missing JSON-RPC 2.0 state fails closed
- server-to-client requests are rejected by default
- protocol/message limits apply to every read/write

One outstanding request is deliberate. Origin Forge does not need multiplexing complexity before benchmarks show a useful throughput gain.

## Workspace URI containment

`LspWorkspaceMapper` separates the local filesystem tree Origin Forge reads from the root URI visible to the server.

Example sandbox mapping:

```text
local copy: .../.origin-forge/lsp-jobs/<id>/workspace
server root: file:///workspace
```

Every returned server URI is translated through a relative path and then revalidated against the local Workspace.

The mapper rejects:

- paths outside the Workspace after resolution
- protected `.git` / `.origin-forge` roots
- symlink escapes
- non-file URIs
- remote-host file URIs
- query/fragment-bearing file URIs
- mismatched server-visible roots

Spaces and Unicode round-trip through percent-encoded file URIs.

## Initialization and capability negotiation

`initialize_lsp_session` advertises only the read-only intelligence capabilities Origin Forge consumes and parses the response into `LspServerCapabilities`.

Position encoding is negotiated from:

- `utf-8`
- `utf-16`
- `utf-32`

If the server omits the negotiated encoding, UTF-16 is the compatibility fallback.

Origin Forge currently models one immutable Workspace root. `rootUri` is authoritative and `workspaceFolders` is sent as `null`; dynamic workspace-folder support is not advertised.

Normalized capability flags currently cover:

- workspace symbols
- definitions
- references
- pull diagnostics

## Normalized LSP provider

`LspCodeIntelligenceProvider` connects an initialized bounded LSP session to the common `CodeIntelligenceProvider` interface.

It supports:

- `workspace/symbol`
- `textDocument/definition`
- `textDocument/references`
- `textDocument/diagnostic`

Raw LSP results never go directly to the model. Returned URIs are contained first, source files are re-read through `RepositoryReader`, and character offsets are converted from the negotiated encoding back to Origin Forge Unicode-codepoint positions.

## Config v4 trusted server registry

Project config v4 adds an empty-by-default registry of operator-approved LSP servers under protected Origin Forge state.

A server descriptor owns:

- stable server ID
- backend (`podman` only in Phase 11)
- local/preloaded image reference
- exact server argv
- Podman executable
- network policy
- memory / CPU / PID limits
- probe / initialize / request / shutdown timeouts
- protocol-message limit
- notification limit
- stderr limit

Configs v1–v3 remain readable. Configuring a server does not start it.

`create_configured_lsp_backend(runtime, server_id)` accepts only a configured ID. Image, argv, backend, and resource policy come from protected project configuration rather than model input.

## Sandboxed Podman LSP backend

`PodmanLspBackend` treats language-server startup as sandboxed code execution rather than harmless metadata access.

The configured image must already exist locally. Origin Forge resolves it to a local image ID and runs with `--pull=never`.

Each session receives a disposable source copy under:

```text
.origin-forge/lsp-jobs/<id>/workspace
```

The copy:

- excludes protected roots case-insensitively
- omits all symlinks
- is mounted read-only at `/workspace`

The container uses:

- read-only root filesystem
- read-only `/workspace`
- dropped capabilities
- `no-new-privileges`
- bounded CPU / memory / PID count
- tmpfs writable areas for `/tmp` and `/run`
- HOME/cache redirected to `/tmp`
- network disabled by default

Lifecycle is bounded:

```text
resolve local image
→ copy Workspace
→ start container
→ initialize bounded LSP session
→ normalized provider
→ shutdown
→ exit
→ wait / terminate / kill fallback
→ CID cleanup
→ remove disposable copy
```

Initialization failure follows the same cleanup discipline.

There is deliberately no native-host language-server backend in Phase 11.

## Safe operator surface

The Phase-11 CLI exposes only configured identity/status operations:

```text
python -m origin_forge.code_intelligence_cli list
python -m origin_forge.code_intelligence_cli status <configured-server-id>
```

There is no command-line or model surface for arbitrary image names, server argv, raw LSP methods, code actions, or host executables.

## Semantic context expansion

`CodeIntelligenceContextExpander` takes an existing bounded seed context and:

- derives a small deterministic Task query set
- performs bounded workspace-symbol queries
- accepts only tracked result files
- re-reads candidates through `RepositoryReader`
- preserves seed paths
- enforces final file/byte budgets
- fails explicitly when requested semantic evidence is unavailable

It remains separate from Phase-10 orchestration until the lower branch lands. After Phase 10 merges it can plug into the shared `WorkspaceContextSelector` rather than creating a second context state machine.

## Diagnostics evidence

`CodeDiagnosticsEvaluator` converts provider diagnostics into bounded, sorted evidence.

Important rules:

- diagnostics are evidence, not the final correctness oracle
- errors may fail this evidence check
- warnings/information remain visible without automatically failing the Task
- diagnostic messages are length-bounded
- total diagnostic count is bounded
- the number of diagnostic paths is bounded
- the total provider request budget is partitioned across files before the provider call, rather than slicing only after an oversized request
- an excessive path set fails before any provider request is made

Compiler, tests, runtime observation, sandbox verification, and other deterministic checks remain higher-authority evidence.

## Relationship to Phase 10

Phase 10 decides which files are relevant using lexical and structural evidence. Phase 11 can add richer semantic evidence without replacing that selection state machine.

```text
Task
 ↓
WorkspaceContextSelector
 ↓
lexical + structural candidates
 ↓
optional CodeIntelligenceContextExpander
 ↓
final bounded ContextPackage
 ↓
Executor

Workspace / changed files
 ↓
CodeDiagnosticsEvaluator
 ↓
bounded Auditor evidence
```

Semantic expansion and LSP use should be benchmarked before becoming default behavior.

## Current regression surface

Phase-11 tests cover:

- provider protocol/capabilities
- Python class/method/function scope classification
- Python definition/reference lookup
- Python syntax diagnostics
- tracked-only and symlink-safe indexing
- scan budgets/determinism
- byte-accurate LSP framing
- message/header bounds
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
- host ↔ container server-root mapping
- external/non-file/symlink URI rejection
- capability negotiation and UTF-16 fallback
- single-Workspace initialization contract
- process-neutral symbol/definition/reference/diagnostic normalization
- config-v4 server registry validation and backward compatibility
- configured-server factory behavior
- safe operator CLI behavior
- Podman command hardening and local image resolution
- symlink-free disposable copies
- lifecycle and initialization-failure cleanup
- semantic context query/file/byte budgets
- diagnostics sorting, message limits, path limits, and provider-request budgets

## Deferred

Phase 11 intentionally does not include:

- native-host LSP execution
- arbitrary shell execution
- model-controlled server executable/image/argv
- model-controlled raw LSP requests
- language-server plugins downloaded from the internet
- automatic code-action/edit application
- unbounded workspace symbol/reference/diagnostic requests
- dynamic multi-root workspace management
- diagnostics as the only verification oracle
