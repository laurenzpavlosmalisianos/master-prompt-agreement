# Documentation

This index routes the chapter-style documentation and root operator guides for
Master Prompt Agreement. They explain how the framework fits together without
becoming a second authority layer. If an orientation surface conflicts with the
Master Service Agreement, Statement of Work, Task Orders, Practice Guides,
runtime files, or executable command help, correct the orientation surface and
follow the owning canonical file.

The interactive HTML and TypeScript documentation is a human-facing
presentation layer over these markdown chapters and framework files. It may
illustrate concepts, flows, and architecture, but it must not become the source
of truth for agent behavior.

## Root Guides

| Guide | Use When |
|---|---|
| [README](../README.md) | You need the product overview and normal operating path. |
| [Getting Started](../GETTING_STARTED.md) | You are creating a first current-format project instance. |
| [Updating](../UPDATING.md) | You are inspecting, refreshing, revising, recovering, or restoring an existing generated instance. |
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
| [Updating A Generated Project](../UPDATING.md) | You need the operator recipe for inspecting, refreshing, revising, recovering, restoring, or triaging an unsupported generated format; `task_orders/framework_refresh.md` remains the workflow authority. |
| [Repository Taxonomy](repository_taxonomy.md) | You need to know where a file belongs, which surfaces are product files, and which generated files are templates. |
| [Source And Feedback](source_and_feedback.md) | You are reviewing external sources, source-monitor packets, or downstream project feedback. |
| [Source-Chain Artifacts](source_chain_artifacts.md) | You need the complete, version-bound monitor, review, apply, and assurance artifact contract used by the product source-chain helpers. |
| [Source Deep-Research Artifacts](source_deep_research_artifacts.md) | You need the typed digest contract for a completed browser research report retained as task-local evidence. |
| [Verification And Quality](verification_and_quality.md) | You need to understand deterministic checks, semantic review, reviewer lanes, and product-quality gates. |
| [Integration Packaging](../integrations/README.md) | You need the generated Codex, Claude Code, or generic-agent entrypoint and optional integration surfaces. |

## Human-Facing Interactive View

[Interactive Guide](interactive/index.html) is a static HTML and TypeScript
presentation layer for humans. Download or clone the product and open the file
locally; GitHub's repository view displays its source instead of executing it.
It exists to make the architecture easier to inspect visually. Agents may use
it as an explanatory aid when teaching or walking a human through the framework,
but it does not replace, override, or extend the Markdown framework files. Its
[source layout and verification notes](interactive/README.md) explain the
TypeScript/generated-JavaScript boundary.

## Canonical References

- `master_service_agreement.md` is the universal doctrine.
- `scripts/project_contract_model.py` owns the machine-readable downstream project-contract semantics and generates the answer schema and Markdown blueprints.
- `statement_of_work_template.md` is the generated human-readable downstream project-contract blueprint.
- `runtime/operative_charter.md` is the compact always-on runtime rule layer.
- `task_orders/` owns workflow sequence and output shape.
- `practice_guides/` owns specialist quality standards.
- `scripts/` verifies objective framework invariants where useful.
