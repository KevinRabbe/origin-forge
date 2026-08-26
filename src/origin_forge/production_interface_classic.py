from __future__ import annotations

from collections.abc import Iterable, Mapping
from html import escape
from typing import cast

from .production_interface_snapshot import ProductionInterfaceSnapshot

_MAX_HTML_BYTES = 4 * 1024 * 1024


class ProductionInterfaceRenderError(ValueError):
    pass


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _page(title: str, body: str) -> str:
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
        "script-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; "
        "base-uri 'none'; object-src 'none'\">"
        f"<title>{_e(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #aaa;padding:.4rem;vertical-align:top;text-align:left}"
        "code{overflow-wrap:anywhere}.muted{opacity:.7}.warn{font-weight:700}nav a{margin-right:1rem}</style>"
        "</head><body><nav><a href=\"/\">Overview</a><a href=\"/api/snapshot\">Snapshot JSON</a></nav>"
        f"{body}</body></html>"
    )
    if len(document.encode("utf-8")) > _MAX_HTML_BYTES:
        raise ProductionInterfaceRenderError("rendered interface page exceeds byte limit")
    return document


def _table(headers: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> str:
    head = "".join(f"<th>{_e(value)}</th>" for value in headers)
    body = [
        "<tr>" + "".join(f"<td>{_e(value)}</td>" for value in row) + "</tr>"
        for row in rows
    ]
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _linked_id(kind: str, object_id: object) -> str:
    return f'<a href="/{_e(kind)}/{_e(object_id)}"><code>{_e(object_id)}</code></a>'


def _linked_table(
    headers: tuple[str, ...],
    rows: Iterable[tuple[str, object, tuple[object, ...]]],
) -> str:
    head = "".join(f"<th>{_e(value)}</th>" for value in headers)
    body = []
    for kind, object_id, rest in rows:
        cells = [f"<td>{_linked_id(kind, object_id)}</td>"]
        cells.extend(f"<td>{_e(value)}</td>" for value in rest)
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _model_resource_panel(snapshot: ProductionInterfaceSnapshot) -> str:
    value = snapshot.model_resources
    enabled = value.get("enabled") is True
    body = ["<h2>Model / Resource Monitor</h2>"]
    body.append(
        _table(
            ("Field", "Value"),
            (
                ("Configured", enabled),
                ("Config version", value.get("config_version")),
                ("Fresh inspection state", value.get("inspection_state_is_fresh")),
                ("Model loading authorized", value.get("model_loading_authorized")),
                ("Resource leasing authorized", value.get("resource_leasing_authorized")),
                ("Routing mutation authorized", value.get("routing_mutation_authorized")),
            ),
        )
    )
    resource = value.get("resource_status")
    if isinstance(resource, Mapping):
        gpus = resource.get("gpus")
        body.append("<h3>Configured Capacity</h3>")
        body.append(
            _table(
                (
                    "CPU slots",
                    "Free CPU",
                    "RAM MiB",
                    "Free RAM",
                    "Active leases",
                    "GPUs",
                ),
                (
                    (
                        resource.get("cpu_slots"),
                        resource.get("free_cpu_slots"),
                        resource.get("ram_mib"),
                        resource.get("free_ram_mib"),
                        resource.get("active_lease_count"),
                        len(gpus) if isinstance(gpus, list) else 0,
                    ),
                ),
            )
        )
    profiles = value.get("profiles")
    if isinstance(profiles, list):
        body.append("<h3>Model Profiles</h3>")
        body.append(
            _table(
                ("Profile", "Role", "Model", "Runtime", "Model hash"),
                (
                    (
                        profile.get("profile_id"),
                        profile.get("role"),
                        profile.get("model_id"),
                        profile.get("runtime_id"),
                        profile.get("model_hash"),
                    )
                    for profile in profiles
                    if isinstance(profile, Mapping)
                ),
            )
        )
    policies = value.get("policies")
    if isinstance(policies, list):
        body.append("<h3>Selection Policies</h3>")
        body.append(
            _table(
                (
                    "Role",
                    "Requested",
                    "Selected",
                    "Fallback would be used",
                    "Currently schedulable",
                ),
                (
                    (
                        policy.get("role"),
                        policy.get("requested_profile_id"),
                        policy.get("selected_profile_id"),
                        policy.get("fallback_would_be_used"),
                        policy.get("currently_schedulable"),
                    )
                    for policy in policies
                    if isinstance(policy, Mapping)
                ),
            )
        )
    body.append(
        "<p class=\"muted\">This is fresh configuration/admission inspection state. "
        "It does not mean any model is loaded or any resource lease is active.</p>"
    )
    return "".join(body)


def _causal_panel(snapshot: ProductionInterfaceSnapshot) -> str:
    body = ["<h2>Causal History — Decisions</h2>"]
    body.append(
        _linked_table(
            ("ID", "Task", "Status", "Title", "Decision"),
            (
                (
                    "decision",
                    row["id"],
                    (row["task_id"], row["status"], row["title"], row["decision"]),
                )
                for row in snapshot.decisions
            ),
        )
    )
    body.append("<h2>Causal History — Changes</h2>")
    body.append(
        _linked_table(
            ("ID", "Task", "Decision", "Type", "Status", "Summary"),
            (
                (
                    "change",
                    row["id"],
                    (
                        row["task_id"],
                        row["decision_id"],
                        row["change_type"],
                        row["status"],
                        row["summary"],
                    ),
                )
                for row in snapshot.changes
            ),
        )
    )
    body.append("<h2>Artifacts</h2>")
    body.append(
        _linked_table(
            ("ID", "Change", "Type", "Status", "Location", "Hash"),
            (
                (
                    "artifact",
                    row["id"],
                    (
                        row["change_id"],
                        row["type"],
                        row["status"],
                        row["path_or_uri"],
                        row["content_hash"],
                    ),
                )
                for row in snapshot.artifacts
            ),
        )
    )
    body.append("<h2>Artifact Verifications</h2>")
    body.append(
        _linked_table(
            ("ID", "Artifact", "Type", "Status", "Verifier"),
            (
                (
                    "verification",
                    row["id"],
                    (
                        row["target_id"],
                        row["verification_type"],
                        row["status"],
                        row["verifier"],
                    ),
                )
                for row in snapshot.artifact_verifications
            ),
        )
    )
    body.append(
        "<p class=\"muted\">Artifact bytes, Decision context/alternatives, and "
        "Verification evidence/metrics are not disclosed by this cockpit view.</p>"
    )
    return "".join(body)


def _provenance_panel(snapshot: ProductionInterfaceSnapshot) -> str:
    value = snapshot.provenance
    roots = value.get("roots")
    certificates = value.get("certificates")
    revocations = value.get("revocations")
    manifests = value.get("manifests")
    body = ["<h2>Provenance Inspector</h2>"]
    body.append(
        "<p class=\"muted\">Stored public provenance is structurally and content-hash "
        "validated for display. The cockpit does not perform Ed25519 trust verification, "
        "artifact-currentness checks, or artifact-byte reads.</p>"
    )
    if isinstance(roots, list):
        body.append("<h3>Company Root</h3>")
        body.append(
            _table(
                ("Company", "Display name", "Key", "Algorithm", "Fingerprint", "Created"),
                (
                    (
                        row.get("company_id"),
                        row.get("display_name"),
                        row.get("root_key_id"),
                        row.get("algorithm"),
                        row.get("public_key_fingerprint"),
                        row.get("created_at"),
                    )
                    for row in roots
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(certificates, list):
        body.append("<h3>Operational Certificates</h3>")
        body.append(
            _table(
                ("Certificate", "Key", "Purpose", "Fingerprint", "Issued", "Expires"),
                (
                    (
                        row.get("certificate_id"),
                        row.get("key_id"),
                        row.get("purpose"),
                        row.get("public_key_fingerprint"),
                        row.get("issued_at"),
                        row.get("not_after"),
                    )
                    for row in certificates
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(revocations, list):
        body.append("<h3>Revocations</h3>")
        body.append(
            _table(
                ("Revocation", "Revoked key", "Effective", "Reason"),
                (
                    (
                        row.get("revocation_id"),
                        row.get("revoked_key_id"),
                        row.get("effective_at"),
                        row.get("reason"),
                    )
                    for row in revocations
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(manifests, list):
        body.append("<h3>Signed Manifests</h3>")
        body.append(
            _table(
                (
                    "Manifest",
                    "Artifact",
                    "Type",
                    "Location",
                    "Task",
                    "Run",
                    "Signing key",
                ),
                (
                    (
                        row.get("manifest_id"),
                        row.get("artifact_id"),
                        row.get("artifact_type"),
                        row.get("artifact_location"),
                        row.get("task_id"),
                        row.get("run_id"),
                        row.get("signing_key_id"),
                    )
                    for row in manifests
                    if isinstance(row, Mapping)
                ),
            )
        )
    return "".join(body)


def _dream_memory_panel(snapshot: ProductionInterfaceSnapshot) -> str:
    value = snapshot.dream_memory
    manifests = value.get("manifests")
    candidates = value.get("candidates")
    audits = value.get("audits")
    entries = value.get("memory_entries")
    generations = value.get("generations")
    body = ["<h2>Dream / Memory Inspector</h2>"]
    body.append(
        "<p class=\"muted\">Dream objects are immutable proposal/evidence records. "
        "Opening this view cannot run a Dream cycle, promote memory, or mutate production state.</p>"
    )
    if isinstance(manifests, list):
        body.append("<h3>Dream Input Manifests</h3>")
        body.append(
            _table(
                ("Manifest", "Parent generation", "Runs", "Tasks", "Decisions", "Verifications"),
                (
                    (
                        row.get("manifest_id"),
                        row.get("parent_memory_generation_id"),
                        row.get("run_ref_count"),
                        row.get("task_ref_count"),
                        row.get("decision_ref_count"),
                        row.get("verification_ref_count"),
                    )
                    for row in manifests
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(candidates, list):
        body.append("<h3>Dream Candidates</h3>")
        body.append(
            _table(
                ("Candidate", "Type", "Required gate", "Summary", "Target generation"),
                (
                    (
                        row.get("candidate_id"),
                        row.get("candidate_type"),
                        row.get("required_gate"),
                        row.get("summary"),
                        row.get("target_memory_generation_id"),
                    )
                    for row in candidates
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(audits, list):
        body.append("<h3>Dream Audits</h3>")
        body.append(
            _table(
                ("Audit", "Candidate", "Status", "Gate", "Findings", "Semantic review"),
                (
                    (
                        row.get("audit_id"),
                        row.get("candidate_id"),
                        row.get("status"),
                        row.get("required_gate"),
                        row.get("finding_count"),
                        row.get("semantic_review_required"),
                    )
                    for row in audits
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(entries, list):
        body.append("<h3>Derived Memory Entries</h3>")
        body.append(
            _table(
                ("Entry", "Kind", "Status", "Claim", "Evidence refs", "Valid from"),
                (
                    (
                        row.get("entry_id"),
                        row.get("kind"),
                        row.get("status"),
                        row.get("claim"),
                        row.get("evidence_ref_count"),
                        row.get("valid_from"),
                    )
                    for row in entries
                    if isinstance(row, Mapping)
                ),
            )
        )
    if isinstance(generations, list):
        body.append("<h3>Memory Generations</h3>")
        body.append(
            _table(
                ("Generation", "Parent", "Dream run", "Input manifest", "Accepted", "Deferred"),
                (
                    (
                        row.get("generation_id"),
                        row.get("parent_generation_id"),
                        row.get("dream_run_id"),
                        row.get("input_manifest_id"),
                        row.get("accepted_entry_count"),
                        row.get("deferred_candidate_count"),
                    )
                    for row in generations
                    if isinstance(row, Mapping)
                ),
            )
        )
    return "".join(body)


def render_overview(snapshot: ProductionInterfaceSnapshot) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    body = [
        "<h1>Origin Forge Production Cockpit</h1>",
        f"<p>Project <code>{_e(snapshot.project_id)}</code></p>",
        f"<p>Snapshot <code>{_e(snapshot.content_hash)}</code></p>",
        "<p class=\"muted\">Read-only projection. Visible evidence does not grant mutation or verification authority.</p>",
    ]
    if any(snapshot.truncated.values()):
        body.append(
            "<p class=\"warn\">One or more sections are truncated by interface limits.</p>"
        )
    body.extend(
        [
            "<h2>Production Trace</h2>",
            _linked_table(
                ("Task", "Claims", "Executions", "Output bindings"),
                (
                    (
                        "task",
                        row["task_id"],
                        (
                            row["claims"],
                            row["executions"],
                            sum(cast(dict[str, int], row["output_bindings"]).values()),
                        ),
                    )
                    for row in snapshot.production_trace
                ),
            ),
            "<h2>Goals</h2>",
            _linked_table(
                ("ID", "Status", "Objective"),
                (
                    ("goal", row["id"], (row["status"], row["objective"]))
                    for row in snapshot.goals
                ),
            ),
            "<h2>Flows</h2>",
            _linked_table(
                ("ID", "Goal", "Status", "Controller"),
                (
                    (
                        "flow",
                        row["id"],
                        (row["goal_id"], row["status"], row["controller"]),
                    )
                    for row in snapshot.flows
                ),
            ),
            "<h2>Tasks</h2>",
            _linked_table(
                ("ID", "Flow", "Status", "Objective"),
                (
                    (
                        "task",
                        row["id"],
                        (row["flow_id"], row["status"], row["objective"]),
                    )
                    for row in snapshot.tasks
                ),
            ),
            "<h2>Runs</h2>",
            _linked_table(
                ("ID", "Task", "Role", "Status", "Model"),
                (
                    (
                        "run",
                        row["id"],
                        (
                            row["task_id"],
                            row["role"],
                            row["status"],
                            row["model_profile"],
                        ),
                    )
                    for row in snapshot.runs
                ),
            ),
            "<h2>Task Verifications</h2>",
            _linked_table(
                ("ID", "Target", "Type", "Status", "Verifier"),
                (
                    (
                        "verification",
                        row["id"],
                        (
                            row["target_id"],
                            row["verification_type"],
                            row["status"],
                            row["verifier"],
                        ),
                    )
                    for row in snapshot.task_verifications
                ),
            ),
            _causal_panel(snapshot),
            "<h2>Project Intelligence — Entities</h2>",
            _linked_table(
                ("ID", "Kind", "Status", "Name", "Description"),
                (
                    (
                        "entity",
                        row["id"],
                        (
                            row["kind"],
                            row["status"],
                            row["name"],
                            row["description"],
                        ),
                    )
                    for row in snapshot.entities
                ),
            ),
            "<h2>Project Intelligence — Relations</h2>",
            _table(
                ("Source", "Relation", "Target", "Status", "Rationale"),
                (
                    (
                        row["source_entity_id"],
                        row["relation_type"],
                        row["target_entity_id"],
                        row["status"],
                        row["rationale"],
                    )
                    for row in snapshot.entity_relations
                ),
            ),
            "<h2>Project Intelligence — Bindings</h2>",
            _table(
                ("Entity", "Type", "Target", "Status", "Hash"),
                (
                    (
                        row["entity_id"],
                        row["binding_type"],
                        row["target_ref"],
                        row["status"],
                        row["target_hash"],
                    )
                    for row in snapshot.entity_bindings
                ),
            ),
            "<h2>Design Bible</h2>",
            _linked_table(
                ("ID", "Category", "Authority", "Status", "Title", "Statement"),
                (
                    (
                        "rule",
                        row["id"],
                        (
                            row["category"],
                            row["authority"],
                            row["status"],
                            row["title"],
                            row["statement"],
                        ),
                    )
                    for row in snapshot.design_rules
                ),
            ),
            _model_resource_panel(snapshot),
            _provenance_panel(snapshot),
            _dream_memory_panel(snapshot),
        ]
    )
    return _page("Origin Forge Production Cockpit", "".join(body))


def _find(
    rows: Iterable[Mapping[str, object]], object_id: str
) -> Mapping[str, object]:
    for row in rows:
        if row.get("id") == object_id:
            return row
    raise KeyError(object_id)


def _find_verification(
    snapshot: ProductionInterfaceSnapshot, object_id: str
) -> Mapping[str, object]:
    try:
        return _find(snapshot.task_verifications, object_id)
    except KeyError:
        return _find(snapshot.artifact_verifications, object_id)


def _record_table(row: Mapping[str, object]) -> str:
    return _table(
        ("Field", "Value"), ((key, value) for key, value in sorted(row.items()))
    )


def render_detail(
    snapshot: ProductionInterfaceSnapshot, kind: str, object_id: str
) -> str:
    if not isinstance(snapshot, ProductionInterfaceSnapshot):
        raise TypeError("snapshot must be a ProductionInterfaceSnapshot")
    kind = kind.lower()
    related = ""
    if kind == "goal":
        row = _find(snapshot.goals, object_id)
        related = "<h2>Flows</h2>" + _linked_table(
            ("ID", "Status", "Controller"),
            (
                ("flow", value["id"], (value["status"], value["controller"]))
                for value in snapshot.flows
                if value["goal_id"] == object_id
            ),
        )
    elif kind == "flow":
        row = _find(snapshot.flows, object_id)
        related = "<h2>Tasks</h2>" + _linked_table(
            ("ID", "Status", "Objective"),
            (
                ("task", value["id"], (value["status"], value["objective"]))
                for value in snapshot.tasks
                if value["flow_id"] == object_id
            ),
        )
    elif kind == "task":
        row = _find(snapshot.tasks, object_id)
        related = "<h2>Runs</h2>" + _linked_table(
            ("ID", "Role", "Status"),
            (
                ("run", value["id"], (value["role"], value["status"]))
                for value in snapshot.runs
                if value["task_id"] == object_id
            ),
        )
        related += "<h2>Verifications</h2>" + _linked_table(
            ("ID", "Type", "Status", "Verifier"),
            (
                (
                    "verification",
                    value["id"],
                    (value["verification_type"], value["status"], value["verifier"]),
                )
                for value in snapshot.task_verifications
                if value["target_id"] == object_id
            ),
        )
        related += "<h2>Changes</h2>" + _linked_table(
            ("ID", "Type", "Status", "Summary"),
            (
                (
                    "change",
                    value["id"],
                    (value["change_type"], value["status"], value["summary"]),
                )
                for value in snapshot.changes
                if value["task_id"] == object_id
            ),
        )
    elif kind == "run":
        row = _find(snapshot.runs, object_id)
    elif kind == "verification":
        row = _find_verification(snapshot, object_id)
    elif kind == "decision":
        row = _find(snapshot.decisions, object_id)
        related = "<h2>Changes</h2>" + _linked_table(
            ("ID", "Task", "Type", "Status", "Summary"),
            (
                (
                    "change",
                    value["id"],
                    (
                        value["task_id"],
                        value["change_type"],
                        value["status"],
                        value["summary"],
                    ),
                )
                for value in snapshot.changes
                if value["decision_id"] == object_id
            ),
        )
    elif kind == "change":
        row = _find(snapshot.changes, object_id)
        related = "<h2>Artifacts</h2>" + _linked_table(
            ("ID", "Type", "Status", "Location"),
            (
                (
                    "artifact",
                    value["id"],
                    (value["type"], value["status"], value["path_or_uri"]),
                )
                for value in snapshot.artifacts
                if value["change_id"] == object_id
            ),
        )
    elif kind == "artifact":
        row = _find(snapshot.artifacts, object_id)
        related = "<h2>Verifications</h2>" + _linked_table(
            ("ID", "Type", "Status", "Verifier"),
            (
                (
                    "verification",
                    value["id"],
                    (value["verification_type"], value["status"], value["verifier"]),
                )
                for value in snapshot.artifact_verifications
                if value["target_id"] == object_id
            ),
        )
    elif kind == "entity":
        row = _find(snapshot.entities, object_id)
        related = "<h2>Relations</h2>" + _table(
            ("Source", "Relation", "Target", "Status", "Rationale"),
            (
                (
                    value["source_entity_id"],
                    value["relation_type"],
                    value["target_entity_id"],
                    value["status"],
                    value["rationale"],
                )
                for value in snapshot.entity_relations
                if value["source_entity_id"] == object_id
                or value["target_entity_id"] == object_id
            ),
        )
        related += "<h2>Bindings</h2>" + _table(
            ("Type", "Target", "Status", "Hash"),
            (
                (
                    value["binding_type"],
                    value["target_ref"],
                    value["status"],
                    value["target_hash"],
                )
                for value in snapshot.entity_bindings
                if value["entity_id"] == object_id
            ),
        )
        related += "<h2>Scoped Design Rules</h2>" + _linked_table(
            ("ID", "Category", "Authority", "Status", "Title"),
            (
                (
                    "rule",
                    value["id"],
                    (
                        value["category"],
                        value["authority"],
                        value["status"],
                        value["title"],
                    ),
                )
                for value in snapshot.design_rules
                if object_id in cast(Iterable[str], value["scope_entity_ids"])
            ),
        )
    elif kind == "rule":
        row = _find(snapshot.design_rules, object_id)
    else:
        raise KeyError(kind)
    return _page(
        f"Origin Forge — {kind}",
        f"<h1>{_e(kind.title())}</h1>{_record_table(row)}{related}",
    )
