# Changelog

All notable release-level changes to Origin Forge are summarized here. Detailed architecture and per-phase evidence remain in `docs/` and the canonical roadmap.

## [Unreleased]

### Added

- governed production planning, capability routing, WorkOrders, dispatch binding, Task activation, dispatch claims, execution ownership, and single-shot production invocation from Phases 31–37;
- Manager dispatch/preparation admission, one-shot global advancement, explicit preparation recovery, recovery integration, and the fixed six-step bounded Manager driver from Phases 38–43;
- explicit local `origin-forge manager status` and `origin-forge manager advance` operator commands from Phase 44 without a fourth daemon/service entrypoint or recurring queue-drain authority.

### Changed

- current post-v0.1 development now uses package version `0.2.0.dev0` so mutable `main` no longer presents the same package identity as the immutable v0.1.0 tag;
- living current-main operator guidance is separated from the historical v0.1.0 operator surface.

## [0.1.0] — 2026-08-11

### Release boundary

Origin Forge v0.1.0 is the first useful local production-infrastructure release. It is built around durable verified state, replaceable models, deterministic verification, explicit capability boundaries, and causal/provenance evidence rather than long-lived conversation state.

### Included

- durable Goal / Flow / Task / Run / Verification control plane;
- bounded local model worker and deterministic patch proposal/application/audit flow;
- isolated Git workspaces and governed sandbox verification;
- bounded retry/resume/escalation orchestration;
- deterministic source context and governed Skills;
- structural code intelligence plus Project Intelligence / Design Bible state;
- cryptographic provenance and cross-media fingerprint evidence;
- governed 2D, 3D, image/vision, audio, runtime-observation, playtesting, and simulation layers;
- Dream/memory consolidation and governed improvement/research substrates;
- read-only local production cockpit over runtime state, causal history, Project Intelligence, model/resource configuration, provenance, and Dream/memory state;
- installed `origin-forge` control-plane, `origin-forge-attempt` single bounded coding-attempt, and `origin-forge-cockpit` read-only inspection entrypoints;
- Apache License 2.0 distribution license.

### Deliberately excluded

- automatic merge or release authority;
- a new release-only unbounded retry command;
- unrestricted shell/filesystem/process/model execution;
- UI-driven production mutation;
- implicit Artifact adoption or signing;
- automatic Dream promotion;
- remote/multi-user cockpit hosting;
- arbitrary Artifact-byte/media preview serving;
- production checkpoint/model activation or live self-training.

### Release proof

Phase 30 and release-readiness packaging passed exact-head Python 3.12/3.13 matrices before their SHA-guarded merges. Final candidate head `98eeab1b5519c5018d003300126f2da247d3f911` then passed normal run `31478577762` on Python 3.12 and Python 3.13, was SHA-guarded squash-merged as `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`, and annotated tag `v0.1.0` points to that exact reviewed/tested release commit.
