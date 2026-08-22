# GUI — Governed Blender Production Task Acceptance Boundary

Status: **FROZEN ARCHITECTURE PROPOSAL — planning only**

This document defines the first post–conversation-Gate-E writable production action that may be exposed in the local Origin Forge GUI: explicit human acceptance of one exact already-dispatched, already-canonically-adopted Blender production result through the accepted Phase-53 application authority.

This planning document does **not** authorize implementation by itself. It changes no runtime, schema, tests, HTTP routes, HTML/CSS/JS, production authority, package entrypoints, release records, or immutable Phase-53 evidence.

The core rule is:

```text
conversation-linked exact production Task
        ↓
read-only Blender acceptance action projection
        ↓
explicit local human confirmation
        ↓
typed GUI application action service
        ↓
GovernedBlenderProductionTaskAcceptor
        ↓
existing Phase-53 currentness / PASS / Task-transition laws
        ↓
render exact durable result
```

The browser remains a client. It never becomes Task, Verification, Artifact, filesystem, Blender, signing, merge, deployment, or release authority.

## 1. Why this is the next GUI slice

The governed conversation foundation is already implemented through Gate E:

- durable Conversation Sessions / Turns / Submissions;
- typed read-only processing;
- governed production intent through existing Goal/bootstrap/Manager authority;
- bounded loopback browser Send;
- durable live polling, processing/activity state, exact referenced Task Run/token telemetry, and reconnect reconstruction.

That architecture intentionally ends at Gate E. There is no pre-authorized generic “Gate F” production-action channel.

Phase 53 separately established one exact production mutation that is explicitly human-only and documented for future UI integration:

```text
accept one exact Blender DISPEXEC-*
→ validate exact Phase-51 dispatch truth
→ validate exact Phase-52 PUBLISHED adoption truth
→ validate current canonical GLB before first acceptance
→ publish/reuse exact HUMAN_OPERATOR Task PASS + immutable receipt
→ use existing Task RUNNING → SUCCEEDED transition law
```

The Phase-53 closure explicitly permits a future UI to display the read-only acceptance state and invoke the same governed acceptor after explicit human confirmation. It explicitly forbids direct Task/Verification writes, file mutation, validation duplication, automatic acceptance, Blender replay, signing, merge, deployment, and release.

Therefore the smallest safe next GUI capability is **one Blender-specific acceptance action**, not a generic action bus, tool launcher, Task mutation API, or browser-side production router.

## 2. Repository baseline

This architecture starts from exact current `main`:

```text
b35be76ffd8227a15df0d93eb94656e35afd3e88
```

That mainline includes:

- governed conversation Gates A–E;
- Phase-51 governed Blender production dispatch;
- Phase-52 create-only Blender output adoption;
- Phase-53 human-only Blender production Task acceptance and terminalization;
- the Phase-53 implementation closure.

The accepted Phase-53 currentness states are exactly:

```text
NOT_ACCEPTED
ACCEPTED_PENDING_TASK_TRANSITION
ACCEPTED_TASK_SUCCEEDED
STALE_OR_CONFLICTING
```

The accepted mutation boundary is `GovernedBlenderProductionTaskAcceptor.accept(...)`, keyed by one exact `DISPEXEC-*` plus optional normal operator attribution.

## 3. Permanent authority boundary

### 3.1 What the browser may own

The browser may own only presentation and explicit user intent:

- display an exact eligible Blender acceptance action;
- display read-only currentness and service-derived production identities;
- require an explicit confirmation gesture;
- submit one bounded same-origin form for that already-displayed action;
- display the exact bounded result or fail-closed error state;
- observe durable action state after redirect/reconnect.

### 3.2 What the browser may never own

The browser must not:

- write Task status directly;
- create/update/delete Verification rows;
- create/update/delete Phase-53 acceptance rows;
- select or override Task, Run, Artifact, Verification, WorkOrder, binding, MODEL3D request, path, hash, size, Blender runtime/profile/version/runner/workspace/operation, PASS value, verifier, force/bypass, signing, merge, deployment, or release authority;
- copy, replace, rewrite, move, delete, or overwrite the adopted GLB;
- call Blender;
- call a model or specialist to synthesize acceptance;
- duplicate Phase-53 currentness, lineage, hash, byte-count, or GLB validation in presentation code;
- automatically retry stale/conflicting authority;
- accept automatically because live polling observes an eligible state;
- convert conversation text, a model score, vision result, or specialist finding into `HUMAN_OPERATOR` acceptance.

### 3.3 HTTP is transport, not production authority

`production_interface_server.py` must remain a transport/router layer. It must not import or call:

- `GovernedBlenderProductionTaskAcceptor` directly;
- Phase-53 publication primitives;
- Task transition helpers;
- raw acceptance/adoption/dispatch stores;
- Blender execution adapters;
- model/specialist/tool execution code.

The server may import only the dedicated typed GUI application action boundary defined by this architecture.

## 4. Action discovery must start from durable conversation context

The first GUI version must not expose a free-form `DISPEXEC-*` text box or generic production-action endpoint.

An acceptance action may be displayed only when it is derived from an exact Task already referenced by the selected durable conversation state.

The discovery flow is:

```text
selected ConversationSession
→ bounded durable Conversation Turn TASK/RESULT references
→ exact project-owned Task identities
→ read-only Blender production execution relation discovery
→ exact Phase-53 currentness inspection
→ bounded GUI action projection
```

Presentation code must not query SQLite to discover executions.

If a referenced Task has no Blender production relation, no Blender acceptance action is displayed.

If production identity discovery is ambiguous or conflicting, the UI must expose a non-actionable stale/conflicting state rather than selecting one candidate heuristically.

No objective text, title, path string, model output, latest-created heuristic, or browser-provided ID may substitute for durable identity linkage.

## 5. Typed read-only GUI action projection

Implementation must add an application-layer read projection separate from HTML and HTTP.

The projection should expose only bounded service-derived fields needed by the operator, conceptually:

```text
BlenderTaskAcceptanceActionView
- conversation_session_id
- task_id
- execution_id
- status
- acceptance_eligible
- accepted
- adopted_artifact_id
- adopted_destination_path
- accepted_content_hash
- accepted_byte_count
- model3d_request_id
- task_verification_id
- task_revision
- detail                 bounded operator-safe text or null
```

Exact implementation naming may differ, but these semantics are frozen.

The projection may compose accepted read-only production-domain APIs and a narrow read-only identity-discovery helper. It may not mutate production state or invoke external execution.

The projection must derive destination/hash/size/MODEL3D identity from durable Phase-51/52/53 authority. Those values must never come from browser fields.

### 5.1 Bounds

The action projection must be bounded:

- only Tasks already present in the bounded selected conversation live state are considered;
- at most a small code-owned number of production actions is returned per conversation render/live payload;
- deterministic ordering is required;
- truncation must be explicit if the bound is reached;
- detail/error text must be bounded and operator-safe.

The UI must not scan the whole production database on every poll.

## 6. Typed GUI mutation service

The mutation boundary must be an in-process application service outside the HTTP/presentation module.

Conceptually:

```text
accept_conversation_blender_task(
    runtime,
    conversation_session_id,
    execution_id,
) -> BlenderTaskAcceptanceActionResult
```

The exact name may differ, but the service must:

1. validate canonical Conversation and DISPEXEC identities;
2. confirm the selected execution is the exact Blender production relation for a Task currently linked to that conversation’s bounded durable Task result context;
3. refuse ambiguous/unlinked execution substitution;
4. delegate acceptance exactly once to `GovernedBlenderProductionTaskAcceptor(runtime).accept(execution_id, ...)`;
5. project only the accepted typed result or bounded error;
6. perform no direct Task/Verification/receipt/file mutation itself;
7. invoke no Blender, model, specialist, Manager, dispatch, signing, merge, deployment, or release path.

### 6.1 Operator attribution

The first local GUI version must not accept arbitrary browser-controlled `actor_id` text.

The application action service should use a code-owned local-GUI operator attribution or the acceptor’s reviewed default attribution semantics.

Authentication/multi-user attribution is a separate future architecture question and must not be improvised inside this loopback action.

## 7. Explicit confirmation semantics

First acceptance from `NOT_ACCEPTED` requires an explicit human form submission.

The rendered action must clearly distinguish:

```text
NOT_ACCEPTED
  → action label: Accept Blender production Task

ACCEPTED_PENDING_TASK_TRANSITION
  → recovery state is visible
  → any recovery call requires a separate explicit operator action
  → no automatic retry from polling/reconnect

ACCEPTED_TASK_SUCCEEDED
  → terminal accepted state
  → no enabled mutation control

STALE_OR_CONFLICTING
  → fail-closed state
  → no enabled mutation control
```

The UI must not make `NOT_ACCEPTED` look like a routine “continue” button. The confirmation text must state that the operator is accepting the exact canonically adopted Blender result against the production Task contract.

It must also state that this does **not** sign provenance or authorize release.

## 8. Browser transport

The first accepted transport should remain a normal server-rendered form POST with POST/Redirect/GET behavior. JavaScript may enhance presentation later but must not be required to exercise the action.

Frozen route shape:

```text
POST /conversation/<CONV-ID>/actions/blender-task-acceptance
```

The form body is intentionally small and exact.

Allowed browser-supplied fields:

```text
execution_id
confirmation
```

`confirmation` must equal one fixed code-owned value. It is a human-intent signal, not production authority.

No Task/Run/Artifact/Verification/path/hash/revision/status/verifier/model/runtime/force/sign/release field is accepted.

### 8.1 HTTP checks

The writable route must preserve Gate-D framing/security rules:

- loopback-only server binding;
- exact loopback Host validation;
- exact same-origin `Origin` validation;
- bounded exactly framed request body;
- no Transfer-Encoding ambiguity;
- strict UTF-8 form semantics;
- exact field set and single values;
- canonical `CONV-*` / `DISPEXEC-*` validation;
- conservative bounded error responses;
- POST/Redirect/GET on success.

Unknown or malformed production-action routes return fail-closed HTTP results and never fall through to another mutation path.

### 8.2 Status mapping

Transport status is mechanical, not production truth.

Recommended mapping:

```text
303  governed action completed; redirect to workspace
400  malformed form / confirmation / ID
403  Host/Origin violation
404  conversation or displayed action relation not found
409  stale/conflicting/unlinked action state
500  bounded application action failure
```

The exact accepted Task status is read back through the typed action projection after redirect/reconnect.

## 9. No-JavaScript and live UX behavior

The action must work with JavaScript disabled.

Normal flow:

```text
render exact current action
→ human submits form
→ server delegates typed action once
→ 303 redirect
→ page rebuilds from durable state
```

Gate-E JavaScript may later update the displayed action status through the existing same-origin GET polling channel.

The polling script must never submit, retry, resume, or auto-confirm acceptance.

If live polling observes `ACCEPTED_PENDING_TASK_TRANSITION`, it may update the display only. Recovery remains a separate explicit human POST.

A browser reconnect must reconstruct the action solely from durable conversation + production state.

## 10. Relationship to conversation history

The first action slice must not automatically fabricate a Forge chat Turn merely because an acceptance POST succeeded.

The durable Phase-53 receipt, Task PASS, Task state event, and conversation-linked read projection are sufficient production facts.

A later architecture may define explicit operator-facing action-event Turns if they provide measurable value, but that must not make conversation history the source of production truth.

## 11. Idempotence and recovery

The GUI inherits Phase-53 semantic idempotence; it must not implement a second idempotency model for production acceptance.

### Same exact acceptance replay

Repeated explicit submission for the same exact accepted execution may converge through the accepted Phase-53 idempotent behavior.

The GUI application service must not create duplicate Task PASS or receipt state itself.

### Pending transition

If Phase-53 PASS/receipt is durable but Task transition is still pending:

- the read projection shows `ACCEPTED_PENDING_TASK_TRANSITION`;
- no automatic recovery is executed;
- an explicit operator recovery action may call the same accepted acceptor;
- the same receipt/PASS is reused;
- Blender is never replayed;
- the GLB is never rewritten.

### Stale/conflicting state

`STALE_OR_CONFLICTING` is non-actionable in the first GUI implementation.

The UI must not repair, replace, retry, reinterpret, or choose alternate authority automatically.

## 12. Security properties

Tests must prove at least:

- cross-origin POST cannot call the action service;
- malformed Host cannot call the action service;
- malformed/extra form fields fail before application mutation;
- a valid DISPEXEC belonging to another conversation-linked Task cannot be substituted through form tampering;
- a valid project execution not linked to the selected conversation cannot be accepted through this UI route;
- Task/Run/Artifact/path/Verification/revision/force/release override fields are rejected;
- GET, polling, page render, asset GET, and action projection are read-only;
- JavaScript contains no production POST/auto-accept path;
- HTTP/presentation source does not import the Phase-53 acceptor, production stores, Blender adapter, model adapter, specialist, Manager, or direct Task transition APIs;
- the application action service delegates to exactly one reviewed Phase-53 acceptor call site;
- exact same-action replay creates no duplicate acceptance;
- stale/conflicting currentness creates no mutation;
- successful acceptance does not mutate the adopted GLB bytes;
- successful acceptance does not sign provenance or authorize release;
- Pixelorama acceptance remains a separate authority family;
- conversation Turns/Submissions are not rewritten as a side effect of the acceptance action.

## 13. Implementation gates

Implementation should proceed in four separately reviewable gates.

### Action Gate A — read-only discovery and projection

Implement only:

- bounded conversation-linked Blender execution discovery;
- typed read-only action projection;
- exact Phase-53 currentness composition;
- server-rendered non-actionable status panel;
- optional live GET payload extension;
- no POST/action mutation.

Acceptance must prove no raw-store/production mutation authority enters presentation code.

### Action Gate B — typed application mutation boundary

Implement only:

- `accept_conversation_blender_task(...)` or equivalent typed service;
- conversation→Task→execution binding revalidation;
- exactly one Phase-53 acceptor delegation site;
- bounded typed result/error projection;
- adversarial substitution/idempotence/recovery tests;
- no HTTP mutation yet.

### Action Gate C — explicit browser confirmation POST

Implement only:

- one exact POST route;
- strict form parser for `execution_id + confirmation`;
- Gate-D same-origin/framing checks;
- server-rendered confirmation control;
- POST/Redirect/GET;
- no JavaScript-owned write.

### Action Gate D — durable live action observation

Implement only:

- bounded action status in the existing live GET projection;
- DOM-only status/button-state refresh;
- reconnect reconstruction;
- no polling-triggered action, retry, or recovery.

Each gate must pass the canonical Python 3.12/3.13 matrix on its exact final head before merge.

## 14. Explicit non-goals

This GUI slice does not add:

- generic production action registry;
- generic Task state buttons;
- Pixelorama acceptance UI;
- Blender adoption UI;
- Manager advance UI;
- Goal-bootstrap UI;
- merge/deploy/release UI;
- provenance signing UI;
- file browser/write controls;
- arbitrary Artifact adoption controls;
- model/provider/profile selection;
- backend/tool execution buttons;
- remote or multi-user authorization;
- role-based access control;
- background acceptance/recovery;
- action batching;
- queue draining;
- automatic parent Flow/Goal transition;
- automatic conversation response generation after acceptance.

Those remain independent architecture questions.

## 15. Acceptance gate for this architecture PR

This planning PR must be documentation-only.

Allowed diff:

```text
docs/gui-governed-blender-task-acceptance-boundary.md
```

The exact planning head must pass the normal canonical Python 3.12/3.13 matrix before ready-for-review and SHA-guarded squash merge.

If `main` advances before merge, the planning document must be revalidated against the new base. No stale CI result may authorize merge.

Only after this architecture is accepted may Action Gate A implementation begin.

## 16. Permanent invariant

> A browser may present and explicitly request one exact already-authorized Blender Task acceptance action. The typed application layer proves that the action is the exact conversation-linked production relation and delegates to the accepted Phase-53 authority. The browser never owns production truth or mutation semantics.

This keeps the GUI useful without turning it into a second control plane.
