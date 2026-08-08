# Phase 11 current-main revalidation

This documentation-only commit exists to force the Phase-11 pull-request merge ref and hosted test matrix to be rebuilt against the current `main` after Phase 12 (governed Skill evaluation) and Phase 13 (Tool Search/progressive disclosure) were merged.

The first current-main revalidation exposed a Phase-13 packaging omission: the finalized Phase-13 merge contained callers/tests for `origin_forge.tool_search` but not the module itself. PR #23 restored that bounded Tool Search session and passed the complete Python 3.12 + 3.13 matrix before merging into `main` at `a5354882acc04ae0743ff23290ad8e54a6619e82`.

That revalidation also exposed two Phase-11 issues, both now fixed on this branch:

- semantic query-token expectations now match the deterministic camel-case tokenizer (`WidgetParser` → `widget`, `parser`)
- sandboxed LSP source validation now accepts only direct canonical `.origin-forge/workspaces/<WSPACE-ID>` roots, rejecting live/arbitrary/nested/symlink-alias paths before any Podman/image probe

The later layers do not replace Phase-11 code-intelligence authority boundaries. The intended combined stack is:

```text
Phase 10 snapshot-local context
→ Phase 11 read-only code intelligence / sandboxed LSP
→ Phase 12 governed Skill evaluation evidence
→ Phase 13 authority-filtered Tool Search
```

Phase 11 remains read-only evidence infrastructure. It grants no Tool Search invocation authority, Skill promotion authority, arbitrary process execution, native-host LSP execution, or merge authority.

Only the fresh Python 3.12 + 3.13 pull-request matrix produced from this final head against the repaired current `main` counts as the Phase-11 merge gate.
