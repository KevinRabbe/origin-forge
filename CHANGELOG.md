# Changelog

All notable release-level changes to Origin Forge are summarized here. Detailed architecture and per-phase evidence remain in `docs/` and the canonical roadmap.

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

Phase 30 and release-readiness packaging both passed exact-head Python 3.12/3.13 matrices before their SHA-guarded merges. The final `0.1.0` version/license candidate must pass its own exact-head Python 3.12/3.13 matrix with clean review/thread state before merge. The `v0.1.0` tag is created only after that merge and must point to the exact reviewed/tested release commit.
