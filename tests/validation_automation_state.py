"""Automation manifest, cron rendering, and scheduled-runtime tests."""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import date
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from unittest import mock
from typing import Any, cast
from zoneinfo import ZoneInfoNotFoundError

from tests.validation_test_support import (
    REPO_ROOT,
    compile_adjacent_bytecode,
    run_bounded,
    valid_automation_job,
)

import automation_orders_lint  # noqa: E402
import project_state_lint  # noqa: E402
import render_cron  # noqa: E402
import run_scheduled_job  # noqa: E402


def valid_external_review() -> dict[str, object]:
    return {
        "allowed_data_classes": ["public_source_urls"],
        "authentication": "none",
        "egress": "approved_endpoints_only",
        "max_requests": 10,
        "redaction": "before_egress",
        "retained_artifacts": "sanitized_result_only",
        "retention_days": 30,
        "sensitive_data": "deny",
        "unlisted_data": "deny",
    }


def valid_source_policy() -> dict[str, object]:
    return {
        "allowed_capabilities": ["read", "search"],
        "max_requests_per_run": 25,
        "oauth_scopes": ["content.read"],
        "primary_source_verification": "required",
        "retention_days": 30,
        "source_aliases": ["approved_account"],
        "terms_reviewed_on": "2026-06-30",
        "write_access": "deny",
    }


def valid_parser_change() -> dict[str, object]:
    digest = "sha256:" + "1" * 64
    return {
        "approval_record": "tests/fixtures/parser_change_approval.json",
        "approved_output_digests": [digest],
        "change_kind": "parser",
        "change_record": "tests/fixtures/parser_change_diff.json",
        "expected_output_digests": [digest],
        "fail_closed_action": "manual_review",
        "golden_fixture_paths": [
            "tests/fixtures/source_monitor/input.html",
            "tests/fixtures/source_monitor/output.json",
        ],
        "implementation_version": "abc1234",
        "input_fixture_digests": [digest],
        "old_new_comparison_completed": True,
        "primary_evidence_verified": True,
        "schema_version": "v1",
        "verification_command": (
            "uv run python -B scripts/source_parser_check.py "
            "--fixtures tests/fixtures/source_monitor"
        ),
    }


class AutomationStateTests(unittest.TestCase):
    def test_automation_lint_rejects_ambiguous_or_unsafe_manifest_values(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "approval_mode": "per_run",
                "autonomy_level": "act",
                "command": "uv run python report.py\nuv run python other.py",
                "concurrency": "allow",
                "id": "nightly",
                "objective": "Run report",
                "timeout_minutes": True,
                "write_scope": "repo",
            }
        )
        authority = cast(dict[str, object], job["authority"])
        authority["basis"] = "per_run_user_approval"
        authority["effect_class"] = "repo_write"
        validity = cast(dict[str, object], authority["validity"])
        validity.update(
            {
                "expires_on": None,
                "mode": "per_run",
                "revocation_events": ["user_revocation"],
            }
        )
        manifest = {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "preferred_backend": "cron",
            "jobs": [job],
        }

        errors, warnings = automation_orders_lint.validate_manifest(manifest)

        self.assertEqual([], warnings)
        self.assertIn("job nightly: command must not contain control characters", errors)
        self.assertIn(
            "job nightly: timeout_minutes must be an integer from 1 through 60",
            errors,
        )
        self.assertIn("job nightly: act jobs require approval_mode standing_order", errors)
        self.assertIn("job nightly: act jobs must use concurrency forbid", errors)

        for field in automation_orders_lint.AUTOMATION_SOW_SUMMARY_FIELDS:
            for separator in (
                "\x00",
                "\x07",
                "\t",
                "\x7f",
                "\x85",
                "\u2028",
                "\u2029",
            ):
                with self.subTest(field=field, separator=ascii(separator)):
                    unicode_separator_job = valid_automation_job()
                    unicode_separator_job[field] = (
                        f"{unicode_separator_job[field]}{separator}injected"
                    )
                    expected_job_id = (
                        "<invalid-id>" if field == "id" else "weekly_report"
                    )
                    expected_error = (
                        f"job {expected_job_id}: {field} must not contain "
                        "control characters"
                    )
                    unicode_errors, unicode_warnings = (
                        automation_orders_lint.validate_manifest(
                            {
                                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                                "preferred_backend": "cron",
                                "jobs": [unicode_separator_job],
                            }
                        )
                    )
                    self.assertEqual([], unicode_warnings)
                    self.assertEqual(
                        1,
                        unicode_errors.count(expected_error),
                        unicode_errors,
                    )

    def test_automation_lint_rejects_generated_sow_comment_in_summary_fields(self) -> None:
        for field in automation_orders_lint.AUTOMATION_SOW_SUMMARY_FIELDS:
            with self.subTest(field=field):
                job = valid_automation_job()
                job[field] = f"{job[field]} <!-- injected policy -->"

                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )

                self.assertEqual([], warnings)
                expected_job_id = (
                    "<invalid-id>" if field == "id" else "weekly_report"
                )
                expected_error = (
                    f"job {expected_job_id}: {field} must not contain generated-SOW "
                    "HTML comment syntax"
                )
                self.assertEqual(1, errors.count(expected_error), errors)

    def test_automation_lint_rejects_controls_in_generic_string_surfaces(self) -> None:
        cases = (
            (
                "command",
                lambda job: job.__setitem__("command", "printf\x00unsafe"),
                "job weekly_report: command must not contain control characters",
            ),
            (
                "outputs",
                lambda job: job.__setitem__("outputs", ["artifacts/report\x00.json"]),
                "job weekly_report: outputs must be non-empty strings without "
                "control characters",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(surface=label):
                job = valid_automation_job()
                mutate(job)
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )
                self.assertEqual([], warnings)
                self.assertEqual([expected], errors)

    def test_automation_lint_accepts_empty_starter_manifest(self) -> None:
        errors, warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "unspecified",
                "jobs": [],
            }
        )

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_automation_orders_lint_cli_contract_covers_generic_cron_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "task_orders").mkdir()
            (project / "task_orders" / "automation.md").write_text(
                "# Automation\n",
                encoding="utf-8",
            )
            valid_manifest = project / "AUTOMATION_ORDERS.json"
            valid_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [valid_automation_job()],
                    }
                ),
                encoding="utf-8",
            )
            invalid_job = deepcopy(valid_automation_job())
            invalid_job["timeout_minutes"] = True
            invalid_manifest = project / "AUTOMATION_ORDERS.bad.json"
            invalid_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [invalid_job],
                        "unexpected": True,
                    }
                ),
                encoding="utf-8",
            )

            cases = (
                ("generic", valid_manifest, (), 0),
                ("cron", valid_manifest, ("--target", "cron"), 0),
                ("invalid", invalid_manifest, (), 1),
            )
            reports: dict[str, dict[str, object]] = {}
            for label, manifest, extra_arguments, expected_result in cases:
                with self.subTest(label=label), mock.patch.object(
                    sys,
                    "argv",
                    [
                        "automation_orders_lint.py",
                        str(manifest),
                        "--project-root",
                        str(project),
                        *extra_arguments,
                    ],
                ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = automation_orders_lint.main()
                self.assertEqual(expected_result, result, stdout.getvalue())
                reports[label] = json.loads(stdout.getvalue())

        for label in ("generic", "cron"):
            self.assertEqual([], reports[label]["errors"])
            self.assertEqual([], reports[label]["warnings"])
        invalid_errors = cast(list[str], reports["invalid"]["errors"])
        self.assertIn("unknown top-level key: unexpected", invalid_errors)
        self.assertIn(
            "job weekly_report: timeout_minutes must be an integer from 1 through 60",
            invalid_errors,
        )

    def test_tracked_automation_orders_template_passes_the_cli_contract(self) -> None:
        manifest = REPO_ROOT / "project_state_templates" / "AUTOMATION_ORDERS.json"
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "automation_orders_lint.py",
                    str(manifest),
                    "--project-root",
                    str(REPO_ROOT),
                ],
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = automation_orders_lint.main()

        self.assertEqual(0, result, stdout.getvalue())
        self.assertEqual(
            {"errors": [], "warnings": []},
            json.loads(stdout.getvalue()),
        )

    def test_automation_cli_reports_excessive_json_nesting_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "automation_orders_lint.py",
                        str(manifest),
                        "--project-root",
                        str(project),
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = automation_orders_lint.main()

            report = json.loads(stdout.getvalue())
            self.assertEqual(1, result)
            self.assertEqual([], report["warnings"])
            self.assertEqual(1, len(report["errors"]), report)
            self.assertIn(
                "JSON nesting exceeds the supported parser depth",
                report["errors"][0],
            )
            self.assertEqual([manifest], list(project.iterdir()))

    def test_non_object_manifest_preserves_independent_cron_boundary_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_root = Path(temp_dir) / "missing-project"
            errors, warnings = automation_orders_lint.validate_manifest(
                [],
                target="cron",
                project_root=missing_root,
                manifest_path=None,
            )

        self.assertEqual([], warnings)
        self.assertTrue(
            any("selected project root" in error for error in errors),
            errors,
        )
        self.assertIn(
            "target cron requires an explicit automation manifest path",
            errors,
        )
        self.assertIn("manifest must be a JSON object", errors)

    def test_automation_lint_requires_one_safe_preferred_backend(self) -> None:
        base = {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "jobs": [],
        }
        missing_errors, _ = automation_orders_lint.validate_manifest(base)
        invalid_errors, _ = automation_orders_lint.validate_manifest(
            {**base, "preferred_backend": "CI scheduler"}
        )
        mismatched_errors, _ = automation_orders_lint.validate_manifest(
            {**base, "preferred_backend": "systemd"},
            target="cron",
            project_root=REPO_ROOT,
            manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
            require_existing_project_root=False,
        )

        self.assertIn(
            "manifest is missing top-level keys ['preferred_backend']",
            missing_errors,
        )
        self.assertTrue(
            any("lowercase slug" in error for error in invalid_errors),
            invalid_errors,
        )
        self.assertIn(
            "target cron requires preferred_backend 'cron', got 'systemd'",
            mismatched_errors,
        )

    def test_automation_lint_missing_manifest_is_only_prospective_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            missing_manifest = project / "AUTOMATION_ORDERS.json"
            data = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [],
            }

            actual_errors, _ = automation_orders_lint.validate_manifest(
                data,
                target="cron",
                project_root=project,
                manifest_path=missing_manifest,
            )
            prospective_errors, _ = automation_orders_lint.validate_manifest(
                data,
                target="cron",
                project_root=project,
                manifest_path=missing_manifest,
                require_existing_project_root=False,
            )

        self.assertTrue(
            any("automation manifest does not exist" in error for error in actual_errors),
            actual_errors,
        )
        self.assertEqual([], prospective_errors)

    def test_automation_lint_rejects_control_bearing_job_ids(self) -> None:
        for suffix in ("\n", "\r", "\x00", "\x7f"):
            with self.subTest(suffix=repr(suffix)):
                job = valid_automation_job()
                job["id"] = f"weekly_report{suffix}"
                errors, _ = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )
                expected_fragment = "id must not contain control characters"
                self.assertTrue(
                    any(expected_fragment in error for error in errors),
                    errors,
                )
                self.assertTrue(
                    all(error.startswith("job <invalid-id>:") for error in errors),
                    errors,
                )

    def test_invalid_approval_mode_type_does_not_enter_authority_parity(self) -> None:
        job = valid_automation_job()
        job["approval_mode"] = []

        errors, warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [job],
            }
        )

        self.assertEqual([], warnings)
        self.assertEqual(
            ["job weekly_report: approval_mode must be a string"],
            errors,
        )

    def test_invalid_discriminators_do_not_emit_dependent_diagnostics(self) -> None:
        invalid_digest = "not-a-digest"
        cases = (
            (
                "scheduler retention mode",
                (
                    (("scheduler_artifacts", "retention", "mode"), []),
                    (("scheduler_artifacts", "retention", "days"), 1),
                ),
                "job weekly_report: scheduler_artifacts.retention.mode must be a string",
                None,
            ),
            (
                "state checkpoint",
                ((("state_policy", "checkpoint"), []),),
                "job weekly_report: state_policy.checkpoint must be a string",
                None,
            ),
            (
                "project-file write scope",
                (
                    (("write_scope",), []),
                    (("state_policy", "persistence"), "project_file"),
                    (("state_policy", "reference"), "artifacts/state.json"),
                ),
                "job weekly_report: write_scope must be a string",
                None,
            ),
            (
                "idempotency mode",
                ((("idempotency", "mode"), []),),
                "job weekly_report: idempotency.mode must be a string",
                None,
            ),
            (
                "source access class",
                ((("source_access_class",), []),),
                "job weekly_report: source_access_class must be a string",
                None,
            ),
            (
                "external-review retention",
                (
                    (("reviewer_runtime_class",), "model"),
                    (("reviewer_boundary_mode",), "external"),
                    (("external_review",), valid_external_review()),
                    (("external_review", "retained_artifacts"), "none"),
                    (("external_review", "retention_days"), []),
                ),
                "job weekly_report: external_review.retention_days must be an integer from 0 through 3650",
                None,
            ),
            (
                "parser approved digest",
                (
                    (("workload_class",), "parser_or_extractor_change"),
                    (("parser_change",), valid_parser_change()),
                    (
                        ("parser_change", "approved_output_digests"),
                        [invalid_digest],
                    ),
                ),
                "job weekly_report: parser_change.approved_output_digests[1] "
                f"must match {automation_orders_lint.SHA256_TOKEN_RE.pattern}",
                None,
            ),
            (
                "authority basis",
                ((("authority", "basis"), []),),
                "job weekly_report: authority.basis must be a string",
                None,
            ),
            (
                "authority effect class",
                ((("authority", "effect_class"), []),),
                "job weekly_report: authority.effect_class must be a string",
                None,
            ),
            (
                "authority failure action",
                ((("authority", "failure_action"), []),),
                "job weekly_report: authority.failure_action must be a string",
                None,
            ),
            (
                "authority validity mode",
                (
                    (("authority", "validity", "mode"), []),
                    (("authority", "validity", "expires_on"), "2026-12-31"),
                ),
                "job weekly_report: authority.validity.mode must be a string",
                None,
            ),
            (
                "authority revocation event",
                (
                    (
                        ("authority", "validity", "revocation_events"),
                        ["invalid_event"],
                    ),
                ),
                "job weekly_report: authority.validity.revocation_events[1] "
                f"must be one of {sorted(automation_orders_lint.AUTHORITY_REVOCATION_EVENTS)}",
                None,
            ),
            (
                "instruction source",
                (
                    (
                        ("instruction_sources",),
                        [
                            {
                                "path": "task_orders/automation.md\x00",
                                "root": "framework",
                            }
                        ],
                    ),
                ),
                "job weekly_report: instruction_sources[1].path must not contain control characters",
                None,
            ),
            (
                "reviewer boundary",
                (
                    (("reviewer_runtime_class",), "model"),
                    (("reviewer_boundary_mode",), []),
                    (("external_review",), valid_external_review()),
                ),
                "job weekly_report: reviewer_boundary_mode must be a string",
                None,
            ),
            (
                "workload class",
                (
                    (("workload_class",), []),
                    (("parser_change",), valid_parser_change()),
                ),
                "job weekly_report: workload_class must be a string",
                None,
            ),
            (
                "cron concurrency",
                ((("concurrency",), []),),
                "job weekly_report: concurrency must be a string",
                "cron",
            ),
            (
                "cron failure policy",
                ((("failure_policy",), []),),
                "job weekly_report: failure_policy must be a string",
                "cron",
            ),
            (
                "enabled",
                (
                    (("enabled",), "yes"),
                    (("outputs",), []),
                ),
                "job weekly_report: enabled must be boolean",
                None,
            ),
            (
                "outputs",
                ((("outputs",), {}),),
                "job weekly_report: outputs must be a list of strings",
                None,
            ),
            (
                "cwd",
                ((("cwd",), []),),
                "job weekly_report: cwd must be a string",
                None,
            ),
        )

        def assign(
            job: dict[str, object],
            path: tuple[str, ...],
            value: object,
        ) -> None:
            target = job
            for key in path[:-1]:
                nested = target[key]
                self.assertIsInstance(nested, dict)
                target = cast(dict[str, object], nested)
            target[path[-1]] = value

        for label, mutations, expected, target in cases:
            with self.subTest(discriminator=label):
                job = deepcopy(valid_automation_job())
                for path, value in mutations:
                    assign(job, path, deepcopy(value))
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    },
                    target=target,
                    project_root=REPO_ROOT,
                    manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
                    require_existing_project_root=False,
                )
                self.assertEqual([], warnings)
                self.assertEqual([expected], errors)

    def test_enabled_jobs_require_bounded_timeout_and_typed_idempotency(self) -> None:
        missing_idempotency = valid_automation_job()
        del missing_idempotency["idempotency"]
        unknown_idempotency = valid_automation_job()
        unknown_idempotency["idempotency"] = {"key": None, "mode": "tbd"}
        disabled_only = valid_automation_job()
        disabled_only["idempotency"] = {"key": None, "mode": "disabled_only"}
        too_long = valid_automation_job()
        too_long["timeout_minutes"] = automation_orders_lint.MAX_TIMEOUT_MINUTES + 1
        maximum = valid_automation_job()
        maximum["timeout_minutes"] = automation_orders_lint.MAX_TIMEOUT_MINUTES

        reports = [
            automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                }
            )[0]
            for job in (
                missing_idempotency,
                unknown_idempotency,
                disabled_only,
                too_long,
                maximum,
            )
        ]

        self.assertTrue(
            any("missing keys ['idempotency']" in error for error in reports[0]),
            reports[0],
        )
        self.assertTrue(
            any("idempotency.mode must be one of" in error for error in reports[1]),
            reports[1],
        )
        self.assertTrue(
            any("enabled jobs cannot use idempotency.mode disabled_only" in error for error in reports[2]),
            reports[2],
        )
        self.assertTrue(
            any("integer from 1 through 60" in error for error in reports[3]),
            reports[3],
        )
        self.assertEqual([], reports[4])

    def test_enabled_job_authority_is_closed_and_cross_field_consistent(self) -> None:
        missing = valid_automation_job()
        del missing["authority"]
        descriptive_claim = valid_automation_job()
        del descriptive_claim["authority"]
        descriptive_claim["description"] = (
            "This prose claims standing authority, verification, and revocation."
        )
        wrong_effect = valid_automation_job()
        cast(dict[str, object], wrong_effect["authority"])["effect_class"] = "repo_write"
        wrong_validity = valid_automation_job()
        validity = cast(
            dict[str, object],
            cast(dict[str, object], wrong_validity["authority"])["validity"],
        )
        validity["mode"] = "per_run"
        unknown_field = valid_automation_job()
        cast(dict[str, object], unknown_field["authority"])["policy_note"] = "allow"
        expired = valid_automation_job()
        expired_validity = cast(
            dict[str, object],
            cast(dict[str, object], expired["authority"])["validity"],
        )
        expired_validity.update(
            {
                "expires_on": "2000-01-01",
                "mode": "time_window",
                "revocation_events": ["date_reached", "user_revocation"],
            }
        )
        undated_window = valid_automation_job()
        undated_validity = cast(
            dict[str, object],
            cast(dict[str, object], undated_window["authority"])["validity"],
        )
        undated_validity.update(
            {
                "expires_on": "2999-01-01",
                "mode": "time_window",
                "revocation_events": ["user_revocation"],
            }
        )

        reports = [
            automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                }
            )[0]
            for job in (
                missing,
                descriptive_claim,
                wrong_effect,
                wrong_validity,
                unknown_field,
                expired,
                undated_window,
            )
        ]

        self.assertIn(
            "job weekly_report: authority-bearing jobs must define authority",
            reports[0],
        )
        self.assertIn(
            "job weekly_report: authority-bearing jobs must define authority",
            reports[1],
        )
        self.assertTrue(
            any("authority.effect_class must be observe" in error for error in reports[2]),
            reports[2],
        )
        self.assertTrue(
            any("validity.mode must be time_window or until_revoked" in error for error in reports[3]),
            reports[3],
        )
        self.assertTrue(
            any("authority has unknown keys ['policy_note']" in error for error in reports[4]),
            reports[4],
        )
        self.assertTrue(
            any("expires_on must not be in the past" in error for error in reports[5]),
            reports[5],
        )
        self.assertTrue(
            any("must include date_reached for time_window" in error for error in reports[6]),
            reports[6],
        )

    def test_automation_lint_uses_one_effective_date_for_source_and_authority_boundaries(self) -> None:
        job = valid_automation_job()
        job["source_access_class"] = "account_visible"
        source_policy = valid_source_policy()
        source_policy["terms_reviewed_on"] = "2026-07-13"
        job["source_policy"] = source_policy
        authority = cast(dict[str, object], job["authority"])
        validity = cast(dict[str, object], authority["validity"])
        validity.update(
            {
                "expires_on": "2026-07-13",
                "mode": "time_window",
                "revocation_events": ["date_reached", "user_revocation"],
            }
        )
        manifest = {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "preferred_backend": "cron",
            "jobs": [job],
        }

        def validate_on(value: date) -> tuple[list[str], list[str]]:
            with mock.patch.object(
                automation_orders_lint,
                "current_utc_date",
                return_value=value,
            ) as capture_date:
                result = automation_orders_lint.validate_manifest(manifest)
            capture_date.assert_called_once_with()
            return result

        boundary_errors, boundary_warnings = validate_on(date(2026, 7, 13))
        prior_errors, _ = validate_on(date(2026, 7, 12))
        later_errors, _ = validate_on(date(2026, 7, 14))

        self.assertEqual([], boundary_warnings)
        self.assertEqual([], boundary_errors)
        self.assertIn(
            "job weekly_report: source_policy.terms_reviewed_on must not be in the future",
            prior_errors,
        )
        self.assertNotIn(
            "job weekly_report: authority.validity.expires_on must not be in the past",
            prior_errors,
        )
        self.assertIn(
            "job weekly_report: authority.validity.expires_on must not be in the past",
            later_errors,
        )
        self.assertNotIn(
            "job weekly_report: source_policy.terms_reviewed_on must not be in the future",
            later_errors,
        )

    def test_automation_lint_requires_exact_calendar_date_spelling(self) -> None:
        invalid_dates = (
            "20260630",
            "2026-6-30",
            "２０２６-０６-３０",
            "2026-02-30",
        )
        for invalid_date in invalid_dates:
            with self.subTest(field="terms_reviewed_on", value=invalid_date):
                source_job = valid_automation_job()
                source_job["source_access_class"] = "account_visible"
                source_policy = valid_source_policy()
                source_policy["terms_reviewed_on"] = invalid_date
                source_job["source_policy"] = source_policy

                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [source_job],
                    }
                )

                self.assertEqual([], warnings)
                self.assertEqual(
                    [
                        "job weekly_report: source_policy.terms_reviewed_on must be "
                        "an exact YYYY-MM-DD date"
                    ],
                    errors,
                )

            with self.subTest(field="expires_on", value=invalid_date):
                authority_job = valid_automation_job()
                authority = cast(dict[str, object], authority_job["authority"])
                validity = cast(dict[str, object], authority["validity"])
                validity.update(
                    {
                        "expires_on": invalid_date,
                        "mode": "time_window",
                        "revocation_events": ["date_reached", "user_revocation"],
                    }
                )

                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [authority_job],
                    }
                )

                self.assertEqual([], warnings)
                self.assertEqual(
                    [
                        "job weekly_report: authority.validity.expires_on must be an "
                        "exact YYYY-MM-DD date when mode is time_window"
                    ],
                    errors,
                )

    def test_automation_lint_captures_current_utc_date_once_for_multiple_jobs(self) -> None:
        jobs: list[dict[str, object]] = []
        for index in range(2):
            job = deepcopy(valid_automation_job())
            job_id = f"dated_job_{index + 1}"
            job["id"] = job_id
            job["source_access_class"] = "account_visible"
            source_policy = valid_source_policy()
            source_policy["terms_reviewed_on"] = "2026-07-14"
            job["source_policy"] = source_policy
            authority = cast(dict[str, object], job["authority"])
            validity = cast(dict[str, object], authority["validity"])
            validity.update(
                {
                    "expires_on": "2026-07-12",
                    "mode": "time_window",
                    "revocation_events": ["date_reached", "user_revocation"],
                }
            )
            jobs.append(job)
        manifest = {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "preferred_backend": "cron",
            "jobs": jobs,
        }

        with mock.patch.object(
            automation_orders_lint,
            "current_utc_date",
            return_value=date(2026, 7, 13),
        ) as capture_date:
            errors, warnings = automation_orders_lint.validate_manifest(manifest)

        capture_date.assert_called_once_with()
        self.assertEqual([], warnings)
        for index in range(2):
            prefix = f"job dated_job_{index + 1}"
            self.assertIn(
                f"{prefix}: source_policy.terms_reviewed_on must not be in the future",
                errors,
            )
            self.assertIn(
                f"{prefix}: authority.validity.expires_on must not be in the past",
                errors,
            )

    def test_minimum_disabled_automation_example_matches_schema_v7(self) -> None:
        example_path = REPO_ROOT / "examples" / "automation_orders.example.json"
        example = automation_orders_lint.load_manifest(example_path)

        errors, warnings = automation_orders_lint.validate_manifest(
            example,
            target="cron",
            project_root=REPO_ROOT,
            manifest_path=example_path,
        )

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_minimum_disabled_automation_example_cannot_render(self) -> None:
        example_path = REPO_ROOT / "examples" / "automation_orders.example.json"
        with mock.patch.object(
            sys,
            "argv",
            [
                "render_cron.py",
                str(example_path),
                "--project-root",
                str(REPO_ROOT),
            ],
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                result = render_cron.main()

        self.assertEqual(1, result)
        self.assertIn("no enabled cron jobs to render", stdout.getvalue())

    def test_automation_authority_inputs_reject_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                '{"schema_version":6,"schema_version":1,"jobs":[]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate JSON key: schema_version"):
                automation_orders_lint.load_manifest(manifest)

            state_report = project_state_lint.lint_state_files(
                root,
                ["AUTOMATION_ORDERS.json"],
                require_core=False,
            )
            with mock.patch.object(
                sys,
                "argv",
                [
                    "render_cron.py",
                    str(manifest),
                    "--project-root",
                    str(root),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    render_result = render_cron.main()

        self.assertTrue(
            any("duplicate JSON key: schema_version" in error for error in state_report["errors"]),
            state_report,
        )
        self.assertEqual(1, render_result)
        self.assertIn("duplicate JSON key: schema_version", stdout.getvalue())

    def test_automation_lint_bounds_outputs_to_write_scope(self) -> None:
        absolute = valid_automation_job()
        absolute["outputs"] = ["/tmp/out.md"]
        traversal = valid_automation_job()
        traversal["outputs"] = ["review_" + "artifacts/../out.md"]
        artifact_scope = valid_automation_job()
        artifact_scope["outputs"] = ["report.md"]
        none_scope = valid_automation_job()
        none_scope["write_scope"] = "none"
        none_scope["outputs"] = ["review_" + "artifacts/report.md"]

        absolute_errors, _absolute_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [absolute]}
        )
        traversal_errors, _traversal_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [traversal]}
        )
        artifact_errors, _artifact_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [artifact_scope]}
        )
        none_errors, _none_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [none_scope]}
        )

        self.assertIn("job weekly_report: output path must be repo-relative: /tmp/out.md", absolute_errors)
        self.assertIn(
            "job weekly_report: output path must not contain empty, current-directory, or traversal segments: review_" + "artifacts/../out.md",
            traversal_errors,
        )
        self.assertIn(
            "job weekly_report: write_scope artifacts outputs must stay under artifacts/, review_" + "artifacts/: report.md",
            artifact_errors,
        )
        self.assertIn("job weekly_report: write_scope none must not declare outputs", none_errors)

    def test_automation_lint_rejects_windows_and_lexically_ambiguous_state_paths(self) -> None:
        windows_output = valid_automation_job()
        windows_output["outputs"] = ["artifacts\\report.md"]
        traversal_lock = valid_automation_job()
        traversal_artifacts = dict(cast(dict[str, object], traversal_lock["scheduler_artifacts"]))
        traversal_artifacts["lock_file"] = "../weekly.lock"
        traversal_lock["scheduler_artifacts"] = traversal_artifacts

        output_errors, _ = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [windows_output]}
        )
        lock_errors, _ = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [traversal_lock]}
        )

        self.assertTrue(any("output path must use POSIX separators" in error for error in output_errors), output_errors)
        self.assertTrue(any("scheduler_artifacts.lock_file must be a safe repo-relative path" in error for error in lock_errors), lock_errors)

    def test_automation_lint_confines_scheduler_artifacts_to_declared_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            traversal_project = Path(temp_dir) / "traversal-project"
            symlink_project = Path(temp_dir) / "symlink-project"
            outside = Path(temp_dir) / "outside"
            project.mkdir()
            traversal_project.mkdir()
            symlink_project.mkdir()
            outside.mkdir()
            cases: list[tuple[str, Path, dict[str, object], str]] = []

            absolute_lock = valid_automation_job()
            absolute_lock["cwd"] = "."
            absolute_artifacts = dict(cast(dict[str, object], absolute_lock["scheduler_artifacts"]))
            absolute_artifacts["lock_file"] = "/etc/cron.d/framework.lock"
            absolute_lock["scheduler_artifacts"] = absolute_artifacts
            cases.append(("absolute-lock", project, absolute_lock, "must be a safe repo-relative path"))

            traversing_root = valid_automation_job()
            traversing_root["cwd"] = "."
            traversal_artifacts = dict(cast(dict[str, object], traversing_root["scheduler_artifacts"]))
            traversal_artifacts["root"] = "../outside"
            traversing_root["scheduler_artifacts"] = traversal_artifacts
            cases.append(("traversing-root", traversal_project, traversing_root, "must be a safe repo-relative path"))

            symlinked_root = valid_automation_job()
            symlinked_root["cwd"] = "."
            (symlink_project / ".automation").symlink_to(outside, target_is_directory=True)
            cases.append(("symlinked-root", symlink_project, symlinked_root, "must not include symlink components"))

            for case_id, selected_root, job, expected in cases:
                with self.subTest(case_id=case_id):
                    errors, warnings = automation_orders_lint.validate_manifest(
                        {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        },
                        project_root=selected_root,
                    )
                    self.assertEqual([], warnings)
                    self.assertTrue(any(expected in error for error in errors), errors)

    def test_automation_lint_requires_a_bounded_scheduler_log(self) -> None:
        missing = valid_automation_job()
        missing_artifacts = dict(cast(dict[str, object], missing["scheduler_artifacts"]))
        del missing_artifacts["max_log_bytes"]
        missing["scheduler_artifacts"] = missing_artifacts

        too_small = valid_automation_job()
        small_artifacts = dict(cast(dict[str, object], too_small["scheduler_artifacts"]))
        small_artifacts["max_log_bytes"] = automation_orders_lint.MIN_SCHEDULER_LOG_BYTES - 1
        too_small["scheduler_artifacts"] = small_artifacts

        too_large = valid_automation_job()
        large_artifacts = dict(cast(dict[str, object], too_large["scheduler_artifacts"]))
        large_artifacts["max_log_bytes"] = automation_orders_lint.MAX_SCHEDULER_LOG_BYTES + 1
        too_large["scheduler_artifacts"] = large_artifacts

        boolean = valid_automation_job()
        boolean_artifacts = dict(cast(dict[str, object], boolean["scheduler_artifacts"]))
        boolean_artifacts["max_log_bytes"] = True
        boolean["scheduler_artifacts"] = boolean_artifacts

        reports = [
            automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                }
            )[0]
            for job in (missing, too_small, too_large, boolean)
        ]

        self.assertTrue(any("missing keys ['max_log_bytes']" in error for error in reports[0]))
        for errors in reports[1:]:
            self.assertTrue(
                any("scheduler_artifacts.max_log_bytes must be an integer" in error for error in errors),
                errors,
            )

    def test_automation_lint_requires_explicit_log_retention_and_redaction(self) -> None:
        missing_retention = valid_automation_job()
        retention_artifacts = dict(
            cast(dict[str, object], missing_retention["scheduler_artifacts"])
        )
        del retention_artifacts["retention"]
        missing_retention["scheduler_artifacts"] = retention_artifacts

        missing_redaction = valid_automation_job()
        redaction_artifacts = dict(
            cast(dict[str, object], missing_redaction["scheduler_artifacts"])
        )
        del redaction_artifacts["redaction"]
        missing_redaction["scheduler_artifacts"] = redaction_artifacts

        explicit_none = valid_automation_job()
        none_artifacts = cast(
            dict[str, object], explicit_none["scheduler_artifacts"]
        )
        none_artifacts["retention"] = {
            "days": None,
            "manual_owner": None,
            "manual_trigger": None,
            "mode": "indefinite",
        }
        none_artifacts["redaction"] = {"mode": "retain_verbatim"}

        bare_none = valid_automation_job()
        bare_none_artifacts = cast(
            dict[str, object], bare_none["scheduler_artifacts"]
        )
        bare_none_artifacts["redaction"] = {"mode": "none"}

        placeholder = valid_automation_job()
        placeholder_artifacts = cast(
            dict[str, object], placeholder["scheduler_artifacts"]
        )
        placeholder_artifacts["retention"] = {
            "days": None,
            "manual_owner": None,
            "manual_trigger": None,
            "mode": "bounded_days",
        }

        retention_errors, _ = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [missing_retention],
            }
        )
        redaction_errors, _ = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [missing_redaction],
            }
        )
        none_errors, none_warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [explicit_none],
            }
        )
        bare_none_errors, _ = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [bare_none],
            }
        )
        placeholder_errors, _ = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [placeholder],
            }
        )

        self.assertTrue(any("missing keys ['retention']" in error for error in retention_errors))
        self.assertTrue(any("missing keys ['redaction']" in error for error in redaction_errors))
        self.assertEqual([], none_errors)
        self.assertEqual([], none_warnings)
        self.assertTrue(
            any("redaction.mode must be one of" in error for error in bare_none_errors),
            bare_none_errors,
        )
        self.assertTrue(
            any("retention.days must be an integer" in error for error in placeholder_errors),
            placeholder_errors,
        )

    def test_manual_log_retention_requires_owner_and_trigger_without_stale_metadata(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "missing owner",
                {
                    "days": None,
                    "manual_owner": None,
                    "manual_trigger": "when the scheduler log lacks capacity",
                    "mode": "manual_archive_or_truncate",
                },
                "retention.manual_owner must be a string",
            ),
            (
                "control-bearing trigger",
                {
                    "days": None,
                    "manual_owner": "project_operator",
                    "manual_trigger": "daily\u2028surprise",
                    "mode": "manual_archive_or_truncate",
                },
                "retention.manual_trigger must not contain control characters",
            ),
            (
                "stale manual owner",
                {
                    "days": None,
                    "manual_owner": "project_operator",
                    "manual_trigger": None,
                    "mode": "indefinite",
                },
                "retention.manual_owner must be null unless mode is manual_archive_or_truncate",
            ),
            (
                "stale manual trigger",
                {
                    "days": 30,
                    "manual_owner": None,
                    "manual_trigger": "monthly",
                    "mode": "bounded_days",
                },
                "retention.manual_trigger must be null unless mode is manual_archive_or_truncate",
            ),
        )
        for label, retention, expected in cases:
            with self.subTest(retention=label):
                job = valid_automation_job()
                artifacts = cast(dict[str, object], job["scheduler_artifacts"])
                artifacts["retention"] = retention
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )
                self.assertEqual([], warnings)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_cron_target_rejects_retention_modes_its_runner_does_not_execute(self) -> None:
        unsupported_modes = (
            ("bounded_days", 30),
            ("delete_after_run", None),
        )
        for mode, days in unsupported_modes:
            with self.subTest(mode=mode):
                job = valid_automation_job()
                artifacts = cast(dict[str, object], job["scheduler_artifacts"])
                artifacts["retention"] = {
                    "days": days,
                    "manual_owner": None,
                    "manual_trigger": None,
                    "mode": mode,
                }
                manifest = {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                }

                generic_errors, generic_warnings = (
                    automation_orders_lint.validate_manifest(manifest)
                )
                cron_errors, cron_warnings = automation_orders_lint.validate_manifest(
                    manifest,
                    target="cron",
                    project_root=REPO_ROOT,
                    manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
                    require_existing_project_root=False,
                )

                self.assertEqual([], generic_warnings)
                self.assertEqual([], generic_errors)
                self.assertEqual([], cron_warnings)
                self.assertEqual(
                    [
                        "job weekly_report: target cron does not execute "
                        f"scheduler_artifacts.retention.mode {mode!r}; use one of "
                        f"{sorted(automation_orders_lint.CRON_SUPPORTED_RETENTION_MODES)}"
                    ],
                    cron_errors,
                )

        for mode in automation_orders_lint.CRON_SUPPORTED_RETENTION_MODES:
            with self.subTest(supported_mode=mode):
                job = valid_automation_job()
                artifacts = cast(dict[str, object], job["scheduler_artifacts"])
                artifacts["retention"] = {
                    "days": None,
                    "manual_owner": (
                        "project_operator"
                        if mode == "manual_archive_or_truncate"
                        else None
                    ),
                    "manual_trigger": (
                        "when the scheduler log lacks capacity"
                        if mode == "manual_archive_or_truncate"
                        else None
                    ),
                    "mode": mode,
                }
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    },
                    target="cron",
                    project_root=REPO_ROOT,
                    manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
                    require_existing_project_root=False,
                )

                self.assertEqual([], warnings)
                self.assertEqual([], errors)

    def test_scheduler_paths_reject_the_full_single_line_control_grammar(self) -> None:
        path_mutations = (
            ("cwd", lambda job, value: job.__setitem__("cwd", value)),
            (
                "scheduler_artifacts.root",
                lambda job, value: cast(
                    dict[str, object], job["scheduler_artifacts"]
                ).__setitem__("root", value),
            ),
            (
                "scheduler_artifacts.log_file",
                lambda job, value: cast(
                    dict[str, object], job["scheduler_artifacts"]
                ).__setitem__("log_file", value),
            ),
            (
                "scheduler_artifacts.lock_file",
                lambda job, value: cast(
                    dict[str, object], job["scheduler_artifacts"]
                ).__setitem__("lock_file", value),
            ),
        )
        rejected_characters = ("\x85", "\u2028", "\u2029", "\ud800", "\udfff")

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            manifest_path.write_text("{}\n", encoding="utf-8")

            for field, mutate in path_mutations:
                for character in rejected_characters:
                    with self.subTest(field=field, character=ascii(character)):
                        job = valid_automation_job()
                        mutate(job, f"path{character}injected")
                        manifest = {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        }

                        generic_errors, generic_warnings = (
                            automation_orders_lint.validate_manifest(manifest)
                        )
                        cron_errors, cron_warnings = (
                            automation_orders_lint.validate_manifest(
                                manifest,
                                target="cron",
                                project_root=project,
                                manifest_path=manifest_path,
                            )
                        )

                        expected_fragment = (
                            f"{field} must not contain control characters"
                        )
                        self.assertEqual([], generic_warnings)
                        self.assertEqual([], cron_warnings)
                        self.assertTrue(
                            any(expected_fragment in error for error in generic_errors),
                            generic_errors,
                        )
                        self.assertTrue(
                            any(expected_fragment in error for error in cron_errors),
                            cron_errors,
                        )
                        with self.assertRaisesRegex(
                            ValueError,
                            "must not contain control characters",
                        ):
                            render_cron.render_job(job, project, manifest_path)
                        self.assertFalse((project / ".automation").exists())

    def test_scheduler_artifact_topology_rejects_portable_file_directory_collisions(self) -> None:
        same_job_cases = (
            ("same", "same"),
            ("shared", "shared/lock"),
            ("shared/log", "shared"),
            ("Out", "out"),
            ("caf\u00e9", "cafe\u0301"),
        )
        for log_file, lock_file in same_job_cases:
            with self.subTest(log_file=log_file, lock_file=lock_file):
                job = valid_automation_job()
                artifacts = cast(dict[str, object], job["scheduler_artifacts"])
                artifacts["log_file"] = log_file
                artifacts["lock_file"] = lock_file
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )
                self.assertEqual([], warnings)
                self.assertTrue(
                    any("scheduler artifact topology collision" in error for error in errors),
                    errors,
                )

        first = valid_automation_job()
        first["id"] = "first"
        first_artifacts = cast(dict[str, object], first["scheduler_artifacts"])
        first_artifacts["log_file"] = "shared"
        first_artifacts["lock_file"] = "locks/first.lock"
        second = valid_automation_job()
        second["id"] = "second"
        second_artifacts = cast(dict[str, object], second["scheduler_artifacts"])
        second_artifacts["log_file"] = "shared/log"
        second_artifacts["lock_file"] = "locks/second.lock"
        collision_errors, collision_warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [first, second],
            }
        )
        self.assertEqual([], collision_warnings)
        self.assertTrue(
            any("scheduler artifact topology collision" in error for error in collision_errors),
            collision_errors,
        )

        first_artifacts["log_file"] = "logs/first.log"
        second_artifacts["log_file"] = "logs/second.log"
        clean_errors, clean_warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [first, second],
            }
        )
        self.assertEqual([], clean_warnings)
        self.assertEqual([], clean_errors)

    def test_cron_project_root_and_relative_cwd_are_independent_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            contract_root = project / "contracts" / "mpa"
            nested_cwd = project / "work"
            sibling = root / "sibling"
            percent_project = root / "project%cron"
            contract_root.mkdir(parents=True)
            nested_cwd.mkdir()
            sibling.mkdir()
            percent_project.mkdir()
            manifest_path = contract_root / "AUTOMATION_ORDERS.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            linked_project = root / "linked-project"
            linked_project.symlink_to(project, target_is_directory=True)
            linked_cwd = project / "linked-work"
            linked_cwd.symlink_to(sibling, target_is_directory=True)
            linked_manifest = project / "linked-orders.json"
            linked_manifest.symlink_to(manifest_path)

            root_job = valid_automation_job()
            root_job["cwd"] = "."
            nested_job = valid_automation_job()
            nested_job["cwd"] = "work"
            manifest = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [root_job],
            }

            root_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )
            manifest["jobs"] = [nested_job]
            nested_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )
            missing_cwd_job = valid_automation_job()
            missing_cwd_job["cwd"] = "missing-work"
            missing_cwd_manifest = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [missing_cwd_job],
            }
            missing_cwd_errors, _ = automation_orders_lint.validate_manifest(
                missing_cwd_manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )
            prospective_errors, _ = automation_orders_lint.validate_manifest(
                missing_cwd_manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
                require_existing_project_root=False,
            )

            rejected_cwds: list[list[str]] = []
            for cwd in ("/", str(Path.home()), "../sibling"):
                invalid = valid_automation_job()
                invalid["cwd"] = cwd
                errors, _ = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [invalid],
                    },
                    target="cron",
                    project_root=project,
                    manifest_path=manifest_path,
                )
                rejected_cwds.append(errors)

            filesystem_root_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=Path("/"),
                manifest_path=manifest_path,
            )
            home_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=Path.home(),
                manifest_path=manifest_path,
            )
            sibling_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=sibling,
                manifest_path=manifest_path,
            )
            percent_manifest = percent_project / "AUTOMATION_ORDERS.json"
            percent_manifest.write_text("{}\n", encoding="utf-8")
            percent_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=percent_project,
                manifest_path=percent_manifest,
            )
            linked_project_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=linked_project,
                manifest_path=manifest_path,
            )
            linked_cwd_job = valid_automation_job()
            linked_cwd_job["cwd"] = "linked-work"
            linked_cwd_errors, _ = automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [linked_cwd_job],
                },
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )
            linked_manifest_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=linked_manifest,
            )
            missing_root_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
            )

        self.assertEqual([], root_errors)
        self.assertEqual([], nested_errors)
        self.assertTrue(
            any("cwd must name an existing directory" in error for error in missing_cwd_errors),
            missing_cwd_errors,
        )
        self.assertFalse(
            any("cwd must name an existing directory" in error for error in prospective_errors),
            prospective_errors,
        )
        for errors in rejected_cwds:
            self.assertTrue(any("cwd must be a safe repo-relative path" in error for error in errors), errors)
        self.assertIn("selected project root must not be the filesystem root", filesystem_root_errors)
        self.assertIn("selected project root must not be the scheduler user's home directory", home_errors)
        self.assertIn("automation manifest must be inside the selected project root", sibling_errors)
        self.assertIn("target cron requires a selected project root without '%'", percent_errors)
        self.assertIn("target cron requires an automation manifest path without '%'", percent_errors)
        self.assertTrue(
            any("selected project root must not contain symlink components" in error for error in linked_project_errors),
            linked_project_errors,
        )
        self.assertTrue(
            any("cwd must not include symlink components" in error for error in linked_cwd_errors),
            linked_cwd_errors,
        )
        self.assertTrue(
            any("automation manifest must not include symlink components" in error for error in linked_manifest_errors),
            linked_manifest_errors,
        )
        self.assertIn("target cron requires an explicit selected project root", missing_root_errors)
        self.assertIn("target cron requires an explicit automation manifest path", missing_root_errors)

    def test_cron_preflight_rejects_ambiguous_manifest_and_cwd_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest_alias = project / "automation_orders.json"
            manifest.write_text("{}\n", encoding="utf-8")
            manifest_alias.write_text("{}\n", encoding="utf-8")
            manifest_target = (
                manifest_alias if os.path.samefile(manifest, manifest_alias) else manifest
            )

            upper_cwd = project / "Work"
            lower_cwd = project / "work"
            upper_cwd.mkdir()
            try:
                lower_cwd.mkdir()
            except FileExistsError:
                pass
            cwd_value = "work" if os.path.samefile(upper_cwd, lower_cwd) else "Work"

            job = valid_automation_job()
            manifest_errors, _ = automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                },
                target="cron",
                project_root=project,
                manifest_path=manifest_target,
            )
            job["cwd"] = cwd_value
            cwd_errors, _ = automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                },
                target="cron",
                project_root=project,
                manifest_path=manifest_target,
            )

            self.assertTrue(
                any(
                    "exact path spelling" in error or "ambiguous path spellings" in error
                    for error in manifest_errors
                ),
                manifest_errors,
            )
            self.assertTrue(
                any(
                    "exact path spelling" in error or "ambiguous path spellings" in error
                    for error in cwd_errors
                ),
                cwd_errors,
            )
            with self.assertRaisesRegex(
                ValueError,
                "exact path spelling|ambiguous path spellings",
            ):
                render_cron.render_job(valid_automation_job(), project, manifest_target)

    def test_project_rooted_instruction_source_rejects_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            outside = Path(temp_dir) / "outside"
            project.mkdir()
            outside.mkdir()
            (outside / "automation.md").write_text("outside instruction\n", encoding="utf-8")
            (project / "task_orders").symlink_to(outside, target_is_directory=True)

            error = automation_orders_lint.source_reference_path_error(
                "instruction_sources",
                "project",
                "task_orders/automation.md",
                project,
                instruction_source=True,
                filesystem_checks=True,
            )

        self.assertIsNotNone(error)
        self.assertIn("must not include symlink components", error or "")

    def test_automation_instruction_source_rejects_symlinked_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            outside = base / "outside"
            project = base / "project"
            (outside / "task_orders").mkdir(parents=True)
            (outside / "task_orders" / "automation.md").write_text(
                "outside instruction\n",
                encoding="utf-8",
            )
            project.symlink_to(outside, target_is_directory=True)

            error = automation_orders_lint.source_reference_path_error(
                "instruction_sources",
                "project",
                "task_orders/automation.md",
                project,
                instruction_source=True,
                filesystem_checks=True,
            )

        self.assertIsNotNone(error)
        self.assertIn("root must not use symlink path components", error or "")

    def test_automation_lint_rejects_noncurrent_schema_without_legacy_guidance(self) -> None:
        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": 1, "jobs": []})

        self.assertEqual([], warnings)
        self.assertIn(f"schema_version must be {automation_orders_lint.SCHEMA_VERSION}", errors)
        self.assertFalse(any("migrate" in error.casefold() for error in errors), errors)

    def test_automation_lint_accepts_typed_boundaries_and_stored_command_percent(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "command": "uv run python report.py % truncated",
                "external_review": {
                    "allowed_data_classes": ["public_source_urls"],
                    "authentication": "none",
                    "egress": "approved_endpoints_only",
                    "max_requests": 1,
                    "redaction": "before_egress",
                    "retained_artifacts": "sanitized_result_only",
                    "retention_days": 30,
                    "sensitive_data": "deny",
                    "unlisted_data": "deny",
                },
                "id": "weekly",
                "reviewer_boundary_mode": "external",
                "reviewer_runtime_class": "model",
            }
        )
        scheduler_artifacts = cast(dict[str, object], job["scheduler_artifacts"])
        scheduler_artifacts["redaction"] = {
            "mode": "command_redacts_before_capture"
        }
        manifest = {
            "schema_version": automation_orders_lint.SCHEMA_VERSION,
            "preferred_backend": "cron",
            "jobs": [job],
        }

        errors, warnings = automation_orders_lint.validate_manifest(manifest)

        self.assertEqual([], warnings)
        self.assertEqual([], errors)

        job["command"] = "uv run python report.py"
        job["state_policy"] = ["not an object"]
        type_errors, type_warnings = automation_orders_lint.validate_manifest(manifest)

        self.assertEqual([], type_warnings)
        self.assertIn("job weekly: state_policy must be an object", type_errors)

    def test_automation_lint_requires_external_reviewer_boundary_fields(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "reviewer_runtime_class": "model",
                "reviewer_boundary_mode": "external",
            }
        )
        manifest = {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}

        errors, warnings = automation_orders_lint.validate_manifest(manifest)

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: external reviewer jobs must define external_review",
            errors,
        )

    def test_automation_lint_accepts_instruction_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            overlay = root / "local_overlays" / "source_monitor_policy.md"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("# Local Overlay\n", encoding="utf-8")
            job = valid_automation_job()
            job["cwd"] = "."
            job["instruction_sources"] = [
                {"path": "task_orders/automation.md", "root": "framework"},
                {
                    "path": "project_state_templates/SOURCE_MONITOR_RESEARCHER.md",
                    "root": "framework",
                },
                {
                    "path": "practice_guides/source_freshness_review.md",
                    "root": "framework",
                },
                {
                    "path": "practice_guides/scheduled_automation.md",
                    "root": "framework",
                },
                {
                    "path": "local_overlays/source_monitor_policy.md",
                    "root": "project",
                },
            ]

            errors, warnings = automation_orders_lint.validate_manifest(
                {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]},
                project_root=root,
            )

        self.assertEqual([], warnings)
        self.assertEqual([], errors)

    def test_automation_instruction_sources_bind_the_required_transitive_closure(self) -> None:
        for missing_path in sorted(
            automation_orders_lint.AUTOMATION_REQUIRED_INSTRUCTION_SOURCES
        ):
            with self.subTest(missing=missing_path):
                job = valid_automation_job()
                job["instruction_sources"] = [
                    reference
                    for reference in cast(list[dict[str, str]], job["instruction_sources"])
                    if reference["path"] != missing_path
                ]
                if missing_path == "task_orders/automation.md":
                    cast(list[object], job["instruction_sources"]).append(
                        {
                            "path": "runtime/task_modules/automation.md",
                            "root": "framework",
                        }
                    )
                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )
                self.assertEqual([], warnings)
                self.assertTrue(
                    any(
                        "complete framework-rooted automation instruction closure"
                        in error
                        and missing_path in error
                        for error in errors
                    ),
                    errors,
                )

    def test_instruction_source_roots_are_explicit_and_never_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            framework = root / "framework"
            project.mkdir()
            (project / "task_orders").mkdir()
            (project / "task_orders" / "automation.md").write_text(
                "# Project shadow\n",
                encoding="utf-8",
            )
            (framework / "local_overlays").mkdir(parents=True)
            (framework / "task_orders").mkdir()
            (framework / "local_overlays" / "policy.md").write_text(
                "# Wrong-project overlay\n",
                encoding="utf-8",
            )
            (framework / "task_orders" / "automation.md").write_text(
                "# Framework task order\n",
                encoding="utf-8",
            )

            with mock.patch.object(automation_orders_lint, "REPO_ROOT", framework):
                overlay_error = automation_orders_lint.source_reference_path_error(
                    "instruction_sources",
                    "project",
                    "local_overlays/policy.md",
                    project,
                    instruction_source=True,
                    filesystem_checks=True,
                )
                framework_error = automation_orders_lint.source_reference_path_error(
                    "instruction_sources",
                    "framework",
                    "task_orders/automation.md",
                    project,
                    instruction_source=True,
                    filesystem_checks=True,
                )
                project_shadow_error = automation_orders_lint.source_reference_path_error(
                    "instruction_sources",
                    "project",
                    "task_orders/automation.md",
                    project,
                    instruction_source=True,
                    filesystem_checks=True,
                )
                (framework / "task_orders" / "automation.md").unlink()
                missing_framework_error = automation_orders_lint.source_reference_path_error(
                    "instruction_sources",
                    "framework",
                    "task_orders/automation.md",
                    project,
                    instruction_source=True,
                    filesystem_checks=True,
                )

        self.assertIn("project-rooted source does not exist", overlay_error or "")
        self.assertIsNone(framework_error)
        self.assertIsNone(project_shadow_error)
        self.assertIn(
            "framework-rooted source does not exist",
            missing_framework_error or "",
        )

    def test_bound_source_resource_limits_have_objective_boundaries(self) -> None:
        second_framework_source = {
            "path": "practice_guides/scheduled_automation.md",
            "root": "framework",
        }
        per_list_job = valid_automation_job()
        per_list_job["instruction_sources"] = [
            *cast(list[object], per_list_job["instruction_sources"]),
            second_framework_source,
        ]
        with mock.patch.object(
            automation_orders_lint,
            "MAX_BOUND_SOURCE_REFERENCES",
            1,
        ):
            per_list_errors, _ = automation_orders_lint.validate_manifest(
                {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [per_list_job],
                }
            )
        self.assertTrue(
            any("instruction_sources must contain at most 1 references" in error for error in per_list_errors),
            per_list_errors,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            execution_source = project / "scripts" / "report.py"
            execution_source.parent.mkdir()
            execution_source.write_text("print('report')\n", encoding="utf-8")
            combined_job = valid_automation_job()
            combined_job["execution_sources"] = [
                {"path": "scripts/report.py", "root": "project"}
            ]
            with mock.patch.object(
                automation_orders_lint,
                "MAX_BOUND_SOURCE_REFERENCES",
                2,
            ):
                combined_errors, _ = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [combined_job],
                    },
                    project_root=project,
                )
        self.assertTrue(
            any("instruction_sources and execution_sources together must contain at most 2 references" in error for error in combined_errors),
            combined_errors,
        )

        for limit_name, expected in (
            ("MAX_BOUND_SOURCE_FILE_BYTES", "1-byte limit"),
            ("MAX_BOUND_SOURCE_TOTAL_BYTES", "1-byte aggregate limit"),
        ):
            with self.subTest(limit=limit_name), mock.patch.object(
                automation_orders_lint,
                limit_name,
                1,
            ):
                errors, _ = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [valid_automation_job()],
                    }
                )
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_automation_lint_requires_sensitive_source_boundaries(self) -> None:
        job = valid_automation_job()
        job["objective"] = "Inspect approved account-visible records for source discovery"
        job["source_access_class"] = "account_visible"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: non-public source access must define source_policy",
            errors,
        )

        job["source_policy"] = valid_source_policy()

        fixed_errors, fixed_warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], fixed_warnings)
        self.assertEqual([], fixed_errors)

        policy = cast(dict[str, object], job["source_policy"])
        policy["max_requests_per_run"] = "reasonable"
        vague_errors, vague_warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], vague_warnings)
        self.assertTrue(
            any("source_policy.max_requests_per_run must be an integer" in error for error in vague_errors),
            vague_errors,
        )

        policy["max_requests_per_run"] = 25
        policy["source_aliases"] = ["@real_vendor_handle"]
        concrete_errors, concrete_warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], concrete_warnings)
        self.assertTrue(
            any("source_policy.source_aliases[1] must match" in error for error in concrete_errors),
            concrete_errors,
        )

    def test_automation_lint_validates_source_access_classification(self) -> None:
        public_job = valid_automation_job()
        public_job["source_access_class"] = "public_unauthenticated"
        public_errors, public_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [public_job]}
        )

        unknown_job = valid_automation_job()
        unknown_job["source_access_class"] = "synthetic_unknown"
        unknown_errors, unknown_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [unknown_job]}
        )

        unclassified_job = valid_automation_job()
        unclassified_job["source_policy"] = valid_source_policy()
        unclassified_errors, unclassified_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [unclassified_job]}
        )

        public_with_boundary_job = valid_automation_job()
        public_with_boundary_job.update(
            {
                "source_access_class": "public_unauthenticated",
                "source_policy": valid_source_policy(),
            }
        )
        public_with_boundary_errors, public_with_boundary_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [public_with_boundary_job]}
        )

        self.assertEqual([], public_warnings)
        self.assertEqual([], public_errors)
        self.assertEqual([], unknown_warnings)
        self.assertTrue(
            any("source_access_class must be one of" in error for error in unknown_errors),
            unknown_errors,
        )
        self.assertEqual([], unclassified_warnings)
        self.assertIn(
            "job weekly_report: source_policy requires source_access_class",
            unclassified_errors,
        )
        self.assertEqual([], public_with_boundary_warnings)
        self.assertIn(
            "job weekly_report: public_unauthenticated source access must not declare source_policy",
            public_with_boundary_errors,
        )

    def test_automation_lint_requires_fixture_gate_for_parser_updates(self) -> None:
        job = valid_automation_job()
        job["objective"] = "Update deterministic parser when source shape changes"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertEqual([], errors)

        job["workload_class"] = "parser_or_extractor_change"
        missing_errors, missing_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )
        self.assertEqual([], missing_warnings)
        self.assertIn(
            "job weekly_report: parser_or_extractor_change workload must define parser_change",
            missing_errors,
        )

        job["parser_change"] = valid_parser_change()

        fixed_errors, fixed_warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], fixed_warnings)
        self.assertEqual([], fixed_errors)

        parser_change = cast(dict[str, object], job["parser_change"])
        parser_change["approved_output_digests"] = []
        approval_errors, approval_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )

        self.assertEqual([], approval_warnings)
        self.assertTrue(
            any("approved_output_digests must be a non-empty list" in error for error in approval_errors),
            approval_errors,
        )

        parser_change["approved_output_digests"] = ["sha256:" + "2" * 64]
        mismatch_errors, mismatch_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )

        self.assertEqual([], mismatch_warnings)
        self.assertTrue(
            any("approved_output_digests must cover expected_output_digests" in error for error in mismatch_errors),
            mismatch_errors,
        )

        first_digest = "sha256:" + "1" * 64
        second_digest = "sha256:" + "3" * 64
        parser_change["expected_output_digests"] = [first_digest, second_digest]
        parser_change["approved_output_digests"] = [first_digest]
        partial_approval_errors, partial_approval_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )

        self.assertEqual([], partial_approval_warnings)
        self.assertTrue(
            any("approved_output_digests must cover expected_output_digests" in error for error in partial_approval_errors),
            partial_approval_errors,
        )

        parser_change["expected_output_digests"] = [first_digest]
        parser_change["approved_output_digests"] = [first_digest]
        parser_change["input_fixture_digests"] = ["hashes_recorded"]
        hash_errors, hash_warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], hash_warnings)
        self.assertTrue(
            any("input_fixture_digests[1] must match" in error for error in hash_errors),
            hash_errors,
        )

    def test_automation_lint_requires_context_sources_for_fresh_runs(self) -> None:
        job = valid_automation_job()
        del job["instruction_sources"]

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn("job weekly_report: missing keys ['instruction_sources']", errors)

        job = valid_automation_job()
        del job["execution_sources"]
        execution_errors, execution_warnings = automation_orders_lint.validate_manifest(
            {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [job],
            }
        )
        self.assertEqual([], execution_warnings)
        self.assertIn(
            "job weekly_report: missing keys ['execution_sources']",
            execution_errors,
        )

    def test_automation_lint_requires_typed_state_for_thread_continuity(self) -> None:
        job = valid_automation_job()
        job["scheduler_context_mode"] = "thread_continuity"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: thread_continuity requires persistent state, a checkpoint, or cursor resume",
            errors,
        )

        job["state_policy"] = {
            "checkpoint": "per_run",
            "persistence": "none",
            "reference": None,
            "resume": "restart",
        }
        ephemeral_errors, _ = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )
        self.assertIn(
            "job weekly_report: state_policy.checkpoint per_run requires persistent state",
            ephemeral_errors,
        )

        job["state_policy"] = {
            "checkpoint": "per_run",
            "persistence": "project_file",
            "reference": "project_state/automation_cursor.json",
            "resume": "cursor",
        }
        scope_errors, _ = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )
        self.assertTrue(
            any("when write_scope is artifacts" in error for error in scope_errors),
            scope_errors,
        )

        job["state_policy"] = {
            "checkpoint": "per_run",
            "persistence": "project_file",
            "reference": "artifacts/automation_cursor.json",
            "resume": "cursor",
        }
        fixed_errors, fixed_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )
        self.assertEqual([], fixed_warnings)
        self.assertEqual([], fixed_errors)

    def test_automation_lint_rejects_bad_instruction_sources(self) -> None:
        cases: tuple[tuple[str, object, str], ...] = (
            (
                "non-object",
                ["task_orders/automation.md"],
                "instruction_sources[1] must be an object",
            ),
            (
                "missing path",
                [{"root": "framework"}],
                "instruction_sources[1] is missing keys ['path']",
            ),
            (
                "unknown key",
                [
                    {
                        "path": "task_orders/automation.md",
                        "root": "framework",
                        "type": "instruction",
                    }
                ],
                "instruction_sources[1] has unknown keys ['type']",
            ),
            (
                "invalid root",
                [{"path": "task_orders/automation.md", "root": "fallback"}],
                "instruction_sources[1].root must be one of",
            ),
            (
                "control path",
                [{"path": "task_orders/automation.md\x00", "root": "framework"}],
                "instruction_sources[1].path must not contain control characters",
            ),
            (
                "duplicate",
                [
                    {"path": "task_orders/automation.md", "root": "framework"},
                    {"path": "task_orders/automation.md", "root": "framework"},
                ],
                "case-colliding",
            ),
            (
                "project shadow cannot supply authority",
                [{"path": "task_orders/automation.md", "root": "project"}],
                "must include the complete framework-rooted automation instruction closure",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "task_orders").mkdir()
            (project / "task_orders" / "automation.md").write_text(
                "# Project-local instruction\n",
                encoding="utf-8",
            )
            for label, sources, expected in cases:
                with self.subTest(source_reference=label):
                    job = valid_automation_job()
                    job["instruction_sources"] = sources
                    errors, warnings = automation_orders_lint.validate_manifest(
                        {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        },
                        project_root=project,
                    )
                    self.assertEqual([], warnings)
                    self.assertTrue(
                        any(expected in error for error in errors),
                        errors,
                    )

    def test_execution_sources_reject_symlinks_hardlinks_and_inexact_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            scripts = project / "scripts"
            scripts.mkdir()
            source = scripts / "Script.sh"
            source.write_text("printf source\n", encoding="utf-8")
            symlink = scripts / "linked.sh"
            symlink.symlink_to(source)
            hardlink = scripts / "hardlinked.sh"
            os.link(source, hardlink)

            cases = (
                ("symlink", "scripts/linked.sh", "symlink components"),
                ("hardlink", "scripts/hardlinked.sh", "exactly one hard link"),
                ("inexact spelling", "scripts/script.sh", "exact path spelling"),
            )
            for label, path, expected in cases:
                with self.subTest(execution_source=label):
                    job = valid_automation_job()
                    job["execution_sources"] = [
                        {"path": path, "root": "project"}
                    ]
                    errors, warnings = automation_orders_lint.validate_manifest(
                        {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        },
                        project_root=project,
                    )
                    self.assertEqual([], warnings)
                    self.assertTrue(
                        any(expected in error for error in errors),
                        errors,
                    )

    def test_source_reference_pairs_reject_case_and_unicode_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            overlays = project / "local_overlays"
            overlays.mkdir()
            nfc = unicodedata.normalize("NFC", "cafe\u0301.md")
            nfd = unicodedata.normalize("NFD", "café.md")
            for name in ("Policy.md", "policy.md", nfc, nfd):
                (overlays / name).write_text(f"# {name}\n", encoding="utf-8")
            cases = (
                ("case", "local_overlays/Policy.md", "local_overlays/policy.md"),
                ("unicode", f"local_overlays/{nfc}", f"local_overlays/{nfd}"),
            )
            for label, first, second in cases:
                with self.subTest(collision=label):
                    job = valid_automation_job()
                    job["instruction_sources"] = [
                        {"path": "task_orders/automation.md", "root": "framework"},
                        {"path": first, "root": "project"},
                        {"path": second, "root": "project"},
                    ]
                    errors, warnings = automation_orders_lint.validate_manifest(
                        {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        },
                        project_root=project,
                    )
                    self.assertEqual([], warnings)
                    self.assertTrue(
                        any("case-colliding" in error for error in errors),
                        errors,
                    )

    def test_automation_lint_requires_paired_reviewer_classification(self) -> None:
        for field, value in (
            ("reviewer_runtime_class", "model"),
            ("reviewer_boundary_mode", "external"),
        ):
            with self.subTest(field=field):
                job = valid_automation_job()
                job[field] = value

                errors, warnings = automation_orders_lint.validate_manifest(
                    {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
                )

                self.assertEqual([], warnings)
                self.assertIn(
                    "job weekly_report: reviewer jobs must define reviewer_runtime_class and reviewer_boundary_mode together",
                    errors,
                )

    def test_automation_lint_rejects_unknown_reviewer_classification(self) -> None:
        for field, value, companion_field, companion_value in (
            ("reviewer_runtime_class", "synthetic_unknown", "reviewer_boundary_mode", "local"),
            ("reviewer_boundary_mode", "remote", "reviewer_runtime_class", "human"),
        ):
            with self.subTest(field=field):
                job = valid_automation_job()
                job.update({field: value, companion_field: companion_value})

                errors, warnings = automation_orders_lint.validate_manifest(
                    {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
                )

                self.assertEqual([], warnings)
                self.assertTrue(
                    any(f"{field} must be one of" in error for error in errors),
                    errors,
                )

    def test_automation_lint_accepts_local_reviewer_runtime_classes_without_external_packet(self) -> None:
        for runtime_class in sorted(automation_orders_lint.REVIEWER_RUNTIME_CLASSES):
            with self.subTest(runtime_class=runtime_class):
                job = valid_automation_job()
                job.update(
                    {
                        "reviewer_runtime_class": runtime_class,
                        "reviewer_boundary_mode": "local",
                    }
                )

                errors, warnings = automation_orders_lint.validate_manifest(
                    {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
                )

                self.assertEqual([], warnings)
                self.assertEqual([], errors)

    def test_automation_lint_requires_typed_default_deny_external_review(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "external_review": valid_external_review(),
                "reviewer_boundary_mode": "external",
                "reviewer_runtime_class": "model",
            }
        )
        external_review = cast(dict[str, object], job["external_review"])
        external_review["unlisted_data"] = "allow"
        manifest = {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}

        errors, warnings = automation_orders_lint.validate_manifest(manifest)

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: external_review.unlisted_data must be deny",
            errors,
        )

    def test_external_review_policy_never_depends_on_negated_descriptive_prose(self) -> None:
        for packet in (
            "public source URLs; do not deny unlisted data",
            "public source URLs only if available",
            "Public source URLs. Data not named in the packet is denied except private notes when useful.",
            "Public source URLs. Data not named in the packet is denied. Also include private notes when useful.",
            "Public source URLs. Data not named in the packet is denied. Send secrets too.",
            "Public source URLs. Data not named in the packet is denied. Include API keys when needed.",
            "Public source URLs. Data not named in the packet is denied. Confidential attachments are allowed.",
            "Public source URLs. No restrictions on secrets. Data not named in the packet is denied.",
            "Public source URLs. Data not named in the packet is denied. Secrets are not included, tokens allowed.",
        ):
            with self.subTest(packet=packet):
                job = valid_automation_job()
                job.update(
                    {
                        "description": packet,
                        "external_review": valid_external_review(),
                        "reviewer_boundary_mode": "external",
                        "reviewer_runtime_class": "model",
                    }
                )

                errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

                self.assertEqual([], warnings)
                self.assertEqual([], errors)

    def test_automation_lint_accepts_typed_external_review_policy(self) -> None:
        job = valid_automation_job()
        job.update(
            {
                "external_review": valid_external_review(),
                "reviewer_boundary_mode": "external",
                "reviewer_runtime_class": "hybrid",
            }
        )

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertEqual([], errors)

        external_review = cast(dict[str, object], job["external_review"])
        external_review["retained_artifacts"] = "none"
        retention_errors, retention_warnings = automation_orders_lint.validate_manifest(
            {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
        )
        self.assertEqual([], retention_warnings)
        self.assertIn(
            "job weekly_report: external_review.retention_days must be 0 when retained_artifacts is none",
            retention_errors,
        )

    def test_automation_lint_requires_non_overlap_for_state_changing_propose_jobs(self) -> None:
        job = valid_automation_job()
        job["autonomy_level"] = "propose"
        job["write_scope"] = "repo"
        job["concurrency"] = "allow"
        cast(dict[str, object], job["authority"])["effect_class"] = "propose"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: enabled state-changing propose jobs must use concurrency forbid",
            errors,
        )

    def test_automation_lint_cron_target_rejects_non_cron_failure_policy(self) -> None:
        job = valid_automation_job()
        job["cwd"] = "."
        job["failure_policy"] = "log-and-notify"
        authority = cast(dict[str, object], job["authority"])
        authority["failure_action"] = "record_and_notify"
        manifest = {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}

        errors, warnings = automation_orders_lint.validate_manifest(manifest)
        cron_errors, cron_warnings = automation_orders_lint.validate_manifest(
            manifest,
            target="cron",
            project_root=REPO_ROOT,
            manifest_path=REPO_ROOT / "AUTOMATION_ORDERS.json",
        )

        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual([], cron_warnings)
        self.assertIn(
            "job weekly_report: target cron supports failure_policy ['log']",
            cron_errors,
        )

    def test_cron_target_rejects_enabled_per_run_job_without_runtime_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            job = valid_automation_job()
            job["approval_mode"] = "per_run"
            authority = cast(dict[str, object], job["authority"])
            authority["basis"] = "per_run_user_approval"
            validity = cast(dict[str, object], authority["validity"])
            validity.update(
                {
                    "expires_on": None,
                    "mode": "per_run",
                    "revocation_events": ["user_revocation"],
                }
            )
            manifest = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [job],
            }

            generic_errors, generic_warnings = automation_orders_lint.validate_manifest(
                manifest,
                project_root=project,
                manifest_path=manifest_path,
            )
            cron_errors, cron_warnings = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )
            with self.assertRaisesRegex(ValueError, "no per-run approval gate"):
                render_cron.render_job(job, project, manifest_path)

        self.assertEqual([], generic_errors)
        self.assertEqual([], generic_warnings)
        self.assertEqual([], cron_warnings)
        self.assertTrue(
            any("no per-run approval gate" in error for error in cron_errors),
            cron_errors,
        )

    def test_cron_target_rejects_enabled_overlap_even_when_generic_schema_allows_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            job = valid_automation_job()
            job["concurrency"] = "allow"
            artifacts = cast(dict[str, object], job["scheduler_artifacts"])
            artifacts["lock_file"] = None
            manifest = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [job],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            generic_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                project_root=project,
                manifest_path=manifest_path,
            )
            cron_errors, _ = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )

        self.assertEqual([], generic_errors)
        self.assertTrue(
            any("does not isolate concurrent command effects" in error for error in cron_errors),
            cron_errors,
        )

    def test_cron_renderer_refuses_disabled_job_when_called_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            job = valid_automation_job()
            job["enabled"] = False

            with self.assertRaisesRegex(ValueError, "disabled jobs must not be rendered"):
                render_cron.render_job(job, project, manifest_path)

    def test_cron_renderer_direct_call_revalidates_complete_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            manifest_path.write_text("{}\n", encoding="utf-8")

            unsafe_schedule = valid_automation_job()
            unsafe_schedule["schedule"] = "0 9 * * 1\n* * * * *"
            with self.assertRaisesRegex(
                ValueError,
                "schedule must not contain control characters",
            ):
                render_cron.render_job(unsafe_schedule, project, manifest_path)

            overlapping = valid_automation_job()
            overlapping["concurrency"] = "allow"
            cast(dict[str, object], overlapping["scheduler_artifacts"])[
                "lock_file"
            ] = None
            with self.assertRaisesRegex(
                ValueError,
                "does not isolate concurrent command effects",
            ):
                render_cron.render_job(overlapping, project, manifest_path)

            invalid_idempotency = valid_automation_job()
            invalid_idempotency["idempotency"] = {"key": None, "mode": "tbd"}
            with self.assertRaisesRegex(ValueError, "idempotency.mode must be one of"):
                render_cron.render_job(invalid_idempotency, project, manifest_path)

    def test_automation_lint_requires_valid_timezone(self) -> None:
        job = valid_automation_job()
        job["timezone"] = "Not/AZone"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn("job weekly_report: timezone must be a valid IANA timezone name", errors)

    def test_automation_lint_rejects_non_normalized_timezone_key(self) -> None:
        job = valid_automation_job()
        job["timezone"] = "../UTC"

        errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: timezone must be a normalized IANA timezone name, not an absolute or traversal path",
            errors,
        )

    def test_automation_lint_reports_missing_timezone_data_separately(self) -> None:
        job = valid_automation_job()

        with mock.patch("automation_orders_lint.ZoneInfo", side_effect=ZoneInfoNotFoundError):
            errors, warnings = automation_orders_lint.validate_manifest({"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]})

        self.assertEqual([], warnings)
        self.assertIn(
            "job weekly_report: timezone cannot be validated because timezone data is unavailable; "
            "install system tzdata or the Python tzdata package",
            errors,
        )

    def test_automation_lint_cron_target_requires_no_external_lock_or_timeout_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest_path = project / "AUTOMATION_ORDERS.json"
            job = valid_automation_job()
            manifest = {"schema_version": automation_orders_lint.SCHEMA_VERSION, "preferred_backend": "cron", "jobs": [job]}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors, warnings = automation_orders_lint.validate_manifest(
                manifest,
                target="cron",
                project_root=project,
                manifest_path=manifest_path,
            )

        self.assertEqual([], warnings)
        self.assertEqual([], errors)

    def test_render_cron_creates_nested_lock_parent_and_rejects_unsupported_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            manifest = project / "orders.json"
            manifest.write_text("{}\n", encoding="utf-8")

            rendered = render_cron.render_job(job, project, manifest)
            expected_digest, expected_runtime_digest = (
                run_scheduled_job.cron_render_digests(
                    job,
                    project,
                    manifest,
                )
            )
            job["failure_policy"] = "disable-until-review"
            with self.assertRaises(ValueError):
                render_cron.render_job(job, project, manifest)

        self.assertIn("scripts/run_scheduled_job.py", rendered)
        self.assertIn("--job-id weekly_report", rendered)
        self.assertIn(
            f"--expected-job-sha256 {expected_digest}",
            rendered,
        )
        self.assertIn(
            f"--expected-runtime-bundle-sha256 {expected_runtime_digest}",
            rendered,
        )
        self.assertEqual(1, rendered.count("--expected-runtime-bundle-sha256"))
        self.assertIn(f"--project-root {project}", rendered)
        self.assertNotIn("flock", rendered)
        self.assertNotIn("mkdir", rendered)
        self.assertNotIn(">>", rendered)
        self.assertIn("CRON_TZ=Europe/Paris", rendered)
        self.assertIn(" -I -S -B ", rendered)
        self.assertIn("-X pycache_prefix=/dev/null", rendered)

    def test_cron_helper_launch_ignores_existing_timestamp_bytecode_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            dependency = scripts_root / "automation_orders_lint.py"
            reviewed_source = dependency.read_bytes()
            cache_marker = root / "timestamp-cache-ran"
            marker_source = (
                "from pathlib import Path\n"
                f"Path({str(cache_marker)!r}).write_text('ran', encoding='utf-8')\n"
            ).encode("utf-8")
            self.assertLess(len(marker_source) + 2, len(reviewed_source))
            stale_source = (
                marker_source
                + b"#"
                + b" " * (len(reviewed_source) - len(marker_source) - 2)
                + b"\n"
            )
            self.assertEqual(len(reviewed_source), len(stale_source))
            stable_mtime = 1_700_000_000
            dependency.write_bytes(stale_source)
            os.utime(dependency, (stable_mtime, stable_mtime))
            compile_adjacent_bytecode(dependency)
            dependency.write_bytes(reviewed_source)
            os.utime(dependency, (stable_mtime, stable_mtime))

            isolated = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(scripts_root / "run_scheduled_job.py"),
                    "--help",
                ],
                cwd=root,
                check=False,
            )
            self.assertEqual(
                0,
                isolated.returncode,
                isolated.stdout + isolated.stderr,
            )
            self.assertFalse(cache_marker.exists())

    def test_scheduled_runner_help_does_not_execute_adjacent_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            markers = []
            for source_name in (
                "python_import_boundary.py",
                "resource_cleanup.py",
            ):
                marker = root / f"{source_name}-ran"
                markers.append(marker)
                (scripts_root / source_name).write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
                    encoding="utf-8",
                )

            for help_flag in ("-h", "--help"):
                with self.subTest(help_flag=help_flag):
                    result = run_bounded(
                        [
                            sys.executable,
                            "-B",
                            str(scripts_root / "run_scheduled_job.py"),
                            help_flag,
                        ],
                        cwd=root,
                        check=False,
                    )
                    self.assertEqual(
                        0,
                        result.returncode,
                        result.stdout + result.stderr,
                    )
                    self.assertIn(
                        "--expected-runtime-bundle-sha256",
                        result.stdout,
                    )
            operational = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(scripts_root / "run_scheduled_job.py"),
                    "--project-root",
                    str(root),
                    "--manifest",
                    str(root / "AUTOMATION_ORDERS.json"),
                    "--job-id",
                    "weekly_report",
                    "--expected-runtime-bundle-sha256",
                    "0" * 64,
                    "--expected-job-sha256",
                    "0" * 64,
                ],
                cwd=root,
                check=False,
            )
            self.assertNotEqual(0, operational.returncode)
            self.assertIn(
                "scheduled runner help and runtime require -E -S -B",
                operational.stderr,
            )
            self.assertTrue(all(not marker.exists() for marker in markers))

    def test_scheduled_runner_rejects_invalid_runtime_digest_before_local_source(
        self,
    ) -> None:
        cases = {
            "missing": [],
            "malformed": ["--expected-runtime-bundle-sha256", "invalid"],
            "uppercase": ["--expected-runtime-bundle-sha256", "A" * 64],
            "duplicate": [
                "--expected-runtime-bundle-sha256",
                "0" * 64,
                "--expected-runtime-bundle-sha256",
                "1" * 64,
            ],
        }
        for case, runtime_digest_args in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                scripts_root = root / "scripts"
                shutil.copytree(
                    REPO_ROOT / "scripts",
                    scripts_root,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
                marker = root / "local-source-ran"
                (scripts_root / "resource_cleanup.py").write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
                    encoding="utf-8",
                )
                result = run_bounded(
                    [
                        sys.executable,
                        *run_scheduled_job.CRON_HELPER_PYTHON_FLAGS,
                        str(scripts_root / "run_scheduled_job.py"),
                        "--project-root",
                        str(root),
                        "--manifest",
                        str(root / "AUTOMATION_ORDERS.json"),
                        "--job-id",
                        "weekly_report",
                        *runtime_digest_args,
                        "--expected-job-sha256",
                        "0" * 64,
                    ],
                    cwd=root,
                    check=False,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertFalse(marker.exists())

    def test_scheduled_runner_refuses_changed_runtime_source_before_execution(
        self,
    ) -> None:
        for source_name in (
            "python_import_boundary.py",
            "resource_cleanup.py",
        ):
            with (
                self.subTest(runtime_source=source_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                scripts_root = root / "scripts"
                shutil.copytree(
                    REPO_ROOT / "scripts",
                    scripts_root,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
                expected_runtime_digest = run_scheduled_job.runtime_bundle_sha256(
                    root
                )
                marker = root / f"{source_name}-ran"
                (scripts_root / source_name).write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
                    encoding="utf-8",
                )

                result = run_bounded(
                    [
                        sys.executable,
                        *run_scheduled_job.CRON_HELPER_PYTHON_FLAGS,
                        str(scripts_root / "run_scheduled_job.py"),
                        "--project-root",
                        str(root),
                        "--manifest",
                        str(root / "AUTOMATION_ORDERS.json"),
                        "--job-id",
                        "weekly_report",
                        "--expected-runtime-bundle-sha256",
                        expected_runtime_digest,
                        "--expected-job-sha256",
                        "0" * 64,
                    ],
                    cwd=root,
                    check=False,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "scheduled runtime bundle changed since cron rendering",
                    result.stderr,
                )
                self.assertFalse(marker.exists())
                self.assertFalse((root / ".automation").exists())

    def test_runtime_bundle_reader_rejects_unsafe_fixed_source_objects(self) -> None:
        cases = ("missing", "symlink", "hardlink", "directory", "fifo", "oversize")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                scripts_root = root / "scripts"
                shutil.copytree(
                    REPO_ROOT / "scripts",
                    scripts_root,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
                source = scripts_root / "resource_cleanup.py"
                original = source.read_bytes()
                source.unlink()
                if case == "symlink":
                    outside = root / "outside.py"
                    outside.write_bytes(original)
                    source.symlink_to(outside)
                elif case == "hardlink":
                    outside = root / "outside.py"
                    outside.write_bytes(original)
                    os.link(outside, source)
                elif case == "directory":
                    source.mkdir()
                elif case == "fifo":
                    os.mkfifo(source)
                elif case == "oversize":
                    source.write_bytes(
                        b"x" * (run_scheduled_job.MAX_RUNTIME_SOURCE_FILE_BYTES + 1)
                    )

                with self.assertRaises((OSError, RuntimeError)):
                    run_scheduled_job.runtime_bundle_sha256(root)

    def test_runtime_bundle_reader_rejects_ambiguous_fixed_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            (scripts_root / "RESOURCE_CLEANUP.PY").write_text(
                "# ambiguous alias\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "ambiguous name edges"):
                run_scheduled_job.runtime_bundle_sha256(root)

    def test_runtime_bundle_reader_rejects_source_metadata_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            target_inode = (scripts_root / "resource_cleanup.py").stat().st_ino
            real_fstat = os.fstat
            target_reads = 0

            class ChangedMetadata:
                def __init__(self, original: os.stat_result) -> None:
                    self._original = original
                    self.st_mtime_ns = original.st_mtime_ns + 1

                def __getattr__(self, name: str) -> Any:
                    return getattr(self._original, name)

            def changed_after_read(
                descriptor: int,
            ) -> os.stat_result | ChangedMetadata:
                nonlocal target_reads
                metadata = real_fstat(descriptor)
                if metadata.st_ino == target_inode:
                    target_reads += 1
                    if target_reads == 2:
                        return ChangedMetadata(metadata)
                return metadata

            with (
                mock.patch.object(os, "fstat", side_effect=changed_after_read),
                self.assertRaisesRegex(RuntimeError, "changed while being read"),
            ):
                run_scheduled_job.runtime_bundle_sha256(root)

    def test_runtime_bundle_reader_rejects_scripts_root_metadata_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            target_inode = scripts_root.stat().st_ino
            real_fstat = os.fstat
            target_reads = 0

            class ChangedMetadata:
                def __init__(self, original: os.stat_result) -> None:
                    self._original = original
                    self.st_ctime_ns = original.st_ctime_ns + 1

                def __getattr__(self, name: str) -> Any:
                    return getattr(self._original, name)

            def changed_after_read(
                descriptor: int,
            ) -> os.stat_result | ChangedMetadata:
                nonlocal target_reads
                metadata = real_fstat(descriptor)
                if metadata.st_ino == target_inode:
                    target_reads += 1
                    if target_reads == 2:
                        return ChangedMetadata(metadata)
                return metadata

            with (
                mock.patch.object(os, "fstat", side_effect=changed_after_read),
                self.assertRaisesRegex(RuntimeError, "scripts root changed"),
            ):
                run_scheduled_job.runtime_bundle_sha256(root)

    def test_scheduled_runner_rejects_package_shadow_before_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
                scripts_root,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            dependency = scripts_root / "automation_orders_lint.py"
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
                    *run_scheduled_job.CRON_HELPER_PYTHON_FLAGS,
                    str(scripts_root / "run_scheduled_job.py"),
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
            expected_runtime_digest = run_scheduled_job.runtime_bundle_sha256(root)

            package_marker = root / "package-ran"
            package = scripts_root / "automation_orders_lint"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(package_marker)!r}).write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )
            shadow_result = run_bounded(
                [
                    sys.executable,
                    *run_scheduled_job.CRON_HELPER_PYTHON_FLAGS,
                    str(scripts_root / "run_scheduled_job.py"),
                    "--project-root",
                    str(root),
                    "--manifest",
                    str(root / "AUTOMATION_ORDERS.json"),
                    "--job-id",
                    "weekly_report",
                    "--expected-runtime-bundle-sha256",
                    expected_runtime_digest,
                    "--expected-job-sha256",
                    "0" * 64,
                ],
                cwd=root,
                check=False,
            )
            self.assertFalse(package_marker.exists())

        self.assertNotEqual(0, shadow_result.returncode)
        self.assertIn(
            "scheduled runner rejected local import shadow: automation_orders_lint",
            shadow_result.stderr,
        )

    def test_cron_runtime_source_closure_matches_local_python_imports(self) -> None:
        scripts_root = REPO_ROOT / "scripts"
        discovered = {"scripts/run_scheduled_job.py"}
        pending = [scripts_root / "run_scheduled_job.py"]
        while pending:
            source = pending.pop()
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            imported_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    dynamic_name = isinstance(node.func, ast.Name) and node.func.id == "__import__"
                    dynamic_attribute = (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_module"
                    )
                    self.assertFalse(
                        dynamic_name or dynamic_attribute,
                        f"dynamic import is outside the sealed flat-module closure: {source}",
                    )
                if isinstance(node, ast.Import):
                    imported_names.update(alias.name.partition(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported_names.add(node.module.partition(".")[0])
            for name in sorted(imported_names):
                candidate = scripts_root / f"{name}.py"
                self.assertFalse(
                    (scripts_root / name).is_dir(),
                    f"local package import is outside the sealed flat-module closure: {name}",
                )
                relative = f"scripts/{name}.py"
                if candidate.is_file() and relative not in discovered:
                    discovered.add(relative)
                    pending.append(candidate)

        self.assertEqual(set(run_scheduled_job.CRON_RUNTIME_SOURCE_PATHS), discovered)
        run_scheduled_job._verify_local_runtime_module_origins()

    def test_descriptor_ownership_preserves_transfer_and_cleanup_failures(self) -> None:
        cleanup_module = run_scheduled_job.resource_cleanup
        real_close = os.close

        predecessor = os.open(os.devnull, os.O_RDONLY)
        child = os.open(os.devnull, os.O_RDONLY)
        owned = cleanup_module.OwnedFileDescriptors()
        owned.adopt(predecessor, "predecessor")
        owned.adopt(child, "child")
        close_calls: list[int] = []
        predecessor_failure = OSError("injected predecessor close failure")

        def fail_predecessor_close(descriptor: int) -> None:
            close_calls.append(descriptor)
            if descriptor == predecessor:
                raise predecessor_failure
            real_close(descriptor)

        try:
            with mock.patch.object(
                cleanup_module.os,
                "close",
                side_effect=fail_predecessor_close,
            ):
                with self.assertRaises(OSError) as failure:
                    owned.close(predecessor)
                self.assertIs(predecessor_failure, failure.exception)
                owned.cleanup(primary=failure.exception)
        finally:
            real_close(predecessor)

        self.assertEqual([predecessor, child], close_calls)
        with self.assertRaises(OSError):
            os.fstat(child)

        for case, primary in (
            ("no-primary", None),
            ("active-primary", KeyboardInterrupt("injected primary")),
        ):
            with self.subTest(case=case):
                descriptors = [
                    os.open(os.devnull, os.O_RDONLY)
                    for _index in range(3)
                ]
                owned = cleanup_module.OwnedFileDescriptors()
                for index, descriptor in enumerate(descriptors):
                    owned.adopt(descriptor, f"cleanup descriptor {index}")
                aggregate_calls: list[int] = []
                cleanup_failure = OSError("injected aggregate cleanup failure")
                faulted = False

                def close_then_fault(descriptor: int) -> None:
                    nonlocal faulted
                    aggregate_calls.append(descriptor)
                    real_close(descriptor)
                    if not faulted:
                        faulted = True
                        raise cleanup_failure

                with mock.patch.object(
                    cleanup_module.os,
                    "close",
                    side_effect=close_then_fault,
                ):
                    if primary is None:
                        with self.assertRaises(OSError) as failure:
                            owned.cleanup()
                        self.assertIs(cleanup_failure, failure.exception)
                    else:
                        owned.cleanup(primary=primary)
                        self.assertIn(
                            "injected aggregate cleanup failure",
                            "\n".join(getattr(primary, "__notes__", ())),
                        )

                self.assertEqual(list(reversed(descriptors)), aggregate_calls)
                for descriptor in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_scheduler_traversal_cleans_registered_child_after_close_fault(
        self,
    ) -> None:
        real_open = os.open
        real_close = os.close
        opened: list[int] = []
        close_calls: list[int] = []
        faulted_descriptor: list[int] = []
        injected = OSError("injected scheduler traversal close failure")

        def track_open(
            path: str | bytes,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            opened.append(descriptor)
            return descriptor

        def fault_first_close(descriptor: int) -> None:
            close_calls.append(descriptor)
            if not faulted_descriptor:
                faulted_descriptor.append(descriptor)
                raise injected
            real_close(descriptor)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                target = Path(temp_dir) / "child"
                target.mkdir()
                with (
                    mock.patch.object(
                        run_scheduled_job,
                        "_directory_flags",
                        return_value=(
                            os.O_RDONLY
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0)
                            | getattr(os, "O_CLOEXEC", 0)
                        ),
                    ),
                    mock.patch.object(
                        run_scheduled_job.os,
                        "open",
                        side_effect=track_open,
                    ),
                    mock.patch.object(
                        run_scheduled_job.os,
                        "close",
                        side_effect=fault_first_close,
                    ),
                    self.assertRaises(OSError) as failure,
                ):
                    run_scheduled_job.open_absolute_directory(
                        target,
                        description="fault-injected traversal",
                    )
                self.assertIs(injected, failure.exception)
        finally:
            for descriptor in faulted_descriptor:
                try:
                    real_close(descriptor)
                except OSError:
                    pass

        self.assertGreaterEqual(len(opened), 2)
        self.assertEqual(opened[:2], close_calls[:2])
        with self.assertRaises(OSError):
            os.fstat(opened[1])

    def test_cron_runtime_rejects_a_local_module_loaded_from_another_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir) / "automation_orders_lint.py"
            outside.write_text("# wrong origin\n", encoding="utf-8")
            with mock.patch.object(automation_orders_lint, "__file__", str(outside)):
                with self.assertRaisesRegex(RuntimeError, "did not load from the bound framework root"):
                    run_scheduled_job._verify_local_runtime_module_origins()

    def test_runtime_aggregate_source_limit_refuses_before_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            project_descriptor = run_scheduled_job.open_absolute_directory(
                project,
                description="test project root",
            )
            framework_descriptor = run_scheduled_job.open_absolute_directory(
                run_scheduled_job.FRAMEWORK_ROOT,
                description="test framework root",
            )
            try:
                with mock.patch.object(
                    run_scheduled_job,
                    "MAX_BOUND_CONTROL_SOURCE_TOTAL_BYTES",
                    1,
                ):
                    with self.assertRaisesRegex(ValueError, "bound runtime, instruction, and execution sources"):
                        run_scheduled_job._bound_source_records(
                            valid_automation_job(),
                            project_descriptor=project_descriptor,
                            framework_descriptor=framework_descriptor,
                        )
            finally:
                os.close(framework_descriptor)
                os.close(project_descriptor)

    def test_each_fixed_runtime_source_changes_the_bound_source_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            framework = root / "framework"
            project.mkdir()
            originals: dict[str, bytes] = {}
            for index, relative in enumerate(
                run_scheduled_job.CRON_RUNTIME_SOURCE_PATHS,
                start=1,
            ):
                path = framework / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = f"runtime source {index}\n".encode()
                path.write_bytes(raw)
                originals[relative] = raw
            for relative in sorted(
                automation_orders_lint.AUTOMATION_REQUIRED_INSTRUCTION_SOURCES
            ):
                instruction = framework / relative
                instruction.parent.mkdir(parents=True, exist_ok=True)
                instruction.write_text(
                    f"# Bound instruction {relative}\n",
                    encoding="utf-8",
                )
            project_descriptor = run_scheduled_job.open_absolute_directory(
                project,
                description="test project root",
            )
            framework_descriptor = run_scheduled_job.open_absolute_directory(
                framework,
                description="test framework root",
            )
            try:
                job = valid_automation_job()
                baseline = run_scheduled_job._bound_source_records(
                    job,
                    project_descriptor=project_descriptor,
                    framework_descriptor=framework_descriptor,
                )
                baseline_bundle_sha256 = (
                    run_scheduled_job._runtime_bundle_sha256_from_records(baseline)
                )
                baseline_runtime = {
                    str(record["path"]): str(record["sha256"])
                    for record in baseline
                    if record["role"] == "runtime"
                }
                for relative, raw in originals.items():
                    with self.subTest(runtime_source=relative):
                        path = framework / relative
                        path.write_bytes(raw + b"changed\n")
                        changed = run_scheduled_job._bound_source_records(
                            job,
                            project_descriptor=project_descriptor,
                            framework_descriptor=framework_descriptor,
                        )
                        changed_runtime = {
                            str(record["path"]): str(record["sha256"])
                            for record in changed
                            if record["role"] == "runtime"
                        }
                        self.assertNotEqual(
                            baseline_runtime[relative],
                            changed_runtime[relative],
                        )
                        self.assertNotEqual(
                            baseline_bundle_sha256,
                            run_scheduled_job._runtime_bundle_sha256_from_records(
                                changed
                            ),
                        )
                        path.write_bytes(raw)
            finally:
                os.close(framework_descriptor)
                os.close(project_descriptor)

    def test_cron_job_authority_digest_is_canonical_and_covers_complete_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            other_project = root / "other"
            project.mkdir()
            other_project.mkdir()
            (project / "scripts").mkdir()
            (project / "scripts" / "digest-probe.py").write_text(
                "print('probe')\n",
                encoding="utf-8",
            )
            manifest = project / "AUTOMATION_ORDERS.json"
            other_manifest = other_project / "AUTOMATION_ORDERS.json"
            job = valid_automation_job()
            baseline = run_scheduled_job.job_authority_sha256(job, project, manifest)
            reordered = dict(reversed(tuple(job.items())))

            self.assertEqual(
                baseline,
                run_scheduled_job.job_authority_sha256(reordered, project, manifest),
            )
            for key, value in job.items():
                with self.subTest(field=key):
                    changed = cast(dict[str, object], json.loads(json.dumps(job)))
                    if isinstance(value, bool):
                        changed[key] = not value
                    elif isinstance(value, int):
                        changed[key] = value + 1
                    elif key == "cwd":
                        (project / "changed-cwd").mkdir(exist_ok=True)
                        changed[key] = "changed-cwd"
                    elif isinstance(value, str):
                        changed[key] = value + "-changed"
                    elif key == "execution_sources":
                        changed[key] = [
                            {
                                "path": "scripts/digest-probe.py",
                                "root": "project",
                            }
                        ]
                    elif key == "instruction_sources":
                        changed[key] = [
                            *cast(list[object], value),
                            {
                                "path": "practice_guides/scheduled_automation.md",
                                "root": "framework",
                            },
                        ]
                    elif isinstance(value, list):
                        changed[key] = [*value, "changed"]
                    elif isinstance(value, dict):
                        changed[key] = {**value, "authority_probe": "changed"}
                    else:
                        self.fail(f"unhandled job value type for {key}: {type(value).__name__}")
                    self.assertNotEqual(
                        baseline,
                        run_scheduled_job.job_authority_sha256(
                            changed,
                            project,
                            manifest,
                        ),
                    )

            extended = {**job, "description": "one approved report only"}
            self.assertNotEqual(
                baseline,
                run_scheduled_job.job_authority_sha256(extended, project, manifest),
            )
            self.assertNotEqual(
                baseline,
                run_scheduled_job.job_authority_sha256(
                    job,
                    other_project,
                    other_manifest,
                ),
            )

    def test_cron_authority_digest_refuses_root_or_cwd_identity_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            project = root / "root-replacement"
            project.mkdir()
            root_job = valid_automation_job()
            root_manifest = project / "AUTOMATION_ORDERS.json"
            root_data = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [root_job],
            }
            root_manifest.write_text(json.dumps(root_data), encoding="utf-8")
            expected_root_digest = run_scheduled_job.job_authority_sha256(
                root_job,
                project,
                root_manifest,
            )
            project.rename(root / "root-replacement-old")
            project.mkdir()
            root_manifest = project / "AUTOMATION_ORDERS.json"
            root_manifest.write_text(json.dumps(root_data), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "project/framework identity"):
                run_scheduled_job.run_job(
                    project,
                    root_manifest,
                    "weekly_report",
                    expected_root_digest,
                )
            self.assertFalse((project / ".automation").exists())

            cwd_project = root / "cwd-replacement"
            cwd_project.mkdir()
            cwd = cwd_project / "work"
            cwd.mkdir()
            cwd_job = valid_automation_job()
            cwd_job["cwd"] = "work"
            cwd_manifest = cwd_project / "AUTOMATION_ORDERS.json"
            cwd_data = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": "cron",
                "jobs": [cwd_job],
            }
            cwd_manifest.write_text(json.dumps(cwd_data), encoding="utf-8")
            expected_cwd_digest = run_scheduled_job.job_authority_sha256(
                cwd_job,
                cwd_project,
                cwd_manifest,
            )
            cwd.rename(cwd_project / "work-old")
            cwd.mkdir()

            with self.assertRaisesRegex(ValueError, "project/framework identity"):
                run_scheduled_job.run_job(
                    cwd_project,
                    cwd_manifest,
                    "weekly_report",
                    expected_cwd_digest,
                )
            self.assertFalse((cwd / ".automation").exists())

    def test_cron_authority_digest_binds_framework_directory_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            first_framework = root / "framework-a"
            second_framework = root / "framework-b"
            project.mkdir()
            for framework in (first_framework, second_framework):
                for relative in (
                    *run_scheduled_job.CRON_RUNTIME_SOURCE_PATHS,
                    *sorted(
                        automation_orders_lint.AUTOMATION_REQUIRED_INSTRUCTION_SOURCES
                    ),
                ):
                    path = framework / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"bound bytes for {relative}\n", encoding="utf-8")

            project_descriptor = run_scheduled_job.open_absolute_directory(
                project,
                description="test project root",
            )
            cwd_descriptor = run_scheduled_job.open_absolute_directory(
                project,
                description="test cwd",
            )
            first_descriptor = run_scheduled_job.open_absolute_directory(
                first_framework,
                description="first test framework root",
            )
            second_descriptor = run_scheduled_job.open_absolute_directory(
                second_framework,
                description="second test framework root",
            )
            try:
                job = valid_automation_job()
                first_digest = run_scheduled_job._job_authority_sha256_from_descriptors(
                    job,
                    project,
                    Path("AUTOMATION_ORDERS.json"),
                    project_descriptor,
                    cwd_descriptor,
                    first_descriptor,
                )
                second_digest = run_scheduled_job._job_authority_sha256_from_descriptors(
                    job,
                    project,
                    Path("AUTOMATION_ORDERS.json"),
                    project_descriptor,
                    cwd_descriptor,
                    second_descriptor,
                )
            finally:
                os.close(second_descriptor)
                os.close(first_descriptor)
                os.close(cwd_descriptor)
                os.close(project_descriptor)

        self.assertNotEqual(first_digest, second_digest)

    def test_validated_cron_job_refuses_selected_job_drift_but_not_sibling_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            alternate_project = root / "alternate-project"
            project.mkdir()
            alternate_project.mkdir()
            manifest = project / "AUTOMATION_ORDERS.json"
            job = valid_automation_job()
            expected = run_scheduled_job.job_authority_sha256(job, project, manifest)

            sibling = valid_automation_job()
            sibling["id"] = "unrelated_job"
            sibling["command"] = "printf unrelated"
            sibling_artifacts = cast(
                dict[str, object],
                sibling["scheduler_artifacts"],
            )
            sibling_artifacts["log_file"] = "logs/unrelated_job.log"
            sibling_artifacts["lock_file"] = "locks/unrelated_job.lock"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job, sibling],
                    }
                ),
                encoding="utf-8",
            )
            selected = run_scheduled_job.validated_job(
                project,
                manifest,
                "weekly_report",
                expected,
            )
            self.assertEqual(job, selected)

            mutations: tuple[tuple[str, object], ...] = (
                ("command", "printf changed"),
                ("timeout_minutes", 31),
                ("schedule", "5 9 * * 1"),
                ("timezone", "UTC"),
                ("enabled", False),
                ("idempotency", {"key": "changed_report", "mode": "replace"}),
            )
            for field, replacement in mutations:
                with self.subTest(field=field):
                    changed = cast(dict[str, object], json.loads(json.dumps(job)))
                    changed[field] = replacement
                    manifest.write_text(
                        json.dumps(
                            {
                                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                                "preferred_backend": "cron",
                                "jobs": [changed, sibling],
                            }
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "authority changed since cron rendering"):
                        run_scheduled_job.validated_job(
                            project,
                            manifest,
                            "weekly_report",
                            expected,
                        )

            changed = cast(dict[str, object], json.loads(json.dumps(job)))
            authority = cast(dict[str, object], changed["authority"])
            authority["resource_refs"] = ["changed_project"]
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [changed, sibling],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "authority changed since cron rendering"):
                run_scheduled_job.validated_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected,
                )

            changed = cast(dict[str, object], json.loads(json.dumps(job)))
            changed["cwd"] = "../alternate-project"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [changed, sibling],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "cwd must be a safe repo-relative path",
            ):
                run_scheduled_job.validated_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected,
                )

            for field, replacement in (
                ("root", ".automation-changed"),
                ("log_file", "logs/changed.log"),
                ("lock_file", "locks/changed.lock"),
                ("max_log_bytes", 2 * 1024 * 1024),
                (
                    "retention",
                    {
                        "days": None,
                        "manual_owner": None,
                        "manual_trigger": None,
                        "mode": "indefinite",
                    },
                ),
                ("redaction", {"mode": "command_redacts_before_capture"}),
            ):
                with self.subTest(scheduler_artifact=field):
                    changed = cast(dict[str, object], json.loads(json.dumps(job)))
                    artifacts = cast(dict[str, object], changed["scheduler_artifacts"])
                    artifacts[field] = replacement
                    manifest.write_text(
                        json.dumps(
                            {
                                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                                "preferred_backend": "cron",
                                "jobs": [changed, sibling],
                            }
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "authority changed since cron rendering"):
                        run_scheduled_job.validated_job(
                            project,
                            manifest,
                            "weekly_report",
                            expected,
                        )

            with self.assertRaisesRegex(ValueError, "64 lowercase hexadecimal"):
                run_scheduled_job.validated_job(
                    project,
                    manifest,
                    "weekly_report",
                    "not-a-digest",
                )

    def test_cron_renderer_refuses_manifest_outside_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            sibling = root / "sibling"
            project.mkdir()
            sibling.mkdir()
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text("{}\n", encoding="utf-8")
            job = valid_automation_job()

            with self.assertRaisesRegex(
                ValueError,
                "automation manifest must be inside the selected project root",
            ):
                render_cron.render_job(job, sibling, manifest)

    def test_cron_renderer_accepts_manifest_nested_inside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            contract_root = project / "contracts" / "mpa"
            contract_root.mkdir(parents=True)
            (project / "work").mkdir()
            manifest = contract_root / "AUTOMATION_ORDERS.json"
            manifest.write_text("{}\n", encoding="utf-8")
            job = valid_automation_job()
            job["cwd"] = "work"

            rendered = render_cron.render_job(job, project, manifest)

        self.assertIn(str(manifest), rendered)
        self.assertIn(f"--project-root {project}", rendered)

    def test_cron_renderer_keeps_stored_percent_command_out_of_crontab(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            job["command"] = "printf '100%% complete\\n'"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )

            rendered = render_cron.render_job(job, project, manifest)

        self.assertNotIn(str(job["command"]), rendered)
        self.assertNotIn("%", rendered)

    def test_cron_renderer_refuses_missing_relative_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text("{}\n", encoding="utf-8")
            job = valid_automation_job()
            job["cwd"] = "missing-work"

            with self.assertRaisesRegex(ValueError, "cwd must name an existing directory"):
                render_cron.render_job(job, project, manifest)

    def test_cron_renderer_refuses_percent_in_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project%cron"
            project.mkdir()
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "project root without '%'"):
                render_cron.render_job(valid_automation_job(), project, manifest)

    def test_cron_runtime_refuses_unimplemented_retention_before_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            artifacts = cast(dict[str, object], job["scheduler_artifacts"])
            artifacts["retention"] = {
                "days": 30,
                "manual_owner": None,
                "manual_trigger": None,
                "mode": "bounded_days",
            }
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            expected = run_scheduled_job.job_authority_sha256(
                job,
                project,
                manifest,
            )

            with self.assertRaisesRegex(
                ValueError,
                "target cron does not execute .*bounded_days",
            ):
                run_scheduled_job.validated_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected,
                )
            self.assertFalse((project / ".automation").exists())

    def test_rendered_cron_runtime_refuses_command_drift_before_creating_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            job["command"] = "printf original"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            rendered = render_cron.render_job(job, project, manifest)
            command = rendered.splitlines()[2].split(None, 5)[5]
            job["command"] = "printf changed"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )

            result = run_bounded(
                ["/bin/bash", "-c", command],
                cwd=Path("/"),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("authority changed since cron rendering", result.stderr)
            self.assertFalse((project / ".automation").exists())

    def test_bound_instruction_and_execution_source_drift_refuses_before_artifacts(self) -> None:
        cases = (
            ("instruction", "mutate"),
            ("instruction", "delete"),
            ("execution", "mutate"),
            ("execution", "delete"),
        )
        for role, action in cases:
            with self.subTest(source_role=role, drift=action):
                with tempfile.TemporaryDirectory() as temp_dir:
                    project = Path(temp_dir)
                    if role == "instruction":
                        source = project / "local_overlays" / "policy.md"
                        source.parent.mkdir()
                        source.write_text("# Approved policy\n", encoding="utf-8")
                    else:
                        source = project / "scripts" / "report.sh"
                        source.parent.mkdir()
                        source.write_text("printf report\n", encoding="utf-8")
                    job = valid_automation_job()
                    reference = {
                        "path": source.relative_to(project).as_posix(),
                        "root": "project",
                    }
                    if role == "instruction":
                        job["instruction_sources"] = [
                            *cast(list[object], job["instruction_sources"]),
                            reference,
                        ]
                    else:
                        job["execution_sources"] = [reference]
                        job["command"] = "sh scripts/report.sh"
                    manifest = project / "AUTOMATION_ORDERS.json"
                    manifest.write_text(
                        json.dumps(
                            {
                                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                                "preferred_backend": "cron",
                                "jobs": [job],
                            }
                        ),
                        encoding="utf-8",
                    )
                    expected = run_scheduled_job.job_authority_sha256(
                        job,
                        project,
                        manifest,
                    )
                    if action == "mutate":
                        source.write_text("changed source bytes\n", encoding="utf-8")
                        with self.assertRaisesRegex(
                            ValueError,
                            "bound source bytes",
                        ):
                            run_scheduled_job.run_job(
                                project,
                                manifest,
                                "weekly_report",
                                expected,
                            )
                    else:
                        source.unlink()
                        with self.assertRaises(FileNotFoundError):
                            run_scheduled_job.run_job(
                                project,
                                manifest,
                                "weekly_report",
                                expected,
                            )
                    self.assertFalse((project / ".automation").exists())

    def test_rerender_after_bound_execution_source_change_updates_seal_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            script = project / "scripts" / "report.sh"
            script.parent.mkdir()
            script.write_text("printf old-report\n", encoding="utf-8")
            job = valid_automation_job()
            job["command"] = "sh scripts/report.sh"
            job["execution_sources"] = [
                {"path": "scripts/report.sh", "root": "project"}
            ]
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            before = render_cron.render_job(job, project, manifest)
            script.write_text("printf new-report\n", encoding="utf-8")
            after = render_cron.render_job(job, project, manifest)
            expected_match = re.search(
                r"--expected-job-sha256 ([0-9a-f]{64})",
                after,
            )
            self.assertIsNotNone(expected_match)
            assert expected_match is not None

            self.assertNotEqual(before, after)
            self.assertEqual(
                0,
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected_match.group(1),
                ),
            )

    def test_cron_lock_inode_is_reused_as_active_coordination_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            expected = run_scheduled_job.job_authority_sha256(
                job,
                project,
                manifest,
            )
            self.assertEqual(
                0,
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected,
                ),
            )
            lock = project / ".automation" / "locks" / "weekly_report.lock"
            first_inode = lock.stat().st_ino
            self.assertEqual(
                0,
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    expected,
                ),
            )
            self.assertEqual(first_inode, lock.stat().st_ino)

    def test_rendered_cron_runtime_rejects_hardlinked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            seed = project / "orders-seed.json"
            manifest = project / "AUTOMATION_ORDERS.json"
            seed.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            os.link(seed, manifest)

            with self.assertRaisesRegex(ValueError, "exactly one hard link"):
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    run_scheduled_job.job_authority_sha256(job, project, manifest),
                )

            self.assertFalse((project / ".automation").exists())

    def test_rendered_cron_runtime_streams_a_bounded_auditable_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            work = project / "work"
            work.mkdir()
            job = valid_automation_job()
            job["command"] = "printf cron-ok:; pwd"
            job["cwd"] = "work"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            rendered = render_cron.render_job(job, project, manifest)
            command = rendered.splitlines()[2].split(None, 5)[5]

            result = run_bounded(
                ["/bin/bash", "-c", command],
                cwd=Path("/"),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            log_text = (
                work / ".automation" / "logs" / "weekly_report.log"
            ).read_text(encoding="utf-8")
            self.assertIn("job weekly_report started", log_text)
            self.assertIn("cron-ok:", log_text)
            self.assertIn(str(work), log_text)
            self.assertIn("job weekly_report exited with status 0", log_text)

    def test_scheduled_output_is_length_framed_and_run_attributed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            forged = b"[2099-01-01] CONTROL run=fake event=exit forged"
            job = valid_automation_job()
            job["command"] = "printf '[2099-01-01] CONTROL run=fake event=exit forged'"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )

            result = run_scheduled_job.run_job(
                project,
                manifest,
                "weekly_report",
                run_scheduled_job.job_authority_sha256(job, project, manifest),
            )

            log_bytes = (
                project / ".automation" / "logs" / "weekly_report.log"
            ).read_bytes()
            output_match = re.search(
                rb"OUTPUT run=([0-9a-f]{32}) bytes=(\d+)\n",
                log_bytes,
            )
            self.assertEqual(0, result)
            self.assertIsNotNone(output_match)
            assert output_match is not None
            payload_start = output_match.end()
            payload_length = int(output_match.group(2))
            self.assertEqual(len(forged), payload_length)
            self.assertEqual(
                forged,
                log_bytes[payload_start : payload_start + payload_length],
            )
            real_run = output_match.group(1)
            self.assertIn(
                b"CONTROL run=" + real_run + b" event=exit ",
                log_bytes[payload_start + payload_length + 1 :],
            )

    def test_rendered_cron_runtime_terminates_output_at_the_log_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            artifacts = cast(dict[str, object], job["scheduler_artifacts"])
            artifacts["max_log_bytes"] = automation_orders_lint.MIN_SCHEDULER_LOG_BYTES
            job["command"] = "head -c 5000 /dev/zero"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )

            result = run_scheduled_job.run_job(
                project,
                manifest,
                "weekly_report",
                run_scheduled_job.job_authority_sha256(job, project, manifest),
            )

            log_path = project / ".automation" / "logs" / "weekly_report.log"
            self.assertEqual(run_scheduled_job.LOG_LIMIT_EXIT, result)
            self.assertLessEqual(log_path.stat().st_size, artifacts["max_log_bytes"])
            self.assertIn(
                "exceeded scheduler_artifacts.max_log_bytes",
                log_path.read_text(encoding="utf-8"),
            )

    def test_rendered_cron_runtime_refuses_a_full_retained_log_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            marker = project / "command-ran"
            job = valid_automation_job()
            artifacts = cast(dict[str, object], job["scheduler_artifacts"])
            max_log_bytes = automation_orders_lint.MIN_SCHEDULER_LOG_BYTES
            artifacts["max_log_bytes"] = max_log_bytes
            job["command"] = f"touch {marker}"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            log_path = project / ".automation" / "logs" / "weekly_report.log"
            log_path.parent.mkdir(parents=True)
            (project / ".automation").chmod(0o700)
            log_path.parent.chmod(0o700)
            log_path.write_bytes(b"x" * max_log_bytes)
            log_path.chmod(0o600)

            with self.assertRaisesRegex(ValueError, "reached max_log_bytes"):
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    run_scheduled_job.job_authority_sha256(job, project, manifest),
                )

            self.assertFalse(marker.exists())
            self.assertEqual(max_log_bytes, log_path.stat().st_size)

    def test_rendered_cron_runtime_honors_the_declared_overlap_lock(self) -> None:
        import fcntl

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            marker = project / "command-ran"
            job = valid_automation_job()
            job["command"] = f"touch {marker}"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            lock_path = project / ".automation" / "locks" / "weekly_report.lock"
            lock_path.parent.mkdir(parents=True)
            (project / ".automation").chmod(0o700)
            lock_path.parent.chmod(0o700)
            with lock_path.open("wb") as external_lock:
                external_lock.write(b"lock")
                external_lock.flush()
                os.fchmod(external_lock.fileno(), 0o600)
                fcntl.flock(external_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    run_scheduled_job.job_authority_sha256(job, project, manifest),
                )

            log_text = (
                project / ".automation" / "logs" / "weekly_report.log"
            ).read_text(encoding="utf-8")
            self.assertEqual(1, result)
            self.assertFalse(marker.exists())
            self.assertIn("skipped because its scheduler lock is held", log_text)

    def test_linux_proc_stat_parser_keeps_comm_bytes_opaque(self) -> None:
        stat_record = b"4242 (worker \xff) phase (2)) S 1 4242 0 0 0\n"

        parsed = run_scheduled_job._parse_linux_proc_stat_state_and_process_group(
            stat_record
        )

        self.assertEqual((b"S", 4242), parsed)

    def test_linux_proc_stat_parser_rejects_malformed_records(self) -> None:
        malformed_records = (
            b"",
            b"123 worker) R 1 2",
            b"not-a-pid (worker) R 1 2",
            b"123 (worker R 1 2",
            b"123 (worker) RR 1 2",
            b"123 (worker) R not-a-parent 2",
            b"123 (worker) R 1 not-a-group",
            b"123 (worker) R 1",
        )
        for stat_record in malformed_records:
            with self.subTest(stat_record=stat_record):
                self.assertIsNone(
                    run_scheduled_job._parse_linux_proc_stat_state_and_process_group(
                        stat_record
                    )
                )

    def test_linux_process_group_probe_is_indeterminate_on_malformed_stat(self) -> None:
        proc_root = mock.Mock()
        proc_root.is_dir.return_value = True
        process_entry = mock.Mock()
        process_entry.name = "123"
        stat_path = mock.Mock()
        stat_path.read_bytes.return_value = b"123 (truncated"
        process_entry.__truediv__ = mock.Mock(return_value=stat_path)
        proc_root.iterdir.return_value = iter((process_entry,))

        with mock.patch.object(run_scheduled_job, "Path", return_value=proc_root):
            result = run_scheduled_job._process_group_has_live_linux_member(123)

        self.assertIsNone(result)

    @unittest.skipUnless(
        sys.platform.startswith("linux") and Path("/proc/self/stat").is_file(),
        "requires Linux procfs",
    )
    def test_linux_process_group_probe_handles_non_utf8_comm(self) -> None:
        child_source = "\n".join(
            (
                "import ctypes",
                "import os",
                "import time",
                "libc = ctypes.CDLL(None, use_errno=True)",
                "libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4",
                "libc.prctl.restype = ctypes.c_int",
                "name = ctypes.create_string_buffer(b'worker\\xff)name')",
                "result = libc.prctl(15, ctypes.addressof(name), 0, 0, 0)",
                "if result != 0:",
                "    raise OSError(ctypes.get_errno(), 'prctl(PR_SET_NAME)')",
                "os.write(1, b'ready\\n')",
                "time.sleep(30)",
            )
        )
        with subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", child_source],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            try:
                assert process.stdout is not None
                ready = process.stdout.readline()
                if ready != b"ready\n":
                    process.wait(timeout=5)
                    assert process.stderr is not None
                    self.fail(process.stderr.read().decode("utf-8", errors="replace"))
                stat_record = Path(f"/proc/{process.pid}/stat").read_bytes()

                self.assertIn(b"\xff", stat_record)
                self.assertTrue(
                    run_scheduled_job._process_group_has_live_linux_member(process.pid)
                )
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    def test_scheduled_output_stream_timeout_terminates_the_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "job.log"
            log_descriptor = os.open(
                log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            process = subprocess.Popen(
                ["/bin/sh", "-c", "sleep 30 & wait"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                returncode, timed_out, exceeded, lingering = run_scheduled_job._stream_bounded_output(
                    process,
                    log_descriptor,
                    run_id="test-timeout-run",
                    timeout_seconds=0.05,
                    output_log_limit=4096,
                )
            finally:
                os.close(log_descriptor)

        self.assertTrue(timed_out)
        self.assertFalse(exceeded)
        self.assertFalse(lingering)
        self.assertIsNotNone(returncode)
        self.assertIsNotNone(process.poll())

    def test_scheduled_stream_invalid_timeout_still_terminates_the_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "job.log"
            log_descriptor = os.open(
                log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            process = subprocess.Popen(
                ["/bin/sh", "-c", "sleep 30 & wait"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                with self.assertRaisesRegex(ValueError, "must be finite"):
                    run_scheduled_job._stream_bounded_output(
                        process,
                        log_descriptor,
                        run_id="test-invalid-timeout-run",
                        timeout_seconds=float("inf"),
                        output_log_limit=4096,
                    )
            finally:
                os.close(log_descriptor)

        self.assertIsNotNone(process.poll())
        self.assertFalse(
            run_scheduled_job._process_group_has_live_linux_member(process.pid)
        )

    def test_scheduled_runtime_terminates_unexpected_background_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            job["command"] = "sleep 30 </dev/null >/dev/null 2>&1 &"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )

            result = run_scheduled_job.run_job(
                project,
                manifest,
                "weekly_report",
                run_scheduled_job.job_authority_sha256(job, project, manifest),
            )

            log_text = (
                project / ".automation" / "logs" / "weekly_report.log"
            ).read_text(encoding="utf-8")
            self.assertEqual(run_scheduled_job.LINGERING_PROCESS_EXIT, result)
            self.assertIn("left a background process", log_text)

    def test_scheduled_runtime_refuses_non_private_artifact_paths(self) -> None:
        for case in ("root", "log", "lock"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                project = Path(temp_dir)
                marker = project / "command-ran"
                job = valid_automation_job()
                job["command"] = f"touch {marker}"
                manifest = project / "AUTOMATION_ORDERS.json"
                manifest.write_text(
                    json.dumps(
                        {
                            "schema_version": automation_orders_lint.SCHEMA_VERSION,
                            "preferred_backend": "cron",
                            "jobs": [job],
                        }
                    ),
                    encoding="utf-8",
                )
                artifact_root = project / ".automation"
                artifact_root.mkdir(mode=0o700)
                if case == "root":
                    artifact_root.chmod(0o755)
                elif case == "log":
                    log_path = artifact_root / "logs" / "weekly_report.log"
                    log_path.parent.mkdir(mode=0o700)
                    log_path.write_bytes(b"")
                    log_path.chmod(0o644)
                else:
                    lock_path = artifact_root / "locks" / "weekly_report.lock"
                    lock_path.parent.mkdir(mode=0o700)
                    lock_path.write_bytes(b"")
                    lock_path.chmod(0o644)

                with self.assertRaisesRegex(
                    ValueError,
                    "must not grant group or world permissions",
                ):
                    run_scheduled_job.run_job(
                        project,
                        manifest,
                        "weekly_report",
                        run_scheduled_job.job_authority_sha256(
                            job,
                            project,
                            manifest,
                        ),
                    )
                self.assertFalse(marker.exists())

    def test_rendered_cron_runtime_refuses_scheduler_root_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            outside = Path(temp_dir) / "outside"
            project.mkdir()
            outside.mkdir()
            job = valid_automation_job()
            job["command"] = "printf must-not-run"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            rendered = render_cron.render_job(job, project, manifest)
            command = rendered.splitlines()[2].split(None, 5)[5]
            original_artifact_root = project / ".automation-original"
            original_artifact_root.mkdir()
            (project / ".automation").symlink_to(outside, target_is_directory=True)

            result = run_bounded(
                ["/bin/bash", "-c", command],
                cwd=Path("/"),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("scheduled job refused", result.stderr)
            self.assertFalse((outside / "logs" / "weekly_report.log").exists())
            self.assertFalse((outside / "locks" / "weekly_report.lock").exists())

    def test_rendered_cron_runtime_refuses_fifo_without_waiting_for_a_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            job = valid_automation_job()
            marker = project / "command-ran"
            job["command"] = f"touch {marker}"
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            log_parent = project / ".automation" / "logs"
            log_parent.mkdir(parents=True)
            (project / ".automation").chmod(0o700)
            log_parent.chmod(0o700)
            os.mkfifo(log_parent / "weekly_report.log", mode=0o600)

            with self.assertRaises(OSError):
                run_scheduled_job.run_job(
                    project,
                    manifest,
                    "weekly_report",
                    run_scheduled_job.job_authority_sha256(job, project, manifest),
                )

            self.assertFalse(marker.exists())

    def test_render_cron_uses_cron_target_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            manifest = project / "AUTOMATION_ORDERS.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "sys.argv",
                [
                    "render_cron.py",
                    str(manifest),
                    "--project-root",
                    str(project),
                ],
            ):
                with mock.patch(
                    "automation_orders_lint.validate_manifest",
                    return_value=(["target error"], []),
                ) as validate:
                    with mock.patch("sys.stdout", new_callable=io.StringIO):
                        result = render_cron.main()

        self.assertEqual(1, result)
        self.assertEqual("cron", validate.call_args.kwargs["target"])

    def test_render_cron_refuses_existing_output_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "orders.json"
            output = root / "crontab"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [valid_automation_job()],
                    }
                ),
                encoding="utf-8",
            )
            output.write_text("existing\n", encoding="utf-8")

            with mock.patch(
                "sys.argv",
                [
                    "render_cron.py",
                    str(manifest),
                    "--project-root",
                    str(root),
                    "--output",
                    str(output),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    refused = render_cron.main()
            self.assertEqual(1, refused)
            self.assertIn("refusing to overwrite existing output", stdout.getvalue())
            self.assertEqual("existing\n", output.read_text(encoding="utf-8"))

            with mock.patch(
                "sys.argv",
                [
                    "render_cron.py",
                    str(manifest),
                    "--project-root",
                    str(root),
                    "--output",
                    str(output),
                    "--force",
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    overwritten = render_cron.main()
            self.assertIn("# Generated by scripts/render_cron.py", output.read_text(encoding="utf-8"))

        self.assertEqual(0, overwritten)

    def test_render_cron_rejects_symlink_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "orders.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [valid_automation_job()],
                    }
                ),
                encoding="utf-8",
            )
            cron_target = root / "cron-target"
            cron_output = root / "cron-output"
            cron_output.symlink_to(cron_target)

            with mock.patch(
                "sys.argv",
                [
                    "render_cron.py",
                    str(manifest),
                    "--project-root",
                    str(root),
                    "--output",
                    str(cron_output),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    self.assertEqual(1, render_cron.main())

        self.assertIn("symlink output path", stdout.getvalue())

    def test_automation_lint_rejects_empty_cron_step(self) -> None:
        for schedule in ("*/ 6 * * 1", "*/ * * * *", "5/ * * * *"):
            with self.subTest(schedule=schedule):
                job = valid_automation_job()
                job["id"] = "weekly"
                job["schedule"] = schedule
                manifest = {
                    "schema_version": automation_orders_lint.SCHEMA_VERSION,
                    "preferred_backend": "cron",
                    "jobs": [job],
                }

                errors, warnings = automation_orders_lint.validate_manifest(manifest)

                self.assertEqual([], warnings)
                self.assertIn(
                    "job weekly: schedule must be a bounded ASCII numeric 5-field "
                    "cron expression without '%'",
                    errors,
                )

    def test_automation_lint_rejects_non_ascii_and_unbounded_cron_numerals(self) -> None:
        invalid_schedules = {
            "superscript": "0 ² * * 1",
            "fullwidth": "０ 9 * * 1",
            "nonbreaking-space": "0\u00a09 * * 1",
            "huge-numeral": f"{'9' * 10000} 9 * * 1",
        }
        expected = (
            "job weekly: schedule must be a bounded ASCII numeric 5-field "
            "cron expression without '%'"
        )
        for label, schedule in invalid_schedules.items():
            with self.subTest(case=label):
                job = valid_automation_job()
                job["id"] = "weekly"
                job["schedule"] = schedule

                errors, warnings = automation_orders_lint.validate_manifest(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [job],
                    }
                )

                self.assertEqual([], warnings)
                self.assertEqual([expected], errors)
