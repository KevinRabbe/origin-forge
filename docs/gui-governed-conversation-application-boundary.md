# Governed Conversation Application Boundary

Status: **GUI architecture proposal — planning only**

This document freezes the intended application boundary required to turn the current read-only cockpit Chat Workspace into a real Origin Forge conversation surface without creating a second production control plane.

It is intentionally not a numbered backend phase. It does not authorize implementation, schema migration, HTTP mutation, model execution, Task creation, dispatch, adoption, verification, provenance signing, or release behavior.

## 1. Purpose

The cockpit now exposes a chat-first read-only workspace, exact Task workspaces, durable Run token telemetry, project token telemetry, and recent Task navigation. The remaining gap is a governed way for a human to submit a message and receive durable operator-facing responses.

A browser Send button must not:

- shell out to `origin-forge-attempt` or any other CLI;
- invoke a model adapter directly;
- call a production tool directly;
- create or transition Goals, Flows, Tasks, Runs, Artifacts, Verifications, or adoption receipts directly;
- reinterpret `state_events` as chat storage;
- make model output canonical project truth;
- bypass Manager, policy, verification, or existing durable authority boundaries.

The target layering is:

```text
CLI / GUI / future operator surfaces
              │
              ▼
     Conversation/Application API
              │
              ▼
        Manager / authority
              │
              ▼
 Goal → Flow → Task → Run → tools
              │
              ▼
   verification / durable state
```

The GUI becomes another client of the same governed application boundary, not a privileged alternate executor.

## 2. Existing architecture that must remain true

Origin Forge already separates disposable model context from durable project truth. Old model conversations must never be required to recover canonical production state.

Therefore conversation records are durable **operator intent and interaction history**, not verified product truth.

Canonical truth remains in existing governed records such as:

- Goals and Flows;
- Tasks and Runs;
- Decisions and Changes;
- Artifacts;
- Verifications;
- provenance and immutable production receipts;
- project graph and other explicitly governed durable services.

A Conversation may point to those records. It may not replace them.

## 3. Why `state_events` is not chat storage

`state_events` is an aggregate state-transition audit journal. Its contract is centered on:

- aggregate type and aggregate ID;
- event type;
- old and new state;
- revision;
- actor identity;
- bounded metadata;
- event time.

That is valuable audit evidence but it does not define:

- a conversation identity;
- ordered message identity;
- human/Forge message semantics;
- idempotent message submission;
- reply ancestry;
- attachment/context references;
- processing state;
- durable response linkage;
- conversation archival or selection semantics.

Overloading the state journal would make replay, retention, and authority ambiguous. Conversation storage must be a separate durable application concept.

## 4. Proposed durable identities

The minimum durable substrate should introduce infrastructure-owned opaque identities for two primary records.

### `ConversationSession`

One durable operator conversation within one Origin Forge project.

Proposed fields:

```text
id
project_id
status              OPEN | ARCHIVED
revision
created_at
updated_at
```

Optional human-facing title/label may be added later, but it must not be used as identity.

A session is not a Goal, Flow, or Task. One conversation may inspect or influence many production records over time.

### `ConversationTurn`

One immutable submitted or emitted operator-facing turn.

Proposed fields:

```text
id
session_id
sequence             monotonically increasing within the session
actor_type           HUMAN | FORGE | SYSTEM
content
content_hash
client_submission_id nullable; required for HUMAN submissions
created_at
```

A committed Turn is immutable. Corrections or follow-up clarification create another Turn rather than rewriting history.

`FORGE` identifies the Origin Forge application as the operator-facing responder. It deliberately does not pretend that one model is the durable author; a response may be produced through Manager decisions, deterministic services, multiple Runs, or no model at all.

## 5. Idempotent human submission

Browser retries, refreshes, double-clicks, and transport reconnects must not duplicate operator intent.

A human submission therefore carries a client-generated idempotency key:

```text
client_submission_id
```

Within a session, repeating the same key must return the existing durable submission receipt instead of appending another human Turn.

If the same key is reused with different content, submission must fail closed.

Session revision or an equivalent compare-and-swap token should protect ordering and concurrent writers.

## 6. Conversation context is a reference, not copied truth

A message may be submitted while the operator is viewing a Goal, Flow, Task, Run, Artifact, or other durable object. That context should be persisted as typed references, not as copied production payloads.

A minimal associated record can model the context captured for a Turn:

```text
ConversationTurnReference
- turn_id
- reference_type
- reference_id
- relation              FOCUS | ATTACHMENT | RESULT | EVIDENCE
- created_at
```

Requirements:

- references use infrastructure-owned durable IDs where available;
- the referenced object's own service remains authoritative;
- a stale or deleted optional reference does not rewrite conversation history;
- file bytes, secret key material, verification payloads, or unrestricted paths are not embedded merely because a browser supplied them;
- references are bounds-checked and policy-checked at submission time.

This also gives future Forge responses a durable way to link the exact Tasks, Runs, Artifacts, Decisions, or Verifications they are discussing.

## 7. Processing state must not be hidden inside message text

Accepting a human Turn and producing a Forge response are separate facts.

The application layer needs a durable processing/receipt concept so a workstation restart cannot leave ambiguous UI state.

A minimal `ConversationSubmission` or equivalent receipt should carry:

```text
id
session_id
human_turn_id
status              ACCEPTED | PROCESSING | RESPONDED | FAILED
expected_session_revision
response_turn_id    nullable
failure_code        nullable
created_at
updated_at
```

Exact naming is implementation work, but the semantics are mandatory:

- `ACCEPTED` means the human intent is durably recorded;
- `PROCESSING` means the governed application layer owns an in-flight handling attempt;
- `RESPONDED` means an immutable Forge Turn is linked;
- `FAILED` is terminal for that processing attempt and must expose a bounded operator-safe reason.

These statuses are conversation/application state. They are not Task or production status.

## 8. Typed application service

The first writable interface should be an in-process typed service, not an HTTP handler and not CLI parsing.

Conceptual API:

```text
create_session(...) -> ConversationSession
get_session(session_id) -> ConversationSession
list_sessions(...) -> bounded sessions
list_turns(session_id, ...) -> bounded ordered turns
submit_human_turn(
    session_id,
    content,
    client_submission_id,
    expected_revision,
    references=(),
) -> ConversationSubmissionReceipt
process_submission(submission_id) -> ConversationProcessingResult
```

The exact split between `submit_human_turn` and processing may evolve, but persistence of operator intent must happen before expensive model or production work.

HTTP, CLI, desktop, and future automation adapters should call this typed boundary rather than reimplement its semantics.

## 9. Authority after submission

A durable human Turn is **intent**, not automatic production permission.

After submission, a governed application/Manager layer determines the semantic class of the request. Examples include:

```text
answer / explain / inspect
continue existing work
change focus
create new Goal
request modification
request production execution
request verification
request approval-sensitive action
```

The classification result must not itself bypass existing authorities.

For production-changing intent:

1. resolve the exact governed project context;
2. use existing typed Goal/Flow/Task/application authorities;
3. record durable Manager/application decisions where required;
4. route through existing planning, dispatch, execution, verification, adoption, and provenance boundaries;
5. link resulting durable IDs back to the conversation using typed references;
6. produce an operator-facing Forge Turn describing durable facts rather than claiming unverifiable success.

A message such as "make the player faster" does not grant a browser permission to edit files. It creates durable intent that the governed application layer must interpret and execute through existing policy.

## 10. Read-only questions and production-changing requests

The application service should preserve a meaningful difference between read-only conversational work and production mutation.

### Read-only path

For inspection, explanation, status, or project questions, the response may be produced from existing read services and/or bounded model reasoning without creating production Tasks when no Task is semantically required.

Any model Run created for such a response remains a durable Run with its token/resource telemetry where appropriate.

### Production path

For requested project change, the application service should create or select governed work only through existing application/Manager contracts.

The conversation layer should not contain generic file-write or tool-call methods.

## 11. Model and Run linkage

Conversation Turns and model Runs are distinct identities.

A Forge Turn may link to:

- zero Runs for a deterministic response;
- one Run for a simple local-model response;
- multiple Runs for Manager/Executor/Auditor work.

The durable linkage should make token consumption explainable without making a Run itself the chat message.

This distinction is important for the current GUI telemetry:

```text
Conversation Turn = operator-facing interaction record
Run               = bounded execution/model activity record
Task              = governed production work record
```

They may relate, but they are not interchangeable.

## 12. Token and context telemetry semantics

The GUI already has durable Run input/output token counts. Those counters remain the source for cumulative token consumption.

Do not conflate three different concepts:

```text
Task tokens consumed     cumulative Run usage linked to one Task
Conversation tokens     cumulative usage linked to conversation processing Runs
Current model context    occupancy of one active model invocation/context window
```

The first two can be aggregated when exact durable Run linkage exists.

`Current model context used / maximum` must not be displayed until an authoritative context-window limit and current invocation context accounting are available. A cumulative Task token total is not a context-window utilization percentage.

No monetary cost field is required for the local-first product.

## 13. Compaction and summarization

Conversation history may eventually become too large for one model context, but durable history must not be destructively rewritten to solve that problem.

Future compaction should therefore produce an explicitly derived context artifact/summary with lineage to the Turns it summarizes.

Requirements:

- original durable Turns remain immutable;
- compaction affects model input construction, not historical truth;
- summary identity and source-turn range are durable;
- repeated compaction is lineage-aware;
- token savings are measurable separately from conversation history size.

## 14. Browser/API boundary

The existing cockpit remains loopback-only and GET-only today. Enabling Send is a separate reviewed security change after the application service exists.

The writable browser boundary must define at minimum:

- loopback binding requirements;
- allowed Origin/Host behavior;
- request body size and text limits;
- UTF-8 normalization policy;
- session/turn ID validation;
- idempotency key validation;
- compare-and-swap/session revision behavior;
- attachment/reference bounds;
- error response disclosure limits;
- rate/concurrency limits;
- shutdown/restart recovery;
- CSP changes required for form/fetch/SSE/WebSocket use.

The server must call the typed application service. It must not import model adapters, production stores, or tool executors as a shortcut.

## 15. Live updates

A chat UX eventually needs to observe processing without page refreshes.

Polling, Server-Sent Events, or WebSocket support must be added only after the writable application boundary is stable.

Live transport is observation of durable processing state; it must not become an alternate command channel with different authority semantics.

A reconnecting client should be able to rebuild the conversation from durable session/turn/submission reads.

## 16. Failure and recovery invariants

The conversation subsystem must survive:

- browser refresh;
- duplicate submission;
- application process crash after human Turn commit;
- model/backend crash during processing;
- workstation reboot;
- stale browser session revision;
- response generation completing after the browser disconnects.

After restart, durable state must distinguish:

- message never accepted;
- accepted but not yet processed;
- processing interrupted and recoverable;
- response durably committed;
- terminal processing failure.

No recovery path may replay production mutation merely because a chat response was not rendered to the browser.

## 17. Security and disclosure

Conversation persistence introduces user-provided text, so every rendering and transport layer must preserve hostile-text escaping and bounded payload handling.

Conversation reads must not automatically disclose:

- chain-of-thought or hidden reasoning;
- secret credentials or signing keys;
- unrestricted environment data;
- artifact bytes solely because an Artifact is referenced;
- private verification payloads beyond existing read contracts;
- raw model backend internals that existing read APIs intentionally hide.

Operator-facing Forge responses should state observable durable outcomes and bounded errors.

## 18. Minimum implementation sequence

Implementation should proceed in explicit gates.

### Gate A — durable substrate

- add Conversation Session / Turn identities and schema;
- immutable ordered writes;
- bounded read service;
- idempotent human submission receipt;
- restart/concurrency tests;
- no browser mutation yet;
- no model invocation required.

### Gate B — typed processing boundary

- add Conversation/Application service;
- connect read-only answering/inspection first;
- link responses to exact durable Runs/references where used;
- keep production mutation delegated to existing authorities;
- no browser Send yet.

### Gate C — governed production intent

- route change requests through Manager/application authority;
- exact Goal/Flow/Task linkage;
- prove conversation cannot bypass verification/dispatch/adoption policy;
- recovery/idempotence coverage for mutation-sensitive requests.

### Gate D — browser Send

- intentionally revise GET-only server/CSP constraints;
- bounded POST submission through the typed service;
- idempotency and stale-revision behavior;
- render durable conversation history;
- still no direct model/tool/store imports in the HTTP layer.

### Gate E — live UX

- polling or event stream;
- processing/activity updates;
- exact Run/token telemetry beside the conversation;
- reconnect from durable state.

## 19. Explicit non-goals for the first implementation

Do not introduce these as part of the initial conversation substrate:

- generic autonomous agent swarm messaging;
- model chain-of-thought persistence;
- arbitrary CLI execution;
- arbitrary file-system attachments;
- browser-selected model/provider overrides;
- browser-selected production tool overrides;
- direct browser Task state transitions;
- monetary token pricing;
- fabricated context-window percentages;
- conversation history as verified project truth;
- hidden automatic production replay after transport failure.

## 20. Acceptance invariants

Before the composer can be unlocked, all of the following must be demonstrably true:

1. A human submission has an infrastructure-owned immutable Turn identity.
2. Duplicate client submissions are idempotent.
3. Conversation ordering survives restart and concurrent clients.
4. A committed human Turn does not itself mutate production state.
5. Production-changing intent uses existing governed application/Manager authorities.
6. Browser/server code cannot invoke model adapters, tools, stores, or production mutation directly.
7. Forge responses link to durable facts and Runs rather than fabricating success.
8. Conversation history can be reconstructed without old model context.
9. Canonical project recovery does not depend on conversation history.
10. Token telemetry remains derived from exact durable Run counters and explicit completeness semantics.
11. Interrupted processing is distinguishable from a lost/unaccepted message.
12. Recovery cannot duplicate production mutation because a response delivery failed.

## 21. Permanent boundary

The intended invariant is:

> Conversation records durable human intent and operator-facing history. The governed application layer decides what that intent means. Existing Origin Forge authorities own production mutation and verification. The browser owns neither.

That boundary allows the GUI to become the primary Origin Forge workspace without weakening the infrastructure-first architecture that makes the system recoverable and trustworthy.
