#!/usr/bin/env python3

from __future__ import annotations


FLAG_HELP = {
    "small": "Small and local task.",
    "ambiguous": "Scope or success criteria are ambiguous.",
    "current_info": "Task depends on current external information.",
    "source_refresh": "Task needs current primary sources translated into checks.",
    "logic_review": "Task needs logical consistency, satisfiability, case coverage, or decision-table review.",
    "testing_strategy": "Task designs, reviews, generates, repairs, or relies on tests as acceptance evidence.",
    "data_systems": "Task changes data-intensive architecture, storage, replication, consistency, streaming, analytics, search, vector, or cloud data-service behavior.",
    "api_contract_security": "Task designs, changes, or reviews API contracts, endpoint schemas, operation authorization, generated API artifacts, webhooks, GraphQL, gRPC, or REST boundaries.",
    "privacy_data_handling": "Task touches personal, customer, private, production-derived, sensitive, regulated, or protected data, including logs, traces, screenshots, prompts, model outputs, egress, retention, or deletion.",
    "container_image_security": "Task touches Containerfiles, OCI images, base images, image build context, image layers, build secrets, SBOM/provenance/signatures, registries, or container image scanning.",
    "build_pipeline_integrity": "Task touches CI/CD workflow files, build jobs, release jobs, runner trust, workflow permissions, OIDC, secrets, caches, artifacts, provenance, SBOMs, attestations, signatures, or publish handoffs.",
    "database_security": "Task designs, implements, or reviews SQL/database-backed backend security, database exposure, credentials, permissions, migrations, backups, model-generated SQL, or natural-language-to-query execution.",
    "platform_architecture": "Task changes or reviews platform, cloud, DevOps, SRE, gateway, service mesh, control-plane, deployment, or internal developer platform architecture.",
    "infrastructure_as_code": "Task touches infrastructure-as-code source, generated or transformed output, providers, modules, state, plans, previews, diff artifacts, drift, policy-as-code, or apply/deploy gates.",
    "prompt_agent_quality": "Task changes prompts, agent instructions, agent workflows, tool-use contracts, or model-output quality guidance.",
    "source_originality": "Task uses external code, assets, demos, product references, generated prototypes, or third-party patches as inspiration or input.",
    "multi_file": "Task spans multiple files or surfaces.",
    "user_facing": "Task changes user-visible behavior or copy.",
    "dependency_change": "Task adds or upgrades a dependency.",
    "migration": "Task changes schema, data shape, or compatibility.",
    "release": "Task is release, deployment, or merge-readiness work.",
    "visual": "Task changes rendered UI, screenshots, layout, canvas, images, or browser-visible output.",
    "frontend_quality": "Task changes website frontend quality, generated output, CSS architecture, assets, metadata, or release checks.",
    "html_quality": "Task changes authored or generated HTML semantics, forms, links, tables, media, embeds, metadata, ARIA, or validator output.",
    "css_quality": "Task changes CSS architecture, selectors, cascade, layout, animation, browser support, or modern CSS feature use.",
    "javascript_quality": "Task changes plain JavaScript source, module semantics, runtime APIs, package entry points, generated JavaScript, or JavaScript async/resource behavior.",
    "swift_quality": "Task changes Swift, SwiftUI, Apple-platform app architecture, resources, concurrency, or package behavior.",
    "rust_quality": "Task changes Rust code, Cargo configuration, crate APIs, unsafe code, platform targets, or Rust release behavior.",
    "typescript_quality": "Task changes TypeScript, tsconfig, module resolution, declaration emit, package types, or type boundaries.",
    "python_quality": "Task changes Python code, pyproject metadata, uv workflow, Python typing, packaging, tests, or Python runtime behavior.",
    "go_quality": "Task changes Go code, modules, package APIs, command packages, concurrency, cgo, tests, or Go release behavior.",
    "shell_cli_quality": "Task changes shell scripts, CLI wrappers, install/bootstrap scripts, automation command strings, or reusable shell-driven workflows.",
    "sql_quality": "Task changes handwritten SQL, schema DDL, query shape, migrations' SQL text, transactions, result shape, or query performance.",
    "kubernetes_quality": "Task changes Kubernetes manifests, rendered Helm/Kustomize/GitOps output, RBAC, workloads, networking, storage, CRDs, admission, or rollout behavior.",
    "apple_container_workflow": "Task changes Apple container CLI workflow, machines, images, registry use, mounts, volumes, networks, ports, or host/container boundaries.",
    "review": "Task is a review rather than direct implementation.",
    "debugging": "Task is root-cause investigation or debugging.",
    "impact_review": "Task needs blast-radius or invariant-focused review.",
    "secure_development": "Task asks for secure code generation, secure application hardening, approved static analysis, authorized dynamic checks, fuzzing, or security verification profiles.",
    "audit": "Task is an audit or systematic assessment.",
    "security": "Task has explicit security impact.",
    "untrusted_input": "Task touches untrusted external content.",
    "hard_to_reverse": "Task is recoverable but rollback-sensitive or costly to undo.",
    "destructive": "Task deletes, overwrites, or irreversibly changes state, or recovery is unclear.",
    "external_effect": "Task will write to or otherwise affect an external system, account, service, deployment, or recipient.",
    "privileged_effect": "Task will exercise elevated privileges, protected credentials, administrative authority, or a privileged control plane.",
    "incident": "Task involves incident response or compromise analysis.",
    "data_loss": "Task may involve data loss risk.",
    "secret_exposure": "Task may involve exposed secrets or credentials.",
    "agentic": "Task uses agentic retrieval, tool-using flows, MCP/connectors, or persistent memory/state.",
    "planning": "Task is implementation planning for multi-step work.",
    "scheduled": "Task defines recurring scheduled automation.",
    "seo": "Task is SEO-related.",
    "briefing": "Task needs a concise decision or status brief.",
    "knowledge_transfer": "Task asks for teaching, onboarding, a guided explanation, or comprehension checks.",
    "scholarly_writing": "Task is scholarly writing, citation, or source-heavy revision.",
    "video_creation_quality": "Task produces or revises a temporal audiovisual deliverable, including its brief, script, assets, edit, captions, encoding, playback, or delivery package; do not use for video as a research source, still images, or HTML media embedding alone.",
    "delegated_communication_coverage": "Task configures or operates bounded delegated communication coverage over untrusted inbound messages, protected information, and an external communication effect.",
}

CONTEXT_ONLY_FLAG_HELP = {
    "critical_surface": "Task crosses a critical project, security, authority, or release surface.",
    "delegated": "Plan or work product will be handed to another agent or session.",
    "same_author_tests": "Same-author tests or their coverage are material review evidence.",
    "coverage_ledger": "Every relevant file or surface must be recorded in a coverage ledger.",
    "multi_agent": "Multiple agents or reviewer lanes contribute evidence.",
    "remediation": "Remediation is in scope.",
    "state_edits": "Project state-file edits are in scope.",
    "broad_scope": "The requested audit scope is broad.",
    "external_tool_output": "External standards or tool output drive findings.",
    "project_write": "The workflow may change or render files inside the project.",
    "external_reviewer": "An external reviewer is used.",
    "browser_session": "A browser session is used.",
    "scheduler_change": "Scheduler installation or enablement is requested.",
    "non_cron_backend": "Automation needs scheduler semantics beyond Cronie rendering.",
    "panel": "An arbitration panel will be convened.",
    "human_reviewer": "A human reviewer will be convened.",
    "interested_coordinator": "The active coordinator is a position holder or has another material stake in the dispute.",
    "act_autonomy": "The automation has act autonomy rather than observe or propose autonomy.",
    "binding_ratification": "Binding arbitration ratification is requested.",
    "no_decision": "An arbitration no-decision outcome needs follow-up routing.",
}

CONTEXT_FLAG_OPTION_ALIASES = {
    "act_autonomy": ("--act", "--act-autonomy"),
    "binding_ratification": ("--binding", "--binding-ratification"),
}

FORENSIC_FLAGS = ("incident", "data_loss", "secret_exposure")
ADVERSARIAL_FLAGS = (
    "security",
    "secure_development",
    "api_contract_security",
    "privacy_data_handling",
    "container_image_security",
    "build_pipeline_integrity",
    "database_security",
    "infrastructure_as_code",
    "untrusted_input",
    "destructive",
    "external_effect",
    "privileged_effect",
    "delegated_communication_coverage",
)
CAREFUL_FLAGS = (
    "ambiguous",
    "current_info",
    "source_refresh",
    "logic_review",
    "testing_strategy",
    "data_systems",
    "api_contract_security",
    "privacy_data_handling",
    "container_image_security",
    "build_pipeline_integrity",
    "database_security",
    "platform_architecture",
    "infrastructure_as_code",
    "prompt_agent_quality",
    "source_originality",
    "multi_file",
    "user_facing",
    "dependency_change",
    "migration",
    "release",
    "visual",
    "frontend_quality",
    "html_quality",
    "css_quality",
    "javascript_quality",
    "swift_quality",
    "rust_quality",
    "typescript_quality",
    "python_quality",
    "go_quality",
    "shell_cli_quality",
    "sql_quality",
    "kubernetes_quality",
    "apple_container_workflow",
    "hard_to_reverse",
    "review",
    "audit",
    "debugging",
    "impact_review",
    "secure_development",
    "agentic",
    "planning",
    "scheduled",
    "seo",
    "briefing",
    "knowledge_transfer",
    "scholarly_writing",
    "video_creation_quality",
)


def cli_flags() -> list[tuple[str, str]]:
    return [(name.replace("_", "-"), help_text) for name, help_text in FLAG_HELP.items()]


def allowed_trigger_flags() -> set[str]:
    return set(FLAG_HELP)


def context_condition_arguments() -> list[tuple[tuple[str, ...], str, str]]:
    return [
        (
            CONTEXT_FLAG_OPTION_ALIASES.get(
                destination,
                (f"--{destination.replace('_', '-')}",),
            ),
            destination,
            help_text,
        )
        for destination, help_text in CONTEXT_ONLY_FLAG_HELP.items()
    ]


def runtime_condition_flags() -> set[str]:
    """Return every flag destination that context_manifest can evaluate."""

    return allowed_trigger_flags() | set(CONTEXT_ONLY_FLAG_HELP)
