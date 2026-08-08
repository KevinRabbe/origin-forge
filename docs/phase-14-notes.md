# Phase 14 — Resource-Aware Model Scheduler

Status: **completion candidate; final exact-head CI required before merge**

Phase 14 gives Origin Forge an explicit hardware-admission boundary for local models and future GPU-heavy deterministic tools. It does not make hardware allocation part of durable project truth.

## Core rule

```text
Durable Goal / Flow / Task / Run policy
              ↓
explicit model selection policy
              ↓
process-local resource admission
              ↓
CPU / RAM / VRAM lease
              ↓
trusted runtime load
              ↓
perform bounded work
              ↓
runtime unload
              ↓
release lease
```

Project state survives process restart. Hardware leases do not.

A process crash must never leave a durable record claiming that VRAM or RAM is still reserved. The restarted Manager reconstructs Task/Run state and makes a new resource-admission decision.

## Resource arbiter

`ResourceScheduler` owns one process-local capacity snapshot:

- CPU slots
- RAM MiB
- zero or more GPUs
- per-GPU total VRAM
- per-GPU reserved VRAM headroom
- per-GPU compute slots
- maximum active lease count

A request may reserve CPU, RAM, GPU resources, or a combination.

Admission is atomic. If any requested dimension is unavailable, no partial CPU/RAM/GPU reservation remains.

## Static impossibility vs dynamic contention

Origin Forge distinguishes two cases.

**Static impossible request**

The request cannot ever fit configured machine capacity, for example 18 GiB usable VRAM requested from a GPU with 14 GiB usable VRAM. This is an invalid request/profile for that configured machine.

**Dynamic contention**

The request could fit configured capacity, but another process-local lease currently occupies required capacity. This is temporary unavailability.

The resource arbiter does not wait or retry internally. It returns immediately. Durable Manager policy decides whether the surrounding Task should wait, retry later, choose an explicitly permitted alternative, or become blocked.

This avoids turning hardware contention into another hidden autonomous loop.

## GPU rules

VRAM headroom is subtracted from allocatable capacity before any lease decision.

A GPU lease may also consume one or more compute slots. This allows Origin Forge to model cases where two light workloads can coexist while heavy inference/image generation should serialize.

An `exclusive` request requires the GPU to be completely unused and blocks all other GPU leases until release.

When no device is pinned, multi-GPU placement uses deterministic best-fit ordering:

1. least VRAM remaining after allocation
2. least compute-slot capacity remaining after allocation
3. stable device ID tie-break

This preserves larger/more-free devices for workloads that genuinely need them and keeps repeated decisions reconstructable from the same capacity/usage state.

## Model profiles are inventory, not routing policy

`ModelProfileRegistry` contains governed model resource profiles.

A profile declares:

- stable profile ID
- semantic role
- runtime model ID
- optional model hash
- trusted runtime adapter ID
- CPU/RAM/GPU footprint

Current semantic roles are:

```text
coder_fast
coder_strong
vision
image_generator
audio_generator
speech
```

The registry does **not** choose a model.

Governed `profile_id` and `runtime_id` values use strict portable identifiers. Runtime model IDs may retain provider-style identifiers such as `Qwen/Qwen3-Coder-30B-A3B`.

## Explicit fallback policy

`ModelSelectionPolicy` owns one ordered allowed chain:

```text
primary profile
→ explicit fallback 1
→ explicit fallback 2
```

Only those profile IDs may be considered.

A registry containing another smaller model does not grant permission to use it.

Therefore:

> requesting `coder_strong` never silently becomes another installed model merely because the primary profile is busy or too large.

Fallback occurs only when the policy explicitly lists the alternative and every listed profile has the same semantic role.

Static hardware mismatch or temporary contention may advance through this explicit chain. Unknown profiles, role mismatches, malformed ownership, or malformed policy fail before allocation.

## Load / use / unload contract

Runtime-specific model startup stays outside the generic scheduler.

`ManagedModelLoader` provides the trusted loading boundary while `ModelRuntimeRegistry` maps governed runtime IDs to already-registered runtime loaders.

`ModelScheduler.use()` guarantees:

1. resource lease exists before model load
2. work executes while the lease remains active
3. unload runs before lease release
4. load failure releases the lease
5. unload failure remains visible when work otherwise succeeded
6. cleanup failure does not hide an earlier task failure

`ModelRuntimeRegistry` tracks active instance ownership only in memory and rejects unknown runtimes or unowned/reused active instances.

The separation is intentional:

```text
model inventory
      ≠
selection policy
      ≠
resource admission
      ≠
runtime implementation
```

This contract can support llama.cpp, image pipelines, vision runtimes, audio/music models, TTS, and future adapters without embedding runtime-specific startup logic into the scheduler.

## Existing ModelAdapter integration

`ScheduledModelAdapter` bridges the scheduler into the existing bounded Executor.

The Worker still sees a normal `ModelAdapter` and remains unaware of GPU/resource details.

For each model request:

```text
Run ID
  ↓
explicit ModelSelectionPolicy
  ↓
ModelScheduler lease
  ↓
trusted runtime loader
  ↓
loaded ModelAdapter identity check
  ↓
Run schedule evidence
  ↓
generate(request)
  ↓
unload + release
```

The loaded adapter must expose exactly the model ID declared by the selected profile. A runtime cannot claim it loaded one governed profile while silently serving another model.

## Run-level evidence

Model/resource selection is recorded as supplementary RUN verification evidence.

Evidence records:

- requested profile
- selected profile
- semantic role
- model ID / hash
- runtime ID
- attempted explicit profile chain
- whether fallback occurred
- resource lease ID
- assigned GPU ID
- exclusive flag

Metrics record:

- CPU slots
- RAM MiB
- VRAM MiB
- GPU compute slots

This evidence is provenance/observability only. It does not become a Task-success oracle.

## Read-only admission and model inspection

Phase 14 provides non-mutating inspection APIs:

- `inspect_resource_request`
- `inspect_model_profile`
- `inspect_model_registry`
- `inspect_model_policy`

They distinguish static incompatibility from current process-local contention and predict the same deterministic GPU/model selection rules used by real admission.

Inspection never creates a lease and never loads a model.

This lets operator surfaces answer questions such as:

- can this profile ever fit configured hardware?
- is it available in the current scheduler state?
- which GPU would best-fit select?
- if the primary cannot run, which explicitly authorized fallback would be selected?

## Config v5

Phase 14 extends the merged Phase-11 config-v4 schema to config v5.

Configs v1–v4 remain readable. For those versions, resource-aware model scheduling is represented as disabled.

The default v5 config is also safe-disabled:

```toml
[resources]
enabled = false
gpus = []

[models]
profiles = []
policies = []
```

Only config v5 may activate resource/model scheduling.

An enabled `[resources]` section can declare:

- CPU slots
- RAM MiB
- maximum active leases
- bounded GPU descriptors
- per-GPU total VRAM
- reserved VRAM headroom
- compute slots

`[models]` contains bounded profile and policy arrays. Profiles declare resource requests and governed identity. Policies declare primary and explicitly allowed fallback IDs.

The parser:

- has hard counts and numeric limits
- rejects unknown fields
- rejects duplicate GPU/profile/policy identities
- validates policy references
- rejects cross-role policy chains
- preserves explicit statically-too-large primary profiles so an authorized fallback may still be described
- rejects hidden capacity/profile/policy data while scheduling is disabled

Merely parsing config never downloads, probes, starts, or loads a model.

`create_model_scheduling()` constructs only process-local scheduler/registry bookkeeping. It does not perform model I/O.

## Read-only operator status

Phase 14 adds one operator command:

```text
python -m origin_forge.model_resource_cli status
```

It reports:

- config version
- whether resource/model scheduling is enabled
- configured CPU/RAM capacity
- configured GPU capacity/headroom/compute slots
- process-local scheduler usage
- configured model profile compatibility
- explicit policy chains
- which policy profile would currently be selected

The command constructs a fresh empty process-local scheduler from protected config and performs inspection only.

It is **not** a physical system monitor. It does not discover VRAM used by unrelated host processes and does not claim that configured capacity equals instantaneous hardware telemetry.

The CLI exposes no commands or flags for:

- model loading/startup
- downloads
- arbitrary model paths
- runtime argv
- container images
- resource lease mutation
- policy mutation

## Recovery semantics

The durable control plane remains authoritative after a restart.

Examples:

- an interrupted Executor Run may be recovered using existing Run/Task recovery semantics
- a model resource lease from the crashed process is considered gone
- no VRAM lease is replayed from SQLite
- a future fresh/resumed action performs a new capacity decision

This is intentional. Hardware occupancy is instantaneous process/machine state, not durable product truth.

## Integration history

Phase 14 was initially implemented while Phase 11 was still awaiting its current-main revalidation.

Before final config integration:

1. the missing Phase-13 `tool_search.py` packaging defect was repaired and merged
2. Phase 11 passed a fresh Python 3.12 + 3.13 matrix and merged with config v4
3. the 21 reviewed Phase-14 scheduler files were replayed byte-for-byte onto the resulting mainline
4. config v5 and the read-only operator CLI were added on that clean base

An earlier Phase-14 inspection test also revealed a fixture mistake: a scenario intended to model VRAM-only contention used a one-compute-slot GPU, so the busy lease exhausted both VRAM availability and compute capacity. The fixture was corrected to two compute slots; scheduler behavior itself was unchanged.

## Verification coverage

Phase-14 regression coverage includes:

- capacity/request validation
- static impossible requests
- dynamic contention
- VRAM headroom
- compute-slot limits
- exclusive GPU behavior
- explicit device pinning
- unknown pinned-device normalization
- deterministic best-fit placement
- atomic mixed CPU/RAM/GPU admission
- hard active-lease count
- context-manager cleanup
- concurrent no-overcommit acquisition
- read-only resource inspection
- deterministic model registry
- governed model/runtime identity rules
- explicit static fallback
- explicit contention fallback
- no implicit downgrade
- role/profile/owner fail-closed behavior
- runtime registry ownership
- load/use/unload ordering
- load/unload failure cleanup
- original exception preservation
- loaded model identity enforcement
- Run-level model/resource schedule evidence
- unchanged Worker integration
- bounded standalone resource/model parsing
- direct config-object invariant revalidation
- config-v5 integration with v1–v4 compatibility
- config-v5 coexistence with the Phase-11 LSP registry
- read-only operator CLI surface and structured status output

The final merge gate is the complete Python 3.12 + 3.13 GitHub Actions matrix on the exact final PR head.

## Deferred

Phase 14 does not introduce:

- automatic model downloads
- arbitrary runtime process commands
- registry-driven implicit fallback
- unbounded internal scheduling queues
- resource retry loops hidden from Manager policy
- model-driven resource-policy modification
- physical GPU telemetry from unrelated processes
- durable stale hardware leases
- new Task-success authority
- merge authority

Later phases may add measured model routing and richer hardware telemetry, but those decisions remain governed by explicit profiles, benchmark evidence, and durable Manager policy.
