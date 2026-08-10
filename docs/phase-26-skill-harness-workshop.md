# Phase 26 — Skill & Harness Workshop

Status: **DONE — governed proposal, evaluation, audit and promotion-eligibility substrate**

Phase 26 turns verified trajectories, Dream proposals and benchmark evidence into bounded improvement candidates without introducing live self-modification.

## Core rule

```text
source evidence
    ↓
minimal immutable improvement candidate
    ↓
independently frozen evaluation plan
    ↓
trusted regression-dominant evaluation evidence
    ↓
independent structural audit
    ↓
promotion-eligibility decision
    ↓
STOP

promotion eligibility != production activation
```

The candidate author, Dream process, evaluator, acceptance authority and activation authority remain separate roles.

## Relationship to existing phases

Phase 26 extends existing governance rather than replacing it:

- Phase 12 remains the authoritative paired Skill benchmark implementation for Skill candidates.
- Phase 15 Dream candidates remain proposal/source evidence and retain their mandatory downstream gates.
- Phase 25 simulation evidence may be referenced by future frozen evaluation plans, but candidate-authored post-hoc acceptance criteria remain forbidden.
- Phase 27 remains the place for sandboxed model-written mini-workflow and programmatic-context experiments. Phase 26 can represent a mini-workflow candidate as inert data, but v1 neither executes nor activates one.

## Improvement candidates

`HarnessImprovementCandidate` represents exactly one bounded target:

- `SKILL`
- `PROMPT`
- `CONTEXT_STRATEGY`
- `ROUTING_POLICY`
- `SPECIALIST_CONTRACT`
- `MINI_WORKFLOW`

Every candidate binds:

- infrastructure-owned `HIC-*` identity;
- exact target component ID/version/hash;
- exact baseline payload hash;
- exact source-evidence IDs/hashes/classes;
- one bounded canonical candidate payload;
- bounded hypothesis, expected metric effects and known risks;
- evaluator family fixed by target kind;
- optional exact originating Dream candidate ID/hash/required gate.

Candidate payloads are inert canonical JSON data. v1 bounds depth, node count, collections, strings and total bytes; rejects floats and non-JSON objects; and never interprets payload fields as shell commands, executable paths, callbacks, source code, arbitrary tool calls or process authority.

A candidate payload must differ from the baseline payload hash. Bundled multi-component self-upgrades are outside the v1 contract.

## Smallest-change principle

Phase 26 adopts this invariant:

> An improvement proposal must contain the smallest independently evaluable change capable of testing its stated hypothesis.

Infrastructure cannot prove that prose is philosophically minimal, but it does enforce one target component and one immutable payload delta. Evaluation remains tied to a separately frozen plan.

## Independent evaluation plans

`WorkshopEvaluationPlan` is infrastructure-owned and content-addressed separately from the candidate. The candidate therefore cannot define or rewrite its own acceptance gate.

A plan binds:

- infrastructure-owned `HPLAN-*` identity;
- exact candidate ID/hash;
- exact evaluator family/protocol;
- exact evaluation evidence references/hashes;
- exact metric IDs and direction;
- integer minimum-improvement and maximum-regression thresholds;
- exact cost ceilings for model calls, input/output tokens, wall time and resource units;
- regression-dominant policy.

Changing the candidate, evaluator, evidence suite, metric, threshold or cost ceiling changes the plan hash. Completed evidence cannot be silently reinterpreted under a different plan.

Candidate `expected_effects` are hypotheses only and never populate or override the plan's acceptance criteria.

## Trusted evaluator registry

Promotion-capable evaluator protocols are infrastructure-owned code, not candidate data and not free-form plan authority.

The v1 registry contains exactly one promotion-capable adapter:

```text
SKILL_BENCHMARK → paired-skill-ab-v1 (Phase 12)
```

The following evaluator families deliberately have no promotion-capable v1 adapter:

- `PROMPT_BENCHMARK`
- `CONTEXT_BENCHMARK`
- `ROUTING_BENCHMARK`
- `SPECIALIST_BENCHMARK`
- `MINI_WORKFLOW_BENCHMARK`

Candidates, plans and generic reports for those families may still be represented and retained as evidence, but structural audit fails closed for promotion until a separately governed evaluator adapter is added to the infrastructure-owned registry with its own evidence validation.

A plausible protocol string such as `prompt-benchmark-v1` therefore grants no authority by itself.

## Regression-dominant evaluation reports

`WorkshopEvaluationReport` binds the exact candidate and plan and references immutable evaluator evidence.

Metric keys must exactly equal the frozen plan. Candidate-chosen extra metrics are rejected.

Each metric records exact integer baseline/candidate values, signed improvement and verdict. v1 also records baseline/candidate cost totals and deltas for:

- model calls;
- input tokens;
- output tokens;
- wall time;
- resource units.

Overall generic report policy is regression-dominant:

```text
any required metric regression → REGRESSED
any candidate cost ceiling exceeded → REGRESSED
otherwise any required improvement → IMPROVED
otherwise → EQUIVALENT
```

`INCONCLUSIVE` remains a first-class effective verdict for trusted evaluator evidence that cannot establish a comparison.

## Phase-12 Skill reuse

For `SKILL` targets, Phase 26 consumes an exact Phase-12 `SkillBenchmarkReport`; it does not reimplement the paired trial runner.

The adapter requires:

- target kind `SKILL`;
- evaluator family `SKILL_BENCHMARK`;
- protocol `paired-skill-ab-v1`;
- exact Phase-12 report content hash;
- benchmark-class evidence binding.

The effective Skill verdict is the more conservative of the Phase-26 metric/cost report and Phase 12's own overall paired benchmark verdict.

Consequences:

- Phase-12 `REGRESSED` can never become Phase-26 `IMPROVED`;
- Phase-12 `EQUIVALENT` caps a separate Phase-26 improvement at `EQUIVALENT`;
- a Phase-26 regression remains a regression even if Phase 12 improved.

Phase 26 may become stricter than Phase 12 but may not weaken Phase-12 evidence.

## Structural audit

`WorkshopEvaluationAudit` independently rebinds exact candidate, plan and evaluation evidence.

Audit requires the evaluator protocol to exist in the trusted promotion registry. Skill audit additionally requires the Phase-12 Skill adapter and exact Phase-12 report. A generic Workshop report cannot bypass those requirements.

The audit records:

- infrastructure-owned `HAUD-*` identity;
- exact candidate/plan/report/evaluation hashes;
- effective verdict;
- `PASS` or `FAIL`;
- bounded structural findings;
- `semantic_correctness_verified = false`;
- `production_activation_authorized = false`.

A structurally valid negative evaluation may receive audit `PASS`; that means the evidence is well-formed, not that the candidate is desirable.

## Promotion eligibility is not activation

`WorkshopDecision` records one of:

- `APPROVE_FOR_PROMOTION`
- `REJECT`
- `DEFER`

`APPROVE_FOR_PROMOTION` requires:

1. the decision to rebind the exact candidate, plan, audit and evaluation;
2. audit `PASS`;
3. effective verdict `IMPROVED`;
4. a currently trusted promotion-capable evaluator protocol; and
5. for Skills, exact Phase-12 adapter/report revalidation again at decision time.

The final revalidation prevents a manually forged `PASS` audit object from amplifying an unsupported evaluator into promotion eligibility.

Unsupported evaluators can still produce durable `DEFER` or `REJECT` decisions so evidence is retained without authority escalation.

Even an `APPROVE_FOR_PROMOTION` decision sets `production_activation_authorized = false`. Phase 26 does not install, enable, overwrite, route traffic to or otherwise activate a candidate.

## Dream bridge

The proposal-only bridge pins the exact Dream candidate ID/hash/type/required gate into a new independently content-addressed Workshop candidate.

Supported mappings:

- Dream `SKILL` → Workshop `SKILL`, preserving `SKILL_EVALUATION`;
- Dream `ROUTING` → Workshop `ROUTING_POLICY`, preserving `ROUTING_BENCHMARK`;
- Dream `CONTEXT` → Workshop `CONTEXT_STRATEGY`, preserving `CONTEXT_BENCHMARK`;
- Dream `PROCESS` → explicitly infrastructure-selected `PROMPT`, `SPECIALIST_CONTRACT` or `MINI_WORKFLOW`, preserving `ENGINEERING_REVIEW`.

Dream `MEMORY` and `DATA_QUALITY` keep their Phase-15 gates and are rejected by the Workshop bridge. Non-`PROCESS` Dream candidates cannot choose a different Workshop target family.

Bridging never satisfies the Dream downstream gate. Since v1 trusts only the Phase-12 Skill evaluator, Dream routing/context/process proposals can be represented and inspected but cannot become promotion-eligible yet.

## Immutable persistence

`HarnessWorkshopStore` persists canonical envelopes under:

```text
.origin-forge/workshop/
├── candidates/
├── plans/
├── reports/
├── audits/
└── decisions/
```

The store provides:

- exact ID-kind validation (`HIC-*`, `HPLAN-*`, `HREP-*`, `HAUD-*`, `HDEC-*`);
- canonical UTF-8 JSON envelopes with schema version/type/ID/hash/payload;
- 512 KiB per-object limit;
- 10,000-object limit per category;
- exclusive no-overwrite publication with flush/fsync;
- symlink/root/category/object containment checks;
- duplicate-key rejection;
- canonical-byte and content-hash revalidation on load;
- object revalidation while listing.

Downstream objects bind immutable upstream hashes, so post-publication rewriting creates detectable drift rather than silent reinterpretation.

## Read-only operator surface

The inspection-only CLI exposes:

```text
python -m origin_forge.harness_workshop_cli status
python -m origin_forge.harness_workshop_cli candidates
python -m origin_forge.harness_workshop_cli plans
python -m origin_forge.harness_workshop_cli reports
python -m origin_forge.harness_workshop_cli audits
python -m origin_forge.harness_workshop_cli decisions
python -m origin_forge.harness_workshop_cli candidate-show <HIC-ID>
python -m origin_forge.harness_workshop_cli plan-show <HPLAN-ID>
python -m origin_forge.harness_workshop_cli report-show <HREP-ID>
python -m origin_forge.harness_workshop_cli audit-show <HAUD-ID>
python -m origin_forge.harness_workshop_cli decision-show <HDEC-ID>
```

`status` also exposes the read-only trusted evaluator registry snapshot. All execution/mutation authority flags remain false.

There is no candidate creation, evaluation execution, refinement, promotion execution, activation, installation, rewrite, Task mutation, provenance signing, merge or release command.

## Explicit exclusions in v1

Not implemented or authorized:

- live prompt/Skill/harness rewriting by a running agent;
- candidate-defined acceptance metrics or promotion-capable evaluator protocols;
- generic model-authored evaluator code;
- promotion-capable prompt/context/routing/specialist/mini-workflow evaluator adapters;
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

## Phase-26 v1 exit condition — MET

Phase 26 v1 is complete because the implementation can:

1. freeze a content-addressed single-target improvement candidate over exact source evidence;
2. freeze an independent evaluation plan whose acceptance criteria cannot be changed by the candidate;
3. reuse exact Phase-12 Skill benchmark evidence rather than reimplementing Skill evaluation;
4. restrict promotion-capable evaluation to infrastructure-owned trusted adapters, with unsupported evaluator families failing closed;
5. derive a bounded regression-dominant metric/cost report whose metric keys exactly match the frozen plan;
6. preserve the more conservative Phase-12 Skill verdict rather than weakening it;
7. independently audit candidate/plan/evaluation bindings and separate structural validity from semantic quality;
8. revalidate evaluator trust at decision time and record promotion eligibility only for trusted, structurally valid, effective `IMPROVED` evidence;
9. persist and revalidate immutable bounded Workshop objects;
10. bridge supported Dream candidates only as exact proposal/source evidence while preserving downstream-gate semantics;
11. expose Workshop state and evaluator trust through read-only inspection; and
12. keep production Task completion/verification, active Skill/prompt/routing/context mutation, candidate activation, provenance signing, merge and release authority outside the Workshop.

**Merge gate:** the immutable closure head must pass the normal Python 3.12/3.13 matrix with unrelated external evidence workflows disarmed/skipped before SHA-guarded merge.
