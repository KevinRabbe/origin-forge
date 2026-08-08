# Phase 12 — Governed Skill Evaluation & Benchmarks

Status: **completion candidate; exact-head hosted CI required before merge**

Phase 12 creates the evidence layer required before Origin Forge can ever consider Skill rewriting or promotion.

The central rule is:

> A Skill changes procedure. Only externally measured evidence can say whether that procedure is better.

Phase 12 does **not** modify or promote Skills.

## Experimental identity

A valid Skill A/B comparison pins four independent identities:

1. immutable eval case
2. exact repository/fixture snapshot
3. exact scorer contract/version
4. exact model/tool/harness environment

The only intended difference between variants is the candidate Skill instruction bundle.

If baseline and candidate return different environment fingerprints, the benchmark fails instead of assigning the difference to the Skill.

## Eval case

`SkillEvalCase` contains:

- stable case ID
- `fixture_ref`
- `scorer_ref`
- objective
- acceptance criteria
- constraints
- required capabilities
- context paths
- tags
- SHA-256 content hash

The fixture and scorer refs are part of the case hash. Changing either creates a different benchmark case.

Case text/list sizes are bounded before execution.

## Paired experiment protocol

Current protocol ID:

```text
paired-skill-ab-v1
```

For every case/repetition:

```text
same immutable case
same fixture fingerprint
same scorer fingerprint
same environment fingerprint
same deterministic seed
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

This reduces systematic order/cache bias.

Seeds derive from:

```text
seed_base + stable case-content-hash offset + repetition
```

so suite reordering does not change a case's seed.

The report stores the exact paired seeds and execution order for every repetition.

## Exact Skill identity

Candidate variants record exact governed Phase-9 Skill refs:

```text
name@version#fingerprint-prefix
```

Candidate count and combined instruction bytes are bounded. Duplicate Skill refs are rejected.

Benchmarking reads Skills only.

## Trial boundary

`SkillBenchmarkRunner` receives a `SkillEvalTrial` callable.

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

The external trial implementation owns:

- fixture/worktree setup
- model execution
- tool execution
- deterministic verification/scoring
- timing/token measurement
- environment fingerprint construction

Unexpected trial infrastructure errors abort the benchmark rather than being silently counted as candidate failures.

## Trial result

Each result records bounded:

- success boolean
- normalized finite score `0..1`
- duration
- model calls
- input/output tokens
- fixture fingerprint
- environment fingerprint
- scorer fingerprint
- optional failure reason
- optional unique-key metadata

The runner verifies:

```text
result.fixture_fingerprint == case.fixture_ref
result.scorer_fingerprint  == case.scorer_ref
baseline.environment == candidate.environment
all trials in one report use the same environment fingerprint
```

This prevents an environment/model/tool change from masquerading as Skill improvement.

## Aggregation

Per variant/case:

- success rate
- mean score
- mean duration
- mean model calls
- mean input tokens
- mean output tokens

Per comparison:

- paired seeds
- execution orders
- raw baseline trials
- raw candidate trials
- score delta
- success-rate delta
- case verdict

Verdicts:

- `IMPROVED`
- `REGRESSED`
- `EQUIVALENT`
- `INCONCLUSIVE`

Success-rate differences take precedence over small score differences.

Score deltas use configured improvement/equivalence margins.

### Statistical limitation

These verdicts are deterministic policy classifications over supplied trials; they are **not** statistical-significance claims.

Default evaluation uses paired repetitions and preserves raw trials so later phases can add confidence intervals, bootstrap policies, or paired significance tests without rewriting old evidence.

## Regression dominance

Overall report policy is conservative:

```text
any REGRESSED case      → REGRESSED
else any INCONCLUSIVE   → INCONCLUSIVE
else any IMPROVED       → IMPROVED
else                    → EQUIVALENT
```

A gain on easy cases cannot average away a known regression.

## Experiment bounds

Before trial execution:

- case count bounded
- repetitions bounded
- case contents bounded
- candidate Skill count bounded
- candidate Skill instruction bytes bounded

Trial result metadata/failure strings are bounded as well.

## Immutable case store

Protected location:

```text
.origin-forge/skill-evals/cases/<case-id>.json
```

Case IDs are immutable.

- identical write: idempotent
- changed meaning under same ID: rejected
- symlink/unsupported entries: rejected
- reads bounded
- catalog count bounded
- atomic writes use unique temporary files

A changed fixture, scorer, task, constraints, or acceptance criteria therefore requires a new case hash/identity.

## Content-addressed report store

Protected location:

```text
.origin-forge/skill-evals/reports/<report-id>.json
```

Before saving, the store verifies:

- every report case exists durably with the same hash
- every report Skill ref still matches the live governed Skill snapshot

This closes the race where a Skill changes after evaluation but before the result is persisted.

Reports include:

- format version
- protocol ID
- environment fingerprint
- exact Skill refs
- suite hash over sorted `(case_id, case_hash)` pairs
- raw paired trials
- aggregate metrics/verdicts
- content-addressed report ID/hash

Report count and bytes are bounded. Identical reports are idempotent.

## Historical validity vs replayability

`SkillEvalReplayInspector` separates:

### Integrity

Stored report ID/content hash/envelope/protocol/suite hash must verify.

Tampering fails closed.

### Replayability

A historically valid report is currently replayable only when:

- all referenced cases still exist with the same hashes
- all referenced Skill names still resolve to the same exact Skill refs

If the Skill later changes, the old report remains valid historical evidence but becomes stale for replay.

## Operator CLI

Evidence-only commands:

```text
python -m origin_forge.skill_eval_cli case-list
python -m origin_forge.skill_eval_cli case-show <case-id>
python -m origin_forge.skill_eval_cli case-add <case-id> \
  --fixture-ref <ref> --scorer-ref <ref> --objective ...
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

Phase 12 adds no model or filesystem authority beyond protected evidence storage.

It does not:

- mutate active Skills
- promote candidates
- download Skills
- execute Skill scripts
- modify security policy
- bypass worktree/sandbox rules
- let model self-assessment determine benchmark truth

The external trial/scorer supplies measured evidence; the benchmark runner pairs and records it.

## Future Skill Workshop relationship

A later governed Skill Workshop may use:

```text
observed correction/success
→ proposed Skill change bound to current Skill hash
→ static/security scan
→ paired baseline/candidate benchmark
→ regression/replay checks
→ human approval
→ promotion
```

Phase 12 implements only the benchmark/evidence substrate.

## Deferred

Not included:

- automatic Skill generation
- automatic Skill rewriting
- automatic Skill promotion
- executable Skill content
- internet Skill installation
- benchmark-specific model judge in the core evaluator
- statistical-significance claims
- model fine-tuning
- Skill marketplace
