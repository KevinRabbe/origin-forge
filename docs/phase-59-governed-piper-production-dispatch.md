# Phase 59 — Governed Piper Production Dispatch

Status: implemented on the Phase 57B development branch.

Phase 59 promotes the existing Piper TTS adapter through the production
dispatch lifecycle without granting it semantic acceptance or adoption
authority:

```text
WorkOrder → resolution → binding → claim → STARTED execution
→ Piper invocation → Artifact/Verification evidence
→ durable audio output binding → RETURNED → recovery
```

The frozen request contains the exact Task, Audio Profile identity/hash,
speech text, duration and timeout limits, output path, and request hash.
The profile is reloaded from the protected AudioProfileStore after the
execution boundary; the request projection does not carry a duplicated mutable
profile object. Piper infrastructure is explicit and local-only through
`ORIGIN_FORGE_PIPER_RUNTIME_ROOT`, `ORIGIN_FORGE_PIPER_EXECUTABLE`,
`ORIGIN_FORGE_PIPER_ESPEAK_DATA`, `ORIGIN_FORGE_PIPER_MODEL`,
`ORIGIN_FORGE_PIPER_MODEL_CONFIG`, and `ORIGIN_FORGE_PIPER_LICENSE`.

The v25 `audio_dispatch_output_bindings` table stores request/result/output
Artifact and Verification identities, canonical WAV metrics, hashes, and the
exact execution relation. Recovery materializes a valid binding without
invoking Piper again. A `STARTED` execution without complete durable evidence
fails closed; it is never replayed automatically.

The governed fake-runner acceptance test is
`tests/test_production_piper_dispatch_vertical.py`. Pinned real Piper tests
remain capability-gated and require explicit local infrastructure. Missing or
drifted configuration must be diagnosed before execution; Origin Forge never
downloads, installs, or discovers hidden voice state.

Piper produces evidence only. Human semantic acceptance, canonical adoption,
signing, merge, and release remain separate authority boundaries.
