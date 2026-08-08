# Phase 12 — Governed Skill Evaluation & Benchmarks

Status: **development candidate; full hosted matrix required before merge**

Phase 12 creates the evidence layer required before Origin Forge can ever consider Skill improvement or promotion.

The central rule is:

> A Skill may change procedure, but only external evaluation may tell us whether the changed procedure is better.

Phase 12 does **not** modify or promote Skills.

## Experimental model

A benchmark contains immutable `SkillEvalCase` definitions.

Each case is evaluated in paired variants:

```text
same case + same repetition + same seed
├── baseline: no Skill instructions
└── candidate: exact governed Skill snapshot(s)
```

Execution order alternates by repetition:

```text
rep 0: baseline → candidate
rep 1: candidate → baseline
rep 2: baseline → candidate
...
```

This reduces systematic order/cache bias while preserving paired seeds.

Seeds are derived from:

```text
seed_base + stable case-content-hash offset + repetition
```

so reordering a suite does not silently change a case's random seed.

## Exact Skill identity

Candidate variants record exact Phase-9 Skill refs:

```text
name@version#fingerprint-prefix
```

The benchmark therefore evaluates a specific immutable Skill snapshot, not merely a Skill name.

The candidate variant is bounded by:

- maximum Skill count
- maximum combined instruction bytes
- duplicate-ref rejection

Benchmarking reads Skills only. It does not write to the Skill registry.

## Eval cases

A `SkillEvalCase` contains:

- stable case ID
- objective
- acceptance criteria
- constraints
- required capabilities
- context paths
- tags
- SHA-256 content hash

Cases can be persisted under:

```text
.origin-forge/skill-evals/cases/<case-id>.json
```

The case ID is immutable.

Writing the same ID with identical bytes is idempotent. Attempting to change the meaning of an existing ID fails closed. A changed benchmark must receive a new case ID/hash.

This prevents benchmark drift from being mistaken for Skill improvement.

## Trial boundary

`SkillBenchmarkRunner` does not own model/tool execution.

It receives a `SkillEvalTrial` callable:

```text
SkillEvalTrialRequest
├── immutable case
├── baseline/candidate variant
├── repetition
└── paired seed
        ↓
external trial implementation
        ↓
SkillEvalTrialResult
```

The trial implementation owns:

- model execution
- tool execution
- fixture/workspace setup
- external scoring
- model/token measurements

This keeps the experiment engine independent of a specific model backend or coding workflow.

Unexpected trial infrastructure errors should fail the benchmark run rather than be silently converted into candidate failures.

## Raw trial result

Each result records:

- success boolean
- normalized score `0..1`
- duration
- model-call count
- input tokens
- output tokens
- optional failure reason
- optional bounded metadata

The report preserves raw paired results as well as aggregates.

## Aggregates

Per variant/case:

- trial count
- success rate
- mean score
- mean duration
- mean model calls
- mean input tokens
- mean output tokens

Per comparison:

- score delta
- success-rate delta
- case verdict

Current verdicts:

- `IMPROVED`
- `REGRESSED`
- `EQUIVALENT`
- `INCONCLUSIVE`

Success-rate differences take precedence over small score differences.

A score delta must exceed the configured improvement threshold before it becomes `IMPROVED` or `REGRESSED`; sufficiently small deltas become `EQUIVALENT`; the middle band is `INCONCLUSIVE`.

### Important statistical limitation

These verdicts are deterministic policy classifications over the supplied trials. They are **not** claims of statistical significance.

The default uses multiple paired repetitions, and all raw trials are retained so future phases can add confidence intervals, paired statistical tests, or bootstrap policies without rewriting old evidence.

## Regression dominance

Overall report policy is deliberately conservative:

```text
any REGRESSED case      → REGRESSED
else any INCONCLUSIVE   → INCONCLUSIVE
else any IMPROVED       → IMPROVED
else                    → EQUIVALENT
```

An improvement on easy cases cannot average away a known regression on another case.

## Experiment bounds

Before trial execution, the runner bounds:

- case count
- repetition count
- candidate Skill count
- candidate instruction bytes

Trial outputs validate:

- finite score
- score range
- non-negative duration
- non-negative model calls
- non-negative token counts
- structured metadata

## Durable reports

Reports are stored under:

```text
.origin-forge/skill-evals/reports/<report-id>.json
```

The store records:

- content-addressed report ID
- SHA-256 report hash
- suite hash over sorted `(case_id, case_hash)` pairs
- exact Skill refs
- raw paired trials
- aggregates
- verdicts

Identical reports are idempotent.

## Historical validity vs replayability

`SkillEvalReplayInspector` distinguishes two different questions.

### Is the stored report intact?

The report ID, content hash, format, and suite hash must verify.

Tampering fails closed.

### Can the experiment be replayed against current live inputs?

A report is replayable only if:

- every referenced eval case still exists with the same content hash
- every referenced Skill name currently resolves to the same exact Skill ref/fingerprint

If the Skill later changes, the old report remains valid historical evidence, but its replay status becomes stale.

This is the intended behavior: history does not change merely because live state changes.

## Operator CLI

Phase 12 exposes only evidence-management operations:

```text
python -m origin_forge.skill_eval_cli case-list
python -m origin_forge.skill_eval_cli case-show <case-id>
python -m origin_forge.skill_eval_cli case-add <case-id> --objective ...
python -m origin_forge.skill_eval_cli report-list
python -m origin_forge.skill_eval_cli report-show <report-id>
python -m origin_forge.skill_eval_cli report-status <report-id>
```

There is deliberately no:

```text
promote
install
rewrite
apply-skill
self-modify
```

command.

## Authority boundary

Phase 12 adds no model or filesystem authority.

It does not:

- mutate active Skills
- promote candidate Skills
- download Skills
- execute Skill scripts
- modify security policy
- bypass worktree/sandbox rules
- let model output decide benchmark truth

The external trial/scorer provides the measurement; the benchmark runner records and compares it.

## Future relationship to Skill Workshop

A later governed Skill Workshop may use this evidence pipeline:

```text
observed correction/success
→ proposed Skill change
→ static/security scan
→ baseline vs candidate benchmark
→ regression check
→ replay/integrity check
→ human approval
→ promotion
```

Phase 12 implements only the benchmark/evidence portion.

A future proposal must be bound to the exact base Skill hash it was created from so stale proposals cannot be promoted after the Skill changes.

## Deferred

Not included in Phase 12:

- automatic Skill generation
- automatic Skill rewriting
- automatic Skill promotion
- executable Skill content
- internet Skill installation
- blind model-judge implementation
- statistical-significance claims
- benchmark-driven model fine-tuning
- model-specific trial adapters embedded in the core evaluator
- cross-project public Skill marketplace
