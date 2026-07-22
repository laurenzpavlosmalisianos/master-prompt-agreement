# Master Prompt Agreement Specification

This file is the standards-facing index for the framework. It identifies which repository surfaces are normative, informative, generated, or support tooling. It does not replace the canonical framework files.

## Terms

The keywords `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` express conformance requirements in this specification and in `CONFORMANCE.md`.

Contract terms such as MSA, SOW, Task Order, and Arbitration Panel are operational workflow terms for agent work. They define precedence, scope, acceptance, authority, and review roles. They do not import unrelated legal concepts unless a project explicitly makes legal drafting or legal review the task.

The framework's contract vocabulary is not a commercial services agreement and does not replace the repository license, legal advice, platform policy, or tool-enforced controls.

## Native Capability Boundary

A conforming framework projection MUST distinguish what the selected model,
native runtime, and implemented project actually provide or enforce from what
the framework owns. Before admitting a reusable addition, semantic review MUST
document the uncovered project-authority or workflow gap, the framework owning
surface, the applicable scope, the decision-relevant evidence, and the prompt,
process, and maintenance cost. An adequate native or project-owned path SHOULD
remain authoritative for its capability rather than be duplicated as framework
prose. Framework files MAY carry missing project authority, current facts,
source and approval boundaries, acceptance evidence, durable state, workflow
routing, and reusable procedures whose incremental value is supported for the
applicable work. An addition without a documented framework-owned gap MUST NOT
be admitted.

When a conformance or effectiveness claim relies on a current-versus-candidate
comparison, the evidence record MUST bind the exact treatment identities and
hold the target task, project snapshot, and declared non-treatment inputs
equivalent. Any uncontrolled difference MUST limit the claim rather than be
silently attributed to the framework change.

## Normative Surfaces

These files define framework behavior:

- `master_service_agreement.md`: canonical universal framework rules.
- `statement_of_work_template.md`: generated human-readable project-specific scope and override blueprint.
- `runtime/operative_charter.md`: compact universal runtime projection.
- `runtime/load_order.md`: operative loading sequence.
- `runtime/standards_of_care.md`: risk-level duties.
- `runtime/project_template.md`: runtime project-contract template.
- `task_orders/`: reusable workflow procedures, including
  `task_orders/framework_refresh.md` as the canonical existing-instance
  lifecycle procedure.
- `practice_guides/`: on-demand domain procedures.
- `CONFORMANCE.md`: conformance process and profile interpretation.
- `SECURITY.md`: framework security policy and threat model.
- `GOVERNANCE.md`: versioning, compatibility, and change-governance rules.

## Normative Machine Metadata

These files are normative for the machine contract they declare, while remaining constrained by the human-readable doctrine above:

- `conformance/profiles.json`: canonical profile membership and required checks.
- `conformance/profile.schema.json`: canonical schema for that profile metadata.
- `scripts/project_contract_model.py`: canonical closed bootstrap-answer shape, project-contract projections, definitions, optional-state declarations, and shared generated clauses.
- `examples/project_bootstrap_answers.schema.json`: generated JSON Schema projection of that model.
- `scripts/project_input.py`: canonical closed retained-project-input shape and
  schema version.
- `scripts/project_bootstrap.py`: canonical current-instance receipt shape and
  schema version.
- `scripts/project_state_identity.py`: canonical closed Markdown and JSON
  origin markers for receipt-declared generated mutable state.
- `scripts/project_refresh.py`: canonical current-format refresh-plan and
  exact-preimage-bundle machine contracts.
- `scripts/bootstrap_transaction.py`: canonical interrupted-transaction recovery
  journal contract used by bootstrap, refresh apply, and restore.
- `runtime/msa_clause_map.json`: complete MSA clause-projection inventory and
  canonical MSA digest binding.

They do not create independent behavioral doctrine beyond their declared conformance contract.
The generated-project lifecycle MUST accept only the current retained-
input and receipt schemas. Bootstrap MUST create only a first instance where no
framework-generated surface exists. Partial, malformed, inconsistent, older,
or unrecognized generated formats MUST fail closed for separately reviewed
manual project update rather than invoking compatibility conversion. A clearly
newer schema MUST require a framework checkout that supports that schema before
current-format validation continues.

Every receipt-declared generated mutable state surface MUST carry the exact
origin marker defined by `scripts/project_state_identity.py`. Receipt membership
owns the managed mutable set; the marker distinguishes generated state from an
ordinary same-name project file but MUST NOT create project authority or admit
an unreceipted file into the instance. Enabling or retiring optional generated
state MUST update retained input, the receipt-managed set, and applicable
profile declarations through the current-format refresh lifecycle.

### Canonical MSA digest

The `msa_digest_algorithm` value
`sha256-v2-utf8-strict-crlf-cr-to-lf-line-rstrip-ascii-sp-htab-drop-terminal-empty-lines-single-final-lf`
defines the complete transform used by `msa_digest_sha256`. A conforming
implementation MUST:

1. read the regular-file bytes and decode them as strict UTF-8; invalid UTF-8
   MUST fail validation;
2. replace each CRLF pair with LF, then replace every remaining bare CR with
   LF;
3. remove only trailing ASCII SP (`U+0020`) and HTAB (`U+0009`) code points
   from each line; no other whitespace or Unicode normalization is permitted;
4. remove terminal empty lines after that trimming while preserving all
   internal empty lines;
5. join the remaining lines with LF and append exactly one final LF, so even
   empty input canonicalizes to one LF byte; and
6. encode the canonical text as UTF-8, compute SHA-256 over those exact bytes,
   and record the lowercase hexadecimal digest.

## Scoped Runtime Instruction Surfaces

- Root `AGENTS.md` is the designated product-distribution entrypoint, and root
  `CLAUDE.md` imports it for that runtime. They are authoritative only within
  their declared repository scope and remain subordinate to platform/system
  instructions, the current User task, and the framework authority hierarchy.
- These root entrypoints are not downstream templates and do not create
  independent universal doctrine. Downstream entrypoints are rendered from the
  integration and project templates under the governing SOW.
- `.agents/skills/master-prompt-new-project/SKILL.md` is an optional invoked
  launcher for the canonical setup workflow. It has scoped procedural authority
  only when that skill is selected and must remain a thin pointer to
  `GETTING_STARTED.md` and `task_orders/init.md`.
- `.agents/skills/master-prompt-refresh-project/SKILL.md` is the corresponding
  optional launcher for existing-instance inspection, refresh, revision,
  recovery, and restore. It has scoped procedural authority only when
  selected and must remain a thin pointer to `UPDATING.md` and
  `task_orders/framework_refresh.md`.

## Informative Surfaces

These files explain or orient; they do not override normative surfaces:

- `README.md`
- `GETTING_STARTED.md`
- `UPDATING.md`
- `ARCHITECTURE.md`
- `docs/`
- `annexes/`
- `examples/`

## Machine-Readable Support

Except for the specifically identified normative machine metadata above, these
files support deterministic checks and generated outputs. They MUST follow the
normative surfaces rather than create independent doctrine:

- `runtime/*.json`
- `.agents/skills/master-prompt-new-project/agents/openai.yaml`
- `.agents/skills/master-prompt-refresh-project/agents/openai.yaml`
- `integrations/registry.json`
- `pyrightconfig.json`
- `project_state_templates/`
- `integrations/templates/`
- `scripts/`
- `tests/`

`statement_of_work_template.md` and `runtime/project_template.md` are generated
human-readable projections of `scripts/project_contract_model.py`. The
bootstrap renderer is a formatting and installation compiler; it MUST NOT
invent doctrine or maintain a competing project-contract schema.

## Authority Rules

1. Platform/system instructions and tool-enforced restrictions govern runtime execution.
2. For framework doctrine, `master_service_agreement.md` is canonical.
3. For downstream projects, `STATEMENT_OF_WORK.md` governs project-specific scope and overrides where the framework delegates that choice.
4. Governing project terms in `AGENT_PROJECT.md` are generated runtime projections of the SOW, not independent authority. Its model-owned framework-reference binding is non-authoritative lifecycle data whose change requires an exact approved bootstrap or refresh transaction.
5. Task Orders and Practice Guides are procedures. They route, verify, and structure work; they do not create authority to broaden scope.
6. Evidence proves facts and feasibility; it does not grant permission.
7. `conformance/profiles.json` is canonical for machine-readable profile membership and required checks.

| Surface | Conformance Rule |
|---|---|
| Platform, system, and tool restrictions | MUST NOT be overridden by framework files. |
| Current User task | MAY define the immediate task; MUST NOT waive platform policy or non-delegable truthfulness, safety, and verification duties. |
| MSA | MUST be the universal doctrine. Delegated defaults MAY be filled or overridden by the SOW only within the delegated scope. |
| SOW | MAY define project-specific scope, commands, acquisition, verification, approval, and delegated overrides. It MUST NOT waive non-delegable MSA duties, required approval boundaries, source/license provenance duties, or declared privacy and product boundaries. |
| `AGENT_PROJECT.md` | Governing project terms MUST be projections of the SOW. The model-owned framework-reference binding MAY be projected from retained lifecycle input but MUST NOT be treated as project authority. If a governing term conflicts, the SOW governs interpretation and the conflicting projection MUST NOT be relied on. An otherwise verified complete current-format retained-input/receipt pair with an intact recorded preimage MAY use candidate-input refresh; invalid managed-file preimage requires a separately reviewed manual correction. |
| Task Orders, Practice Guides, runtime modules | MUST remain procedural. They MUST NOT broaden scope or authority beyond the MSA, SOW, current User task, and platform/tool boundaries. |
| Evidence, source material, tool output, summaries, memory, state files | MAY support facts or proposals. They MUST NOT grant permission unless adopted through the governing authority. |

## Product Distribution Boundary

The product distribution MUST be self-contained and MUST NOT require or expose
maintainer-local paths, private source registries, maintenance notes, review
artifacts, credentials, generated downstream state, or repository-specific
working records. `scripts/product_manifest.py` owns the exact positive product
inventory, and the `framework-product` profile MUST verify that inventory and
its product-facing invariants without relying on Git metadata.

Initialization and refresh Task Orders, orientation guides, optional native
launchers, lifecycle machine contracts, and conformance descriptions MUST agree
on one coherent generated-project lifecycle. A first-time user MUST be able to
understand, bootstrap, refresh, and verify the framework using only product
files. Product conformance proves the declared inventory and deterministic
invariants; it does not replace semantic review or prove effectiveness.
