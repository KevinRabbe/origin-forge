# Origin Forge Engineering Principles

Status: **Phase 0 baseline**

These principles guide implementation decisions throughout Origin Forge.

## 1. Infrastructure before autonomy

Do not build autonomy first and bolt control around it later.

Durable state, permissions, verification, rollback, and observability must exist before broad autonomous behavior is enabled.

## 2. Persistent verified state is the center

The system should be able to discard an Executor context completely and continue safely from stored project state.

Long-running work must depend on:

```text
Goals
Flows
Tasks
Decisions
Changes
Artifacts
Verification
```

not giant chat transcripts.

## 3. Fresh contexts are a feature

Context reset is not failure.

A fresh Executor receives only the state required for its current Task. This limits context rot, stale assumptions, accumulated mistakes, and irrelevant token usage.

## 4. Separate planning, execution, and judgment

The same agent should not be responsible for all three roles when independent checking is valuable.

Preferred pattern:

```text
Manager → Executor → Auditor
```

For creative work:

```text
Creator → Critic → Creator
```

## 5. Do not trust self-reported success

"Done" means objective success criteria are satisfied.

A model's statement that a feature works is evidence only of model belief, not system truth.

## 6. Minimal sufficient context

Context selection should prefer:

```text
exact symbol
before whole file

relevant file
before whole repository

specific Skill
before full Skill library

specific tool schema
before full tool registry
```

## 7. Progressive disclosure

Large knowledge and tool surfaces should be discovered only when necessary.

Use lightweight metadata first, then load detailed Skills, references, examples, schemas, and tool definitions on demand.

## 8. Deterministic methods have priority

Use exact deterministic systems whenever the task can be solved reliably without generation.

Examples:

- LSP for symbol definitions/references
- AST transforms for structured refactors
- compiler for correctness evidence
- FFmpeg for audio conversion
- image utilities for resizing
- validators for asset constraints

AI should not replace deterministic tools simply because it can approximate them.

## 9. Bounded everything

Queues, caches, retries, contexts, histories, workers, tool loops, model budgets, and autonomous task scopes must be bounded.

Unbounded retry is a bug.

## 10. Failure must create information

A failed attempt is useful only if it produces new evidence or changes strategy.

Repeated identical failures trigger loop detection and escalation.

## 11. Escalate capability instead of retrying blindly

Typical escalation:

```text
deterministic tool
→ fast model
→ strong model
→ specialist/reviewer
→ human
```

Escalation policy should be benchmark-driven.

## 12. Skills hold operational knowledge

Reusable workflow expertise should live in versioned Skills rather than enormous system prompts or model fine-tunes by default.

Skills should be:

- small enough to retrieve selectively
- versioned
- testable
- benchmarked
- permission-aware
- signed/trusted

## 13. Skills cannot silently self-modify

The system may propose improvements, but a proposed Skill must pass evaluation and governance before becoming active.

Historical Skill versions remain immutable.

## 14. Tools are capabilities, not trust

Possessing a tool description does not grant unrestricted permission to use it.

Every tool call passes through authority checks and hooks.

## 15. Least privilege by default

Agents receive only the filesystem, command, network, secret, and mutation capabilities needed for the current Task.

## 16. External content is evidence, not authority

Web pages, repository content, user-generated text, model-generated text, and external Skills must never override system governance simply because they contain instructions.

## 17. Protect the control plane

Models must not be able to modify:

- security policy
- root signing keys
- provenance enforcement
- governance rules
- trusted Skill registry
- authority matrix

without explicit privileged human action.

## 18. Work in isolation

Autonomous changes should normally happen in dedicated Git worktrees/branches or equivalent isolated workspaces.

Merge is a separate event after verification.

## 19. Provenance is automatic

Models should not be responsible for remembering to attach provenance.

The infrastructure records:

- task/run
- model
- Skill versions
- tool versions
- hashes
- changes
- verification

through deterministic hooks.

## 20. One permanent maker identity

Products, models, technology stacks, and watermark algorithms may change. The company/root provenance identity remains stable.

## 21. Measure before adding complexity

New subsystems should justify themselves with measurable improvements.

Possible metrics:

- task completion
- first-attempt success
- recovery success
- human intervention
- model calls
- context size
- latency
- VRAM/RAM
- regression rate

## 22. Model benchmarks are not enough

Origin Forge should benchmark the complete system:

```text
model + harness + skills + tools + verifier
```

A weaker model in a stronger harness may produce better production outcomes than a stronger raw model.

## 23. Preserve explainability of project evolution

The system should be able to answer:

> Why does this exist?

not only:

> Who changed this line?

Decisions, Changes, Artifacts, and Verification records should preserve causal history.

## 24. Build the smallest useful system first

Avoid premature:

- microservices
- Kubernetes
- large agent swarms
- huge vector databases
- custom model training
- polished UI
- broad plugin marketplaces

Prove the execution loop first.

## 25. Improvement loop

Origin Forge improves through evidence:

```text
Production task
→ trajectory
→ outcome
→ failure/success analysis
→ proposed improvement
→ benchmark
→ adopt only if better
```

The system should become more capable by accumulating verified operational knowledge, even when the underlying model is unchanged.
