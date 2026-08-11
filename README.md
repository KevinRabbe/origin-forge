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

Origin Forge is at its **v0.1.0 First Useful Release candidate**. Phases 0–30 are merged, including the first bounded local production cockpit from Phase 30, and the release-readiness packaging/entrypoint matrix passed on Python 3.12 and 3.13 before merge.

The final release candidate sets package version `0.1.0` and adopts the Apache License 2.0. The `v0.1.0` tag remains downstream of exact-head Python 3.12/3.13 CI, clean review/thread state, and SHA-guarded merge of the final release candidate.

### What exists now

- durable SQLite Goal / Flow / Task / Run / Verification state;
- isolated Git workspaces and deterministic patch application/audit;
- governed sandbox verification and bounded retry orchestration;
- deterministic source context, governed Skills, structural code intelligence, and Project Intelligence / Design Bible state;
- cryptographic provenance plus cross-media fingerprints;
- governed Pixelorama, Blender, image/vision, audio, runtime-observation, playtesting, and simulation evidence layers;
- Dream/memory consolidation, Skill/harness workshop experiments, programmatic-context experiments, and training/fine-tuning research substrate;
- a bounded loopback-only read-only production cockpit over runtime, causal history, Project Intelligence, model/resource configuration, provenance, and Dream/memory state.

The system still deliberately excludes automatic merge/release authority, unrestricted shell/filesystem/model execution, UI-driven production mutation, implicit Artifact adoption/signing, and model self-verification.

## Quick start

Requires Python 3.12+.

```bash
python -m pip install -e .
origin-forge init --name my-project
origin-forge status
```

Initialization is the explicit project-state creation boundary. Packaged attempt/cockpit commands do not silently initialize a missing project.

The main CLI exposes the durable control-plane and governed worker/sandbox operations:

```bash
origin-forge --help
origin-forge goal --help
origin-forge task --help
origin-forge run --help
origin-forge verify --help
origin-forge sandbox --help
```

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

After Phase-30 state is initialized and quiescent, the installed read-only cockpit entrypoint is:

```bash
origin-forge-cockpit snapshot
origin-forge-cockpit serve --port 8765
```

The cockpit binds only to `127.0.0.1`, exposes fixed GET routes, and does not create/migrate runtime state, load models, execute tools, mutate Tasks, adopt/sign Artifacts, promote Dream memory, merge, or release.

`origin-forge status` remains an authoritative control-plane status path using the normal runtime/store lifecycle. Use `origin-forge-cockpit snapshot` when the requirement is specifically bounded non-creating inspection.

See the [v0.1 operator guide](docs/v0.1-operator-guide.md) for the installed command boundary and end-to-end local workflow.

## v0.1 release gate

The Phase-30 and release-readiness implementation/packaging gates are complete. The final `v0.1.0` release requires:

- exact-head Python 3.12 and Python 3.13 green CI on the final version/license candidate;
- no unresolved review or CI failures on that exact head;
- SHA-guarded merge of the final candidate;
- a `v0.1.0` tag bound to the exact reviewed/tested merge commit.

See the [v0.1 release-readiness contract](docs/v0.1-release-readiness.md), [v0.1 acceptance matrix](docs/v0.1-acceptance-matrix.md), and [changelog](CHANGELOG.md) for the explicit release boundary.

## Documentation

Start with:

- [Architecture](docs/architecture.md)
- [Core Model](docs/core-model.md)
- [Principles](docs/principles.md)
- [Security and Authority](docs/security.md)
- [Roadmap](docs/roadmap.md)
- [Phase 30 — Full Production Interface](docs/phase-30-full-production-interface.md)
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
