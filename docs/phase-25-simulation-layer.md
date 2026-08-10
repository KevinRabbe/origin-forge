# Phase 25 — Simulation Layer

Status: **IN PROGRESS — governed deterministic simulation substrate**

Phase 25 adds cheap pre-implementation simulation for bounded system models such as economies, loot/crafting/progression, spawning, combat-resource balance, skill-tree unlock flows and resource distribution.

It is deliberately separate from Phase 24 runtime playtesting:

```text
Phase 24: execute a real target + synthetic player → runtime gameplay evidence
Phase 25: execute a bounded abstract model        → simulation evidence
```

## Core rule

```text
frozen simulation specification
        ↓
deterministic bounded engine
        ↓
exact trajectories + metrics
        ↓
independent structural validation
        ↓
durable simulation evidence

simulation evidence != production Task authority
```

## v1 model boundary

The first engine is a finite integer state-transition system, not a generic scripting environment.

A simulation specification contains:

- infrastructure-owned simulation/spec/workspace identity;
- a caller-selected integer seed within strict bounds;
- bounded replicate and step counts;
- an initial named integer state vector;
- a finite ordered set of rules;
- optional typed state invariants;
- a progression-stall threshold.

Each rule may contain only bounded declarative fields:

- exact rule ID;
- priority;
- prerequisite minimum state values;
- non-negative resource consumption;
- non-negative resource production;
- an integer probability in millionths.

The engine evaluates rules in deterministic priority/ID order. A rule can fire only when prerequisites and consumption requirements are satisfied. Probability draws are derived from SHA-256 over frozen simulation identity, replicate, step and rule identity rather than a runtime/version-dependent random API.

No rule can contain Python, JavaScript, shell text, arbitrary expressions, file paths, process commands, network operations, callbacks or model-authored executable code.

## Intended representational use

The v1 state vector is intentionally generic. Named integer variables can represent bounded quantities such as:

- currency, income and sinks;
- item/material inventory;
- crafting inputs and outputs;
- loot/event counts;
- spawn/enemy population counts;
- health/damage/resource pools at an aggregate level;
- XP/level/unlock counters;
- skill points and acquired-node flags;
- progression gates;
- scarcity/resource-distribution counters.

This is not a claim that every game system can be represented faithfully in v1. Systems requiring continuous physics, spatial geometry, complex AI, rich timing or full runtime behavior remain outside this substrate or require later separately governed adapters.

## Deterministic evidence

For each replicate the engine will retain bounded mechanical evidence such as:

- final state;
- observed minimum/maximum state values;
- rule attempts/firings;
- invariant violations;
- first violation step;
- no-progress/deadlock indication;
- executed step count.

A deterministic aggregate analyzer can derive cross-replicate metrics such as min/max/mean final values, firing rates, violation counts and stall frequency.

These metrics are reproducible evidence. They do not decide whether an economy is fun, a combat system is balanced, a loot table is fair, or a progression curve is good.

## Authority boundary

The Phase-25 service may create its own simulation Run and durable Artifacts/Run Verification. It does not:

- verify or complete the production Task;
- mutate game source/config/content;
- automatically tune balance values;
- adopt a candidate configuration;
- sign provenance;
- merge or release;
- execute model-authored code;
- redefine Design Bible truth.

A later Manager/human/governed pipeline may use simulation evidence when deciding whether to create a separate change proposal. The simulation itself cannot apply that change.

## Relationship to later harness refinement

Phase 26 may eventually evaluate whether a Skill, prompt, context strategy, routing policy or bounded mini-workflow improves outcomes. Phase-25 metrics may be included as frozen evaluation evidence, but an optimizing agent may not choose its own acceptance criteria or activate its own replacement.

## Initial exit condition

Phase 25 v1 is complete when one immutable repository head proves on the supported Python matrix that Origin Forge can:

1. freeze a content-addressed bounded simulation specification;
2. deterministically execute finite seeded state-transition replicates without arbitrary code authority;
3. produce exact bounded trajectory/results and deterministic aggregate metrics;
4. detect and retain invariant violations and no-progress states as evidence;
5. persist exact simulation spec/result/summary lineage through a separate simulation Run;
6. expose evidence through a read-only operator surface; and
7. leave production Task/adoption/signing/merge/release authority unchanged.
