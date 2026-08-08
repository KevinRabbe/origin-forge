# Phase 11 — Code Intelligence and Sandboxed LSP

Status: **completion candidate; final exact-head CI required before merge**

Phase 11 adds provider-neutral code intelligence to the already-merged Phase-10 Workspace context pipeline. Code intelligence remains evidence, never authority.

## Inherited stack

```text
hardened portable-path main
→ Phase 9 governed Skills
→ Phase 10 snapshot-local lexical + structural context
→ Phase 11 semantic code intelligence / sandboxed LSP
```

Phase 11 does not replace lower-layer controls. It inherits:

- portable cross-platform repository path identity
- protected `.git` / `.origin-forge` state
- governed Skill authority boundaries
- Workspace-first immutable Git snapshots
- retry-time context reselection inside fresh Workspaces
- deterministic patch apply/audit/sandbox gates

## Provider-neutral contract

Origin Forge exposes one read-only interface:

```text
CodeIntelligenceProvider
├── workspace_symbols
├── definitions
├── references
└── diagnostics
```

Normalized Origin Forge values are used for symbols, locations, ranges, and diagnostics. Manager/Executor code therefore does not depend on whether evidence came from Python AST, LSP, Tree-sitter, or another future static-analysis provider.

Internal text positions use:

```text
line       zero-based
character  zero-based Unicode codepoint index
```

Provider adapters translate their own native representation at the boundary.

## Deterministic Python AST provider

`PythonAstCodeIntelligence` is the default Phase-11 semantic provider.

It:

- executes no project code
- enumerates tracked Python files only
- uses explicit Git argv, never shell syntax
- applies a Python pathspec before Git output
- drains stdout/stderr concurrently
- has Git timeout/output limits
- kills enumeration on stdout overflow
- retains at most `max_scan_files`
- reads through `RepositoryReader`
- skips symlinks
- applies source scan-byte limits
- extracts class/function/method symbols
- supports conservative definition/reference lookup
- reports Python syntax diagnostics

It intentionally does not claim complete semantic knowledge of dynamic Python.

## Semantic context in the shared selector

Phase 11 does not introduce a second context state machine.

The existing Phase-10 selector now composes:

```text
MANUAL or AUTO
      ↓
optional STRUCTURAL
      ↓
optional SEMANTIC
      ↓
final bounded paths
```

`semantic_context=False` by default.

When enabled without an injected provider, semantic expansion uses the deterministic Python AST provider. A trusted provider may be injected explicitly by infrastructure code, but the model does not select providers.

Semantic expansion:

- derives a bounded deterministic Task query set
- requests a bounded number of workspace symbols per query
- preserves seed files
- enforces final file/byte limits
- verifies only the bounded seed/candidate set as tracked
- uses Git literal pathspecs so wildcard-like filenames cannot broaden a check
- rejects untracked seed files
- ignores untracked provider candidates

One-shot orchestration records the resulting `context_mode` and exact ContextPackage paths.

The retry policy carries only selection intent into each fresh attempt:

```text
new Workspace
→ MANUAL/AUTO
→ optional STRUCTURAL
→ optional SEMANTIC
→ fresh Executor
```

Resume-from-APPLIED/AUDITED/VERIFIED paths do not rerun context discovery.

## LSP protocol boundary

`lsp_protocol.py` implements bounded LSP framing and position conversion:

- mandatory byte-count `Content-Length`
- UTF-8 JSON content
- header/message size limits
- JSON object validation
- UTF-8 / UTF-16 / UTF-32 position conversion
- rejection of offsets that split Unicode code points

## Bounded JSON-RPC session

`LspJsonRpcSession` deliberately supports exactly one outstanding client request.

It enforces:

- one pending response slot
- exact response-ID correlation
- terminal request timeout
- terminal protocol/correlation failures
- JSON-RPC 2.0 validation
- server-to-client request rejection by default
- pending notification count limit
- cumulative pending-notification byte limit

A second pending response or excess notification memory fails the session closed.

## Workspace URI containment

`LspWorkspaceMapper` uses the same shared portable path policy as repository reads and patch application.

A server may see a different root URI from Origin Forge's local disposable copy:

```text
host:   .../.origin-forge/lsp-jobs/<id>/workspace
server: file:///workspace
```

Every returned URI is converted through a relative path and revalidated locally.

Rejected forms include:

- non-file URIs
- remote-host file URIs
- query/fragment-bearing file URIs
- server-root escapes
- local Workspace escapes
- protected roots
- symlink escapes
- Windows-host-dependent path forms

Spaces and Unicode round-trip through percent-encoded file URIs.

## LSP initialization

Origin Forge advertises only the read-only intelligence features it consumes.

Position encoding supports:

- UTF-8
- UTF-16
- UTF-32

UTF-16 is the compatibility fallback when the server omits `positionEncoding`.

Phase 11 models one immutable Workspace root:

- `rootUri` is authoritative
- `workspaceFolders = null`
- dynamic multi-root behavior is not advertised

## Normalized LSP provider

`LspCodeIntelligenceProvider` converts initialized LSP evidence into the common provider contract.

Supported requests:

- `workspace/symbol`
- `textDocument/definition`
- `textDocument/references`
- `textDocument/diagnostic`

Raw LSP results never go directly to the model. Returned URIs are contained first and positions are translated from the negotiated encoding.

Diagnostic text is bounded during normalization:

- message: 16 KiB characters
- source: 512 characters
- code: 512 characters

## Diagnostics are evidence, not truth

`CodeDiagnosticsEvaluator` bounds diagnostic collection by:

- path count
- total retained diagnostic count
- provider request budget partitioned across paths before the request
- evidence message length
- deterministic severity/path ordering

`WorkspaceAuditor` records deterministic Python diagnostics for changed non-deleted files as `code_diagnostics` evidence.

Important rule:

**Diagnostics do not add patch-audit findings and do not decide Task success.**

A syntactically invalid Python patch may therefore pass the structural patch audit if it was applied exactly; later sandbox/compiler/test verification remains responsible for correctness.

If diagnostic collection itself fails, the bounded error is recorded as supplementary evidence rather than replacing the primary audit oracle.

## Config v4 trusted LSP registry

Project config v4 adds an empty-by-default operator-owned registry:

```toml
[code_intelligence]
lsp_servers = []
```

A configured server descriptor owns:

- stable server ID
- backend (`podman` only)
- preloaded/local image reference
- exact server argv
- Podman executable
- network policy
- memory / CPU / PID limits
- probe / initialize / request / shutdown timeouts
- protocol message limit
- notification limit
- stderr limit

Configs v1–v3 remain readable.

Configuring a server does not start it.

`create_configured_lsp_backend(runtime, server_id)` accepts only a configured ID. The model cannot provide image, argv, backend, or host executable.

## Sandboxed Podman LSP backend

Language-server startup is treated as sandboxed code execution.

`PodmanLspBackend`:

- requires an already-local image
- resolves it to a local image ID
- uses `--pull=never`
- creates a disposable source copy
- excludes protected roots case-insensitively
- omits all symlinks
- mounts `/workspace` read-only
- uses a read-only container root
- drops capabilities
- enables `no-new-privileges`
- bounds CPU / memory / PID count
- uses tmpfs for writable runtime directories
- redirects HOME/cache to `/tmp`
- disables network by default

Lifecycle is bounded:

```text
resolve image
→ copy Workspace
→ start container
→ initialize LSP
→ normalized provider
→ shutdown
→ exit
→ wait / terminate / kill fallback
→ CID cleanup
→ close pipes
→ delete disposable copy
```

Initialization failure follows the same cleanup discipline.

There is deliberately no native-host LSP backend in Phase 11.

## Operator surfaces

The orchestration development CLI exposes:

```text
--semantic-context
```

This means deterministic semantic expansion only. It does **not** select or start an LSP server.

The separate code-intelligence operator CLI exposes only:

```text
python -m origin_forge.code_intelligence_cli list
python -m origin_forge.code_intelligence_cli status <configured-server-id>
```

It does not expose arbitrary image, argv, raw LSP method, raw query, or code-action controls.

## Verification strategy

Phase-11-specific regression coverage includes:

- provider contract/capabilities
- Python class/method/function/nested-function classification
- Python definitions/references/syntax diagnostics
- bounded Python-only Git enumeration
- tracked-only and symlink-safe indexing
- LSP framing/message limits
- Unicode position encodings
- JSON-RPC correlation/timeouts
- one pending response slot
- notification count/byte limits
- server-request rejection
- Workspace/container URI mapping
- shared portable-path rejection
- capability negotiation
- normalized LSP evidence
- diagnostic text caps
- semantic query/file/byte budgets
- literal candidate pathspec behavior
- semantic one-shot ContextPackage integration
- semantic reselection across fresh retries
- diagnostics-as-evidence audit behavior
- config-v4 backward compatibility
- configured-server factory boundary
- safe operator CLI
- Podman isolation command/copy/local-image behavior

The final merge gate is the complete Python 3.12 + 3.13 GitHub Actions matrix on the exact final PR head.

## Deferred

Phase 11 intentionally does not include:

- native-host language-server execution
- arbitrary host shell execution
- model-controlled server image/argv
- model-controlled raw LSP requests
- internet-downloaded language-server plugins
- automatic code-action/edit application
- unbounded workspace symbol/reference/diagnostic requests
- dynamic multi-root workspace management
- diagnostics as the sole correctness oracle
- semantic/LSP context enabled by default before benchmarking
