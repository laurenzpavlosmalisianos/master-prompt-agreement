"""Semantic checks for compact runtime project-contract projection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import (
    REPO_ROOT,
    SCRIPTS_DIR,
    TEST_FRAMEWORK_RUNNER,
    run_bounded,
)

import bootstrap_transaction  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import project_contract_sync  # noqa: E402
import safe_paths  # noqa: E402


ALWAYS_RUNTIME_DEFINITIONS = {
    "Agent",
    "Bootstrap Mode",
}
STATE_OWNED_RUNTIME_DEFINITIONS = {
    "Automation Orders File",
    "Framework Feedback File",
    "Precedent File",
    "Reviewer Lane Feedback File",
    "Security Verification File",
    "Source Monitor Researcher Brief",
    "Source Packs File",
    "Source Update File",
    "Source Registry Scope",
    "Source Review Cadence",
    "Source Monitor Role",
    "Source Monitor Instruction Sources",
    "Source Monitor Source Data",
    "Source Monitor Boundary",
    "Security Verification Profile Scope",
    "Security Verification Target Policy",
}
OVERRIDE_RUNTIME_DEFINITIONS = {
    "Execution Mode",
}
SECTION_OWNED_RUNTIME_DEFINITIONS = {
    "AI Disclosure": "constraints",
    "Backout Rule": "version_control",
    "Branch Rule": "version_control",
    "Critical Surface Rule": "critical_surfaces",
    "Credential Delivery": "acquisition_boundary",
    "Decision Boundary": "approval_boundaries",
    "Default Review Topology": "review_routing",
    "Dependency Rule": "active_stack",
    "Direct Panel Rules": "review_routing",
    "External Source Rule": "acquisition_boundary",
    "Framework Verification Runner": "framework_verification",
    "Independent Assessment Approval": "review_routing",
    "Language/Runtime Standards": "active_stack",
    "Memory Boundary": "memory_boundary",
    "Package Manager": "active_stack",
    "Reviewer Lane Inventory": "review_routing",
    "Secret Store": "acquisition_boundary",
    "Security Policy File": "active_modules",
    "Source Freshness Rule": "acquisition_boundary",
    "Standing Panel Convocation Approval": "review_routing",
    "Version Control Rule": "version_control",
    "Version Review Rule": "framework_verification",
}
CANONICAL_ONLY_RUNTIME_DEFINITIONS = {"Arbitration Panel"}


def minimal_answers(**overrides: object) -> dict[str, object]:
    return {
        "bootstrap_mode": "minimal",
        "agent": "Agent",
        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
        "project_name": "Demo",
        **overrides,
    }


def sow_definitions(text: str) -> dict[str, str]:
    sections = project_contract_sync.plain_sections(
        text,
        project_contract_sync.SOW_TITLES,
    )
    return project_contract_sync.parse_key_values(sections["Definitions"])


def runtime_sections(text: str) -> dict[str, list[str]]:
    return project_contract_sync.markdown_sections(text)


def runtime_definitions(text: str) -> dict[str, str]:
    return project_contract_sync.parse_key_values(
        runtime_sections(text)["Definitions"],
        bullet=True,
    )


def run_sync(
    answers: dict[str, object],
    *,
    mutate: tuple[str, str, str] | None = None,
    mutations: tuple[tuple[str, str, str], ...] = (),
) -> tuple[int, dict[str, list[str]]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        outputs = project_bootstrap.render_output_files(
            answers,
            "generic",
            "$FRAMEWORK",
        )
        selected_mutations = (*mutations, *((mutate,) if mutate is not None else ()))
        for name, content in outputs.items():
            for mutated_name, before, after in selected_mutations:
                if name == mutated_name:
                    content = content.replace(before, after, 1)
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = run_bounded(
            [
                sys.executable,
                "-B",
                str(SCRIPTS_DIR / "project_contract_sync.py"),
                str(root),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    return result.returncode, json.loads(result.stdout)


class RuntimeCompactnessTests(unittest.TestCase):
    def test_command_identity_is_one_exact_declarative_tuple(self) -> None:
        self.assertEqual(
            (
                ("dev", "Development", "Development", "Development"),
                ("build", "Build", "Build", "Build"),
                (
                    "build_all",
                    "Regenerate all deliverable artifacts from source",
                    "Regenerate artifacts",
                    "Build All",
                ),
                ("test", "Test", "Test", "Test Command"),
                ("lint", "Lint", "Lint", "Lint Command"),
                ("type_check", "Type Check", "Type check", "Type Check Command"),
                ("deploy", "Deploy (if applicable)", "Deploy", "Deploy"),
            ),
            tuple(
                (
                    spec.answer_key,
                    spec.sow_label,
                    spec.runtime_label,
                    spec.deferral_field,
                )
                for spec in project_contract_model.COMMAND_SPECS
            ),
        )

    def test_every_runtime_definition_has_one_explicit_projection_policy(self) -> None:
        by_policy: dict[str, set[str]] = {}
        for spec in project_contract_model.PROJECT_DEFINITION_SPECS:
            by_policy.setdefault(spec.runtime_policy, set()).add(spec.label)

        self.assertEqual(ALWAYS_RUNTIME_DEFINITIONS, by_policy["always"])
        self.assertNotIn("when-active", by_policy)
        self.assertEqual(
            OVERRIDE_RUNTIME_DEFINITIONS,
            by_policy["when-overridden"],
        )
        self.assertEqual(
            set(SECTION_OWNED_RUNTIME_DEFINITIONS),
            by_policy["section-owned"],
        )
        actual_owners = {
            spec.label: spec.runtime_owner
            for spec in project_contract_model.PROJECT_DEFINITION_SPECS
            if spec.runtime_policy == "section-owned"
        }
        self.assertEqual(SECTION_OWNED_RUNTIME_DEFINITIONS, actual_owners)
        self.assertEqual(
            STATE_OWNED_RUNTIME_DEFINITIONS,
            by_policy["state-owned"],
        )
        self.assertEqual(
            CANONICAL_ONLY_RUNTIME_DEFINITIONS,
            by_policy["canonical-only"],
        )
        expected_activation_owners = {
            "Source Registry Scope": "Source Update File",
            "Source Review Cadence": "Source Update File",
            "Source Monitor Role": "Source Monitor Researcher Brief",
            "Source Monitor Instruction Sources": "Source Monitor Researcher Brief",
            "Source Monitor Source Data": "Source Monitor Researcher Brief",
            "Source Monitor Boundary": "Source Monitor Researcher Brief",
            "Security Verification Profile Scope": "Security Verification File",
            "Security Verification Target Policy": "Security Verification File",
        }
        actual_activation_owners = {
            spec.label: project_contract_model.OPTIONAL_STATE_DEFINITION_BY_FLAG[
                spec.active_when
            ]
            for spec in project_contract_model.PROJECT_DEFINITION_SPECS
            if spec.runtime_policy == "state-owned" and spec.active_when is not None
        }
        self.assertEqual(expected_activation_owners, actual_activation_owners)
        for owner_label in set(expected_activation_owners.values()):
            owner = project_contract_model.DEFINITIONS_BY_LABEL[owner_label]
            self.assertEqual("state-owned", owner.runtime_policy)
            self.assertEqual(
                "none",
                project_contract_model.rendered_definition_default(owner),
            )
        self.assertEqual([], project_contract_model.validate_model())

    def test_runtime_owner_ledger_must_match_semantic_projection(self) -> None:
        with mock.patch.dict(
            project_contract_model.RUNTIME_FIELD_OWNERS,
            {"workflows": "project:auxiliary_tools"},
        ):
            errors = project_contract_model.validate_model()

        self.assertTrue(
            any(
                "answer field 'workflows' direct runtime projections" in error
                and "must equal its sole owner 'project:auxiliary_tools'" in error
                for error in errors
            ),
            errors,
        )

        original = project_contract_model.FIELD_PROJECTIONS["workflows"]
        with mock.patch.dict(
            project_contract_model.FIELD_PROJECTIONS,
            {"workflows": (*original, "project:auxiliary_tools")},
        ):
            errors = project_contract_model.validate_model()

        self.assertTrue(
            any(
                "answer field 'workflows' direct runtime projections" in error
                and "must equal its sole owner 'project:active_workflows'" in error
                for error in errors
            ),
            errors,
        )

    def test_default_render_keeps_canonical_definitions_and_compacts_runtime(self) -> None:
        answers = minimal_answers()
        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")

        expected_sow = {
            spec.label
            for spec in project_contract_model.SOW_DEFINITION_SPECS
            if spec.active_when is None
        }
        self.assertEqual(expected_sow, set(sow_definitions(sow)))
        self.assertEqual(
            ALWAYS_RUNTIME_DEFINITIONS,
            set(runtime_definitions(runtime)),
        )
        sections = runtime_sections(runtime)
        active_stack = project_contract_sync.parse_key_values(
            sections["Active Stack"],
            bullet=True,
        )
        self.assertIn("Language/Runtime Standards", active_stack)
        self.assertEqual(
            [project_contract_model.DEFAULT_PERSISTENT_MEMORY_BOUNDARY],
            project_contract_sync.parse_bullets(sections["Memory Boundary"]),
        )
        verification = project_contract_sync.parse_key_values(
            sections["Framework Verification Commands"],
            bullet=True,
        )
        self.assertEqual(
            {
                "Framework reference",
                "Framework Verification Runner",
                "Core conformance",
                "Runner fallback",
            },
            set(verification),
        )
        self.assertIn(
            "$FRAMEWORK/scripts/conformance_check.py --profile core-project --root .",
            verification["Core conformance"],
        )
        self.assertNotIn("scripts/project_contract_sync.py", runtime)
        self.assertNotIn("scripts/project_state_lint.py", runtime)

    def test_runtime_preserves_explicit_none_commands_and_omits_definition_defaults(
        self,
    ) -> None:
        answers = minimal_answers(
            bootstrap_mode="full",
            commands={
                "build": "make build",
                "deploy": "none",
                "dev": "none",
                "test": "make test",
            },
        )
        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")
        sections = runtime_sections(runtime)
        commands = project_contract_sync.parse_key_values(
            sections["Common Commands"],
            bullet=True,
        )

        self.assertEqual(
            {
                "Development": "none",
                "Build": "make build",
                "Regenerate artifacts": "none",
                "Test": "make test",
                "Lint": "none",
                "Type check": "none",
                "Deploy": "none",
            },
            commands,
        )
        self.assertIn("Execution Mode", sow_definitions(sow))
        self.assertNotIn("Execution Mode", runtime_definitions(runtime))
        self.assertEqual(
            [],
            project_contract_sync.common_command_row_errors(
                sections["Common Commands"]
            ),
        )

    def test_runtime_lifecycle_mechanics_have_one_declared_owner(self) -> None:
        runtime = project_bootstrap.render_project_contract(
            minimal_answers(),
            "$FRAMEWORK",
        )
        preamble = runtime.split("## ", 1)[0]
        loading = [
            line
            for line in runtime_sections(runtime)["Loading Rule"]
            if line.strip()
        ]

        self.assertEqual(1, preamble.count(project_contract_model.PROJECT_PREAMBLE_RULE))
        self.assertEqual(1, preamble.count(project_contract_model.PROJECT_AUTHORITY_TEXT))
        self.assertNotIn("retained-input/receipt", preamble)
        self.assertNotIn("RETIRE-MUTABLE-####", runtime)
        self.assertNotIn("exact-preimage backout bundle", runtime)
        self.assertIn("task_orders/framework_refresh.md", runtime)
        self.assertEqual(
            list(project_contract_model.PROJECT_LOADING_RULE_LINES),
            loading,
        )
        for line in project_contract_model.PROJECT_LOADING_RULE_LINES:
            self.assertEqual(1, runtime.count(line), line)

    def test_runtime_excludes_canonical_only_rationale_and_review_detail(self) -> None:
        answers = minimal_answers(
            bootstrap_mode="full",
            code_review_checklist=["CANONICAL-REVIEW-DETAIL"],
            file_structure=["CANONICAL-FILE-STRUCTURE-DETAIL"],
            recitals=["CANONICAL-PROJECT-RATIONALE"],
        )
        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")

        for value in (
            "CANONICAL-REVIEW-DETAIL",
            "CANONICAL-FILE-STRUCTURE-DETAIL",
            "CANONICAL-PROJECT-RATIONALE",
        ):
            self.assertIn(value, sow)
            self.assertNotIn(value, runtime)
        routes = project_contract_sync.parse_bullets(
            runtime_sections(runtime)["Canonical Detail Routes"]
        )
        self.assertEqual(
            {
                project_contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES[
                    "code_review_checklist"
                ],
                project_contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES[
                    "file_structure"
                ],
            },
            set(routes),
        )

    def test_pattern_and_custom_review_routes_self_conform_and_cannot_disappear(
        self,
    ) -> None:
        panel = {
            "seats": [
                {
                    "model": "review model",
                    "role": "independent reviewer",
                    "focus": "contract architecture",
                }
            ],
            "quorum": "one available seat",
            "recommendation_threshold": "one supported recommendation",
            "failure_handling": "report unavailable evidence",
            "tie_handling": "record no recommendation",
            "no_majority_handling": "record no recommendation",
            "abstention_handling": "record the abstention",
            "unavailable_panelist_handling": "reconstitute before review",
            "binding_effect": "recommendation only",
            "accountable_owner": "User",
            "appeal_or_override_path": "User decision",
        }
        answers = minimal_answers(
            arbitration_panel=panel,
            pattern_sources=["src/example.py — parsing pattern — illustrative"],
        )

        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")
        self.assertIn("src/example.py", sow)
        self.assertNotIn("src/example.py", runtime)
        self.assertIn(
            project_contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES[
                "pattern_sources"
            ],
            runtime,
        )
        self.assertIn(project_contract_model.ARBITRATION_PANEL_RUNTIME_ROUTE, runtime)
        returncode, payload = run_sync(answers)
        self.assertEqual(0, returncode, payload)

        for route, expected_error in (
            (
                project_contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES[
                    "pattern_sources"
                ],
                "Canonical Detail Routes drift between SOW and project contract",
            ),
            (
                project_contract_model.ARBITRATION_PANEL_RUNTIME_ROUTE,
                "Review Routing drift between SOW and project contract",
            ),
        ):
            with self.subTest(route=route):
                returncode, payload = run_sync(
                    answers,
                    mutate=("AGENT_PROJECT.md", f"- {route}\n", ""),
                )
                self.assertEqual(1, returncode, payload)
                self.assertIn(expected_error, payload["errors"])

    def test_active_features_and_overrides_remain_projected(self) -> None:
        answers = minimal_answers(
            dependency_posture="no-external-dependencies",
            include_precedents=True,
            include_source_packs=True,
            include_source_update=True,
            persistent_memory_boundary="Project memory may be written only after approval.",
        )
        outputs = project_bootstrap.render_output_files(
            answers,
            "generic",
            "$FRAMEWORK",
        )
        runtime = outputs["AGENT_PROJECT.md"]
        definitions = runtime_definitions(runtime)

        self.assertEqual(ALWAYS_RUNTIME_DEFINITIONS, set(definitions))
        self.assertIn("PRECEDENTS.md", outputs)
        self.assertIn("SOURCE_PACKS.md", outputs)
        self.assertIn("SOURCE_UPDATE.md", outputs)
        self.assertIn(
            "- Source Registry Scope:",
            outputs["SOURCE_UPDATE.md"],
        )
        self.assertIn(
            "- Default Review Cadence:",
            outputs["SOURCE_UPDATE.md"],
        )
        self.assertNotIn("Source Registry Scope:", runtime)
        self.assertNotIn("Source Review Cadence:", runtime)
        active_stack = project_contract_sync.parse_key_values(
            runtime_sections(runtime)["Active Stack"],
            bullet=True,
        )
        self.assertIn("Dependency Rule", active_stack)
        self.assertNotIn("Memory Boundary", definitions)
        self.assertIn(
            "Project memory may be written only after approval.",
            project_contract_sync.parse_bullets(
                runtime_sections(runtime)["Memory Boundary"]
            ),
        )

    def test_source_update_defaults_and_overrides_self_conform(self) -> None:
        cases = (
            minimal_answers(
                include_source_packs=True,
                include_source_update=True,
            ),
            minimal_answers(
                include_source_packs=True,
                include_source_update=True,
                version_review_policy="Review pinned versions at each release boundary.",
            ),
        )
        for answers in cases:
            with self.subTest(version_review=answers.get("version_review_policy")):
                returncode, payload = run_sync(answers)
                self.assertEqual(0, returncode, payload)
                self.assertEqual([], payload["errors"])

    def test_inactive_conditional_definitions_cannot_be_injected_into_either_surface(self) -> None:
        injected = (
            "Source Update File: none\n",
            "Source Update File: none\n"
            "Source Registry Scope: injected scope\n"
            "Source Review Cadence: injected cadence\n",
        )
        runtime_injected = (
            "## Definitions\n",
            "## Definitions\n\n"
            "- Source Registry Scope: injected scope\n"
            "- Source Review Cadence: injected cadence\n",
        )
        returncode, payload = run_sync(
            minimal_answers(),
            mutations=(
                ("STATEMENT_OF_WORK.md", *injected),
                ("AGENT_PROJECT.md", *runtime_injected),
            ),
        )

        self.assertEqual(1, returncode, payload)
        for key in ("Source Registry Scope", "Source Review Cadence"):
            self.assertIn(
                f"STATEMENT_OF_WORK.md Definitions contains inactive conditional key: {key}",
                payload["errors"],
            )
            self.assertTrue(
                any(
                    error.startswith(
                        f"{key} SOW Definitions -> AGENT_PROJECT.md Definitions drift"
                    )
                    for error in payload["errors"]
                ),
                payload,
            )

    def test_sync_rejects_omitted_or_misplaced_owned_rows_and_unbacked_rows(self) -> None:
        cases = (
            (
                minimal_answers(dependency_posture="no-external-dependencies"),
                (
                    "AGENT_PROJECT.md",
                    "- Dependency Rule: no-external-dependencies "
                    "(governs adding new dependencies, not already-approved project dependencies)\n",
                    "",
                ),
                "Dependency Rule must appear exactly once in AGENT_PROJECT.md Active Stack",
            ),
            (
                minimal_answers(),
                (
                    "AGENT_PROJECT.md",
                    "## Active Stack\n",
                    "## Active Stack\n\n- Dependency Rule: justify-external-dependencies "
                    "(governs adding new dependencies, not already-approved project dependencies)\n",
                ),
                "Dependency Rule must be omitted from the runtime projection when inactive or model-default",
            ),
            (
                minimal_answers(),
                (
                    "AGENT_PROJECT.md",
                    "## Definitions\n",
                    "## Definitions\n\n- Unknown Runtime Fact: value\n",
                ),
                "AGENT_PROJECT.md Definitions contains unbacked key: Unknown Runtime Fact",
            ),
            (
                minimal_answers(),
                (
                    "STATEMENT_OF_WORK.md",
                    "User: User\n",
                    "",
                ),
                "STATEMENT_OF_WORK.md Definitions missing required key: User",
            ),
        )
        for answers, mutation, expected in cases:
            with self.subTest(expected=expected):
                returncode, payload = run_sync(answers, mutate=mutation)
                self.assertEqual(1, returncode, payload)
                matching = [
                    error for error in payload["errors"] if expected in error
                ]
                self.assertEqual(1, len(matching), payload)

    def test_workflow_runtime_index_omits_sequence_but_retains_active_controls(self) -> None:
        answers = minimal_answers(
            workflows=[
                {
                    "name": "release",
                    "sequence": "CANONICAL-WORKFLOW-SEQUENCE",
                    "when": "before release (candidate)",
                    "owner": "coordinator",
                    "verifier_gate": "release checks pass",
                    "stop_condition": "first failed gate",
                }
            ]
        )

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")
        self.assertIn("CANONICAL-WORKFLOW-SEQUENCE", sow)
        self.assertNotIn("CANONICAL-WORKFLOW-SEQUENCE", runtime)
        self.assertIn(
            "release: load STATEMENT_OF_WORK.md Workflows entry when before release "
            "(candidate) — owner: coordinator — verifier: release checks pass — "
            "stop: first failed gate",
            runtime,
        )
        returncode, payload = run_sync(answers)
        self.assertEqual(0, returncode, payload)
        returncode, payload = run_sync(
            answers,
            mutate=(
                "AGENT_PROJECT.md",
                "verifier: release checks pass",
                "verifier: release checks fail",
            ),
        )
        self.assertEqual(1, returncode, payload)
        self.assertIn(
            "Active Workflows drift between SOW and project contract",
            payload["errors"],
        )

    def test_auxiliary_runtime_index_omits_protocol_detail_but_retains_route_facts(
        self,
    ) -> None:
        tool = {
            "name": "Review Lane",
            "purpose": "Independent bounded review",
            "invocation": "CANONICAL-TOOL-INVOCATION",
            "source": "project-owned integration",
            "owner": "project",
            "transport": "native extension",
            "permissions": "read-only project files",
            "data_boundary": "project files only",
            "effect_boundary": "read-only report generation",
            "persistence": "task-scoped unless explicitly saved",
            "trust": "project-owned configuration",
            "credential_source": "none",
            "when_to_use": "when an independent review is required",
            "approval": "none",
            "control_role": "none",
        }
        answers = minimal_answers(auxiliary_tools=[tool])

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        runtime = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")
        self.assertIn("CANONICAL-TOOL-INVOCATION", sow)
        self.assertNotIn("CANONICAL-TOOL-INVOCATION", runtime)
        self.assertIn(
            "Review Lane — Independent bounded review — "
            "load STATEMENT_OF_WORK.md Auxiliary Tools entry before use — "
            "use when: when an independent review is required — approval: none — "
            "control role: none",
            runtime,
        )
        returncode, payload = run_sync(answers)
        self.assertEqual(0, returncode, payload)
        returncode, payload = run_sync(
            answers,
            mutate=(
                "AGENT_PROJECT.md",
                "Independent bounded review",
                "Different review purpose",
            ),
        )
        self.assertEqual(1, returncode, payload)
        self.assertIn(
            "Auxiliary Tools drift between SOW and project contract",
            payload["errors"],
        )

    def test_invalid_answer_shapes_do_not_look_resolved_to_deferral_check(self) -> None:
        cases = (
            ("Tech stack", {"tech_stack": {"unexpected": "mapping"}}),
            ("In scope", {"in_scope": [{"unexpected": "mapping"}]}),
            ("Test Command", {"commands": {"test": ["not", "a", "command"]}}),
            (
                "Deliverables and Acceptance Evidence",
                {
                    "deliverables": [
                        {
                            "description": ["not", "text"],
                            "test": "TBD",
                            "pass_criteria": "TBD",
                        }
                    ]
                },
            ),
        )
        for field_name, malformed in cases:
            answers = minimal_answers(
                **malformed,
                minimal_deferrals=[
                    project_bootstrap.minimal_deferral_record(field_name)
                ],
            )
            with self.subTest(field=field_name):
                errors = project_bootstrap.validate_answers(answers)
                self.assertTrue(errors)
                self.assertFalse(
                    any("defers resolved canonical field" in error for error in errors),
                    errors,
                )

    def test_generated_asset_write_refuses_a_symlink_without_partial_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "model-root"
            root.mkdir()
            original = {
                relative: f"original:{relative}\n"
                for relative in project_contract_model.GENERATED_ASSET_PATHS
            }
            for relative, content in original.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            outside = Path(temp_dir) / "outside.md"
            outside.write_text("outside must remain unchanged\n", encoding="utf-8")
            symlink_target = root / project_contract_model.SOW_BLUEPRINT_PATH
            symlink_target.unlink()
            symlink_target.symlink_to(outside)

            with self.assertRaises(bootstrap_transaction.BootstrapTransactionError):
                project_contract_model.write_generated_assets(root)

            self.assertEqual(
                "outside must remain unchanged\n",
                outside.read_text(encoding="utf-8"),
            )
            self.assertTrue(symlink_target.is_symlink())
            for relative, content in original.items():
                if relative == project_contract_model.SOW_BLUEPRINT_PATH:
                    continue
                self.assertEqual(content, (root / relative).read_text(encoding="utf-8"))

    def test_generated_asset_write_rolls_back_a_partial_staging_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "model-root"
            root.mkdir()
            original = {
                relative: f"original:{relative}\n"
                for relative in project_contract_model.GENERATED_ASSET_PATHS
            }
            for relative, content in original.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            real_stage = bootstrap_transaction._stage_output
            call_count = 0

            def fail_second_stage(record: object, index: int) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("injected staging failure")
                real_stage(record, index)  # type: ignore[arg-type]

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_stage_output",
                    side_effect=fail_second_stage,
                ),
                self.assertRaises(bootstrap_transaction.BootstrapTransactionError),
            ):
                project_contract_model.write_generated_assets(root)

            self.assertEqual(
                original,
                {
                    relative: (root / relative).read_text(encoding="utf-8")
                    for relative in project_contract_model.GENERATED_ASSET_PATHS
                },
            )

    def test_generated_asset_check_uses_bounded_no_follow_reads(self) -> None:
        target_relative = project_contract_model.SOW_BLUEPRINT_PATH
        expected_target = project_contract_model.generated_assets()[target_relative]

        for mutation in ("symlink", "fifo", "oversized", "invalid-utf8"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "model-root"
                root.mkdir()
                for relative, content in project_contract_model.generated_assets().items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                target = root / target_relative
                target.unlink()
                if mutation == "symlink":
                    outside = Path(temp_dir) / "equal-content.md"
                    outside.write_text(expected_target, encoding="utf-8")
                    target.symlink_to(outside)
                elif mutation == "fifo":
                    os.mkfifo(target)
                elif mutation == "oversized":
                    target.write_bytes(
                        b"x" * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                    )
                else:
                    target.write_bytes(b"\xff")

                errors = project_contract_model.generated_asset_errors(root)

                self.assertTrue(
                    any(
                        f"could not be read safely: {target_relative}" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_generated_asset_check_preserves_missing_and_stale_diagnostics(self) -> None:
        for mutation, expected_fragment in (
            ("missing", "generated project-contract asset is missing"),
            ("stale", "generated project-contract asset is stale"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "model-root"
                root.mkdir()
                for relative, content in project_contract_model.generated_assets().items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                target = root / project_contract_model.SOW_BLUEPRINT_PATH
                if mutation == "missing":
                    target.unlink()
                else:
                    target.write_text("stale\n", encoding="utf-8")

                errors = project_contract_model.generated_asset_errors(root)

                self.assertTrue(
                    any(expected_fragment in error for error in errors),
                    errors,
                )


if __name__ == "__main__":
    unittest.main()
