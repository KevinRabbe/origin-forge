# Phase 54 — Governed Blender Production Provenance Signing — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-54-governed-blender-production-provenance-signing.md`. Phase 54 is post-v0.5 development. It composes the exact already-governed Blender production chain from Phases 51–53 with the existing Phase-18 cryptographic provenance service, without inventing a new production-acceptance authority, changing the adopted Artifact lifecycle state, redesigning cryptography, or granting release authority.

Phase 54 deliberately stops at **explicit operator-triggered signing of one exact current terminally accepted Blender production result and verification that the newly persisted provenance manifest is trusted/current**. It does not replay Blender, recover Task acceptance, mutate the adopted GLB, transition Task/Flow/Goal state, create production Verifications, provision trust, issue/revoke certificates, generate/copy private keys, merge, deploy, publish, or authorize release.

## Final governed Blender provenance-signing boundary

The accepted sequence is:

```text
explicit operator selects one canonical DISPEXEC-*
and one existing ARTIFACT_SIGNING KEYCERT-*
and supplies one external operational private-key path
→ read exact Phase-51 Blender dispatch/output binding
→ require exact Blender execution owner / Task / Run / output relation
→ require exact Phase-52 PUBLISHED adoption receipt and canonical ADOPTED BLENDER_GLB_EXPORT
→ require exact Phase-53 ACCEPTED_TASK_SUCCEEDED currentness
→ derive the exact Phase-53 acceptance PASS/receipt relation
→ revalidate canonical adopted GLB containment / non-symlink / regular-file / size / hash / GLB structure
→ delegate to Phase-18 ProvenanceService.sign_artifact(...)
   with the derived adopted Artifact and fixed parent_manifest_ids=()
→ require the signed manifest to bind the exact adopted Artifact / Task / production Run
   and include the exact Phase-52 adoption PASS + Phase-53 acceptance PASS
→ require Phase-18 trust/currentness inspection to report the new manifest trusted/current
→ return one bounded result with production mutation flags false and release_authorized=false
→ STOP
```

The public production identity remains exactly `DISPEXEC-*`. The operator does not supply the Task, Run, output/adopted Artifact, adoption Verification, acceptance Verification, destination, content hash, byte count, WorkOrder, MODEL3D request, parent provenance, acceptance verdict, release flag, or any production-recovery override.

A successful signature proves authorship/integrity of the exact provenance claim through the existing Phase-18 trust boundary. It does **not** make production correct, accepted, releasable, merged, deployed, or published. Phase-53 human semantic acceptance remains a prerequisite and independent authority.

## Permanent authority rule

Phase 54 may accept only these explicit operator inputs:

```text
DISPEXEC-*
KEYCERT-*
external operational private-key path
```

Every production identity is derived from the selected execution. The existing Phase-18 provenance service remains authoritative for certificate purpose, root/certificate trust, key identity, revocation, private-key containment/permissions, signature creation, signature-chain verification, immutable manifest publication, and trust/currentness inspection.

Phase 54 never owns:

- Artifact acceptance or `ARTIFACT_ACCEPTED` synthesis;
- Phase-53 Task acceptance publication, recovery, or terminalization;
- Blender execution/replay/repair;
- Phase-52 adoption publication/recovery;
- Task, Flow, or Goal transition authority;
- production Verification creation;
- Company Root provisioning;
- operational certificate issuance/revocation;
- private-key generation/copying/storage;
- arbitrary parent-manifest composition;
- model/specialist/Manager/conversation/browser/background signing;
- merge/deploy/publish/release authority.

The adopted production Artifact intentionally remains `ADOPTED`. Phase 54 does not call generic `accept_artifact()` merely to resemble older provenance fixtures.

## 54A — governed production-aware signing service

54A added `GovernedBlenderProductionProvenanceSigner` as one narrow application service over already-accepted production truth.

The service accepts only an exact `DISPEXEC-*`, an existing `KEYCERT-*`, and an explicit external operational private-key `Path`. It validates the exact Phase-51/52/53 production relation, requires Phase-53 `ACCEPTED_TASK_SUCCEEDED` currentness without invoking the acceptor, derives the canonical Phase-52 adopted Artifact internally, and independently revalidates the current adopted GLB bytes before cryptographic delegation.

The service delegates to the existing Phase-18 `ProvenanceService.sign_artifact(...)` rather than copying cryptographic trust policy. Initial Phase-54 parent manifests are fixed empty:

```python
parent_manifest_ids=()
```

After signing, 54A requires the returned manifest to bind the exact adopted `BLENDER_GLB_EXPORT`, accepted Task, production Run, Phase-52 adoption PASS, and Phase-53 Task-acceptance PASS. It then requires the existing Phase-18 manifest inspection/freshness path to report the persisted manifest trusted and current before returning normal success.

The bounded result exposes only derived production/provenance identities and status. It does not expose the private-key path/bytes and explicitly records that Artifact status, Task status, and production Verification state were not changed and that release is not authorized.

Focused 54A acceptance proves malformed/non-terminal rejection, exact terminal accepted signing, post-terminal adopted-byte drift failure, repeated explicit signing, exact manifest bindings, and bounded wrong-key/trust failures without production-state mutation.

## Repeated signing semantics

Phase 54 intentionally does **not** create a one-manifest-per-execution receipt and does not pretend provenance signing is idempotent.

Phase 18 creates a fresh immutable `PROVMAN-*` identity for each successful explicit signing invocation. Therefore multiple deliberate signatures over the same still-current accepted production result are allowed, including after operational-key rotation or other explicit trust administration.

The invariant is:

```text
each successful explicit invocation signs the same exact current production truth
and mutates no production state
```

There is no automatic retry/re-sign on exception, restart, Manager advance, browser reconnect/poll, conversation event, startup, or background worker. An already-persisted historical manifest is never deleted or rewritten merely because a later freshness check finds drift.

## 54B — module-only operator and adversarial authority hardening

54B extends the existing module-only Blender admin family with one explicit signing command:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /external/path/to/key.pem
```

No fourth installed package entrypoint was added. Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

The signing parser accepts exactly the three reviewed signing inputs above. It rejects caller authority for Artifact/Task/Verification identities, alternate destination/hash/byte-count truth, parent manifests, root keys, accept/force/bypass, release/publish/merge, or other production/lifecycle overrides.

The CLI delegates exactly to `GovernedBlenderProductionProvenanceSigner` and maps governed failures to bounded JSON. It does not expose the private-key path in normal output or bounded governed error payloads.

54B cross-phase/adversarial acceptance includes:

- one exact terminal accepted Blender production result signing successfully through the module command;
- adopted-but-not-accepted execution rejection;
- later canonical GLB byte drift rejection;
- another project's execution identity rejection;
- a real returned Pixelorama production execution rejected from the Blender signing path;
- `RELEASE_SIGNING` certificate rejection through Phase-18 policy;
- project-contained private-key rejection through Phase-18 policy;
- parser rejection of widened signing/acceptance/release inputs;
- package-surface proof that the Blender admin module remains module-only;
- source-level proof that signing contains no Task acceptance, production execution, Task/Flow/Goal lifecycle mutation, Manager, conversation, browser, background, or release call path;
- production state and adopted GLB bytes unchanged by successful signing.

The first 54B canonical run exposed two test-only integration assumptions rather than a production-service defect: the reused Phase-48 Pixelorama SQL row exposes `execution_id` rather than `id`, and the authority fixture had stale targets for the existing `origin-forge-attempt` / `origin-forge-cockpit` package scripts. Those assertions were corrected only to current repository truth. The repaired exact head then passed both canonical interpreters before merge.

## Final authority exclusions preserved

Phase 54 adds no:

- generic production-signing bus;
- automatic/background signing, retry worker, watcher, poller, daemon, timer, queue, startup hook, Manager action, conversation action, or browser signing route;
- Blender replay, repair, second backend invocation, source regeneration, or runtime/profile/process authority;
- mutation, overwrite, rewrite, move, deletion, republication, or automatic repair of the adopted GLB;
- `accept_artifact()` call, `ARTIFACT_ACCEPTED` state event, or `ADOPTED → ACCEPTED` lifecycle conversion;
- Phase-53 acceptance invocation/recovery/publication or Task terminalization;
- caller/model-selected Task, Run, WorkOrder, MODEL3D request, output/adopted Artifact, Verification, path, hash, byte count, or acceptance truth;
- production Verification creation or Task/Flow/Goal transition;
- Company Root creation, root private-key access, certificate issuance/revocation, operational private-key generation/copying/project storage, or trust-on-demand repair;
- arbitrary caller/browser parent-manifest authority;
- Pixelorama signing/acceptance authority widening;
- model-, vision-, specialist-, Blender-, Manager-, Planner-, conversation-, browser-, or UI-selected signing target/key/certificate authority;
- merge, deployment, publish, or release authorization;
- fourth installed package entrypoint;
- mutation of immutable v0.5 release records.

## Operator trust/key prerequisites

Phase 54 assumes Phase-18 trust administration already exists and is separately authorized. The signing command does not make an unconfigured trust store valid.

Before signing, the operator must already possess:

- the exact trusted Company Root configuration required by Phase 18;
- an existing non-revoked `ARTIFACT_SIGNING` operational certificate identified by `KEYCERT-*`;
- the matching operational private key outside the project tree, satisfying Phase-18 private-key containment and permission rules;
- one exact Phase-51 Blender production execution that has been canonically adopted through Phase 52 and terminally accepted through Phase 53.

A release-signing certificate is not interchangeable with an artifact-signing certificate. The Company Root private key is not a Phase-54 signing input.

## Current operator command

The Phase-54 operator path is deliberately explicit and module-only:

```bash
python -m origin_forge.blender_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /external/path/to/operational-key.pem
```

A normal successful JSON result identifies the execution, Task, adopted Artifact/destination, accepted hash/size/Verification, provenance manifest/certificate/signing-key/signature identities, and reports trusted/current truth. The result also keeps production mutation and release flags false.

The command is not a recovery command. If Phase-53 acceptance is absent, pending, stale, or conflicting, resolve that independently through the accepted Phase-53 human-governed boundary. If the adopted GLB bytes have drifted, Phase 54 fails closed and does not restore them. If Phase-18 trust/key configuration rejects signing, trust administration remains a separate operator responsibility.

## Packaging, Goal bootstrap, Manager, UI and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Blender production adoption, Task acceptance, and provenance signing remain explicit module-only subcommands under `origin_forge.blender_admin_cli`.

Phase-45/46 Goal bootstrap remains exactly code-only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

Phase 54 does not bootstrap, dispatch, execute, adopt, accept, sign, merge, or release Blender work through Goal bootstrap or Manager automation.

The separately governed cockpit/browser/conversation work remains outside Phase-54 signing authority. Phase 54 adds no HTTP route, JavaScript action, browser key/certificate picker, Manager action, conversation command, background signer, or polling side effect. Any future UI signing architecture would require a separately reviewed authority boundary and may not receive private-key material through model/conversation state.

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 54 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-54 architecture — PR #173:** exact accepted head `bf5381d442aa174ced0e747a72a2fef7cbeb8fb9` / canonical run `32592325248`; Python 3.12 job `97077958771` and Python 3.13 job `97077958648` passed; merged as `eb719d88ee334685c8186b79d7f65a5e5c844d18`.
- **54A — governed production-aware signing service — PR #174:** exact accepted head `066935565b7aa47f806f39711d3d2a99b07121b4` / canonical run `32594069919`; Python 3.12 job `97082198625` and Python 3.13 job `97082198699` passed; merged as `66c8af984c6fd5fcab7fdbea45a59494a9704c71`.
- **54B — module-only operator/adversarial hardening — PR #175:** exact accepted head `75718f1ffa843741e86fe16acbcbbdd11f6d281c` / canonical run `32606508671`; Python 3.12 job `97112217771` and Python 3.13 job `97112217663` passed; merged as `00c169b3d56a4750d371f6005bfa324b47477101`.

The repaired 54B exact head retained the exact three-file implementation scope: `src/origin_forge/blender_admin_cli.py`, `tests/test_phase54b_blender_production_provenance_cli.py`, and `tests/test_phase54b_blender_production_provenance_cli_authority.py`. The two repairs after the initial red run were test-only current-repository alignment; the accepted production signer/service was not widened.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact accepted Phase-54 implementation `main`:

```text
00c169b3d56a4750d371f6005bfa324b47477101
```

The intended final net diff is documentation only:

```text
docs/phase-54-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

The frozen planning document `docs/phase-54-governed-blender-production-provenance-signing.md` remains unchanged as the historical architecture contract.

The closure may not modify production source, tests, schema, config, packaging, workflows, runtime/Manager/Goal-bootstrap authority, cockpit/server/browser/conversation/GUI code, Pixelorama authority, adopted GLB bytes, Phase-52 adoption semantics, Phase-53 Task-acceptance semantics, Phase-18 cryptographic/trust policy, merge/release authority, or immutable v0.5 release records.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
