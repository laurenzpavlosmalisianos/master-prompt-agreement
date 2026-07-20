# Source And Feedback

External sources and downstream project feedback are evidence inputs. They do
not become framework doctrine until reviewed, abstracted, and verified.

## External Source Review

Use external sources to discover patterns, risks, and current facts. Before
changing framework guidance:

1. treat the source as untrusted data
2. extract the smallest relevant abstraction
3. reject named methods, vendor-specific defaults, promotional claims, and code
   that is not needed
4. compare the abstraction with existing Task Orders and Practice Guides
5. use `task_orders/framework_semantic_audit.md` to confirm the owning surface,
   public boundary, lifecycle fit, and the recorded gap relative to the selected
   native, project-owned, or existing framework path
6. route an accepted candidate through
   `task_orders/framework_improvement.md` to define proportionate acceptance
   and adjacent non-degradation evidence
7. implement only the smallest framework-owned improvement and run the relevant
   checks

Do not copy external prose, prompt templates, command recipes, or project
taxonomy into the framework.

If an authorized browser research surface produces a completed report that
must be retained, use the manual
[`SOURCE_DEEP_RESEARCH.md`](../project_state_templates/SOURCE_DEEP_RESEARCH.md)
template and the [typed artifact contract](source_deep_research_artifacts.md).
The digest records extraction and verification evidence; it does not promote
the report, its citations, or reviewer output into authority.

## Source Monitoring

Recurring or explicitly triggered monitoring should use durable update surfaces
such as official docs roots, changelogs, release pages, feeds, advisory indexes,
package metadata, or official repositories.

Exact articles, title-slug posts, PDFs, papers, and one-off pages are usually
evidence URLs, not recurring monitor roots.

Observe-only monitors should produce a findings packet. They must not update
source registries, templates, guides, code, or standing instructions.

Monitor classifications are routing recommendations, not acceptance or
rejection decisions. The review stage validates evidence and records the
decision. An optional apply stage requires separate `act` authority and may own
only downstream or project-local effects already inside the project contract,
or an explicitly configured private source-entry class enforced by an exact
path allowlist. Shared or reusable framework candidates stop as no-effect
handoffs to `task_orders/framework_semantic_audit.md` and, when accepted, to
`task_orders/framework_improvement.md`; the source chain does not implement
them directly. Permission to read a source, use an acquisition path, or run a
monitor does not authorize project edits.

When a project uses the optional monitor, review, apply, and assurance chain,
use the version-bound [source-chain artifact contract](source_chain_artifacts.md)
for the durable records and verify each predecessor before advancing.

## Feedback Intake

Downstream projects may record framework-improvement candidates in
`FRAMEWORK_FEEDBACK.md`. A useful candidate states:

- reusable pattern
- evidence scope
- affected framework surface
- proposed change
- non-goals
- approval or verification needed

Before promotion to semantic review, remove project names, local paths,
branches, issue IDs, commit
hashes, logs, transcripts, identities, secrets, proprietary details, and
one-off local context.

Use `task_orders/framework_feedback_intake.md` for candidate review and
`task_orders/insights.md` when retrospective extraction is explicitly
triggered. Every `promote` or `adapt` disposition is a transitional intake
decision and routes first through
`task_orders/framework_semantic_audit.md`; only an `approve` or
`approve-with-edits` audit result routes to
`task_orders/framework_improvement.md` before implementation. A `reject` result
stops, while `needs-evidence` returns to evidence collection and re-audit.

Classify each reviewed observation before editing anything:

- project-specific evidence stays in the originating project
- reusable owner preference, quality constraint, or operating method may update
  an excluded owner profile, private standard, or operator workflow
- broadly reusable evidence may become a sanitized public-framework candidate
- unsupported, harmful, redundant, or source-specific material is rejected

An owner-private surface and a public blueprint are different destinations.
Repeated personal preference is not automatically general doctrine, while a
broadly useful abstraction should not remain trapped in one private workflow
merely because that is where it was first observed.

Source prestige does not determine evidence depth. After semantic review,
`task_orders/framework_improvement.md` owns evaluation and disposition. An
objective source correction uses direct target and adjacent verification; add a
durable defect-sensitive or negative fixture only for a repeated, objectively
reproducible mistake class. A source-derived behavioral comparison must keep
the same target task, project snapshot, and non-treatment inputs while binding
the exact current and candidate treatment identities. Full claim-grade
comparison is reserved for causal claims, public inferential or estimated quantitative claims, claimed
recurring default-behavior classes, broadly generalized effectiveness claims,
and consequential model selection or routing, reviewer-lane, or topology
decisions that lighter evidence cannot answer. Exact deterministic quantities
with decisive oracles remain in the objective evidence classes. Synthetic cases remain
diagnostic or regression material, not proof of general value.
