# Phase 29 — Training / Fine-Tuning Research

Status: **DONE — governed offline trajectory/dataset/evaluation research substrate**

Phase 29 establishes the data and evaluation boundary required before any real training system can be considered. It does **not** execute gradient training, load candidate checkpoints into production, or allow a trainer/model to promote itself.

## Core rule

```text
verified history → trusted redacted producer → eligibility audit → frozen leakage-safe dataset
        ↓
independent experiment plan → candidate checkpoint evidence → independent evaluation → STOP
```

Training research evidence is not production model authority.

## v1 identities and objects

Phase 29 adds infrastructure-owned:

- `TRAJ-*` — bounded research trajectories;
- `TRAUD-*` — eligibility audits;
- `TRDATA-*` — frozen dataset manifests;
- `TRPLAN-*` — independently frozen experiment/evaluation plans;
- `TRREP-*` — candidate checkpoint evaluation reports.

The generic model layer can represent success, failure, and infrastructure-failure trajectory outcomes for future research, but the **only producer accepted into durable v1 datasets** is the frozen successful-runtime redaction adapter described below.

## Bounded research-value contract

A trajectory binds:

- exact project, Task and Run IDs;
- deterministic leakage-group hash;
- explicit outcome class;
- bounded objective label;
- optional model profile/hash;
- bounded canonical JSON example;
- exact typed Task/Run/Verification/Artifact/Decision evidence refs with hashes/revisions/disclosure classes;
- explicit false authority flags for production training, model activation and Task verification.

Verified success/failure records require Verification evidence. Source refs are bounded, deduplicated and sorted. Canonical JSON/text limits prevent unbounded transcript or arbitrary binary ingestion through the model contract.

## Trusted v1 trajectory producer

The only producer trusted for durable v1 datasets is:

```text
origin-forge-runtime-redacted @ 1
```

Its fingerprint content-addresses the exact projection/redaction contract.

`build_verified_runtime_trajectory()` accepts only:

- a task-scoped Run;
- Run status `SUCCEEDED`;
- terminal Task status `SUCCEEDED`;
- at least one `PASS` Task Verification whose `run_id` equals that exact successful Run.

It exports only a stable structural/cost projection:

- Task: ID, Flow ID, status, revision, attempt count;
- Run: ID, Task ID, role, model profile/hash, status, input/output token counts;
- Verification: ID, target type/ID, verification type, verifier, status, bound Run ID;
- deterministic Task-based leakage group;
- a redacted input/target/cost example.

It deliberately excludes:

- Task objective text;
- acceptance criteria and constraints;
- Verification evidence/metrics payloads;
- failure text;
- repository/source content;
- arbitrary Artifact bytes;
- secrets/protected state.

Tests seed those excluded fields with sentinel secret values and prove they are absent from serialized trajectory evidence.

Failed attempts are **not exported by the real v1 producer**. The generic trajectory schema preserves failure classes for future research, but widening the trusted producer to failed attempts requires a separately frozen disclosure/outcome policy. The current Task-based leakage-group policy already ensures future attempts for one Task must remain in one split.

## Trusted eligibility policy

The v1 dataset policy is:

```text
verified-runtime-redacted-v1 @ 1
```

Its fingerprint binds:

- the exact trusted producer ID/version/fingerprint;
- protected evidence as ineligible;
- no production-training authority.

`GovernedTrainingEligibilityAudit` recomputes eligibility from the trajectory. It adds `untrusted-producer` for generic/manual trajectories or producer identity/fingerprint drift, and `protected-evidence` for protected refs.

A forged `eligible=true` audit fails revalidation. Policy identity/fingerprint and trusted-producer metadata are also revalidated.

Generic/manual `TrainingTrajectory` and generic audit objects may exist as inert research records, but the durable v1 dataset store rejects them even when their self-declared disclosure flags look clean.

## Deterministic leakage-safe dataset splitting

`TrainingDatasetManifest` contains exact trajectory/audit IDs and hashes, leakage groups and infrastructure-assigned splits.

Split assignment is deterministic from:

- frozen split-salt hash;
- leakage-group hash;
- exact `80-10-10-v1` split policy.

The caller cannot choose the split. Every member of one leakage group deterministically maps to the same train/validation/test split. Caller-forged split changes fail at the model boundary, and durable publication reconstructs the dataset from the supplied trajectories/audits before accepting it.

Durable v1 dataset publication additionally requires:

- every trajectory is a trusted `GovernedTrainingTrajectory` from the exact redacted runtime producer;
- every audit is a `GovernedTrainingEligibilityAudit`;
- exact v1 eligibility-policy identity/fingerprint;
- every audit is eligible and rebinds to its trajectory;
- reconstructed dataset entries exactly match the supplied manifest.

## Frozen experiment plan

`TrainingExperimentPlan` freezes **before candidate evaluation**:

- exact dataset ID/hash;
- exact base model profile/hash;
- tokenizer hash;
- method family (`ROUTING_CLASSIFIER`, `SUPERVISED_FINETUNE`, `ADAPTER_LORA`, or `OFFLINE_DISTILLATION`);
- trainer ID/version/fingerprint;
- independent evaluator ID/version/fingerprint;
- evaluation-suite ID/hash;
- maximum training tokens;
- maximum wall time;
- maximum candidate-checkpoint bytes;
- regression/acceptance thresholds.

These are inert research commitments. The presence of trainer identity does not mean a trainer is wired or executable in v1.

## Candidate report and independent evaluation

`TrainingExperimentReport` stores only candidate **checkpoint hash/size** plus independently supplied baseline/candidate evaluation observations and the exact evaluator identity from the frozen plan.

The report recomputes regression-dominant classification over:

- success;
- quality;
- critical failures;
- model calls;
- input/output tokens;
- wall time.

A quality/success regression or cost/critical-failure increase beyond the frozen plan dominates efficiency gains. Forged verdicts, evaluator drift, plan drift and checkpoint-size violations fail closed.

Training loss is explicitly **not** promotion evidence. `TRREP-*` records no checkpoint bytes and provides no loader or activation surface.

## Immutable persistence

`.origin-forge/training-research/` provides protected immutable categories for:

- trajectories;
- eligibility audits;
- datasets;
- experiment plans;
- experiment reports.

The store enforces:

- protected-root containment;
- symlink/alias rejection;
- no overwrite;
- strict UTF-8 JSON and duplicate-key rejection;
- object-count/byte limits;
- canonical bytes/content-hash revalidation;
- trajectory↔audit revalidation;
- trusted-producer/policy enforcement for durable datasets;
- dataset reconstruction before publication;
- plan↔dataset binding;
- report↔plan/evaluator/classification revalidation.

## Read-only operator surface

`python -m origin_forge.training_research_cli` exposes only:

- `status`;
- list commands for the five immutable evidence categories;
- corresponding `*-show` commands.

`status` exposes the exact trusted producer and eligibility-policy fingerprints and reports all of the following false:

- dataset build;
- arbitrary-path ingestion;
- training execution;
- model download;
- checkpoint loading;
- model-profile mutation;
- routing activation;
- secret export;
- production Task mutation;
- Phase-26 promotion;
- provenance signing;
- merge/release.

There is no `train`, `finetune`, `distill`, ingestion, model-download, checkpoint-load, activation, Task, promotion, signing, merge or release command.

## Relationship to Phase 15 and Phase 26

Phase-15 Dream remains symbolic/offline memory consolidation and candidate generation. It is not gradient training.

Phase-26 Workshop gains no trusted model-candidate evaluator or activation path from Phase 29 v1. A future trained model candidate would require a separately governed evaluator family and explicit model-profile activation authority outside this research substrate.

## Why v1 deliberately stops before training

The roadmap phase is research, and the safety-critical prerequisite is proving dataset/evaluation governance before spending GPU resources or creating active weight artifacts. Phase 29 therefore stops at a reproducible research contract that can describe a candidate checkpoint by hash and independently evaluate it.

A future training backend must be separately justified and must preserve:

```text
trainer authority  ≠ evaluator authority
research checkpoint ≠ active ModelProfile
training loss       ≠ promotion evidence
```

No arbitrary training shell/process, external dataset path ingestion, internet model/dataset download, raw secret export, or production checkpoint loader exists in v1.

## Explicit v1 exclusions

Not implemented or authorized:

- production model self-training;
- live/online gradient updates;
- actual fine-tuning/LoRA/distillation process execution;
- automatic checkpoint/LoRA loading;
- automatic model-profile/routing replacement;
- arbitrary training shell/process execution;
- arbitrary external dataset ingestion;
- internet model/dataset download;
- secret/private-key/token inclusion in datasets;
- raw protected project-state training by default;
- trusted failed-attempt export;
- trainer-defined acceptance criteria;
- training-loss-only promotion;
- automatic Phase-26 promotion;
- production Task verification/completion;
- provenance signing;
- merge/release authority.

## v1 exit condition

Phase 29 v1 is complete when one immutable repository head proves on Python 3.12 and 3.13 that Origin Forge can:

1. construct a bounded trusted redacted research trajectory only from a successful terminal Task/Run with PASS Verification bound to that exact Run;
2. exclude protected/raw Task/Verification/repository content from that producer contract;
3. independently audit producer trust and disclosure eligibility;
4. deterministically assign leakage-group-preserving train/validation/test splits;
5. persist only governed eligible trajectories into durable v1 datasets with source/policy revalidation;
6. freeze exact base-model, tokenizer, trainer, evaluator, evaluation-suite, resource and acceptance identities before candidate evaluation;
7. represent candidate checkpoint results by bounded hash/size evidence and recompute regression-dominant independent evaluation verdicts;
8. persist/reconstruct the full research evidence chain and inspect it read-only; and
9. keep training execution, checkpoint loading, production model/routing mutation, Task authority, Phase-26 promotion, signing, merge and release outside Phase 29.
