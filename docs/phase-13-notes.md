# Phase 13 — Tool Search & Progressive Disclosure

Status: **development candidate; exact-head hosted CI required before merge**

Phase 13 adds the discovery layer needed for local models to operate over a large capability catalog without receiving every full tool schema in every prompt.

The central rule is:

> Tool Search reduces disclosure. It does not grant authority.

## Why this exists

A mature Origin Forge installation may eventually contain hundreds of capabilities:

```text
repository/Git
compiler/tests/LSP
Pixelorama
Blockbench
image models
vision
SFX/music/TTS
runtime automation
playtesting
release/build tooling
future plugins
```

Putting every full JSON schema into every Executor context wastes tokens and makes smaller local models choose among too many irrelevant actions.

Phase 13 changes disclosure from:

```text
Executor prompt
└── every authorized full tool schema
```

to:

```text
Executor prompt
├── search_tools
└── describe_tool
        ↓
hidden authorized catalog
        ↓
compact matches
        ↓
full schema only when needed
```

## Immutable tool descriptors

`ToolDescriptor` defines the stable contract metadata for one capability:

- stable `tool_id`
- trusted description
- capabilities
- search keywords
- side-effect classes
- deterministic flag
- reversible flag
- input JSON schema
- output JSON schema
- permissions
- required resources
- timeout
- verification method
- SHA-256 content hash / stable ref

Side effects are explicit:

- `READ`
- `WRITE`
- `EXECUTE`
- `NETWORK`

An empty effect set means no declared external side effect.

Descriptors canonicalize schemas to JSON strings when constructed. Mutating the caller's original dictionary afterward therefore cannot change the registered contract or hash.

Schema bytes, depth, node count, descriptions, capabilities, keywords, permissions, and resources are bounded.

## Catalog snapshots

`ToolCatalogSnapshot` is immutable and content-addressed.

It:

- sorts tools deterministically
- rejects duplicate IDs
- bounds catalog size
- records exact descriptor refs
- computes a catalog SHA-256

A running Executor discovers against one snapshot rather than a mutable live registry. Tool installation/removal therefore cannot change that Executor's hidden catalog halfway through a Task.

## Authority before discovery

`AuthorizedToolView` is created from a catalog snapshot plus externally determined allowed tool IDs.

This ordering is fundamental:

```text
full trusted catalog
        ↓
Manager/security authority decision
        ↓
authorized immutable view
        ↓
Tool Search
```

not:

```text
search everything
→ model chooses authority
```

The view has its own `authority_hash` derived from the catalog snapshot and exact allowed descriptor refs.

A hidden tool is absent from search. Guessing its ID through `describe_tool` produces the same denial class as an unknown ID.

Tool Search itself has no path that adds a tool to the view.

## Deterministic search

`ToolSearchSession.search_tools()` uses bounded deterministic lexical ranking over trusted metadata.

Evidence weights prioritize:

```text
capability terms    highest
stable tool ID
keywords
description         lowest
```

There is no arbitrary fallback tool. An unrelated query returns no results.

Search bounds include:

- query characters
- query terms
- searches per Executor session
- results per search
- compact search-description length

Results expose compact metadata only:

- tool ID/ref
- relevance score
- bounded description
- capabilities
- effects
- deterministic flag

Input/output schemas are deliberately absent.

## Schema hydration

`describe_tool(tool_id)` hydrates the full descriptor only for an already-authorized ID.

It records:

- descriptor hash/ref
- catalog hash
- authority hash
- full input/output schemas
- permissions/resources/effects/verification metadata

Hydrated unique-tool count is bounded. Re-describing the same tool does not consume another unique hydration slot.

Hydration still grants no invocation authority.

## Constant model-facing protocol

`ToolDiscoveryGateway` exposes exactly two meta-tools:

```text
search_tools(query, limit?)
describe_tool(tool_id)
```

The meta schemas are constant-size and independent of catalog size.

There is deliberately no `call_tool` operation in Phase 13.

The gateway strictly validates operation arguments and caps:

- request JSON bytes
- cumulative response JSON bytes

The cumulative response budget includes both compact searches and full descriptor hydration, preventing progressive disclosure from becoming an unbounded context dump over many calls.

Every response carries enough identity to tie it to the exact catalog/authority snapshot.

## Discovery trajectory

The session keeps a bounded-by-operation-budget in-memory trajectory:

- search query
- ordered result tool IDs
- described tool IDs
- deterministic ordinal

Schemas are not copied into search trajectory events.

A later observability phase can persist these events into `RUN` provenance with appropriate secret/redaction policy.

## Byte-footprint benchmark

`measure_tool_disclosure()` compares:

```text
full_authorized_schema_bytes
```

against:

```text
constant meta-tool schema bytes
+ actual discovery response bytes
```

It reports:

- authorized tool count
- hydrated tool count
- searches used
- full-schema UTF-8 JSON bytes
- meta-schema bytes
- discovery-response bytes
- progressive total bytes
- bytes avoided
- progressive/full ratio

This intentionally measures serialized bytes, **not tokens**. Model/tokenizer-specific token measurements belong in later model-profile benchmarks.

A small catalog can legitimately have negative savings; Tool Search should be enabled where measured catalog size/model behavior justifies it.

## Trust boundary

Phase 13 descriptors are trusted Origin Forge/internal registration data.

Untrusted Internet/plugin manifests must not be inserted directly into a live catalog. Future external plugins require the planned path:

```text
download/quarantine
→ static scan
→ permission inspection
→ sandbox evaluation
→ human approval
→ signature/trusted local registry
→ descriptor registration
```

Tool descriptions are instructions-adjacent metadata, so treating arbitrary external descriptions as trusted would be a prompt-injection path.

## Relationship to execution

Phase 13 intentionally does **not** introduce a generic invocation registry.

Existing execution authority remains where it already lives:

- RepositoryReader containment
- isolated Git worktrees
- deterministic patch applier
- sandbox verification
- trusted configured LSP backend
- explicit operator policies

A later invocation gateway may add `call_tool` only after it can enforce the same authority, side-effect, resource, audit, and verification contracts at the call boundary.

The intended future flow is:

```text
Task Contract / role authority
→ authorized ToolCatalogSnapshot view
→ search_tools
→ describe_tool
→ selected tool contract
→ governed invocation gateway
→ hooks / resource scheduler / provenance / verification
```

## Model relationship

A local model should normally receive only the two meta-tool schemas up front.

This is especially valuable for smaller local models because:

- fewer irrelevant schemas compete for attention
- prompt footprint stays nearly constant as catalog size grows
- exact schema is loaded just-in-time
- model choice can be benchmarked with and without Tool Search under the same Task set

Tool Search is infrastructure, not intelligence. If a model searches poorly, Origin Forge can improve ranking/Skills/model profiles without changing tool authority.

## Regression coverage

Phase-13-specific tests cover:

- immutable/detached descriptor schemas
- descriptor hash changes on contract changes
- deterministic catalog hashes independent of registration order
- duplicate/count bounds
- authority subsets and hashes
- unknown authority IDs rejected before discovery
- schema size/depth/finite-JSON validation
- explicit sorted side effects
- authorized-only search
- no arbitrary search fallback
- deterministic relevance ordering
- query/search/result budgets
- compact search results excluding schemas
- full hydration only through describe
- hidden/unknown ID denial equivalence
- unique hydration budget
- bounded search descriptions
- deterministic discovery trajectory
- constant two-meta-tool model surface
- strict gateway argument validation
- no `call_tool`
- hidden tools staying hidden through the gateway
- cumulative discovery-response byte bounds
- disclosure footprint measurement
- authority-mismatch protection in metrics

## Deferred

Not included in Phase 13:

- generic `call_tool`
- model-controlled authority changes
- persistent external plugin installation
- executable plugin code
- Internet plugin discovery
- semantic/embedding tool search
- learned tool router
- Code Mode
- automatic tool chaining
- tool-result persistence into RUN provenance
- resource scheduling across tool calls
- tokenizer-specific Tool Search savings claims
