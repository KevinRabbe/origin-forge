# Pixelorama real-editor gate

Phase 19 keeps the real Pixelorama integration test opt-in. Normal unit-test CI does not download, install, or trust Pixelorama automatically.

The current target is Pixelorama release tag `v1.2`, whose application runtime reports `v1.2-stable`. The v1.2 source declares Extensions API version `9` and `.pxo` format version `7`.

## Required externally pinned inputs

The real integration test requires all five values to be supplied independently of the files under test:

```text
ORIGIN_FORGE_PIXELORAMA_EXECUTABLE=/absolute/path/to/Pixelorama
ORIGIN_FORGE_PIXELORAMA_EXECUTABLE_SHA256=sha256:<64 lowercase hex>
ORIGIN_FORGE_PIXELORAMA_FIXTURE_PXO=/absolute/path/to/fixture.pxo
ORIGIN_FORGE_PIXELORAMA_FIXTURE_SHA256=sha256:<64 lowercase hex>
ORIGIN_FORGE_PIXELORAMA_VERSION=v1.2-stable
```

The integration test does not calculate an expected executable or fixture digest from those same paths and call the result a trust pin. Production code re-hashes the supplied files and compares them to externally supplied expected values.

## Frozen Phase-19 evidence profile

The authoritative Phase-19 real-editor gate uses the official Pixelorama v1.2 Windows x64 release archive and a real `.pxo` reproduction project attached by a Pixelorama user to upstream issue #1368.

The reviewed immutable identities are:

```text
Pixelorama release archive:
  Pixelorama-Windows-64bit.zip
  sha256:1ddc65930ddd435612519e293d1927849d4d4c18928a856b5bd4f058fe2f4a72

Extracted Pixelorama.exe:
  sha256:07ee2defdbf14f335b8f102f224926cc1ef1456bd09f3af708e948ccadc3d904

Upstream issue #1368 fixture:
  layers-test.pxo.zip   # attachment contains opaque .pxo bytes
  byte_count: 1906
  sha256:c9d3eb48002d0a68ce718717588b3b43d785171f57dbb85a04e194481cb65fb2

Expected runtime version:
  v1.2-stable
```

Microsoft WinGet's Pixelorama 1.2 package manifest independently pins the exact official Windows x64 release archive SHA-256 above. The workflow refuses the archive before extraction unless it matches that external package-manifest value. The extracted executable and upstream issue fixture are then checked against separately frozen expected hashes committed in the Origin Forge evidence workflow.

The first successful compatibility probe was GitHub Actions real-editor evidence run `31327381822` on Origin Forge head `cf0c2642ccb83e757d361ef74616719265f500b9`. Its observed executable and fixture identities were then frozen in repository code rather than reused dynamically.

The authoritative frozen-pin rerun was GitHub Actions real-editor evidence run `31327454509` on Origin Forge head `eb38cfaca5b11029b281b58145abad227393763c`. Both the acquisition/integrity step and the real Pixelorama CLI integration test completed successfully.

## What the gate proves

The test performs only the documented v0 export surface:

```text
frozen opaque fixture.pxo
        ↓ exact SHA-256 + byte-count check
pinned Pixelorama executable
        ↓ exact executable SHA-256 check
--headless --quit -- --pixelorama-version
        ↓ exact `v1.2-stable` output-line match
Origin Forge derives absolute source/output paths
inside the validated MEDIA-* workspace only
        ↓
--headless --quit -- --spritesheet --output <contained absolute output> <contained absolute source>
        ↓
post-process workspace containment revalidation
        ↓
exact output SHA-256 + bounded RGBA8 PNG validation
```

The request/provenance contract remains workspace-relative. Absolute paths exist only as infrastructure-derived process arguments after containment has been established; the caller cannot provide arbitrary host paths through the request.

A successful process exit is not sufficient by itself, and this test does not create Origin Forge Task verification or adopt a canonical project asset.

## Why process arguments are absolute

Pixelorama v1.2 resolves relative project inputs through its CLI working-directory rules, and its export implementation requires `project.export_directory_path` to be an absolute directory. A real-editor probe showed that passing `exports/spritesheet.png` directly can exit successfully without writing the requested workspace export.

Origin Forge therefore keeps request paths portable and relative, resolves them inside the isolated workspace, validates the source plus output parent containment, and only then passes the resulting absolute contained paths to Pixelorama. After the editor exits, Origin Forge revalidates workspace roots/path components and requires the declared output leaf to exist before hashing or raster inspection.

## Executable acquisition policy

Normal CI never downloads Pixelorama. The opt-in evidence workflow downloads only the fixed official v1.2 Windows x64 release URL and checks it against the externally anchored WinGet SHA-256 before extraction.

A release URL or GitHub origin by itself is provenance information, not an integrity proof. Any future platform/profile must add its own reviewable immutable acquisition trust anchor and frozen executable identity before it can become authoritative evidence.

## Fixture acquisition policy

Do not manufacture `.pxo` bytes in Origin Forge.

The Phase-19 proof uses the real `layers-test.pxo` project attached to upstream Pixelorama issue #1368, frozen by exact byte count and SHA-256. The attachment was named `layers-test.pxo.zip` because GitHub's issue attachment surface required an allowed extension; the downloaded bytes are treated as opaque Pixelorama project bytes and saved locally as `.pxo`.

A future fixture may instead come from a separately governed Pixelorama API 9 fixture generator that constructs a minimal project through supported editor APIs and asks Pixelorama's own `OpenSave.save_pxo_file(...)` implementation to save it. Such a generator must remain separate from the CLI-export proof so two unproven bridges do not validate each other in one test.

## Evidence workflow policy

`.github/workflows/pixelorama-real-editor-evidence.yml` is deliberately opt-in. It runs for PR #28 only while the PR body contains the explicit marker:

```text
<!-- phase19-real-editor-evidence -->
```

This keeps ordinary push/PR unit-test CI free of editor downloads. The marker is an evidence-run control, not production authority. Once Phase 19 closure evidence is recorded, the marker can be removed without changing branch content.

## Deferred extension bridge

Pixelorama v1.2's Extension API version is `9`. Any future trusted project-create/import/save bridge must pin that API version and its governed extension fingerprint. It may use Pixelorama-owned project APIs and save implementation, but Origin Forge must continue treating `.pxo` serialization as Pixelorama-owned and opaque.
