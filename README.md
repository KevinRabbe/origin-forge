# Origin Forge

Origin Forge is a local autonomous production infrastructure for turning human intent into verified, versioned software and game assets using replaceable AI models and deterministic tools.

The project is intentionally broader than a coding agent. Its long-term goal is to coordinate code, 2D art, 3D assets, image generation, audio, testing, simulation, provenance, and project knowledge behind one durable production harness.

## Core idea

```text
Human intent
    ↓
Goals + constraints
    ↓
Durable production state
    ↓
Manager
    ↓
Fresh bounded Executor
    ↓
Tools + Skills + Models
    ↓
Independent Auditor
    ↓
Verified state
    ↓
Versioned product
```

## Architectural laws

1. **Models are replaceable.** Project truth must never depend on one model or provider.
2. **Infrastructure owns state.** Goals, tasks, decisions, artifacts, permissions, provenance, and verification are deterministic system state.
3. **Verified state beats conversation history.** Raw reasoning is disposable; verified facts and outcomes persist.
4. **Models propose; tools verify.** Compiler, tests, runtime evidence, and structured project state outrank model claims.
5. **Every meaningful change is reversible.** Autonomous work happens in isolated workspaces/worktrees before merge.
6. **Use deterministic software whenever possible.** AI handles ambiguity and judgment; conventional tools handle deterministic operations.
7. **Context is a scarce resource.** Load only task-relevant state, skills, schemas, and source context.
8. **Long-running autonomy is a state-management problem.** Use Manager → Executor → Auditor → Verified State, not one endless chat session.
9. **Authority is explicit.** Agents receive capabilities, not unrestricted machine access.
10. **Identity is permanent.** Company/product provenance is independent of whichever model created an artifact.

## Current status

Origin Forge is in **Phase 6 — Snapshot-First Bounded Orchestration**.

Phase 1 established the durable control plane and causal lineage. Phase 2 connected a replaceable local coding model through read-only context and structured patch proposals. Phase 3 added isolated Git worktree application plus independent deterministic content audit. Phase 4 separated `AUDITED` from `VERIFIED` and defined a backend-neutral sandbox contract. Phase 5 implemented the first real sandbox backend using Podman. Phase 6 now connects those components into a single bounded coding attempt.

The Phase-6 Manager creates the isolated Git Workspace **before** the model sees repository content. Context, SHA-256 proposal preconditions, deterministic application, audit, and sandbox verification therefore all operate on one Git snapshot rather than the user's potentially dirty live checkout.

A successful attempt still does **not** merge anything. The verified change remains isolated. There is no arbitrary shell surface, no automatic retry loop, no automatic context discovery, and no model-controlled merge authority.

## Documentation

- [Architecture](docs/architecture.md)
- [Phase 0 Implementation Specification](docs/phase-0-spec.md)
- [Phase 1 Runtime Notes](docs/phase-1-notes.md)
- [Phase 2 Worker Notes](docs/phase-2-notes.md)
- [Phase 3 Isolation Notes](docs/phase-3-notes.md)
- [Phase 4 Sandbox Notes](docs/phase-4-notes.md)
- [Phase 5 Podman Sandbox Notes](docs/phase-5-notes.md)
- [Phase 6 Bounded Orchestration Notes](docs/phase-6-notes.md)
- [Core Model](docs/core-model.md)
- [Principles](docs/principles.md)
- [Security and Authority](docs/security.md)
- [Roadmap](docs/roadmap.md)
- [Research Influences](docs/research-influences.md)

## Initial technology direction

The implementation currently uses or targets:

- Python for the harness
- SQLite for durable state
- Git for versioning and isolated work
- llama.cpp-compatible local inference
- Podman as the first real sandbox backend for executing AI-modified code
- replaceable sandbox backends behind a common verification contract
- snapshot-first bounded orchestration for the first complete coding attempt
- ripgrep + Tree-sitter + LSP for code intelligence
- Pixelorama for 2D production
- Blockbench for 3D production
- rFXGen + FFmpeg for audio tooling
- replaceable local adapters for image, vision, music, and speech models

These are implementation choices, not permanent architectural dependencies.

## Development rule

A new feature should only remain in Origin Forge if it measurably improves at least one of:

- capability
- reliability
- efficiency
- observability
- control
- safety

Complexity by itself is not progress.

## License

Not selected yet. The repository may remain personal infrastructure, become open source, or later support a commercial product. Licensing will be chosen deliberately before any public release that requires it.
