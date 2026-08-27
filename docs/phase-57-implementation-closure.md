# Phase 57 Implementation Closure

Status: **Phase 57A–57C implemented; Phase 57D evidence synchronization in progress**

Latest candidate evidence head: `bf482cd`.
Remote CI is in progress for this head; the branch remains a draft PR and the
final Phase 57D release gate is therefore still open. The candidate also
contains the later governed Pixelorama source/animation vertical and its
read-only trace evidence; those additions do not alter Phase-57 authority.
The source WorkOrder planner now binds accepted-design animation intents before
WorkOrder freeze, and the fake-bridge vertical verifies dispatch, adoption,
actor-bound acceptance, and no-replay recovery with that derived animation.
The candidate also retries bounded checkpoint contention during Goal bootstrap
finalization instead of mistaking a concurrent writer race for semantic goal
staleness; the regression is covered by the focused finalization suite.

Phase 57 now closes the semantic-request boundary from accepted design evidence
to the existing protected Blender request registry. The implementation keeps
the Phase-20A `BlockbenchProjectSpec`, Phase-51 WorkOrder and execution, and
Phase-53 result acceptance contracts unchanged.

## Historical implementation heads

- Phase 57A base: `8cb0f50170edbb0fc1118ecfcf98241a53cdc992`
- Phase 57B publication: `2590160ccf4d4d919189c1b1bc644c6905d25ba8`
- Phase 57C admission: `6d1d883413e7ceac6a72b870e62793e27ecfa757`

The Phase 57B/57C implementation adds the immutable
`M3DREQAPP-*` / `M3DREQPUB-*` evidence families. Approval freezes an
infrastructure-owned `MODEL3DREQ-*` identity, canonical request bytes, and
request hash. Publication is create-only and revalidated through the existing
Phase-51 protected reader. Phase-51 admission requires the exact current
Task/publication/request relation and rejects stale upstream lineage.

Subsequent foundation work has advanced the composed candidate schema to v32.
Migration v28 records a `sha256:` hash for each migration after validating its
version; historical rows with no hash are backfilled only when their versions
and SQL identity are known. Migration v29 preserves existing shared Piper
audio-binding rows and adds the reviewed FFmpeg owner constraint without
rewriting those rows. A stored hash mismatch fails closed before further
upgrade work. These migrations change migration-integrity and owner-compatibility
evidence only; migration v30 adds the dedicated Pixelorama source/animation
multi-output binding surface without rewriting domain IDs, receipts, or
existing production evidence. Migration v31 adds the dedicated create-only
Pixelorama source adoption receipt, and migration v32 adds the explicit
actor-bound source Task-acceptance receipt. Both are immutable and preserve
the existing Phase-57 rows byte-for-byte.

The module-only operator surface is:

```text
python -m origin_forge.model3d_request_publication_admin_cli approve
python -m origin_forge.model3d_request_publication_admin_cli publish
python -m origin_forge.model3d_request_publication_admin_cli inspect
```

No installed entry point, browser mutation authority, Manager auto-approval,
Blender execution authority, adoption authority, Task acceptance, signing, or
release authority was added.

## Verification

The focused Phase 57A/57B/57C and migration suite covers exact approval retry,
create-only publication, protected-request tampering, competing proposals,
immutable evidence, exact Phase-51 admission matching, and stale-lineage
rejection. The focused candidate verification also covers source execution,
adoption, acceptance, trace, migration, and doctor behavior. The current
remote verification baseline also includes 23 Phase-51
and Phase-57 tests with one explicit symlink capability skip, five migration
tests, and the 15-test Blender invocation/currentness regression suite. The
canonical workflow runs the Windows/Linux Python matrix, strict doctor
preflight, resource-warning checks, and the configured type-check baseline;
mypy writes its cache to the runner temporary directory. Full canonical CI
remains the release gate and must run against the final candidate commit in the
repository hosting workflow. The current candidate matrix is workflow
`33053950400` for candidate `bf482cd`.
