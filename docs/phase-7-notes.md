# Phase 7 — Bounded Retry, Resume, Loop Detection, and Model Escalation

Phase 7 adds explicit control policy above the Phase-6 single-attempt orchestrator.

The objective is not to create an endless self-correcting agent loop. The objective is to make retries, resume behavior, escalation, and stopping conditions deterministic, durable, and inspectable.

## Control model

```text
Task state + Workspace state + durable evidence
                  ↓
          BoundedRetryPolicy
                  ↓
      resume checkpoint if possible
                  ↓
      otherwise one fresh Phase-6 attempt
                  ↓
       inspect durable outcome/evidence
                  ↓
retry only if policy and budgets permit
                  ↓
      succeed / block / fail / quarantine
```

No retry decision depends only on in-memory conversation history.

## Existing durable records are the ledgers

Phase 7 deliberately avoids adding a second retry-counter table.

It derives policy state from records Origin Forge already owns:

### Model-attempt ledger

Every coding-model attempt creates a durable Run with:

```text
role = EXECUTOR
```

The number of Executor Runs for a Task is therefore the authoritative strategy-attempt count.

### Verification-failure ledger

Failed sandbox verification records already exist as Workspace Verifications.

Phase 7 counts Workspace verifications where:

```text
status = FAIL
verification_type starts with sandbox-
```

This becomes the independent verification-failure budget.

### Loop signal

Every persisted `PATCH_PROPOSAL` Artifact has a durable content hash.

Phase 7 compares the most recent consecutive Patch Proposal hashes. An exact repeat is evidence that the strategy is repeating rather than producing a new candidate.

### Resume checkpoint

Workspace state determines whether work should be resumed or replaced.

The policy never treats all interrupted Tasks as equivalent.

## Strategy retry budget

Project config already contains:

```toml
[limits]
max_strategy_retries = 2
```

Phase 7 interprets this as:

```text
maximum total Executor attempts = 1 initial attempt + max_strategy_retries
```

Example:

```text
max_strategy_retries = 2

attempt 1 = initial strategy
attempt 2 = retry 1
attempt 3 = retry 2
attempt 4 = forbidden
```

When the budget is exhausted, Origin Forge moves the Task to `QUARANTINED` rather than continuing indefinitely.

## Independent verification-failure budget

Project config also contains:

```toml
max_verification_failures = 3
```

This limit is independent of the model-strategy budget.

A Task may therefore be quarantined because repeated build/test verification failures reached the configured limit even when unused model retry capacity still exists.

This separates two different failure modes:

```text
strategy cannot produce a useful candidate
vs.
candidates repeatedly fail deterministic verification
```

## Deterministic model escalation

`BoundedRetryPolicy` accepts an ordered sequence of replaceable `ModelAdapter` instances.

Model selection is deterministic from durable Executor-attempt count:

```text
attempt 1 → models[0]
attempt 2 → models[1]
attempt 3 → models[2]
...
attempt N beyond list → last / strongest configured model
```

Each resulting Executor Run persists the selected `model_profile`.

A future investigation can therefore reconstruct exactly which model tier produced every proposal.

## Exact-repeat loop detection

Before another fresh strategy attempt, Phase 7 checks the two most recent Patch Proposal Artifact hashes.

If they are identical:

```text
proposal(N-1).hash == proposal(N).hash
```

Origin Forge quarantines the Task before spending another retry.

This first loop detector is intentionally conservative and deterministic. It detects exact repeated strategy output rather than trying to infer semantic similarity with another model.

Future loop detection may add structural or semantic fingerprints, but exact hashes provide a reliable baseline.

## Resume matrix

Phase 7 resumes the most advanced trustworthy durable checkpoint.

### VERIFIED Workspace

```text
Workspace = VERIFIED
```

No model call is required.

The policy moves the Task back into the required running state, records Task PASS evidence, and finalizes Task success.

### AUDITED Workspace

```text
Workspace = AUDITED
```

The proposed change has already survived deterministic content audit.

Phase 7 resumes sandbox verification only.

It does not ask a model to regenerate the patch.

If sandbox infrastructure is unavailable again, the Workspace remains `AUDITED` and the Task returns to `BLOCKED`.

### APPLIED Workspace

```text
Workspace = APPLIED
```

Phase 7 recovers the associated `proposal_artifact_id` from the durable `WORKSPACE_PATCH_APPLIED` state event.

It then resumes:

```text
independent audit
    ↓
sandbox verification
```

No new model attempt is made.

If durable proposal linkage is missing, the Task is quarantined instead of guessing which proposal belongs to the Workspace.

### clean CREATED Workspace

A clean `CREATED` Workspace can represent an interrupted attempt before the Executor produced useful state.

If it contains no changes, Phase 7 abandons it and starts a fresh bounded attempt from a new snapshot.

### dirty CREATED Workspace

A `CREATED` Workspace with unexplained file changes is not silently discarded.

Origin Forge quarantines the Task because it cannot prove whether the partial state is safe to reuse or throw away.

### FAILED Workspace

A failed Workspace may be abandoned only when policy has decided that a fresh strategy retry is still allowed by all budgets.

It is not deleted merely because the policy process restarted.

## Infrastructure failure is not strategy failure

A key Phase-7 rule is that model retry budget must not hide control-plane outages.

For example, Workspace creation happens before the Executor Run exists.

If Workspace creation fails repeatedly and policy used only Executor count as its retry bound, it could theoretically retry forever without increasing the durable strategy-attempt ledger.

Therefore:

```text
WORKSPACE-stage failure → immediate FAILED / STOP
```

It does not consume another model strategy attempt and it is not automatically retried.

The regression suite explicitly verifies that even with a strategy retry budget of five:

```text
Workspace creation failure
→ one orchestration attempt
→ zero model calls
→ zero Executor Runs
→ one Workspace create call
→ STOP
```

Likewise, unavailable sandbox infrastructure during preflight returns `BLOCKED` without invoking the model.

## Strategy failures that may retry

Fresh strategy retry is reserved for outcomes where a new candidate can reasonably change the result, such as:

- malformed/invalid model output
- Executor returns no usable change
- deterministic apply/audit failure attributable to the candidate
- required sandbox verification command failure, while verification and strategy budgets remain

Before retrying, Phase 7:

1. checks for exact proposal repetition
2. checks strategy-attempt budget
3. checks verification-failure budget
4. resolves active Workspace state
5. abandons only a safe failed/unused Workspace
6. moves the Task back to `READY`
7. selects the next model tier
8. invokes exactly one new Phase-6 attempt

## Quarantine

`QUARANTINED` is an explicit stop state for situations where autonomous continuation is no longer justified.

Current quarantine triggers include:

- exact consecutive Patch Proposal repetition
- strategy retry budget exhaustion
- verification failure budget exhaustion
- dirty unexplained `CREATED` Workspace
- `APPLIED` Workspace missing durable proposal linkage

Quarantine is different from ordinary failure:

```text
FAILED       → another policy decision may retry if allowed
QUARANTINED  → autonomous retry stops until explicit intervention
```

The policy records a `bounded-retry-policy` Task Verification describing the reason and action before transitioning the Task.

## No new authority

Phase 7 changes retry/control policy only.

It does not add:

- automatic merge
- automatic commit to the user's main branch
- push or pull-request authority
- arbitrary shell execution
- automatic network authority
- automatic context discovery
- model-created retry budgets
- unlimited recursion
- model-generated control policy

The same Phase-6 snapshot-first execution and Phase-5 sandbox boundaries remain in force for every fresh attempt.

## Validation

GitHub Actions validates the full project on Python 3.12 and Python 3.13.

Current Phase-7 hardened head result:

```text
Ran 101 tests
OK
```

Phase-7-specific regression coverage includes:

- deterministic three-tier model escalation
- retry after failed sandbox verification
- exact repeated proposal quarantine before a third attempt
- strategy retry budget exhaustion
- verification failure budget exhaustion
- resume from `AUDITED` without another model call
- resume from `APPLIED` through audit + sandbox without another model call
- clean `CREATED` Workspace replacement
- dirty partial `CREATED` Workspace quarantine
- unavailable sandbox blocks without model retry
- Workspace-creation infrastructure failure stops after one control attempt with zero model calls

## Next step

Phase 7 gives Origin Forge a bounded autonomous control loop with durable stop conditions.

The next high-value layer is **Skills and code intelligence/context discovery** so each bounded attempt can select better context and specialized procedures without increasing authority.

A later phase can extend loop detection from exact hashes to structural/semantic strategy fingerprints, but only if that added complexity measurably improves reliability.
