# Repository Taxonomy

This repository is the framework product distribution. Classify files by their
role rather than by where a similar filename already exists.

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
| `scripts/` | deterministic setup, refresh, lint, routing, and verification support |
| `docs/` | human and agent orientation chapters |
| `examples/` | product examples and schema references |
| `tests/` | product behavior, security, and conformance verification |

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
doctrine version. Only the current contract format is supported by the
framework lifecycle tooling. An absent, partial, malformed, inconsistent,
older, or
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
template. Root-level files in the product distribution are framework files
unless the product manifest and bootstrap model explicitly say otherwise.

## Runtime Task Modules

`runtime/task_modules/` contains compact views of selected Task Orders. They are
for known workflows where a compact operative extract is enough.

Load the full Task Order when:

- workflow choice is ambiguous
- the task touches a critical surface
- remediation or escalation is involved
- the agent must explain or justify the workflow

## Generated Project Surfaces

A downstream project's `STATEMENT_OF_WORK.md`, `AGENT_PROJECT.md`, runtime
entrypoint, retained `PROJECT_INPUT.json`, root `PROJECT_INSTANCE.json`, and
receipt-declared state belong to that project, not to the framework product.
Bootstrap creates them from confirmed project facts; refresh revises or
regenerates them through an exact reviewed plan. Never copy one project's
generated authority, state, paths, or source records into product templates or
another project.

Reusable bootstrap profiles are input defaults, not authority. Project facts
belong in the concrete SOW, and evidence or reviewer output remains data until
the governing project adopts a result through its authorized workflow.

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

## Product Inventory

The product surface is explicit. `scripts/product_manifest.py` declares the
exact required files. The `framework-product` conformance profile checks that
inventory, and its `--exact-product-tree` mode rejects undeclared distribution
entries except a physical root `.git` file or directory, as documented in
`CONFORMANCE.md`. Caches, bytecode, and OS metadata are not exceptions. A file
outside the manifest is not required for a user or
agent to understand, set up, refresh, or verify the framework.

Use [`scripts/README.md`](../scripts/README.md) to distinguish supported command
interfaces from import-only implementation modules.
