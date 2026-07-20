"""Codex automation-registry schema-v6 contract tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest

from tests.validation_test_support import REPO_ROOT, run_bounded

import codex_automation_registry_lint  # noqa: E402


def execution_environment() -> dict[str, str]:
    return {
        "boundary_mode": "local",
        "environment_ref": "fixture_agent_app",
        "runtime_class": "agent_app",
    }


def discovery_policy() -> dict[str, str]:
    return {
        "digest_validator": "scripts/source_deep_research_lint.py",
        "launch_mode": "operator_supervised",
        "primary_source_verification": "required",
        "result_authority": "candidate_only",
    }


def exposed(value: str) -> dict[str, str]:
    return {"value": value, "visibility": "exposed"}


def cron_entry(
    automation_id: str = "weekly-monitor",
    *,
    cadence_role: str = "narrow_source_chain",
    frequency: str = "WEEKLY",
    status: str = "PAUSED",
    prompt: str = "Inspect the declared instruction sources and report once.",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "autonomy_level": "observe",
        "cadence_role": cadence_role,
        "context_mode": "fresh_run",
        "cwd": "{PROJECT_ROOT}",
        "execution_environment": execution_environment(),
        "id": automation_id,
        "instruction_sources": ["AGENTS.md"],
        "kind": "cron",
        "model_route": "quality_first",
        "prompt_lines": [prompt],
        "rrule": f"FREQ={frequency};BYDAY=MO",
        "status": status,
        "timezone": "Europe/Vienna",
    }
    if cadence_role == "broad_source_discovery":
        entry["discovery_policy"] = discovery_policy()
    return entry


def thread_wakeup_entry() -> dict[str, Any]:
    return {
        "autonomy_level": "observe",
        "cadence_role": "recovery_diagnostic",
        "context_mode": "thread_continuity",
        "execution_environment": execution_environment(),
        "id": "repair-supervisor",
        "instruction_sources": ["AGENTS.md"],
        "kind": "thread_wakeup",
        "model_route": "quality_first",
        "prompt_lines": ["Inspect state and report once."],
        "status": "PAUSED",
        "target_thread": "current_thread_when_installed",
        "timezone": "Europe/Vienna",
    }


def registry_document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "automations": entries,
        "project_root_placeholder": "{PROJECT_ROOT}",
        "schema_version": codex_automation_registry_lint.SCHEMA_VERSION,
        "timezone": "Europe/Vienna",
    }


def operator_entry(stage: str) -> dict[str, Any]:
    autonomy = {
        "monitor": "observe",
        "review": "propose",
        "apply": "act",
        "assurance": "observe",
    }[stage]
    return {
        "autonomy_level": autonomy,
        "cadence_role": "narrow_source_chain",
        "chain_stage": stage,
        "context_mode": "fresh_run",
        "cwd": "{PROJECT_ROOT}",
        "execution_environment": execution_environment(),
        "id": f"framework-{stage}",
        "instruction_sources": ["AGENTS.md", "model-routing.md"],
        "kind": "operator_trigger",
        "model_route": "quality_first",
        "prompt_lines": [
            "Run {MONITOR_SCOPE} for {LOGICAL_DATE} at {RUN_SLOT} from {PROJECT_ROOT}; declared files are authoritative."
        ],
        "status": "MANUAL",
        "timezone": "Europe/Vienna",
        "trigger_note": "Operator requested this source-chain stage.",
        "trigger_policy": "explicit_user_request",
    }


def operator_contract() -> dict[str, Any]:
    return {
        "activation": "explicit_user_request",
        "default_model_route": "quality_first",
        "logical_date_placeholder": "{LOGICAL_DATE}",
        "model_routing_reference": "model-routing.md",
        "run_slot_placeholder": "{RUN_SLOT}",
        "scope_placeholder": "{MONITOR_SCOPE}",
        "source_chain_order": [
            "framework-monitor",
            "framework-review",
            "framework-apply",
            "framework-assurance",
        ],
        "stage_assignments": {
            stage: {
                "execution_mode": exposed("standard"),
                "model_label": exposed("Fixture Model"),
                "reasoning_effort": exposed("high"),
            }
            for stage in ("monitor", "review", "apply", "assurance")
        },
    }


class CodexAutomationRegistryTests(unittest.TestCase):
    def test_schema_v6_enforces_portability_typed_discovery_and_formal_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            validator = root / "scripts" / "source_deep_research_lint.py"
            validator.parent.mkdir()
            validator.write_text("# Fixture validator\n", encoding="utf-8")
            valid = root / "valid.json"
            valid.write_text(
                json.dumps(
                    registry_document(
                        [
                            cron_entry(),
                            cron_entry(
                                "monthly-broad-discovery",
                                cadence_role="broad_source_discovery",
                                frequency="MONTHLY",
                                prompt=(
                                    "Do not infer any verification, cadence, or authority from "
                                    "this deliberately negated prose."
                                ),
                            ),
                            thread_wakeup_entry(),
                        ]
                    )
                ),
                encoding="utf-8",
            )

            host_path = "/" + "Users" + "/example/project"
            invalid_entries = [
                cron_entry("bad-monitor", prompt=f"Inspect {host_path}."),
                cron_entry(
                    "bad-broad-discovery",
                    cadence_role="broad_source_discovery",
                    frequency="WEEKLY",
                ),
                thread_wakeup_entry(),
            ]
            invalid_entries[0]["cwd"] = host_path
            invalid_entries[1]["autonomy_level"] = "propose"
            invalid_entries[1].pop("discovery_policy")
            invalid_entries[2].update(
                {
                    "autonomy_level": "act",
                    "cadence_role": "narrow_source_chain",
                    "cwd": "{PROJECT_ROOT}",
                    "metadata": {"last_cwd": host_path},
                    "rrule": "FREQ=MINUTELY;INTERVAL=5",
                    "status": "ACTIVE",
                    "target_thread": "thread-local-id-123",
                    "target_thread_id": "thread-local-id",
                }
            )
            invalid = root / "invalid.json"
            invalid.write_text(
                json.dumps(registry_document(invalid_entries)),
                encoding="utf-8",
            )

            valid_errors = codex_automation_registry_lint.validate_registry(valid)
            active_errors = codex_automation_registry_lint.validate_registry(
                valid,
                require_active_source_chain=True,
            )
            invalid_errors = codex_automation_registry_lint.validate_registry(invalid)

        self.assertEqual([], valid_errors)
        self.assertIn("no ACTIVE narrow_source_chain cron automation is registered", active_errors)
        self.assertIn("bad-monitor: cron automation cwd must be {PROJECT_ROOT}", invalid_errors)
        self.assertTrue(
            any("must not contain host-specific absolute paths" in error for error in invalid_errors),
            invalid_errors,
        )
        self.assertIn(
            "bad-broad-discovery: broad_source_discovery must stay observe-only",
            invalid_errors,
        )
        self.assertIn(
            "bad-broad-discovery: discovery_policy must be an object",
            invalid_errors,
        )
        self.assertIn(
            "bad-broad-discovery: broad_source_discovery cron RRULE must be MONTHLY or YEARLY",
            invalid_errors,
        )
        self.assertTrue(
            any("automations[2] has unknown fields" in error for error in invalid_errors),
            invalid_errors,
        )
        self.assertIn(
            "repair-supervisor: target_thread must be current_thread_when_installed or thread_alias:<portable-name>",
            invalid_errors,
        )
        self.assertIn(
            "repair-supervisor: thread_wakeup automation must stay PAUSED in the portable registry",
            invalid_errors,
        )
        self.assertIn(
            "repair-supervisor: thread_wakeup automation must stay observe-only",
            invalid_errors,
        )
        self.assertIn(
            "repair-supervisor: thread_wakeup automation must use cadence_role recovery_diagnostic",
            invalid_errors,
        )

    def test_prompt_prose_cannot_classify_or_supply_discovery_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            validator = root / "scripts" / "source_deep_research_lint.py"
            validator.parent.mkdir()
            validator.write_text("# Fixture validator\n", encoding="utf-8")
            path = root / "registry.json"

            prose_only = cron_entry(
                "prose-only",
                prompt=(
                    "Run Deep Research monthly, invoke source_deep_research_lint.py, "
                    "and require primary-source verification."
                ),
            )
            path.write_text(
                json.dumps(registry_document([prose_only])),
                encoding="utf-8",
            )
            prose_only_errors = codex_automation_registry_lint.validate_registry(path)

            typed_broad = cron_entry(
                "typed-broad",
                cadence_role="broad_source_discovery",
                frequency="YEARLY",
                prompt=(
                    "Never run Deep Research, never validate its digest, and do not verify "
                    "primary sources; this prose is deliberately non-authoritative."
                ),
            )
            typed_broad["cadence_note"] = "Daily is written here but is not cadence authority."
            path.write_text(
                json.dumps(registry_document([typed_broad])),
                encoding="utf-8",
            )
            typed_broad_errors = codex_automation_registry_lint.validate_registry(path)

            typed_broad["rrule"] = "FREQ=WEEKLY;BYDAY=MO"
            typed_broad["cadence_note"] = "Monthly broad discovery."
            path.write_text(
                json.dumps(registry_document([typed_broad])),
                encoding="utf-8",
            )
            invalid_frequency_errors = codex_automation_registry_lint.validate_registry(path)

            typed_broad["rrule"] = "FREQ=YEARLY;BYDAY=MO"
            typed_broad["discovery_policy"]["digest_validator"] = "scripts/missing.py"
            path.write_text(
                json.dumps(registry_document([typed_broad])),
                encoding="utf-8",
            )
            invalid_validator_errors = codex_automation_registry_lint.validate_registry(path)

        self.assertEqual([], prose_only_errors)
        self.assertEqual([], typed_broad_errors)
        self.assertIn(
            "typed-broad: broad_source_discovery cron RRULE must be MONTHLY or YEARLY",
            invalid_frequency_errors,
        )
        self.assertIn(
            "typed-broad: discovery_policy.digest_validator must be scripts/source_deep_research_lint.py",
            invalid_validator_errors,
        )
        self.assertTrue(
            any(
                "discovery_policy.digest_validator file does not exist" in error
                for error in invalid_validator_errors
            ),
            invalid_validator_errors,
        )

    def test_operator_trigger_contract_owns_route_and_structured_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            routing_file = root / "model-routing.md"
            routing_file.write_text(
                "# Explanation only\n\nRoute ID: `different_route`\n",
                encoding="utf-8",
            )
            registry = root / "registry.json"
            document = registry_document(
                [operator_entry(stage) for stage in ("monitor", "review", "apply", "assurance")]
            )
            document["operator_trigger_contract"] = operator_contract()
            registry.write_text(json.dumps(document), encoding="utf-8")
            valid_errors = codex_automation_registry_lint.validate_registry(registry)

            explicit_not_exposed = copy.deepcopy(document)
            for field_name in ("reasoning_effort", "execution_mode"):
                explicit_not_exposed["operator_trigger_contract"]["stage_assignments"][
                    "review"
                ][field_name] = {"value": None, "visibility": "not_exposed"}
            registry.write_text(json.dumps(explicit_not_exposed), encoding="utf-8")
            not_exposed_errors = codex_automation_registry_lint.validate_registry(registry)

            reserved_exposed = copy.deepcopy(document)
            reserved_exposed["operator_trigger_contract"]["stage_assignments"][
                "review"
            ]["reasoning_effort"] = {
                "value": "not_exposed",
                "visibility": "exposed",
            }
            registry.write_text(json.dumps(reserved_exposed), encoding="utf-8")
            reserved_exposed_errors = codex_automation_registry_lint.validate_registry(
                registry
            )

            invalid = copy.deepcopy(document)
            invalid["automations"][0]["status"] = "ACTIVE"
            invalid["automations"][0]["trigger_policy"] = "calendar"
            invalid["automations"][0]["cadence_note"] = "Daily wakeup."
            invalid["automations"][0]["model_route"] = "unvalidated_route"
            invalid["automations"][0]["reasoning_effort"] = "extra_high"
            invalid["automations"][0]["autonomy_level"] = "act"
            invalid["automations"][0]["rrule"] = "FREQ=DAILY"
            invalid["automations"][0]["prompt_lines"] = [
                "Run {MONITOR_SCOPE} for {LOGICAL_DATE}."
            ]
            invalid["operator_trigger_contract"]["source_chain_order"] = [
                "framework-review",
                "framework-monitor",
                "framework-apply",
                "framework-assurance",
            ]
            invalid["operator_trigger_contract"]["model_routing_file"] = (
                invalid["operator_trigger_contract"].pop("model_routing_reference")
            )
            registry.write_text(json.dumps(invalid), encoding="utf-8")
            invalid_errors = codex_automation_registry_lint.validate_registry(registry)

            invalid_assignment = copy.deepcopy(document)
            invalid_assignment["operator_trigger_contract"]["stage_assignments"]["review"] = {
                "execution_mode": "standard",
                "model_label": {"value": " Fixture Model ", "visibility": "exposed"},
                "provider": "fixture-provider",
                "reasoning_effort": {"value": "high", "visibility": "unknown"},
            }
            registry.write_text(json.dumps(invalid_assignment), encoding="utf-8")
            assignment_errors = codex_automation_registry_lint.validate_registry(registry)

            malformed_prompt = copy.deepcopy(document)
            malformed_prompt["automations"][0]["prompt_lines"] = [
                "Run from {PROJECT_ROOT} for {LOGICAL_DATE} at {RUN_SLOT} with "
                "{{MONITOR_SCOPE}}, {UNKNOWN}, and {BROKEN."
            ]
            registry.write_text(json.dumps(malformed_prompt), encoding="utf-8")
            malformed_prompt_errors = codex_automation_registry_lint.validate_registry(
                registry
            )

        self.assertEqual([], valid_errors)
        self.assertEqual([], not_exposed_errors)
        self.assertIn(
            "operator_trigger_contract.stage_assignments.review.reasoning_effort.value "
            "must not use the reserved token not_exposed when visibility is exposed",
            reserved_exposed_errors,
        )
        self.assertIn(
            "framework-monitor: operator_trigger automation must use status MANUAL",
            invalid_errors,
        )
        self.assertIn(
            "framework-monitor: operator_trigger trigger_policy must be explicit_user_request",
            invalid_errors,
        )
        self.assertTrue(
            any("automations[0] has unknown fields" in error for error in invalid_errors),
            invalid_errors,
        )
        self.assertIn(
            "framework-monitor: monitor operator trigger autonomy_level must be observe",
            invalid_errors,
        )
        self.assertIn(
            "framework-monitor: operator_trigger model_route must match operator_trigger_contract.default_model_route",
            invalid_errors,
        )
        self.assertIn(
            "framework-monitor: prompt_lines are missing required placeholders: PROJECT_ROOT, RUN_SLOT",
            invalid_errors,
        )
        self.assertTrue(
            any(
                "operator_trigger_contract is missing fields: model_routing_reference" in error
                for error in invalid_errors
            ),
            invalid_errors,
        )
        self.assertTrue(
            any(
                "operator_trigger_contract has unknown fields: model_routing_file" in error
                for error in invalid_errors
            ),
            invalid_errors,
        )
        self.assertIn(
            "operator_trigger_contract.source_chain_order must resolve to chain_stage values monitor, review, apply, assurance",
            invalid_errors,
        )
        self.assertIn(
            "operator_trigger_contract.stage_assignments.review has unknown fields: provider",
            assignment_errors,
        )
        self.assertIn(
            "operator_trigger_contract.stage_assignments.review.model_label.value must use canonical NFKC text with collapsed whitespace",
            assignment_errors,
        )
        self.assertIn(
            "operator_trigger_contract.stage_assignments.review.reasoning_effort.visibility must be exposed or not_exposed",
            assignment_errors,
        )
        self.assertIn(
            "operator_trigger_contract.stage_assignments.review.execution_mode must be an object",
            assignment_errors,
        )
        self.assertIn(
            "framework-monitor: prompt_lines contain malformed placeholder syntax",
            malformed_prompt_errors,
        )
        self.assertIn(
            "framework-monitor: prompt_lines contain unsupported placeholders: UNKNOWN",
            malformed_prompt_errors,
        )

    def test_instruction_sources_are_sole_instruction_path_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (root / "target.md").write_text("# Target\n", encoding="utf-8")
            linked = root / "linked.md"
            linked.symlink_to(root / "target.md")
            path = root / "registry.json"

            entry = cron_entry(prompt="Read AGENTS.md and target.md before acting.")
            path.write_text(json.dumps(registry_document([entry])), encoding="utf-8")
            undeclared_prompt_errors = codex_automation_registry_lint.validate_registry(path)

            entry["instruction_sources"] = ["missing.md"]
            path.write_text(json.dumps(registry_document([entry])), encoding="utf-8")
            missing_errors = codex_automation_registry_lint.validate_registry(path)

            entry["instruction_sources"] = [
                "../outside.md",
                "https://example.com/policy",
                "linked.md",
            ]
            path.write_text(json.dumps(registry_document([entry])), encoding="utf-8")
            unsafe_errors = codex_automation_registry_lint.validate_registry(path)

        self.assertEqual([], undeclared_prompt_errors)
        self.assertTrue(
            any(
                "file does not exist as a regular non-symlink file: missing.md" in error
                for error in missing_errors
            ),
            missing_errors,
        )
        self.assertTrue(any("must be a safe repo-relative path" in error for error in unsafe_errors))
        self.assertTrue(
            any("must be repo-relative, not a URI or absolute path" in error for error in unsafe_errors)
        )
        self.assertTrue(any("must not include symlink components" in error for error in unsafe_errors))

    def test_closed_schema_rejects_v5_aliases_and_untyped_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            path = root / "registry.json"
            document = registry_document([cron_entry()])
            document["legacy_metadata"] = {}
            document["schema_version"] = 5
            document["automations"][0]["prompt"] = document["automations"][0].pop(
                "prompt_lines"
            )
            document["automations"][0]["execution_environment"] = "local"
            document["automations"][0]["cadence_role"] = "inferred_from_prompt"
            path.write_text(json.dumps(document), encoding="utf-8")
            errors = codex_automation_registry_lint.validate_registry(path)

        self.assertIn("registry has unknown fields: legacy_metadata", errors)
        self.assertIn("schema_version must be 6", errors)
        self.assertTrue(
            any("automations[0] is missing fields: prompt_lines" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("automations[0] has unknown fields: prompt" in error for error in errors),
            errors,
        )
        self.assertIn(
            "weekly-monitor: execution_environment must be an object",
            errors,
        )
        self.assertTrue(
            any("weekly-monitor: cadence_role must be one of" in error for error in errors),
            errors,
        )

    def test_host_path_leak_scan_covers_top_level_and_operator_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (root / "model-routing.md").write_text("# Explanation\n", encoding="utf-8")
            path = root / "registry.json"
            host_path = "/" + "Users" + "/example/project"

            top_level = registry_document([cron_entry()])
            top_level["install_notes"] = [f"Run from {host_path}."]
            path.write_text(json.dumps(top_level), encoding="utf-8")
            top_level_errors = codex_automation_registry_lint.validate_registry(path)

            contract_document = registry_document(
                [operator_entry(stage) for stage in ("monitor", "review", "apply", "assurance")]
            )
            contract_document["operator_trigger_contract"] = operator_contract()
            contract_document["operator_trigger_contract"]["scope_placeholder"] = host_path
            path.write_text(json.dumps(contract_document), encoding="utf-8")
            contract_errors = codex_automation_registry_lint.validate_registry(path)

        self.assertIn(
            "$.install_notes[0]: must not contain host-specific absolute paths",
            top_level_errors,
        )
        self.assertIn(
            "$.operator_trigger_contract.scope_placeholder: must not contain host-specific absolute paths",
            contract_errors,
        )

    def test_formal_rrule_parser_rejects_malformed_duplicate_and_out_of_range_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            path = root / "registry.json"
            entries = [
                cron_entry("malformed"),
                cron_entry("duplicate"),
                cron_entry("range"),
                cron_entry("until"),
            ]
            entries[0]["rrule"] = "FREQ =WEEKLY"
            entries[1]["rrule"] = "FREQ=WEEKLY;FREQ=MONTHLY"
            entries[2]["rrule"] = "FREQ=MONTHLY;BYMONTH=13;INTERVAL=0"
            entries[3]["rrule"] = "FREQ=YEARLY;UNTIL=20261399"
            path.write_text(json.dumps(registry_document(entries)), encoding="utf-8")
            errors = codex_automation_registry_lint.validate_registry(path)

        self.assertIn("malformed: rrule must use canonical RRULE key=value syntax", errors)
        self.assertIn("duplicate: rrule repeats key FREQ", errors)
        self.assertIn("range: RRULE INTERVAL must be a positive integer", errors)
        self.assertIn("range: RRULE BYMONTH value 13 is outside its allowed range", errors)
        self.assertIn(
            "until: RRULE UNTIL must be a valid YYYYMMDD or YYYYMMDDTHHMMSSZ value",
            errors,
        )

    def test_registry_infers_nested_framework_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            charter = root / "runtime" / "operative_charter.md"
            charter.parent.mkdir()
            charter.write_text("# Charter\n", encoding="utf-8")
            entry = cron_entry()
            entry["instruction_sources"] = ["AGENTS.md", "runtime/operative_charter.md"]
            registry = root / "private" / "authoring" / "automation" / "registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps(registry_document([entry])),
                encoding="utf-8",
            )

            errors = codex_automation_registry_lint.validate_registry(registry)

        self.assertEqual([], errors)

    def test_cli_rejects_registry_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(
                json.dumps(registry_document([cron_entry()])),
                encoding="utf-8",
            )
            linked_registry = root / "registry-link.json"
            linked_registry.symlink_to(registry)

            result = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(REPO_ROOT / "scripts" / "codex_automation_registry_lint.py"),
                    str(linked_registry),
                    "--root",
                    str(root),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not include symlink components", result.stdout)
