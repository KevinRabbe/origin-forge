# Phase 55 — Governed Pixelorama Production Provenance Signing — Implementation Closure

Status: **IMPLEMENTED / ACCEPTED — final documentation gate pending**

This document closes the implementation planned in `docs/phase-55-governed-pixelorama-production-provenance-signing.md`. Phase 55 is post-v0.5 development. It composes the exact already-governed Pixelorama production chain from Phases 48–50 with the existing Phase-18 cryptographic provenance service, without inventing a generic media-signing dispatcher, changing the canonical adopted Artifact lifecycle state, redesigning cryptography, widening semantic acceptance authority, or granting release authority.

Phase 55 deliberately stops at **explicit operator-triggered signing of one exact current terminally accepted Pixelorama production result and verification that the newly persisted provenance manifest is trusted/current**. It does not replay Pixelorama, recover Task acceptance, mutate or re-encode the adopted PNG, transition Task/Flow/Goal state, create production Verifications, provision trust, issue/revoke certificates, generate/copy private keys, merge, deploy, publish, or authorize release.

## Final governed Pixelorama provenance-signing boundary

The accepted sequence is:

```text
explicit operator selects one canonical DISPEXEC-*
and one existing ARTIFACT_SIGNING KEYCERT-*
and supplies one external operational private-key path
→ read exact Phase-49 Pixelorama dispatch/output binding
→ require exact Pixelorama execution owner / Task / Run / output relation
→ require exact Phase-49 PUBLISHED adoption receipt and canonical ADOPTED SPRITESHEET_EXPORT
→ require exact Phase-50 ACCEPTED_TASK_SUCCEEDED currentness
→ derive the exact Phase-50 acceptance PASS/receipt relation
→ revalidate canonical adopted PNG containment / non-symlink / regular-file / size / hash / RGBA8 PNG structure
→ delegate to Phase-18 ProvenanceService.sign_artifact(...)
   with the derived adopted Artifact and fixed parent_manifest_ids=()
→ require the signed manifest to bind the exact adopted Artifact / Task / production Run
   and include the exact Phase-49 adoption PASS + Phase-50 acceptance PASS
→ require Phase-18 trust/currentness inspection to report the new manifest trusted/current
→ return one bounded result with production mutation flags false and release_authorized=false
→ STOP
```

The public production identity remains exactly `DISPEXEC-*`. The operator does not supply the Task, Run, output/adopted Artifact, adoption Verification, acceptance Verification, destination/source path, content hash, byte count, WorkOrder, parent provenance, acceptance verdict, media selector, release flag, or any production-recovery override.

A successful signature proves authorship/integrity of the exact provenance claim through the existing Phase-18 trust boundary. It does **not** make production correct, accepted, releasable, merged, deployed, or published. Phase-50 human semantic acceptance remains a prerequisite and independent authority.

## Permanent authority rule

Phase 55 may accept only these explicit operator inputs:

```text
DISPEXEC-*
KEYCERT-*
external operational private-key path
```

Every production identity is derived from the selected execution. The existing Phase-18 provenance service remains authoritative for certificate purpose, root/certificate trust, key identity, revocation, private-key containment/permissions, signature creation, signature-chain verification, immutable manifest publication, and trust/currentness inspection.

Phase 55 never owns:

- Artifact acceptance or `ARTIFACT_ACCEPTED` synthesis;
- Phase-50 Task acceptance publication, recovery, or terminalization;
- Pixelorama execution/replay/repair;
- Phase-49 adoption publication/recovery;
- Task, Flow, or Goal transition authority;
- production Verification creation;
- Company Root provisioning;
- operational certificate issuance/revocation;
- private-key generation/copying/storage;
- arbitrary parent-manifest composition;
- model/specialist/Manager/conversation/browser/background signing;
- generic Blender+Pixelorama production-signing dispatch;
- merge/deploy/publish/release authority.

The adopted production Artifact intentionally remains `ADOPTED`. Phase 55 does not call generic `accept_artifact()` merely to make the provenance path resemble older fixtures.

## 55A — governed production-aware signing service

55A added `GovernedPixeloramaProductionProvenanceSigner` as one narrow application service over already-accepted Pixelorama production truth.

The service accepts only an exact `DISPEXEC-*`, an existing `KEYCERT-*`, and an explicit external operational private-key `Path`. It validates the exact Phase-48/49/50 production relation, requires Phase-50 `ACCEPTED_TASK_SUCCEEDED` currentness without invoking the acceptor, derives the canonical Phase-49 adopted Artifact internally, and independently revalidates the current adopted RGBA8 PNG bytes before cryptographic delegation.

The service delegates to the existing Phase-18 `ProvenanceService.sign_artifact(...)` rather than copying cryptographic trust policy. Initial Phase-55 parent manifests are fixed empty:

```python
parent_manifest_ids=()
```

After signing, 55A requires the returned manifest to bind the exact adopted `SPRITESHEET_EXPORT`, accepted Task, production Run, Phase-49 adoption PASS, and Phase-50 Task-acceptance PASS. It then requires the existing Phase-18 manifest inspection/freshness path to report the persisted manifest trusted and current before returning normal success.

The bounded result exposes only derived production/provenance identities and status. It does not expose the private-key path/bytes and explicitly records that Artifact status, Task status, and production Verification state were not changed and that release is not authorized.

Focused 55A acceptance proves malformed/non-terminal rejection, exact terminal accepted signing, post-terminal adopted-byte drift failure, repeated explicit signing, exact manifest bindings, bounded trust/key rejection, zero production-state mutation, and real Blender cross-media exclusion.

## Repeated signing semantics

Phase 55 intentionally does **not** create a one-manifest-per-execution receipt and does not pretend provenance signing is semantically idempotent.

Phase 18 creates a fresh immutable `PROVMAN-*` identity for each successful explicit signing invocation. Therefore multiple deliberate signatures over the same still-current accepted production result are allowed, including after operational-key rotation or other explicit trust administration.

The invariant is:

```text
each successful explicit invocation signs the same exact current Pixelorama production truth
and mutates no production state
```

There is no automatic retry/re-sign on exception, restart, Manager advance, browser reconnect/poll, conversation event, startup, or background worker. An already-persisted historical manifest is never deleted or rewritten merely because a later freshness check finds drift.

## 55B — module-only operator and adversarial authority hardening

55B extends the existing module-only Pixelorama admin family with one explicit signing command:

```bash
python -m origin_forge.pixelorama_admin_cli \
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

The signing parser accepts exactly the three reviewed signing inputs above. It rejects caller authority for Artifact/Task/Run/Verification identities, alternate source/destination/hash/byte-count truth, acceptance overrides, media selection, parent manifests, root keys, force/bypass, release/publish/deploy, model/tool/specialist selection, or other production/lifecycle overrides.

The CLI delegates exactly to `GovernedPixeloramaProductionProvenanceSigner` and maps governed failures to bounded JSON. It does not expose the private-key path in normal output or bounded governed error payloads.

55B cross-phase/adversarial acceptance includes:

- one exact terminal accepted Pixelorama production result signing successfully through the module command;
- adopted-but-not-accepted execution rejection;
- later canonical PNG byte drift rejection;
- another project's execution identity rejection;
- a real terminal Blender production execution rejected from the Pixelorama signing path;
- `RELEASE_SIGNING` certificate rejection through Phase-18 policy;
- project-contained private-key rejection through Phase-18 policy;
- parser proof that signing exposes only the three reviewed signing inputs and preserves older Pixelorama grammar;
- package-surface proof that the Pixelorama admin module remains module-only and installed scripts remain exactly three;
- source/mock proof that signing does not invoke legacy adoption or Task-acceptance authorities;
- repeated explicit signing creating distinct immutable manifests while production state remains unchanged.

The first 55B canonical run exposed one stale pre-existing CLI-surface test rather than a production-service defect. `tests/test_pixelorama_admin_cli.py::test_surface_contains_only_explicit_governed_commands` still asserted the old three-subcommand module surface and therefore rejected the architecture-authorized `sign-production-provenance` addition on both Python 3.12 and 3.13. The recovery commit changed only that expected command set. No production signer, trust policy, lifecycle authority, or release boundary was widened. The corrected exact head then passed both canonical interpreters before merge.

## Final authority exclusions preserved

Phase 55 adds no:

- generic production-signing bus or media dispatcher;
- automatic/background signing, retry worker, watcher, poller, daemon, timer, queue, startup hook, Manager action, conversation action, or browser signing route;
- Pixelorama replay, repair, second backend invocation, source regeneration, or editor/profile/process authority;
- mutation, overwrite, rewrite, move, deletion, republication, optimization, or re-encoding of the adopted PNG;
- `accept_artifact()` call, `ARTIFACT_ACCEPTED` state event, or `ADOPTED → ACCEPTED` lifecycle conversion;
- Phase-50 acceptance invocation/recovery/publication or Task terminalization;
- caller/model-selected Task, Run, WorkOrder, output/adopted Artifact, Verification, path, hash, byte count, or acceptance truth;
- production Verification creation or Task/Flow/Goal transition;
- Company Root creation, root private-key access, certificate issuance/revocation, operational private-key generation/copying/project storage, or trust-on-demand repair;
- arbitrary caller/browser parent-manifest authority;
- Blender signing/acceptance authority widening;
- model-, vision-, specialist-, Pixelorama-, Manager-, Planner-, conversation-, browser-, or UI-selected signing target/key/certificate authority;
- merge, deployment, publish, or release authorization;
- fourth installed package entrypoint;
- mutation of immutable v0.5 release records.

## Operator trust/key prerequisites

Phase 55 assumes Phase-18 trust administration already exists and is separately authorized. The signing command does not make an unconfigured trust store valid.

Before signing, the operator must already possess:

- the exact trusted Company Root configuration required by Phase 18;
- an existing non-revoked `ARTIFACT_SIGNING` operational certificate identified by `KEYCERT-*`;
- the matching operational private key outside the project tree, satisfying Phase-18 private-key containment and permission rules;
- one exact Phase-48/49 Pixelorama production execution whose output has been canonically adopted through Phase 49 and terminally accepted through Phase 50.

A release-signing certificate is not interchangeable with an artifact-signing certificate. The Company Root private key is not a Phase-55 signing input.

## Current operator command

The Phase-55 operator path is deliberately explicit and module-only:

```bash
python -m origin_forge.pixelorama_admin_cli \
  --project-root /path/to/project \
  sign-production-provenance \
  --execution-id DISPEXEC-... \
  --certificate-id KEYCERT-... \
  --operational-private-key /external/path/to/operational-key.pem
```

A normal successful JSON result identifies the execution, Task, adopted Artifact/destination, accepted hash/size/Verification, provenance manifest/certificate/signing-key/signature identities, and reports trusted/current truth. The result also keeps production mutation and release flags false.

The command is not a recovery command. If Phase-50 acceptance is absent, pending, stale, or conflicting, resolve that independently through the accepted Phase-50 human-governed boundary. If the adopted PNG bytes have drifted, Phase 55 fails closed and does not restore or re-encode them. If Phase-18 trust/key configuration rejects signing, trust administration remains a separate operator responsibility.

## Packaging, Goal bootstrap, Manager, UI and immutable release boundaries preserved

Installed scripts remain exactly:

```text
origin-forge
origin-forge-attempt
origin-forge-cockpit
```

Pixelorama production adoption, Task acceptance, and provenance signing remain explicit module-only subcommands under `origin_forge.pixelorama_admin_cli`.

Phase-45/46 Goal bootstrap remains exactly code-only:

```text
code.change
→ originforge.code.bounded-retry
→ code.bounded-retry@1
```

Phase 55 does not bootstrap, dispatch, execute, adopt, accept, sign, merge, or release Pixelorama work through Goal bootstrap or Manager automation.

The separately governed cockpit/browser/conversation work remains outside Phase-55 signing authority. Phase 55 adds no HTTP route, JavaScript action, browser key/certificate picker, Manager action, conversation command, background signer, or polling side effect. Any future UI signing architecture requires a separately reviewed authority boundary and may not receive private-key material through model/conversation/browser project state.

The immutable v0.5 release remains:

```text
v0.5.0
→ annotated tag object b45c1ef4cbb5b219d165331dff96ffcfa10cf609
→ release commit 8ac46ee5f14654187469e79b021dbbd83992270b
```

Phase 55 is post-v0.5 development and does not move, replace, or rewrite that release identity.

## Exact-head accepted evidence

- **Phase-55 architecture — PR #177:** exact accepted head `058bd2fd1200920cdfafd3b102f11a80c3795836` / canonical run `32613410897`; Python 3.13 job `97129983111` and Python 3.12 job `97129983180` passed; merged as `874b7c0f9ebd2e17015619df0c4a4d53a60fa308`.
- **55A — governed production-aware signing service — PR #178:** exact accepted head `ee8d76993d03e8c48f7fc10d5a87a870bdd1881c` / canonical run `32613994294`; Python 3.13 job `97131508999` and Python 3.12 job `97131509147` passed; merged as `6ea39a7c80d8159147d9230e08fe08ad295cd445`.
- **55B — module-only operator/adversarial hardening — PR #179:** repaired exact accepted head `f95dca2e82518e87b4f494e17cb0dbc9d79f27de` / canonical run `32657074635`; Python 3.13 job `97237396780` and Python 3.12 job `97237396830` passed; merged as `7d07d9267bbc67c4f9149ef7257bfa677255252a`.

The first 55B candidate `8e191f5b8f12e4dc1906c3ac60a95ebed263fec5` failed run `32650782883` on Python 3.13 job `97221927559` and Python 3.12 job `97221927666` only at the stale pre-existing explicit-command-set assertion described above. The repaired accepted head retained the exact final three-file implementation scope: `src/origin_forge/pixelorama_admin_cli.py`, `tests/test_phase55b_pixelorama_production_provenance_cli.py`, and `tests/test_pixelorama_admin_cli.py`, totaling +445/-3. The production signer/service was not widened by that repair.

## Closure gate

This documentation/operator-guide/roadmap closure branch starts from exact accepted Phase-55 implementation `main`:

```text
7d07d9267bbc67c4f9149ef7257bfa677255252a
```

The intended final net diff is documentation only:

```text
docs/phase-55-implementation-closure.md
docs/operator-guide.md
docs/roadmap.md
```

The frozen planning document `docs/phase-55-governed-pixelorama-production-provenance-signing.md` remains unchanged as the historical architecture contract.

The closure may not modify production source, tests, schema, config, packaging, workflows, runtime/Manager/Goal-bootstrap authority, cockpit/server/browser/conversation/GUI code, Blender authority, adopted PNG bytes, Phase-49 adoption semantics, Phase-50 Task-acceptance semantics, Phase-18 cryptographic/trust policy, merge/release authority, or immutable v0.5 release records.

The final immutable closure head must pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error. Only that exact green head may be transitioned out of draft and SHA-guarded merged.
