# Phase 23 — Runtime Observation

Status: **IN PROGRESS — governed v1 substrate and roadmap synchronized; final exact-head closure pending**

Phase 23 adds runtime evidence without creating a second path for production truth. Launches, logs, captures, crashes, timings, memory observations, and visual comparisons are evidence about an application run. They do not verify or complete the production Task by themselves.

## Core rule

```text
application runtime
        ↓
bounded observer
        ↓
exact logs + captures + exit/performance evidence
        ↓
independent Origin Forge revalidation
        ↓
durable evidence

runtime evidence != Task success authority
```

## Governed v1 surface

The repository now provides:

- infrastructure-owned `OBS-*` observation IDs and `OBSWS-*` workspaces;
- immutable content-addressed observation requests/results;
- exact backend, target version and executable SHA-256 binding;
- bounded log and timeout budgets;
- explicit `EXITED`, `FAILED`, `SIGNALED`, and `TIMEOUT` runtime outcomes;
- no-shell local launch through an adapter-owned executable and fixed argv;
- no caller-controlled environment variables or follow-up commands;
- bounded concurrent stdout/stderr draining with active termination on overflow;
- POSIX process-group cleanup, including descendants that survive direct-child exit;
- wall-clock duration and best-effort Linux `/proc` direct-process peak-RSS observations;
- cooperative exact-path screenshot capture as standard RGB/RGBA PNG;
- logically timed `VIDEO_FRAME` PNG sequences as the canonical v1 video evidence surface;
- exact capture-set enforcement on normal exit, with declared partial capture evidence allowed after crash/signal/timeout;
- explicit durable `missing_capture_ids` for abnormal runs that terminate before all requested captures;
- symlink/root containment and undeclared-output rejection for every runtime outcome;
- pre-read PNG size bounds so sparse/oversized captures cannot force an unbounded allocation;
- independent PNG reinspection after the backend returns;
- exact visual-baseline Artifact binding and deterministic pixel/channel regression metrics;
- pre-read size/hash binding for baseline, request, log, and capture evidence at the durable service boundary;
- durable request/result/log/capture Artifacts and Run/Artifact Verifications;
- visual regression `PASS`/`FAIL` evidence that does not change Task state;
- a read-only `runtime_observation_cli` inspection surface;
- explicit evidence fields proving that visual semantics, performance requirements, canonical adoption, and production Task completion remain outside this service.

## Why video is a frame sequence in v1

A codec container is useful transport but poor canonical truth. Different encoder builds and metadata can produce different bytes for the same frames. Phase 23 therefore starts from logically timed, independently validated PNG frames. A later governed FFmpeg derivation can package those frames into a viewable video while the frame sequence remains the deterministic evidence source.

This is intentionally analogous to the Phase-22 audio rule that canonical media structure is independently inspected instead of trusting a tool exit code.

## Cooperative capture boundary

The v1 local process backend does not pretend to be a universal desktop recorder. It injects only infrastructure-owned observation/capture paths:

- `ORIGIN_FORGE_OBSERVATION_ID`
- `ORIGIN_FORGE_REQUEST_HASH`
- `ORIGIN_FORGE_CAPTURE_DIR`
- `ORIGIN_FORGE_CAPTURE_MANIFEST`

A target that supports the governed observation hook may write declared PNGs there. Undeclared files, symlinks, invalid PNGs, oversized PNGs, path escapes, or capture drift fail closed.

On a normal `EXITED` outcome every declared capture is required. On `FAILED`, `SIGNALED`, or `TIMEOUT`, the observer accepts only the declared subset that actually exists so the abnormal runtime outcome is not lost merely because a later scheduled screenshot/frame could not happen. The durable Run verification records the exact missed capture IDs. Undeclared captures remain forbidden in all cases.

**Decision:** cooperative exact-path capture is the accepted Phase-23 v1 capture surface. Platform framebuffer/window capture is a replaceable backend-specific enhancement, not a blocker for the runtime-observation substrate. A future native/window backend must be separately governed and proven rather than hidden behind GUI-coordinate automation.

### Capture timing semantics

`timestamp_ms` is a frozen logical capture offset in the request and capture manifest. The service proves that each returned capture has the exact declared capture ID, kind, path and logical timestamp, but the cooperative v1 backend does **not** independently measure the wall-clock instant at which target code sampled the image.

Therefore Phase 23 v1 proves the ordered/logically timed frame contract and exact returned frame bytes; it does not claim independent framebuffer-time attestation. A future window/framebuffer backend may add infrastructure-measured sampling timestamps as a stronger evidence level without changing the current canonical frame contract.

## Process authority

`LocalProcessRuntimeObserver` is deliberately not a generic model-facing process tool.

The trusted adapter constructor owns:

- executable path;
- exact executable hash;
- backend identity/version;
- target identity/version;
- fixed argv.

The observation request can bind those values but cannot choose an executable, inject shell syntax, add arbitrary argv, supply environment variables, install software, download dependencies, or run a second command.

The v1 local backend requires POSIX process groups. Timeout and log-overflow termination kill the observation group, and cleanup also removes same-group descendants after the direct target exits so an orphan cannot keep capture pipes/files live after observation completion. The backend uses a minimal environment and an isolated observation workspace.

The native target is still a preconfigured trusted application executable rather than a sandboxed untrusted binary. Phase 23 therefore makes no claim that this local backend provides host-filesystem or network isolation. Untrusted application execution requires a separately governed sandbox backend rather than weakening this contract.

## Runtime outcomes

A nonzero exit, signal, or timeout can still produce a **successful observation**. That distinction is required:

```text
observer succeeded + app crashed
!=
observer infrastructure failed
```

The durable Run records `crash_detected`, `timed_out`, exit kind/code, log Artifacts, capture Artifacts, `missing_capture_ids`, duration and direct-process peak RSS. Governance or a later verification policy may decide what those observations mean for a particular production Task.

## Visual regression

A visual baseline is an exact existing Artifact plus frozen:

- PNG content hash;
- normalized RGBA pixel hash;
- dimensions;
- maximum changed pixels;
- maximum per-channel delta;
- maximum total channel delta.

The service re-reads and revalidates the baseline before starting the observation Run. Baseline size is bounded before allocation. After capture it independently decodes both PNGs and calculates deterministic deltas. Dimension drift is a structural error, not silently converted into a similarity score.

A visual-regression verification can be `FAIL` while the observation Run itself is `SUCCEEDED`. This records the regression without granting the observer authority to fail or complete the production Task. If an abnormal runtime exit prevents a baseline-bound capture from occurring, that capture is recorded as missing rather than inventing a visual-regression verdict for bytes that do not exist.

## Durable evidence

The service persists:

- `RUNTIME_OBSERVATION_REQUEST`
- `RUNTIME_OBSERVATION_RESULT`
- `RUNTIME_STDOUT_LOG`
- `RUNTIME_STDERR_LOG`
- `RUNTIME_SCREENSHOT_PNG`
- `RUNTIME_VIDEO_FRAME_PNG`
- `runtime-capture-integrity` Artifact Verifications
- optional `runtime-visual-regression` Artifact Verifications
- one `runtime-observation-structure` Run Verification including abnormal-exit missing capture IDs

All returned workspace/output bytes are re-resolved, size-checked, rehashed and re-inspected after backend execution.

## Read-only operator inspection

```text
python -m origin_forge.runtime_observation_cli status
python -m origin_forge.runtime_observation_cli observation-runs
python -m origin_forge.runtime_observation_cli run-show <RUN-ID>
python -m origin_forge.runtime_observation_cli artifact-show <ART-ID>
```

The CLI exposes durable evidence only. It has no launch, capture, kill, input automation, baseline mutation, adoption, signing, Task mutation, merge, or release command.

## Explicit exclusions in v1

Not implemented or authorized:

- arbitrary shell/process execution;
- caller/model-selected executables or environment variables;
- host-filesystem or network sandbox claims for the native local backend;
- OS/window/framebuffer capture as a required canonical backend;
- infrastructure-attested wall-clock capture timestamps for cooperative frames;
- aggregate descendant/process-tree RSS accounting;
- mouse/keyboard/game-controller automation;
- semantic visual grading by a vision model;
- performance-budget pass/fail authority;
- automatic Task verification/completion;
- automatic retry/repair based on a crash;
- automatic asset adoption/signing;
- merge/release authority;
- Phase-24 synthetic playtesting/bot control.

## Phase-23 v1 exit condition

Phase 23 v1 is complete when one immutable repository head proves on the normal supported Python matrix that Origin Forge can:

1. launch one exact adapter-owned executable with fixed argv and no shell/caller environment authority;
2. bound stdout/stderr and terminate the full observation process group on timeout/overflow/cleanup;
3. record normal exit, nonzero failure, signal, or timeout distinctly from observer infrastructure failure;
4. require the exact declared screenshot/logically timed-video-frame PNG set on normal exit, preserve only declared partial captures plus explicit missing IDs on abnormal exit, and independently validate every returned bounded PNG;
5. revalidate exact baseline Artifacts and emit deterministic visual-regression PASS/FAIL evidence only for captures that exist;
6. persist request/result/log/capture lineage plus duration/direct-process peak-RSS evidence;
7. expose that evidence through a read-only operator surface; and
8. prove none of those paths verifies/completes the production Task, adopts assets, signs provenance, merges, or releases.

The regression suite uses real local subprocesses for launch, timeout, log overflow, nonzero exit, signal exit, crash-before-requested-capture, sparse oversized capture, and descendant cleanup, while fake service adapters exercise adversarial workspace/evidence binding and durable missing-capture recording. A separate heavyweight external runtime is not required for the v1 substrate because the governed local process boundary itself executes for real in ordinary CI.

Remaining closure work is one final exact-head Python 3.12/3.13 matrix after this documentation is frozen.

Phase 24 remains separate. Runtime observation collects evidence; automated playtesting decides and performs synthetic player actions.
