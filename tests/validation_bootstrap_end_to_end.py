"""End-to-end project-bootstrap contracts that cross runtime-owned surfaces."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from typing import cast

from tests.validation_test_support import (
    REPO_ROOT,
    SCRIPTS_DIR,
    TEST_FRAMEWORK_RUNNER,
    run_bounded,
    valid_automation_job,
)

import bootstrap_transaction  # noqa: E402
import conformance_check  # noqa: E402
import integration_registry  # noqa: E402
import project_bootstrap  # noqa: E402
import safe_paths  # noqa: E402


def _write_answers(path: Path, answers: dict[str, object]) -> None:
    path.write_text(
        json.dumps(answers, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _minimal_answers() -> dict[str, object]:
    return {
        "project_name": "Bootstrap Matrix",
        "bootstrap_mode": "minimal",
        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
        "agent": "Codex",
        "tech_stack": "Python CLI test fixture",
        "commands": {
            "build": "none",
            "test": "none",
            "lint": "none",
            "type_check": "none",
        },
        "auxiliary_tools": [
            {
                "name": "review-tool",
                "purpose": "Run a bounded project review.",
                "source": "approved/review-tool",
                "version": "reviewed 2026-07-14",
                "permissions": "read-only project files",
                "owner": "project",
                "transport": "native runtime integration",
                "capability_surface": "bounded review commands",
                "data_boundary": "project files",
                "effect_boundary": "read-only report generation; no project writes or external actions",
                "persistence": "report exists only in the active task unless explicitly saved",
                "trust": "approved project package; output remains advisory",
                "credential_source": "none",
                "env_allowlist": "none",
                "approval": "none",
                "control_role": "none",
                "review": "inspect the package source and update path before upgrade",
            }
        ],
    }


def _run_bootstrap(
    answers_path: Path,
    project_root: Path,
    runtime: str,
    *extra_arguments: str,
) -> tuple[int, dict[str, object], str]:
    result = run_bounded(
        [
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
            runtime,
            "--framework-ref",
            os.path.relpath(REPO_ROOT, project_root),
            "--framework-revision-policy",
            "pinned",
            *extra_arguments,
        ],
        cwd=REPO_ROOT,
    )
    return result.returncode, json.loads(result.stdout), result.stderr


def _write_plan_approval_arguments(report: dict[str, object]) -> tuple[str, ...]:
    return (
        "--approve-write-plan-sha256",
        cast(str, report["write_plan_sha256"]),
    )


def _run_approved_bootstrap(
    answers_path: Path,
    project_root: Path,
    runtime: str,
    *extra_arguments: str,
) -> tuple[int, dict[str, object], str]:
    dry_code, dry_report, dry_stderr = _run_bootstrap(
        answers_path,
        project_root,
        runtime,
        *extra_arguments,
        "--dry-run",
    )
    if dry_code != 0:
        raise AssertionError((dry_report, dry_stderr))
    return _run_bootstrap(
        answers_path,
        project_root,
        runtime,
        *extra_arguments,
        *_write_plan_approval_arguments(dry_report),
    )


def _run_project_gate(
    script_name: str,
    project_root: Path,
    contract_root_ref: str,
    project_kind: str,
    *,
    profile: str = "core-project",
    scripts_dir: Path = SCRIPTS_DIR,
) -> dict[str, object]:
    contract_arguments = (
        []
        if contract_root_ref == "."
        else ["--contract-root", contract_root_ref]
    )
    if script_name == "project_instance_lint.py":
        arguments = [
            "--project-root",
            str(project_root),
            *contract_arguments,
            "--project-kind",
            project_kind,
            "--framework-root",
            str(scripts_dir.parent),
        ]
    elif script_name == "project_contract_sync.py":
        arguments = [
            "--strict-warnings",
            str(project_root),
            *contract_arguments,
            "--project-kind",
            project_kind,
        ]
    elif script_name == "conformance_check.py":
        arguments = [
            "--profile",
            profile,
            "--root",
            str(project_root),
            *contract_arguments,
            "--project-kind",
            project_kind,
            "--strict-warnings",
            "--format",
            "json",
        ]
    else:  # pragma: no cover - this helper owns a closed gate set.
        raise AssertionError(f"unsupported project gate: {script_name}")
    result = run_bounded(
        [sys.executable, "-B", str(scripts_dir / script_name), *arguments],
        cwd=scripts_dir.parent,
    )
    report = json.loads(result.stdout)
    if result.returncode != 0:
        raise AssertionError((script_name, report, result.stderr))
    return cast(dict[str, object], report)


class BootstrapEndToEndTests(unittest.TestCase):
    def test_project_bootstrap_cli_materializes_and_conforms_every_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())

            for runtime in integration_registry.family_names(REPO_ROOT):
                with self.subTest(runtime=runtime):
                    project_root = root / f"project-{runtime}"
                    project_root.mkdir()
                    return_code, report, stderr = _run_approved_bootstrap(
                        answers_path,
                        project_root,
                        runtime,
                    )
                    self.assertEqual(0, return_code, (report, stderr))

                    config = integration_registry.family_config(runtime, REPO_ROOT)
                    entrypoint_name = cast(str, config["entrypoint"]["output"])
                    entrypoint = project_root / entrypoint_name
                    self.assertTrue(entrypoint.is_file())
                    entrypoint_text = entrypoint.read_text(encoding="utf-8")
                    framework_ref, errors = (
                        integration_registry.entrypoint_authority_load_references(
                            entrypoint_name,
                            entrypoint_text,
                            contract_root_ref=".",
                        )
                    )
                    self.assertEqual([], errors)
                    self.assertEqual(
                        os.path.relpath(REPO_ROOT, project_root),
                        framework_ref,
                    )
                    self.assertNotIn("{{", entrypoint_text)
                    self.assertNotIn("}}", entrypoint_text)
                    self.assertFalse(
                        safe_paths.contains_host_identity_path(entrypoint_text)
                    )

                    project_contract = (
                        project_root / "AGENT_PROJECT.md"
                    ).read_text(encoding="utf-8")
                    statement_of_work = (
                        project_root / "STATEMENT_OF_WORK.md"
                    ).read_text(encoding="utf-8")
                    self.assertIn("env allowlist: none", statement_of_work)
                    self.assertNotIn("env allowlist:", project_contract)
                    self.assertIn(
                        "review-tool — Run a bounded project review. — "
                        "load STATEMENT_OF_WORK.md Auxiliary Tools entry before use",
                        project_contract,
                    )

                    retained_input = json.loads(
                        (project_root / "PROJECT_INPUT.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    receipt = json.loads(
                        (project_root / "PROJECT_INSTANCE.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual("downstream", retained_input["project_kind"])
                    self.assertEqual(runtime, retained_input["runtime"])
                    self.assertEqual(
                        project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION,
                        receipt["schema_version"],
                    )
                    self.assertEqual("PROJECT_INPUT.json", receipt["input_source"])
                    self.assertEqual(["core-project"], receipt["active_profiles"])
                    self.assertEqual(runtime, receipt["runtime"])

                    for gate in (
                        "project_instance_lint.py",
                        "project_contract_sync.py",
                        "conformance_check.py",
                    ):
                        gate_report = _run_project_gate(
                            gate,
                            project_root,
                            ".",
                            "downstream",
                        )
                        self.assertEqual([], gate_report["errors"], gate_report)

                    link_result = run_bounded(
                        [
                            sys.executable,
                            "-B",
                            str(SCRIPTS_DIR / "link_check.py"),
                            "--root",
                            str(project_root),
                        ],
                        cwd=REPO_ROOT,
                    )
                    link_report = json.loads(link_result.stdout)
                    self.assertEqual(0, link_result.returncode, link_report)
                    self.assertEqual([], link_report["errors"])

    def test_receipt_activated_profiles_are_individually_strict_conformant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            (project_root / "task_orders").mkdir(parents=True)
            (project_root / "task_orders" / "automation.md").write_text(
                "# Project Automation\n",
                encoding="utf-8",
            )
            answers_path = root / "answers.json"
            answers = _minimal_answers()
            automation_job = valid_automation_job()
            automation_job["outputs"] = ["artifacts/weekly_report.md"]
            answers.update(
                {
                    "include_source_packs": True,
                    "include_source_update": True,
                    "include_security_verification": True,
                    "include_automation_orders": True,
                    "automation_orders": {"jobs": [automation_job]},
                    "include_precedents": True,
                    "include_reviewer_lane_feedback": True,
                }
            )
            _write_answers(answers_path, answers)

            return_code, report, stderr = _run_approved_bootstrap(
                answers_path,
                project_root,
                "generic",
            )
            self.assertEqual(0, return_code, (report, stderr))
            receipt = json.loads(
                (project_root / "PROJECT_INSTANCE.json").read_text(
                    encoding="utf-8"
                )
            )
            active_profiles = cast(list[str], receipt["active_profiles"])
            self.assertEqual(
                [
                    "core-project",
                    "source-managed",
                    "security-managed",
                    "automation-managed",
                    "multi-agent-managed",
                    "reviewer-lane-managed",
                ],
                active_profiles,
            )

            for profile in active_profiles:
                with self.subTest(profile=profile):
                    gate_report = _run_project_gate(
                        "conformance_check.py",
                        project_root,
                        ".",
                        "downstream",
                        profile=profile,
                    )
                    self.assertEqual("pass", gate_report["status"], gate_report)
                    self.assertEqual([], gate_report["errors"], gate_report)
                    self.assertEqual([], gate_report["warnings"], gate_report)

    def test_nested_downstream_keeps_single_receipt_at_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            contract_root_ref = ".mpa/contracts"

            return_code, report, stderr = _run_approved_bootstrap(
                answers_path,
                project_root,
                "generic",
                "--contract-root",
                contract_root_ref,
                "--create-contract-root",
            )

            self.assertEqual(0, return_code, (report, stderr))
            contract_root = project_root / contract_root_ref
            self.assertTrue((contract_root / "PROJECT_INPUT.json").is_file())
            self.assertFalse((contract_root / "PROJECT_INSTANCE.json").exists())
            receipt = json.loads(
                (project_root / "PROJECT_INSTANCE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(5, receipt["schema_version"])
            self.assertEqual(contract_root_ref, receipt["contract_root"])
            self.assertEqual(
                f"{contract_root_ref}/PROJECT_INPUT.json",
                receipt["input_source"],
            )

            for gate in (
                "project_instance_lint.py",
                "project_contract_sync.py",
                "conformance_check.py",
            ):
                gate_report = _run_project_gate(
                    gate,
                    project_root,
                    contract_root_ref,
                    "downstream",
                )
                self.assertEqual([], gate_report["errors"], gate_report)

    def test_failed_post_install_conformance_rolls_back_bootstrap_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            with mock.patch.object(
                conformance_check,
                "run_profiles",
                return_value={
                    "status": "fail",
                    "errors": ["injected semantic failure"],
                    "warnings": [],
                },
            ):
                with self.assertRaises(
                    bootstrap_transaction.BootstrapTransactionError
                ):
                    project_bootstrap.write_bootstrap_outputs(
                        inputs,
                        answers,
                        outputs,
                        framework_identity=plan.framework_identity,
                    )

            self.assertTrue(project_root.is_dir())
            self.assertFalse((project_root / "STATEMENT_OF_WORK.md").exists())

    def test_initial_bootstrap_rechecks_absent_output_preimages_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            raced_target = project_root / "TODO.md"
            raced_target.write_text("concurrent owner bytes\n", encoding="utf-8")

            with self.assertRaises(bootstrap_transaction.BootstrapTransactionError):
                project_bootstrap.write_bootstrap_outputs(
                    inputs,
                    answers,
                    outputs,
                    framework_identity=plan.framework_identity,
                )

            self.assertEqual(
                "concurrent owner bytes\n",
                raced_target.read_text(encoding="utf-8"),
            )
            self.assertEqual(["TODO.md"], [path.name for path in project_root.iterdir()])

    def test_framework_identity_change_before_verification_rolls_back_create(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            changed_identity = project_bootstrap.FrameworkIdentity(
                content_sha256="a" * 64,
                effective_file_digests=(("changed", "b" * 64),),
                distribution_sha256="c" * 64,
            )
            with (
                mock.patch.object(
                    project_bootstrap,
                    "capture_framework_identity",
                    return_value=changed_identity,
                ),
                mock.patch.object(conformance_check, "run_profiles") as conformance,
                self.assertRaises(bootstrap_transaction.BootstrapTransactionError),
            ):
                project_bootstrap.write_bootstrap_outputs(
                    inputs,
                    answers,
                    outputs,
                    framework_identity=plan.framework_identity,
                )

            conformance.assert_not_called()
            self.assertTrue(project_root.is_dir())
            self.assertFalse((project_root / "STATEMENT_OF_WORK.md").exists())

    def test_framework_identity_change_during_verification_rolls_back_create(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            changed_identity = project_bootstrap.FrameworkIdentity(
                content_sha256="a" * 64,
                effective_file_digests=(("changed", "b" * 64),),
                distribution_sha256="c" * 64,
            )
            with (
                mock.patch.object(
                    project_bootstrap,
                    "capture_framework_identity",
                    side_effect=(plan.framework_identity, changed_identity),
                ),
                mock.patch.object(
                    conformance_check,
                    "run_profiles",
                    return_value={
                        "status": "pass",
                        "errors": [],
                        "warnings": [],
                    },
                ) as conformance,
                self.assertRaises(bootstrap_transaction.BootstrapTransactionError),
            ):
                project_bootstrap.write_bootstrap_outputs(
                    inputs,
                    answers,
                    outputs,
                    framework_identity=plan.framework_identity,
                )

            conformance.assert_called_once_with(
                ["core-project"],
                project_root,
                contract_root=project_root,
                contract_root_ref=".",
                project_kind="downstream",
            )
            self.assertTrue(project_root.is_dir())
            self.assertFalse((project_root / "STATEMENT_OF_WORK.md").exists())

    def test_post_install_verifies_union_of_every_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            answers_payload = _minimal_answers()
            answers_payload["include_source_update"] = True
            answers_payload["include_source_packs"] = True
            answers_payload["include_security_verification"] = True
            _write_answers(answers_path, answers_payload)
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual([], project_bootstrap.bootstrap_validation_errors(inputs))
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            with mock.patch.object(
                conformance_check,
                "run_profiles",
                return_value={
                    "status": "pass",
                    "errors": [],
                    "warnings": [],
                },
            ) as conformance:
                result = project_bootstrap.write_bootstrap_outputs(
                    inputs,
                    answers,
                    outputs,
                    framework_identity=plan.framework_identity,
                )

        self.assertTrue(result.written)
        conformance.assert_called_once_with(
            ["core-project", "source-managed", "security-managed"],
            project_root,
            contract_root=project_root,
            contract_root_ref=".",
            project_kind="downstream",
        )

    def test_post_install_warning_is_nonwaivable_during_initial_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_answers(answers_path, _minimal_answers())
            inputs = project_bootstrap.load_bootstrap_inputs(
                project_bootstrap.BootstrapOptions(
                    answers=str(answers_path),
                    project_root=str(project_root),
                    project_kind="downstream",
                    contract_root=None,
                    setup_profile=None,
                    runtime="generic",
                    framework_ref=os.path.relpath(REPO_ROOT, project_root),
                    dry_run=False,
                    create_contract_root=False,
                    framework_revision_policy="live",
                )
            )
            self.assertEqual(
                [],
                project_bootstrap.bootstrap_validation_errors(inputs),
            )
            answers = cast(dict[str, object], inputs.effective_answers)
            answers_bytes = cast(bytes, inputs.answers_bytes)
            plan = project_bootstrap.build_bootstrap_write_plan(inputs, answers)
            outputs = project_bootstrap.render_bootstrap_write_outputs(
                inputs,
                answers,
                answers_bytes,
                plan.effective_date,
                framework_identity=plan.framework_identity,
            )
            run_profiles_result = {
                "status": "warn",
                "errors": [],
                "warnings": ["reviewed project warning"],
            }
            with mock.patch.object(
                conformance_check,
                "run_profiles",
                return_value=run_profiles_result,
            ):
                with self.assertRaises(
                    bootstrap_transaction.BootstrapTransactionError
                ):
                    project_bootstrap.write_bootstrap_outputs(
                        inputs,
                        answers,
                        outputs,
                        framework_identity=plan.framework_identity,
                    )
                self.assertTrue(project_root.is_dir())
                self.assertFalse(
                    (project_root / "STATEMENT_OF_WORK.md").exists()
                )

    def test_project_bootstrap_write_plan_approval_cannot_waive_full_mode_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.json"
            project_root = root / "project"
            project_root.mkdir()
            _write_answers(
                answers_path,
                {
                    "project_name": "Deferred Full Project",
                    "bootstrap_mode": "full",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "agent": "Codex",
                    "tech_stack": "Replace with project stack",
                    "in_scope": ["Replace with in-scope project work"],
                    "language_runtime_standards": "Replace with project language version",
                    "out_of_scope": ["Replace with excluded project work"],
                    "commands": {
                        "build": "none",
                        "test": "replace-with-project-test-command",
                    },
                    "deliverables": [
                        {
                            "description": "Replace with the first deliverable",
                            "test": "replace-with-project-test-command",
                            "pass_criteria": "Replace with project-specific pass criteria",
                        }
                    ],
                },
            )

            return_code, report, stderr = _run_bootstrap(
                answers_path,
                project_root,
                "codex",
                "--approve-write-plan-sha256",
                "0" * 64,
            )
            sow_exists = (project_root / "STATEMENT_OF_WORK.md").exists()

        self.assertNotEqual(0, return_code, (report, stderr))
        errors = cast(list[str], report["errors"])
        self.assertTrue(
            any("full bootstrap requires" in item for item in errors),
            report,
        )
        self.assertFalse(sow_exists)

    def test_project_bootstrap_dry_run_preserves_distinct_warning_causes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            answers_path = project_root / "answers.json"
            answers = _minimal_answers()
            answers["verification_profiles"] = [
                "Contract sync: uv run python -B scripts/project_contract_sync.py "
                f"--strict-warnings {project_root}"
            ]
            _write_answers(answers_path, answers)

            return_code, report, stderr = _run_bootstrap(
                answers_path,
                project_root,
                "codex",
                "--dry-run",
            )

        self.assertEqual(0, return_code, (report, stderr))
        warnings = cast(list[str], report["warnings"])
        self.assertTrue(
            any(
                "bootstrap answers file is inside the target project root" in warning
                for warning in warnings
            ),
            warnings,
        )
        self.assertTrue(
            any(
                "host-specific absolute path in verification_profiles" in warning
                for warning in warnings
            ),
            warnings,
        )
