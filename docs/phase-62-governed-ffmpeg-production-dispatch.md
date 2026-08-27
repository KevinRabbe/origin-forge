# Phase 62 — Governed FFmpeg Production Dispatch

Phase 62 promotes the existing fixed-argument FFmpeg adapter through the
governed production lifecycle:

`WorkOrder → source/profile resolution → binding → claim → STARTED execution → FFmpeg → Artifact/Verification → output binding → RETURNED`.

FFmpeg WorkOrders require one `audio_source` Artifact and one `audio_profile`.
The source resolver reads the protected WAV bytes and freezes the exact PCM
hash, byte count, frame count, sample rate, and channel count. The profile pins
the FFmpeg backend version and executable hash. The executable path comes only
from the project’s explicit `[tools].ffmpeg` configuration; PATH discovery is
not used.

Execution IDs, workspaces, operation IDs, and output paths are allocated only
after durable `DISPATCH_EXECUTION_STARTED`. The adapter validates the source,
executable, fixed invocation, output budget, and canonical PCM16 WAV result.
The shared audio service publishes request/result/output evidence without
accepting or adopting a Task.

Schema v29 repairs the v25 shared audio binding owner constraint. It copies
existing Piper rows unchanged and permits the reviewed FFmpeg owner alongside
Piper. Recovery validates the durable Artifact and Verification lineage before
materializing a binding; a STARTED execution with incomplete evidence fails
closed and never replays FFmpeg.

The vertical is capability-gated. A project without an explicit absolute
FFmpeg path, or with an executable whose bytes do not match the governed
profile, receives an actionable infrastructure error.
