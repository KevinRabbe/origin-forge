# Research Influences

Status: **Living design note**

Origin Forge is not intended to clone any existing agent framework. This document records external engineering patterns that materially influenced the architecture so future contributors can understand why particular design choices exist.

## 1. Anthropic — long-running agent harnesses

Primary source:

- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

Useful lessons:

- Long-running work spans multiple context windows and should be treated as incremental engineering sessions.
- Compaction alone is insufficient for reliable long-horizon work.
- New sessions need explicit project/progress artifacts rather than guessing previous state.
- Git history provides a strong recovery and rollback mechanism.
- Agents tend to declare completion prematurely unless success is explicitly verified.
- End-to-end testing is more valuable than trusting source-level changes alone.

Origin Forge adaptation:

- structured durable state replaces a prose progress file as the canonical handoff mechanism
- fresh bounded Executors are expected rather than exceptional
- completion is owned by Verification records, not model judgment
- worktrees/checkpoints isolate incremental work

## 2. Anthropic — context engineering, Skills, hooks, and subagents

Primary engineering index:

- https://www.anthropic.com/engineering

Useful patterns:

- selectively retrieve task-relevant context
- isolate side work in separate agent contexts
- use lifecycle hooks for deterministic guardrails
- package reusable operational knowledge as Skills rather than giant prompts

Origin Forge adaptation:

- progressive Skill disclosure
- bounded specialist roles rather than a large conversational swarm
- deterministic hooks for formatting, diagnostics, provenance, and verification
- project state is retrieved just in time

## 3. OpenClaw — durable Task Flow

Primary source:

- https://docs.openclaw.ai/automation/taskflow

Useful patterns:

- multi-step work is represented by durable Flow records
- Flow state survives gateway/runtime restarts
- explicit statuses distinguish running, waiting, blocked, succeeded, failed, and cancelled work
- revision counters prevent stale concurrent state writers from silently overwriting newer state

Origin Forge adaptation:

- Flow is a first-class persistent object in SQLite
- every mutation increments a revision/version
- restart recovery is a Phase-1 requirement
- the LLM conversation is never the owner of Flow state

## 4. OpenClaw — Tool Search

Primary source:

- https://docs.openclaw.ai/tools/tool-search

Useful pattern:

- large agent systems should not inject every complete tool schema into every model context

Origin Forge adaptation:

```text
search_tools(query)
describe_tool(id)
call_tool(id, args)
```

Only relevant tool schemas are disclosed to the current Executor.

This is especially important for local 20–30B models where context efficiency has a large effect on usable capability.

## 5. OpenClaw — loop detection

Primary source:

- https://docs.openclaw.ai/tools/loop-detection

Useful pattern:

- detect repeated tool/argument/result patterns and break no-progress loops

Origin Forge adaptation:

Loop detection includes:

- identical tool calls
- identical verification failures
- repeated patches with no metric improvement
- no new information acquired

The response is strategy change/escalation, not infinite retry.

## 6. Qwen Code — permission and autonomous execution patterns

Primary sources:

- https://github.com/QwenLM/qwen-code
- https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/approval-mode.md
- https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/auto-mode.md

Useful patterns:

- multiple approval modes for different risk levels
- workspace-local edits can be treated differently from system/security-sensitive mutations
- self-modification and persistence surfaces deserve higher scrutiny than ordinary code edits
- autonomous operation benefits from explicit command/network/write boundaries

Origin Forge adaptation:

- deterministic Authority Matrix
- task-worktree writes are lower privilege than control-plane writes
- security/provenance/Skill-registry surfaces cannot be modified by ordinary Executors
- capability grants are task-scoped

## 7. Qwen Code — recent agent architecture evolution

Primary source:

- https://qwenlm.github.io/qwen-code-docs/en/blog/updates/

Relevant engineering directions observed in Qwen Code include:

- autonomous goal/loop modes
- worktree-isolated sessions
- independent judging/review
- Tool Search
- Skill management
- background/subagent execution
- context compression improvements
- model-specific concurrency controls
- durable loops that survive restart

Origin Forge does not copy Qwen Code's implementation. These developments reinforce the broader direction that reliable autonomous work requires a persistent operating layer around the model rather than relying on model capability alone.

## 8. Origin Forge synthesis

The architecture intentionally combines several classes of ideas:

```text
Anthropic
→ strong bounded worker/context/verification practices

OpenClaw
→ durable outer runtime and explicit long-running Flow state

Qwen Code
→ practical autonomous coding permissions, worktree isolation, model/tool evolution

Origin Forge
→ persistent verified state
 + semantic project graph
 + cross-media production
 + resource-aware local scheduling
 + company provenance/signature
 + deterministic verification
```

The goal is not feature parity with existing agent frameworks.

The goal is to build a local production operating environment in which models are replaceable processors and accumulated operational knowledge belongs to the infrastructure.

## 9. Research adoption rule

A pattern from another system is not adopted merely because it exists.

It should enter Origin Forge only if it plausibly improves:

- capability
- reliability
- efficiency
- security
- observability
- control

and should be benchmarked when implementation reaches the relevant phase.
