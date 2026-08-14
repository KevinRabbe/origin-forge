# Post-v0.1 Release State Reconciliation

Status: **FROZEN PLANNING CONTRACT**

This is release-maintenance work, not a new numbered architecture phase. It reconciles the immutable `v0.1.0` release with the substantial post-release work now present on `main` without moving historical tags, rewriting tested release identity, or widening production authority.

## Verified historical release facts

The v0.1 release is already complete:

- final release-candidate PR: `#42`;
- final tested candidate head: `98eeab1b5519c5018d003300126f2da247d3f911`;
- final normal matrix: run `31478577762`, Python 3.12 and Python 3.13 both successful on attempt 1;
- SHA-guarded squash merge: `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`;
- annotated tag object: `e6dd319cf6c8ba450fed274c04a95eae63f9811c`;
- tag `v0.1.0` dereferences to release commit `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`;
- release date: 2026-08-11.

The tag is immutable historical release evidence for this maintenance unit. It must not be moved, deleted, recreated, or retargeted.

A GitHub Release object is not required by the accepted v0.1 release contract and is not created retroactively by this reconciliation.

## Current-main facts

Phase-44 closure is merged on `main` as `da0894962dd01ae73ec08c98cf73771397e0f262`.

That mainline is 127 commits ahead of the immutable v0.1.0 release commit and contains the post-release Phase-31 through Phase-44 production-planning, routing, dispatch, recovery, bounded-Manager, and explicit Manager-CLI work.

Current repository metadata still reports package version `0.1.0`, while README/readiness/acceptance text still describes the already-completed v0.1 tag operation as pending. The living `docs/v0.1-operator-guide.md` also contains Phase-44 Manager commands that do not exist in the immutable v0.1.0 release.

Those are release-state/documentation inconsistencies, not reasons to alter the historical release.

## Frozen reconciliation decisions

### 1. Preserve v0.1.0 identity

`v0.1.0` continues to identify exactly `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`.

Release documentation may record the completed final CI/merge/tag evidence, but it may not imply that current post-release main is still the v0.1.0 release payload.

### 2. Move current main to a distinct development version

After this planning contract is accepted, post-release implementation changes package metadata from:

```text
0.1.0
```

to:

```text
0.2.0.dev0
```

This is a development-line identity only. It prevents post-release `main` from presenting the same package version as the immutable v0.1.0 tag. It does not promise a v0.2.0 release, does not create a tag, and does not change the roadmap's v0.5/v1.0 milestone semantics.

The release-packaging regression must be updated to assert the exact development version while preserving package name, Apache-2.0 license, Python floor, build-system floor, and the exact existing three console scripts.

### 3. Separate historical and current operator guidance

`docs/v0.1-operator-guide.md` must describe the actual v0.1.0 operator surface, not post-release Manager commands.

A separate current-development guide, `docs/operator-guide.md`, becomes the living operator document for current `main`. It may include Phase-44 `manager status` / `manager advance` because those commands exist on current main.

README and later Phase-44 documentation references must point to the current guide when discussing current-main Manager operation. The historical v0.1 guide remains linked where the subject is specifically the released v0.1.0 surface.

### 4. Reconcile the release ledger

`docs/v0.1-release-readiness.md` and `docs/v0.1-acceptance-matrix.md` become archival completed-release records:

- status reflects **RELEASED** rather than candidate/pending;
- final candidate run `31478577762` is recorded as Python 3.12/3.13 green;
- PR #42 merge `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d` is recorded as the exact release commit;
- `v0.1.0` is recorded as pointing to that exact merge;
- no checkbox remains falsely pending for already-completed release mechanics.

These documents must not claim that later Phase-31–44 functionality shipped in v0.1.0.

### 5. Reconcile README and changelog

README current status must distinguish:

- **released v0.1.0** at the immutable historical tag; and
- **post-v0.1 development main** containing later phases.

The quick-start/current operator section should reference `docs/operator-guide.md` and include the current Phase-44 Manager commands without attributing them to the old release.

`CHANGELOG.md` gains an `[Unreleased]` section for post-v0.1 development. It should summarize Phase-31–44 at a release level without declaring a future release version or date. The existing `[0.1.0] — 2026-08-11` section remains historical.

### 6. Correct roadmap chronology without rewriting phase evidence

The canonical roadmap must make release chronology explicit:

```text
Phases 0–30
→ v0.1.0 RELEASED 2026-08-11
→ Phases 31–44 post-v0.1 development
→ later milestones
```

Phase implementation text/evidence remains unchanged except where a Phase-44 operator-guide reference must point to the living `docs/operator-guide.md` rather than the historical v0.1 guide.

The roadmap edit must be reviewed as a structural move/relabel, not as deletion of accepted phase history.

## Implementation slices

### R1 — Development identity and operator-guide separation

Allowed changes:

- `pyproject.toml` → exact `0.2.0.dev0` development version;
- `tests/test_release_packaging.py` → exact development-version assertion only, preserving all other packaging invariants;
- create `docs/operator-guide.md` as the current-main living guide including Phase-44 Manager commands;
- restore/reconcile `docs/v0.1-operator-guide.md` to the actual v0.1 surface and completed-release status;
- update README current status/operator links;
- add an `[Unreleased]` changelog section.

No production runtime code changes are allowed in R1.

### R2 — Historical release ledger and roadmap chronology

Allowed changes:

- `docs/v0.1-release-readiness.md`;
- `docs/v0.1-acceptance-matrix.md`;
- `docs/roadmap.md`;
- `docs/phase-44-implementation-closure.md` only if required to correct the living-guide reference;
- `docs/phase-44-governed-manager-operator-invocation.md` only if required to correct the living-guide reference.

R2 records only already-verified history and structural chronology. It adds no runtime/test/package authority.

### R3 — Reconciliation closure

After R1/R2 are merged, create a concise closure record with exact accepted heads/runs/merge commits and run one final exact-head Python 3.12/3.13 matrix over the documentation closure.

## CI and merge discipline

Every implementation slice starts from the independently verified merged mainline of the previous slice.

For each slice:

1. draft PR;
2. exact head pinned before interpreting CI;
3. normal `tests` matrix on Python 3.12 and 3.13 with `ResourceWarning` treated as error;
4. no merge while either interpreter is red or pending;
5. review/comment/diff inspection on the immutable accepted head;
6. SHA-guarded merge only;
7. independently re-read `main` before starting the next slice.

A docs-only planning/closure slice still receives the full matrix because it changes canonical release truth.

## Explicit non-goals

This reconciliation adds no:

- new production phase or runtime behavior;
- Manager repetition, daemon, scheduler, watcher, or background authority;
- Task/PREP/claim/model/resource/action selector;
- new console entrypoint;
- automatic merge/release/tag authority;
- tag movement or replacement;
- retroactive GitHub Release publication;
- Artifact adoption/signing, Project Intelligence mutation, Dream promotion, training, deployment, or remote multi-user authority.

## Exit condition

Reconciliation is complete when:

- `v0.1.0` remains bound to `fbc6764b3b5e71cb5f5a223f09c82189e7326c1d`;
- current main has a distinct `0.2.0.dev0` package identity;
- historical v0.1 and living current operator guides are separate and accurate;
- README/changelog/release ledger distinguish released v0.1 from post-release work;
- roadmap chronology places the historical v0.1 release after Phase 30 and Phases 31–44 after that release;
- all R1/R2/R3 exact heads pass Python 3.12 and 3.13 and are SHA-guarded merged;
- no runtime production authority changed.
