# Phase 27 — Code Mode and Programmatic Context Experiments

Status: **IN PROGRESS — governed read-only program experiment substrate**

Phase 27 evaluates whether a model can reduce repeated round trips and oversized prompt context by emitting a bounded mini-program that performs multiple **read-only, infrastructure-authorized context operations** before returning one reconstructable evidence package to the next model invocation.

It does not introduce arbitrary model-written Python, JavaScript, shell, SQL, filesystem traversal, generic process authority, or automatic Phase-26 promotion.

## Core rule

```text
frozen task / evidence request
        ↓
model proposes inert bounded program
        ↓
infrastructure validates exact operation catalog + budgets
        ↓
deterministic read-only interpreter
        ↓
registered governed context adapters only
        ↓
content-addressed execution trace + context package
        ↓
independent experiment / benchmark evidence

program output = context evidence
program output != production authority
```

## Why a restricted program first

The roadmap calls for sandboxed model-written mini-workflows, but the first useful experiment does not require a general-purpose language. A tiny straight-line dataflow program can already test the key hypothesis:

> Can one bounded model-authored program discover and assemble sufficient governed context with fewer model round trips / tokens while preserving reliability and reconstructability?

A general-purpose runtime would add loops, recursion, imports, subprocesses, filesystem/network APIs and hidden state before Origin Forge has evidence that any of those capabilities are needed. Phase 27 therefore begins with a deliberately weaker program representation.

## Program contract

A v1 `ContextProgram` is immutable canonical JSON data with infrastructure-owned identity and content hash. It binds:

- exact program format/version;
- exact operation-catalog ID/hash;
- exact input request ID/hash;
- a bounded ordered instruction list;
- declared final output bindings;
- instruction, invocation, result-byte and aggregate context-byte budgets.

The first interpreter is **straight-line only**:

- no loops;
- no recursion;
- no branches whose condition can introduce an undeclared operation;
- no dynamic/evaluated operation names;
- no function definitions/imports;
- no strings interpreted as executable source;
- no hidden mutable scratch state outside declared bindings.

Instructions may reference only earlier immutable bindings or literal bounded JSON values. Rebinding an existing name is rejected.

## Operation catalog

Program execution uses an infrastructure-owned `ContextOperationCatalog`. A model sees only disclosed descriptors; it cannot register an adapter or widen its authority.

Every operation descriptor binds:

- stable operation ID/version;
- exact adapter fingerprint;
- input/output schema identity;
- maximum calls per program;
- maximum response bytes;
- effect class, which is `READ_ONLY` in v1;
- deterministic/replay classification;
- evidence class emitted by the adapter.

The catalog itself is content-addressed. A program written against one catalog hash cannot execute against another.

Phase 27 does **not** turn Phase-13 Tool Search into generic `call_tool`. Tool search/description may be exposed through a dedicated read-only context adapter; arbitrary ToolDescriptor execution remains outside v1.

## Programmatic context adapters

The intended adapter families are narrow façades over existing governed read surfaces, for example:

- exact Run / Artifact / Verification lookup;
- bounded failed-attempt or recent-run search;
- Project Intelligence Entity / impact context;
- active Dream/Memory lookup;
- governed Skill description;
- Phase-13 Tool search / description;
- bounded source/context evidence already available through existing deterministic selectors.

Adapters are added only when the underlying read API has a stable contract. Each adapter must revalidate project scope, IDs, hashes/revisions where applicable, limits and returned evidence before exposing data to the program.

No adapter may expose:

- unrestricted SQL;
- arbitrary path reads or traversal;
- generic HTTP/network access;
- environment variables or host secrets;
- subprocess/process launch;
- source/config mutation;
- Task state mutation;
- Skill/prompt/routing/context activation;
- signing, merge or release operations.

## Interpreter

`ContextProgramInterpreter` is infrastructure code, not model-authored code. It:

1. validates exact request/program/catalog binding;
2. enforces hard instruction and total invocation budgets;
3. resolves each declared operation through the frozen catalog;
4. validates exact literal/reference argument structure before dispatch;
5. invokes the registered read-only adapter;
6. bounds and canonicalizes the result before binding it;
7. records operation ID/version/fingerprint, canonical input hash, output hash/size and status;
8. assembles only declared final bindings into the returned context package;
9. enforces aggregate output/context limits;
10. emits a complete content-addressed execution trace.

Infrastructure errors are distinct from an operation returning zero matching evidence. A failed program cannot silently return a partial package as successful evidence unless the program contract explicitly declares an optional operation and the trace records that condition.

## Evidence and replay

A completed execution records:

- exact input request/hash;
- exact program/hash;
- exact operation catalog/hash;
- ordered step trace;
- exact adapter fingerprints;
- canonical per-call input/output hashes and sizes;
- total operation count;
- total result/context bytes;
- execution duration/resource counters where available;
- final context-package hash.

Deterministic adapters may be replay-compared exactly. Time-varying read adapters must declare that property and bind the durable source revisions/timestamps used by the result rather than pretending replay equivalence.

The context package is evidence for a later model invocation. It cannot verify a production Task or mutate canonical state.

## Benchmark boundary

Phase 27 is explicitly experimental. A later benchmark compares a conventional bounded context path against programmatic context using frozen tasks/cases and measures at least:

- task/evaluation success;
- model calls / round trips;
- input/output tokens;
- disclosed context bytes;
- operation count;
- wall time / resource cost;
- missing-evidence or wrong-evidence failures;
- deterministic/replay drift where applicable.

Regression remains dominant. A cheaper program that reduces correctness is not an improvement.

Phase 27 experiment results may become Phase-26 `MINI_WORKFLOW` or `CONTEXT_STRATEGY` candidate evidence, but Phase 26 v1 deliberately has no trusted promotion-capable evaluator for those families. Phase 27 therefore does not create an automatic promotion path.

## Long-lived work

Long-lived activity continues to use durable Origin Forge Goal/Flow/Task/Run/evidence state plus fresh bounded model invocations. Phase 27 does not introduce a persistent autonomous model process with private evolving memory.

A program is finite inert data. Its execution trace is durable evidence. A later model invocation receives a reconstructable bounded package rather than inheriting hidden interpreter/model state.

## Recursive delegation

v1 has no delegation instruction. Future nested programs, if ever justified by measurement, must satisfy:

```text
child authority ⊆ parent authority
child budget    ⊆ remaining parent budget
```

and must preserve an explicit parent/child evidence chain. Recursive delegation may never increase the operation catalog or authority surface.

## Initial v1 implementation checkpoints

1. immutable IDs/models for request, operation catalog, program, execution trace and context package;
2. strict straight-line instruction/reference semantics and hard structural/resource bounds;
3. infrastructure-owned read-only adapter registry with exact fingerprints;
4. deterministic interpreter with canonical per-step evidence and fail-closed dispatch;
5. at least one real adapter over an existing governed Origin Forge read surface plus adversarial fake adapters;
6. durable bounded evidence persistence and read-only inspection;
7. replay/containment/authority regressions;
8. paired experiment harness measuring baseline vs programmatic context without production activation authority;
9. canonical roadmap closure only after exact-head Python 3.12/3.13 CI is green.

## Explicit exclusions in v1

Not implemented or authorized:

- arbitrary Python / JavaScript / shell / bytecode execution;
- arbitrary SQL;
- arbitrary filesystem traversal or path reads;
- generic process/network access;
- unrestricted Phase-13 tool invocation;
- dynamic code download/import;
- persistent hidden autonomous scratch memory;
- unbounded loops/recursion/branching;
- peer-agent authority transfer;
- production Task verification/completion;
- source/config mutation;
- active Skill/prompt/routing/context replacement;
- candidate activation;
- provenance signing;
- merge/release authority;
- automatic Phase-26 promotion.

## Initial exit condition

Phase 27 v1 is complete when one immutable repository head proves that Origin Forge can execute a model-proposable but inert bounded read-only program over an exact governed operation catalog, emit a fully reconstructable context package and execution trace, measure the approach against a conventional context baseline, and demonstrate that neither the program nor its adapters gain generic tool/process/filesystem/Task/activation/signing/merge/release authority.
