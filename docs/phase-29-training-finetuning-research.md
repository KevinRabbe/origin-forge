# Phase 29 — Training / Fine-Tuning Research

Status: **IN PROGRESS — offline verified-trajectory research substrate**

Phase 29 investigates whether verified Origin Forge trajectories can improve routing, tool use, coding assistance, or infrastructure-native model behavior without allowing production models to rewrite their own weights or allowing a training process to promote itself.

## Core rule

```text
verified history → frozen research dataset → independent experiment plan → offline candidate evidence → independent evaluation → STOP
```

Training research may create evidence and candidate weight artifacts. It does not change the model profiles used by production execution.

## Why dataset governance comes first

The repository already has substantial durable evidence across Goal / Flow / Task / Run, verification, Dream, specialist, media, playtest, simulation and workshop phases. A training system that simply dumps that history into a model would mix:

- verified and failed work;
- infrastructure failures and semantic failures;
- model inputs and privileged infrastructure state;
- secrets or protected state that should never become training text;
- near-duplicate attempts that could leak across train/evaluation splits;
- downstream evaluation evidence that could contaminate the training target;
- unsupported assumptions about whether a trajectory is actually useful to imitate.

Phase 29 therefore starts with immutable **dataset eligibility and split contracts**, not GPU training code.

## v1 research objects

The initial substrate uses infrastructure-owned immutable objects for:

- `TrainingTrajectory` — one bounded exact research example assembled from eligible durable evidence;
- `TrainingDatasetManifest` — a frozen set of trajectory IDs/hashes plus split assignment and dataset-policy identity;
- `TrainingExperimentPlan` — an independently frozen research hypothesis, base-model identity, dataset binding, method family, resource ceiling and evaluation requirements;
- `TrainingExperimentReport` — evidence-only result binding candidate checkpoint identity to the plan and independently supplied evaluation metrics.

All objects are canonical/content-addressed and proposal/evidence only.

## Trajectory boundary

A v1 trajectory is **not** an arbitrary transcript dump. It is a bounded typed record that may include only explicitly disclosed research fields such as:

- task objective / acceptance criteria;
- exact selected context or context hashes where permitted;
- exact model profile/hash used by the recorded Run;
- bounded model request/response evidence where the upstream contract permits research disclosure;
- proposed patch/tool/context decision evidence;
- independent audit / verification outcome;
- terminal Run / Task outcome;
- bounded cost metrics;
- exact source evidence refs/hashes/revisions.

It must preserve failure semantics. Infrastructure failure is not relabeled as a bad model answer, and a failed semantic attempt is not silently removed merely because a later retry succeeded.

## Eligibility policy

Dataset inclusion is infrastructure-owned. A model or trainer cannot mark its own trajectory eligible.

The v1 policy must fail closed on at least:

- nonterminal or mutable source evidence;
- missing exact hashes/revisions;
- unverifiable Task/Run ownership;
- protected/secret evidence classes;
- explicit `training_allowed = false` evidence;
- unsupported binary/raw media payloads;
- oversized fields;
- malformed UTF-8/control data;
- unbounded arbitrary filesystem content;
- candidates whose required independent verification is absent.

A trajectory may represent success or failure, but the outcome class and verifier evidence remain explicit.

## Split integrity and leakage control

Train/validation/test membership is infrastructure-owned and deterministic from frozen grouping keys. Samples that share the same leakage group must remain in one split.

Leakage grouping should conservatively bind related examples such as:

- retries/attempts for the same Task;
- equivalent fixture/case identity;
- the same source snapshot or benchmark case;
- derivative examples that would expose the held-out target;
- paired baseline/candidate trials that must not straddle train/test.

The model/trainer cannot choose a favorable split.

## Experiment plan

A `TrainingExperimentPlan` freezes before training:

- exact dataset manifest ID/hash;
- exact base model profile/hash and tokenizer/runtime identity;
- method family (for example routing classifier, supervised fine-tune, adapter/LoRA research, or offline distillation);
- hyperparameter/effective-token/resource ceilings as inert data;
- exact trainer implementation/version/fingerprint if a trainer is later introduced;
- required independent evaluation suite IDs/hashes;
- acceptance thresholds and regression ceilings;
- checkpoint byte/count limits;
- whether raw candidate weights may be retained at all.

The candidate does not define its own acceptance criteria after seeing evaluation results.

## Candidate checkpoint boundary

Any future trained checkpoint is a **research artifact**, not an active Origin Forge model.

A checkpoint record must bind:

- exact experiment plan;
- exact base model;
- exact dataset;
- exact trainer identity;
- exact checkpoint/content hash;
- resource/training metrics;
- independent evaluation evidence.

It has no `ModelProfile` activation, routing, production loader, Task completion, signing, merge or release authority.

## Independent evaluation

Training success cannot be measured by training loss alone. Evaluation must be separate from the trainer and regression-dominant.

Depending on the research family, metrics may include:

- frozen task/case success;
- verifier/audit pass rate;
- critical failure rate;
- tool-selection precision/recall;
- context sufficiency / irrelevant-context rate;
- model calls and token cost;
- wall time/resource cost;
- held-out leakage checks;
- baseline-vs-candidate regressions.

The trainer/candidate may emit metrics, but those metrics never self-certify promotion.

## Relationship to Phase 15 and Phase 26

Phase-15 Dream consolidation remains symbolic/offline memory and proposal generation. It does not become gradient training.

Phase-26 Workshop may eventually receive a bounded `MODEL_CANDIDATE` research proposal only after Phase 29 has a trusted evaluator family. Phase 29 v1 does **not** add such a promotion-capable evaluator and does not activate candidate weights.

## Persistence and operator surface

Research manifests/plans/reports must use protected immutable no-overwrite persistence with canonical/hash/source-reference revalidation and read-only inspection.

No v1 CLI may expose:

- `train` / `finetune` / `distill` execution;
- arbitrary dataset path ingestion;
- arbitrary model download;
- production model/profile replacement;
- route activation;
- secret/token export;
- Task completion/verification;
- signing/merge/release.

## Initial implementation checkpoints

1. immutable IDs/models for trajectory, dataset manifest, experiment plan and report;
2. bounded explicit research-value schema with strict text/JSON/resource limits;
3. deterministic leakage-group-preserving split assignment;
4. eligibility/audit contract that cannot be set by the model/trainer;
5. protected immutable research persistence and read-only inspection;
6. at least one real adapter from existing terminal Run/Task/Verification evidence into a bounded trajectory, with protected fields excluded;
7. adversarial tests for source drift, split leakage, forged eligibility, duplicate evidence, dataset drift and self-reported promotion;
8. offline experiment-report comparison contract with independent evaluator identity and regression-dominant semantics;
9. no production weight-loading or training execution until the dataset/evaluation substrate is separately proven useful;
10. exact-head Python 3.12/3.13 CI before canonical roadmap closure.

## Explicit v1 exclusions

Not implemented or authorized:

- production model self-training;
- live online gradient updates;
- automatic LoRA/checkpoint loading;
- automatic model-profile/routing replacement;
- arbitrary training shell/process execution;
- arbitrary external dataset ingestion;
- internet model/dataset download;
- secret/private-key/token inclusion in datasets;
- training on protected raw project state by default;
- trainer-defined acceptance criteria;
- training-loss-only promotion;
- automatic Phase-26 promotion;
- production Task verification/completion;
- provenance signing;
- merge/release authority.

## Initial exit condition

Phase 29 v1 is complete when one immutable repository head proves that Origin Forge can construct and persist bounded exact verified-trajectory research data, deterministically create leakage-safe frozen dataset splits, freeze independent experiment/evaluation requirements, and retain candidate training results only as non-production research evidence without adding a path for models or trainers to rewrite active weights, routing, production truth, or release state.
