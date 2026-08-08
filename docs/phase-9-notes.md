# Phase 9 — Governed Skills

Phase 9 adds procedural knowledge to Origin Forge without adding model authority.

A Skill answers:

> What procedure should the bounded Executor follow for this kind of Task?

It does **not** answer:

> What new actions is the Executor allowed to perform?

Tools, sandbox policy, filesystem boundaries, verification, retry limits, Workspace state, and merge authority remain independent deterministic infrastructure.

## Package format

Project-local Skills live under Origin Forge state:

```text
.origin-forge/skills/<skill-name>/
├── SKILL.md
└── skill.toml
```

`SKILL.md` deliberately resembles the small portable core of Agent Skills:

```markdown
---
name: python-debug
description: Diagnose and repair Python failures
---

Inspect the failing path first.
Prefer the smallest evidence-backed change.
Do not bypass tests.
```

Origin Forge governance metadata is separate:

```toml
version = "1.0.0"
keywords = ["python", "debug", "failure"]
capabilities = ["debug"]
```

Phase 9 supports simple single-line `name` and `description` frontmatter only. Full YAML parsing is intentionally not introduced as a dependency.

## Instruction-only boundary

A Phase-9 Skill directory may contain **exactly**:

```text
SKILL.md
skill.toml
```

Any script, executable helper, reference directory, nested package, or unknown file causes validation to fail closed.

This gives Origin Forge the context-efficiency and reusable-procedure benefits of Skills before introducing the much more security-sensitive problem of executable Skill content.

## Deterministic selection

`SkillRegistry` derives evidence only from durable Task state:

```text
Task objective
acceptance criteria
constraints
required capabilities
        ↓
term/capability matching
        ↓
bounded deterministic ranking
        ↓
selected Skills
```

Scoring prioritizes:

1. exact required-capability matches
2. Skill-name matches
3. declared keyword matches
4. description matches

There is no arbitrary fallback Skill when no positive evidence exists.

Explicit selection is also supported by the registry API and remains subject to count/byte limits.

## Progressive disclosure

The Skill catalog exposes compact metadata:

```text
name
description
version
keywords
capabilities
fingerprint
```

Only selected Skill bodies enter model instructions.

The current implementation reads local package files to validate/fingerprint them, but unselected instruction bodies consume no model context.

## Fingerprints and Run identity

Every Skill package is SHA-256 fingerprinted over:

```text
skill.toml + NUL + SKILL.md
```

The Run-facing identity is:

```text
<name>@<version>#<fingerprint-prefix>
```

Example:

```text
python-debug@1.0.0#91ad0b4c2ef8
```

Selected refs are persisted in the existing `runs.skills_json` field.

Artifacts created by that Executor Run also receive the same refs through `skill_versions_json`.

## Captured Skill bundle

When one or more Skills are selected, Origin Forge persists:

```text
.origin-forge/runs/<RUN-ID>/skill-bundle.json
```

The bundle contains the exact metadata, fingerprint, and instructions supplied to that Run.

The causal chain becomes:

```text
CONTEXT_PACKAGE
      ↓
SKILL_BUNDLE
      ↓
MODEL_RESPONSE
      ↓
PATCH_PROPOSAL
```

Without selected Skills, the existing Phase-8 chain remains unchanged:

```text
CONTEXT_PACKAGE
      ↓
MODEL_RESPONSE
      ↓
PATCH_PROPOSAL
```

This is intentional backward compatibility: installing no Skills should not alter the Executor request shape.

## Security model

Skill instructions are trusted project control-plane input, not repository content discovered by the model.

Phase 9 inherits the portable repository-path policy now enforced by the hardened base: serialized repository paths use one host-independent syntax, protected roots are matched case-insensitively, and case-colliding path identities fail closed. Skills cannot bypass that boundary because they only augment bounded instructions; they do not replace repository, patch, or sandbox path validation.

Important boundaries remain:

- `.origin-forge` cannot be targeted by Patch Proposals
- Skills do not grant new tools
- Skills cannot weaken sandbox requirements
- Skills cannot increase retry budgets
- Skills cannot merge or push
- Skills cannot execute code in Phase 9
- selected Skill versions are fingerprinted and captured per Run

A malformed registry fails closed instead of silently dropping bad packages.

## Example lifecycle

```text
Durable Task
    ↓
SkillRegistry catalog
    ↓
deterministic Skill selection
    ↓
Workspace-local source context
    ↓
CONTEXT_PACKAGE
    ↓
SKILL_BUNDLE
    ↓
bounded Executor
    ↓
PATCH_PROPOSAL
    ↓
existing deterministic apply/audit/sandbox pipeline
```

Skills therefore change **procedure**, not **authority**.

## Validation target

Phase-9 regression coverage includes:

- deterministic catalog/fingerprints
- capability-driven selection
- no irrelevant fallback
- explicit-selection budgets
- instruction-only package enforcement
- symlink package rejection
- selected instructions reaching the ModelRequest
- exact Skill refs persisted on the Run
- Skill refs persisted on generated Artifacts
- `SKILL_BUNDLE` causal lineage
- proposal-only Worker source immutability
- no-Skill backward compatibility through the existing suite

## Deferred work

Phase 9 intentionally does not implement:

- executable Skill scripts
- reference subdirectories
- external Skill download/install
- company-wide/shared Skill registries
- cryptographic Skill signatures
- Skill Workshop proposals
- automatic Skill modification
- with-Skill vs without-Skill benchmark evaluation
- Skill promotion or rollback

Those belong after the instruction-only substrate is proven.

The next major intelligence layer should add structural code relationships (symbols, imports/references, and source↔test links) so Skills and bounded model reasoning operate over better selected context rather than simply more context.
