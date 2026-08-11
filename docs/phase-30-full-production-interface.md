# Phase 30 — Full Production Interface

Status: **IN PROGRESS — read-only production cockpit first**

Phase 30 builds a human-facing interface over the durable Origin Forge runtime without creating a second authority or truth layer.

## Core rule

```text
authoritative services/state → bounded projection → escaped presentation → human inspection
```

The interface may summarize, navigate, and explain existing state. It does not bypass `OriginForgeRuntime`, verification gates, protected state, model/tool governance, provenance, or downstream promotion rules.

## First v1 boundary

The first implemented slice is intentionally read-only:

- deterministic bounded snapshots over Goal / Flow / Task / Run / Verification state;
- fixed projections rather than raw SQLite rows or arbitrary SQL;
- verification evidence/metrics and approved command arrays excluded from presentation;
- explicit section limits and truncation evidence;
- repository-owned HTML rendering with strict escaping;
- a fixed read-only router and loopback-only HTTP server;
- operator commands limited to snapshot inspection and serving the cockpit;
- no arbitrary static-file serving, project-file browser, shell/process execution, model invocation, key access, Task mutation, adoption, signing, merge, or release surface.

Later panels may expose Project Intelligence, Artifacts, provenance, Dream/memory, model/resource state, media evidence, simulations, playtests, training-research evidence, and causal history, but only through their existing governed read APIs or new explicitly read-only projections.

## Authority boundary

The interface is never authoritative merely because a value is visible in the UI. In particular:

- rendering a Verification does not create or change one;
- rendering a model/resource status does not load or route a model;
- rendering an Artifact does not adopt, sign, or publish it;
- rendering a Workshop/Training result does not activate a candidate;
- rendering a Task does not complete, retry, or mutate it;
- HTTP reachability does not grant any new model/tool/process authority.

All mutation paths remain outside the first cockpit slice.

## Initial exit condition

Phase 30 v1 is complete when one immutable repository head proves that Origin Forge can run a bounded local production cockpit over authoritative durable state, navigate causal evidence, safely render untrusted project text, expose representative subsystem status through read-only projections, and preserve all existing authority boundaries under Python 3.12/3.13 CI.
