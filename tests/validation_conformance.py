"""Conformance metadata and bounded-input validation tests."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT  # noqa: F401

import conformance_check  # noqa: E402
import automation_orders_lint  # noqa: E402
import integration_registry  # noqa: E402
import project_bootstrap  # noqa: E402
import safe_paths  # noqa: E402


def _write_universal_project_pair(root: Path) -> None:
    """Satisfy retained-input/receipt profile surfaces when checks are mocked."""

    (root / "PROJECT_INPUT.json").write_text("{}\n", encoding="utf-8")
    (root / "PROJECT_INSTANCE.json").write_text("{}\n", encoding="utf-8")


class ConformanceTests(unittest.TestCase):
    def test_automation_conformance_derives_cron_target_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            contract_root = project_root / "private" / "authoring"
            contract_root.mkdir(parents=True)
            (contract_root / "AUTOMATION_ORDERS.json").write_text(
                json.dumps(
                    {
                        "schema_version": automation_orders_lint.SCHEMA_VERSION,
                        "preferred_backend": "cron",
                        "jobs": [],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                conformance_check,
                "run_command_capture",
                return_value=conformance_check.CommandCapture(
                    ok=True,
                    stdout=json.dumps({"errors": [], "warnings": []}),
                    returncode=0,
                ),
            ) as run:
                outcome = conformance_check.check_automation_manifest_lints(
                    project_root,
                    contract_root,
                )

        self.assertIsInstance(outcome, conformance_check.CheckOutcome)
        if not isinstance(outcome, conformance_check.CheckOutcome):
            self.fail("automation conformance did not return a structured outcome")
        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        argv = run.call_args.args[1]
        self.assertEqual(
            ["--project-root", str(project_root), "--target", "cron"],
            argv[-4:],
        )

    def test_project_state_lint_receives_contract_and_project_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            contract_root = project_root / "private" / "authoring"

            with mock.patch.object(
                conformance_check,
                "run_command_capture",
                return_value=conformance_check.CommandCapture(
                    ok=True,
                    stdout=json.dumps({"errors": [], "warnings": []}),
                    returncode=0,
                ),
            ) as run:
                outcome = conformance_check.check_project_state_files_lint(
                    project_root,
                    contract_root,
                )

        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        argv = run.call_args.args[1]
        self.assertEqual(
            [
                "--root",
                str(contract_root),
                "--project-root",
                str(project_root),
            ],
            argv[-4:],
        )

    def test_structured_child_reports_survive_nonzero_exit(self) -> None:
        payload = {
            "errors": ["semantic failure"],
            "warnings": ["advisory"],
        }
        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            return_value=conformance_check.CommandCapture(
                ok=False,
                stdout=json.dumps(payload),
                returncode=1,
            ),
        ):
            outcome = conformance_check.run_json_child(
                "structured-child",
                ["child"],
                REPO_ROOT,
            )

        self.assertEqual(("semantic failure",), outcome.errors)
        self.assertEqual(("advisory",), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        self.assertTrue(outcome.failed())

    def test_structured_child_parses_stdout_and_rejects_stderr(self) -> None:
        outcome = conformance_check.run_json_child(
            "split-stream-child",
            [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    "print(json.dumps({'errors': ['semantic failure'], "
                    "'warnings': ['advisory']})); "
                    "print('side-channel diagnostic', file=sys.stderr); "
                    "sys.exit(1)"
                ),
            ],
            REPO_ROOT,
        )

        self.assertEqual(("semantic failure",), outcome.errors)
        self.assertEqual(("advisory",), outcome.warnings)
        self.assertIn("stderr must be empty", outcome.protocol_failure or "")
        self.assertIn("side-channel diagnostic", outcome.protocol_failure or "")
        self.assertNotIn("invalid JSON", outcome.protocol_failure or "")

    def test_structured_child_rejects_invalid_utf8_stdout(self) -> None:
        outcome = conformance_check.run_json_child(
            "invalid-utf8-child",
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.stdout.buffer.write("
                    "b'{\"errors\": [], \"warnings\": [\"\\xff\"]}')"
                ),
            ],
            REPO_ROOT,
        )

        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIn("must be valid UTF-8", outcome.protocol_failure or "")

    def test_structured_child_validates_shape_and_exit_contract(self) -> None:
        cases = (
            (True, "[]", "top level must be an object"),
            (True, json.dumps({"errors": [], "warnings": "bad"}), "warnings must be a list"),
            (
                True,
                '{"errors": [], "errors": [], "warnings": []}',
                "duplicate JSON key",
            ),
            (
                True,
                '{"errors": [], "warnings": [], "value": NaN}',
                "non-finite JSON number",
            ),
            (False, "not-json", "failed before returning a valid report"),
            (
                False,
                json.dumps({"errors": [], "warnings": []}),
                "exited nonzero despite reporting no failing diagnostics",
            ),
            (
                True,
                json.dumps({"errors": ["failure"], "warnings": []}),
                "exited zero despite reporting failing diagnostics",
            ),
        )
        for command_ok, output, expected in cases:
            with self.subTest(command_ok=command_ok, output=output):
                with mock.patch.object(
                    conformance_check,
                    "run_command_capture",
                    return_value=conformance_check.CommandCapture(
                        ok=command_ok,
                        stdout=output,
                        returncode=0 if command_ok else 1,
                    ),
                ):
                    outcome = conformance_check.run_json_child(
                        "structured-child",
                        ["child"],
                        REPO_ROOT,
                    )
                self.assertIn(expected, outcome.protocol_failure or "")
                self.assertTrue(outcome.failed())

    def test_structured_child_retains_valid_items_and_all_shape_failures(self) -> None:
        payload = {
            "errors": ["kept error", 7, "later error"],
            "warnings": ["kept warning", 8, "later warning"],
        }
        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            return_value=conformance_check.CommandCapture(
                ok=False,
                stdout=json.dumps(payload),
                returncode=1,
            ),
        ):
            outcome = conformance_check.run_json_child(
                "mixed-child",
                ["child"],
                REPO_ROOT,
            )

        self.assertEqual(("kept error", "later error"), outcome.errors)
        self.assertEqual(("kept warning", "later warning"), outcome.warnings)
        protocol_failure = outcome.protocol_failure or ""
        self.assertIn("errors[1] has an unsupported shape", protocol_failure)
        self.assertIn("warnings[1] has an unsupported shape", protocol_failure)

    def test_structured_child_preserves_declared_protocol_failures_separately(
        self,
    ) -> None:
        payload = {
            "errors": ["semantic failure"],
            "warnings": [],
            "protocol_failures": ["child transport failure"],
        }
        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            return_value=conformance_check.CommandCapture(
                ok=False,
                stdout=json.dumps(payload),
                returncode=1,
            ),
        ):
            outcome = conformance_check.run_json_child(
                "nested-conformance",
                ["child"],
                REPO_ROOT,
            )

        self.assertEqual(("semantic failure",), outcome.errors)
        self.assertEqual("child transport failure", outcome.protocol_failure)
        self.assertNotIn("child transport failure", outcome.report_errors())

    def test_structured_child_warning_policy_is_explicit(self) -> None:
        output = json.dumps({"errors": [], "warnings": ["advisory"]})
        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            side_effect=(
                conformance_check.CommandCapture(
                    ok=True,
                    stdout=output,
                    returncode=0,
                ),
                conformance_check.CommandCapture(
                    ok=False,
                    stdout=output,
                    returncode=1,
                ),
            ),
        ):
            report_only = conformance_check.run_json_child(
                "report-only",
                ["child"],
                REPO_ROOT,
            )
            strict = conformance_check.run_json_child(
                "strict",
                ["child"],
                REPO_ROOT,
                warnings_fail=True,
            )

        self.assertFalse(report_only.failed())
        self.assertEqual(("advisory",), report_only.warnings)
        self.assertIsNone(report_only.protocol_failure)
        self.assertTrue(strict.failed())
        self.assertEqual(("advisory",), strict.warnings)
        self.assertIsNone(strict.protocol_failure)

    def test_project_contract_sync_conformance_is_report_only_by_default(self) -> None:
        output = json.dumps({"errors": [], "warnings": ["contract advisory"]})
        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            return_value=conformance_check.CommandCapture(
                ok=True,
                stdout=output,
                returncode=0,
            ),
        ) as run:
            outcome = conformance_check.check_project_contract_sync(REPO_ROOT)

        self.assertEqual(("contract advisory",), outcome.warnings)
        self.assertFalse(outcome.failed())
        self.assertNotIn("--strict-warnings", run.call_args.args[1])

    def test_authoring_export_validation_runs_public_role_checks_without_git_inference(
        self,
    ) -> None:
        calls: list[tuple[str, list[str], Path, float | None]] = []

        def fake_export_command(
            label: str,
            command: list[str],
            cwd: Path,
            *,
            timeout_seconds: float = conformance_check.COMMAND_TIMEOUT_SECONDS,
        ) -> tuple[bool, str]:
            calls.append((label, command, cwd, timeout_seconds))
            return True, "exported"

        def fake_report_command(
            label: str,
            command: list[str],
            cwd: Path,
            *,
            timeout_seconds: float = conformance_check.COMMAND_TIMEOUT_SECONDS,
        ) -> conformance_check.CommandCapture:
            calls.append((label, command, cwd, timeout_seconds))
            return conformance_check.CommandCapture(
                ok=True,
                stdout=json.dumps({"errors": [], "warnings": []}),
                returncode=0,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(
                    conformance_check,
                    "run_command",
                    side_effect=fake_export_command,
                ),
                mock.patch.object(
                    conformance_check,
                    "run_command_capture",
                    side_effect=fake_report_command,
                ),
            ):
                outcome = (
                    conformance_check.check_framework_public_export_validation(
                        root
                    )
                )

        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        self.assertEqual(
            [
                "public-export",
                "exported-tree-conformance",
                "exported-tree-self-compliance",
            ],
            [label for label, _command, _cwd, _timeout in calls],
        )
        export_command = calls[0][1]
        exported_tree = export_command[export_command.index("--output") + 1]
        exported_check = calls[1][1]
        self_check = calls[2][1]
        self.assertTrue(
            any("public_export.py" in argument for argument in export_command)
        )
        self.assertTrue(
            any("conformance_check.py" in argument for argument in exported_check)
        )
        self.assertEqual(
            "framework-public-release",
            exported_check[exported_check.index("--profile") + 1],
        )
        self.assertEqual(
            exported_tree,
            exported_check[exported_check.index("--root") + 1],
        )
        self.assertEqual(
            [
                sys.executable,
                "-B",
                "scripts/framework_compliance.py",
                "--tree-role",
                "public-export",
            ],
            self_check,
        )
        self.assertEqual(Path(exported_tree), calls[2][2])
        self.assertEqual(
            conformance_check.PUBLIC_EXPORT_TIMEOUT_SECONDS,
            calls[0][3],
        )
        self.assertEqual(
            conformance_check.EXPORTED_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
            calls[1][3],
        )
        self.assertEqual(
            conformance_check.EXPORTED_TREE_SELF_COMPLIANCE_TIMEOUT_SECONDS,
            calls[2][3],
        )

    def test_release_profiles_have_static_role_specific_checks(self) -> None:
        registry, metadata_errors = conformance_check.load_profiles()
        self.assertEqual([], metadata_errors)
        if registry is None:
            self.fail("current conformance registry did not load")

        public_checks, _public_files, _public_directories, public_error = (
            conformance_check.expand_profile(
                "framework-public-release",
                registry,
            )
        )
        authoring_checks, _authoring_files, _authoring_directories, authoring_error = (
            conformance_check.expand_profile(
                "framework-authoring-release",
                registry,
            )
        )

        self.assertIsNone(public_error)
        self.assertIsNone(authoring_error)
        self.assertIn("framework_public_release", public_checks)
        self.assertNotIn("framework_authoring_release", public_checks)
        self.assertNotIn("framework_public_export_validation", public_checks)
        self.assertIn("framework_authoring_release", authoring_checks)
        self.assertIn("framework_public_export_validation", authoring_checks)
        self.assertNotIn("framework_public_release", authoring_checks)

    def test_release_checks_use_role_derived_outer_timeouts(self) -> None:
        clean = conformance_check.CheckOutcome()
        with mock.patch.object(
            conformance_check,
            "run_json_child",
            return_value=clean,
        ) as child:
            self.assertIs(
                clean,
                conformance_check.check_framework_authoring_release(REPO_ROOT),
            )
            self.assertEqual(
                conformance_check.AUTHORING_RELEASE_TIMEOUT_SECONDS,
                child.call_args.kwargs["timeout_seconds"],
            )

            self.assertIs(
                clean,
                conformance_check.check_framework_public_release(REPO_ROOT),
            )
            self.assertEqual(
                conformance_check.COMMAND_TIMEOUT_SECONDS,
                child.call_args.kwargs["timeout_seconds"],
            )

    def test_release_profiles_preserve_role_specific_negative_results(self) -> None:
        registry, metadata_errors = conformance_check.load_profiles()
        self.assertEqual([], metadata_errors)
        if registry is None:
            self.fail("current conformance registry did not load")

        cases = (
            (
                "framework-public-release",
                "framework_public_release",
                "public export role defect",
                {"framework_authoring_release", "framework_public_export_validation"},
            ),
            (
                "framework-authoring-release",
                "framework_public_export_validation",
                "authoring export chain defect",
                {"framework_public_release"},
            ),
        )
        for profile_id, failing_check, defect, excluded_checks in cases:
            with self.subTest(profile_id=profile_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                checks, files, directories, profile_error = (
                    conformance_check.expand_profile(profile_id, registry)
                )
                self.assertIsNone(profile_error)
                for directory in directories:
                    (root / directory).mkdir(parents=True, exist_ok=True)
                for relative_path in files:
                    path = root / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture\n", encoding="utf-8")
                replacements = {
                    check_id: mock.Mock(return_value=[])
                    for check_id in conformance_check.CHECKS
                }
                replacements[failing_check] = mock.Mock(return_value=[defect])

                with mock.patch.dict(
                    conformance_check.CHECKS,
                    replacements,
                    clear=True,
                ):
                    report = conformance_check.run_profiles([profile_id], root)

            self.assertEqual("fail", report["status"])
            self.assertEqual(1, report["errors"].count(defect))
            replacements[failing_check].assert_called_once_with(root)
            for check_id in checks:
                replacements[check_id].assert_called_once()
            for check_id in excluded_checks:
                replacements[check_id].assert_not_called()

    def test_nested_compliance_timeouts_cover_sequential_children(self) -> None:
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.AUTHORING_RELEASE_GIT_CHILD_TIMEOUTS
            ),
            conformance_check.AUTHORING_RELEASE_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.PUBLIC_EXPORT_AUTHORING_SNAPSHOT_TIMEOUTS
            ),
            conformance_check.PUBLIC_EXPORT_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            180.0,
            conformance_check.CORE_PROJECT_AUTHORING_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.CORE_PROJECT_AUTHORING_CHILD_TIMEOUTS
            ),
            conformance_check.CORE_PROJECT_AUTHORING_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            (
                "framework-validate",
                "framework-consistency",
                "framework-public-release",
            ),
            tuple(
                label
                for label, _seconds in (
                    conformance_check.EXPORTED_FRAMEWORK_CONFORMANCE_CHILD_TIMEOUTS
                )
            ),
        )
        self.assertEqual(
            (
                "framework-validate",
                "framework-consistency",
                "framework-authoring-release",
                "framework-public-export-validation",
            ),
            tuple(
                label
                for label, _seconds in (
                    conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_CHILD_TIMEOUTS
                )
            ),
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.EXPORTED_FRAMEWORK_CONFORMANCE_CHILD_TIMEOUTS
            ),
            conformance_check.EXPORTED_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.EXPORTED_TREE_COMPLIANCE_CHILD_TIMEOUTS
            ),
            conformance_check.EXPORTED_TREE_SELF_COMPLIANCE_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.PUBLIC_EXPORT_VALIDATION_CHILD_TIMEOUTS
            ),
            conformance_check.PUBLIC_EXPORT_VALIDATION_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.PUBLIC_EXPORT_TIMEOUT_SECONDS,
            dict(conformance_check.PUBLIC_EXPORT_VALIDATION_CHILD_TIMEOUTS)[
                "public-export"
            ],
        )
        self.assertEqual(
            conformance_check.AUTHORING_RELEASE_TIMEOUT_SECONDS,
            dict(conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_CHILD_TIMEOUTS)[
                "framework-authoring-release"
            ],
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_CHILD_TIMEOUTS
            ),
            conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
        )
        exported_children = dict(
            conformance_check.EXPORTED_TREE_COMPLIANCE_CHILD_TIMEOUTS
        )
        self.assertEqual(
            conformance_check.COMMAND_TIMEOUT_SECONDS * 10,
            conformance_check.EXPORTED_TREE_UNIT_TEST_WORK_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            conformance_check.COMMAND_TIMEOUT_SECONDS * 5,
            conformance_check.EXPORTED_TREE_UNIT_TEST_SHARED_RUNTIME_MARGIN_SECONDS,
        )
        self.assertEqual(
            conformance_check.sequential_timeout_budget(
                (
                    (
                        "unit-test-suite-work",
                        conformance_check.EXPORTED_TREE_UNIT_TEST_WORK_TIMEOUT_SECONDS,
                    ),
                ),
                orchestration_margin_seconds=(
                    conformance_check.EXPORTED_TREE_UNIT_TEST_SHARED_RUNTIME_MARGIN_SECONDS
                ),
            ),
            exported_children["unit-tests"],
        )
        self.assertGreater(
            conformance_check.EXPORTED_TREE_SELF_COMPLIANCE_TIMEOUT_SECONDS,
            exported_children["unit-tests"]
            + exported_children["conformance-framework-public-release"],
        )
        self.assertGreater(
            conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
            conformance_check.EXPORTED_TREE_SELF_COMPLIANCE_TIMEOUT_SECONDS,
        )
        self.assertLessEqual(
            conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
            conformance_check.COMMAND_MAX_TIMEOUT_SECONDS,
        )

    def test_profile_prerequisites_block_only_dependent_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("STATEMENT_OF_WORK.md", "AGENT_PROJECT.md", "DECISIONS.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                )

        prerequisite = report["checks"][0]
        self.assertEqual("profile_required_surfaces", prerequisite["id"])
        self.assertEqual("prerequisite", prerequisite["phase"])
        self.assertEqual("fail", prerequisite["status"])
        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("pass", by_id["project_core_files"]["status"])
        self.assertEqual("blocked", by_id["project_state_files_lint"]["status"])
        replacements["project_core_files"].assert_called_once()
        replacements["project_state_files_lint"].assert_not_called()
        replacements["project_entrypoint_resolves"].assert_called_once()
        replacements["project_contract_sync"].assert_called_once()
        missing_todo = "missing required file for selected profile: TODO.md"
        self.assertEqual(1, report["errors"].count(missing_todo))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            conformance_check.print_report(report, "text")
        self.assertEqual(1, stdout.getvalue().count(missing_todo))

    def test_nested_contract_routes_only_instance_receipt_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            contract_root = project_root / "private" / "authoring"
            contract_root.mkdir(parents=True)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
                "PROJECT_INPUT.json",
            ):
                (contract_root / name).write_text(f"# {name}\n", encoding="utf-8")
            (project_root / "PROJECT_INSTANCE.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            contract_root_ref = "private" + "/authoring"
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                passing = conformance_check.run_profiles(
                    ["core-project"],
                    project_root,
                    contract_root=contract_root,
                    contract_root_ref=contract_root_ref,
                    project_kind="framework-authoring",
                )
                (project_root / "PROJECT_INSTANCE.json").replace(
                    contract_root / "PROJECT_INSTANCE.json"
                )
                failing = conformance_check.run_profiles(
                    ["core-project"],
                    project_root,
                    contract_root=contract_root,
                    contract_root_ref=contract_root_ref,
                    project_kind="framework-authoring",
                )

        self.assertEqual("pass", passing["status"], passing)
        self.assertEqual("fail", failing["status"], failing)
        self.assertIn(
            "missing required file for selected profile: PROJECT_INSTANCE.json",
            failing["errors"],
        )
        failed_checks = {item["id"]: item for item in failing["checks"]}
        self.assertEqual(
            ["PROJECT_INSTANCE.json"],
            failed_checks["project_core_files"]["blocked_by"],
        )

    def test_profile_union_expands_and_executes_shared_claims_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
                "PROJECT_INPUT.json",
                "PROJECT_INSTANCE.json",
                "SOURCE_PACKS.md",
                "SOURCE_UPDATE.md",
                "SECURITY_VERIFICATION.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with (
                mock.patch.dict(
                    conformance_check.CHECKS,
                    replacements,
                    clear=True,
                ),
                mock.patch.object(
                    conformance_check,
                    "project_required_file_diagnostic_map",
                    wraps=conformance_check.project_required_file_diagnostic_map,
                ) as required_files,
                mock.patch.object(
                    conformance_check,
                    "required_directory_diagnostic_map",
                    wraps=conformance_check.required_directory_diagnostic_map,
                ) as required_directories,
            ):
                report = conformance_check.run_profiles(
                    ["source-managed", "security-managed"],
                    root,
                    contract_root=root,
                )

        self.assertEqual("pass", report["status"], report)
        self.assertEqual(
            ["source-managed", "security-managed"],
            report["profiles"],
        )
        self.assertNotIn("profile", report)
        self.assertEqual(
            ["source-managed", "security-managed"],
            [item["id"] for item in report["profile_results"]],
        )
        self.assertIn(
            "project_core_files",
            report["profile_results"][0]["required_checks"],
        )
        self.assertIn(
            "project_core_files",
            report["profile_results"][1]["required_checks"],
        )
        replacements["project_core_files"].assert_called_once()
        replacements["project_contract_sync"].assert_called_once()
        replacements["source_freshness_metadata"].assert_called_once()
        replacements["security_verification_file"].assert_called_once()
        required_files.assert_called_once()
        required_directories.assert_called_once()
        union_files = required_files.call_args.args[2]
        self.assertEqual(len(union_files), len(set(union_files)))

    def test_profile_union_preserves_profile_specific_failure_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
                "PROJECT_INPUT.json",
                "PROJECT_INSTANCE.json",
                "SOURCE_PACKS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project", "source-managed"],
                    root,
                    contract_root=root,
                )

        by_profile = {item["id"]: item for item in report["profile_results"]}
        self.assertEqual("pass", by_profile["core-project"]["status"])
        self.assertEqual("fail", by_profile["source-managed"]["status"])
        self.assertIn(
            "missing required file for selected profile: SOURCE_UPDATE.md",
            by_profile["source-managed"]["errors"],
        )
        replacements["project_core_files"].assert_called_once()
        replacements["source_freshness_metadata"].assert_not_called()

    def test_only_missing_receipt_blocks_core_file_check(self) -> None:
        generated_files = (
            "STATEMENT_OF_WORK.md",
            "AGENT_PROJECT.md",
            "TODO.md",
            "DECISIONS.md",
        )
        cases = (
            "STATEMENT_OF_WORK.md",
            "TODO.md",
            "PROJECT_INPUT.json",
            "PROJECT_INSTANCE.json",
        )
        for missing in cases:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for name in generated_files:
                    (root / name).write_text(f"# {name}\n", encoding="utf-8")
                _write_universal_project_pair(root)
                (root / missing).unlink()
                replacements = {
                    check_id: mock.Mock(return_value=[])
                    for check_id in conformance_check.CHECKS
                }
                with mock.patch.dict(
                    conformance_check.CHECKS,
                    replacements,
                    clear=True,
                ):
                    report = conformance_check.run_profiles(
                        ["core-project"],
                        root,
                        contract_root=root,
                    )

            by_id = {item["id"]: item for item in report["checks"]}
            missing_diagnostic = (
                f"missing required file for selected profile: {missing}"
            )
            self.assertEqual(1, report["errors"].count(missing_diagnostic))
            if missing == "PROJECT_INSTANCE.json":
                self.assertEqual(
                    "blocked",
                    by_id["project_core_files"]["status"],
                )
                self.assertEqual(
                    ["PROJECT_INSTANCE.json"],
                    by_id["project_core_files"]["blocked_by"],
                )
                replacements["project_core_files"].assert_not_called()
            else:
                self.assertEqual("pass", by_id["project_core_files"]["status"])
                replacements["project_core_files"].assert_called_once()

    def test_unsafe_receipt_blocks_core_file_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            outside_receipt = base / "outside-receipt.json"
            outside_receipt.write_text("{}\n", encoding="utf-8")
            (root / "PROJECT_INSTANCE.json").unlink()
            (root / "PROJECT_INSTANCE.json").symlink_to(outside_receipt)
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                )

        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("blocked", by_id["project_core_files"]["status"])
        self.assertEqual(
            ["PROJECT_INSTANCE.json"],
            by_id["project_core_files"]["blocked_by"],
        )
        replacements["project_core_files"].assert_not_called()
        self.assertTrue(
            any(
                "required profile file PROJECT_INSTANCE.json" in error
                for error in report["errors"]
            ),
            report["errors"],
        )

    def test_missing_contract_does_not_block_independent_entrypoint_diagnostics(self) -> None:
        cases = ("missing-entrypoint", "missing-charter")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for name in ("STATEMENT_OF_WORK.md", "TODO.md", "DECISIONS.md"):
                    (root / name).write_text(f"# {name}\n", encoding="utf-8")
                _write_universal_project_pair(root)
                if case == "missing-charter":
                    missing_framework = root / "missing-framework"
                    entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                        "generic",
                        str(missing_framework),
                    )
                    (root / entrypoint_name).write_text(
                        entrypoint,
                        encoding="utf-8",
                    )

                entrypoint_check = mock.Mock(
                    side_effect=conformance_check.check_project_entrypoint_resolves
                )
                replacements = {
                    check_id: mock.Mock(return_value=[])
                    for check_id in conformance_check.CHECKS
                }
                replacements["project_entrypoint_resolves"] = entrypoint_check
                with mock.patch.dict(
                    conformance_check.CHECKS,
                    replacements,
                    clear=True,
                ):
                    report = conformance_check.run_profiles(
                        ["core-project"],
                        root,
                        contract_root=root,
                    )

                missing_contract = (
                    "missing required file for selected profile: AGENT_PROJECT.md"
                )
                self.assertEqual(1, report["errors"].count(missing_contract))
                self.assertNotIn(
                    "AGENT_PROJECT.md missing for generated entrypoint",
                    report["errors"],
                )
                entrypoint_check.assert_called_once()
                by_id = {item["id"]: item for item in report["checks"]}
                self.assertEqual(
                    "fail",
                    by_id["project_entrypoint_resolves"]["status"],
                )
                if case == "missing-entrypoint":
                    expected = (
                        "missing generated runtime entrypoint: AGENTS.md or CLAUDE.md"
                    )
                else:
                    expected = (
                        "entrypoint framework reference does not resolve operative charter: "
                        f"{root / 'missing-framework'}"
                    )
                self.assertEqual(1, report["errors"].count(expected))

    def test_framework_checks_continue_after_independent_surface_failure(self) -> None:
        registry, metadata_errors = conformance_check.load_profiles()
        self.assertEqual([], metadata_errors)
        if registry is None:
            self.fail("current conformance registry did not load")
        checks, files, directories, profile_error = (
            conformance_check.expand_profile(
                "framework-public-release",
                registry,
            )
        )
        self.assertIsNone(profile_error)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for directory in directories:
                (root / directory).mkdir(parents=True, exist_ok=True)
            for relative_path in files:
                if relative_path == "SPECIFICATION.md":
                    continue
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            independent_defect = "independent framework defect"
            replacements["framework_consistency"] = mock.Mock(
                return_value=[independent_defect]
            )
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["framework-public-release"],
                    root,
                )

        missing_surface = (
            "missing required file for selected profile: SPECIFICATION.md"
        )
        self.assertEqual(1, report["errors"].count(missing_surface))
        self.assertEqual(1, report["errors"].count(independent_defect))
        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("fail", by_id["framework_consistency"]["status"])
        for check_id in checks:
            self.assertNotEqual("blocked", by_id[check_id]["status"])
            replacements[check_id].assert_called_once()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            conformance_check.print_report(report, "text")
        rendered = stdout.getvalue()
        self.assertEqual(1, rendered.count(missing_surface))
        self.assertEqual(1, rendered.count(independent_defect))

    def test_profile_continues_after_check_exception_and_invalid_return(self) -> None:
        registry = {
            "profiles": [
                {
                    "id": "synthetic-framework",
                    "subject": "framework",
                }
            ]
        }
        raising_check = mock.Mock(side_effect=RuntimeError("boom\nwith detail"))
        invalid_check = mock.Mock(return_value={"errors": []})
        later_check = mock.Mock(return_value=["later semantic defect"])
        checks = {
            "raising_check": raising_check,
            "invalid_check": invalid_check,
            "later_check": later_check,
        }
        with (
            mock.patch.object(
                conformance_check,
                "load_profiles",
                return_value=(registry, []),
            ),
            mock.patch.object(
                conformance_check,
                "expand_profile",
                return_value=(list(checks), [], [], None),
            ),
            mock.patch.dict(conformance_check.CHECKS, checks, clear=True),
        ):
            report = conformance_check.run_profiles(
                ["synthetic-framework"],
                REPO_ROOT,
            )

        by_id = {item["id"]: item for item in report["checks"]}
        self.assertIn(
            "conformance check raising_check raised RuntimeError: boom with detail",
            by_id["raising_check"]["protocol_failure"] or "",
        )
        self.assertIn(
            "expected CheckOutcome or list[str], observed dict",
            by_id["invalid_check"]["protocol_failure"] or "",
        )
        self.assertEqual(
            ["later semantic defect"],
            by_id["later_check"]["errors"],
        )
        self.assertEqual(["later semantic defect"], report["errors"])
        self.assertEqual(2, len(report["protocol_failures"]))
        self.assertNotIn(
            "conformance check raising_check raised",
            "\n".join(report["errors"]),
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            conformance_check.print_report(report, "text")
        rendered = stdout.getvalue()
        for failure in report["protocol_failures"]:
            self.assertEqual(1, rendered.count(failure))
        raising_check.assert_called_once()
        invalid_check.assert_called_once()
        later_check.assert_called_once()

    def test_authoring_instance_is_owned_by_profile_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            (root / "PROJECT_INSTANCE.json").unlink()
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                    project_kind="framework-authoring",
                )

        missing_instance = (
            "missing required file for selected profile: PROJECT_INSTANCE.json"
        )
        self.assertEqual(1, report["errors"].count(missing_instance))
        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("blocked", by_id["project_core_files"]["status"])
        self.assertEqual(
            ["PROJECT_INSTANCE.json"],
            by_id["project_core_files"]["blocked_by"],
        )
        replacements["project_core_files"].assert_not_called()

    def test_missing_state_does_not_block_malformed_authoring_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "DECISIONS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            project_core_check = mock.Mock(
                side_effect=conformance_check.check_project_core_files
            )
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            replacements["project_core_files"] = project_core_check
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                    project_kind="framework-authoring",
                )

        missing_todo = "missing required file for selected profile: TODO.md"
        self.assertEqual(1, report["errors"].count(missing_todo))
        malformed_instance = (
            "project instance manifest schema_version is missing. The current-only "
            "lifecycle supports exactly schema_version "
            f"{project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION} and does not migrate "
            "or rewrite other receipt formats; perform a reviewed project-specific "
            "manual update before running current-schema checks"
        )
        self.assertEqual(1, report["errors"].count(malformed_instance), report["errors"])
        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("fail", by_id["project_core_files"]["status"])
        project_core_check.assert_called_once()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            conformance_check.print_report(report, "text")
        rendered = stdout.getvalue()
        self.assertEqual(1, rendered.count(missing_todo))
        self.assertEqual(1, rendered.count(malformed_instance))

    def test_noncurrent_receipt_preflights_before_missing_retained_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            unsupported_version = project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION - 1
            (root / "PROJECT_INSTANCE.json").write_text(
                json.dumps({"schema_version": unsupported_version}) + "\n",
                encoding="utf-8",
            )
            project_core_check = mock.Mock(
                side_effect=conformance_check.check_project_core_files
            )
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            replacements["project_core_files"] = project_core_check
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                    project_kind="framework-authoring",
                )

        missing_input = (
            "missing required file for selected profile: PROJECT_INPUT.json"
        )
        manual_update_errors = [
            error
            for error in report["errors"]
            if "project instance manifest schema_version" in error
            and "current-only lifecycle" in error
            and "manual update" in error
        ]
        self.assertEqual(1, report["errors"].count(missing_input))
        self.assertEqual(1, len(manual_update_errors), report["errors"])
        self.assertFalse(
            any("retained project input" in error for error in report["errors"]),
            report["errors"],
        )
        by_id = {item["id"]: item for item in report["checks"]}
        self.assertEqual("fail", by_id["project_core_files"]["status"])
        project_core_check.assert_called_once()

    def test_profile_warning_aggregation_and_strict_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            replacements["project_contract_sync"] = mock.Mock(
                return_value=conformance_check.CheckOutcome(
                    warnings=("shared advisory", "shared advisory"),
                )
            )
            replacements["project_state_files_lint"] = mock.Mock(
                return_value=conformance_check.CheckOutcome(
                    warnings=("shared advisory",),
                )
            )
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["core-project"],
                    root,
                    contract_root=root,
                )

        self.assertEqual("warn", report["status"])
        self.assertEqual(["shared advisory"], report["warnings"])
        self.assertEqual("none", report["error_class"])
        warning_checks = [
            item for item in report["checks"] if item["status"] == "warn"
        ]
        self.assertEqual(2, len(warning_checks))
        original_checks = deepcopy(report["checks"])
        original_errors = deepcopy(report["errors"])
        original_warnings = deepcopy(report["warnings"])
        conformance_check.apply_strict_warning_policy(
            report,
            strict_warnings=True,
        )
        self.assertEqual("fail", report["status"])
        self.assertEqual("conformance", report["error_class"])
        self.assertEqual(original_checks, report["checks"])
        self.assertEqual(original_errors, report["errors"])
        self.assertEqual(original_warnings, report["warnings"])

    def test_conformance_cli_strict_warnings_changes_only_aggregate_status(self) -> None:
        base_report = {
            "profiles": ["core-project"],
            "profile_results": [],
            "root": str(REPO_ROOT),
            "contract_root": ".",
            "project_kind": "downstream",
            "checks": [
                {
                    "id": "project_contract_sync",
                    "phase": "check",
                    "status": "warn",
                    "errors": [],
                    "warnings": ["contract advisory"],
                    "protocol_failure": None,
                }
            ],
            "errors": [],
            "warnings": ["contract advisory"],
            "status": "warn",
            "error_class": "none",
        }
        cases = (
            ([], 0, "warn", "none"),
            (["--strict-warnings"], 1, "fail", "conformance"),
        )
        for extra_args, expected_code, expected_status, expected_class in cases:
            with self.subTest(extra_args=extra_args):
                argv = [
                    "conformance_check.py",
                    "--profile",
                    "core-project",
                    "--root",
                    str(REPO_ROOT),
                    "--format",
                    "json",
                    *extra_args,
                ]
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(
                        conformance_check.project_instance_lint,
                        "contract_root_path",
                        return_value=(REPO_ROOT, None),
                    ),
                    mock.patch.object(
                        conformance_check,
                        "run_profiles",
                        return_value=deepcopy(base_report),
                    ),
                    mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                ):
                    return_code = conformance_check.main()
                payload = json.loads(stdout.getvalue())
                self.assertEqual(expected_code, return_code)
                self.assertEqual(expected_status, payload["status"])
                self.assertEqual(expected_class, payload["error_class"])
                self.assertEqual(base_report["checks"], payload["checks"])
                self.assertEqual(base_report["errors"], payload["errors"])
                self.assertEqual(base_report["warnings"], payload["warnings"])

    def test_source_profile_warning_remains_intrinsically_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "TODO.md",
                "DECISIONS.md",
                "SOURCE_PACKS.md",
                "SOURCE_UPDATE.md",
            ):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            _write_universal_project_pair(root)
            replacements = {
                check_id: mock.Mock(return_value=[])
                for check_id in conformance_check.CHECKS
            }
            replacements["source_freshness_metadata"] = mock.Mock(
                return_value=conformance_check.CheckOutcome(
                    warnings=("stale source",),
                    warnings_fail=True,
                )
            )
            with mock.patch.dict(
                conformance_check.CHECKS,
                replacements,
                clear=True,
            ):
                report = conformance_check.run_profiles(
                    ["source-managed"],
                    root,
                    contract_root=root,
                )

        self.assertEqual("fail", report["status"])
        self.assertEqual([], report["errors"])
        self.assertEqual(["stale source"], report["warnings"])
        source_result = next(
            item
            for item in report["checks"]
            if item["id"] == "source_freshness_metadata"
        )
        self.assertEqual("fail", source_result["status"])

    def test_non_file_uris_are_not_absolute_paths(self) -> None:
        for value in (
            "https://example.com/path/to/resource",
            "ssh://user@example.com/repository",
            "--url=https://example.com/api/v1",
            "https://example.com/a_(b)/c",
            "[docs](https://example.com/a_(b)/c)",
        ):
            with self.subTest(value=value):
                self.assertFalse(safe_paths.contains_absolute_path(value))
        unix_path = "/" + "tmp/local"
        windows_path = "C:" + "\\" + "Users\\alice\\local"
        for value in (
            unix_path,
            windows_path,
            "file://" + unix_path,
            "https://example.com/api " + unix_path,
            "https://example.com/a_(b)/c " + unix_path,
            "https://example.com/api;" + unix_path,
        ):
            with self.subTest(value=value):
                self.assertTrue(safe_paths.contains_absolute_path(value))

    def test_conformance_metadata_rejects_boolean_schema_version(self) -> None:
        registry, load_errors = conformance_check.load_profiles()
        self.assertEqual([], load_errors)
        if registry is None:
            self.fail("current conformance registry did not load")
        candidate = deepcopy(registry)
        candidate["schema_version"] = True

        errors = conformance_check.validate_profile_metadata(candidate)

        self.assertIn(
            "conformance profiles schema_version must be exactly 1",
            errors,
        )

    def test_conformance_schema_validator_rejects_non_string_required_items(self) -> None:
        non_string_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "required": ["schema_version", {"not": "hashable"}],
            "properties": {},
        }
        duplicate_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "spec_version",
                "checks",
                "profiles",
                "profiles",
            ],
            "properties": {},
        }

        for schema in (non_string_schema, duplicate_schema):
            with self.subTest(required=schema["required"]):
                errors = conformance_check.validate_schema_file(schema)
                self.assertIn(
                    "conformance profile schema required fields must match profiles.json top-level fields",
                    errors,
                )

    def test_conformance_metadata_rejects_control_bearing_paths(self) -> None:
        registry, load_errors = conformance_check.load_profiles()
        self.assertEqual([], load_errors)
        if registry is None:
            self.fail("current conformance registry did not load")
        candidate = deepcopy(registry)
        candidate["profiles"][0]["required_files"] = ["docs/bad\x00name.md"]

        errors = conformance_check.validate_profile_metadata(candidate)

        self.assertTrue(
            any("required file must not contain control characters" in error for error in errors),
            errors,
        )

    def test_conformance_metadata_and_expansion_handle_deep_inheritance(self) -> None:
        registry, load_errors = conformance_check.load_profiles()
        self.assertEqual([], load_errors)
        if registry is None:
            self.fail("current conformance registry did not load")
        candidate = {
            "schema_version": 1,
            "spec_version": "1.0.0",
            "checks": deepcopy(registry["checks"]),
            "profiles": [],
        }
        profiles = candidate["profiles"]
        if not isinstance(profiles, list):
            self.fail("synthetic profile list was not created")
        for index in range(1_500):
            profile_id = f"p-{index:04d}"
            profile = {
                "description": f"Synthetic profile {index}",
                "id": profile_id,
                "required_checks": [],
                "required_files": [],
                "subject": "project",
            }
            if index:
                profile["extends"] = [f"p-{index - 1:04d}"]
            if index == 0:
                profile["required_checks"] = ["project_core_files"]
                profile["required_files"] = ["parent.md"]
                profile["required_directories"] = ["parent-dir"]
            elif index == 1_499:
                profile["required_checks"] = ["project_state_files_lint"]
                profile["required_files"] = ["leaf.md"]
                profile["required_directories"] = ["leaf-dir"]
            profiles.append(profile)
        candidate["profiles"] = list(reversed(profiles))

        errors = conformance_check.validate_profile_metadata(candidate)
        checks, files, directories, expansion_error = conformance_check.expand_profile(
            "p-1499",
            candidate,
        )

        self.assertEqual([], errors)
        self.assertEqual(
            (
                ["project_core_files", "project_state_files_lint"],
                ["parent.md", "leaf.md"],
                ["parent-dir", "leaf-dir"],
                None,
            ),
            (checks, files, directories, expansion_error),
        )

    def test_conformance_json_loader_enforces_bounded_regular_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")
            hardlink = root / "hardlink.json"
            os.link(source, hardlink)
            fifo = root / "metadata.fifo"
            os.mkfifo(fifo)
            invalid_utf8 = root / "invalid.json"
            invalid_utf8.write_bytes(b"\xff")
            oversized = root / "oversized.json"
            oversized.write_bytes(
                b" " * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
            )

            cases = (
                (hardlink, "exactly one hard link"),
                (fifo, "regular file"),
                (invalid_utf8, "valid UTF-8"),
                (oversized, "input limit"),
            )
            for path, expected in cases:
                with self.subTest(path=path.name):
                    payload, errors = conformance_check.load_json_object(
                        path,
                        "fixture metadata",
                    )
                    self.assertIsNone(payload)
                    self.assertTrue(
                        any(expected in error for error in errors),
                        errors,
                    )

            missing, missing_errors = conformance_check.load_json_object(
                root / "missing.json",
                "fixture metadata",
            )
            self.assertIsNone(missing)
            self.assertTrue(
                any("is missing" in error for error in missing_errors),
                missing_errors,
            )

    def test_conformance_text_consumers_fail_closed_on_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_bytes(b"\xff")
            roots, entrypoint_errors = conformance_check.entrypoint_framework_roots(
                root
            )
            self.assertEqual([], roots)
            self.assertTrue(
                any("must be valid UTF-8" in error for error in entrypoint_errors),
                entrypoint_errors,
            )

            (root / "SECURITY_VERIFICATION.md").write_bytes(b"\xff")
            security_errors = conformance_check.check_security_verification_file(root)
            self.assertTrue(
                any("must be valid UTF-8" in error for error in security_errors),
                security_errors,
            )

    def test_conformance_resolves_canonical_filesystem_root_framework_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                "generic",
                "/",
            )
            (project_root / entrypoint_name).write_text(
                entrypoint,
                encoding="utf-8",
            )

            roots, errors = conformance_check.entrypoint_framework_roots(project_root)

        self.assertEqual([], errors)
        self.assertEqual([Path("/")], roots)

    def test_conformance_resolves_only_marker_selected_framework_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            missing_decoy_root = project_root / "missing-decoy-framework"
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                "generic",
                str(REPO_ROOT),
            )
            entrypoint += (
                "\nRead `"
                f"{missing_decoy_root}/runtime/operative_charter.md"
                "` before acting. This line is outside every authority-load block.\n"
            )
            (project_root / entrypoint_name).write_text(
                entrypoint,
                encoding="utf-8",
            )
            (project_root / "AGENT_PROJECT.md").write_text(
                "# Project Contract\n",
                encoding="utf-8",
            )

            roots, root_errors = conformance_check.entrypoint_framework_roots(
                project_root
            )
            errors = conformance_check.check_project_entrypoint_resolves(project_root)

        self.assertEqual([], root_errors)
        self.assertEqual([REPO_ROOT.resolve()], roots)
        self.assertEqual([], errors)

    def test_conformance_rejects_authority_load_decoys_for_every_runtime(self) -> None:
        contract_root_ref = ".mpa/contracts"
        for runtime in ("generic", "codex", "claude-code"):
            with tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                contract_root = project_root / contract_root_ref
                contract_root.mkdir(parents=True)
                (contract_root / "AGENT_PROJECT.md").write_text(
                    "# Project Contract\n",
                    encoding="utf-8",
                )
                entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                    runtime,
                    str(REPO_ROOT),
                    contract_root_ref=contract_root_ref,
                )
                entrypoint_path = project_root / entrypoint_name
                entrypoint_path.write_text(entrypoint, encoding="utf-8")

                with self.subTest(runtime=runtime, mutation="valid"):
                    self.assertEqual(
                        [],
                        conformance_check.check_project_entrypoint_resolves(
                            project_root,
                            contract_root,
                            contract_root_ref=contract_root_ref,
                        ),
                    )

                lines = entrypoint.splitlines()
                framework_marker = lines.index(
                    integration_registry.FRAMEWORK_CORE_MARKER
                )
                contract_marker = lines.index(
                    integration_registry.PROJECT_CONTRACT_MARKER
                )
                state_marker = lines.index(integration_registry.STATE_LOADING_MARKER)
                framework_directive_index = next(
                    index
                    for index in range(framework_marker + 1, contract_marker)
                    if "operative_charter.md" in lines[index]
                )
                project_directive_index = next(
                    index
                    for index in range(contract_marker + 1, state_marker)
                    if "AGENT_PROJECT.md" in lines[index]
                )
                mutations = (
                    (
                        "framework-directive-decoy",
                        framework_directive_index,
                        "framework authority-load directive is missing, inactive, or malformed",
                    ),
                    (
                        "project-directive-decoy",
                        project_directive_index,
                        "project-contract authority-load directive is missing, inactive, malformed, or selects the wrong contract",
                    ),
                )
                for mutation, directive_index, expected_error in mutations:
                    with self.subTest(runtime=runtime, mutation=mutation):
                        candidate_lines = list(lines)
                        decoy = candidate_lines[directive_index]
                        candidate_lines[directive_index] = "Authority-load directive removed."
                        candidate_lines.extend(("", decoy))
                        candidate = "\n".join(candidate_lines) + "\n"
                        entrypoint_path.write_text(candidate, encoding="utf-8")
                        errors = conformance_check.check_project_entrypoint_resolves(
                            project_root,
                            contract_root,
                            contract_root_ref=contract_root_ref,
                        )
                        self.assertTrue(
                            any(expected_error in error for error in errors),
                            errors,
                        )

    def test_framework_maintainer_authority_loads_are_operative_directives(self) -> None:
        contract_root_ref = ("pri" + "vate") + "/authoring"
        charter_directive = (
            "Read `runtime/operative_charter.md` before acting. "
            "It is the always-on operative charter."
        )
        recovery_marker = integration_registry.RECOVERY_GUARD_MARKER
        recovery_clause = integration_registry.RECOVERY_GUARD_CLAUSE
        contract_directive = (
            f"If `{contract_root_ref}/AGENT_PROJECT.md` exists, load it after the "
            "operative charter as the concrete authoring-project runtime layer and "
            f"resolve its project-state references against `{contract_root_ref}/`."
        )
        valid = (
            "# Maintainer\n\n<framework-rules>\n"
            f"{charter_directive}\n{recovery_marker}\n{recovery_clause}\n"
            f"{contract_directive}\n"
            "</framework-rules>\n"
        )
        cases = {
            "valid": (valid, False),
            "comment": (
                "# Maintainer\n\n<framework-rules>\n"
                f"<!-- {charter_directive} -->\n{recovery_marker}\n"
                f"{recovery_clause}\n{contract_directive}\n"
                "</framework-rules>\n",
                True,
            ),
            "fence": (
                "# Maintainer\n\n<framework-rules>\n```text\n"
                f"{charter_directive}\n```\n{recovery_marker}\n"
                f"{recovery_clause}\n{contract_directive}\n"
                "</framework-rules>\n",
                True,
            ),
            "negated": (
                "# Maintainer\n\n<framework-rules>\n"
                "Do not read `runtime/operative_charter.md` before acting.\n"
                f"{recovery_marker}\n{recovery_clause}\n"
                f"{contract_directive}\n</framework-rules>\n",
                True,
            ),
            "descriptive-decoy": (
                "# Maintainer\n\n<framework-rules>\n"
                "The runtime/operative_charter.md path is the operative charter.\n"
                f"{recovery_marker}\n{recovery_clause}\n"
                f"{contract_directive}\n</framework-rules>\n",
                True,
            ),
            "outside-owner-block": (
                "# Maintainer\n\n"
                f"{charter_directive}\n{recovery_marker}\n{recovery_clause}\n"
                "<framework-rules>\n"
                f"{contract_directive}\n</framework-rules>\n",
                True,
            ),
        }
        for name, (entrypoint, should_fail) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "runtime").mkdir()
                (root / "runtime" / "operative_charter.md").write_text(
                    "# Operative Charter\n",
                    encoding="utf-8",
                )
                (root / "AGENTS.md").write_text(entrypoint, encoding="utf-8")
                errors = conformance_check.check_project_entrypoint_resolves(
                    root,
                    root / contract_root_ref,
                    project_kind="framework-authoring",
                    contract_root_ref=contract_root_ref,
                )

            if should_fail:
                self.assertTrue(
                    any("operative charter load directive" in error for error in errors),
                    errors,
                )
            else:
                self.assertEqual([], errors)

    def test_framework_maintainer_recovery_guard_precedes_nested_authority_and_state(
        self,
    ) -> None:
        contract_root_ref = ("pri" + "vate") + "/authoring"
        charter_directive = (
            "Read `runtime/operative_charter.md` before acting. "
            "It is the always-on operative charter."
        )
        recovery_marker = integration_registry.RECOVERY_GUARD_MARKER
        recovery_clause = integration_registry.RECOVERY_GUARD_CLAUSE
        contract_directive = (
            f"If `{contract_root_ref}/AGENT_PROJECT.md` exists, load it after the "
            "operative charter as the concrete authoring-project runtime layer and "
            f"resolve its project-state references against `{contract_root_ref}/`."
        )

        def entrypoint(*between_charter_and_guard: str) -> str:
            return (
                "# Maintainer\n\n<framework-rules>\n"
                f"{charter_directive}\n"
                + "\n".join(between_charter_and_guard)
                + ("\n" if between_charter_and_guard else "")
                + f"{recovery_marker}\n{recovery_clause}\n"
                + f"{contract_directive}\n</framework-rules>\n"
            )

        cases = {
            "valid": (entrypoint(), False, None),
            "early-authority-read": (
                entrypoint(f"Read `{contract_root_ref}/AGENT_PROJECT.md` now."),
                True,
                "before the recovery guard",
            ),
            "early-state-read": (
                entrypoint(f"Read `{contract_root_ref}/TODO.md` now."),
                True,
                "before the recovery guard",
            ),
            "commented-early-read": (
                entrypoint(
                    f"<!-- Read `{contract_root_ref}/TODO.md` now. -->"
                ),
                False,
                None,
            ),
            "fenced-early-read": (
                entrypoint(
                    "```text",
                    f"Read `{contract_root_ref}/TODO.md` now.",
                    "```",
                ),
                False,
                None,
            ),
            "paraphrased-clause": (
                entrypoint().replace(
                    recovery_clause,
                    "Check for a recovery file before continuing.",
                ),
                True,
                "exact recovery clause once",
            ),
            "guard-after-contract": (
                (
                    "# Maintainer\n\n<framework-rules>\n"
                    f"{charter_directive}\n{contract_directive}\n"
                    f"{recovery_marker}\n{recovery_clause}\n"
                    "</framework-rules>\n"
                ),
                True,
                "recovery guard",
            ),
        }
        for name, (candidate, should_fail, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "runtime").mkdir()
                (root / "runtime" / "operative_charter.md").write_text(
                    "# Operative Charter\n",
                    encoding="utf-8",
                )
                (root / "AGENTS.md").write_text(candidate, encoding="utf-8")
                errors = conformance_check.check_project_entrypoint_resolves(
                    root,
                    root / contract_root_ref,
                    project_kind="framework-authoring",
                    contract_root_ref=contract_root_ref,
                )

            if should_fail:
                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )
            else:
                self.assertEqual([], errors)

    def test_security_sections_ignore_mixed_fences_and_multiline_comments(self) -> None:
        text = (
            "# Security Verification\n\n"
            "```text\n"
            "~~~\n"
            "## Scope\n"
            "fenced spoof\n"
            "```\n\n"
            "## Profiles\n"
            "<!--\n"
            "comment-only spoof\n"
            "-->\n"
        )

        sections = conformance_check.markdown_h2_sections(text)

        self.assertNotIn("Scope", sections)
        self.assertFalse(
            conformance_check.section_has_substantive_content(sections["Profiles"][0])
        )


if __name__ == "__main__":
    unittest.main()
