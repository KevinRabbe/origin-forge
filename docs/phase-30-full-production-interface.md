# Phase 30 — Full Production Interface

Status: **IMPLEMENTED — exact-head closure gate pending**

Phase 30 adds a human-facing local production cockpit over durable Origin Forge state without creating a second authority or truth layer.

## Core rule

```text
authoritative services/state
        ↓
bounded read-only projections
        ↓
content-addressed snapshot
        ↓
escaped static presentation
        ↓
human inspection
```

The interface may summarize, navigate, and explain existing state. It does not bypass `OriginForgeRuntime`, verification gates, protected state, model/tool governance, provenance, Dream downstream gates, or promotion rules.

## Implemented v1 surface

### Runtime and causal state

- deterministic bounded Goal / Flow / Task / Run / Verification snapshots;
- explicit total counts and truncation evidence;
- causal Decision → Change → Artifact → Artifact Verification navigation;
- Task → Run / Verification / Change relationships;
- no Verification evidence/metrics, approved command arrays, arbitrary SQL, or raw store rows;
- Artifact metadata only in v1; arbitrary Artifact file bytes are not previewed or served.

### Project Intelligence and Design Bible

- SELECT-only bounded Entity, relation, binding, and Design Rule projections;
- Entity detail pages with related relations, bindings, and scoped Design Rules;
- relation evidence refs and binding metadata remain withheld;
- the cockpit does not expose the mutable Phase-17 service as a UI authority surface.

### Model and resource monitor

- protected config version, configured capacity, model profiles, selection policies, and admission state;
- inspection uses fresh process-local scheduling state with zero resource leases;
- opening the cockpit does not load a model, acquire a lease, invoke a runtime loader, or change routing.

### Public provenance inspector

- non-creating inspection of stored Phase-18 Company Root, operational certificates, revocations, and signed provenance manifests;
- strict bounded canonical-envelope/content-hash validation before display;
- protected-root and symlink containment validation, including parent-registry alias rejection;
- public fingerprints/signature hashes and Artifact/Task/Run bindings may be displayed;
- public-key DER, detached signature bytes, secret key material, Artifact bytes, Skill/tool lists, and private signing handles are not disclosed;
- the cockpit explicitly does **not** claim Ed25519 trust verification or Artifact-currentness verification. Those remain Phase-18 verification concerns.

### Dream and memory inspector

- non-creating inspection of immutable Dream input manifests, candidates, audits, derived-memory entries, and memory generations;
- strict canonical/hash validation and nested `dream/memory` containment checks;
- bounded candidate summaries/actions, audit status/finding codes, derived-memory claims, and generation lineage;
- raw Dream evidence refs and audit finding messages remain withheld;
- opening the cockpit cannot run a Dream cycle, promote memory, mutate Skills/routing/context, or change production state.

### Presentation and network boundary

- repository-owned static HTML with strict escaping of untrusted project/model text;
- CSP disables scripts, forms, connections, frames, objects, and external resources;
- fixed route set only; query strings, fragments, absolute request targets, traversal, and malformed typed IDs fail closed;
- loopback-only `127.0.0.1` HTTP bind;
- no arbitrary static/project file serving;
- every non-GET method returns 405;
- fresh bounded snapshot per request;
- response byte ceiling and `no-store`, `nosniff`, frame/referrer security headers.

### Operator surface

The Phase-30 CLI exposes only:

- `snapshot`
- `serve`

There is no host override, browser launch, model/tool/process execution command, Task mutation, adoption, signing, merge, or release command.

## Read-side mutation boundary

A read-only UI must also be non-mutating merely by opening it. Phase 30 therefore does not reuse store listing methods that create directories as a side effect. Dedicated provenance and Dream readers treat absent registries as empty and validate every existing registry path component before reading it.

```text
missing optional registry → empty view
corrupt / aliased registry → fail closed
valid registry → bounded validated projection
```

## Authority boundary

Visibility is not authority. In particular:

- rendering a Verification does not create or change one;
- rendering an Artifact does not adopt, sign, publish, or read arbitrary Artifact bytes;
- rendering model/resource status does not load or route a model;
- rendering provenance does not sign or establish fresh cryptographic trust/currentness;
- rendering a Dream candidate does not satisfy its downstream gate or promote it;
- rendering a Task does not complete, retry, or mutate it;
- HTTP reachability grants no new model/tool/process authority;
- the cockpit has no merge or release authority.

## v1 exit condition

Phase 30 v1 is complete when one immutable repository head proves that Origin Forge can:

1. run a bounded loopback-only production cockpit over authoritative durable state;
2. navigate runtime and causal evidence without a second truth store;
3. safely render hostile/untrusted text as inert HTML;
4. expose Project Intelligence and Design Bible through narrowed read facades;
5. expose model/resource configuration and admission state without model loading or leasing;
6. inspect public provenance without registry creation, secret access, signature-trust claims, or Artifact-currentness claims;
7. inspect Dream/memory generations without registry creation, automatic promotion, or production mutation;
8. keep Artifact bytes and Verification evidence/metrics outside the v1 presentation surface;
9. expose only fixed GET routes and the `snapshot` / `serve` operator commands;
10. preserve all existing Task, adoption, signing, promotion, merge, and release authority boundaries;
11. pass the normal Python 3.12 and 3.13 matrix on the exact immutable closure head with unrelated heavyweight evidence workflows skipped.

Artifact-byte/media preview rendering, mutation workflows, production approvals, and remote/multi-user hosting remain separate future capabilities rather than implicit authority added by Phase 30 v1.
