"""Project bootstrap validation and rendering tests."""

from __future__ import annotations

import ast
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from typing import cast

from tests.validation_test_support import (
    REPO_ROOT,
    SCRIPTS_DIR,
    TEST_FRAMEWORK_RUNNER,
    compile_adjacent_bytecode,
    run_bounded,
    valid_automation_job,
)

import automation_orders_lint  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import project_contract_sync  # noqa: E402
import render_integrations  # noqa: E402
import safe_paths  # noqa: E402


class BootstrapRenderingTests(unittest.TestCase):
    def test_authority_modules_require_utf8_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AUTHORITY.md").write_bytes(b"authority:\xff\n")

            records, errors = project_bootstrap.authority_module_digest_records(
                {"annexes": {"authority": "AUTHORITY.md"}},
                root,
            )

        self.assertEqual([], records)
        self.assertIn("UTF-8", " ".join(errors))

    def test_authority_modules_reject_output_ancestor_collisions(self) -> None:
        cases = (
            ("authority", "authority/generated.md"),
            ("authority/policy.md", "authority"),
        )
        for authority_path, output_path in cases:
            with self.subTest(
                authority_path=authority_path,
                output_path=output_path,
            ), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                candidate = root / authority_path
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("# Authority\n", encoding="utf-8")

                _records, errors = project_bootstrap.authority_module_digest_records(
                    {"annexes": {"authority": authority_path}},
                    root,
                    forbidden_paths=frozenset({output_path}),
                )

            self.assertTrue(errors)
            self.assertIn("ancestors or descendants", " ".join(errors))

    def test_project_contract_model_rejects_invalid_auxiliary_control_role_sets(self) -> None:
        with mock.patch.object(
            project_contract_model,
            "AUXILIARY_CONTROL_COVERAGE_ROLES",
            frozenset(),
        ):
            empty_errors = project_contract_model.validate_model()
        with mock.patch.object(
            project_contract_model,
            "AUXILIARY_CONTROL_COVERAGE_ROLES",
            frozenset({"none", "unknown"}),
        ):
            invalid_errors = project_contract_model.validate_model()

        self.assertIn(
            "auxiliary control coverage roles must not be empty",
            empty_errors,
        )
        self.assertIn(
            "auxiliary control coverage roles must be declared control roles",
            invalid_errors,
        )
        self.assertIn(
            "auxiliary non-control role must not require control coverage",
            invalid_errors,
        )

    def test_project_contract_model_requires_boolean_optional_state_flags(self) -> None:
        mutated = (
            replace(project_contract_model.OPTIONAL_STATE_SPECS[0], flag="agent"),
            *project_contract_model.OPTIONAL_STATE_SPECS[1:],
        )

        with mock.patch.object(project_contract_model, "OPTIONAL_STATE_SPECS", mutated):
            errors = project_contract_model.validate_model()

        self.assertIn(
            "optional-state declaration 'FINDINGS.md' has unknown/non-boolean flag: 'agent'",
            errors,
        )

    def test_project_contract_model_requires_closed_optional_state_partitions(self) -> None:
        mutated = (
            replace(
                project_contract_model.OPTIONAL_STATE_SPECS[0],
                partition=cast(
                    project_contract_model.OptionalStatePartition,
                    "archival",
                ),
            ),
            *project_contract_model.OPTIONAL_STATE_SPECS[1:],
        )

        with mock.patch.object(project_contract_model, "OPTIONAL_STATE_SPECS", mutated):
            errors = project_contract_model.validate_model()

        self.assertIn(
            "optional-state declaration 'FINDINGS.md' has unsupported receipt "
            "partition: 'archival'",
            errors,
        )
        self.assertIn(
            "optional-state declarations lack a supported receipt partition: "
            "['FINDINGS.md']",
            errors,
        )

    def test_project_contract_model_requires_boolean_and_matching_definition_gates(self) -> None:
        definitions = list(project_contract_model.DEFINITION_SPECS)
        source_registry_index = next(
            index
            for index, spec in enumerate(definitions)
            if spec.label == "Source Registry Scope"
        )
        source_cadence_index = next(
            index
            for index, spec in enumerate(definitions)
            if spec.label == "Source Review Cadence"
        )
        definitions[source_registry_index] = replace(
            definitions[source_registry_index],
            active_when="include_findings",
        )
        definitions[source_cadence_index] = replace(
            definitions[source_cadence_index],
            active_when="agent",
        )

        with mock.patch.object(
            project_contract_model,
            "DEFINITION_SPECS",
            tuple(definitions),
        ):
            errors = project_contract_model.validate_model()

        self.assertIn(
            "Definition 'Source Registry Scope' activation gate 'include_findings' does "
            "not match answer field 'source_registry_scope' activation gate "
            "'include_source_update'",
            errors,
        )
        self.assertIn(
            "Definition 'Source Review Cadence' has unknown/non-boolean active flag: 'agent'",
            errors,
        )

    def test_project_contract_model_rejects_duplicate_optional_state_definition_labels(self) -> None:
        mutated = (
            replace(
                project_contract_model.OPTIONAL_STATE_SPECS[0],
                definition_label="Precedent File",
            ),
            *project_contract_model.OPTIONAL_STATE_SPECS[1:],
        )

        with mock.patch.object(project_contract_model, "OPTIONAL_STATE_SPECS", mutated):
            errors = project_contract_model.validate_model()

        self.assertIn(
            "duplicate optional-state Definition labels: ['Precedent File']",
            errors,
        )
        self.assertIn(
            "optional-state Definition 'Precedent File' resolves to 2 optional-state declarations",
            errors,
        )

    def test_project_contract_model_requires_bidirectional_optional_state_definitions(self) -> None:
        missing_definition = tuple(
            spec
            for spec in project_contract_model.DEFINITION_SPECS
            if spec.label != "Precedent File"
        )
        orphan_definition = project_contract_model._definition(
            "Orphan Optional State",
            "fixture",
            ("sow", "project"),
            projection="optional-state",
            default="none",
        )

        with mock.patch.object(
            project_contract_model,
            "DEFINITION_SPECS",
            (*missing_definition, orphan_definition),
        ):
            errors = project_contract_model.validate_model()

        self.assertIn(
            "optional-state declaration 'PRECEDENTS.md' Definition label 'Precedent File' "
            "resolves to 0 optional-state Definitions",
            errors,
        )
        self.assertIn(
            "optional-state Definition 'Orphan Optional State' resolves to 0 optional-state declarations",
            errors,
        )

    def test_project_contract_model_requires_exact_state_definition_projection_coverage(
        self,
    ) -> None:
        missing_boundary = tuple(
            spec
            for spec in project_contract_model.STATE_DEFINITION_PROJECTION_SPECS
            if not (
                spec.filename == "SOURCE_MONITOR_RESEARCHER.md"
                and spec.definition_label == "Source Monitor Boundary"
            )
        )
        with mock.patch.object(
            project_contract_model,
            "STATE_DEFINITION_PROJECTION_SPECS",
            missing_boundary,
        ):
            missing_errors = project_contract_model.validate_model()

        surplus_projection = project_contract_model.StateDefinitionProjectionSpec(
            "source_monitor",
            "SOURCE_MONITOR_RESEARCHER.md",
            "Project Configuration",
            "Version Review Rule",
            "Version Review Rule",
        )
        with mock.patch.object(
            project_contract_model,
            "STATE_DEFINITION_PROJECTION_SPECS",
            (
                *project_contract_model.STATE_DEFINITION_PROJECTION_SPECS,
                surplus_projection,
            ),
        ):
            surplus_errors = project_contract_model.validate_model()

        self.assertIn(
            "state Definition projections are missing definition-parity placeholder "
            "coverage: [('SOURCE_MONITOR_RESEARCHER.md', 'Source Monitor Boundary')]",
            missing_errors,
        )
        self.assertIn(
            "state Definition projections have no matching definition-parity placeholder: "
            "[('SOURCE_MONITOR_RESEARCHER.md', 'Version Review Rule')]",
            surplus_errors,
        )

    def test_generation_source_provenance_covers_direct_semantic_and_transform_owners(self) -> None:
        cases = (
            (
                "contracts/STATEMENT_OF_WORK.md",
                None,
                (
                    "master_service_agreement.md",
                    "scripts/project_contract_model.py",
                    "scripts/integration_registry.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
            (
                "contracts/AGENT_PROJECT.md",
                None,
                (
                    "scripts/project_contract_model.py",
                    "scripts/integration_registry.py",
                    "scripts/safe_paths.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
            (
                "contracts/FINDINGS.md",
                None,
                (
                    "project_state_templates/FINDINGS.md",
                    "scripts/project_contract_model.py",
                    "scripts/project_state_identity.py",
                    "scripts/integration_registry.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
            (
                "contracts/SOURCE_MONITOR_RESEARCHER.md",
                None,
                (
                    "project_state_templates/SOURCE_MONITOR_RESEARCHER.md",
                    "scripts/project_contract_model.py",
                    "scripts/project_state_identity.py",
                    "scripts/integration_registry.py",
                    "scripts/safe_paths.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
            (
                "contracts/AUTOMATION_ORDERS.json",
                None,
                (
                    "project_state_templates/AUTOMATION_ORDERS.json",
                    "scripts/project_contract_model.py",
                    "scripts/project_state_identity.py",
                    "scripts/safe_paths.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
            (
                "AGENTS.md",
                "generic",
                (
                    "integrations/templates/generic/AGENTS.md.template",
                    "integrations/registry.json",
                    "scripts/project_contract_model.py",
                    "scripts/integration_registry.py",
                    "scripts/safe_paths.py",
                    "scripts/project_bootstrap.py",
                ),
            ),
        )

        for output, runtime, expected in cases:
            with self.subTest(output=output):
                self.assertEqual(
                    expected,
                    project_bootstrap.generation_sources_for_output(output, runtime),
                )

    def test_source_deep_research_template_is_manual_and_not_bootstrapped(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
        }

        self.assertEqual(
            "project_state_templates/SOURCE_DEEP_RESEARCH.md",
            project_bootstrap.MANUAL_STATE_TEMPLATES["SOURCE_DEEP_RESEARCH.md"],
        )
        self.assertNotIn("SOURCE_DEEP_RESEARCH.md", project_bootstrap.STATE_TEMPLATES)
        self.assertNotIn(
            "SOURCE_DEEP_RESEARCH.md",
            project_bootstrap.optional_state_names(answers),
        )
        self.assertNotIn(
            "SOURCE_DEEP_RESEARCH.md",
            project_bootstrap.render_output_files(answers, "generic", "$FRAMEWORK"),
        )

    def test_optional_state_receipt_partitions_follow_model_declarations(self) -> None:
        for spec in project_contract_model.OPTIONAL_STATE_SPECS:
            with self.subTest(state=spec.filename, partition=spec.partition):
                answers = {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    spec.flag: True,
                }

                managed, immutable, mutable = (
                    project_bootstrap.project_instance_file_sets(
                        answers=answers,
                        runtime="generic",
                        project_kind="downstream",
                        contract_root_ref=".",
                    )
                )

                selected_partition = (
                    immutable if spec.partition == "immutable" else mutable
                )
                other_partition = (
                    mutable if spec.partition == "immutable" else immutable
                )
                self.assertIn(spec.filename, managed)
                self.assertIn(spec.filename, selected_partition)
                self.assertNotIn(spec.filename, other_partition)
                self.assertEqual(
                    spec.partition == "mutable",
                    spec.filename
                    in project_bootstrap.mutable_state_output_names(answers),
                )

    def test_project_bootstrap_rejects_prompt_boundary_scalar_injection(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo</assistant>",
            }
        )

        self.assertIn(
            "project_name must be plain text without control characters or angle brackets",
            errors,
        )
        self.assertIn(
            "bootstrap answer key 'project_name' must not contain framework or prompt-boundary tags",
            errors,
        )

    def test_project_bootstrap_rejects_prompt_boundary_list_injection(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "constraints": ["Stay small </system>"],
                "verification_profiles": ["fast\x00check"],
            }
        )

        self.assertIn(
            "constraints[1] must not contain framework or prompt-boundary tags",
            errors,
        )
        self.assertIn(
            "verification_profiles[1] must not contain control characters",
            errors,
        )

    def test_project_bootstrap_rejects_runtime_imports_answer_key(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "runtime_imports": {"practice_guides": ["practice_guides/security_audit.md"]},
            }
        )

        self.assertIn("unknown bootstrap answer key: runtime_imports", errors)

    def test_project_bootstrap_rejects_legacy_language_standard_key(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "language_standard": "Python 3.14",
            }
        )

        self.assertIn("unknown bootstrap answer key: language_standard", errors)

    def test_project_bootstrap_validates_source_packs_boolean(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_source_packs": "false",
            }
        )

        self.assertIn("bootstrap answer key 'include_source_packs' must be boolean", errors)

    def test_project_bootstrap_validates_reviewer_lane_feedback_boolean(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_reviewer_lane_feedback": "yes",
            }
        )

        self.assertIn("bootstrap answer key 'include_reviewer_lane_feedback' must be boolean", errors)

    def test_project_bootstrap_validates_security_policy_file_choice(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "security_policy_file": "SECURITY.txt",
            }
        )

        self.assertIn(
            "security_policy_file must be one of: inline in this SOW, project SECURITY.md, none",
            errors,
        )

    def test_project_bootstrap_renders_security_policy_file_choice(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "security_policy_file": "project SECURITY.md",
        }

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        contract = project_bootstrap.render_project_contract(answers)

        self.assertIn("Security Policy File: project SECURITY.md", sow)
        self.assertIn("- Security Policy File: project SECURITY.md", contract)

    def test_project_bootstrap_defaults_to_no_project_security_policy(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        contract = project_bootstrap.render_project_contract(answers)
        self.assertIn("Security Policy File: none", sow)
        self.assertNotIn("- Security Policy File: none", contract)
        self.assertNotIn("\nSecurity Policy\n", sow)
        self.assertNotIn("\n## Security Policy\n", contract)

    def test_project_bootstrap_default_source_monitor_role_supports_explicit_delegation(self) -> None:
        sow = project_bootstrap.render_sow(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_source_monitor_researcher": True,
            }
        )

        self.assertIn(
            "Role: observe-only recurring or explicitly delegated source-discovery brief",
            sow,
        )
        self.assertIn("project authority owns the cadence or trigger", sow)
        self.assertIn("project local_overlays/ instruction files when present", sow)

    def test_project_bootstrap_rejects_fields_for_inactive_optional_surfaces(self) -> None:
        cases: tuple[tuple[str, object, str], ...] = (
            ("source_registry_scope", "runtime sources", "include_source_update"),
            (
                "source_monitor_role",
                "observe-only reviewer",
                "include_source_monitor_researcher",
            ),
            (
                "security_verification_profile_scope",
                "project source",
                "include_security_verification",
            ),
            ("automation_orders", {}, "include_automation_orders"),
        )

        for field, value, flag in cases:
            with self.subTest(field=field):
                errors = project_bootstrap.validate_answers(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        field: value,
                    }
                )
                self.assertIn(
                    f"bootstrap answer key '{field}' requires {flag} to be true",
                    errors,
                )

    def test_source_monitor_default_data_tracks_enabled_source_files(self) -> None:
        cases: tuple[tuple[dict[str, object], str], ...] = (
            ({}, "none"),
            ({"include_source_packs": True}, "SOURCE_PACKS.md"),
            (
                {"include_source_packs": True, "include_source_update": True},
                "SOURCE_PACKS.md / SOURCE_UPDATE.md",
            ),
            (
                {
                    "include_source_packs": True,
                    "source_monitor_source_data": ["approved/sources.json"],
                },
                "approved/sources.json",
            ),
        )

        for answers, expected in cases:
            with self.subTest(answers=answers):
                self.assertEqual(
                    expected,
                    project_bootstrap.source_monitor_source_data(answers),
                )

    def test_project_bootstrap_requires_and_projects_inline_security_policy_terms(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "security_policy_file": "inline in this SOW",
        }
        errors = project_bootstrap.validate_answers(answers)
        self.assertIn(
            "security_policy_file 'inline in this SOW' requires at least one security_policy_terms entry",
            errors,
        )

        answers["security_policy_terms"] = [
            "Production credentials may be delivered only through the approved project secret store."
        ]
        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        contract = project_bootstrap.render_project_contract(answers)
        sow_sections = project_contract_sync.plain_sections(
            sow,
            project_contract_sync.SOW_TITLES,
        )
        contract_sections = project_contract_sync.markdown_sections(contract)
        self.assertEqual(
            {"production credentials may be delivered only through the approved project secret store."},
            {
                project_contract_sync.normalize(item)
                for item in project_contract_sync.parse_bullets(sow_sections["Security Policy"])
            },
        )
        self.assertEqual(
            [],
            project_contract_sync.inline_security_policy_errors(
                sow_sections,
                contract_sections,
                project_contract_sync.parse_key_values(sow_sections["Definitions"]),
            ),
        )

    def test_project_bootstrap_projects_standalone_panel_convocation_approval(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "standing_panel_convocation_approval": "Yes, limited to release-blocking disputes",
        }

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        contract = project_bootstrap.render_project_contract(answers)
        self.assertIn(
            "Standing Panel Convocation Approval: Yes, limited to release-blocking disputes",
            sow,
        )
        self.assertIn(
            "- Standing Panel Convocation Approval: Yes, limited to release-blocking disputes",
            contract,
        )

    def test_project_bootstrap_rejects_noncanonical_governance_enums(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "independent_assessment_approval": "optional",
                "standing_panel_convocation_approval": "Yesterday",
            }
        )

        self.assertIn(
            "independent_assessment_approval must be one of: Autonomous, Required",
            errors,
        )
        self.assertIn(
            "standing_panel_convocation_approval must be 'No', 'Yes', or start with 'Yes,'",
            errors,
        )

    def test_project_bootstrap_requires_explicit_bootstrap_mode(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "agent": "Agent",
                "project_name": "Demo",
            }
        )

        self.assertIn("missing required bootstrap answer key: bootstrap_mode", errors)
        self.assertIn("bootstrap_mode must be 'full' or 'minimal'", errors)

    def test_project_bootstrap_rejects_empty_required_values(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "",
                "project_name": "   ",
            }
        )

        self.assertIn("required bootstrap answer key 'agent' must not be empty", errors)
        self.assertIn("required bootstrap answer key 'project_name' must not be empty", errors)

    def test_project_bootstrap_requires_source_packs_for_source_update(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_source_update": True,
            }
        )

        self.assertIn(
            "include_source_update requires include_source_packs because SOURCE_UPDATE.md references SOURCE_PACKS.md",
            errors,
        )

    def test_project_bootstrap_requires_jobs_for_enabled_automation_orders(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_automation_orders": True,
            }
        )

        self.assertIn(
            "include_automation_orders requires automation_orders.jobs with at least one concrete job",
            errors,
        )

    def test_project_bootstrap_rejects_custom_automation_orders_filename(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "include_automation_orders": True,
                "automation_orders": {"file": "ORDERS.json", "jobs": [valid_automation_job()]},
            }
        )

        self.assertIn("unknown automation_orders key: file", errors)

    def test_project_bootstrap_rejects_noncanonical_automation_backend_slug(self) -> None:
        for backend in ("Cron", "bad backend", "-cron", "cron/primary"):
            with self.subTest(backend=backend):
                errors = project_bootstrap.validate_answers(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "automation_orders": {
                            "preferred_backend": backend,
                            "jobs": [valid_automation_job()],
                        },
                    }
                )
                self.assertIn(
                    "automation_orders.preferred_backend must be one lowercase safe slug",
                    errors,
                )

    def test_project_bootstrap_accepts_concrete_automation_jobs(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_automation_orders": True,
            "automation_orders": {"jobs": [valid_automation_job()]},
        }

        self.assertEqual(
            [],
            project_bootstrap.validate_answers(
                answers,
                automation_project_root=REPO_ROOT,
                automation_manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
                require_existing_automation_project_root=False,
            ),
        )
        outputs = project_bootstrap.render_output_files(answers, "generic", "$FRAMEWORK")
        manifest = json.loads(outputs["AUTOMATION_ORDERS.json"])
        self.assertEqual(automation_orders_lint.SCHEMA_VERSION, manifest["schema_version"])
        self.assertEqual("unspecified", manifest["preferred_backend"])
        self.assertEqual([valid_automation_job()], manifest["jobs"])

    def test_project_bootstrap_persists_preferred_automation_backend(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_automation_orders": True,
            "automation_orders": {
                "preferred_backend": "cron",
                "jobs": [valid_automation_job()],
            },
        }

        outputs = project_bootstrap.render_output_files(
            answers,
            "generic",
            "$FRAMEWORK",
        )
        manifest = json.loads(outputs["AUTOMATION_ORDERS.json"])

        self.assertEqual("cron", manifest["preferred_backend"])
        self.assertIn("Preferred Scheduler Backend: cron", outputs["STATEMENT_OF_WORK.md"])

    def test_project_bootstrap_renders_schema_v7_automation_classifications(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "reviewer_runtime_class": "deterministic_tool",
                "reviewer_boundary_mode": "local",
                "source_access_class": "public_unauthenticated",
            }
        )
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_automation_orders": True,
            "automation_orders": {"jobs": [job]},
        }

        errors = project_bootstrap.validate_answers(
            answers,
            automation_project_root=REPO_ROOT,
            automation_manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
            require_existing_automation_project_root=False,
        )
        manifest = json.loads(
            project_bootstrap.render_output_files(
                answers,
                "generic",
                "$FRAMEWORK",
            )["AUTOMATION_ORDERS.json"]
        )

        self.assertEqual([], errors)
        self.assertEqual(7, automation_orders_lint.SCHEMA_VERSION)
        self.assertEqual(7, manifest["schema_version"])
        self.assertEqual("deterministic_tool", manifest["jobs"][0]["reviewer_runtime_class"])
        self.assertEqual("local", manifest["jobs"][0]["reviewer_boundary_mode"])
        self.assertEqual("public_unauthenticated", manifest["jobs"][0]["source_access_class"])

    def test_project_bootstrap_propagates_schema_v7_typed_boundaries(self) -> None:
        cases = (
            (
                {"reviewer_runtime_class": "model"},
                "reviewer jobs must define reviewer_runtime_class and reviewer_boundary_mode together",
            ),
            (
                {
                    "reviewer_runtime_class": "model",
                    "reviewer_boundary_mode": "external",
                },
                "external reviewer jobs must define external_review",
            ),
            (
                {"source_access_class": "authenticated"},
                "non-public source access must define source_policy",
            ),
            (
                {"source_policy": {}},
                "source_policy requires source_access_class",
            ),
            (
                {
                    "reviewer_runtime_class": "browser-backed model",
                    "reviewer_boundary_mode": "local",
                },
                "reviewer_runtime_class must be one of",
            ),
        )
        for additions, expected in cases:
            with self.subTest(additions=additions):
                job = valid_automation_job()
                job.update(additions)
                errors = project_bootstrap.validate_answers(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "include_automation_orders": True,
                        "automation_orders": {"jobs": [job]},
                    },
                    automation_project_root=REPO_ROOT,
                    automation_manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
                    require_existing_automation_project_root=False,
                )

                self.assertTrue(any(expected in error for error in errors), errors)

    def test_project_bootstrap_rejects_a_missing_governed_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            project_root = root / "missing-project"

            with mock.patch(
                "sys.argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-revision-policy",
                    "pinned",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()

        self.assertEqual(1, result)
        self.assertIn("lifecycle transactions do not create it", stdout.getvalue())

    def test_project_bootstrap_reports_unresolvable_user_path_without_traceback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            missing_user_root = "~mpa_framework_user_that_must_not_exist/project"

            with mock.patch(
                "sys.argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    missing_user_root,
                    "--runtime",
                    "generic",
                    "--framework-ref",
                    str(REPO_ROOT),
                    "--framework-revision-policy",
                    "live",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()

        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("recovery-required", payload["status"])
        self.assertEqual("invalid", payload["transaction_state"])
        self.assertTrue(
            any(
                "target project root could not be resolved" in error
                for error in payload["errors"]
            ),
            payload,
        )

    def test_project_bootstrap_rejects_symlink_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps({"bootstrap_mode": "minimal", "agent": "Agent", "project_name": "Demo"}),
                encoding="utf-8",
            )
            real_project = root / "real-project"
            link_project = root / "linked-project"
            real_project.mkdir()
            link_project.symlink_to(real_project, target_is_directory=True)

            with mock.patch(
                "sys.argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    str(link_project),
                    "--runtime",
                    "generic",
                    "--framework-revision-policy",
                    "pinned",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()

        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("recovery-required", payload["status"])
        self.assertEqual("invalid", payload["transaction_state"])
        self.assertTrue(
            any("must not be a symbolic link" in error for error in payload["errors"]),
            payload,
        )

    def test_project_bootstrap_rejects_regular_file_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps({"bootstrap_mode": "minimal", "agent": "Agent", "project_name": "Demo"}),
                encoding="utf-8",
            )
            project_root = root / "not-a-directory"
            project_root.write_text("occupied\n", encoding="utf-8")

            with mock.patch(
                "sys.argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-revision-policy",
                    "pinned",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()

        self.assertEqual(1, result)
        payload = json.loads(stdout.getvalue())
        self.assertIn(
            f"target project root must be a directory: {project_root.resolve()}",
            payload["errors"],
        )

    def test_project_bootstrap_applies_cron_target_validation_for_preferred_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            contract_root = project / "contracts" / "project"
            (project / "task_orders").mkdir(parents=True)
            contract_root.mkdir(parents=True)
            (project / "task_orders" / "automation.md").write_text(
                "# Automation\n",
                encoding="utf-8",
            )
            job = valid_automation_job()
            job["failure_policy"] = "log-and-notify"

            errors = project_bootstrap.validate_answers(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "include_automation_orders": True,
                    "automation_orders": {"preferred_backend": "cron", "jobs": [job]},
                },
                automation_project_root=project,
                automation_manifest_path=contract_root / "AUTOMATION_ORDERS.json",
                require_existing_automation_project_root=False,
            )

        self.assertIn(
            "automation_orders.jobs: job weekly_report: target cron supports failure_policy ['log']",
            errors,
        )

    def test_project_bootstrap_binds_cron_cwd_to_selected_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            contract_root = project / "contracts" / "project"
            (project / "task_orders").mkdir(parents=True)
            contract_root.mkdir(parents=True)
            (project / "work").mkdir()
            (project / "task_orders" / "automation.md").write_text(
                "# Automation\n",
                encoding="utf-8",
            )
            job = valid_automation_job()
            job["cwd"] = "work"
            answers = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                "include_automation_orders": True,
                "automation_orders": {
                    "preferred_backend": "cron",
                    "jobs": [job],
                },
            }

            accepted = project_bootstrap.validate_answers(
                answers,
                automation_project_root=project,
                automation_manifest_path=contract_root / "AUTOMATION_ORDERS.json",
                require_existing_automation_project_root=False,
            )
            job["cwd"] = "../sibling"
            rejected = project_bootstrap.validate_answers(
                answers,
                automation_project_root=project,
                automation_manifest_path=contract_root / "AUTOMATION_ORDERS.json",
                require_existing_automation_project_root=False,
            )

        self.assertEqual([], accepted)
        self.assertTrue(
            any("cwd must be a safe repo-relative path" in error for error in rejected),
            rejected,
        )

    def test_project_bootstrap_rejects_invalid_project_date(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "date": "2026-99-99",
            }
        )

        self.assertIn("bootstrap answer key 'date' must be a valid ISO date: '2026-99-99'", errors)

    def test_project_bootstrap_uses_source_date_epoch_in_utc(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
        }

        with mock.patch.dict(project_bootstrap.os.environ, {"SOURCE_DATE_EPOCH": "86399"}, clear=False):
            outputs = project_bootstrap.render_output_files(
                answers,
                "generic",
                "$FRAMEWORK",
            )

        self.assertIn("Date: 1970-01-01", outputs["STATEMENT_OF_WORK.md"])
        self.assertIn("Date: 1970-01-01", outputs["AGENT_PROJECT.md"])

    def test_project_bootstrap_effective_date_reaches_write_plan_outputs_and_manifest(
        self,
    ) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            contract_root = project_root / "contracts" / "project"
            contract_root.mkdir(parents=True)
            answers_path = contract_root / "answers.json"
            answers_path.write_text(json.dumps(answers), encoding="utf-8")
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root="contracts/project",
                    setup_profile=None,
                    runtime="generic",
                    framework_ref="$FRAMEWORK",
                    dry_run=False,
                    create_contract_root=True,
                    framework_revision_policy="pinned",
                )
            )
            self.assertEqual([], inputs.input_errors)
            self.assertEqual([], inputs.contract_root_errors)
            self.assertIsInstance(inputs.effective_answers, dict)
            effective_answers = cast(dict[str, object], inputs.effective_answers)
            self.assertIsNotNone(inputs.answers_bytes)
            answers_bytes = cast(bytes, inputs.answers_bytes)

            effective_files = {"runtime/operative_charter.md": "0" * 64}
            fixed_identity = project_bootstrap.FrameworkIdentity(
                content_sha256=project_bootstrap.canonical_json_digest(
                    effective_files
                ),
                effective_file_digests=tuple(effective_files.items()),
                distribution_sha256="1" * 64,
            )
            with (
                mock.patch.object(
                    project_bootstrap,
                    "render_date",
                    side_effect=("2026-07-13", "2026-07-14"),
                ) as clock,
                mock.patch.object(
                    project_bootstrap,
                    "capture_framework_identity",
                    return_value=fixed_identity,
                ),
            ):
                plan = project_bootstrap.build_bootstrap_write_plan(
                    inputs,
                    effective_answers,
                )
                outputs = project_bootstrap.render_bootstrap_write_outputs(
                    inputs,
                    effective_answers,
                    answers_bytes,
                    plan.effective_date,
                    framework_identity=plan.framework_identity,
                )

        clock.assert_called_once_with(effective_answers)
        self.assertEqual([], plan.errors)
        sow_name = project_bootstrap.project_relative_output(
            inputs.contract_root_ref,
            "STATEMENT_OF_WORK.md",
        )
        contract_name = project_bootstrap.project_relative_output(
            inputs.contract_root_ref,
            "AGENT_PROJECT.md",
        )
        manifest_name = project_bootstrap.INSTANCE_MANIFEST
        manifest = json.loads(outputs[manifest_name])

        self.assertEqual("2026-07-13", plan.effective_date)
        self.assertEqual("2026-07-13", plan.summary["contract_effective_date"])
        self.assertIn("Date: 2026-07-13", outputs[sow_name])
        self.assertIn("Date: 2026-07-13", outputs[contract_name])
        self.assertEqual("2026-07-13", manifest["contract_effective_date"])
        self.assertEqual(
            project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION,
            manifest["schema_version"],
        )
        self.assertEqual(6, manifest["schema_version"])
        self.assertEqual([], manifest["authority_module_digests"])
        self.assertNotIn(
            project_bootstrap.project_relative_output(
                inputs.contract_root_ref,
                project_bootstrap.INSTANCE_MANIFEST,
            ),
            outputs,
        )
        self.assertEqual(
            project_bootstrap.canonical_json_digest(effective_files),
            manifest["framework_content_sha256"],
        )
        self.assertEqual(
            effective_files,
            manifest["framework_effective_file_digests"],
        )
        self.assertEqual("1" * 64, manifest["framework_distribution_sha256"])
        self.assertNotIn("2026-07-14", "\n".join(outputs.values()))

    def test_project_bootstrap_cli_bounds_invalid_source_date_epoch_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                        "project_name": "Demo",
                    }
                ),
                encoding="utf-8",
            )
            arguments = [
                sys.executable,
                "-E",
                "-S",
                "-B",
                str(SCRIPTS_DIR / "project_bootstrap.py"),
                "--answers",
                str(answers_path),
                "--project-root",
                str(project_root),
                "--runtime",
                "generic",
                "--framework-ref",
                "$FRAMEWORK",
                "--framework-revision-policy",
                "pinned",
                "--dry-run",
            ]
            for epoch in ("not-an-integer", "9" * 200):
                with self.subTest(epoch=epoch[:16]):
                    result = run_bounded(
                        ["/usr/bin/env", f"SOURCE_DATE_EPOCH={epoch}", *arguments],
                        cwd=REPO_ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(
                        "SOURCE_DATE_EPOCH must be a supported integer Unix timestamp",
                        result.stderr,
                    )
                    self.assertNotIn("Traceback", result.stderr)

    def test_project_bootstrap_rejects_removed_top_level_command_aliases(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "test_command": "uv run pytest",
            "lint_command": "uv run ruff check .",
            "type_check_command": "uv run basedpyright",
        }

        errors = project_bootstrap.validate_answers(answers)

        self.assertIn("unknown bootstrap answer key: test_command", errors)
        self.assertIn("unknown bootstrap answer key: lint_command", errors)
        self.assertIn("unknown bootstrap answer key: type_check_command", errors)

    def test_project_bootstrap_does_not_parse_removed_command_aliases(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "test_command": "uv run pytest 'unterminated",
            }
        )

        self.assertIn("unknown bootstrap answer key: test_command", errors)
        self.assertFalse(any(error.startswith("test_command is not shell-parseable") for error in errors))

    def test_project_bootstrap_uses_only_canonical_commands_object(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "commands": {"test": "uv run pytest", "lint": "uv run ruff check ."},
        }

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        sow = project_bootstrap.render_sow(answers)
        contract = project_bootstrap.render_project_contract(answers, "$FRAMEWORK")

        self.assertIn(
            "Test Command: see Build and Development Commands",
            sow,
        )
        self.assertIn(
            "Lint Command: see Build and Development Commands",
            sow,
        )
        self.assertIn("uv run pytest — Test", sow)
        self.assertIn("- Test: uv run pytest", contract)
        self.assertIn("- Lint: uv run ruff check .", contract)

    def test_project_bootstrap_warns_for_embedded_absolute_paths_in_commands(self) -> None:
        warnings = project_bootstrap.absolute_path_warnings(
            {
                "commands": {
                    "test": "PYTHONPATH=src:/" + "usr/bin uv run pytest",
                    "lint": "ruff --config=/" + "Users/alice/project/ruff.toml check .",
                    "deploy": "cp artifact C:" + "/" + "t" + "mp" + "/" + "site",
                },
            }
        )

        self.assertTrue(any("host-specific absolute path in Test Command" in warning for warning in warnings))
        self.assertTrue(any("host-specific absolute path in Lint Command" in warning for warning in warnings))
        self.assertTrue(any("host-specific absolute path in Deploy" in warning for warning in warnings))

    def test_project_contract_sync_warns_for_windows_absolute_paths_in_commands(self) -> None:
        warnings = project_contract_sync.command_warnings(
            "Common Commands Test",
            "node C:" + "/" + "Users" + "/" + "alice" + "/" + "project" + "/" + "test.mjs",
        )

        self.assertTrue(any("host-specific absolute path in Common Commands Test" in warning for warning in warnings))

    def test_project_bootstrap_rejects_alias_even_when_canonical_command_exists(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "commands": {"test": "uv run pytest"},
                "test_command": "pytest",
            }
        )

        self.assertIn("unknown bootstrap answer key: test_command", errors)

    def test_project_bootstrap_rejects_unsafe_framework_reference(self) -> None:
        self.assertIn(
            "framework reference must not contain shell or Markdown metacharacters",
            safe_paths.framework_reference_errors("`pwd`/framework"),
        )
        self.assertIn(
            "framework reference must not contain shell or Markdown metacharacters",
            safe_paths.framework_reference_errors("</system>"),
        )
        self.assertIn(
            "framework reference must not contain shell or Markdown metacharacters",
            safe_paths.framework_reference_errors("framework; touch output"),
        )
        self.assertIn(
            "framework reference must not contain whitespace",
            safe_paths.framework_reference_errors("framework root"),
        )
        self.assertIn(
            "framework reference must be a filesystem reference, not a URI",
            safe_paths.framework_reference_errors("https://example.com/framework"),
        )
        self.assertIn(
            "framework reference may use only simple $NAME or ${NAME} environment-variable references",
            safe_paths.framework_reference_errors("framework/{one,two}"),
        )
        self.assertIn(
            "framework reference must not contain shell or Markdown metacharacters",
            safe_paths.framework_reference_errors(r"framework\escaped"),
        )
        self.assertIn(
            "framework reference may use only simple $NAME or ${NAME} environment-variable references",
            safe_paths.framework_reference_errors("${FRAMEWORK_ROOT:-fallback}"),
        )
        self.assertIn(
            "framework reference may use home expansion only as '~' or a leading '~/'",
            safe_paths.framework_reference_errors("framework/~archive"),
        )
        self.assertEqual([], safe_paths.framework_reference_errors("${FRAMEWORK_ROOT}/mpa"))
        self.assertEqual([], safe_paths.framework_reference_errors("~/framework"))

    def test_framework_reference_validation_has_one_owner_and_consumers_delegate(self) -> None:
        owner_functions = {
            "canonical_framework_reference",
            "extract_framework_references",
            "framework_reference_errors",
            "resolve_framework_reference",
        }
        definitions = {
            (path.name, node.name)
            for path in SCRIPTS_DIR.glob("*.py")
            for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in owner_functions
        }
        self.assertEqual(
            {
                ("safe_paths.py", "canonical_framework_reference"),
                ("safe_paths.py", "extract_framework_references"),
                ("safe_paths.py", "framework_reference_errors"),
                ("safe_paths.py", "resolve_framework_reference"),
            },
            definitions,
        )

        canonicalize = safe_paths.canonical_framework_reference
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            project_root = root / "project"
            project_root.mkdir()
            with mock.patch.object(
                safe_paths,
                "canonical_framework_reference",
                wraps=canonicalize,
            ) as bootstrap_delegate:
                inputs = project_bootstrap.load_bootstrap_inputs(
                    project_bootstrap.BootstrapOptions(
                        answers=str(answers_path),
                        project_root=str(project_root),
                        project_kind="downstream",
                        contract_root=None,
                        setup_profile=None,
                        runtime="generic",
                        framework_ref="$FRAMEWORK/",
                        dry_run=True,
                        create_contract_root=False,
                        framework_revision_policy="pinned",
                    )
                )
            self.assertEqual("$FRAMEWORK", inputs.framework_ref)
            bootstrap_delegate.assert_called_once_with("$FRAMEWORK/")

            output_root = root / "rendered"
            with (
                mock.patch.object(
                    safe_paths,
                    "canonical_framework_reference",
                    wraps=canonicalize,
                ) as integration_delegate,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "render_integrations.py",
                        "--integration",
                        "generic",
                        "--output-dir",
                        str(output_root),
                        "--framework-ref",
                        "$FRAMEWORK/",
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                result = render_integrations.main()

        self.assertEqual(0, result)
        integration_delegate.assert_any_call("$FRAMEWORK/")

    def test_project_bootstrap_warns_for_file_uri_host_framework_reference(self) -> None:
        self.assertTrue(project_bootstrap.framework_reference_warnings("file:///" + "Users" + "/alice/framework"))

    def test_framework_reference_canonicalization_handles_trailing_and_root_forms(self) -> None:
        self.assertEqual("$FRAMEWORK", safe_paths.canonical_framework_reference("$FRAMEWORK/"))
        self.assertEqual("/", safe_paths.canonical_framework_reference("/"))
        rendered = safe_paths.render_framework_reference_tokens(
            "Read {{FRAMEWORK_ROOT}}/runtime/operative_charter.md",
            "/",
        )
        self.assertEqual("Read /runtime/operative_charter.md", rendered)
        command_lines = project_contract_model.framework_verification_command_lines(
            "/",
            runner="python3 -E -S -B",
        )
        self.assertTrue(any(" /scripts/conformance_check.py " in line for line in command_lines))
        self.assertFalse(any("//scripts/" in line for line in command_lines))

    def test_contract_root_rejects_rendered_token_metacharacters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            cases = (
                "contract root",
                "-contracts",
                "contracts;touch",
                "contracts$HOME",
                "contracts\\nested",
                "contracts\x00nested",
            )
            for value in cases:
                with self.subTest(value=repr(value)):
                    _root, _reference, errors = project_bootstrap.resolve_contract_root(
                        project_root,
                        value,
                    )
                    self.assertTrue(errors, value)

    def test_project_entrypoint_substitution_is_single_pass_when_root_contains_filename(self) -> None:
        contract_root = "contracts/AGENT_PROJECT.md-bundle"
        _name, entrypoint = project_bootstrap.render_entrypoint(
            "generic",
            "$FRAMEWORK/",
            contract_root_ref=contract_root,
        )

        self.assertIn(
            f"Read `{contract_root}/AGENT_PROJECT.md` before acting",
            entrypoint,
        )
        self.assertNotIn(f"{contract_root}/contracts/", entrypoint)

    def test_project_bootstrap_setup_profile_fills_only_absent_whole_fields(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "auxiliary_tools": [
                {"name": "answer tool", "purpose": "answer-owned", "source": "answer source"}
            ],
        }
        profile = {
            "schema_version": 1,
            "defaults": {
                "execution_posture": "advise",
                "auxiliary_tools": [
                    {
                        "name": "profile tool",
                        "purpose": "profile-owned",
                        "source": "profile source",
                        "owner": "profile owner",
                        "transport": "local CLI",
                        "capability_surface": "declared commands",
                        "permissions": "none",
                        "data_boundary": "none",
                        "trust": "approved profile tool",
                        "credential_source": "none",
                        "approval": "none",
                        "effect_boundary": "no external effects",
                        "persistence": "none",
                        "control_role": "none",
                    }
                ],
            },
        }

        effective, applied, overridden = project_bootstrap.apply_setup_profile(answers, profile)

        self.assertEqual([], project_bootstrap.validate_setup_profile(profile))
        self.assertEqual(["execution_posture"], applied)
        self.assertEqual(["auxiliary_tools"], overridden)
        self.assertEqual("advise", cast(dict[str, object], effective)["execution_posture"])
        self.assertEqual(answers["auxiliary_tools"], cast(dict[str, object], effective)["auxiliary_tools"])

    def test_project_bootstrap_setup_profile_rejects_project_facts_and_unknown_keys(self) -> None:
        errors = project_bootstrap.validate_setup_profile(
            {
                "schema_version": 1,
                "defaults": {
                    "project_name": "Leaked project identity",
                    "user": "Leaked user identity",
                    "commands": {"test": "run hidden preference"},
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "invented": True,
                },
            }
        )

        self.assertIn("setup profile must not provide project-fact key: project_name", errors)
        self.assertIn("setup profile must not provide project-fact key: user", errors)
        self.assertIn("setup profile must not provide project-fact key: commands", errors)
        self.assertIn(
            "setup profile must not provide project-fact key: framework_verification_runner",
            errors,
        )
        self.assertIn("unknown setup profile default key: invented", errors)

        semantic_errors = project_bootstrap.validate_setup_profile(
            {
                "schema_version": 1,
                "defaults": {"execution_posture": "unbounded"},
            }
        )
        self.assertIn(
            "setup profile defaults: execution_posture must be one of: act, advise, ask-when-ambiguous",
            semantic_errors,
        )

    def test_project_bootstrap_public_profile_example_is_valid_and_project_neutral(self) -> None:
        profile = json.loads(
            (REPO_ROOT / "examples" / "project_bootstrap_profile.example.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual([], project_bootstrap.validate_setup_profile(profile))
        self.assertFalse(
            set(cast(dict[str, object], profile["defaults"]))
            & project_bootstrap.SETUP_PROFILE_FORBIDDEN_KEYS
        )
        self.assertNotIn("bootstrap_mode", cast(dict[str, object], profile["defaults"]))
        self.assertNotIn(
            "framework_verification_runner",
            cast(dict[str, object], profile["defaults"]),
        )
        self.assertEqual(
            project_contract_model.DEFAULT_SOURCE_FRESHNESS_POLICY,
            cast(dict[str, object], profile["defaults"])["source_freshness_policy"],
        )
        answers_example = json.loads(
            (REPO_ROOT / "examples" / "project_bootstrap_answers.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            "framework_verification_runner must be a concrete executable command prefix",
            project_bootstrap.validate_answers(answers_example),
        )

    def test_project_bootstrap_json_input_failures_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            good_answers = root / "good-answers.json"
            good_answers.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            malformed = root / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff")
            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"bootstrap_mode":"minimal","agent":"Agent","project_name":"Reviewed",'
                '"project_name":"Override","framework_verification_runner":"uv run python -E -S -B"}',
                encoding="utf-8",
            )
            oversized = root / "oversized.json"
            oversized.write_bytes(b" " * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1))
            symlinked = root / "symlinked.json"
            symlinked.symlink_to(good_answers)
            cases = (
                ("answers missing", root / "missing.json", None, "bootstrap answers file is missing"),
                ("answers malformed", malformed, None, "bootstrap answers file is invalid JSON"),
                ("answers invalid UTF-8", invalid_utf8, None, "bootstrap answers file must be valid UTF-8"),
                ("answers duplicate key", duplicate, None, "duplicate JSON key: project_name"),
                ("answers oversized", oversized, None, "exceeds the"),
                ("answers symlinked", symlinked, None, "bootstrap answers file must not use symlink path components"),
                ("profile missing", good_answers, root / "missing-profile.json", "setup profile file is missing"),
                ("profile malformed", good_answers, malformed, "setup profile file is invalid JSON"),
                ("profile invalid UTF-8", good_answers, invalid_utf8, "setup profile file must be valid UTF-8"),
                ("profile symlinked", good_answers, symlinked, "setup profile file must not use symlink path components"),
            )
            for label, answers_path, profile_path, expected in cases:
                argv = [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-ref",
                    "$FRAMEWORK",
                    "--framework-revision-policy",
                    "pinned",
                    "--dry-run",
                ]
                if profile_path is not None:
                    argv.extend(["--setup-profile", str(profile_path)])
                with self.subTest(label=label), mock.patch.object(sys, "argv", argv):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        result = project_bootstrap.main()
                    report = json.loads(stdout.getvalue())
                    self.assertEqual(1, result)
                    self.assertTrue(any(expected in error for error in report["errors"]), report)

            missing_runner_answers = root / "missing-runner.json"
            missing_runner_answers.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                sys,
                "argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(missing_runner_answers),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-ref",
                    "$FRAMEWORK",
                    "--framework-revision-policy",
                    "pinned",
                    "--dry-run",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()
            report = json.loads(stdout.getvalue())
            self.assertEqual(1, result)
            self.assertTrue(
                any("missing required bootstrap answer key: framework_verification_runner" in error for error in report["errors"]),
                report,
            )

    def test_framework_source_reader_rejects_missing_invalid_symlinked_and_replaced_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "valid.md"
            valid.write_text("valid source\n", encoding="utf-8")
            invalid_utf8 = root / "invalid.md"
            invalid_utf8.write_bytes(b"\xff")
            symlinked = root / "symlinked.md"
            symlinked.symlink_to(valid)

            cases = (
                ("missing.md", "is missing"),
                ("invalid.md", "must be valid UTF-8"),
                ("symlinked.md", "symlink"),
            )
            with mock.patch.object(project_bootstrap, "REPO_ROOT", root):
                self.assertEqual(
                    "valid source\n",
                    project_bootstrap.read_framework_source_text(
                        "valid.md",
                        description="framework test source",
                    ),
                )
                for relative_path, expected in cases:
                    with self.subTest(relative_path=relative_path):
                        with self.assertRaisesRegex(ValueError, expected):
                            project_bootstrap.read_framework_source_text(
                                relative_path,
                                description="framework test source",
                            )

                with mock.patch.object(
                    safe_paths,
                    "read_regular_file_bytes",
                    side_effect=ValueError(
                        "framework test source changed while it was being read"
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "changed while"):
                        project_bootstrap.read_framework_source_text(
                            "valid.md",
                            description="framework test source",
                        )

    def test_msa_reference_requires_one_well_formed_anchored_version_row(self) -> None:
        malformed_sources = (
            "Master Service Agreement\n",
            "Master Service Agreement\nVersion: unknown\n",
            "Master Service Agreement\nText Version: 1.2.3\n",
            "Master Service Agreement\nVersion: 1.2.3.\n",
            "Version: 1.2.3\nVersion: 2.0.0\n",
        )
        for source in malformed_sources:
            with self.subTest(source=source):
                with mock.patch.object(
                    project_bootstrap,
                    "read_framework_source_text",
                    return_value=source,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "anchored Version row",
                    ):
                        project_bootstrap.msa_reference()

        with mock.patch.object(
            project_bootstrap,
            "read_framework_source_text",
            return_value=(
                "Master Service Agreement\n\n"
                "Version: 1.2.3  Effective Date: 2026-07-14\n"
            ),
        ):
            self.assertEqual(
                "master_service_agreement.md v1.2.3",
                project_bootstrap.msa_reference(),
            )

    def test_project_bootstrap_reports_source_planning_and_render_failures_without_writes(self) -> None:
        cases = (
            (
                "planning",
                mock.patch.object(
                    project_bootstrap,
                    "read_framework_source_text",
                    return_value="Version: invalid\n",
                ),
            ),
            (
                "rendering",
                mock.patch.object(
                    project_bootstrap,
                    "render_bootstrap_write_outputs",
                    side_effect=ValueError(
                        "framework source changed while it was being read"
                    ),
                ),
            ),
        )
        for stage, failure_patch in cases:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                answers_path = root / "answers.json"
                answers_path.write_text(
                    json.dumps(
                        {
                            "bootstrap_mode": "minimal",
                            "agent": "Agent",
                            "project_name": "Demo",
                            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                        }
                    ),
                    encoding="utf-8",
                )
                with failure_patch, mock.patch.object(
                    sys,
                    "argv",
                    [
                        "project_bootstrap.py",
                        "--answers",
                        str(answers_path),
                        "--project-root",
                        str(project_root),
                        "--runtime",
                        "generic",
                        "--framework-ref",
                        "$FRAMEWORK",
                        "--framework-revision-policy",
                        "pinned",
                        "--dry-run",
                    ],
                ):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        result = project_bootstrap.main()
                report = json.loads(stdout.getvalue())
                self.assertEqual(1, result)
                self.assertTrue(
                    any(
                        f"bootstrap {stage} failed" in error
                        for error in report["errors"]
                    ),
                    report,
                )
                self.assertEqual([], list(project_root.iterdir()))

    def test_project_bootstrap_dry_run_reports_profile_application_and_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            profile_path = root / "profile.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "execution_posture": "act",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "defaults": {
                            "execution_posture": "advise",
                            "dependency_posture": "no-external-dependencies",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                sys,
                "argv",
                [
                    "project_bootstrap.py",
                    "--answers",
                    str(answers_path),
                    "--setup-profile",
                    str(profile_path),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-ref",
                    "$FRAMEWORK",
                    "--framework-revision-policy",
                    "pinned",
                    "--dry-run",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_bootstrap.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(0, result)
        self.assertEqual(["dependency_posture"], report["setup_profile"]["applied_fields"])
        self.assertEqual(["execution_posture"], report["setup_profile"]["overridden_fields"])
        self.assertRegex(report["setup_profile"]["sha256"], r"^[0-9a-f]{64}$")
        profile_digest = report["setup_profile"]["sha256"]
        self.assertEqual(
            [
                {
                    "field": "dependency_posture",
                    "value": "no-external-dependencies",
                    "provenance": {
                        "kind": "setup-profile-default",
                        "source_path": str(profile_path),
                        "source_sha256": profile_digest,
                        "source_field": "defaults.dependency_posture",
                    },
                }
            ],
            report["setup_profile"]["applied_values"],
        )
        self.assertEqual(
            [
                {
                    "field": "execution_posture",
                    "profile_value": "advise",
                    "effective_value": "act",
                    "provenance": {
                        "profile": "setup-profile-default",
                        "effective": "bootstrap-answers",
                        "source_path": str(profile_path),
                        "source_sha256": profile_digest,
                        "source_field": "defaults.execution_posture",
                    },
                }
            ],
            report["setup_profile"]["overridden_values"],
        )
        previews = cast(list[dict[str, str]], report["rendered_outputs"])
        self.assertEqual(report["planned_outputs"], [item["path"] for item in previews])
        self.assertTrue(previews)
        for preview in previews:
            self.assertEqual({"path", "text", "sha256"}, set(preview))
            self.assertEqual(
                project_bootstrap.sha256_bytes(preview["text"].encode("utf-8")),
                preview["sha256"],
            )
        self.assertEqual(
            project_bootstrap.canonical_json_digest(previews),
            report["rendered_outputs_sha256"],
        )
        target_binding = cast(dict[str, object], report["write_target_binding"])
        self.assertEqual(str(project_root), target_binding["project_root"])
        self.assertEqual(str(project_root), target_binding["contract_root"])
        self.assertEqual(".", target_binding["contract_root_ref"])
        self.assertEqual(
            target_binding["project_root_identity"],
            target_binding["contract_root_identity"],
        )
        self.assertEqual(
            {".": target_binding["project_root_identity"]},
            target_binding["directory_identities"],
        )

    def test_bootstrap_write_plan_digest_binds_exact_preview_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Preview Binding",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref="$FRAMEWORK",
                    dry_run=True,
                    create_contract_root=False,
                    framework_revision_policy="pinned",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                cast(bytes, inputs.answers_bytes),
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            payload = project_bootstrap._bootstrap_write_plan_approval_payload(
                inputs,
                outputs,
                plan.framework_identity,
                plan.summary["warnings"],
                effective_date=plan.effective_date,
            )
            original_digest = project_bootstrap.canonical_json_digest(payload)
            mutated = json.loads(json.dumps(payload))
            mutated["outputs"][0]["text"] += "reviewed-byte-change"

        self.assertNotEqual(
            original_digest,
            project_bootstrap.canonical_json_digest(mutated),
        )
        self.assertNotEqual(
            mutated["outputs"][0]["sha256"],
            project_bootstrap.sha256_bytes(
                mutated["outputs"][0]["text"].encode("utf-8")
            ),
        )

    def test_project_bootstrap_dry_run_is_identical_under_optimized_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "project_name": "Demo",
                        "date": "2026-07-12",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            arguments = [
                str(SCRIPTS_DIR / "project_bootstrap.py"),
                "--answers",
                str(answers_path),
                "--project-root",
                str(project_root),
                "--runtime",
                "generic",
                "--framework-ref",
                "$FRAMEWORK",
                "--framework-revision-policy",
                "pinned",
                "--dry-run",
            ]
            standard = run_bounded(
                [sys.executable, "-E", "-S", "-B", *arguments],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            optimized = run_bounded(
                [sys.executable, "-E", "-S", "-B", "-O", *arguments],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, standard.returncode, standard.stdout + standard.stderr)
        self.assertEqual(standard.returncode, optimized.returncode)
        self.assertEqual(standard.stdout, optimized.stdout)
        self.assertEqual(standard.stderr, optimized.stderr)

    def test_project_bootstrap_removed_framework_revision_escape_hatch(self) -> None:
        help_result = run_bounded(
            [
                sys.executable,
                "-E",
                "-S",
                "-B",
                str(SCRIPTS_DIR / "project_bootstrap.py"),
                "--help",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertNotIn("--allow-framework-revision", help_result.stdout)
        self.assertIn("--project-kind", help_result.stdout)
        self.assertIn("--contract-root", help_result.stdout)

    def test_project_bootstrap_ignores_cache_and_rejects_package_shadows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                SCRIPTS_DIR,
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            shutil.copytree(REPO_ROOT / "integrations", root / "integrations")
            dependency = scripts_root / "bootstrap_transaction.py"
            reviewed_source = dependency.read_bytes()
            cache_marker = root / "cache-ran"
            dependency.write_text(
                "from pathlib import Path\n"
                f"Path({str(cache_marker)!r}).write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )
            compile_adjacent_bytecode(dependency, unchecked_hash=True)
            dependency.write_bytes(reviewed_source)

            cache_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(scripts_root / "project_bootstrap.py"),
                    "--help",
                ],
                cwd=root,
                check=False,
            )
            self.assertEqual(
                0,
                cache_result.returncode,
                cache_result.stdout + cache_result.stderr,
            )
            self.assertFalse(cache_marker.exists())

            package_marker = root / "package-ran"
            package = scripts_root / "bootstrap_transaction"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(package_marker)!r}).write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )
            shadow_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(scripts_root / "project_bootstrap.py"),
                    "--help",
                ],
                cwd=root,
                check=False,
            )
            self.assertFalse(package_marker.exists())

        self.assertNotEqual(0, shadow_result.returncode)
        self.assertIn(
            "project bootstrap rejected local import shadow: bootstrap_transaction",
            shadow_result.stderr,
        )

    def test_import_boundary_rejects_nonregular_adjacent_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                SCRIPTS_DIR,
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            shutil.copytree(REPO_ROOT / "integrations", root / "integrations")
            os.mkfifo(scripts_root / "untrusted-import-artifact")

            result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(scripts_root / "project_bootstrap.py"),
                    "--help",
                ],
                cwd=root,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "project bootstrap rejected non-regular import-adjacent entry: "
            "untrusted-import-artifact",
            result.stderr,
        )

    def test_exact_source_trampoline_requires_no_follow_open(self) -> None:
        with mock.patch.object(os, "O_NOFOLLOW", 0):
            with self.assertRaisesRegex(
                RuntimeError,
                "requires O_CLOEXEC and O_NOFOLLOW",
            ):
                project_bootstrap._load_trusted_import_boundary(
                    str(SCRIPTS_DIR / "project_bootstrap.py")
                )

    def test_project_bootstrap_nested_downstream_entrypoint_resolves_selected_contract(self) -> None:
        _name, entrypoint = project_bootstrap.render_entrypoint(
            "generic",
            "$FRAMEWORK",
            contract_root_ref=".mpa/contracts",
        )

        self.assertIn("Read `.mpa/contracts/AGENT_PROJECT.md` before acting", entrypoint)
        self.assertIn("`.mpa/contracts/STATEMENT_OF_WORK.md`", entrypoint)
        self.assertIn("Apply Article 5", entrypoint)
        self.assertIn(
            "directory containing the rendered `.mpa/contracts/AGENT_PROJECT.md`",
            entrypoint,
        )
        self.assertNotIn("active_count: 0", entrypoint)

    def test_planned_output_graph_rejects_entrypoint_ancestor_collision(self) -> None:
        errors = project_bootstrap.planned_output_graph_errors(
            project_bootstrap.planned_output_names(
                {"bootstrap_mode": "minimal"},
                "generic",
                contract_root_ref="AGENTS.md",
            )
        )

        self.assertTrue(
            any("both a file and an ancestor directory" in error for error in errors),
            errors,
        )

    def test_project_bootstrap_has_one_template_source_root(self) -> None:
        help_result = run_bounded(
            [
                sys.executable,
                "-E",
                "-S",
                "-B",
                str(SCRIPTS_DIR / "project_bootstrap.py"),
                "--help",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertNotIn("--framework-root", help_result.stdout)
        self.assertIn(
            "Defaults to the executing framework checkout",
            " ".join(help_result.stdout.split()),
        )

        stale_reference = re.compile(
            r"project_bootstrap\.py[^\n]*--framework-root|"
            r"--framework-root[^\n]*project_bootstrap\.py"
        )
        for rel in (
            "README.md",
            "GETTING_STARTED.md",
            "docs/downstream_setup.md",
            "scripts/README.md",
            "task_orders/init.md",
        ):
            with self.subTest(rel=rel):
                self.assertIsNone(
                    stale_reference.search((REPO_ROOT / rel).read_text(encoding="utf-8")),
                    rel,
                )
