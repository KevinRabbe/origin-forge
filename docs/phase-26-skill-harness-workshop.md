# Phase 26 — Skill & Harness Workshop

Status: **IN PROGRESS — governed improvement-candidate and evaluation substrate**

Phase 26 turns verified trajectories, audited Dream findings and benchmark evidence into bounded improvement proposals without introducing live self-modification.

## Core rule

```text
source evidence
    ↓
minimal immutable improvement candidate
    ↓
independently frozen evaluation plan
    ↓
paired / regression-dominant evaluation evidence
    ↓
independent structural audit
    ↓
promotion-eligibility decision

promotion eligibility != production activation
```

The candidate author, optimizer, Dream process, evaluator, acceptance authority and activation authority remain separate roles.

## Relationship to existing phases

Phase 26 extends rather than replaces existing governance:

- Phase 12 remains the authoritative paired Skill benchmark implementation for Skill candidates.
- Phase 15 Dream candidates remain proposal-only source evidence and retain their mandatory downstream gates.
- Phase 25 simulation evidence may later participate in frozen evaluation plans, but a candidate cannot choose seeds/metrics after evaluation starts.
- Phase 27 remains the place to experiment with executable model-written mini-workflows/programmatic context. Phase 26 may represent a mini-workflow improvement proposal, but v1 does not execute or activate one.

## Improvement candidate

A `HarnessImprovementCandidate` proposes exactly one bounded component change.

Supported target kinds:

- `SKILL`
- `PROMPT`
- `CONTEXT_STRATEGY`
- `ROUTING_POLICY`
- `SPECIALIST_CONTRACT`
- `MINI_WORKFLOW`

Every candidate binds:

- infrastructure-owned candidate ID;
- exact target component ID/version/hash;
- exact source evidence references/hashes;
- optional exact originating Dream candidate ID/hash;
- a bounded hypothesis;
- one bounded immutable candidate payload;
- the exact baseline payload hash;
- the expected metric effects as hypotheses only;
- known risks;
- the required evaluator family for the target kind.

The payload is data, not executable authority. v1 accepts bounded canonical JSON-compatible configuration/instruction data and rejects binary blobs, callables, paths-as-authority, commands and executable hooks.

The improvement must be one independently evaluable target. Bundled multi-component self-upgrades are rejected.

## Smallest-change principle

Phase 26 adopts the following invariant:

> An improvement proposal must contain the smallest independently evaluable change capable of testing its stated hypothesis.

The infrastructure cannot prove that prose is philosophically "minimal", but the contract enforces one target component and one immutable payload delta. Auditors/evaluators may reject a candidate whose scope exceeds the frozen evaluation plan.

## Independent evaluation plan

A `WorkshopEvaluationPlan` is infrastructure-owned and frozen separately from the candidate. The candidate does not define its own acceptance gate.

A plan binds:

- candidate ID/hash;
- exact evaluator family/protocol;
- exact suite/evidence references and hashes;
- declared metrics;
- direction (`HIGHER_IS_BETTER` / `LOWER_IS_BETTER` / `MUST_NOT_REGRESS`);
- minimum improvement or maximum regression thresholds represented as exact integers/rationals where possible;
- cost ceilings for model calls, tokens, wall time and resource units;
- regression policy;
- explicit required evidence count.

Changing a metric, threshold, seed suite, scorer or evaluator creates a new plan/hash. It cannot retroactively reinterpret a completed candidate evaluation.

## Evaluation evidence

A `WorkshopEvaluationReport` binds the exact candidate and plan and references immutable evaluator evidence.

For `SKILL` targets, v1 consumes an exact Phase-12 `SkillBenchmarkReport` envelope/report hash and preserves its regression-dominant verdict. Phase 26 does not reimplement the Skill trial runner.

Other target kinds initially support evidence/report contracts and independent evaluator adapters, but no generic model-authored evaluator is accepted. An evaluator must be a trusted infrastructure adapter associated with the frozen plan's evaluator family.

Overall workshop verdicts are regression-dominant:

```text
any required regression → REGRESSED
required evidence missing / ambiguous → INCONCLUSIVE
required improvement with no regressions → IMPROVED
all within equivalence policy → EQUIVALENT
```

Improvements may also fail policy because cost ceilings are exceeded even when task metrics improve.

## Audit and eligibility

`WorkshopEvaluationAudit` independently verifies structural bindings:

- exact candidate hash;
- exact plan hash;
- exact evaluator evidence refs/hashes;
- exact baseline/candidate target hashes;
- verdict consistency;
- required evidence completeness;
- no changed plan after the report;
- no candidate self-reference as acceptance evidence.

A structurally valid audit does not prove semantic correctness.

A later `WorkshopDecision` may record only promotion eligibility:

- `APPROVE_FOR_PROMOTION`
- `REJECT`
- `DEFER`

The decision must bind a passing structural audit and frozen report. It does **not** install, enable, overwrite, route traffic to, or otherwise activate the candidate.

Actual activation remains a separate governed component-specific operation. Phase 26 v1 does not invent a generic production-component registry merely to make self-improvement look complete.

## Dream bridge

An audited Phase-15 Dream candidate may become source evidence only when its type maps to an appropriate workshop target:

- Dream `SKILL` → Workshop `SKILL`
- Dream `ROUTING` → Workshop `ROUTING_POLICY`
- Dream `CONTEXT` → Workshop `CONTEXT_STRATEGY`
- Dream `PROCESS` → Workshop `PROMPT`, `SPECIALIST_CONTRACT`, or `MINI_WORKFLOW` only through an explicit infrastructure mapping

Dream `MEMORY` and `DATA_QUALITY` keep their existing downstream gates and are not silently routed through the workshop.

The Dream candidate's `required_gate` remains evidence about what must happen next; converting it to a workshop candidate never satisfies that gate by itself.

## Persistent evidence

The planned protected store is:

```text
.origin-forge/workshop/
├── candidates/
├── plans/
├── reports/
├── audits/
└── decisions/
```

Objects are immutable, content-addressed, byte/count bounded, symlink-safe and revalidated when loaded. No object may be silently rewritten after downstream evidence has bound its hash.

## Read-only operator surface

The initial CLI is inspection-only:

```text
workshop status
workshop candidates
workshop candidate-show <ID>
workshop plan-show <ID>
workshop report-show <ID>
workshop audit-show <ID>
workshop decision-show <ID>
```

It intentionally has no `refine`, `apply`, `promote`, `activate`, `install`, `rewrite`, `merge` or `release` command.

## Explicit exclusions in v1

Not implemented or authorized:

- live prompt/Skill/harness rewriting by a running agent;
- candidate-defined acceptance metrics;
- generic model-authored evaluator code;
- generic executable mini-workflows;
- automatic production activation;
- automatic Skill installation/replacement;
- automatic routing/context-policy mutation;
- hidden persistent autonomous-agent state as canonical memory;
- recursive authority amplification;
- Task verification/completion;
- source/config mutation;
- asset adoption;
- provenance signing;
- merge/release authority;
- model weight updates.

## Initial v1 exit condition

Phase 26 v1 is complete when one immutable repository head proves on the supported Python matrix that Origin Forge can:

1. freeze one content-addressed single-target improvement candidate over exact source evidence;
2. freeze an independent evaluation plan whose acceptance criteria cannot be changed by the candidate;
3. reuse Phase-12 Skill benchmark evidence for Skill candidates rather than reimplementing Skill evaluation;
4. accept only trusted evaluator-family evidence for non-Skill candidates;
5. derive a regression-dominant bounded report including task metrics and cost/resource evidence;
6. independently audit candidate/plan/report/evaluator bindings;
7. record a promotion-eligibility decision without production activation authority;
8. persist and revalidate immutable bounded workshop objects;
9. bridge supported Dream candidates only as proposal/source evidence while preserving their downstream-gate semantics;
10. expose workshop state through read-only inspection; and
11. prove the workshop cannot verify/complete production Tasks, mutate active Skills/prompts/routing/context, activate candidates, sign provenance, merge or release.
