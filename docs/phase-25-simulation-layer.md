# Phase 25 — Simulation Layer

Status: **DONE candidate — governed deterministic v1 substrate frozen; merge remains gated on final exact-head CI**

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
exact results + mechanical metrics
        ↓
independent structural binding
        ↓
durable simulation evidence

simulation evidence != production Task authority
```

## Governed v1 engine

The first engine is an infrastructure-owned finite integer state-transition system:

```text
engine_id      = origin-forge-deterministic-sim
engine_version = 1
```

`run_simulation()` rejects a specification that claims any other engine identity. Future specialized engines must be introduced as separately governed adapters rather than using the v1 identity as a caller-controlled provenance label.

The built-in engine is pure infrastructure code. It does not invoke subprocesses, use the network, read project files, evaluate source text, execute callbacks, or expose a model-facing scripting surface.

## Frozen specification

A `SimulationSpec` is immutable and content-addressed. It carries:

- infrastructure-format `SIMSPEC-*` specification identity;
- `SIM-*` session identity;
- exact `SIMWS-*` workspace identity;
- exact engine ID/version;
- a bounded integer seed;
- bounded replicate and step counts;
- an explicit no-progress/stall threshold;
- a named signed-int32 initial state vector;
- a finite ordered rule set;
- optional typed state invariants.

The v1 bounds include:

- at most 128 state variables;
- at most 256 rules;
- at most 256 invariants;
- at most 256 replicates;
- at most 10,000 steps per replicate;
- a 5,000,000-unit implementation-aware simulation-work budget;
- signed-int32 state values;
- bounded non-negative consume/produce quantities.

The work budget accounts for the implemented rule-field work, state mutation/bookkeeping and invariant checks rather than using only `replicates × steps × rules` as a proxy.

Input ordering is canonicalized. State values and rule metric maps use deterministic lexical ordering; rules execute in deterministic `(priority, rule_id)` order; invariants are stored in invariant-ID order.

## Declarative rule boundary

Each `SimulationRule` may contain only:

- exact rule ID;
- integer priority;
- probability in integer millionths (`0..1,000,000`);
- prerequisite minimum state values;
- non-negative resource consumption;
- non-negative resource production.

A rule must consume or produce at least one state variable. It can reference only variables declared by the specification.

No rule field can contain or authorize:

- Python;
- JavaScript;
- shell text;
- arbitrary expressions;
- callbacks;
- executable paths;
- process commands;
- filesystem operations;
- network operations;
- generic tool invocation.

This makes the simulation model a bounded declarative transition graph rather than a disguised code-execution surface.

## Deterministic probability schedule

For a probabilistic eligible rule, the v1 engine derives the draw from SHA-256 over:

```text
origin-forge-sim-v1
seed
replicate_index
step_index
rule_id
```

The resulting digest is reduced into `[0, 1_000_000)`. The engine therefore does not depend on Python's `random` implementation or hidden mutable RNG state.

Using the same seed/replicate/step/rule identity also provides a useful common-random-number property for later paired simulation comparisons: candidate specifications that retain the same rule IDs see the same draw schedule at corresponding checkpoints. This improves comparability but is not, by itself, a claim of statistical validity or balance correctness.

`1,000,000` always fires when eligible and `0` never fires.

## Step semantics

Within a replicate:

1. rules are considered in `(priority, rule_id)` order;
2. prerequisite and consumption availability are checked against the current state at that point in the step;
3. eligible rules record an attempt;
4. the deterministic probability decision is evaluated;
5. firing rules consume first, then produce;
6. signed-int32 overflow fails the simulation infrastructure closed;
7. observed minima/maxima are updated for touched variables;
8. after all rules for the step have executed, invariants are checked;
9. net whole-step state progress is evaluated;
10. the replicate stops early after the configured number of consecutive no-progress steps.

A rule can therefore affect the eligibility of a later rule in the same step.

A consume-then-produce rule whose net state is unchanged still counts as **no whole-step progress**. The engine tracks original values only for variables touched during a step, avoiding an unbounded full-state copy on every step.

## Invariant semantics

`SimulationInvariant` supports an exact declared variable plus optional minimum and/or maximum bounds.

Invariants are checked at:

- checkpoint `0`, before the first step; and
- once after each completed full step.

The v1 contract does **not** claim mid-rule or intermediate-within-step invariant observation. If a system needs such semantics, it requires a separately specified simulation contract rather than silently changing v1 interpretation.

Violation details retain:

- invariant ID;
- exact variable;
- checkpoint;
- observed value;
- exact declared minimum/maximum.

The total violation count remains exact even when detail retention is truncated. The governed engine retains at most 1,024 violation details per replicate and at most 8,192 stored violation details across one result. Truncation is explicit.

## Result structural binding

`SimulationResult.bind_spec()` independently checks that result evidence matches the frozen specification rather than trusting a merely shape-correct object.

It requires:

- exact session/spec hash/engine identity;
- exact replicate count and contiguous indexes;
- executed steps within the frozen maximum;
- exact state-variable and rule-metric identities;
- recorded minima/maxima that contain both initial and final state;
- `0 <= firings <= attempts <= steps_executed` for every rule;
- violation counts no larger than the possible invariant checkpoints;
- every stored violation to reference an exact declared invariant;
- exact violation variable/minimum/maximum binding;
- a checkpoint no later than the replicate's executed steps;
- an observed value that actually violates the declared bound;
- no duplicate stored `(checkpoint, invariant_id)` evidence;
- canonical stored violation ordering.

Adversarial tests forge firing counts, extrema and invariant evidence and prove these structures fail closed.

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

This does not mean every game system can be represented faithfully in v1. Continuous physics, spatial geometry, complex AI, rich real-time timing and full application behavior remain outside this substrate or require later separately governed adapters.

## Deterministic aggregate evidence

For each replicate the engine retains bounded mechanical evidence:

- final state;
- observed minimum/maximum state;
- rule attempts/firings;
- exact invariant-violation count;
- bounded stored violation details plus truncation state;
- no-progress/stall state;
- executed step count.

`analyze_simulation()` independently binds the result to the specification and derives deterministic cross-replicate evidence:

- total executed steps;
- stalled replicate count;
- total violation count;
- number of replicates containing violations;
- number of replicates with truncated violation details;
- per-variable final minimum/maximum/sum;
- exact rational mean-final representation using numerator/denominator rather than floating-point formatting;
- overall observed variable minima/maxima;
- per-rule attempts/firings;
- exact rational firing-rate numerator/denominator.

The analyzer precomputes bounded per-replicate state/rule maps rather than repeatedly reconstructing them inside nested loops.

These values are reproducible evidence. They do not decide whether an economy is fun, combat is balanced, a loot table is fair, a progression curve is good, or a design should ship.

## Durable simulation service

`SimulationService` requires an already-`RUNNING` production Task and creates a separate `SIMULATOR` Run.

It owns the protected workspace root:

```text
.origin-forge/simulations/SIMWS-*/
├── request/
│   └── spec.json
└── evidence/
    ├── result.json
    └── summary.json
```

The service:

- rejects symlinked simulation roots/workspaces;
- requires a fresh exact `SIMWS-*` workspace;
- writes canonical JSON with no overwrite;
- independently revalidates exact lexical evidence paths, symlink safety, workspace containment and exact bytes before Artifact creation;
- caps each durable simulation evidence file at 16 MiB;
- executes only the governed built-in engine identity;
- independently binds the result to the specification;
- independently derives the summary.

It creates:

- `SIMULATION_SPEC` Artifact;
- `SIMULATION_RESULT` Artifact;
- `SIMULATION_SUMMARY` Artifact;
- one Run-level `simulation-structure` Verification.

An invariant violation or a stalled simulation is a **simulation finding**, not a simulator infrastructure failure:

```text
simulation infrastructure succeeded + negative model finding
!=
simulation infrastructure failed
```

An engine overflow, invalid engine identity, unsafe workspace/evidence path, oversized durable evidence, or structural result-binding failure is instead an infrastructure failure and fails only the `SIMULATOR` Run.

## Production authority boundary

A successful `SIMULATOR` Run does not verify the production Task. `SimulationService` explicitly records that it has no authority to:

- verify or complete the production Task;
- decide semantic game balance;
- mutate game source/config/content;
- automatically tune balance values;
- adopt a candidate configuration or asset;
- sign provenance;
- merge or release;
- execute model-authored code;
- redefine Design Bible truth.

The production Task remains `RUNNING`, receives no Task Verification from the simulation service, and is not automatically failed because an invariant was violated or a replicate stalled.

A later human/Manager/governed pipeline may use this evidence when deciding whether to create a separate change proposal. The simulator itself cannot apply that proposal.

## Read-only operator inspection

```text
python -m origin_forge.simulation_cli status
python -m origin_forge.simulation_cli sessions
python -m origin_forge.simulation_cli run-show <RUN-ID>
python -m origin_forge.simulation_cli artifact-show <ART-ID>
```

The CLI has only:

- `status`;
- `sessions`;
- `run-show`;
- `artifact-show`.

It has no simulation launch, specification-write, tuning, balance mutation, Task mutation, adoption, signing, merge or release command.

## Relationship to Phase 24

Phase 24 answers:

> What happened when a bounded synthetic player interacted with a real target?

Phase 25 answers:

> What happens when a cheap frozen abstract system model is executed many deterministic bounded times?

Simulation can therefore run before full runtime behavior exists and can cheaply expose resource deadlocks, runaway counters, impossible bounds or progression stalls. Runtime playtesting remains the stronger evidence surface for actual application behavior.

## Relationship to Phase 26 harness refinement

Phase 26 may evaluate whether a Skill, prompt, context strategy, routing policy, specialist contract or bounded mini-workflow improves outcomes. Phase-25 metrics may be included as frozen paired-evaluation evidence.

The authority rule remains:

```text
optimizer / candidate author
    !=
evaluator
    !=
acceptance authority
    !=
component activation authority
```

A candidate may not choose its own success criterion, rewrite the simulator, discard adverse seeds/results, or activate its own replacement merely because a metric improved.

## Explicit exclusions in v1

Not implemented or authorized:

- arbitrary simulation scripts or expression evaluators;
- caller/model-selected executable simulators;
- continuous physics simulation;
- spatial navigation/world geometry simulation;
- real-time application execution;
- semantic game-quality or balance judgment;
- automatic parameter search/tuning;
- automatic repair after simulation findings;
- production Task verification/completion;
- asset/config adoption;
- provenance signing;
- merge/release authority;
- live self-modification or harness activation.

## Phase-25 v1 exit condition

Phase 25 v1 is complete when one immutable repository head proves on the supported Python matrix that Origin Forge can:

1. freeze an immutable content-addressed bounded `SIMSPEC-*` simulation specification with exact governed engine identity;
2. deterministically execute finite seeded integer state-transition replicates without arbitrary code/process/network authority;
3. bound implemented rule/invariant work, state values, replicate/step counts, retained violation evidence and durable evidence bytes;
4. produce exact result evidence with deterministic SHA-256 probability decisions and reproducible ordering;
5. independently bind result structure to the exact specification and reject forged internal inconsistencies;
6. retain exact invariant counts, bounded violation details and no-progress/stall findings without treating them as infrastructure failure;
7. derive deterministic exact aggregate metrics without floating-point semantic authority;
8. persist exact spec/result/summary lineage through a separate `SIMULATOR` Run and `simulation-structure` Verification;
9. expose only read-only operator inspection; and
10. prove production Task/adoption/signing/merge/release and automatic-tuning authority remain unchanged.

The implementation/regression suite covers deterministic repeat execution, probability boundaries, rule prerequisites/consumption, invariant evidence, no-progress semantics, overflow, multi-replicate binding, maximum rule-metric shape, governed engine identity, implementation-aware work bounds, global violation-detail bounds, durable evidence byte bounds, protected workspace behavior, negative-finding-vs-infrastructure semantics, read-only CLI authority, and adversarial forged-result binding.

The PR may be merged only after the frozen closure head passes the normal Python 3.12/3.13 matrix and unrelated external evidence gates remain disarmed/skipped.
