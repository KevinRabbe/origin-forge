# Pixelorama real-editor gate

Phase 19 keeps the real Pixelorama integration test opt-in. Normal unit-test CI does not download, install, or trust Pixelorama automatically.

The current target is Pixelorama release tag `v1.2`, whose application runtime reports `v1.2-stable`. The v1.2 source declares Extensions API version `9` and `.pxo` format version `7`.

## Required externally pinned inputs

The real gate requires all five values to be supplied independently of the files under test:

```text
ORIGIN_FORGE_PIXELORAMA_EXECUTABLE=/absolute/path/to/Pixelorama
ORIGIN_FORGE_PIXELORAMA_EXECUTABLE_SHA256=sha256:<64 lowercase hex>
ORIGIN_FORGE_PIXELORAMA_FIXTURE_PXO=/absolute/path/to/fixture.pxo
ORIGIN_FORGE_PIXELORAMA_FIXTURE_SHA256=sha256:<64 lowercase hex>
ORIGIN_FORGE_PIXELORAMA_VERSION=v1.2-stable
```

The integration test must not calculate an expected executable or fixture digest from those same paths and then call that result a trust pin. Production code re-hashes the supplied files and compares them to the externally supplied expected values.

## What the gate proves

The test performs only the documented v0 export surface:

```text
frozen opaque fixture.pxo
        ↓ exact SHA-256 + byte-count check
pinned Pixelorama executable
        ↓ exact executable SHA-256 check
--headless --quit -- --pixelorama-version
        ↓ exact `v1.2-stable` output-line match
--headless --quit -- --spritesheet --output exports/spritesheet.png inputs/source.pxo
        ↓
post-process workspace containment revalidation
        ↓
exact output SHA-256 + bounded RGBA8 PNG validation
```

A successful process exit is not sufficient by itself, and this test does not create Origin Forge Task verification or adopt a canonical project asset.

## Executable acquisition policy

Pixelorama's v1.2 upstream release workflow publishes Linux release archives, including `Pixelorama-Linux-64bit.tar.gz`. Phase 19 does not automatically download that archive in normal CI. A release URL or GitHub origin is provenance information, not an independent expected SHA-256 value.

Before enabling this gate in CI, review and record how the exact executable digest is established. The configured digest should be reviewable and immutable for the gate run.

## Fixture acquisition policy

Prefer a fixture produced by Pixelorama itself. Do not manufacture `.pxo` bytes in Origin Forge.

Two acceptable fixture sources are:

1. a known human-created Pixelorama v1.2 project whose exact digest is reviewed and frozen; or
2. a separately governed Pixelorama API 9 fixture generator that constructs a minimal project through supported editor APIs and asks Pixelorama's own `OpenSave.save_pxo_file(...)` implementation to save it, after which the produced `.pxo` is frozen by digest.

The second option is deliberately separate from the CLI-export proof. It must not be introduced in a way that makes one unproven bridge validate another unproven bridge in the same test.

## Deferred extension bridge

Pixelorama v1.2's Extension API version is `9`. Any future trusted project-create/import/save bridge must pin that API version and its governed extension fingerprint. It may use Pixelorama-owned project APIs and save implementation, but Origin Forge must continue treating `.pxo` serialization as Pixelorama-owned and opaque.
