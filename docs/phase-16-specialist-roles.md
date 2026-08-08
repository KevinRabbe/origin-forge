# Phase 16 — Isolated Specialist Roles

Status: **DONE — Reviewer-first implementation complete; additional specialist roles remain evidence-gated**

Phase 16 adds a small number of isolated specialist model roles that can improve review, research, testing strategy, and later visual critique without creating an uncontrolled agent swarm or weakening Origin Forge's existing deterministic authority boundaries.

The central distinction is:

```text
model capability role != agent authority role
```

A `coder_strong` model profile may serve an Executor or a Reviewer. The model profile describes resource/capability selection. The specialist contract describes what the model is allowed to see, produce, and influence.

---

## 1. Architectural goal

Existing production authority remains:

```text
Task
  ↓
Executor proposal
  ↓
deterministic apply
  ↓
deterministic Workspace Auditor
  ↓
sandbox verification
  ↓
verified Task state
```

Phase 16 adds isolated advisory evidence beside that chain:

```text
frozen verified/proposal evidence
        ↓
fresh Specialist Run
        ↓
strict specialist report
        ↓
structural report validation
        ↓
content-addressed evidence artifact
        ↓
Manager / human / later benchmark gate
```

A specialist can identify risk, missing evidence, research questions, test scenarios, or visual concerns. It cannot repair production files, mark a Task complete, override deterministic audit/tests, or promote its own recommendation.

---

## 2. Initial specialist roles

### 2.1 Reviewer — first implementation target

The Reviewer inspects a frozen bounded package containing the Task contract plus selected implementation/diff/audit/test evidence.

It may report:

- requirement gaps
- likely regressions
- suspicious assumptions
- missing test coverage
- API/compatibility risks
- evidence inconsistencies
- maintainability concerns

It does not:

- edit files
- apply patches
- run arbitrary commands
- change Workspace status
- change Task/Flow/Goal status
- declare PASS/FAIL authority

Deterministic Workspace audit and sandbox verification remain higher-authority correctness evidence.

### 2.2 Researcher — later in Phase 16

The Researcher answers a bounded question from supplied trusted evidence/references. Initial Phase-16 Researcher work should remain read-only and should not invent a new arbitrary-network authority path.

Its output is cited evidence plus uncertainty, not a project Decision.

### 2.3 Test Planner — later in Phase 16

The Test Planner proposes scenarios, edge cases, invariants, and missing verification targets. It does not write tests or execute commands directly. Any resulting code change becomes a normal bounded Task for an Executor; execution remains in the sandbox verifier.

### 2.4 Visual Critic — deferred until visual media exists

Visual critique belongs here architecturally but should not be implemented before the image/runtime-observation phases provide real visual evidence.

---

## 3. Explicit non-goal: agent swarm

Phase 16 does not introduce:

- autonomous peer-to-peer agent messaging
- recursive delegation
- specialist-created specialists
- voting among many agents
- hidden debate loops
- persistent specialist chat sessions
- specialist-owned Tasks/Goals
- parallel GPU model swarms

The default is one fresh bounded specialist Run for one explicit contract.

---

## 4. Specialist authority contract

Every specialist invocation uses an immutable contract:

```text
SpecialistContract
- contract_id
- role
- parent_task_id
- objective
- evidence_refs[]
- acceptance_questions[]
- max_evidence_bytes
- max_report_bytes
- max_model_calls
- max_input_tokens
- max_output_tokens
- content_hash
```

The contract contains no write permission and no tool-capability escalation field.

Agent authority roles are independent from `ModelRole` in Phase 14. A specialist may use an existing governed model profile selected by an explicit scheduling policy, but changing agent role does not grant a different model or more resources implicitly.

---

## 5. Frozen specialist evidence

A specialist receives a reconstructable bounded evidence package, not mutable live project state.

Initial Reviewer evidence may include exact hashed references to:

- Task record / acceptance criteria
- Executor PatchProposal artifact
- Workspace diff evidence
- deterministic Workspace audit Verification
- sandbox Verification evidence
- selected source snapshots when required
- relevant Decisions / Skills / context metadata

Every evidence item has an infrastructure-owned ID/type/hash and bounded canonical payload.

If evidence changes after the contract is created, the invocation fails or is marked stale rather than silently reviewing a different state.

---

## 6. Fresh context

Each specialist Run starts with a fresh context containing only:

- specialist instructions
- immutable contract
- bounded frozen evidence
- role-specific output schema

It does not inherit Executor scratch reasoning or hidden chain-of-thought.

This preserves independent review rather than asking the same context to critique itself.

---

## 7. Reviewer report

The first report schema should be small and evidence-centric:

```text
ReviewerReport
- report_id
- contract_id/hash
- model_id/hash
- findings[]
- overall_risk
- content_hash

ReviewerFinding
- finding_id
- severity
- category
- summary
- evidence_ref_ids[]
- recommendation
```

Initial severity values:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Initial categories:

```text
REQUIREMENT_GAP
REGRESSION_RISK
TEST_GAP
COMPATIBILITY
SECURITY
MAINTAINABILITY
EVIDENCE_CONFLICT
OTHER
```

The report may say “no findings,” but it cannot say the Task is verified or complete.

---

## 8. Structural specialist auditor

Model output is parsed and structurally audited independently.

The auditor checks:

- report matches the exact contract/hash
- every cited evidence ID exists in the frozen package
- no unknown/duplicate refs
- severity/category enums are valid
- report/count/byte budgets are obeyed
- model did not emit forbidden fields such as patch/apply/verification commands
- stored report hash matches canonical bytes

Structural audit does not prove a semantic finding is correct.

---

## 9. Persistence and provenance

Specialist contracts and reports are immutable derived evidence.

Suggested protected location:

```text
.origin-forge/specialists/
├── contracts/
└── reports/
```

Every model-backed Specialist Run records:

- specialist role
- contract ID/hash
- evidence snapshot hash
- model profile/model ID/model hash
- context hash
- response hash
- input/output tokens
- report ID/hash
- finding counts by severity/category
- elapsed/resource metrics when available

A structural-capture Verification may record that this exact report was produced and validated. That Verification does **not** mean the report's semantic recommendations are accepted.

---

## 10. Integration with production orchestration

Phase 16 should begin as an optional explicit layer, not silently change the Phase-6 production loop.

Initial integration options:

```text
Task verified
→ optional Reviewer contract
→ Reviewer report
→ human/Manager inspection
```

or, for selected experiments:

```text
Workspace audited + sandbox verified
→ Reviewer
→ if HIGH/CRITICAL evidence-backed finding:
     create/route a new bounded repair Task
  else:
     preserve report as supplementary evidence
```

The Reviewer itself never repairs the issue.

No production Task should fail solely because a model Reviewer emitted an unsupported opinion. Promotion of specialist findings into blocking policy requires measured benchmark evidence and a later explicit policy change.

---

## 11. Model/resource scheduling

Specialists reuse Phase-14 scheduling.

Rules:

- no new privileged model-loader path
- explicit model profile/policy selection
- specialist Run holds normal resource leases
- no implicit fallback model
- production work may outrank optional specialist work
- resource contention is visible and bounded

`ModelRole` remains a model capability/resource classification. Phase-16 `SpecialistRole` is an authority/output-contract classification.

---

## 12. Evaluation requirement

Phase 16 exits only if specialist isolation is measurably useful.

Reviewer evaluation should use paired replay cases where possible:

```text
baseline: deterministic pipeline evidence only
variant:  baseline + isolated Reviewer report
```

Measure at least:

- true issue detection
- false-positive rate
- missed critical issues
- downstream repair success
- extra model calls/tokens/time
- context bytes
- model/resource cost

A Reviewer that produces verbose low-value findings should not become a default production gate.

Initial implementation can persist cases/reports before automatic orchestration integration, but Phase-16 completion requires a repeatable evaluation protocol.

---

## 13. Security rules

Specialist model text is untrusted.

A specialist cannot:

- request arbitrary host commands
- request new permissions
- alter its contract
- alter evidence refs
- access protected company keys
- modify project source or `.origin-forge` authority records
- alter active Skills/policies
- invoke merge/release actions
- mark a Task/Goal/Flow verified
- create its own follow-up specialist Run

Any recommendation requiring mutation is routed back into a normal governed Task/Decision/evaluation path.

---

## 14. First implementation slice

Phase 16 v0 should implement only:

1. `SpecialistRole` and immutable `SpecialistContract`
2. exact bounded `SpecialistEvidenceRef` / frozen evidence package
3. Reviewer response schema and parser
4. model-backed `IsolatedReviewer` using normal `ModelAdapter`
5. structural Reviewer report auditor
6. immutable protected specialist persistence
7. Run-level observability/provenance
8. read-only `specialist status/list/show` operator inspection
9. tests proving no patch/apply/status-transition authority
10. repeatable Reviewer evaluation protocol before default orchestration integration

Researcher/Test Planner should follow only after the Reviewer substrate is stable.

---

## 15. Acceptance tests

### Isolation

- Reviewer receives a fresh bounded package, not Executor scratch context
- Reviewer cannot modify source/Workspace/Task state
- Reviewer cannot invoke patch/apply/sandbox/merge operations
- Reviewer cannot promote its own findings

### Frozen evidence

- every report ref must match the exact frozen contract evidence
- changed/missing evidence invalidates replay or report binding
- evidence/report byte and count limits fail closed

### Model containment

- normal `ModelAdapter` contract is required
- strict JSON response schema
- extra/forbidden fields fail closed
- missing/overflowing token accounting fails closed when token budgets are enforced
- model cannot choose permissions, authority, or verification status

### Report integrity

- immutable content hash
- no duplicate finding IDs/evidence IDs
- severity/category are infrastructure enums
- report tampering is detected on load

### Authority

- deterministic audit/tests remain higher-authority than specialist opinion
- Reviewer report alone cannot complete/fail a production Task
- repair requires a separate governed Task/Executor path

### Observability

- contract/evidence/model/context/response/report hashes are reconstructable
- model/resource profile and token metrics are recorded
- inspection is read-only

### Measured value

- paired Reviewer evaluation is repeatable
- true/false-positive metrics are available
- default integration is not enabled until measured benefit justifies it

---

## 16. Exit condition

Phase 16 exits when:

> Origin Forge can invoke a fresh isolated specialist—starting with Reviewer—over exact bounded evidence, persist and structurally audit a provenance-rich advisory report, prove that the specialist has no production mutation or verification authority, and measure whether adding that specialist improves outcomes enough to justify controlled integration.

The result should preserve the core architecture:

```text
specialist insight = evidence
infrastructure verification = authority
```
