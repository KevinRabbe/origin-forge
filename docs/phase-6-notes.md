# Phase 6 — Snapshot-First Bounded Orchestration

Phase 6 connects the previously independent Origin Forge components into the first complete single-attempt coding pipeline.

The Manager is deterministic and bounded. It coordinates one attempt; it does not invent new Tasks, retry itself, merge branches, or declare success without deterministic evidence.

## Snapshot-first invariant

The central Phase-6 rule is:

```text
create isolated Git Workspace first
        ↓
build model context from that Workspace
        ↓
model proposes against that exact snapshot
        ↓
apply proposal to that same Workspace
```

The Executor does **not** read the user's live checkout.

Uncommitted or unstaged user changes are therefore outside the model's context unless they have been deliberately committed into the Git snapshot used to create the Workspace.

This prevents a subtle class of provenance bugs where the model reasons over one filesystem state while the applier later operates on another.

## Pipeline

```text
READY Task inside RUNNING Flow
        ↓
Manager preflight
        ↓
Task RUNNING
        ↓
durable isolated Git Workspace from HEAD commit
        ↓
read-only context from Workspace snapshot
        ↓
local bounded Executor
        ↓
persisted PATCH_PROPOSAL Artifact
        ↓
deterministic apply to same Workspace
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

Only after preflight passes does the Manager transition the Task to `RUNNING` and create the Workspace.

An existing Workspace must be resumed or abandoned explicitly rather than silently replaced by a fresh attempt.

## Model context boundary

After Workspace creation, Phase 6 constructs:

```text
RepositoryReader(workspace_path)
ContextBuilder(runtime, workspace_repository)
LocalPatchWorker(..., repository=workspace_repository, context_builder=...)
```

The model receives only explicitly selected files from the Workspace snapshot.

The model's SHA-256 preconditions are therefore calculated from the same snapshot the deterministic applier will later mutate.

## Unused snapshot cleanup

Because the Workspace now exists before the Executor runs, an Executor-stage failure can leave a clean unused worktree.

If the Executor:

- returns malformed/invalid output, or
- returns no changes for a Task that requires a change,

Origin Forge abandons that still-`CREATED` Workspace automatically before finishing the Task attempt.

This allows a later explicit retry to begin from a fresh snapshot without retaining a useless active Workspace lease.

Once useful mutation/audit state exists, Origin Forge preserves it according to its lifecycle instead of silently discarding it.

## Outcome model

Every bounded attempt returns:

```text
outcome
stage
reason
Task ID
Patch Proposal Artifact ID, if produced
Workspace ID, if created
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
WORKSPACE
EXECUTOR
APPLY
AUDIT
SANDBOX
COMPLETE
```

This makes failure location durable and machine-readable rather than burying it in conversation history.

## BLOCKED vs FAILED

Origin Forge distinguishes inability to continue from evidence that the attempted change failed.

Examples of `BLOCKED`:

- sandbox unavailable during preflight
- sandbox infrastructure failure after successful audit
- Executor returns no changes for a Task that requires a change

Examples of `FAILED`:

- malformed/invalid model proposal
- Workspace creation failure after the attempt starts
- patch application failure
- audit failure
- required project build/test command exits nonzero
- required verification output exceeds its evidence limit

This distinction is the basis for future retry and escalation policy.

## One attempt means one model attempt

The bounded Manager calls the coding Executor at most once.

If the model fails, returns an invalid proposal, or returns an empty change set where a change is required, Phase 6 does not automatically ask it to try again.

That gives later retry/escalation work a measurable baseline rather than hiding repeated attempts inside one opaque operation.

## Success semantics

`SUCCEEDED` in Phase 6 means all of the following happened:

1. an isolated Workspace snapshot was created first
2. the model read only explicitly selected files from that snapshot
3. the model produced a valid persisted Patch Proposal
4. proposal preconditions matched the same Workspace snapshot
5. the proposal was applied only inside that Workspace
6. the actual Workspace changes exactly matched the proposal
7. the Workspace reached `AUDITED`
8. every required project-approved sandbox verification command passed
9. the Workspace reached `VERIFIED`
10. Origin Forge recorded a PASS Task Verification referencing the proposal, diff, audit evidence, Workspace, and sandbox verification IDs
11. only then did the Task transition to `SUCCEEDED`

This does not magically verify qualitative acceptance criteria that have no verifier. Project-required build/test commands are the acceptance oracle for this first coding loop. Future visual, gameplay, audio, simulation, and domain-specific verifiers will extend that evidence model.

## Failure durability and resume boundary

Expected failures are converted into durable Task states and Task Verification evidence.

The Manager does not rely on in-memory exception history to remember what happened.

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

## Development entry point

Phase 6 exposes a deliberately isolated development entrypoint:

```text
python -m origin_forge.orchestration_cli \
  --project-root <project> \
  <TASK-ID> \
  --file path/to/context.py \
  --file path/to/another.py
```

It reuses the existing llama.cpp adapter and configured sandbox backend.

Context files remain explicit in this phase. Automatic repository/context discovery belongs to later code-intelligence work.

Exit codes are:

```text
0   SUCCEEDED
12  FAILED
13  BLOCKED
```

## Validation

The intended full-suite validation is:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
```

The Phase-6 regression set adds coverage for:

- full successful Workspace → Executor → Apply → Audit → Sandbox → Task path
- one model call per attempt
- model context comes from the Workspace snapshot
- dirty/uncommitted user checkout changes remain invisible and untouched
- main working tree remains unchanged
- empty proposal → BLOCKED and unused Workspace abandoned
- malformed proposal → FAILED and unused Workspace abandoned
- sandbox unavailable during preflight → BLOCKED before Workspace/model invocation
- required sandbox command failure → Task and Workspace FAILED
- sandbox infrastructure error → Task BLOCKED while Workspace remains AUDITED
- Task must be READY
- Flow must be RUNNING
- explicit context files required
- active Workspace prevents a duplicate fresh attempt
- audit exception handling
- refusal to begin without required verification commands
- isolated orchestration CLI success and preflight-blocked results

## Next step

Phase 6 creates a reliable single-attempt baseline over one immutable repository snapshot.

The next orchestration work should add **resume, retry, loop detection, and model escalation as explicit bounded policy**, not as an open-ended agent loop.

After that, Skills and code-intelligence/context discovery can improve the quality and efficiency of each attempt without weakening the durable execution contract.
