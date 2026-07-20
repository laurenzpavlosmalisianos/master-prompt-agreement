#!/usr/bin/env python3

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path


PUBLIC_EXPORT_OWNERSHIP_MARKER = ".mpa-public-export.json"

PUBLIC_GITIGNORE_PATTERNS = (
    f"/{PUBLIC_EXPORT_OWNERSHIP_MARKER}",
    "/internal_*.md",
    "/INTERNAL_*.md",
    "/*_STATE*.md",
    "/*_Commit.md",
    "/TODO.md",
    "/DECISIONS.md",
    "/FINDINGS.md",
    "/FRAMEWORK_FEEDBACK.md",
    "/REVIEWER_LANE_FEEDBACK.md",
    "/PRECEDENTS.md",
    "/SOURCE_UPDATE.md",
    "/SOURCE_PACKS.md",
    "/SOURCE_MONITOR_RESEARCHER.md",
    "/SOURCE_DEEP_RESEARCH.md",
    "/SECURITY_VERIFICATION.md",
    "/STATEMENT_OF_WORK.md",
    "/AGENT_PROJECT.md",
    "/PROJECT_INPUT.json",
    "/PROJECT_INSTANCE.json",
    "/.mpa-bootstrap.lock",
    "/.mpa-bootstrap-recovery.json",
    "/.mpa-bootstrap-recovery.tmp",
    "**/.mpa-bootstrap-transaction-*/",
    "/ARBITRATION.md",
    "/AUTOMATION_ORDERS.json",
    "/SOUL.md",
    "/CAPABILITIES.md",
    "/AUTHORITY.md",
    ".direnv/",
    ".envrc",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "pip.conf",
    "credentials.json",
    "token.json",
    "client_secret*.json",
    "service-account*.json",
    "google-credentials*.json",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "/.codex",
    "/.codex/",
    "/.claude",
    "/.claude/",
    "/.mcp.json",
    "/.cursor/",
    "/.continue/",
    "/.aws/",
    "/.azure/",
    "/.gcloud/",
    "/.kube/",
    "/secrets/",
    "/.secrets/",
    "/vault/",
    "/private/**",
    "/review_artifacts/",
    "/external_review/",
    "/notes/",
    "/scratch/",
    "/transcripts/",
    "/session_logs/",
    "/captures/",
    "/source_dumps/",
    "/source_material/",
    "/local/",
    "/" + "tmp" + "/",
    ".DS_Store",
    "Thumbs.db",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.odt",
    "*.rtf",
    "*.pages",
    "*.xls",
    "*.xlsx",
    "*.numbers",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite3",
    ".pyre/",
    ".pytype/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".hypothesis/",
    ".tox/",
    ".nox/",
    ".venv/",
    ".coverage",
    ".coverage.*",
    "htmlcov/",
    "node_modules/",
    ".npm/",
    ".pnpm-store/",
    ".yarn/",
    "dist/",
    "build/",
)

PUBLIC_EXPORT_GITIGNORE_TEXT = (
    "# Generated public-export ignore rules\n"
    "# Keep project-local state, credentials, caches, and authoring material out of commits.\n"
    + "\n".join(PUBLIC_GITIGNORE_PATTERNS)
    + "\n"
)

PUBLIC_ROOTS = (
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "pyrightconfig.json",
    "CONFORMANCE.md",
    "GETTING_STARTED.md",
    "GOVERNANCE.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "UPDATING.md",
    "ARCHITECTURE.md",
    "docs",
    "SECURITY.md",
    "SPECIFICATION.md",
    ".agents/skills/master-prompt-new-project",
    ".agents/skills/master-prompt-refresh-project",
    "master_service_agreement.md",
    "statement_of_work_template.md",
    "conformance",
    "task_orders",
    "practice_guides",
    "runtime",
    "integrations",
    "project_state_templates",
    "annexes",
    "examples",
    "assets",
    "scripts",
    "tests",
)

# Files whose bytes can change downstream agent behavior, generated project
# surfaces, or the validators used to accept those surfaces. Orientation,
# publication, assets, tests, and repository-only maintenance files remain part
# of the exact distribution identity but not this effective set.
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

# Public workflow files outside the broad doctrine/template roots that a
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
# Framework publication, export, source-monitoring, and repository-compliance
# commands deliberately have no downstream owner here and remain
# distribution-only.
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

PUBLIC_REQUIRED_FILES = (
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
    "docs/maintenance_and_release.md",
    "docs/migrating_v1_to_v2.md",
    "docs/interactive/README.md",
    "docs/interactive/index.html",
    "docs/interactive/styles.css",
    "docs/interactive/app.ts",
    "docs/interactive/app.js",
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
    "scripts/framework_contracts.py",
    "scripts/framework_consistency.py",
    "scripts/framework_compliance.py",
    "scripts/framework_quality_lint.py",
    "scripts/generated_sow_text.py",
    "scripts/integration_registry.py",
    "scripts/link_check.py",
    "scripts/markdown_structure.py",
    "scripts/practice_guide_scaffold.py",
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
    "scripts/codex_automation_registry_lint.py",
    "scripts/automation_orders_lint.py",
    "scripts/authoring_workspace_hygiene.py",
    "scripts/conformance_check.py",
    "scripts/public_export.py",
    "scripts/public_handoff_check.py",
    "scripts/public_handoff_lifecycle.py",
    "scripts/public_release.py",
    "scripts/public_release_check.py",
    "scripts/public_release_state.py",
    "scripts/public_surface.py",
    "scripts/validate_framework.py",
    "scripts/verification_plan.py",
    "scripts/verification_registry.py",
    "annexes/authority.md",
    "annexes/capabilities.md",
    "annexes/security.md",
    "annexes/soul.md",
    "tests/__init__.py",
    "tests/test_public_release_state.py",
    "tests/test_validation_scripts.py",
    "tests/validation_automation_state.py",
    "tests/validation_authoring_workspace_hygiene.py",
    "tests/validation_bootstrap_end_to_end.py",
    "tests/validation_bootstrap_runtime.py",
    "tests/validation_bootstrap_transactions.py",
    "tests/validation_codex_automation_registry.py",
    "tests/validation_conformance.py",
    "tests/validation_evidence_scope.py",
    "tests/validation_framework_contracts.py",
    "tests/validation_framework_quality.py",
    "tests/validation_link_check.py",
    "tests/validation_markdown_structure.py",
    "tests/validation_project_contract_sync.py",
    "tests/validation_project_runtime.py",
    "tests/validation_project_refresh.py",
    "tests/validation_public_handoff.py",
    "tests/validation_public_release_controller.py",
    "tests/validation_publication.py",
    "tests/validation_reference_freshness.py",
    "tests/validation_runtime_compactness.py",
    "tests/validation_safe_io_integrations.py",
    "tests/validation_source_chain.py",
    "tests/validation_source_deep_research.py",
    "tests/validation_source_registry_access.py",
    "tests/validation_test_support.py",
    "tests/validation_url_safety.py",
    "tests/validation_validation_routing.py",
    "assets/framework_runtime_loop.svg",
    "assets/framework_runtime_loop_mobile.svg",
    "assets/reviewer_lane_feedback_loop.svg",
    "assets/reviewer_lane_feedback_loop_mobile.svg",
    "examples/automation_orders.example.json",
    "examples/project_bootstrap_answers.example.json",
    "examples/project_bootstrap_answers.schema.json",
    "examples/project_bootstrap_profile.example.json",
)

PUBLIC_EXCLUDED_PREFIXES = (
    "private/",
    "review_artifacts/",
    "external_review/",
    "notes/",
    "scratch/",
    "transcripts/",
    "session_logs/",
    "captures/",
    "source_dumps/",
    "source_material/",
    "local/",
    "tmp/",
)

PUBLIC_EXCLUDED_DIR_NAMES = (
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyre",
    ".pytype",
    ".hypothesis",
    ".tox",
    ".nox",
    ".venv",
    ".direnv",
    "node_modules",
    ".npm",
    ".pnpm-store",
    ".yarn",
    "dist",
    "build",
)

PUBLIC_EXCLUDED_FILES = (
    ".DS_Store",
    "Thumbs.db",
    "TODO.md",
    "DECISIONS.md",
    "FINDINGS.md",
    "FRAMEWORK_FEEDBACK.md",
    "REVIEWER_LANE_FEEDBACK.md",
    "PRECEDENTS.md",
    "SOURCE_UPDATE.md",
    "SOURCE_PACKS.md",
    "SOURCE_MONITOR_RESEARCHER.md",
    "SOURCE_DEEP_RESEARCH.md",
    "SECURITY_VERIFICATION.md",
    "STATEMENT_OF_WORK.md",
    "AGENT_PROJECT.md",
    "PROJECT_INPUT.json",
    "PROJECT_INSTANCE.json",
    "ARBITRATION.md",
    "AUTOMATION_ORDERS.json",
    "SOUL.md",
    "CAPABILITIES.md",
    "AUTHORITY.md",
    ".env",
    ".envrc",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "pip.conf",
    "credentials.json",
    "token.json",
)
PUBLIC_EXCLUDED_STATE_BASENAMES = (
    "TODO.md",
    "DECISIONS.md",
    "FINDINGS.md",
    "FRAMEWORK_FEEDBACK.md",
    "REVIEWER_LANE_FEEDBACK.md",
    "PRECEDENTS.md",
    "SOURCE_UPDATE.md",
    "SOURCE_PACKS.md",
    "SOURCE_MONITOR_RESEARCHER.md",
    "SOURCE_DEEP_RESEARCH.md",
    "SECURITY_VERIFICATION.md",
    "STATEMENT_OF_WORK.md",
    "AGENT_PROJECT.md",
    "PROJECT_INPUT.json",
    "PROJECT_INSTANCE.json",
    "ARBITRATION.md",
    "AUTOMATION_ORDERS.json",
    "SOUL.md",
    "CAPABILITIES.md",
    "AUTHORITY.md",
)
PUBLIC_EXCLUDED_BASENAMES = (
    ".DS_Store",
    "Thumbs.db",
    ".env",
    ".envrc",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "pip.conf",
    "credentials.json",
    "token.json",
)

PUBLIC_EXCLUDED_FILE_PATTERNS = (
    ".env.*",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.bak",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.odt",
    "*.rtf",
    "*.pages",
    "*.xls",
    "*.xlsx",
    "*.numbers",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite3",
    "client_secret*.json",
    "service-account*.json",
    "google-credentials*.json",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    "internal_*.md",
    "INTERNAL_*.md",
    "*_STATE*.md",
    "*_Commit.md",
)


def path_parts(rel: str) -> tuple[str, ...]:
    return tuple(part for part in rel.split("/") if part)


def is_under_public_root(rel: str) -> bool:
    return any(rel == root or rel.startswith(f"{root}/") for root in PUBLIC_ROOTS)


def is_public_excluded(rel: str) -> bool:
    parts = path_parts(rel)
    name = parts[-1] if parts else rel
    return (
        rel in PUBLIC_EXCLUDED_FILES
        or (name in PUBLIC_EXCLUDED_STATE_BASENAMES and not rel.startswith("project_state_templates/"))
        or name in PUBLIC_EXCLUDED_BASENAMES
        or any(part in PUBLIC_EXCLUDED_DIR_NAMES for part in parts)
        or any(fnmatch.fnmatchcase(name, pattern) for pattern in PUBLIC_EXCLUDED_FILE_PATTERNS)
        or any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in PUBLIC_EXCLUDED_PREFIXES)
    )


def iter_public_root_files(root: Path, public_roots: tuple[str, ...] | None = None) -> list[Path]:
    """Return non-excluded files under declared public roots without descending into excluded dirs."""
    public_roots = PUBLIC_ROOTS if public_roots is None else public_roots
    files: list[Path] = []

    def walk_dir(path: Path) -> None:
        for child in path.iterdir():
            rel = child.relative_to(root).as_posix()
            if child.is_symlink():
                continue
            if child.is_dir():
                if is_public_excluded(rel):
                    continue
                walk_dir(child)
            elif child.is_file() and not is_public_excluded(rel):
                files.append(child)

    for rel in public_roots:
        path = root / rel
        if path.is_symlink():
            continue
        if path.is_file():
            if not is_public_excluded(rel):
                files.append(path)
        elif path.is_dir():
            walk_dir(path)
    return sorted(set(files))


def _local_script_dependencies(root: Path, script: Path) -> set[Path]:
    """Return direct import dependencies that resolve to public local scripts."""

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
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and not is_public_excluded(candidate.relative_to(root).as_posix())
        ):
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

    declared = iter_public_root_files(root, DOWNSTREAM_EFFECTIVE_ROOTS)
    exact = iter_public_root_files(root, DOWNSTREAM_EFFECTIVE_EXACT_FILES)
    python_support = downstream_effective_script_files(root)
    return sorted(set([*declared, *exact, *python_support]))
