# Phase 4 — Sandboxed Verification Contract

Phase 4 introduces the policy and orchestration boundary required before Origin Forge may execute AI-modified project code.

A Git worktree protects project state, but it does not protect the host machine from the code being built or tested. Therefore Origin Forge does not treat an allowlisted command as safe merely because the command itself is known. Project code executes only through a sandbox backend that advertises the required isolation guarantees.

## Verification state split

Phase 3 used `VERIFIED` after deterministic content audit. Phase 4 makes that distinction stricter:

```text
CREATED
   ↓
APPLIED
   ↓
AUDITED
   ↓
sandboxed build/test evidence
   ↓
VERIFIED
```

`AUDITED` means the isolated worktree matches the approved Patch Proposal.

`VERIFIED` means required project-approved commands also completed successfully through an acceptable sandbox backend.

## No shell command strings

Config version 2 replaces free-form command strings with structured command specifications.

Example:

```toml
version = 2

[sandbox]
network = false

[commands]
build = [
  { name = "compile", argv = ["python", "-m", "compileall", "."], timeout_seconds = 30, max_output_bytes = 1048576, required = true }
]
test = [
  { name = "unit", argv = ["python", "-m", "unittest", "discover", "-s", "tests", "-q"], timeout_seconds = 120, max_output_bytes = 1048576, required = true }
]
```

Origin Forge never needs to parse shell quoting, redirection, pipes, substitutions, or chained commands. The sandbox backend receives the exact `argv` tuple.

Legacy config v1 files with empty command arrays remain readable. Legacy non-empty shell-string command lists are rejected and must be rewritten explicitly as v2 argv commands.

## Sandbox backend contract

A backend must expose:

- stable backend ID
- availability probe
- declared isolation guarantees
- bounded `run(SandboxJob) -> SandboxResult`

The required guarantees are represented independently:

```text
filesystem isolation
process isolation
host-secret isolation
network control
```

Origin Forge rejects a backend before execution if it cannot satisfy the policy required for the job.

There is deliberately no native-host backend in this phase.

## Sandbox jobs

A `SandboxJob` contains only:

- isolated Workspace path
- exact argv tuple
- timeout
- output byte limit
- explicit network policy
- minimal environment supplied by Origin Forge

The backend is responsible for enforcing those limits and returning a bounded `SandboxResult`.

## Verification behavior

`SandboxedWorkspaceVerifier`:

1. requires Workspace state `AUDITED`
2. loads project config
3. validates backend availability and guarantees
4. schedules only required structured build/test commands
5. sends exact jobs to the sandbox backend
6. records a Workspace Verification for every command
7. promotes to `VERIFIED` only if all required commands pass

A result passes only when:

- it did not time out
- exit code is zero
- stdout was not truncated
- stderr was not truncated

If project code fails a command, the Workspace becomes `FAILED`.

If sandbox infrastructure itself errors, Origin Forge records `BLOCKED` evidence and leaves the Workspace `AUDITED`; infrastructure failure is not treated as proof that the proposed change is bad.

A Workspace cannot become `VERIFIED` if no required sandbox command is configured.

## Safe default

`UnconfiguredSandboxBackend` is intentionally non-executable. Until a real backend is explicitly configured, sandboxed verification cannot run.

This means merging Phase 4's contract does **not** introduce host code execution.

## Validation

Local validation:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
```

Current result:

```text
Ran 62 tests
OK
```

New coverage includes:

- config v2 defaults
- v1 empty-config compatibility
- rejection of v1 shell command strings
- structured argv parsing
- duplicate command rejection
- AUDITED → VERIFIED only after sandbox PASS
- nonzero command failure → FAILED
- truncated output → FAILED
- backend infrastructure error → BLOCKED evidence while Workspace stays AUDITED
- inadequate sandbox guarantees rejected before execution
- no required commands cannot promote a Workspace
- verifier rejects non-AUDITED Workspace state

## Next step

The next slice is to implement the first **real** `SandboxBackend` behind this contract. Backend selection must not weaken the policy above. Platform-specific implementations can differ while the verifier remains unchanged.
