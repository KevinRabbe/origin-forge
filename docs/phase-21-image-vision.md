# Phase 21 — Image and Vision

Status: **DONE**

Phase 21 adds replaceable local image generation/editing and advisory vision inspection without allowing either capability to become a new production authority path.

## Core rule

```text
backend/model output = untrusted evidence
Origin Forge deterministic validation = structural truth
human/governance = acceptance/promotion authority
```

Image generation and vision inspection are deliberately separate roles. A generator cannot declare its own output good; a vision model cannot mark an asset verified, adopted, production-ready, or complete a Task.

## Implemented substrate

### Typed identities

- `IMAGE-*` — isolated image workspace
- `IMGOP-*` — bounded image operation
- `VISION-*` — frozen advisory vision inspection

### Image operation contract

`ImageOperationRequest` freezes:

- operation (`GENERATE` or `EDIT`);
- exact backend ID/version;
- exact approved workflow ID/hash;
- exact model ID/hash;
- prompt and negative prompt;
- dimensions, seed, steps and guidance;
- exact input raster evidence for edit operations;
- declared PNG output paths;
- hard timeout/history/output budgets.

Generation requests cannot carry edit inputs. Edit requests require at least one exact raster input. Paths are portable, workspace-relative and bounded.

`ImageOperationResult` must bind the exact operation/workspace/request/backend/workflow/model identities. A successful result must declare exactly the requested outputs; failed/blocked results may not claim produced output evidence.

### Independent raster evidence

Every generated PNG is independently decoded by Origin Forge. The Phase 21 generation boundary accepts only bounded truecolor RGB8/RGBA8 PNG from the backend, normalizes it to deterministic RGBA8 bytes, and then records:

- file SHA-256;
- decoded pixel SHA-256;
- byte count;
- width/height;
- structural raster PASS evidence.

A backend-reported hash or successful process/HTTP response is never sufficient on its own. Phase 19's stricter Pixelorama RGBA8 contract remains unchanged.

### Governed ComfyUI workflow templates

ComfyUI is the initial image-generation backend because its core exposes a local workflow API rather than requiring GUI automation.

Origin Forge does **not** accept arbitrary model-supplied ComfyUI graphs. A `GovernedComfyWorkflowTemplate` freezes and content-addresses:

- the API workflow graph;
- every allowed input binding Origin Forge may mutate;
- the trusted output node;
- operation type;
- exact ComfyUI backend version;
- exact model ID/hash.

Changing a prompt binding, output node, graph, operation, backend version, or model identity changes the approved workflow hash.

`ImageWorkflowStore` publishes reviewed templates immutably under protected Origin Forge state. Store objects are byte-bounded, count-bounded, symlink-safe, tamper-detected and content-addressed.

### ComfyUI generation adapter

The initial `ComfyUiAdapter` authorizes `GENERATE` only.

It:

1. requires loopback unless remote execution is explicitly enabled;
2. refuses HTTP redirects;
3. verifies the server's exact `comfyui_version` through `/system_stats`;
4. renders only infrastructure-approved template bindings;
5. submits an infrastructure-derived exact prompt UUID to `/prompt`;
6. requires an empty ComfyUI workflow-validation error set;
7. polls only `/history/<exact prompt id>` within a hard deadline/byte budget;
8. reads images only from the approved output node;
9. accepts only bounded safe output metadata;
10. retrieves output bytes through `/view`;
11. independently decodes/hashes/dimension-checks each PNG and normalizes accepted RGB8/RGBA8 output to canonical RGBA8 PNG;
12. writes only the exact declared `exports/*.png` files inside protected `IMAGE-*` workspace state.

The adapter has no Task/Goal transition, merge/release, model-download, custom-node installation, arbitrary workflow execution, asset adoption, signing, or semantic verification surface.

### Advisory llama.cpp vision adapter

The initial vision adapter reuses llama.cpp's OpenAI-compatible multimodal server boundary rather than adding a second unrestricted model runtime.

Before the model call it requires:

- exact image ID set;
- exact source byte count and SHA-256;
- successful Origin Forge RGBA8 PNG decode;
- exact decoded pixel hash and dimensions;
- exact configured model ID and model SHA-256;
- exact configured multimodal projector hash when required by the frozen request/profile;
- bounded total image bytes;
- loopback by default and no redirect following.

The multimodal request uses a fixed strict transport schema. The llama.cpp transport schema is deliberately a stricter subset of the provider-neutral report contract so the pinned runtime can compile the grammar without weakening deterministic acceptance. The canonical returned report is still parsed fail-closed. Unknown fields, authority claims, invalid severities, duplicate semantic findings, and findings referencing images outside the frozen request are rejected.

Every accepted `VisionReport` permanently carries:

```text
semantic_findings_verified = false
advisory_only = true
```

A structural PASS means only that the report is well formed, exactly bound and replayable. It does not establish that its visual judgments are correct.

### Durable services

`ImageGenerationService` records a dedicated `IMAGE_GENERATOR` Run and persists:

- exact request Artifact;
- exact backend result Artifact;
- generated PNG Artifacts;
- deterministic `image-output-integrity` Artifact Verifications;
- a Run-level `image-generation-structure` Verification.

The service independently requires the backend-reported workspace to resolve to the exact protected `.origin-forge/image-workspaces/<workspace_id>` directory before it trusts any persisted request/result/output bytes.

`VisionInspectionService` records a dedicated `VISION_INSPECTOR` Run over exact existing raster Artifacts and persists:

- frozen inspection request Artifact;
- advisory report Artifact;
- exact source Artifact IDs/hashes;
- `vision-report-structure` Artifact Verification;
- Run-level `vision-inspection-structure` Verification.

Neither service changes production Task status/revision or records a Task PASS.

### Explicit create-only adoption

`GeneratedImageAdopter` is the only current path from isolated generated output to a project file. It requires exact PASS `image-output-integrity` evidence, rechecks current source bytes and PNG structure, rejects protected/existing/symlink destinations, performs create-only publication, then rehashes/redecodes the published file and records `image-adoption-integrity` evidence.

Adoption does not imply semantic visual approval and does not complete a Task.

### Read-only CLI

`python -m origin_forge.image_vision_cli` provides only:

- `status`
- `workflow-list`
- `workflow-show`
- `artifact-show`
- `generation-runs`
- `vision-runs`

There is intentionally no generate/edit/inspect/adopt/install/model-download/promote/merge/release CLI command in the initial inspection surface.

## Real-backend evidence levels

Phase 21 keeps these claims distinct:

1. **Protocol/substrate proof** — fake local servers/processes prove Origin Forge request, isolation, validation and authority boundaries.
2. **Real API transport proof** — an exact real ComfyUI/llama.cpp runtime proves our adapter can use the supported upstream API. A core-only/no-model workflow may satisfy transport proof, but not model proof.
3. **Real model proof** — exact reviewed local model files and runtime identities execute the intended generation/vision workloads, with outputs independently validated and frozen evidence retained.
4. **Quality evaluation** — a separate paired/replayable benchmark establishes whether a model/workflow is useful enough for a specific role. Successful execution alone is not quality evidence.

These levels may not be collapsed into one another.

## Completed real-model profiles

### Generation

The evidence workflow pins:

- ComfyUI source commit `700821e1364eaab0e8f21c538a2131719fec57bf` / version `0.28.0`;
- exact Python 3.13 installed-version freeze, content-addressed in the repository;
- Stable Diffusion 1.5 fp16 checkpoint source commit, exact local file SHA-256 and exact byte size;
- loopback-only CPU execution;
- deterministic PyTorch mode;
- no custom nodes;
- no API nodes;
- isolated base/input/output/temp/user directories;
- explicit in-memory SQLite database state;
- one infrastructure-approved core workflow and one exact output node.

The dependency evidence freezes exact installed package versions and the freeze file bytes. It does **not** claim individual downloaded wheel artifact hashes are pinned; that stronger supply-chain level remains a possible future hardening step and is not silently implied by this phase.

### Vision

The evidence workflow pins:

- llama.cpp source commit `aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3`;
- a frozen SmolVLM 256M Q8 model file SHA-256 and byte size;
- its frozen multimodal projector SHA-256 and byte size;
- loopback-only offline server execution;
- CPU-only model/projector execution;
- embedded/prebuilt llama.cpp UI disabled at build time;
- one strict production-adapter multimodal request and canonical advisory report parse.

Exact CI run IDs and final closure head are maintained in the PR closure record so updating evidence metadata does not itself move the proven code head.

## Deferred/remaining work

The following are deliberately **not** Phase 21 completion requirements:

- governed ComfyUI `EDIT` workflow using exact frozen inputs and the supported image-upload path;
- repeatable image/vision quality benchmarks before any default workflow/model promotion;
- broader raster formats only if independently validated;
- per-wheel/package artifact hash locking if a stronger external dependency provenance level is required;
- any automatic relationship between vision findings and repair/generation.

## Authority exclusions

Phase 21 components may not:

- complete or verify production Tasks/Goals;
- merge or release;
- sign provenance with protected keys;
- install arbitrary ComfyUI custom nodes or plugins at runtime;
- execute model-generated workflow code;
- download unreviewed model weights as a side effect of an operation;
- treat a backend success response as raster truth;
- treat a vision-model opinion as deterministic verification;
- overwrite existing canonical project assets;
- promote a workflow/model because one example looked good.

## Exit condition

Phase 21 is complete when the repository-side contracts/evidence path is exact-head green and at least one real, pinned generation backend/model path plus one real, pinned vision backend/model path have executed through these boundaries with independently validated evidence. Quality promotion remains a separate measured decision.

The Phase 21 implementation satisfies this condition. Final exact-head replay is recorded in PR #30 before merge.
