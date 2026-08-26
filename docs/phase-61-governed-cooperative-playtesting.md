# Phase 61 — Governed Cooperative Playtesting

Cooperative playtesting is an evidence-only production vertical. A playtest
scenario is first written to the protected `PLAYSCEN-*` store, then referenced
by an exact WorkOrder input. The dispatcher validates the current scenario,
assembles the configured harness, and allocates execution only after the
durable `DISPATCH_EXECUTION_STARTED` boundary.

The lifecycle is:

```text
PLAYSCEN request → WorkOrder → binding → claim → STARTED execution
→ harness → scenario/telemetry/summary/log Artifacts
→ playtest output binding → RETURNED
```

Configure the harness explicitly with the absolute executable path:

```text
ORIGIN_FORGE_PLAYTEST_EXECUTABLE=C:\absolute\path\to\harness.exe
```

Origin Forge fingerprints the executable and rejects a missing, relative, or
changed path. It never downloads or discovers a hidden harness installation.

The v27 `playtest_dispatch_output_bindings` table is the terminalization
boundary. It stores the exact execution, claim, Task, WorkOrder, scenario,
telemetry, summary, stdout, and stderr relationships. Repeating publication
of identical evidence is idempotent; conflicting evidence is rejected.

Recovery first validates the existing binding and current claim/Task relation.
If the binding exists, recovery materializes the result and may finish a
durable `STARTED` execution. If the binding is absent or inconsistent,
recovery fails closed and never invokes the harness again.

Playtest results remain evidence. They cannot accept Tasks, adopt artifacts,
sign, merge, or release. Use the production trace to inspect playtest output
bindings alongside Goal, Flow, Task, Run, WorkOrder, claims, executions,
Artifacts, Verifications, review, adoption, and provenance.
