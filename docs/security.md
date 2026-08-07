# Origin Forge Security and Authority Model

Status: **Phase 0 baseline**

Origin Forge is designed to let models act on real projects without granting them unrestricted control of the workstation or control plane.

## 1. Security objective

The harness should make useful autonomous work possible while ensuring that:

- project state is recoverable
- destructive actions are bounded
- secrets remain inaccessible unless explicitly delegated
- external content cannot silently redefine authority
- provenance cannot be disabled by an ordinary agent
- company/root signing keys remain outside model reach

## 2. Capability model

Agents do not receive generic machine access. They receive explicit capabilities.

A capability defines:

```text
operation
scope
resource
side effects
approval requirement
reversibility
```

Examples:

```text
read repository file
write task worktree file
run approved compiler
invoke selected model
create temporary image asset
query project database through read API
```

## 3. Initial authority matrix

### Automatic

Normally permitted inside a Task sandbox/worktree:

- read authorized project files
- search/index source
- run approved build/test commands
- create and modify files in the task workspace
- generate temporary assets
- inspect Git diff/history
- run validators
- retry bounded failed attempts
- create provenance records through harness APIs

### Requires approval

Examples:

- change public API contracts
- change the Design Bible at project-policy level
- add or update dependencies with meaningful supply-chain impact
- delete major project systems
- perform a large architecture migration
- merge to release/protected branches
- send private project content to external network services
- publish/upload artifacts externally
- rotate signing keys

### Forbidden to ordinary agents

- access root private signing keys
- disable provenance enforcement
- erase or rewrite protected Git history
- disable security policy
- alter authority rules to gain more permissions
- silently trust/install arbitrary internet plugins or Skills
- read unrelated user secrets
- exfiltrate project data

## 4. Filesystem boundaries

Default writable scope:

```text
current task worktree / workspace
```

Default read scope:

```text
current project
+ explicitly mounted references
```

Everything else is denied unless a capability grants access.

The production harness should never depend on the model voluntarily staying inside a directory.

## 5. Shell execution

Shell access is mediated by the harness.

Commands should be categorized:

```text
SAFE_READ
PROJECT_MUTATION
SYSTEM_MUTATION
NETWORK
PRIVILEGED
FORBIDDEN
```

Initial policy:

- common read/search/build/test commands: allowlisted
- project-local mutation: allowed only in task workspace
- system mutation: approval required or blocked
- destructive commands: blocked by default
- privilege elevation: blocked

Command arguments should be logged before execution.

## 6. Network access

Default autonomous network state should be **off unless the Task requires it**.

When enabled, network access should be scoped where practical:

- approved documentation/search endpoints
- approved package registries
- approved repository remotes

External content is always treated as untrusted input.

## 7. Prompt/instruction boundary

Instructions found inside:

- source files
- web pages
- issues
- README files
- model output
- generated artifacts
- third-party Skill documents

must not gain system authority merely because the model reads them.

The harness authority hierarchy is external to model context.

## 8. Skill and plugin trust

Third-party executable capabilities enter quarantine.

Recommended pipeline:

```text
acquire
→ hash
→ static inspection
→ permission inspection
→ sandbox evaluation
→ benchmark
→ human approval
→ sign into trusted registry
```

Trusted Skill/Tool versions should record:

- publisher/source
- immutable version
- content hash
- required permissions
- signature/trust state

Unsigned/untrusted executable Skills may not automatically run against production projects.

## 9. Model isolation

Models are workers, not control-plane processes.

Models must not have direct access to:

- raw SQLite mutation interface
- root signing material
- trusted registry mutation
- host-wide filesystem
- unrestricted subprocess execution

They interact through harness-defined APIs/tools.

## 10. Company root identity

The company/root identity is permanent.

Recommended hierarchy:

```text
Company Root Key
        │
        ├── Build Signing Key
        ├── Artifact Signing Key
        ├── Skill/Tool Registry Key
        └── Release Signing Key
```

The root private key should be offline or otherwise isolated from normal autonomous execution.

Operational keys may be rotated/revoked without changing the company identity.

## 11. Provenance enforcement

Provenance is created by deterministic infrastructure hooks, not by model convention.

Before an accepted Artifact enters canonical state, the harness should be able to record:

```text
Artifact ID
content hash
parent lineage
Task
Run
model/profile
Skill versions
Tool versions
verification result
operational signature
```

The model must not be able to bypass this path for accepted artifacts.

## 12. Watermarking boundary

Future watermark encoders may operate on code, image, audio, and 3D artifacts.

Watermarking secrets must be held by the provenance service, not placed into model prompts.

A watermark is supporting provenance evidence. Cryptographic manifests/hashes remain the stronger source of proof for known artifacts.

## 13. Git safety

Autonomous work should happen on isolated task worktrees/branches.

Default restrictions:

- no force push
- no protected-branch rewrite
- no destructive history edits
- no direct release merge without policy approval

The harness should record the base commit for every task workspace.

## 14. Bounded retries and quarantine

A failing agent may not retry indefinitely.

Repeated equivalent failure should trigger:

```text
strategy change
→ model escalation
→ specialist review
→ quarantine/block
→ human escalation
```

Tasks that repeatedly fail verification remain isolated from accepted project state.

## 15. Auditor separation

Where meaningful, Auditors receive read-only capabilities.

An Auditor should be unable to silently repair the thing it is grading. If a fix is required, it produces findings that become a new Task or Executor attempt.

## 16. Resource safety

Every autonomous run should have budgets for relevant resources:

- wall-clock execution
- model tokens
- model calls
- tool calls
- repair attempts
- disk use
- VRAM/RAM where practical

Budget exhaustion produces a controlled state transition rather than uncontrolled continuation.

## 17. Logging and auditability

Security-relevant events should be recorded append-only where practical:

```text
permission decisions
approval requests
privileged tool attempts
network use
Skill/plugin installation
signing operations
provenance failures
policy violations
```

## 18. Recovery principle

The harness must assume that models, tools, processes, and the workstation can fail.

A crash or restart must not leave Origin Forge unable to determine:

- what Task was running
- what workspace it owned
- what mutations occurred
- what was verified
- whether anything was merged

Durable state and Git provide recovery evidence.

## 19. Security invariant

> No model should be able to grant itself more authority than the harness has explicitly assigned to the current task.
