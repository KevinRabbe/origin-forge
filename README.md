# Origin Forge

Origin Forge is local production infrastructure for turning human intent into verified, versioned software and game assets using replaceable AI models, deterministic tools, durable state, and explicit authority boundaries.

The system is broader than a coding agent. It coordinates code, 2D/3D media, image and vision workflows, audio, runtime observation, playtesting, simulation, provenance, project knowledge, governed improvement research, and a local production cockpit behind one durable harness.

## Core idea

```text
Human intent
    ↓
Goal / Flow / Task
    ↓
Durable production state
    ↓
Bounded context + governed Skills
    ↓
Fresh Executor
    ↓
Patch / media / evidence proposal
    ↓
Independent deterministic verification
    ↓
Verified durable state + provenance
    ↓
Human review / eventual merge
```

## Architectural laws

1. **Models are replaceable.** Project truth must not depend on one model or provider.
2. **Infrastructure owns state.** Goals, Tasks, Decisions, Artifacts, permissions, provenance, and verification are deterministic system state.
3. **Verified state beats conversation history.** Raw reasoning is disposable; verified facts and outcomes persist.
4. **Models propose; independent tools verify.** Tests, compilers, validators, runtime evidence, and structured state outrank model claims.
5. **Meaningful changes are reversible.** Autonomous work happens in isolated workspaces/worktrees before adoption or merge.
6. **Deterministic software is preferred whenever possible.** AI handles ambiguity and judgment; conventional tools handle deterministic operations.
7. **Context is a scarce resource.** Load only task-relevant state, Skills, schemas, and source context.
8. **Long-running autonomy is state management.** Use Manager → Executor → Auditor → Verified State, not one endless chat session.
9. **Authority is explicit.** Components receive capabilities, not unrestricted machine access.
10. **Identity is permanent.** Product provenance is independent of whichever model created an Artifact.

## Current status

Origin Forge **v0.1.0 was released on 2026-08-11**. Its immutable annotated tag points to release commit `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`, after exact-head Python 3.12/3.13 CI on the final release candidate.

Origin Forge **v0.5.0 was released on 2026-08-16**. Its immutable annotated tag `v0.5.0` points to release commit `8ac46ee5f14654187469e79b021dbbd83992270b`. Phases 0–47 are included in that release; Phases 31–47 remain absent from the historical v0.1.0 payload.

The canonical **v0.5 — Integrated Development Infrastructure** milestone is released. Final candidate head `818de3348834709b58d8117d45539e1a80be1298` passed normal run `31914257104` / #1362 on Python 3.12 and 3.13, was SHA-guarded merged as `8ac46ee5f14654187469e79b021dbbd83992270b`, and annotated tag object `b45c1ef4cbb5b219d165331dff96ffcfa10cf609` dereferences to that exact commit.

### What exists now on current main

- durable SQLite Goal / Flow / Task / Run / Verification state;
- isolated Git workspaces and deterministic patch application/audit;
- governed sandbox verification and bounded retry orchestration;
- deterministic source context, governed Skills, structural/LSP code intelligence, progressive tool discovery, and Project Intelligence / Design Bible state;
- governed local model/resource scheduling;
- cryptographic provenance plus cross-media fingerprints;
- governed Pixelorama, Blender, image/vision, audio, runtime-observation, playtesting, and simulation evidence layers;
- Dream/memory consolidation, specialist review, Skill/harness workshop experiments, programmatic-context experiments, and training/fine-tuning research substrate;
- a bounded loopback-only read-only production cockpit over runtime, causal history, Project Intelligence, model/resource configuration, provenance, and Dream/memory state;
- governed production planning/routing/WorkOrder/binding/claim/execution authority through Phases 31–37;
- one-shot, recovery-aware, bounded Manager advancement through Phases 38–43;
- explicit local `origin-forge manager status` and `origin-forge manager advance` operator commands from Phase 44;
- durable code-only Goal bootstrap plus explicit `goal bootstrap status|start|recover GOAL-ID` operator control from Phases 45–46;
- governed deterministic simulation production dispatch through the existing Manager path from Phase 47, with no direct simulation mutation command and no automatic Task terminalization from simulation findings.

The system still deliberately excludes automatic merge/release authority, unrestricted shell/filesystem/model execution, UI-driven production mutation, implicit Artifact adoption/signing, background Manager/Goal-bootstrap queue draining, model self-verification, and automatic replay of uncertain started execution.

## Quick start

Requires Python 3.12+.

```bash
python -m pip install -e .
origin-forge init --name my-project
origin-forge status
```

Initialization is the explicit project-state creation boundary. Packaged attempt/cockpit/Manager/Goal-bootstrap inspection and advancement commands do not silently initialize a missing project.

The main CLI exposes the durable control-plane and governed worker/sandbox operations:

```bash
origin-forge --help
origin-forge goal --help
origin-forge task --help
origin-forge run --help
origin-forge verify --help
origin-forge sandbox --help
```

Current post-v0.1 main also exposes explicit bounded Manager and Goal-bootstrap surfaces:

```bash
origin-forge manager status
origin-forge manager advance
origin-forge goal bootstrap status  GOAL-...
origin-forge goal bootstrap start   GOAL-...
origin-forge goal bootstrap recover GOAL-...
```

`manager status` is a non-creating projection. `manager advance` invokes the fixed bounded Manager driver once; it does not repeat until idle or drain the queue. Goal-bootstrap `start` and `recover` are separate one-shot authorizations; READY stops before Manager invocation, and uncertain Planner work is not automatically replayed.

The first complete coding path is exposed as **one bounded attempt**, not an unbounded autonomous retry loop:

```bash
origin-forge-attempt TASK-... --auto-context
```

or with explicit snapshot-local context:

```bash
origin-forge-attempt TASK-... \
  --file src/example.py \
  --file tests/test_example.py
```

The command uses the existing snapshot-first orchestrator: isolated Workspace → model proposal → deterministic apply → independent audit → governed sandbox verification. It does not merge, push, release, recursively retry itself, or create missing Origin Forge project state.

The installed read-only cockpit entrypoint is:

```bash
origin-forge-cockpit snapshot
origin-forge-cockpit serve --port 8765
```

The cockpit binds only to `127.0.0.1`, exposes fixed GET routes, and does not create/migrate runtime state, load models, execute tools, mutate Tasks, adopt/sign Artifacts, promote Dream memory, merge, or release.

`origin-forge status` remains an authoritative control-plane status path using the normal runtime/store lifecycle. Use `origin-forge-cockpit snapshot` when the requirement is specifically bounded non-creating inspection.

See the [current operator guide](docs/operator-guide.md) for the current-main command boundary and end-to-end local workflow. The [v0.5 candidate operator guide](docs/v0.5-operator-guide.md) freezes the Phase-47 operator surface for release-readiness review. The [v0.1 operator guide](docs/v0.1-operator-guide.md) documents the immutable released v0.1.0 surface and intentionally excludes later Manager/Goal-bootstrap/simulation production commands.

## Release and development identity

The historical v0.1.0 release proof is complete: final candidate head `98eeab1b5519c5018d003300126f2da247d3f911` passed run `31478577762` on Python 3.12 and 3.13, was SHA-guarded squash-merged as `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`, and annotated tag `v0.1.0` points to that exact commit.

R1 retained `0.2.0.dev0` while the v0.5 acceptance/readiness/operator boundary was audited. R2 transitioned package identity to `0.5.0` without changing the three installed commands or runtime authority. The immutable annotated `v0.5.0` tag now records the tested/reviewed release commit; later post-release documentation does not move that tag.

See the [v0.5 readiness plan](docs/v0.5-release-readiness-plan.md), [v0.5 release-readiness ledger](docs/v0.5-release-readiness.md), [v0.5 acceptance matrix](docs/v0.5-acceptance-matrix.md), [v0.5 candidate operator guide](docs/v0.5-operator-guide.md), historical [v0.1 release-readiness record](docs/v0.1-release-readiness.md), [v0.1 acceptance matrix](docs/v0.1-acceptance-matrix.md), and [changelog](CHANGELOG.md).

## Documentation

Start with:

- [Architecture](docs/architecture.md)
- [Core Model](docs/core-model.md)
- [Principles](docs/principles.md)
- [Security and Authority](docs/security.md)
- [Roadmap](docs/roadmap.md)
- [Current Operator Guide](docs/operator-guide.md)
- [v0.5 Release Readiness Plan](docs/v0.5-release-readiness-plan.md)
- [v0.5 Release Readiness](docs/v0.5-release-readiness.md)
- [v0.5 Acceptance Matrix](docs/v0.5-acceptance-matrix.md)
- [v0.5 Candidate Operator Guide](docs/v0.5-operator-guide.md)
- [v0.1 Operator Guide](docs/v0.1-operator-guide.md)
- [v0.1 Release Readiness](docs/v0.1-release-readiness.md)
- [v0.1 Acceptance Matrix](docs/v0.1-acceptance-matrix.md)
- [Changelog](CHANGELOG.md)
- [Research Influences](docs/research-influences.md)

The repository also contains per-phase implementation contracts and evidence notes under `docs/`.

## Technology direction

The implementation uses or targets:

- Python for the harness;
- SQLite for durable state;
- Git for versioning and isolated work;
- llama.cpp-compatible local inference;
- Podman as the first sandbox backend;
- Tree-sitter/LSP for structural code intelligence;
- Pixelorama for bounded 2D editor integration;
- Blender behind the editor-independent 3D contract;
- FFmpeg and Piper for governed audio processing/TTS;
- replaceable local adapters for image, vision, audio, and model workloads.

These are implementation choices, not permanent architectural dependencies.

## Development rule

A feature should remain in Origin Forge only if it measurably improves at least one of:

- capability;
- reliability;
- efficiency;
- observability;
- control;
- safety.

Complexity by itself is not progress.

## License

Origin Forge is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
