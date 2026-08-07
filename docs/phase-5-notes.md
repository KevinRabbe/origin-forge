# Phase 5 — Podman Sandbox Backend

Phase 5 implements Origin Forge's first real sandbox backend behind the Phase-4 verification contract.

The backend is intentionally narrow: it exists only to execute project-approved build/test command specifications for an `AUDITED` Workspace. It does not expose a general command runner to the model or CLI.

## Execution path

```text
AUDITED Workspace
      ↓
structured approved command
      ↓
Podman backend availability check
      ↓
configured local image → resolved content image ID
      ↓
copy audited Workspace to disposable sandbox-job directory
      ↓
Podman container with hardened policy
      ↓
bounded stdout/stderr + timeout
      ↓
forced container cleanup
      ↓
disposable copy removed
      ↓
durable Verification evidence
      ↓
VERIFIED or FAILED / BLOCKED
```

The audited Git worktree itself is never mounted into the container.

## Config version 3

The default config remains non-executable:

```toml
version = 3
policy_profile = "local-default"

[limits]
max_strategy_retries = 2
max_verification_failures = 3

[sandbox]
backend = "unconfigured"
image = ""
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256

[commands]
build = []
test = []
```

To use Podman, a project explicitly selects it and names an image already present in the local Podman image store:

```toml
[sandbox]
backend = "podman"
image = "origin-forge-python:local"
network = false
memory = "2g"
cpus = 2.0
pids_limit = 256
```

Origin Forge does not automatically pull a configured image. Image installation/building is an explicit operator action outside the autonomous verification loop.

## Content-addressed image execution

Before verification, the backend resolves the configured local image reference through Podman image inspection.

The resulting local image ID is used for execution rather than the mutable tag/reference.

Execution also includes `--pull=never`.

This means the image selected at availability check is the exact local image identity used by that verification run.

The configured image name and resolved content ID are persisted in verification provenance.

## Container policy

The current Podman command applies:

```text
--rm
--pull=never
--read-only
--cap-drop=all
--security-opt=no-new-privileges
--pids-limit=<configured>
--memory=<configured>
--cpus=<configured>
--workdir=/workspace
--tmpfs=/tmp:rw,nosuid,nodev
--tmpfs=/run:rw,nosuid,nodev
--network=none       # unless project config explicitly allows network
--entrypoint <exact approved executable>
```

The approved command is already represented as an argv tuple. No shell command string is created.

Container image entrypoints are overridden so the exact first approved argv element is used as the executable.

## Disposable Workspace copy

The verified Git worktree is copied to:

```text
.origin-forge/sandbox-jobs/<JOB-ID>/workspace/
```

The copy excludes:

- `.git`
- `.origin-forge`

Only this disposable copy is mounted writable at `/workspace`.

Build systems may therefore create binaries, caches, temporary files, or modify source files during verification without mutating the audited Workspace.

After the job, the entire sandbox-job directory is removed.

## Network policy

Network access is disabled by default.

A project must explicitly set:

```toml
[sandbox]
network = true
```

before the backend omits `--network=none`.

Enabling network should be treated as granting executing project code the ability to communicate externally with the project copy it can read.

## Bounded process evidence

Origin Forge drains stdout and stderr concurrently through bounded readers.

Each stream has the project's command `max_output_bytes` limit. Additional bytes are discarded while the pipe continues to drain, preventing output volume from becoming unbounded Origin Forge memory consumption.

A process timeout kills the local Podman client process and marks the SandboxResult as timed out.

Truncated output or timeout cannot produce a passing Verification.

## Container cleanup after timeout/failure

Every run also requests a Podman container ID file.

In `finally`, Origin Forge performs a best-effort forced removal using the CID file before deleting the sandbox-job directory.

Conceptually:

```text
podman rm --force --time 0 --ignore --cidfile=<job cidfile>
```

This is deliberate defense in depth: killing the local Podman client process alone is not treated as sufficient evidence that the container no longer exists.

## Sandbox provenance

The backend publishes execution provenance including:

```text
configured image reference
resolved image ID
memory limit
CPU limit
PID limit
```

`SandboxedWorkspaceVerifier` records this beside the exact argv and bounded SandboxResult.

A future investigation can therefore determine which concrete image and resource policy produced a verification result.

## CLI

Phase 5 adds only two sandbox commands:

```text
origin-forge --project-root <project> sandbox status
origin-forge --project-root <project> sandbox verify <WSPACE-ID>
```

`sandbox status` reports:

- backend ID
- availability
- isolation guarantees
- configured image
- resolved backend provenance
- network policy

`sandbox verify` invokes the existing Phase-4 verifier. It does not accept arbitrary argv.

There is intentionally no command such as:

```text
origin-forge sandbox run <anything>
```

## Trust boundary

Podman and its execution environment are part of the trusted computing base for this backend.

Origin Forge reduces exposure by:

- mounting only a disposable project copy
- not mounting Origin Forge state or Git metadata
- not passing host environment variables except the small explicit SandboxJob environment
- disabling network by default
- removing Linux capabilities
- prohibiting privilege escalation
- using a read-only container root
- bounding PIDs, memory, CPU, time, and output
- executing a locally resolved image ID with no automatic pulls

These controls reduce risk; they do not turn arbitrary hostile native code into a mathematically perfect security boundary. Backend implementations remain replaceable so stronger platform isolation can be introduced later without changing verification semantics.

## Validation

Local validation:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
```

Current result:

```text
Ran 75 tests
OK
```

Phase-5-specific coverage includes:

- config v3 defaults and backward compatibility
- Podman backend selection
- image-required policy
- local image ID resolution
- content-addressed image use
- `--pull=never`
- network-off default
- read-only root / dropped capabilities / no-new-privileges
- PID / CPU / memory limits
- exact entrypoint override
- disposable Workspace copies
- exclusion of Git and Origin Forge state
- original Workspace immutability during container-side mutation
- bounded stdout/stderr
- process timeout
- CID-based forced cleanup
- backend execution provenance
- sandbox CLI status and verification path

## Next step

After this backend is validated in CI and on an actual Podman installation, Origin Forge has the core execution substrate needed for the first Manager → Executor → Apply → Audit → Sandbox Verify orchestration loop.
