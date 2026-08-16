from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


operator_path = Path("docs/operator-guide.md")
operator = operator_path.read_text(encoding="utf-8")
operator = replace_once(
    operator,
    "Status: **POST-v0.1 DEVELOPMENT MAINLINE**",
    "Status: **POST-v0.5 DEVELOPMENT MAINLINE**",
    "operator status",
)
operator = replace_once(
    operator,
    "This guide describes the current `main` operator surface. Origin Forge v0.1.0 was released on 2026-08-11 and remains immutably identified by tag `v0.1.0`; the current development line is `0.2.0.dev0` and contains post-release capabilities through Phase 47. For the exact released v0.1.0 surface, see `docs/v0.1-operator-guide.md`.",
    "This guide describes the current `main` operator surface. Origin Forge v0.5.0 was released on 2026-08-16 and remains immutably identified by annotated tag `v0.5.0` at release commit `8ac46ee5f14654187469e79b021dbbd83992270b`; current `main` is post-v0.5 development and contains the separately gated Phase-48 Pixelorama production-dispatch integration. For the exact released v0.5.0 surface, see `docs/v0.5-operator-guide.md`.",
    "operator release intro",
)
operator = replace_once(
    operator,
    "Current development metadata uses package version `0.2.0.dev0` under the Apache License 2.0. This development version is not a promise or tag for a future v0.2 release.",
    "Current source metadata remains package version `0.5.0` under the Apache License 2.0. The immutable `v0.5.0` tag identifies the released bits; post-release Phase-48 commits on `main` are not retroactively part of that tagged release merely because the source version string remains `0.5.0`.",
    "operator package metadata",
)
operator = replace_once(
    operator,
    "Phase 47 does not widen this bootstrap boundary: Phase-45/46 Goal bootstrap remains exactly code-only (`code.change → originforge.code.bounded-retry → code.bounded-retry@1`). It does not bootstrap `simulation.run` Tasks.",
    "Phases 47 and 48 do not widen this bootstrap boundary: Phase-45/46 Goal bootstrap remains exactly code-only (`code.change → originforge.code.bounded-retry → code.bounded-retry@1`). It does not bootstrap `simulation.run` or `media.2d.export` Tasks.",
    "operator bootstrap isolation",
)
manager_anchor = """There is no direct `origin-forge simulation run` mutation command. Production simulation execution is reachable only through already-governed preparation/claim/dispatch authority and the existing explicit Manager invocation.

The cockpit remains a separate read-only inspection surface. It does not receive a Manager, Goal-bootstrap, or simulation mutation command.
"""
manager_replacement = """There is no direct `origin-forge simulation run` mutation command. Production simulation execution is reachable only through already-governed preparation/claim/dispatch authority and the existing explicit Manager invocation.

Phase 48 likewise allows an **already-governed** `media.2d.export` Task using the exact `originforge.pixelorama.export / pixelorama.spritesheet-export@1` relation to execute through the same explicit Manager path. Its WorkOrder must contain exactly one project-owned `PIXELORAMA_PROJECT` Artifact ref with role `pixelorama_project`. Phase 34 resolves and revalidates that Artifact as metadata only; the `.pxo` source is opened only after durable DISPEXEC `STARTED` and Task `READY → RUNNING` ownership.

The Pixelorama execution owner uses the infrastructure-owned trusted Pixelorama CLI profile, not caller/model-selected executable or process settings. After STARTED it revalidates the exact local `.pxo` source path, containment, regular-file/no-symlink status, hash, and bounded byte count; allocates fresh `PXOP-*` and `MEDIA-*` identities; and invokes the durable direct CLI spritesheet-export service at most once. A trustworthy return creates one PIXELORAMA Run plus exact request/result/export/Verification evidence, consumes the claim, records DISPEXEC `RETURNED`, and leaves the production Task `RUNNING`.

Pixelorama export evidence is structural only. Manager does not infer aesthetic quality or Task acceptance, does not adopt the exported PNG into a canonical project path, does not sign it, and does not complete/fail the Task. Project creation/import/edit/save, arbitrary extensions/plugins/GDScript, caller-selected source/output paths, and automatic replay after STARTED remain outside the production boundary. There is no direct mutating Pixelorama production command.

The cockpit remains a separate read-only inspection surface. It does not receive a Manager, Goal-bootstrap, simulation, or Pixelorama mutation command.
"""
operator = replace_once(operator, manager_anchor, manager_replacement, "operator manager Pixelorama insertion")
operator = replace_once(
    operator,
    "The Phase-47 deterministic simulation dispatch boundary follows the same no-replay law: once simulation DISPEXEC `STARTED` is durable, a BaseException/crash or post-evidence terminalization failure requires explicit recovery rather than a second automatic simulation call.",
    "The Phase-47 deterministic simulation and Phase-48 Pixelorama dispatch boundaries follow the same no-replay law: once owner-specific DISPEXEC `STARTED` is durable, a BaseException/crash or post-evidence terminalization failure requires explicit recovery rather than a second automatic backend/editor call.",
    "operator recovery no replay",
)
operator = replace_once(
    operator,
    "- direct simulation mutation commands or automatic Task terminalization from simulation findings;\n- background Goal bootstrap or Manager scheduling/queue draining;",
    "- direct simulation or Pixelorama production mutation commands, or automatic Task terminalization from simulation/export evidence;\n- generic Pixelorama project creation/import/edit/save, arbitrary editor scripts/plugins, or automatic output adoption/signing;\n- background Goal bootstrap or Manager scheduling/queue draining;",
    "operator current boundary",
)
operator = replace_once(
    operator,
    "The immutable v0.1.0 release remains documented separately in `docs/v0.1-release-readiness.md`, `docs/v0.1-acceptance-matrix.md`, and `docs/v0.1-operator-guide.md`.",
    "The immutable v0.5.0 release remains documented separately in `docs/v0.5-release-readiness.md`, `docs/v0.5-acceptance-matrix.md`, and `docs/v0.5-operator-guide.md`. Phase 48 is explicitly post-v0.5 development.",
    "operator release footer",
)
operator_path.write_text(operator, encoding="utf-8")

roadmap_path = Path("docs/roadmap.md")
roadmap = roadmap_path.read_text(encoding="utf-8")
anchor = """Target capabilities:

- durable long-running work
- local coding models
- governed Skills + Skill evaluation
- structural/LSP code intelligence
- progressive tool discovery
- model/resource scheduling
- offline memory consolidation and audited improvement proposals
- specialist review
- project graph + Design Bible
- cryptographic provenance
- basic 2D production

# v1.0 — Integrated Game Production
"""
replacement = """Target capabilities:

- durable long-running work
- local coding models
- governed Skills + Skill evaluation
- structural/LSP code intelligence
- progressive tool discovery
- model/resource scheduling
- offline memory consolidation and audited improvement proposals
- specialist review
- project graph + Design Bible
- cryptographic provenance
- basic 2D production

## Phase 48 — Governed Pixelorama Spritesheet Export Production Dispatch — DONE

Completed as the first separately gated **post-v0.5 v1.0 production-integration slice**, without changing the immutable `v0.5.0` tag or claiming Phase 48 was part of that release:

- explicit Pixelorama production authority is limited to `media.2d.export → originforge.pixelorama.export → pixelorama.spritesheet-export@1`;
- the Phase-33 WorkOrder contract accepts exactly one project-owned `ARTIFACT` ref with role `pixelorama_project` and an inert `{}` payload; it exposes no caller/model process, path, profile, workspace, identity, adoption, signing, or Task authority;
- Phase-34 binding reuses the existing metadata-only Artifact resolver and requires a current `PIXELORAMA_PROJECT` Artifact without reading source bytes before execution ownership;
- Phase-39 adds the separate `originforge.preparation.pixelorama-spritesheet-export-planner@1` owner, reuses the one-shot `CODER_STRONG` WorkOrder Planner, and preserves mixed-owner fail-closed semantics and code-only Goal bootstrap;
- Phase-36 adds `originforge.execution.pixelorama.spritesheet-export@1`, requires only infrastructure-owned trusted Pixelorama profile dependencies, and atomically commits DISPEXEC `STARTED + Task READY→RUNNING` with no model/runtime/resource/sandbox/Git-Workspace stack;
- post-STARTED execution validates the exact local `.pxo` source path, containment, no-symlink/regular-file status, frozen hash, and bounded byte count before allocating fresh `PXOP-*` / `MEDIA-*` identities;
- the durable direct CLI export service invokes the already-proven Pixelorama v1.2 spritesheet-export adapter at most once, persists one PIXELORAMA Run plus request/result/PNG Artifact/Verification lineage, and independently revalidates that evidence before DISPEXEC RETURNED;
- normal return consumes the claim but leaves the production Task RUNNING; export structure is not aesthetic quality, Task PASS/FAIL, adoption, signing, merge, release, or deployment truth;
- ordinary owner exceptions record RAISED/CONSUMED while BaseException/crash or post-evidence terminalization uncertainty preserves explicit no-replay recovery state;
- cross-phase acceptance proves the real preparation→claim→execution→Manager path, exact one-ref persisted planner recovery/currentness, at-most-one concurrent Pixelorama invocation, no newer-Task fallback, unchanged bounded-code/simulation behavior, and unchanged Phase-45/46 code-only Goal-bootstrap authority;
- the final production execution owner set is exactly bounded code, deterministic simulation, and Pixelorama spritesheet export; no dynamic owner/plugin dispatch, generic media execution, project create/import/edit/save, arbitrary editor scripting, automatic adoption/signing, direct mutating Pixelorama CLI, cockpit mutation, background loop, or fourth packaged command is added.

See `docs/phase-48-governed-pixelorama-spritesheet-export-production-dispatch.md` for the frozen architecture and `docs/phase-48-implementation-closure.md` for the accepted 48A–48F implementation, integration repairs, cross-phase adversarial acceptance, authority exclusions, and exact CI evidence.

**Exit condition met in implementation:** planning head `52411df4` / run `31915469094`, 48A head `c6e32857` / run `31915910291`, 48B head `78e86b4da53be894be2223ee807ba208d42f618a` / run `31922527176`, 48C head `12e10bcbbba5a19d286dbd924ef1270ef929b900` / run `31924707175`, 48D head `66d8c52d4d8f57eed43ddb376a06981ea0bf71e1` / run `31928255035`, the persisted-currentness repair head `4e3bafee120232f607c6405c1dfee6acb33b8845` / run `31929089584`, 48E head `2e1131c85adf3039cd2685c7380300ebfdc6b7ea` / run `31936867196`, and 48F accepted head `68315a50526ac00634ce03d26e669a7053c8ace1` / run `31945142450` all passed Python 3.12 and Python 3.13. Accepted Phase-48 implementation/acceptance is merged to `main` as `16eb0cd631ec572d07605209cb8ca29a1c5f3db9`.

**Merge gate:** this documentation/operator-guide/roadmap closure head must itself pass the normal Python 3.12/3.13 matrix with `ResourceWarning` treated as error before ready-for-review transition and SHA-guarded merge.

# v1.0 — Integrated Game Production
"""
roadmap = replace_once(roadmap, anchor, replacement, "roadmap Phase 48 insertion")
roadmap_path.write_text(roadmap, encoding="utf-8")
