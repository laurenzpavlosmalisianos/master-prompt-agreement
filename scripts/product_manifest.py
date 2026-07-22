#!/usr/bin/env python3

from __future__ import annotations

import ast
from pathlib import Path

"""Canonical positive inventory for the installable MPA product.

This module contains no authoring-workspace, export-marker, Git handoff, or
leak-policy rules. Private release tooling consumes this product declaration;
it does not become part of the product contract.
"""

# Files whose bytes can change downstream agent behavior, generated project
# surfaces, or validators used to accept those surfaces. Orientation,
# human-facing diagrams, and product tests remain part of the distribution
# identity but not this effective set.
DOWNSTREAM_EFFECTIVE_ROOTS = (
    "master_service_agreement.md",
    "statement_of_work_template.md",
    "runtime",
    "task_orders",
    "practice_guides",
    "integrations",
    "project_state_templates",
    "annexes",
    "conformance",
    ".agents/skills/master-prompt-new-project",
    ".agents/skills/master-prompt-refresh-project",
)

# Product workflow files outside the broad doctrine/template roots that a
# downstream lifecycle loads directly. The bootstrap examples are operative
# inputs rather than general repository examples, so their bytes belong to the
# effective identity too.
DOWNSTREAM_EFFECTIVE_EXACT_FILES = (
    "CONFORMANCE.md",
    "GETTING_STARTED.md",
    "UPDATING.md",
    "examples/automation_orders.example.json",
    "examples/project_bootstrap_answers.example.json",
    "examples/project_bootstrap_answers.schema.json",
    "examples/project_bootstrap_profile.example.json",
)

# Positive ownership map for executable downstream support. Values are command
# entrypoints; local import-only support is added through dependency closure.
# Maintainer-only commands deliberately have no downstream owner here.
DOWNSTREAM_EFFECTIVE_SCRIPT_OWNERS = {
    "GETTING_STARTED.md": (
        "scripts/check_prereqs.py",
        "scripts/conformance_check.py",
        "scripts/project_bootstrap.py",
        "scripts/project_contract_sync.py",
        "scripts/render_integrations.py",
    ),
    "UPDATING.md": (
        "scripts/conformance_check.py",
        "scripts/project_refresh.py",
    ),
    "CONFORMANCE.md": (
        "scripts/conformance_check.py",
        "scripts/project_contract_sync.py",
        "scripts/project_state_lint.py",
    ),
    "conformance/profiles.json": (
        "scripts/automation_orders_lint.py",
        "scripts/check_reference_freshness.py",
        "scripts/conformance_check.py",
        "scripts/lint_reviewer_lane_feedback.py",
        "scripts/project_contract_sync.py",
        "scripts/project_state_lint.py",
    ),
    "task_orders/automation.md": (
        "scripts/automation_orders_lint.py",
        "scripts/render_cron.py",
    ),
    "task_orders/orchestrate.md": (
        "scripts/review_packet_contract.py",
    ),
    "task_orders/compliance.md": (
        "scripts/link_check.py",
    ),
    "project_state_templates/SOURCE_MONITOR_RESEARCHER.md": (
        "scripts/source_chain_artifact_lint.py",
    ),
    "project_state_templates/SOURCE_DEEP_RESEARCH.md": (
        "scripts/source_deep_research_lint.py",
    ),
    "integrations/templates/codex/AGENTS.md.template": (
        "scripts/recommend_stack.py",
    ),
    "integrations/templates/claude-code/CLAUDE.md.template": (
        "scripts/recommend_stack.py",
    ),
    "integrations/templates/generic/AGENTS.md.template": (
        "scripts/recommend_stack.py",
    ),
}

# Executable product interfaces documented in scripts/README.md. Every other
# product Python file is import-only support or the public validation harness.
PRODUCT_COMMAND_SCRIPTS = (
    "scripts/automation_orders_lint.py",
    "scripts/check_prereqs.py",
    "scripts/check_reference_freshness.py",
    "scripts/conformance_check.py",
    "scripts/context_manifest.py",
    "scripts/evidence_scope.py",
    "scripts/link_check.py",
    "scripts/lint_reviewer_lane_feedback.py",
    "scripts/project_bootstrap.py",
    "scripts/project_contract_model.py",
    "scripts/project_contract_sync.py",
    "scripts/project_instance_lint.py",
    "scripts/project_refresh.py",
    "scripts/project_state_lint.py",
    "scripts/prompt_load_report.py",
    "scripts/query_clause_map.py",
    "scripts/recommend_stack.py",
    "scripts/reference_snapshot.py",
    "scripts/render_cron.py",
    "scripts/render_integrations.py",
    "scripts/review_packet_contract.py",
    "scripts/run_scheduled_job.py",
    "scripts/source_chain_artifact_lint.py",
    "scripts/source_chain_preflight.py",
    "scripts/source_chain_status.py",
    "scripts/source_chain_wait.py",
    "scripts/source_deep_research_lint.py",
    "scripts/source_registry_access_audit.py",
    "scripts/verification_plan.py",
)

PRODUCT_REQUIRED_FILES = (
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "pyrightconfig.json",
    "CONFORMANCE.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "UPDATING.md",
    "GETTING_STARTED.md",
    "GOVERNANCE.md",
    "ARCHITECTURE.md",
    "docs/README.md",
    "docs/concepts.md",
    "docs/downstream_setup.md",
    "docs/repository_taxonomy.md",
    "docs/source_and_feedback.md",
    "docs/source_chain_artifacts.md",
    "docs/source_deep_research_artifacts.md",
    "docs/verification_and_quality.md",
    "docs/interactive/README.md",
    "docs/interactive/index.html",
    "docs/interactive/styles.css",
    "docs/interactive/src/app.ts",
    "docs/interactive/generated/app.js",
    "docs/interactive/tsconfig.json",
    "SECURITY.md",
    "SPECIFICATION.md",
    "master_service_agreement.md",
    "statement_of_work_template.md",
    "runtime/operative_charter.md",
    "runtime/load_order.md",
    "runtime/standards_of_care.md",
    "runtime/project_template.md",
    "runtime/operative_schedule.json",
    "runtime/msa_clause_map.json",
    "runtime/clause_classification.md",
    "runtime/workflow_catalog.json",
    "runtime/task_module_obligations.json",
    "runtime/consistency_contract.json",
    "runtime/framework_quality_contract.json",
    "runtime/finding_schema.json",
    "runtime/review_packet.schema.json",
    "runtime/task_modules/arbitrate.md",
    "runtime/task_modules/audit.md",
    "runtime/task_modules/automation.md",
    "runtime/task_modules/ideate.md",
    "runtime/task_modules/plan.md",
    "runtime/task_modules/review.md",
    "conformance/profiles.json",
    "conformance/profile.schema.json",
    "task_orders/README.md",
    "task_orders/arbitrate.md",
    "task_orders/audit.md",
    "task_orders/automation.md",
    "task_orders/backout.md",
    "task_orders/commit.md",
    "task_orders/compliance.md",
    "task_orders/evaluate.md",
    "task_orders/framework_feedback_intake.md",
    "task_orders/framework_improvement.md",
    "task_orders/framework_refresh.md",
    "task_orders/incident_response.md",
    "task_orders/independent_assessment.md",
    "task_orders/ideate.md",
    "task_orders/init.md",
    "task_orders/insights.md",
    "task_orders/knowledge_transfer.md",
    "task_orders/plan.md",
    "task_orders/pull_request.md",
    "task_orders/review.md",
    "task_orders/source_update.md",
    "task_orders/framework_semantic_audit.md",
    "task_orders/orchestrate.md",
    "practice_guides/backend_database_security.md",
    "practice_guides/api_contract_security.md",
    "practice_guides/privacy_data_handling.md",
    "practice_guides/container_image_security.md",
    "practice_guides/build_pipeline_integrity.md",
    "practice_guides/apple_container_workflow.md",
    "practice_guides/change_impact_review.md",
    "practice_guides/css_quality.md",
    "practice_guides/data_systems_review.md",
    "practice_guides/decision_brief.md",
    "practice_guides/delegated_communications.md",
    "practice_guides/dependency_risk.md",
    "practice_guides/go_coding_quality.md",
    "practice_guides/html_quality.md",
    "practice_guides/implementation_planning.md",
    "practice_guides/incident_response.md",
    "practice_guides/javascript_coding_quality.md",
    "practice_guides/kubernetes_workload_review.md",
    "practice_guides/infrastructure_as_code_review.md",
    "practice_guides/knowledge_transfer.md",
    "practice_guides/logical_spec_review.md",
    "practice_guides/migration_safety.md",
    "practice_guides/platform_architecture_review.md",
    "practice_guides/prompt_agent_quality.md",
    "practice_guides/prompt_injection_review.md",
    "practice_guides/python_coding_quality.md",
    "practice_guides/release_readiness.md",
    "practice_guides/risk_routing.md",
    "practice_guides/root_cause_investigation.md",
    "practice_guides/rust_coding_quality.md",
    "practice_guides/scheduled_automation.md",
    "practice_guides/scholarly_writing.md",
    "practice_guides/secure_development.md",
    "practice_guides/security_audit.md",
    "practice_guides/seo.md",
    "practice_guides/shell_cli_coding_quality.md",
    "practice_guides/source_freshness_review.md",
    "practice_guides/source_grounded_research.md",
    "practice_guides/source_originality_review.md",
    "practice_guides/sql_query_quality.md",
    "practice_guides/swift_coding_quality.md",
    "practice_guides/task_contract.md",
    "practice_guides/testing_strategy_quality.md",
    "practice_guides/typescript_coding_quality.md",
    "practice_guides/video_creation_quality.md",
    "practice_guides/visual_verification.md",
    "practice_guides/website_frontend_quality.md",
    "project_state_templates/TODO.md",
    "project_state_templates/DECISIONS.md",
    "project_state_templates/DELEGATED_COMMUNICATIONS_COVERAGE.md",
    "project_state_templates/FINDINGS.md",
    "project_state_templates/FRAMEWORK_FEEDBACK.md",
    "project_state_templates/REVIEWER_LANE_FEEDBACK.md",
    "project_state_templates/PRECEDENTS.md",
    "project_state_templates/SOURCE_PACKS.md",
    "project_state_templates/SOURCE_UPDATE.md",
    "project_state_templates/SOURCE_MONITOR_RESEARCHER.md",
    "project_state_templates/SOURCE_DEEP_RESEARCH.md",
    "project_state_templates/SECURITY_VERIFICATION.md",
    "project_state_templates/VIDEO_DELIVERABLE_QA.md",
    "project_state_templates/VISUAL_ASSET_QA.md",
    "project_state_templates/AUTOMATION_ORDERS.json",
    ".agents/skills/master-prompt-new-project/SKILL.md",
    ".agents/skills/master-prompt-new-project/agents/openai.yaml",
    ".agents/skills/master-prompt-refresh-project/SKILL.md",
    ".agents/skills/master-prompt-refresh-project/agents/openai.yaml",
    "project_state_templates/bootstrap/PRECEDENTS.md",
    "project_state_templates/bootstrap/SOURCE_PACKS.md",
    "project_state_templates/bootstrap/SOURCE_UPDATE.md",
    "project_state_templates/bootstrap/SECURITY_VERIFICATION.md",
    "integrations/README.md",
    "integrations/registry.json",
    "integrations/templates/claude-code/CLAUDE.md.template",
    "integrations/templates/claude-code/.claude/agents/security-reviewer.md.template",
    "integrations/templates/claude-code/.claude/agents/seo-auditor.md.template",
    "integrations/templates/generic/AGENTS.md.template",
    "integrations/templates/codex/AGENTS.md.template",
    "integrations/templates/codex/skills/project-init/SKILL.md.template",
    "integrations/templates/codex/skills/project-refresh/SKILL.md.template",
    "integrations/templates/codex/skills/security-audit/SKILL.md.template",
    "integrations/templates/codex/skills/seo/SKILL.md.template",
    "scripts/bootstrap_transaction.py",
    "scripts/bounded_subprocess.py",
    "scripts/check_prereqs.py",
    "scripts/README.md",
    "scripts/check_reference_freshness.py",
    "scripts/context_manifest.py",
    "scripts/evidence_scope.py",
    "scripts/generated_sow_text.py",
    "scripts/git_query.py",
    "scripts/integration_registry.py",
    "scripts/link_check.py",
    "scripts/markdown_structure.py",
    "scripts/product_manifest.py",
    "scripts/project_bootstrap.py",
    "scripts/project_input.py",
    "scripts/project_contract_model.py",
    "scripts/project_contract_sync.py",
    "scripts/project_instance_lint.py",
    "scripts/project_refresh.py",
    "scripts/project_state_identity.py",
    "scripts/project_state_lint.py",
    "scripts/lint_reviewer_lane_feedback.py",
    "scripts/prompt_load_report.py",
    "scripts/python_import_boundary.py",
    "scripts/query_clause_map.py",
    "scripts/recommend_stack.py",
    "scripts/reference_snapshot.py",
    "scripts/render_cron.py",
    "scripts/run_scheduled_job.py",
    "scripts/render_integrations.py",
    "scripts/review_packet_contract.py",
    "scripts/resource_cleanup.py",
    "scripts/routing_policy.py",
    "scripts/safe_paths.py",
    "scripts/url_safety.py",
    "scripts/source_chain_artifact_lint.py",
    "scripts/source_deep_research_lint.py",
    "scripts/source_chain_preflight.py",
    "scripts/source_chain_status.py",
    "scripts/source_chain_wait.py",
    "scripts/source_registry_access_audit.py",
    "scripts/source_registry_files.py",
    "scripts/automation_orders_lint.py",
    "scripts/conformance_check.py",
    "scripts/verification_plan.py",
    "scripts/verification_registry.py",
    "annexes/authority.md",
    "annexes/capabilities.md",
    "annexes/security.md",
    "annexes/soul.md",
    "tests/__init__.py",
    "tests/test_validation_scripts.py",
    "tests/validation_automation_state.py",
    "tests/validation_bootstrap_end_to_end.py",
    "tests/validation_bootstrap_runtime.py",
    "tests/validation_bootstrap_transactions.py",
    "tests/validation_product_conformance.py",
    "tests/validation_evidence_scope.py",
    "tests/validation_link_check.py",
    "tests/validation_markdown_structure.py",
    "tests/validation_project_contract_sync.py",
    "tests/validation_project_runtime.py",
    "tests/validation_project_refresh.py",
    "tests/validation_product_manifest.py",
    "tests/validation_product_quality.py",
    "tests/validation_reference_freshness.py",
    "tests/validation_runtime_compactness.py",
    "tests/validation_safe_io_integrations.py",
    "tests/validation_source_chain.py",
    "tests/validation_source_deep_research.py",
    "tests/validation_source_registry_access.py",
    "tests/validation_test_support.py",
    "tests/validation_url_safety.py",
    "tests/validation_validation_routing.py",
    "examples/automation_orders.example.json",
    "examples/project_bootstrap_answers.example.json",
    "examples/project_bootstrap_answers.schema.json",
    "examples/project_bootstrap_profile.example.json",
)

PRODUCT_REQUIRED_FILE_SET = frozenset(PRODUCT_REQUIRED_FILES)
PRODUCT_TOP_LEVEL_ENTRIES = frozenset(
    relative.split("/", 1)[0] for relative in PRODUCT_REQUIRED_FILES
)
PRODUCT_DIRECTORY_PATHS = frozenset(
    "/".join(parts[:index])
    for relative in PRODUCT_REQUIRED_FILES
    for parts in (relative.split("/"),)
    for index in range(1, len(parts))
)
PRODUCT_COMPLETE_DIRECTORY_ROOTS = (
    ".agents/skills/master-prompt-new-project",
    ".agents/skills/master-prompt-refresh-project",
    "annexes",
    "examples",
    "integrations",
    "practice_guides",
    "project_state_templates",
    "runtime",
    "task_orders",
)


def is_product_path(relative: str) -> bool:
    """Return whether ``relative`` is one exact declared product file."""

    return relative in PRODUCT_REQUIRED_FILE_SET


def is_product_location(relative: str) -> bool:
    """Return whether a file or directory location belongs to a product root."""

    first = relative.split("/", 1)[0]
    return first in PRODUCT_TOP_LEVEL_ENTRIES


def iter_product_files(root: Path) -> list[Path]:
    """Return the exact declared product paths in canonical lexical order."""

    return [root / relative for relative in sorted(PRODUCT_REQUIRED_FILES)]


def iter_product_scope_files(root: Path, scopes: tuple[str, ...]) -> list[Path]:
    """Return declared product files selected by exact file or directory scopes."""

    selected = {
        root / relative
        for relative in PRODUCT_REQUIRED_FILES
        if any(
            relative == scope or relative.startswith(f"{scope}/")
            for scope in scopes
        )
    }
    return sorted(selected)


def _local_script_dependencies(root: Path, script: Path) -> set[Path]:
    """Return direct local-script imports and reject private dependencies."""

    source = script.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=script.relative_to(root).as_posix())
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module_names.add(node.module.split(".", 1)[0])

    dependencies: set[Path] = set()
    for module_name in module_names:
        candidate = root / "scripts" / f"{module_name}.py"
        if not candidate.exists() and not candidate.is_symlink():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative not in PRODUCT_REQUIRED_FILE_SET:
            raise ValueError(
                "product script imports a local private module: "
                f"{script.relative_to(root).as_posix()} -> {relative}"
            )
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"product script dependency is not a regular file: {relative}")
        dependencies.add(candidate)
    return dependencies


def downstream_effective_script_files(root: Path) -> list[Path]:
    """Resolve reviewed downstream commands and their local import closure."""

    seed_relatives = {
        relative
        for owned in DOWNSTREAM_EFFECTIVE_SCRIPT_OWNERS.values()
        for relative in owned
    }
    pending: list[Path] = []
    for relative in sorted(seed_relatives):
        path = root / relative
        if relative not in PRODUCT_REQUIRED_FILE_SET:
            raise ValueError(
                f"downstream-effective script owner is not in the product: {relative}"
            )
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(
                f"downstream-effective script owner references a missing regular file: {relative}"
            )
        pending.append(path)

    selected: set[Path] = set()
    while pending:
        script = pending.pop()
        if script in selected:
            continue
        selected.add(script)
        pending.extend(_local_script_dependencies(root, script) - selected)
    return sorted(selected)


def iter_downstream_effective_files(root: Path) -> list[Path]:
    """Return the reviewed files that can affect a downstream instance."""

    declared = iter_product_scope_files(root, DOWNSTREAM_EFFECTIVE_ROOTS)
    exact = iter_product_scope_files(root, DOWNSTREAM_EFFECTIVE_EXACT_FILES)
    python_support = downstream_effective_script_files(root)
    return sorted(set([*declared, *exact, *python_support]))
