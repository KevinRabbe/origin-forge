# Phase 14 — Resource-Aware Model Scheduler

Status: **implementation in progress; Phase-11 config dependency must land before protected configuration is added**

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
load selected model
              ↓
perform bounded work
              ↓
unload model
              ↓
release lease
```

Project state survives process restart. Hardware leases do not.

A process crash must never leave a durable record claiming that VRAM or RAM is still reserved. The restarted Manager reconstructs the Task/Run state and makes a new resource-admission decision.

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

Origin Forge distinguishes two cases:

**Static impossible request**

The request cannot ever fit the configured machine capacity, for example 18 GiB usable VRAM requested from a GPU with 14 GiB usable VRAM. This is an invalid request/profile for that machine.

**Dynamic contention**

The request could fit the machine, but another lease currently occupies required capacity. This is temporary unavailability.

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
- model ID
- optional model hash
- runtime adapter ID
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

> requesting `coder_strong` never silently becomes a weaker model merely because the stronger profile is busy or too large.

Fallback occurs only when the caller explicitly listed the alternative and every listed profile has the same semantic role.

Static hardware mismatch or temporary contention may advance through this explicit chain. Unknown profiles, role mismatches, malformed ownership, or malformed policy fail before allocation.

## Load / use / unload contract

Runtime-specific model startup stays outside the generic scheduler.

`ManagedModelLoader` provides:

```text
load(profile, lease) -> instance
unload(instance)
```

`ModelScheduler.use()` guarantees:

1. resource lease exists before `load`
2. work executes while the lease remains active
3. `unload` runs before lease release
4. load failure releases the lease
5. unload failure remains visible when work otherwise succeeded
6. cleanup failure does not hide an earlier task failure

This contract can support llama.cpp, image pipelines, vision runtimes, audio/music models, TTS, and future adapters without embedding their startup logic into the scheduler.

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
ManagedModelLoader
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

This evidence is provenance/observability only. It does not become a Task success oracle.

## Recovery semantics

The durable control plane remains authoritative after a restart.

Examples:

- an interrupted Executor Run may be recovered using existing Run/Task recovery semantics
- a model resource lease from the crashed process is considered gone
- no VRAM lease is replayed from SQLite
- a future fresh/resumed action performs a new capacity decision

This is intentional. Hardware occupancy is instantaneous machine state, not durable product truth.

## Phase-11 configuration dependency

Current `main` contains Phase 12 and Phase 13, while Phase-11 code intelligence/config-v4 is being revalidated for integration.

Phase 14 will not create a competing project-config schema on the pre-Phase-11 v3 base.

After Phase 11 lands, Phase 14 should extend config v4 to a new backward-compatible schema containing protected resource/model inventory and selection policy. Config v1–v4 must remain readable.

No config file should automatically download or start a model merely because a profile exists.

## Verification coverage

Current Phase-14 regression coverage includes:

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
- deterministic model registry
- explicit static fallback
- explicit contention fallback
- no implicit downgrade
- role/profile/owner fail-closed behavior
- load/use/unload ordering
- load/unload failure cleanup
- original exception preservation
- loaded model identity enforcement
- Run-level model/resource schedule evidence

## Deferred

Phase 14 does not introduce:

- automatic model downloads
- arbitrary runtime process commands
- registry-driven implicit fallback
- unbounded internal scheduling queues
- resource retry loops hidden from Manager policy
- model-driven resource-policy modification
- durable stale hardware leases
- new Task-success authority
- merge authority

Later phases may add benchmark-informed model routing and resource telemetry, but those decisions remain governed by explicit profiles, measured behavior, and durable Manager policy.
