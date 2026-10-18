# Documentation

Choose the path that matches what you want to do:

| Start here | Purpose |
|---|---|
| [Set up a project](../GETTING_STARTED.md) | Create its first MPA instance after inspection and an approved plan. |
| [Update an existing instance](../UPDATING.md) | Inspect, refresh, revise, recover, or restore generated project files. |
| [Understand the framework](concepts.md) | Learn how project authority, task guidance, state, and evidence fit together. |

For a visual walkthrough, download or clone the framework and open the
[local interactive guide](interactive/index.html). GitHub displays its HTML
source rather than running it.

## Root Guides

| Guide | Use When |
|---|---|
| [README](../README.md) | You need the product overview and normal operating path. |
| [Architecture](../ARCHITECTURE.md) | You need the authority, runtime-assembly, lifecycle, and integration design. |
| [Specification](../SPECIFICATION.md) | You need the normative/informative surface classification and authority rules. |
| [Conformance](../CONFORMANCE.md) | You need profile meanings, checker behavior, and conformance limits. |
| [Governance](../GOVERNANCE.md) | You need product change classes, versioning, compatibility, or acceptance rules. |
| [Security](../SECURITY.md) | You need the framework threat model, disclosure policy, or security boundary. |
| [Command And Script Reference](../scripts/README.md) | You need the complete categorized command inventory, lifecycle command maps, or a route to each command's exact `--help` interface. |

## Chapters

| Chapter | Use When |
|---|---|
| [Concepts](concepts.md) | You need the operating model: authority, runtime packets, Task Orders, Practice Guides, state, source discipline, and feedback. |
| [Downstream Setup](downstream_setup.md) | You want the setup flow before following the full setup procedure in `GETTING_STARTED.md` and `task_orders/init.md`. |
| [Repository Taxonomy](repository_taxonomy.md) | You need to know where a file belongs, which surfaces are product files, and which generated files are templates. |
| [Source And Feedback](source_and_feedback.md) | You are reviewing external sources, source-monitor packets, or downstream project feedback. |
| [Source-Chain Artifacts](source_chain_artifacts.md) | You need the complete, version-bound monitor, review, apply, and assurance artifact contract used by the product source-chain helpers. |
| [Source Deep-Research Artifacts](source_deep_research_artifacts.md) | You need the typed digest contract for a completed browser research report retained as task-local evidence. |
| [Verification And Quality](verification_and_quality.md) | You need to understand deterministic checks, semantic review, reviewer lanes, and product-quality gates. |
| [Integration Packaging](../integrations/README.md) | You need the generated Codex, Claude Code, or generic-agent entrypoint and optional integration surfaces. |

## Human-Facing Interactive View

The guide illustrates the same architecture as these chapters. Its
[source layout and verification notes](interactive/README.md) explain how the
TypeScript source and checked-in JavaScript stay aligned.

## Canonical References

These chapters and the interactive view explain the framework; they do not
create agent instructions. If an explanation conflicts with an owning file,
follow that file and correct the explanation. Exact command interfaces belong
to executable help.

- `master_service_agreement.md` is the universal doctrine.
- `scripts/project_contract_model.py` owns the machine-readable downstream project-contract semantics and generates the answer schema and Markdown blueprints.
- `statement_of_work_template.md` is the generated human-readable downstream project-contract blueprint.
- `runtime/operative_charter.md` is the compact always-on runtime rule layer.
- `task_orders/` owns workflow sequence and output shape.
- `practice_guides/` owns specialist quality standards.
- `scripts/` verifies objective framework invariants where useful.
