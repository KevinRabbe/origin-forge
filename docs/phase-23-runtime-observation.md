# Phase 23 — Runtime Observation

Status: **IN PROGRESS — first governed observation slice implemented**

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

## First slice

The initial repository slice provides:

- infrastructure-owned `OBS-*` observation IDs and `OBSWS-*` workspaces;
- immutable content-addressed observation requests/results;
- exact backend, target version and executable SHA-256 binding;
- bounded log and timeout budgets;
- explicit `EXITED`, `FAILED`, `SIGNALED`, and `TIMEOUT` runtime outcomes;
- no-shell local launch through an adapter-owned executable and fixed argv;
- no caller-controlled environment variables or follow-up commands;
- bounded concurrent stdout/stderr draining with active termination on overflow;
- wall-clock duration and best-effort Linux `/proc` peak-RSS observations;
- cooperative exact-path screenshot capture as standard RGB/RGBA PNG;
- timed `VIDEO_FRAME` PNG sequences as the canonical v1 video evidence surface;
- exact capture-set enforcement with symlink/root containment rejection;
- independent PNG reinspection after the backend returns;
- exact visual-baseline Artifact binding and deterministic pixel/channel regression metrics;
- durable request/result/log/capture Artifacts and Run/Artifact Verifications;
- visual regression `PASS`/`FAIL` evidence that does not change Task state;
- explicit evidence fields proving that visual semantics, performance requirements, canonical adoption, and production Task completion remain outside this service.

## Why video is a frame sequence in v1

A codec container is useful transport but poor canonical truth. Different encoder builds and metadata can produce different bytes for the same frames. Phase 23 therefore starts from timed, independently validated PNG frames. A later governed FFmpeg derivation can package those frames into a viewable video while the frame sequence remains the deterministic evidence source.

This is intentionally analogous to the Phase-22 audio rule that canonical media structure is independently inspected instead of trusting a tool exit code.

## Cooperative capture boundary

The first local process backend does not pretend to be a universal desktop recorder. It injects only infrastructure-owned observation/capture paths:

- `ORIGIN_FORGE_OBSERVATION_ID`
- `ORIGIN_FORGE_REQUEST_HASH`
- `ORIGIN_FORGE_CAPTURE_DIR`
- `ORIGIN_FORGE_CAPTURE_MANIFEST`

A target that supports the governed observation hook may write the exact declared PNGs there. Undeclared files, missing captures, symlinks, invalid PNGs, or path escapes fail closed.

Platform framebuffer/window capture remains a later backend-specific capability. It must be separately governed and proven rather than hidden behind GUI-coordinate automation.

## Process authority

`LocalProcessRuntimeObserver` is deliberately not a generic model-facing process tool.

The trusted adapter constructor owns:

- executable path;
- exact executable hash;
- backend identity/version;
- target identity/version;
- fixed argv.

The observation request can bind those values but cannot choose an executable, inject shell syntax, add arbitrary argv, supply environment variables, install software, download dependencies, or run a second command.

The v1 local backend requires POSIX process groups so timeout/overflow termination includes descendants started in the same process group. It uses a minimal environment and an isolated observation workspace.

## Runtime outcomes

A nonzero exit, signal, or timeout can still produce a **successful observation**. That distinction is required:

```text
observer succeeded + app crashed
!=
observer infrastructure failed
```

The durable Run records `crash_detected`, `timed_out`, exit kind/code, log Artifacts, capture Artifacts, duration and peak RSS. Governance or a later verification policy may decide what those observations mean for a particular production Task.

## Visual regression

A visual baseline is an exact existing Artifact plus frozen:

- PNG content hash;
- normalized RGBA pixel hash;
- dimensions;
- maximum changed pixels;
- maximum per-channel delta;
- maximum total channel delta.

The service re-reads and revalidates the baseline before starting the observation Run. After capture it independently decodes both PNGs and calculates deterministic deltas. Dimension drift is a structural error, not silently converted into a similarity score.

A visual-regression verification can be `FAIL` while the observation Run itself is `SUCCEEDED`. This records the regression without granting the observer authority to fail or complete the production Task.

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
- one `runtime-observation-structure` Run Verification

All returned workspace/output bytes are re-resolved, rehashed and re-inspected after backend execution.

## Explicit exclusions in this slice

Not implemented or authorized yet:

- arbitrary shell/process execution;
- caller/model-selected executables or environment variables;
- network-policy claims for the native local backend;
- OS/window/framebuffer capture;
- mouse/keyboard/game-controller automation;
- semantic visual grading by a vision model;
- performance-budget pass/fail authority;
- automatic Task verification/completion;
- automatic retry/repair based on a crash;
- automatic asset adoption/signing;
- merge/release authority;
- Phase-24 synthetic playtesting/bot control.

## Next Phase-23 work

Before Phase 23 is called complete, the remaining closure work is:

1. run the full Python 3.12/3.13 repository matrix on the substrate;
2. harden any failures found by that matrix;
3. add a separately governed real capture backend where the environment supports deterministic window/frame capture, or explicitly freeze cooperative capture as the accepted v1 runtime surface;
4. add read-only observation inspection/operator status if it proves necessary for durable use;
5. synchronize the canonical roadmap, including marking merged Phase 20C complete;
6. define and satisfy an exact Phase-23 exit condition on one immutable closure SHA.

Phase 24 remains separate. Runtime observation collects evidence; automated playtesting decides and performs synthetic player actions.