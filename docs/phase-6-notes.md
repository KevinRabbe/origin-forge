# Phase 6 — Bounded End-to-End Orchestration

Phase 6 connects the previously independent Origin Forge components into the first complete bounded coding attempt.

The Manager in this phase is deliberately deterministic. It coordinates one attempt; it does not invent new Tasks, retry itself, merge branches, or declare success without external evidence.

## Pipeline

```text
READY Task inside RUNNING Flow
        ↓
Manager preflight
        ↓
local bounded Executor
        ↓
persisted PATCH_PROPOSAL Artifact
        ↓
durable isolated Git Workspace
        ↓
deterministic apply
        ↓
independent content Auditor
        ↓
AUDITED Workspace
        ↓
sandboxed required build/test commands
        ↓
VERIFIED Workspace
        ↓
Task PASS Verification
        ↓
Task SUCCEEDED
```

The user's main working tree remains unchanged throughout the attempt.

## Bounded Manager

`BoundedTaskOrchestrator` executes exactly one attempt.

It does **not** contain an internal retry loop.

Preflight requires:

- Task status `READY`
- parent Flow status `RUNNING`
- no existing non-abandoned Workspace for the Task
- at least one required sandbox verification command
- available sandbox backend
- backend isolation guarantees satisfying project policy
- at least one explicitly selected context file

An existing Workspace must be resumed or abandoned explicitly rather than silently replaced by a new attempt.

## Outcome model

Every bounded attempt returns:

```text
outcome
stage
reason
Task ID
Patch Proposal Artifact ID, if produced
Workspace ID, if produced
Task Verification ID, if recorded
```

Outcomes are:

```text
SUCCEEDED
FAILED
BLOCKED
```

Stages are:

```text
PREFLIGHT
EXECUTOR
WORKSPACE
APPLY
AUDIT
SANDBOX
COMPLETE
```

This makes failure location durable and machine-readable rather than burying it in agent conversation history.

## BLOCKED vs FAILED

Origin Forge distinguishes inability to continue from evidence that the attempted change failed.

Examples of `BLOCKED`:

- sandbox unavailable before execution
- sandbox infrastructure failure after audit
- Executor returns no changes for a Task that requires a change

Examples of `FAILED`:

- invalid model proposal
- Workspace creation failure after the attempt starts
- patch application failure
- audit failure
- required project build/test command exits nonzero
- required verification output exceeds its evidence limit

This distinction is important for future retry and escalation policy.

## One attempt means one model attempt

The bounded Manager calls the coding Executor at most once.

If the model fails, returns an invalid proposal, or returns an empty change set where a change is required, Phase 6 does not automatically ask it to try again.

That gives later retry/escalation work a measurable baseline rather than hiding repeated attempts inside one opaque operation.

## Success semantics

`SUCCEEDED` in Phase 6 means all of the following happened:

1. the model produced a valid persisted Patch Proposal
2. its file preconditions were valid
3. the proposal was applied only inside an isolated Workspace
4. the actual Workspace changes exactly matched the proposal
5. the Workspace reached `AUDITED`
6. every required project-approved sandbox verification command passed
7. the Workspace reached `VERIFIED`
8. Origin Forge recorded a PASS Task Verification referencing the proposal, diff, audit evidence, Workspace, and sandbox verification IDs
9. only then did the Task transition to `SUCCEEDED`

This does not magically verify qualitative acceptance criteria that have no verifier. Project-required build/test commands are the acceptance oracle for this first coding loop. Future visual, gameplay, audio, simulation, and domain-specific verifiers will extend that evidence model.

## Failure durability

Expected failures are converted into durable Task states and Task Verification evidence.

The Manager does not rely on its in-memory exception history to remember what happened.

A sandbox infrastructure outage after successful content audit leaves:

```text
Workspace = AUDITED
Task = BLOCKED
```

so the verified patch can later resume at sandbox verification instead of being silently discarded.

If an active Workspace already exists when a fresh orchestration attempt is requested, Origin Forge refuses to start a second one. Resume/abandon behavior must be explicit.

## No merge authority

Even a successful Phase-6 attempt leaves the verified change in its isolated Git worktree/branch.

There is no automatic:

- commit into the user's main branch
- merge
- push
- pull request
- release

Those are separate future authority levels.

## Entry point

Phase 6 exposes a deliberately isolated development entrypoint:

```text
python -m origin_forge.orchestration_cli \
  --project-root <project> \
  <TASK-ID> \
  --file path/to/context.py \
  --file path/to/another.py
```

It reuses the existing llama.cpp adapter and configured sandbox backend.

The context files remain explicit in this phase. Automatic repository/context discovery belongs to later code-intelligence work.

Exit codes from this entrypoint are:

```text
0   SUCCEEDED
12  FAILED
13  BLOCKED
```

## Validation

Local validation:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
```

Current result:

```text
Ran 89 tests
OK
```

Phase-6-specific coverage includes:

- full successful Executor → Workspace → Apply → Audit → Sandbox → Task path
- one model call per attempt
- main working tree remains unchanged
- empty proposal → BLOCKED without Workspace creation
- sandbox unavailable during preflight → BLOCKED before model invocation
- invalid model output → FAILED
- required sandbox command failure → Task and Workspace FAILED
- sandbox infrastructure error → Task BLOCKED while Workspace remains AUDITED
- Task must be READY
- Flow must be RUNNING
- explicit context files required
- active Workspace prevents duplicate fresh attempt
- audit exception handling
- refusal to begin without required verification commands
- isolated orchestration CLI success and preflight-blocked results

## Next step

Phase 6 creates a reliable single-attempt baseline. The next orchestration work should add **resume, retry, loop detection, and model escalation as explicit policy**, not as an unbounded agent loop.

After that, Skills and code-intelligence/context discovery can improve the quality and efficiency of each attempt without weakening the durable execution contract.
