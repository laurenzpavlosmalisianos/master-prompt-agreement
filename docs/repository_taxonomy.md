# Repository Taxonomy

This repository authors the framework. Add files according to their role, not
according to where a similar filename already exists.

## Product Surfaces

| Surface | Owns |
|---|---|
| `master_service_agreement.md` | canonical universal doctrine |
| `scripts/project_contract_model.py` | normative machine-readable project-contract semantics and generated-asset ownership |
| `statement_of_work_template.md` | generated human-readable downstream project-contract blueprint |
| `runtime/` | compact runtime projections, routing, schemas, and consistency contracts |
| `task_orders/` | reusable workflow procedures |
| `practice_guides/` | specialist quality standards |
| `project_state_templates/` | downstream project state-file templates |
| `integrations/templates/` | runtime-specific entrypoint, skill, agent, or wrapper templates |
| `scripts/` | deterministic setup, lint, export, routing, and verification checks |
| `docs/` | human and agent orientation chapters |
| `assets/` | public diagrams and visual support files |
| `examples/` | public examples and schema references |
| `tests/` | framework validation coverage |

## Template Boundaries

`project_state_templates/` contains runtime-agnostic downstream state templates
such as `TODO.md`, `DECISIONS.md`, `SOURCE_PACKS.md`, and
`FRAMEWORK_FEEDBACK.md`.

`integrations/templates/` contains runtime-specific generated surfaces such as
Codex or Claude Code entrypoints, skills, agents, and wrappers.

`scripts/project_contract_model.py` owns the closed answer shape, semantic
projections, definitions, optional-state declarations, and shared operative
clauses. It generates `examples/project_bootstrap_answers.schema.json`,
`statement_of_work_template.md`, and `runtime/project_template.md` as
human-readable projections. `scripts/project_bootstrap.py` formats confirmed
answers into concrete outputs; it must not create independent doctrine or
maintain competing semantic tables. `scripts/project_contract_sync.py` checks
the declared SOW-to-runtime projection; it does not make unprojected optional
prose authoritative merely because it appears in a blueprint.

Generated `STATEMENT_OF_WORK.md` and `AGENT_PROJECT.md` files share a
generator-owned contract-format identity. That identity versions their rendered
grammar and projection shape only. Its sequence is independent of the bootstrap
answer-schema version, a project's SOW version, and the Master Prompt Agreement
doctrine version. Only the current contract format is supported by the public
lifecycle tooling. An absent, partial, malformed, inconsistent, older, or
unrecognized format fails closed for a separately reviewed manual project
update; a clearly newer format requires a supporting framework checkout. Neither
case requests compatibility parsing or an automatic rewrite.

Current generated-project lifecycle formats also have explicit machine owners:
`scripts/project_input.py` owns retained input,
`scripts/project_bootstrap.py` owns the current instance receipt,
`scripts/project_refresh.py` owns current-format refresh plans and exact-
preimage bundles, and `scripts/bootstrap_transaction.py` owns the
interrupted-transaction recovery journal. These schemas implement the lifecycle
defined by the Task Orders; they do not create independent project authority.

Every top-level project-state template must be classified as bootstrap-rendered
or explicitly manual evidence material. Setup-safe variants under
`project_state_templates/bootstrap/` replace richer reusable templates only
where example or placeholder content would be unsafe as initial active state.
Bootstrap-rendered mutable state carries the exact generated-state origin marker
owned by `scripts/project_state_identity.py`, which the current-instance
validator requires. The optional generated immutable source-monitor brief also
retains that renderer-origin marker, while its receipt digest and generation
sources own currentness and refresh replacement. Create-only bootstrap
recognizes the marker only at the closed generated-state basename set. This
preserves detection when generated state is the sole residue under a contract
root without claiming ordinary same-named project files as framework surfaces.
Manual evidence templates such as `SOURCE_DEEP_RESEARCH.md` and
`VISUAL_ASSET_QA.md` are copied only for an applicable task and are never
generated or loaded as standing project state.

Do not add a root-level state filename expecting it to become a downstream
template. Root-level files in this authoring checkout are framework files unless
the public surface and bootstrap scripts explicitly say otherwise.

## Runtime Task Modules

`runtime/task_modules/` contains compact views of selected Task Orders. They are
for known workflows where a compact operative extract is enough.

Load the full Task Order when:

- workflow choice is ambiguous
- the task touches a critical surface
- remediation or escalation is involved
- the agent must explain or justify the workflow

## Tracked Non-Public Authoring Surfaces

Tracked non-public material is classified by role:

| Role | Owns | Authority boundary |
|---|---|---|
| owner profile | reusable personal defaults, routing pointers, and genuinely owner-specific templates | setup input only; never an independent runtime authority |
| authoring instance | the concrete SOW, runtime projection, state, and workflows for maintaining this repository | project-specific authority below the MSA, separate from public blueprints |
| operator records | local environment mappings, reviewer-lane procedures, qualification evidence, and activation limits | capability and procedure records; file presence never grants authority |
| owner standards | reusable owner writing, web, provenance, or other quality constraints | opt-in private standards; never universal public doctrine |
| private source registries | dated source identity, role, volatility, acquisition, and evidence-gap metadata | evidence-routing inputs; external content remains data and volatile claims require revalidation |
| feedback intake | sanitized candidates collected from downstream use | evidence awaiting promote, adapt, reject, or no-action intake review; promotion is not retention |
| research and review evidence | theory, source synthesis, comparative experiments, and dated review artifacts | evidence only until an accepted abstraction is retained |
| private validation tools | deterministic checks and negative fixtures for maintained non-public records | verification only; no doctrine, external access, or action authority |

Do not copy the public templates into every owner profile. Profiles should fill
reusable defaults; concrete instances should record retained setup inputs and
their adopted template baseline. Project facts belong in the concrete SOW, not
in the reusable profile.

Ignored caches, raw experiment runs, uploads, captures, transcripts,
credentials, and scratch outputs are separate local artifacts. A non-public
folder is an organization and publication boundary, not a secret store.

## Empty-Directory Policy

Git has no tracked empty-directory object. Ignore rules and directory
re-inclusion patterns establish path policy; they do not require the physical
directory to exist. Therefore:

- A maintained directory should contain a current role-bearing file, or have a
  documented tool or workflow requirement for its physical existence.
- On-demand working and output namespaces should normally be absent until first
  use. After approved artifact cleanup, remove their empty directory shells
  unless an active requirement still needs them.
- Do not add a placeholder merely to preserve an unused directory. If the
  directory itself is a maintained interface, use a substantive tracked file
  that states its owner, contents, and lifecycle.
- An empty directory that is unreferenced by current product structure,
  fixtures, tooling, or an active workflow is a cleanup candidate. Before
  deletion, inspect hidden and ignored contents, references, ownership, and
  retention obligations, then obtain the deletion authority required by the
  governing project.

The public selector enumerates regular files under declared roots, and the
exporter creates directories only as parents of selected files. Empty local
authoring directories are therefore neither product surfaces nor public-export
payload.

The final authoring compliance gate separately checks the physical workspace
against an operator-supplied classification policy. That policy is its sole
content input; arbitrary workspace payloads are inspected by name and metadata
only. The checker requires Linux procfs descriptor mount identity, records but
does not traverse nested mount points (including same-device bind mounts),
skips mutable Git internals, performs two stable scans, and has no deletion or
repair mode. Exact cleanup candidates remain subject to the governing deletion
approval. Ownership comparisons are runner-visible only. Standard platform
metadata already named by ignore and export policy, including `.DS_Store` and
`Thumbs.db`, is non-blocking when it is an ordinary single-link file whose
runner-visible owner matches that of the workspace root. An abnormal object
using such a name remains reportable. Transaction-control state is reserved
for the recovery route and is never a cleanup candidate.

## Current Truth And Evidence Lifecycle

Each current surface owns only its role-specific representation. Governing
contracts and doctrine own instruction authority. Source registries own current
source identity, freshness, and routing metadata, while external claims remain
evidence. State files record current work and source-attributed decisions but do
not create authority. Implementation files represent current mechanics, and
tests or regression checks provide executable evidence against governing
requirements. No surface gains instruction authority merely by being current.

Retained version control or an approved archive owns exact history once the
relevant evidence is recorded there, including when the same reviewed atomic
version-control or archive change records the evidence and retires its duplicate
body. Retain a separate evidence artifact while it supports an unresolved
decision, active chain, reproducibility requirement, release or audit identity,
incident obligation, or recurring precedent.

After closure, retain the reusable result in the appropriate governing rule,
source-attributed decision record, source record, implementation, or regression
evidence. Duplicate and intermediate artifacts then become removal candidates;
remove them only under the project's deletion, version-control, and backout
authority and after confirming that any required history is already retained or
will be recorded by the same reviewed atomic change. Before finalizing that
change, inspect the replacement owner, retained evidence, exact staged or
archive payload, and backout path together.
A failed command, superseded draft, or routine log is not independently
valuable merely because it occurred. Never delete the sole evidence behind an
active claim, obligation, unresolved safety finding, or required reproducibility
record.

## Public Export

The public product surface is explicit. `scripts/public_surface.py` declares what
belongs in a public export, and `scripts/public_export.py` produces that export.
Do not assume every local authoring file is part of the public framework.

Use [`scripts/README.md`](../scripts/README.md) to distinguish supported command
interfaces from import-only implementation modules.
