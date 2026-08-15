# Changelog

All notable release-level changes to Origin Forge are summarized here. Detailed architecture and per-phase evidence remain in `docs/` and the canonical roadmap.

## [Unreleased]

## [0.5.0] — 2026-08-16

### Added

- governed production planning, capability routing, WorkOrders, dispatch binding, Task activation, dispatch claims, execution ownership, and single-shot production invocation from Phases 31–37;
- Manager dispatch/preparation admission, one-shot global advancement, explicit preparation recovery, recovery integration, and the fixed six-step bounded Manager driver from Phases 38–43;
- explicit local `origin-forge manager status` and `origin-forge manager advance` operator commands from Phase 44 without a fourth daemon/service entrypoint or recurring queue-drain authority;
- durable governed code-only Goal bootstrap from Phase 45, including exact Goal-revision authority, restart-safe checkpoints, Planner no-replay/recovery semantics, audited materialization, and PREPPOL publication;
- explicit local `origin-forge goal bootstrap status|start|recover GOAL-ID` operator control from Phase 46, preserving separate fresh-start/recovery authorization and stopping at READY before Manager invocation;
- governed deterministic simulation production dispatch from Phase 47 through the existing preparation/claim/execution/Manager path, with zero-model execution dependencies, at-most-once simulation invocation after durable STARTED ownership, independent Phase-25 evidence revalidation, no direct simulation mutation command, and no Task terminalization authority from simulation findings;
- v0.5 release-readiness planning, candidate acceptance traceability, release-readiness ledger, and frozen candidate operator snapshot over the accepted Phase-47 mainline.

### Changed

- the v0.5 release candidate transitions package version from `0.2.0.dev0` to `0.5.0` after accepted R1 readiness while the immutable v0.1.0 tag remains historical release evidence;
- living current-main operator guidance is separated from the historical v0.1.0 operator surface;
- README/release traceability is synchronized through Phase 47 and the R2 candidate freezes `0.5.0` without changing package scripts or runtime authority.

### Release proof

- final candidate head `818de3348834709b58d8117d45539e1a80be1298` passed normal run `31914257104` / #1362 on Python 3.12 and Python 3.13;
- that exact candidate was SHA-guarded merged as release commit `8ac46ee5f14654187469e79b021dbbd83992270b`;
- annotated tag `v0.5.0` is tag object `b45c1ef4cbb5b219d165331dff96ffcfa10cf609` and dereferences to that exact release commit;
- the tag is annotated but unsigned; no claim of cryptographic Git-tag signature is made.

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
