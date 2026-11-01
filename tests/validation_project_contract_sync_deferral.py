"""Project contract synchronization deferral, scope, and duplicate-order tests."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest

from tests.validation_project_contract_sync import (
    FixtureMutation,
    remove_markdown_section,
    render_fixture,
    run_sync,
)
from tests.validation_test_support import (
    DEFERRED_VALUE_CLASSIFICATION_CASES,
    REPO_ROOT,
    TEST_FRAMEWORK_RUNNER,
    run_bounded,
    valid_automation_job,
)

import integration_registry  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import project_contract_sync  # noqa: E402


def remove_plain_section(text: str, title: str) -> str:
    """Remove one unprefixed SOW section and its body from a rendered fixture."""

    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line == title:
            skipping = True
            continue
        if skipping and line in project_contract_sync.SOW_TITLES:
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept) + "\n"


class ProjectContractSyncDeferralTests(unittest.TestCase):
    def test_project_contract_sync_accepts_exact_safe_wrapped_runner(self) -> None:
        runner = "container exec --workdir workspace target uv run python -E -S -B"
        lines = project_contract_model.framework_verification_command_lines(
            "$FRAMEWORK",
            runner=runner,
        )

        errors = project_contract_sync.framework_verification_command_errors(
            lines,
            expected_runner=runner,
        )

        self.assertEqual([], errors)

    def test_environment_framework_commands_preserve_one_script_token(self) -> None:
        runner = f"{shlex.quote(sys.executable)} -E -S -B"
        core_command = next(
            line.removeprefix("- Core conformance: ")
            for line in project_contract_model.framework_verification_command_lines(
                "$FRAMEWORK",
                runner=runner,
            )
            if line.startswith("- Core conformance: ")
        )
        monitor_command = project_contract_model.source_monitor_artifact_lint_command(
            runner,
            "$FRAMEWORK",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            framework_root = root / "framework root"
            scripts_root = framework_root / "scripts"
            scripts_root.mkdir(parents=True)
            for script_name in (
                "conformance_check.py",
                "source_chain_artifact_lint.py",
            ):
                (scripts_root / script_name).write_text(
                    "from pathlib import Path\n"
                    f"Path({str(root / (script_name + '.ran'))!r}).write_text('ran', encoding='utf-8')\n",
                    encoding="utf-8",
                )

            injection_marker = root / "injection-ran"
            malicious_reference = (
                "-c __import__('pathlib').Path("
                f"{str(injection_marker)!r}"
                ").write_text('ran') #"
            )
            for command in (core_command, monitor_command):
                with self.subTest(command=command, case="option-shaped expansion"):
                    result = run_bounded(
                        [
                            "/usr/bin/env",
                            f"FRAMEWORK={malicious_reference}",
                            "/bin/sh",
                            "-c",
                            command,
                        ],
                        cwd=root,
                        check=False,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(injection_marker.exists())

            for command, script_name in (
                (core_command, "conformance_check.py"),
                (monitor_command, "source_chain_artifact_lint.py"),
            ):
                with self.subTest(command=command, case="space-bearing path"):
                    result = run_bounded(
                        [
                            "/usr/bin/env",
                            f"FRAMEWORK={framework_root}",
                            "/bin/sh",
                            "-c",
                            command,
                        ],
                        cwd=root,
                        check=False,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertTrue((root / (script_name + ".ran")).is_file())

    def test_project_contract_sync_rejects_consuming_runner_even_when_rows_match(self) -> None:
        for runner in ("sh -c id", "python3 -c pass"):
            with self.subTest(runner=runner):
                lines = project_contract_model.framework_verification_command_lines(
                    "$FRAMEWORK",
                    runner=runner,
                )

                errors = project_contract_sync.framework_verification_command_errors(
                    lines,
                    expected_runner=runner,
                )

                self.assertTrue(
                    any("supported non-consuming Python runner" in error for error in errors),
                    errors,
                )

    def test_project_contract_sync_rejects_framework_verification_runner_drift(self) -> None:
        lines = project_contract_model.framework_verification_command_lines(
            "$FRAMEWORK",
            runner="uv run python -E -S -B",
        )

        errors = project_contract_sync.framework_verification_command_errors(
            lines,
            expected_runner="container exec verification-runtime uv run python -E -S -B",
        )

        self.assertTrue(
            any("does not use the SOW Framework Verification Runner" in error for error in errors),
            errors,
        )

    def test_project_contract_sync_rejects_verification_reference_fallback_and_extra_command_drift(self) -> None:
        lines = project_contract_model.framework_verification_command_lines(
            "$FRAMEWORK",
            runner="uv run python -E -S -B",
        )
        wrong_reference = [
            line.replace(
                "${FRAMEWORK:?FRAMEWORK is required}/scripts/conformance_check.py",
                "/other/scripts/conformance_check.py",
            )
            for line in lines
        ]
        wrong_fallback = [
            line.replace(
                'uv run python -E -S -B -- "${FRAMEWORK:?FRAMEWORK is required}/scripts/check_prereqs.py"',
                'python3 -E -S -B -- "${FRAMEWORK:?FRAMEWORK is required}/scripts/check_prereqs.py"',
            )
            for line in lines
        ]
        appended = [
            line + "; run another command" if line.startswith("- Core conformance:") else line
            for line in lines
        ]

        for drifted in (wrong_reference, wrong_fallback, appended):
            with self.subTest(drifted=drifted):
                errors = project_contract_sync.framework_verification_command_errors(
                    drifted,
                    expected_runner="uv run python -E -S -B",
                )
                self.assertTrue(any("does not exactly match" in error for error in errors), errors)

    def test_project_contract_sync_rejects_entrypoint_verification_framework_drift(self) -> None:
        entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
            "generic",
            "$FRAMEWORK_A",
        )
        errors = project_contract_sync.entrypoint_resolution_errors(
            Path("."),
            entrypoint_name,
            entrypoint,
            expected_framework_reference="$FRAMEWORK_B",
        )

        self.assertTrue(
            any(
                "does not match AGENT_PROJECT.md Framework reference" in error
                for error in errors
            ),
            errors,
        )

    def test_project_contract_sync_validates_marker_owned_authority_load_directives(self) -> None:
        contract_root_ref = ".mpa/contracts"

        def directive_line(text: str, target: str) -> str:
            candidates = [
                line
                for line in text.splitlines()
                if target in line
                and (line.startswith("Read ") or line.startswith("@"))
            ]
            self.assertEqual(1, len(candidates), candidates)
            return candidates[0]

        for runtime in ("generic", "codex", "claude-code"):
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                runtime,
                "$FRAMEWORK",
                contract_root_ref=contract_root_ref,
            )
            charter_line = directive_line(entrypoint, "operative_charter.md")
            contract_line = directive_line(entrypoint, "AGENT_PROJECT.md")
            unavailable_line = next(
                line
                for line in entrypoint.splitlines()
                if line == integration_registry.FRAMEWORK_UNAVAILABLE_CLAUSE
            )
            mutations = {
                "charter-bak": entrypoint.replace(
                    charter_line,
                    charter_line.replace(
                        "operative_charter.md",
                        "operative_charter.md.bak",
                    ),
                    1,
                ),
                "contract-bak": entrypoint.replace(
                    contract_line,
                    contract_line.replace("AGENT_PROJECT.md", "AGENT_PROJECT.md.bak"),
                    1,
                ),
                "charter-explanatory-only": entrypoint.replace(
                    charter_line,
                    "The configured framework documentation mentions "
                    "`$FRAMEWORK/runtime/operative_charter.md`.",
                    1,
                ),
                "contract-explanatory-only": entrypoint.replace(
                    contract_line,
                    "The selected contract is described as "
                    "`.mpa/contracts/AGENT_PROJECT.md`.",
                    1,
                ),
                "charter-fenced-example": entrypoint.replace(
                    charter_line,
                    f"```text\n{charter_line}\n```",
                    1,
                ),
                "contract-fenced-example": entrypoint.replace(
                    contract_line,
                    f"```text\n{contract_line}\n```",
                    1,
                ),
                "charter-commented-example": entrypoint.replace(
                    charter_line,
                    f"<!--\n{charter_line}\n-->",
                    1,
                ),
                "contract-commented-example": entrypoint.replace(
                    contract_line,
                    f"<!--\n{contract_line}\n-->",
                    1,
                ),
                "missing-framework-unavailable-clause": entrypoint.replace(
                    unavailable_line + "\n",
                    "",
                    1,
                ),
            }
            decoy_line = charter_line.replace(
                "operative_charter.md",
                "operative_charter.md.bak",
            )
            for order, replacement in (
                ("before", f"{decoy_line}\n{charter_line}"),
                ("after", f"{charter_line}\n{decoy_line}"),
            ):
                mutations[f"charter-decoy-{order}"] = entrypoint.replace(
                    charter_line,
                    replacement,
                    1,
                )
            contract_decoy_line = contract_line.replace(
                "AGENT_PROJECT.md",
                "AGENT_PROJECT.md.bak",
            )
            for order, replacement in (
                ("before", f"{contract_decoy_line}\n{contract_line}"),
                ("after", f"{contract_line}\n{contract_decoy_line}"),
            ):
                mutations[f"contract-decoy-{order}"] = entrypoint.replace(
                    contract_line,
                    replacement,
                    1,
                )
            mutations["charter-outside-owner-block"] = entrypoint.replace(
                charter_line + "\n",
                "",
                1,
            ).replace(
                integration_registry.PROJECT_CONTRACT_MARKER,
                f"{charter_line}\n{integration_registry.PROJECT_CONTRACT_MARKER}",
                1,
            )
            mutations["contract-outside-owner-block"] = entrypoint.replace(
                contract_line + "\n",
                "",
                1,
            ).replace(
                integration_registry.STATE_LOADING_MARKER,
                f"{contract_line}\n{integration_registry.STATE_LOADING_MARKER}",
                1,
            )

            for mutation, candidate in mutations.items():
                with self.subTest(
                    runtime=runtime,
                    branch="incompatible-format",
                    mutation=mutation,
                ):
                    errors = project_contract_sync.entrypoint_stable_resolution_errors(
                        Path("."),
                        entrypoint_name,
                        candidate,
                        contract_root_ref=contract_root_ref,
                    )
                    self.assertTrue(
                        any("authority-load" in error for error in errors),
                        errors,
                    )

            if runtime == "generic":
                with self.subTest(
                    runtime=runtime,
                    branch="current-delegate",
                    mutation="charter-bak",
                ):
                    errors = project_contract_sync.entrypoint_resolution_errors(
                        Path("."),
                        entrypoint_name,
                        mutations["charter-bak"],
                        contract_root_ref=contract_root_ref,
                        expected_framework_reference="$FRAMEWORK",
                    )
                    self.assertTrue(
                        any("authority-load" in error for error in errors),
                        errors,
                    )

    def test_project_contract_sync_structural_parser_accepts_root_framework_reference(self) -> None:
        for runtime in ("generic", "codex", "claude-code"):
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                runtime,
                "/",
                contract_root_ref="contracts",
            )
            with self.subTest(runtime=runtime):
                reference, errors = (
                    integration_registry.entrypoint_authority_load_references(
                        entrypoint_name,
                        entrypoint,
                        contract_root_ref="contracts",
                    )
                )
                self.assertEqual([], errors)
                self.assertEqual("/", reference)

    def test_project_contract_sync_incompatible_format_retains_structural_entrypoint_checks(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        older_marker = project_contract_model.contract_format_marker(
            project_contract_model.CONTRACT_FORMAT_VERSION - 1
        )

        for runtime in ("generic", "codex", "claude-code"):
            def mutate(
                root: Path,
                outputs: dict[str, str],
            ) -> None:
                for name in ("STATEMENT_OF_WORK.md", "AGENT_PROJECT.md"):
                    (root / name).write_text(
                        outputs[name].replace(
                            project_contract_model.CONTRACT_FORMAT_MARKER,
                            older_marker,
                            1,
                        ),
                        encoding="utf-8",
                    )
                entrypoint_name = "CLAUDE.md" if runtime == "claude-code" else "AGENTS.md"
                entrypoint = outputs[entrypoint_name].replace(
                    "/runtime/operative_charter.md",
                    "/runtime/operative_charter.md.bak",
                    1,
                )
                (root / entrypoint_name).write_text(entrypoint, encoding="utf-8")

            with self.subTest(runtime=runtime):
                with render_fixture(
                    answers,
                    runtime=runtime,
                    mutation=mutate,
                ) as (_root, _outputs, result):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    errors = json.loads(result.stdout)["errors"]
                self.assertTrue(
                    any(
                        "current-only" in error and "manual update" in error
                        for error in errors
                    ),
                    errors,
                )
                self.assertTrue(
                    any("framework authority-load directive" in error for error in errors),
                    errors,
                )

    def test_project_contract_sync_rejects_deleted_or_wrong_root_state_rules_for_every_runtime(self) -> None:
        contract_root_ref = ".mpa/contracts"
        expected_contract = f"{contract_root_ref}/AGENT_PROJECT.md"
        expected_root_fragment = (
            f"directory containing the rendered `{expected_contract}`"
        )
        for runtime in ("generic", "codex", "claude-code"):
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                runtime,
                "$FRAMEWORK",
                contract_root_ref=contract_root_ref,
            )
            with self.subTest(runtime=runtime, mutation="valid"):
                self.assertEqual(
                    [],
                    project_contract_sync.entrypoint_resolution_errors(
                        Path("."),
                        entrypoint_name,
                        entrypoint,
                        contract_root_ref=contract_root_ref,
                    ),
                )

            mutations = (
                (
                    "deleted-article-pointer",
                    entrypoint.replace("Article 5", ""),
                    "does not retain the Article 5 project-state pointer",
                ),
                (
                    "wrong-contract-root",
                    entrypoint.replace(
                        expected_root_fragment,
                        "directory containing the rendered `wrong/AGENT_PROJECT.md`",
                    ),
                    "does not resolve bare project-state filenames relative to the selected contract directory",
                ),
            )
            for mutation, candidate, expected_error in mutations:
                with self.subTest(runtime=runtime, mutation=mutation):
                    self.assertNotEqual(entrypoint, candidate)
                    errors = project_contract_sync.entrypoint_resolution_errors(
                        Path("."),
                        entrypoint_name,
                        candidate,
                        contract_root_ref=contract_root_ref,
                    )
                    self.assertTrue(
                        any(expected_error in error for error in errors),
                        errors,
                    )

    def test_project_bootstrap_minimal_contract_rewrites_deferred_runtime_values(self) -> None:
        contract = project_bootstrap.render_project_contract(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "tech_stack": "To be confirmed by repository inspection or User answer.",
                "language_runtime_standards": "To be confirmed before full bootstrap.",
                "commands": {},
            }
        )

        self.assertIn("deferred by minimal bootstrap; inspect the repository", contract)
        self.assertIn("deferred by minimal bootstrap; inspect the repository or ask before architecture-specific work", contract)
        self.assertIn("deferred by minimal bootstrap; verify before version-specific work", contract)
        self.assertIn("## Minimal Bootstrap Deferrals", contract)
        self.assertIn("Owner: User", contract)
        self.assertIn("Closure Boundary: before the first task that depends on Tech stack", contract)
        self.assertIn(project_contract_model.DEFAULT_PERSISTENT_MEMORY_BOUNDARY, contract)
        self.assertNotIn("- Memory Boundary:", contract)
        self.assertIn("## Memory Boundary", contract)
        self.assertNotIn("To be confirmed", contract)
        self.assertNotIn("TBD", contract)

    def test_project_bootstrap_minimal_omitted_command_is_deferred(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        self.assertEqual(
            project_contract_model.MINIMAL_COMMAND_DEFERRAL,
            project_bootstrap.command_values(answers)["Test Command"],
        )
        self.assertTrue(
            any(
                line.startswith("Field: Test Command —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        self.assertTrue(
            any(
                line.startswith("Field: Recitals —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            result,
        ):
            self.assertIn(
                project_contract_model.MINIMAL_RECITALS_DEFERRAL,
                outputs["STATEMENT_OF_WORK.md"],
            )
            self.assertNotIn("\nTBD\n", outputs["STATEMENT_OF_WORK.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_bootstrap_minimal_concrete_recitals_resolve_purpose_deferral(
        self,
    ) -> None:
        purpose = "Demo produces bounded, reviewable project reports."
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "recitals": [purpose],
        }

        self.assertFalse(
            any(
                line.startswith("Field: Recitals —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            result,
        ):
            self.assertIn(purpose, outputs["STATEMENT_OF_WORK.md"])
            self.assertNotIn(
                project_contract_model.MINIMAL_RECITALS_DEFERRAL,
                outputs["STATEMENT_OF_WORK.md"],
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_contract_sync_rejects_bare_minimal_recitals_placeholder(
        self,
    ) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        def replace_structured_purpose(
            root: Path,
            outputs: dict[str, str],
        ) -> None:
            sow = outputs["STATEMENT_OF_WORK.md"].replace(
                project_contract_model.MINIMAL_RECITALS_DEFERRAL,
                "TBD",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

        with render_fixture(answers, mutation=replace_structured_purpose) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "minimal bootstrap must use the structured Recitals deferral",
                result.stdout,
            )

    def test_project_bootstrap_minimal_placeholder_command_is_rejected_and_deferred(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "commands": {"test": "TBD"},
        }

        self.assertIn(
            "commands key 'test' must be omitted in minimal mode when it is deferred; the structured deferral records the gap",
            project_bootstrap.validate_answers(answers),
        )
        self.assertEqual(
            project_contract_model.MINIMAL_COMMAND_DEFERRAL,
            project_bootstrap.command_values(answers)["Test Command"],
        )
        self.assertTrue(
            any(
                line.startswith("Field: Test Command —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            result,
        ):
            self.assertNotIn("TBD", outputs["AGENT_PROJECT.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_bootstrap_minimal_concrete_command_is_not_deferred(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "commands": {"test": "uv run python -B -m unittest"},
        }

        self.assertEqual(
            "uv run python -B -m unittest",
            project_bootstrap.command_values(answers)["Test Command"],
        )
        self.assertFalse(
            any(
                line.startswith("Field: Test Command —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_bootstrap_minimal_explicit_none_command_is_not_deferred(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "commands": {"test": "none"},
        }

        self.assertEqual(
            "none",
            project_bootstrap.command_values(answers)["Test Command"],
        )
        self.assertFalse(
            any(
                line.startswith("Field: Test Command —")
                for line in project_bootstrap.minimal_deferrals(answers)
            )
        )
        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            result,
        ):
            self.assertIn("- Test: none", outputs["AGENT_PROJECT.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_bootstrap_rejects_deferrals_for_resolved_canonical_fields(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "recitals": ["Demo produces bounded project reports."],
            "tech_stack": "Python CLI",
            "commands": {"test": "none"},
            "minimal_deferrals": [
                {
                    "field": "Recitals",
                    "owner": "User",
                    "reason": "project purpose was not confirmed",
                    "boundary_type": "event",
                    "closure_boundary": "before purpose-dependent work",
                },
                {
                    "field": "Tech stack",
                    "owner": "User",
                    "reason": "repository not inspected yet",
                    "boundary_type": "event",
                    "closure_boundary": "before stack-specific implementation",
                },
                {
                    "field": "Test Command",
                    "owner": "User",
                    "reason": "test posture not inspected yet",
                    "boundary_type": "event",
                    "closure_boundary": "before test-dependent work",
                },
            ],
        }

        errors = project_bootstrap.validate_answers(answers)

        self.assertIn(
            "minimal_deferrals item 1 defers resolved canonical field: Recitals",
            errors,
        )
        self.assertIn(
            "minimal_deferrals item 2 defers resolved canonical field: Tech stack",
            errors,
        )
        self.assertIn(
            "minimal_deferrals item 3 defers resolved canonical field: Test Command",
            errors,
        )

    def test_project_contract_sync_rejects_rendered_resolved_minimal_deferrals(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "tech_stack": "Python CLI",
            "commands": {"test": "none"},
            "minimal_deferrals": [
                {
                    "field": "Tech stack",
                    "owner": "User",
                    "reason": "repository not inspected yet",
                    "boundary_type": "event",
                    "closure_boundary": "before stack-specific implementation",
                },
                {
                    "field": "Test Command",
                    "owner": "User",
                    "reason": "test posture not inspected yet",
                    "boundary_type": "event",
                    "closure_boundary": "before test-dependent work",
                },
            ],
        }

        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            _outputs,
            result,
        ):
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "Minimal Bootstrap Deferrals contains resolved canonical field: Tech stack",
                result.stdout,
            )
            self.assertIn(
                "Minimal Bootstrap Deferrals contains resolved canonical field: Test Command",
                result.stdout,
            )

    def test_project_bootstrap_merges_explicit_minimal_deferrals(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                "minimal_deferrals": [
                    {
                        "field": "Tech stack",
                        "owner": "User",
                        "reason": "repository not inspected yet",
                        "boundary_type": "event",
                        "closure_boundary": "before stack-specific implementation",
                    }
                ],
            }
        )
        self.assertEqual([], errors)

        contract = project_bootstrap.render_project_contract(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "minimal_deferrals": [
                    {
                        "field": "Tech stack",
                        "owner": "User",
                        "reason": "repository not inspected yet",
                        "boundary_type": "event",
                        "closure_boundary": "before stack-specific implementation",
                    }
                ],
            }
        )

        self.assertIn("Reason: repository not inspected yet", contract)
        self.assertIn("Field: Language/Runtime Standards", contract)
        self.assertIn("Field: Test Command", contract)

    def test_project_bootstrap_defers_placeholder_deliverables(self) -> None:
        contract = project_bootstrap.render_project_contract(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "deliverables": [
                    {
                        "description": "Feature shell",
                        "test": "TBD",
                        "pass_criteria": "TBD",
                    }
                ],
            }
        )

        self.assertIn("Field: Deliverables and Acceptance Evidence", contract)

    def test_project_bootstrap_canonicalizes_partial_minimal_scopes_and_syncs_exactly(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "in_scope": ["Known item", "To be confirmed..."],
            "out_of_scope": ["TBD"],
        }
        in_scope_deferral = project_contract_sync.MINIMAL_RUNTIME_DEFERRALS["In scope"]
        out_scope_deferral = project_contract_sync.MINIMAL_RUNTIME_DEFERRALS["Out of scope"]

        with render_fixture(
            answers,
            flags=("--strict-warnings",),
        ) as (root, outputs, valid):
            contract = outputs["AGENT_PROJECT.md"]
            self.assertIn("In scope:\n- Known item\n- " + in_scope_deferral, contract)
            self.assertIn("Out of scope:\n- " + out_scope_deferral, contract)
            self.assertNotIn("TBD", contract)
            self.assertNotIn("To be confirmed", contract)
            self.assertIn("Field: In scope — Owner: User", contract)
            self.assertIn("Field: Out of scope — Owner: User", contract)
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
            (root / "AGENT_PROJECT.md").write_text(
                contract.replace(in_scope_deferral, in_scope_deferral + "; altered", 1),
                encoding="utf-8",
            )
            invalid = run_sync(root)

        self.assertNotEqual(0, invalid.returncode)
        self.assertIn("In scope drift", invalid.stdout)

    def test_project_bootstrap_canonicalizes_partial_minimal_deliverable_and_syncs_exactly(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "deliverables": [
                {
                    "description": "Feature shell",
                    "test": "TBD",
                    "pass_criteria": "To be confirmed",
                }
            ],
        }
        canonical = " — ".join(
            (
                "Feature shell",
                project_contract_model.MINIMAL_DELIVERABLE_TEST,
                project_contract_model.MINIMAL_DELIVERABLE_PASS_CRITERIA,
            )
        )

        with render_fixture(
            answers,
            flags=("--strict-warnings",),
        ) as (root, outputs, valid):
            contract = outputs["AGENT_PROJECT.md"]
            self.assertIn("1. " + canonical, contract)
            self.assertNotIn("TBD", contract)
            self.assertNotIn("To be confirmed", contract)
            self.assertIn(
                "Field: Deliverables and Acceptance Evidence — Owner: User",
                contract,
            )
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
            (root / "AGENT_PROJECT.md").write_text(
                contract.replace(
                    project_contract_model.MINIMAL_DELIVERABLE_TEST,
                    project_contract_model.MINIMAL_DELIVERABLE_TEST + "; altered",
                    1,
                ),
                encoding="utf-8",
            )
            invalid = run_sync(root)

        self.assertNotEqual(0, invalid.returncode)
        self.assertIn("Active Deliverables drift", invalid.stdout)

    def test_project_bootstrap_rejects_placeholder_operational_content(self) -> None:
        errors = project_bootstrap.validate_answers(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "project_name": "Demo",
                "workflows": [{"name": "", "when": "TBD", "sequence": "To be confirmed"}],
                "command_restrictions": [
                    {"command": "", "reason": "TBD", "alternative": "To be confirmed"}
                ],
                "auxiliary_tools": [
                    {"name": "", "purpose": "TBD", "docs": "docs/tool.md"}
                ],
                "constraints": ["TBD"],
                "decision_authority_grant": "To be confirmed",
                "commands": {"test": "TBD"},
            }
        )

        self.assertTrue(any("workflow" in error and "must be concrete" in error for error in errors), errors)
        self.assertTrue(any("command restriction" in error and "must be concrete" in error for error in errors), errors)
        self.assertTrue(any("auxiliary tool" in error and "must be concrete" in error for error in errors), errors)
        self.assertTrue(
            any("operative runtime content" in error and "must not be placeholder text" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("commands key 'test' must be omitted in minimal mode when it is deferred" in error for error in errors),
            errors,
        )

    def test_shared_deferred_value_classification_matches_raw_and_rendered_validation(
        self,
    ) -> None:
        raw_error = (
            "bootstrap answer key 'critical_surface_policy' is operative runtime "
            "content and must not be placeholder text"
        )
        rendered_error = (
            "STATEMENT_OF_WORK.md full bootstrap requires concrete Recitals"
        )

        for value, expected in DEFERRED_VALUE_CLASSIFICATION_CASES:
            with self.subTest(value=value):
                raw_errors = project_bootstrap.validate_answers(
                    {
                        "bootstrap_mode": "minimal",
                        "agent": "Agent",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                        "project_name": "Demo",
                        "critical_surface_policy": value,
                    }
                )
                rendered_errors = project_contract_sync.full_mode_semantic_errors(
                    {"Recitals": [value]},
                    {},
                    {},
                    {},
                    {},
                    check_definitions=False,
                    check_technical_specs=False,
                    check_scope=False,
                    check_commands=False,
                )

                self.assertEqual(expected, raw_error in raw_errors, raw_errors)
                self.assertEqual(
                    expected,
                    rendered_error in rendered_errors,
                    rendered_errors,
                )

    def test_project_bootstrap_example_source_freshness_matches_default(self) -> None:
        example = json.loads((REPO_ROOT / "examples" / "project_bootstrap_answers.example.json").read_text(encoding="utf-8"))

        self.assertEqual(
            project_contract_model.DEFAULT_SOURCE_FRESHNESS_POLICY,
            example["source_freshness_policy"],
        )

    def test_project_contract_sync_accepts_minimal_runtime_deferral_projection(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "tech_stack": "To be confirmed by repository inspection or User answer.",
            "language_runtime_standards": "To be confirmed before full bootstrap.",
            "commands": {},
        }
        with render_fixture(
            answers,
            flags=("--strict-warnings",),
        ) as (_root, _outputs, result):
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_contract_sync_rejects_project_identity_and_date_drift(self) -> None:
        outputs = project_bootstrap.render_output_files(
            {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "date": "2026-07-13",
                "project_name": "Demo",
                "commands": {},
            },
            "generic",
            "$FRAMEWORK",
        )
        sow_text = outputs["STATEMENT_OF_WORK.md"].replace(
            "Statement of Work — Demo",
            "Statement of Work — Other Project",
            1,
        )
        contract_text = outputs["AGENT_PROJECT.md"].replace(
            "Date: 2026-07-13",
            "Date: 2026-07-14",
            1,
        )

        errors = project_contract_sync.preamble_identity_errors(sow_text, contract_text)

        self.assertTrue(any("project identity mismatch" in error for error in errors), errors)
        self.assertTrue(any("project date mismatch" in error for error in errors), errors)

    def test_project_contract_sync_preamble_identity_rows_cannot_move_to_body_or_duplicate(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "date": "2026-07-13",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        outputs = project_bootstrap.render_output_files(
            answers,
            "generic",
            "$FRAMEWORK",
        )
        sow = outputs["STATEMENT_OF_WORK.md"]
        runtime = outputs["AGENT_PROJECT.md"]
        sow_version = next(
            line for line in sow.splitlines() if line.startswith("SOW Version:")
        )
        identity_rows = (
            ("sow-title", "sow", "Statement of Work — Demo"),
            ("sow-version", "sow", sow_version),
            ("runtime-title", "runtime", "# Runtime Project Contract"),
            ("runtime-project", "runtime", "Project: Demo"),
            ("runtime-date", "runtime", "Date: 2026-07-13"),
        )

        def move_to_body(text: str, row: str) -> str:
            candidate = text.replace(row + "\n", "", 1)
            self.assertNotEqual(text, candidate)
            return candidate.rstrip() + "\n\n" + row + "\n"

        for label, surface, row in identity_rows:
            for mutation in ("moved", "body-decoy"):
                with self.subTest(row=label, mutation=mutation):
                    source = sow if surface == "sow" else runtime
                    candidate = (
                        move_to_body(source, row)
                        if mutation == "moved"
                        else source.rstrip() + "\n\n" + row + "\n"
                    )
                    errors = project_contract_sync.preamble_identity_errors(
                        candidate if surface == "sow" else sow,
                        candidate if surface == "runtime" else runtime,
                    )
                    self.assertTrue(
                        any("preamble" in error for error in errors),
                        errors,
                    )

        marker = project_contract_model.CONTRACT_FORMAT_MARKER
        for surface, source in (("sow", sow), ("runtime", runtime)):
            moved = move_to_body(source, marker)
            with self.subTest(surface=surface, row="marker"):
                errors = project_contract_sync.contract_format_update_errors(
                    moved if surface == "sow" else sow,
                    moved if surface == "runtime" else runtime,
                )
                self.assertEqual(1, len(errors), errors)
                self.assertIn("marker is malformed", errors[0])

    def test_project_contract_sync_requires_one_exact_runtime_authority_row(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "date": "2026-07-13",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        outputs = project_bootstrap.render_output_files(
            answers,
            "generic",
            "$FRAMEWORK",
        )
        authority = project_contract_model.PROJECT_AUTHORITY_TEXT
        reversed_authority = (
            "Authority: This is an independent authority even though it is a generated "
            "projection and the SOW governs conflicts; it is not independent authority "
            "only when convenient."
        )
        mutations = {
            "reversal-with-keywords": outputs["AGENT_PROJECT.md"].replace(
                authority,
                reversed_authority,
                1,
            ),
            "duplicate": outputs["AGENT_PROJECT.md"].replace(
                authority,
                authority + "\n" + authority,
                1,
            ),
            "body-decoy": outputs["AGENT_PROJECT.md"].replace(
                authority + "\n",
                "",
                1,
            ).rstrip()
            + "\n\n"
            + authority
            + "\n",
        }

        for label, candidate in mutations.items():
            def mutate(
                root: Path,
                rendered: dict[str, str],
                value: str = candidate,
            ) -> None:
                (root / "AGENT_PROJECT.md").write_text(value, encoding="utf-8")

            with self.subTest(mutation=label):
                with render_fixture(answers, mutation=mutate) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertTrue(
                        "Authority row" in result.stdout
                        or "preamble must contain" in result.stdout,
                        result.stdout,
                    )

    def test_project_contract_sync_bounds_incompatible_format_diagnostics(self) -> None:
        marker = project_contract_model.CONTRACT_FORMAT_MARKER
        current = project_contract_model.CONTRACT_FORMAT_VERSION
        older = project_contract_model.contract_format_marker(current - 1)
        future = project_contract_model.contract_format_marker(current + 1)
        oversized = (
            "<!-- mpa-project-contract-format: " + ("9" * 5000) + " -->"
        )
        cases = {
            "missing": ("", "", "marker is missing"),
            "malformed": (
                "<!-- mpa-project-contract-format: current -->",
                "<!-- mpa-project-contract-format: current -->",
                "marker is malformed",
            ),
            "mismatched": (marker, future, "contract markers disagree"),
            "older": (older, older, "both files use older format"),
            "future": (future, future, "both files use future format"),
            "duplicate": (
                f"{marker}\n{marker}",
                marker,
                "marker is malformed (2 marker candidates)",
            ),
            "oversized": (
                oversized,
                oversized,
                "marker exceeds the bounded version length",
            ),
        }
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        for label, (sow_replacement, contract_replacement, expected) in cases.items():
            def mutate(
                root: Path,
                outputs: dict[str, str],
                sow_value: str = sow_replacement,
                contract_value: str = contract_replacement,
            ) -> None:
                for name, replacement in (
                    ("STATEMENT_OF_WORK.md", sow_value),
                    ("AGENT_PROJECT.md", contract_value),
                ):
                    content = outputs[name].replace(marker, replacement, 1)
                    if name == "STATEMENT_OF_WORK.md":
                        content += "\nexample_STATE.md\n"
                    (root / name).write_text(
                        content,
                        encoding="utf-8",
                    )
                stale_entrypoint = re.sub(
                    r"<project-state>.*?</project-state>",
                    "<project-state>\nLoad state from an unsupported prior contract.\n</project-state>",
                    outputs["AGENTS.md"],
                    flags=re.DOTALL,
                )
                (root / "AGENTS.md").write_text(
                    stale_entrypoint,
                    encoding="utf-8",
                )

            with self.subTest(case=label):
                with render_fixture(answers, mutation=mutate) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)

                self.assertEqual([], payload["warnings"])
                if label == "future":
                    format_errors = [
                        error
                        for error in payload["errors"]
                        if "Use a framework checkout that supports contract format"
                        in error
                    ]
                    self.assertEqual(1, len(format_errors), payload)
                    self.assertIn(expected, format_errors[0])
                    self.assertIn(
                        "does not interpret newer contract formats",
                        format_errors[0],
                    )
                    self.assertNotIn("manual update", format_errors[0])
                else:
                    format_errors = [
                        error
                        for error in payload["errors"]
                        if "current-only" in error and "manual update" in error
                    ]
                    self.assertEqual(1, len(format_errors), payload)
                    self.assertIn(expected, format_errors[0])
                    self.assertIn(
                        "does not parse or rewrite other contract formats",
                        format_errors[0],
                    )
                self.assertIn(
                    "STATEMENT_OF_WORK.md contains an internal local-state filename reference",
                    payload["errors"],
                )
                self.assertFalse(
                    any("missing required section" in error for error in payload["errors"]),
                    payload,
                )
                self.assertFalse(
                    any(
                        "Article 5" in error or "bare project-state filename" in error
                        for error in payload["errors"]
                    ),
                    payload,
                )

    def test_project_contract_sync_rejects_impossible_matching_dates(self) -> None:
        sow = (
            "Statement of Work — Demo\n\n"
            "SOW Version: 1.0.0  MSA Reference: master_service_agreement.md v1  Date: 2026-99-99\n"
        )
        contract = "# Runtime Project Contract\n\nProject: Demo\nDate: 2026-99-99\n"

        errors = project_contract_sync.preamble_identity_errors(sow, contract)

        self.assertIn(
            "STATEMENT_OF_WORK.md date is not a valid ISO calendar date: 2026-99-99",
            errors,
        )
        self.assertIn(
            "AGENT_PROJECT.md date is not a valid ISO calendar date: 2026-99-99",
            errors,
        )

    def test_project_contract_sync_rejects_deleted_minimal_deferral_sections(self) -> None:
        def blank_section(text: str, start: str, end: str) -> str:
            start_index = text.index(start) + len(start)
            end_index = text.index(end, start_index)
            return text[:start_index] + "\n" + text[end_index:]

        def blank_markdown_section(text: str, heading: str) -> str:
            start_index = text.index(heading) + len(heading)
            end_index = text.find("\n## ", start_index)
            if end_index == -1:
                end_index = len(text)
            return text[:start_index] + "\n" + text[end_index:]

        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "tech_stack": "To be confirmed by repository inspection or User answer.",
            "language_runtime_standards": "To be confirmed before full bootstrap.",
            "commands": {},
        }

        def remove_deferred_sections(root: Path, outputs: dict[str, str]) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                blank_section(
                    outputs["STATEMENT_OF_WORK.md"],
                    "Minimal Bootstrap Deferrals\n",
                    "\nTechnical Specifications",
                ),
                encoding="utf-8",
            )
            (root / "AGENT_PROJECT.md").write_text(
                blank_markdown_section(
                    outputs["AGENT_PROJECT.md"],
                    "## Minimal Bootstrap Deferrals\n",
                ),
                encoding="utf-8",
            )

        with render_fixture(
            answers,
            flags=("--strict-warnings",),
            mutation=remove_deferred_sections,
        ) as (_root, _outputs, result):
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("Minimal Bootstrap Deferrals missing required deferred field: Tech stack", result.stdout)
            self.assertIn("Minimal Bootstrap Deferrals missing required deferred field: Test Command", result.stdout)
            self.assertIn(
                "Minimal Bootstrap Deferrals missing required deferred field: Deliverables and Acceptance Evidence",
                result.stdout,
            )

    def test_project_contract_sync_rejects_deleted_placeholder_deliverable_deferral(self) -> None:
        def blank_section(text: str, start: str, end: str) -> str:
            start_index = text.index(start) + len(start)
            end_index = text.index(end, start_index)
            return text[:start_index] + "\n" + text[end_index:]

        def blank_markdown_section(text: str, heading: str) -> str:
            start_index = text.index(heading) + len(heading)
            end_index = text.find("\n## ", start_index)
            if end_index == -1:
                end_index = len(text)
            return text[:start_index] + "\n" + text[end_index:]

        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "deliverables": [
                {
                    "description": "Feature shell",
                    "test": "TBD",
                    "pass_criteria": "TBD",
                }
            ],
        }

        def remove_deliverable_deferral(
            root: Path,
            outputs: dict[str, str],
        ) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                blank_section(
                    outputs["STATEMENT_OF_WORK.md"],
                    "Minimal Bootstrap Deferrals\n",
                    "\nTechnical Specifications",
                ),
                encoding="utf-8",
            )
            (root / "AGENT_PROJECT.md").write_text(
                blank_markdown_section(
                    outputs["AGENT_PROJECT.md"],
                    "## Minimal Bootstrap Deferrals\n",
                ),
                encoding="utf-8",
            )

        with render_fixture(
            answers,
            flags=("--strict-warnings",),
            mutation=remove_deliverable_deferral,
        ) as (_root, _outputs, result):
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn(
                "Minimal Bootstrap Deferrals missing required deferred field: Deliverables and Acceptance Evidence",
                result.stdout,
            )

    def test_project_contract_sync_rejects_joint_deletion_across_required_deferrable_surfaces(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        cases: list[
            tuple[
                str,
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
            ]
        ] = [
            (
                "Tech stack",
                ("Tech stack:",),
                (),
                ("- Languages and frameworks:",),
                (),
                (
                    "STATEMENT_OF_WORK.md Technical Specifications missing required key: Tech stack",
                    "AGENT_PROJECT.md Active Stack missing required key: Languages and frameworks",
                ),
            ),
            (
                "Architecture",
                ("Architecture:",),
                (),
                ("- Architecture:",),
                (),
                (
                    "STATEMENT_OF_WORK.md Technical Specifications missing required key: Architecture",
                    "AGENT_PROJECT.md Active Stack missing required key: Architecture",
                ),
            ),
            (
                "Language/Runtime Standards",
                ("Language/Runtime Standards:",),
                (),
                ("- Language/Runtime Standards:",),
                (),
                (
                    "STATEMENT_OF_WORK.md Definitions missing required key: Language/Runtime Standards",
                    "AGENT_PROJECT.md Active Stack missing required key: Language/Runtime Standards",
                ),
            ),
            (
                "Deliverables and Acceptance Evidence",
                (),
                (),
                (),
                (),
                (),
            ),
        ]
        cases.extend(
            (
                spec.deferral_field,
                (),
                (f" — {spec.sow_label}",),
                (f"- {spec.runtime_label}:",),
                (),
                (
                    "STATEMENT_OF_WORK.md Build and Development Commands "
                    f"missing required label: {spec.sow_label}",
                    f"AGENT_PROJECT.md Common Commands missing required key: {spec.runtime_label}",
                ),
            )
            for spec in project_contract_model.COMMAND_SPECS
        )

        def remove_projection_lines(
            text: str,
            *,
            field: str,
            prefixes: tuple[str, ...],
            suffixes: tuple[str, ...],
        ) -> str:
            lines = []
            for line in text.splitlines():
                if f"Field: {field} —" in line:
                    continue
                if any(line.startswith(prefix) for prefix in prefixes):
                    continue
                if any(line.endswith(suffix) for suffix in suffixes):
                    continue
                lines.append(line)
            return "\n".join(lines) + "\n"

        for (
            field,
            sow_prefixes,
            sow_suffixes,
            runtime_prefixes,
            runtime_suffixes,
            expected_errors,
        ) in cases:
            def remove_joint_projection(
                root: Path,
                outputs: dict[str, str],
            ) -> None:
                (root / "STATEMENT_OF_WORK.md").write_text(
                    remove_projection_lines(
                        outputs["STATEMENT_OF_WORK.md"],
                        field=field,
                        prefixes=sow_prefixes,
                        suffixes=sow_suffixes,
                    ),
                    encoding="utf-8",
                )
                (root / "AGENT_PROJECT.md").write_text(
                    remove_projection_lines(
                        outputs["AGENT_PROJECT.md"],
                        field=field,
                        prefixes=runtime_prefixes,
                        suffixes=runtime_suffixes,
                    ),
                    encoding="utf-8",
                )

            with self.subTest(field=field):
                with render_fixture(
                    answers,
                    flags=("--strict-warnings",),
                    mutation=remove_joint_projection,
                ) as (_root, _outputs, result):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(
                        "Minimal Bootstrap Deferrals missing required deferred field: "
                        f"{field}",
                        result.stdout,
                    )
                    for expected_error in expected_errors:
                        self.assertIn(expected_error, result.stdout)

    def test_project_contract_sync_command_deferral_fields_share_command_specs(self) -> None:
        sow_labels = {
            spec.sow_label for spec in project_contract_model.COMMAND_SPECS
        }
        self.assertEqual(
            sow_labels,
            set(project_contract_sync.COMMON_COMMAND_LABELS),
        )
        self.assertEqual(
            sow_labels,
            set(project_contract_sync.COMMAND_DEFERRAL_FIELDS),
        )
        self.assertLessEqual(
            set(project_contract_sync.COMMAND_DEFERRAL_FIELDS.values()),
            project_contract_sync.MINIMAL_DEFERRABLE_FIELDS,
        )

    def test_project_contract_sync_rejects_expired_minimal_deferral_boundary(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        errors = project_contract_sync.minimal_deferral_errors(
            "AGENT_PROJECT.md",
            [
                (
                    f"- Field: Test Command — Owner: User — Reason: not known — "
                    f"Boundary Type: date — Closure Boundary: {yesterday}."
                )
            ],
        )

        self.assertIn("AGENT_PROJECT.md Minimal Bootstrap Deferrals row 1 date boundary has passed", errors)

    def test_project_contract_sync_rejects_malformed_minimal_deferrals(self) -> None:
        errors = project_contract_sync.minimal_deferral_errors(
            "AGENT_PROJECT.md",
            [
                "- Field: Unknown Field — Owner:  — Reason: TBD — Boundary Type: stage — Closure Boundary: soon.",
            ],
        )

        self.assertTrue(any("owner must not be blank" in error for error in errors), errors)
        self.assertTrue(
            any(
                "reason must be concrete, not absent or placeholder text" in error
                for error in errors
            ),
            errors,
        )
        self.assertTrue(any("field is not deferrable" in error for error in errors), errors)
        self.assertTrue(any("boundary_type must be one of" in error for error in errors), errors)

    def test_minimal_deferral_facts_reject_semantic_absence_in_bootstrap_and_sync(self) -> None:
        base_record = {
            "field": "Tech stack",
            "owner": "User",
            "reason": "repository inspection is pending",
            "boundary_type": "event",
            "closure_boundary": "before stack-specific implementation",
        }
        base_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        absent_values = (
            *sorted(project_contract_model.MINIMAL_DEFERRAL_ABSENT_VALUES),
            "[owner]",
            "replace with accountable owner",
            "To be confirmed by repository inspection",
        )
        for key in ("owner", "reason", "closure_boundary"):
            for value in absent_values:
                record = {**base_record, key: value}
                with self.subTest(surface="bootstrap", key=key, value=value):
                    errors = project_bootstrap.validate_answers(
                        {**base_answers, "minimal_deferrals": [record]}
                    )
                    self.assertTrue(
                        any(
                            f"key '{key}' must be concrete, not absent or placeholder text"
                            in error
                            for error in errors
                        ),
                        errors,
                    )
                with self.subTest(surface="sync", key=key, value=value):
                    errors = project_contract_sync.minimal_deferral_errors(
                        "AGENT_PROJECT.md",
                        [f"- {project_bootstrap.minimal_deferral_line(record)}"],
                    )
                    self.assertTrue(
                        any(
                            f"{key} must be concrete, not absent or placeholder text"
                            in error
                            or (value == "" and f"{key} must not be blank" in error)
                            for error in errors
                        ),
                        errors,
                    )

        valid_record = {
            **base_record,
            "reason": (
                "repository inspection found none of the expected metadata, so "
                "owner review is required"
            ),
            "closure_boundary": (
                "when the User confirms none of the optional commands apply"
            ),
        }
        self.assertEqual(
            [],
            project_bootstrap.validate_answers(
                {**base_answers, "minimal_deferrals": [valid_record]}
            ),
        )
        self.assertEqual(
            [],
            project_contract_sync.minimal_deferral_errors(
                "AGENT_PROJECT.md",
                [f"- {project_bootstrap.minimal_deferral_line(valid_record)}"],
            ),
        )

    def test_minimal_deferral_boundaries_require_current_dates_or_named_triggers(self) -> None:
        base_record = {
            "field": "Tech stack",
            "owner": "User",
            "reason": "repository inspection has not run",
        }
        base_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        invalid_cases = (
            ("date", "not-a-date", "date boundary must be ISO YYYY-MM-DD"),
            (
                "date",
                (date.today() - timedelta(days=1)).isoformat(),
                "date boundary has passed",
            ),
            ("event", "soon", "event boundary must name an exact trigger"),
            ("event", "before work", "event boundary trigger is too generic"),
            ("milestone", "later", "milestone boundary must name an exact trigger"),
            (
                "milestone",
                "at next milestone",
                "milestone boundary trigger is too generic",
            ),
        )
        for boundary_type, closure_boundary, expected in invalid_cases:
            record = {
                **base_record,
                "boundary_type": boundary_type,
                "closure_boundary": closure_boundary,
            }
            with self.subTest(
                surface="bootstrap",
                boundary_type=boundary_type,
                closure_boundary=closure_boundary,
            ):
                errors = project_bootstrap.validate_answers(
                    {**base_answers, "minimal_deferrals": [record]}
                )
                self.assertTrue(any(expected in error for error in errors), errors)
            with self.subTest(
                surface="sync",
                boundary_type=boundary_type,
                closure_boundary=closure_boundary,
            ):
                errors = project_contract_sync.minimal_deferral_errors(
                    "AGENT_PROJECT.md",
                    [f"- {project_bootstrap.minimal_deferral_line(record)}"],
                )
                self.assertTrue(any(expected in error for error in errors), errors)

        valid_cases = (
            ("date", date.today().isoformat()),
            ("event", "when repository inspection identifies the active stack"),
            ("milestone", "at full bootstrap completion"),
        )
        for boundary_type, closure_boundary in valid_cases:
            record = {
                **base_record,
                "boundary_type": boundary_type,
                "closure_boundary": closure_boundary,
            }
            with self.subTest(
                surface="bootstrap-valid",
                boundary_type=boundary_type,
            ):
                self.assertEqual(
                    [],
                    project_bootstrap.validate_answers(
                        {**base_answers, "minimal_deferrals": [record]}
                    ),
                )
            with self.subTest(
                surface="sync-valid",
                boundary_type=boundary_type,
            ):
                self.assertEqual(
                    [],
                    project_contract_sync.minimal_deferral_errors(
                        "AGENT_PROJECT.md",
                        [f"- {project_bootstrap.minimal_deferral_line(record)}"],
                    ),
                )

    def test_project_contract_sync_preserves_em_dash_inside_minimal_deferral_value(self) -> None:
        parsed, errors = project_contract_sync.parse_minimal_deferral(
            "AGENT_PROJECT.md",
            1,
            "Field: Test Command — Owner: User — Reason: repository not inspected — command unknown — Boundary Type: event — Closure Boundary: before test-dependent work.",
        )

        self.assertEqual([], errors)
        self.assertIsNotNone(parsed)
        self.assertEqual("repository not inspected — command unknown", parsed["reason"] if parsed else "")

    def test_project_contract_sync_rejects_minimal_deferral_parity_drift(self) -> None:
        sow_records = {
            "Test Command": {
                "field": "Test Command",
                "owner": "User",
                "reason": "minimal bootstrap deferral",
                "boundary_type": "event",
                "closure_boundary": "before test-dependent work",
            }
        }
        contract_records = {
            "Test Command": {
                "field": "Test Command",
                "owner": "Reviewer",
                "reason": "minimal bootstrap deferral",
                "boundary_type": "event",
                "closure_boundary": "before test-dependent work",
            }
        }

        errors = project_contract_sync.minimal_deferral_parity_errors(sow_records, contract_records)

        self.assertIn(
            "Minimal Bootstrap Deferrals drift for Test Command owner: SOW='User' contract='Reviewer'",
            errors,
        )

    def test_project_contract_sync_exact_list_parity_preserves_duplicate_counts(self) -> None:
        self.assertEqual(
            ["Example drift between SOW and project contract"],
            project_contract_sync.exact_list_parity_errors(
                "Example",
                ["same item"],
                ["same item", "same item"],
            ),
        )

    def test_project_contract_sync_rejects_missing_default_memory_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {},
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- " + project_contract_model.DEFAULT_PERSISTENT_MEMORY_BOUNDARY + "\n",
                "",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root, "--strict-warnings")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Memory Boundary drift between SOW and project contract", result.stdout)

    def test_project_contract_sync_enforces_definition_index_owner_semantics(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        mutations = (
            (
                "Memory Boundary",
                (
                    "Memory Boundary: "
                    + project_contract_model.DEFAULT_PERSISTENT_MEMORY_BOUNDARY
                ),
                "Memory Boundary: a contradictory index value",
                "Memory Boundary SOW Definitions index does not exactly match",
            ),
            *(
                (
                    label,
                    f"{label}: {project_contract_model.COMMAND_DEFINITION_POINTER}",
                    f"{label}: run an arbitrary command directly",
                    f"{label} SOW Definitions index must be exactly",
                )
                for label in ("Test Command", "Lint Command", "Type Check Command")
            ),
        )

        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            _outputs,
            valid,
        ):
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)

        for label, owner_row, replacement, expected_error in mutations:
            def mutate(
                root: Path,
                outputs: dict[str, str],
                source: str = owner_row,
                target: str = replacement,
            ) -> None:
                sow = outputs["STATEMENT_OF_WORK.md"].replace(source, target, 1)
                self.assertNotEqual(outputs["STATEMENT_OF_WORK.md"], sow)
                (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

            with self.subTest(definition=label):
                with render_fixture(answers, mutation=mutate) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(expected_error, result.stdout)

    def test_project_contract_sync_requires_generated_projection_authority_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {},
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = "\n".join(
                line for line in contract.splitlines() if not line.startswith("Authority: Generated projection")
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "AGENT_PROJECT.md preamble Authority row occurs 0 times; expected exactly one",
                result.stdout,
            )

    def test_project_contract_sync_requires_generated_projection_loading_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {},
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            generated_rule = project_contract_model.PROJECT_LOADING_RULE_LINES[0]
            self.assertIn(generated_rule, contract)
            contract = contract.replace(
                generated_rule,
                "- Treat this file as a compact runtime summary.",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("AGENT_PROJECT.md Loading Rule drift", result.stdout)

    def test_project_contract_sync_rejects_stack_or_architecture_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "full",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "tech_stack": "Python CLI",
                    "architecture": "single-process command line tool",
                    "in_scope": ["Maintain the CLI"],
                    "language_runtime_standards": "Python 3.14",
                    "out_of_scope": ["Production deployment"],
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- Languages and frameworks: Python CLI",
                "- Languages and frameworks: Rust web service",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            (root / "AGENT_PROJECT.md").write_text(
                outputs["AGENT_PROJECT.md"].replace(
                    "- Architecture: single-process command line tool",
                    "- Architecture: distributed web service",
                ),
                encoding="utf-8",
            )
            architecture_result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Tech stack drift", result.stdout)
            self.assertNotEqual(0, architecture_result.returncode)
            self.assertIn("Architecture drift", architecture_result.stdout)

    def test_project_contract_sync_rejects_unbacked_key_stack_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "key_dependencies": ["SQLite"],
                    "key_directories": ["src"],
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- Key dependencies: SQLite",
                "- Key dependencies: SQLite, unbacked-client",
            ).replace(
                "- Key directories: src",
                "- Key directories: src, unbacked-output",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Key dependencies drift", result.stdout)
            self.assertIn("Key directories drift", result.stdout)

    def test_project_contract_sync_treats_file_structure_as_opaque_to_stack_scalars(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "full",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "recitals": ["Demo is a small reporting command-line tool."],
            "tech_stack": "Python CLI",
            "architecture": "single-process command line tool",
            "key_dependencies": ["SQLite"],
            "key_directories": ["src", "tests"],
            "file_structure": ["src/main.py", "tests/test_main.py"],
            "in_scope": ["Maintain the CLI"],
            "language_runtime_standards": "Python 3.14",
            "out_of_scope": ["Production deployment"],
            "commands": {},
            "deliverables": [
                {
                    "description": "Rendered report",
                    "test": "manual review",
                    "pass_criteria": "the report is accepted",
                }
            ],
        }
        scalar_rows = (
            "Tech stack: Rust service",
            "Architecture: distributed workers",
            "Key dependencies: unbacked-client",
            "Key directories: generated-output",
            "src: first ordinary file label",
            "src: second ordinary file label",
        )

        def append_file_structure_rows(
            root: Path,
            outputs: dict[str, str],
            rows: tuple[str, ...] = scalar_rows,
        ) -> None:
            sow = outputs["STATEMENT_OF_WORK.md"].replace(
                "\nRepresentative Pattern Sources",
                "\n" + "\n".join(rows) + "\n\nRepresentative Pattern Sources",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

        for rows in (scalar_rows, tuple(reversed(scalar_rows))):
            with self.subTest(order=rows):
                with render_fixture(
                    answers,
                    mutation=lambda root, outputs, selected=rows: append_file_structure_rows(
                        root,
                        outputs,
                        selected,
                    ),
                ) as (_root, _outputs, result):
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_contract_sync_file_structure_rows_cannot_override_or_supply_stack_scalars(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "full",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "recitals": ["Demo is a small reporting command-line tool."],
            "tech_stack": "Python CLI",
            "architecture": "single-process command line tool",
            "key_dependencies": ["SQLite"],
            "key_directories": ["src", "tests"],
            "file_structure": ["src/main.py", "tests/test_main.py"],
            "in_scope": ["Maintain the CLI"],
            "language_runtime_standards": "Python 3.14",
            "out_of_scope": ["Production deployment"],
            "commands": {},
            "deliverables": [
                {
                    "description": "Rendered report",
                    "test": "manual review",
                    "pass_criteria": "the report is accepted",
                }
            ],
        }
        cases = (
            ("Tech stack", "Python CLI", "Rust service", "Tech stack drift"),
            (
                "Architecture",
                "single-process command line tool",
                "distributed workers",
                "Architecture drift",
            ),
            ("Key dependencies", "SQLite", "unbacked-client", "Key dependencies drift"),
            ("Key directories", "src, tests", "generated-output", "Key directories drift"),
        )

        for label, canonical, drifted, expected_error in cases:
            def mutate(
                root: Path,
                outputs: dict[str, str],
                *,
                selected_label: str = label,
                selected_canonical: str = canonical,
                selected_drifted: str = drifted,
                remove_owner: bool = False,
            ) -> None:
                owner_row = f"{selected_label}: {selected_canonical}"
                replacement = "" if remove_owner else f"{selected_label}: {selected_drifted}"
                sow = outputs["STATEMENT_OF_WORK.md"].replace(owner_row, replacement, 1)
                sow = sow.replace(
                    "\nRepresentative Pattern Sources",
                    f"\n{owner_row}\n\nRepresentative Pattern Sources",
                    1,
                )
                (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

            for mutation_label, remove_owner in (("override", False), ("supply", True)):
                with self.subTest(field=label, mutation=mutation_label):
                    with render_fixture(
                        answers,
                        mutation=lambda root, outputs, removed=remove_owner: mutate(
                            root,
                            outputs,
                            remove_owner=removed,
                        ),
                    ) as (_root, _outputs, result):
                        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                        self.assertIn(expected_error, result.stdout)

    def test_project_contract_sync_rejects_deliverable_acceptance_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "full",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "tech_stack": "Python CLI",
                    "architecture": "single-process command line tool",
                    "in_scope": ["Render reports"],
                    "language_runtime_standards": "Python 3.14",
                    "out_of_scope": ["Production deployment"],
                    "commands": {"test": "uv run python -m unittest"},
                    "deliverables": [
                        {
                            "description": "Render report",
                            "test": "uv run python -m unittest",
                            "pass_criteria": "all report tests pass",
                        }
                    ],
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "all report tests pass",
                "one smoke test passes",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Active Deliverables drift between SOW and project contract", result.stdout)

    def test_project_contract_sync_preserves_active_deliverable_order(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "full",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "recitals": ["Demo has two ordered delivery milestones."],
            "tech_stack": "Python CLI",
            "architecture": "single-process command line tool",
            "in_scope": ["Deliver both milestones"],
            "language_runtime_standards": "Python 3.14",
            "out_of_scope": ["Production deployment"],
            "commands": {key: "none" for key in project_bootstrap.COMMAND_KEYS},
            "deliverables": [
                {
                    "description": "First milestone",
                    "test": "manual review one",
                    "pass_criteria": "first milestone accepted",
                },
                {
                    "description": "Second milestone",
                    "test": "manual review two",
                    "pass_criteria": "second milestone accepted",
                },
            ],
        }

        with render_fixture(answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            valid,
        ):
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
            runtime = outputs["AGENT_PROJECT.md"]

        first = "1. First milestone — manual review one — first milestone accepted"
        second = "2. Second milestone — manual review two — second milestone accepted"

        def swap_deliverables(root: Path, outputs: dict[str, str]) -> None:
            candidate = outputs["AGENT_PROJECT.md"].replace(
                f"{first}\n{second}",
                (
                    "1. Second milestone — manual review two — second milestone accepted\n"
                    "2. First milestone — manual review one — first milestone accepted"
                ),
                1,
            )
            self.assertNotEqual(outputs["AGENT_PROJECT.md"], candidate)
            (root / "AGENT_PROJECT.md").write_text(candidate, encoding="utf-8")

        self.assertIn(first, runtime)
        self.assertIn(second, runtime)
        with render_fixture(answers, mutation=swap_deliverables) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("Active Deliverables drift", result.stdout)

    def test_project_contract_sync_allows_duplicate_file_structure_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "file_structure": [
                        "src: application code",
                        "src: generated clients",
                    ],
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")

            result = run_sync(root)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_contract_sync_rejects_common_command_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {
                        "dev": "uv run mkdocs serve",
                        "build": "uv run mkdocs build",
                        "test": "uv run pytest",
                    },
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- Development: uv run mkdocs serve",
                "- Development: uv run python wrong.py",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Common Commands Development drift", result.stdout)

    def test_project_contract_sync_preserves_exact_common_command_values(self) -> None:
        cases = (
            ("case", "printf '%s' 'APPROVED'", "printf '%s' 'approved'"),
            (
                "quoted whitespace",
                "printf '%s' 'first  second'",
                "printf '%s' 'first second'",
            ),
            ("literal em dash", "printf '%s' '—'", "printf '%s' '-'"),
        )
        for label, command, changed_command in cases:
            with self.subTest(change=label):
                answers: dict[str, object] = {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "commands": {"test": command},
                }
                self.assertEqual([], project_bootstrap.validate_answers(answers))
                with render_fixture(answers) as (root, _outputs, valid):
                    self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
                    contract_path = root / "AGENT_PROJECT.md"
                    contract_path.write_text(
                        contract_path.read_text(encoding="utf-8").replace(
                            f"- Test: {command}\n",
                            f"- Test: {changed_command}\n",
                            1,
                        ),
                        encoding="utf-8",
                    )
                    changed = run_sync(root)

                self.assertEqual(1, changed.returncode, changed.stdout + changed.stderr)
                self.assertIn("Common Commands Test drift", changed.stdout)

    def test_project_contract_sync_rejects_missing_sow_command_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "commands": {"dev": "none"},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            sow = (root / "STATEMENT_OF_WORK.md").read_text(encoding="utf-8")
            sow = sow.replace("none — Development\n", "")
            (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "STATEMENT_OF_WORK.md Build and Development Commands missing required label: Development",
                result.stdout,
            )

    def test_project_contract_sync_rejects_malformed_or_missing_common_command_rows(
        self,
    ) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "commands": {"deploy": "none"},
        }
        cases = (
            (
                "extra_common_command_row",
                "- Deploy: none",
                "- Deploy: none\n- Package: npm install",
                "AGENT_PROJECT.md Common Commands contains unbacked key: Package",
            ),
            (
                "invalid_common_command_row",
                "- Deploy: none",
                "- Deploy: none\n- Package npm install",
                "AGENT_PROJECT.md Common Commands row must contain ':'",
            ),
            (
                "missing_absent_common_command_row",
                "- Deploy: none\n",
                "",
                "AGENT_PROJECT.md Common Commands missing required key: Deploy",
            ),
        )
        for label, target, replacement, expected_error in cases:
            with self.subTest(case=label):
                def mutate(
                    root: Path,
                    outputs: dict[str, str],
                    *,
                    old: str = target,
                    new: str = replacement,
                ) -> None:
                    (root / "AGENT_PROJECT.md").write_text(
                        outputs["AGENT_PROJECT.md"].replace(old, new),
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=mutate) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(expected_error, result.stdout)

    def test_project_contract_sync_rejects_modified_minimal_runtime_deferral(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "tech_stack": "To be confirmed by repository inspection or User answer.",
                    "language_runtime_standards": "To be confirmed before full bootstrap.",
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- Languages and frameworks: deferred by minimal bootstrap; inspect the repository or ask before stack-specific work",
                "- Languages and frameworks: deferred by minimal bootstrap; inspect the repository or ask before stack-specific work; Python CLI",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Tech stack drift", result.stdout)

    def test_project_contract_sync_requires_exact_minimal_runtime_deferral_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "language_runtime_standards": "To be confirmed before full bootstrap.",
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "- Language/Runtime Standards: deferred by minimal bootstrap; verify before version-specific work",
                "- Language/Runtime Standards: Deferred by minimal bootstrap; verify before version-specific work",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "Language/Runtime Standards in AGENT_PROJECT.md Active Stack "
                "does not exactly match the canonical SOW Definition value",
                result.stdout,
            )

    def test_project_contract_sync_requires_command_and_verification_sections(
        self,
    ) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "commands": {},
        }
        for section in ("Common Commands", "Framework Verification Commands"):
            with self.subTest(section=section):
                def mutate(
                    root: Path,
                    outputs: dict[str, str],
                    *,
                    title: str = section,
                ) -> None:
                    (root / "AGENT_PROJECT.md").write_text(
                        remove_markdown_section(outputs["AGENT_PROJECT.md"], title),
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=mutate) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(
                        f"AGENT_PROJECT.md missing required section: {section}",
                        result.stdout,
                    )

    def test_project_contract_sync_rejects_project_local_framework_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                '"${FRAMEWORK:?FRAMEWORK is required}/scripts/conformance_check.py"',
                "scripts/conformance_check.py",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "must call the framework-owned script through the framework reference, not bare scripts/...",
                result.stdout,
            )

    def test_project_contract_sync_rejects_indented_common_commands_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace("## Common Commands", "    ## Common Commands")
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("AGENT_PROJECT.md missing required section: Common Commands", result.stdout)

    def test_project_contract_sync_rejects_duplicate_sections_and_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {"test": "none"},
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "## Definitions",
                "## Definitions\n\n- Agent: Wrong\n\n## Definitions",
                1,
            )
            contract = contract.replace("- Test: none", "- Test: wrong\n- Test: none")
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("AGENT_PROJECT.md duplicate section: Definitions", result.stdout)
            self.assertIn("AGENT_PROJECT.md Common Commands duplicate key: Test", result.stdout)

    def test_project_contract_sync_reports_each_optional_projection_drift_once(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_framework_feedback": True,
            "include_automation_orders": True,
            "automation_orders": {"jobs": [valid_automation_job()]},
        }
        def remove_feedback(root: Path, _outputs: dict[str, str]) -> None:
            (root / "FRAMEWORK_FEEDBACK.md").unlink()

        def remove_automation_manifest(
            root: Path,
            _outputs: dict[str, str],
        ) -> None:
            (root / "AUTOMATION_ORDERS.json").unlink()

        def drift_automation_manifest(root: Path, outputs: dict[str, str]) -> None:
            payload = json.loads(outputs["AUTOMATION_ORDERS.json"])
            payload["preferred_backend"] = "cron"
            (root / "AUTOMATION_ORDERS.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

        cases = (
            (
                "Framework Feedback File",
                remove_feedback,
                "Framework Feedback File declares FRAMEWORK_FEEDBACK.md, but that project state file is missing",
            ),
            (
                "Automation Orders File",
                drift_automation_manifest,
                "AUTOMATION_ORDERS.json preferred_backend drift",
            ),
            (
                "Automation Orders File missing",
                remove_automation_manifest,
                "Automation Orders File declares AUTOMATION_ORDERS.json, but that project state file is missing",
            ),
        )

        for label, mutation, expected_error in cases:
            with self.subTest(definition=label):
                with render_fixture(
                    answers,
                    mutation=mutation,
                ) as (_root, _outputs, result):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)

                matching = [
                    error for error in payload["errors"] if expected_error in error
                ]
                self.assertEqual(1, len(matching), payload)

    def test_project_contract_sync_models_canonical_automation_owner_edge(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_automation_orders": True,
            "automation_orders": {"jobs": [valid_automation_job()]},
        }

        def drift_sow_definition(root: Path, outputs: dict[str, str]) -> None:
            lines = outputs["STATEMENT_OF_WORK.md"].splitlines()
            in_definitions = False
            for index, line in enumerate(lines):
                if line == "Definitions":
                    in_definitions = True
                    continue
                if in_definitions and line in project_contract_sync.SOW_TITLES:
                    break
                if in_definitions and line == "Automation Orders File: AUTOMATION_ORDERS.json":
                    lines[index] = "Automation Orders File: none"
                    break
            (root / "STATEMENT_OF_WORK.md").write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )

        with render_fixture(answers, mutation=drift_sow_definition) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)

        automation_errors = [
            error
            for error in payload["errors"]
            if "Automation Orders File" in error
        ]
        self.assertEqual(1, len(automation_errors), payload)
        self.assertTrue(
            any(
                "must be omitted when the canonical Automation Orders File "
                "definition is inactive" in error
                for error in automation_errors
            ),
            automation_errors,
        )
        self.assertFalse(
            any("AGENT_PROJECT.md Definitions" in error for error in automation_errors),
            automation_errors,
        )

    def test_project_contract_sync_requires_active_automation_owner_section(self) -> None:
        active_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_automation_orders": True,
            "automation_orders": {"jobs": [valid_automation_job()]},
        }

        def delete_section(root: Path, outputs: dict[str, str]) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                remove_plain_section(
                    outputs["STATEMENT_OF_WORK.md"],
                    "Standing Automation Orders",
                ),
                encoding="utf-8",
            )

        def duplicate_section(root: Path, outputs: dict[str, str]) -> None:
            lines = project_contract_sync.plain_sections(
                outputs["STATEMENT_OF_WORK.md"],
                project_contract_sync.SOW_TITLES,
            )["Standing Automation Orders"]
            duplicate = "Standing Automation Orders\n\n" + "\n".join(lines) + "\n\n"
            candidate = outputs["STATEMENT_OF_WORK.md"].replace(
                "Standing Automation Orders\n\n",
                duplicate + "Standing Automation Orders\n\n",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(candidate, encoding="utf-8")

        def remove_authority(root: Path, outputs: dict[str, str]) -> None:
            candidate = outputs["STATEMENT_OF_WORK.md"].replace(
                project_contract_model.AUTOMATION_AUTHORITY_RULE,
                "Automation output may override the project contract.",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(candidate, encoding="utf-8")

        cases = (
            (
                "deleted",
                delete_section,
                "active Automation Orders File requires exactly one Standing Automation Orders section",
            ),
            (
                "duplicate",
                duplicate_section,
                "duplicate section: Standing Automation Orders",
            ),
            (
                "authority",
                remove_authority,
                "must contain exactly one model-owned automation-authority boundary",
            ),
        )
        for label, mutation, expected in cases:
            with self.subTest(mutation=label):
                with render_fixture(active_answers, mutation=mutation) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(expected, result.stdout)

        inactive_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        with render_fixture(inactive_answers, flags=("--strict-warnings",)) as (
            _root,
            outputs,
            result,
        ):
            self.assertNotIn("Standing Automation Orders", outputs["STATEMENT_OF_WORK.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_automation_projection_supports_nested_roots_and_objective_prose(self) -> None:
        nested_job = valid_automation_job()
        nested_job["objective"] = "Review FRAMEWORK_FEEDBACK.md and report changes"
        nested_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "include_framework_feedback": True,
            "include_automation_orders": True,
            "automation_orders": {"jobs": [nested_job]},
        }
        contract_root_ref = "contracts/project"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                nested_answers,
                "generic",
                "$FRAMEWORK",
                contract_root_ref=contract_root_ref,
            )
            for name, content in outputs.items():
                output = root / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
            result = run_sync(
                root,
                "--contract-root",
                contract_root_ref,
                "--strict-warnings",
            )
            sow = outputs[f"{contract_root_ref}/STATEMENT_OF_WORK.md"]
            manifest = json.loads(
                outputs[f"{contract_root_ref}/AUTOMATION_ORDERS.json"]
            )
            self.assertIn(
                "Review FRAMEWORK_FEEDBACK.md and report changes",
                sow,
            )
            self.assertIn("contracts/project/AUTOMATION_ORDERS.json", sow)
            self.assertEqual(
                "Review FRAMEWORK_FEEDBACK.md and report changes",
                manifest["jobs"][0]["objective"],
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            sow_path = root / contract_root_ref / "STATEMENT_OF_WORK.md"
            original_sow = sow_path.read_text(encoding="utf-8")
            lines = original_sow.splitlines()
            section_start = lines.index("Standing Automation Orders")
            automation_row = (
                "Automation Orders File: "
                f"{contract_root_ref}/AUTOMATION_ORDERS.json"
            )
            row_index = next(
                index
                for index in range(section_start + 1, len(lines))
                if lines[index] == automation_row
            )
            lines[row_index] = automation_row.replace(
                "AUTOMATION_ORDERS.json",
                "automation_orders.json",
            )
            sow_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            case_drift = run_sync(
                root,
                "--contract-root",
                contract_root_ref,
                "--strict-warnings",
            )
            self.assertEqual(1, case_drift.returncode)
            self.assertEqual(
                [
                    "Automation Orders File SOW section -> SOW Definitions drift: "
                    "SOW='contracts/project/automation_orders.json' "
                    "contract='contracts/project/AUTOMATION_ORDERS.json'"
                ],
                json.loads(case_drift.stdout)["errors"],
            )

            sow_path.write_text(original_sow, encoding="utf-8")
            manifest_path = root / contract_root_ref / "AUTOMATION_ORDERS.json"
            manifest_path.rename(manifest_path.with_name("automation_orders.json"))
            spelling_drift = run_sync(
                root,
                "--contract-root",
                contract_root_ref,
                "--strict-warnings",
            )
            self.assertEqual(1, spelling_drift.returncode)
            spelling_errors = json.loads(spelling_drift.stdout)["errors"]
            self.assertEqual(1, len(spelling_errors), spelling_errors)
            self.assertIn("must use exact path spelling", spelling_errors[0])

        delimiter_job = valid_automation_job()
        delimiter_job["objective"] = "Review — report changes"
        delimiter_answers = {
            **nested_answers,
            "include_framework_feedback": False,
            "automation_orders": {"jobs": [delimiter_job]},
        }
        with render_fixture(
            delimiter_answers,
            flags=("--strict-warnings",),
        ) as (_root, outputs, result):
            self.assertIn("Review — report changes", outputs["STATEMENT_OF_WORK.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_inactive_automation_section_and_missing_policy_have_one_root_diagnostic(self) -> None:
        inactive_answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        job = valid_automation_job()
        injected_section = "\n".join(
            (
                "Standing Automation Orders",
                "",
                "Automation Orders File: none",
                "Preferred Scheduler Backend: auto",
                project_contract_model.render_automation_job_summary(job),
                project_contract_model.AUTOMATION_AUTHORITY_RULE,
                "",
            )
        )

        def inject_inactive_section(root: Path, outputs: dict[str, str]) -> None:
            sow = outputs["STATEMENT_OF_WORK.md"].replace(
                "Build and Development Commands\n\n",
                injected_section + "\nBuild and Development Commands\n\n",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

        with render_fixture(
            inactive_answers,
            mutation=inject_inactive_section,
        ) as (_root, _outputs, result):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [
                    "STATEMENT_OF_WORK.md Standing Automation Orders must be "
                    "omitted when the canonical Automation Orders File definition "
                    "is inactive"
                ],
                payload["errors"],
            )

        active_answers = {
            **inactive_answers,
            "include_automation_orders": True,
            "automation_orders": {"jobs": [job]},
        }

        def delete_policy(root: Path, outputs: dict[str, str]) -> None:
            sow = outputs["STATEMENT_OF_WORK.md"].replace(
                project_contract_model.AUTOMATION_AUTHORITY_RULE + "\n",
                "",
                1,
            )
            (root / "STATEMENT_OF_WORK.md").write_text(sow, encoding="utf-8")

        with render_fixture(active_answers, mutation=delete_policy) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [
                    "STATEMENT_OF_WORK.md Standing Automation Orders must contain "
                    "exactly one model-owned automation-authority boundary"
                ],
                payload["errors"],
            )

        def delete_policy_and_drift_backend(
            root: Path,
            outputs: dict[str, str],
        ) -> None:
            delete_policy(root, outputs)
            payload = json.loads(outputs["AUTOMATION_ORDERS.json"])
            payload["preferred_backend"] = "cron"
            (root / "AUTOMATION_ORDERS.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

        with render_fixture(
            active_answers,
            mutation=delete_policy_and_drift_backend,
        ) as (_root, _outputs, result):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [
                    "STATEMENT_OF_WORK.md Standing Automation Orders must contain "
                    "exactly one model-owned automation-authority boundary",
                    "AUTOMATION_ORDERS.json preferred_backend drift: "
                    "SOW='unspecified' contract='cron'",
                ],
                payload["errors"],
            )

    def test_project_contract_sync_duplicate_definition_order_does_not_select_a_mode(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        observed: list[list[str]] = []
        for replacement in (
            "Bootstrap Mode: minimal\nBootstrap Mode: full",
            "Bootstrap Mode: full\nBootstrap Mode: minimal",
        ):
            def duplicate_mode(
                root: Path,
                outputs: dict[str, str],
                rows: str = replacement,
            ) -> None:
                (root / "STATEMENT_OF_WORK.md").write_text(
                    outputs["STATEMENT_OF_WORK.md"].replace(
                        "Bootstrap Mode: minimal",
                        rows,
                        1,
                    ),
                    encoding="utf-8",
                )

            with render_fixture(answers, mutation=duplicate_mode) as (
                _root,
                _outputs,
                result,
            ):
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                observed.append(json.loads(result.stdout)["errors"])

        self.assertEqual(observed[0], observed[1])
        self.assertEqual(
            ["STATEMENT_OF_WORK.md Definitions duplicate key: Bootstrap Mode"],
            observed[0],
        )

    def test_duplicate_arbitration_definition_does_not_drive_review_routing(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        default_row = (
            "Arbitration Panel: "
            + project_contract_model.DEFAULT_ARBITRATION_PANEL_PROJECTION
        )
        custom_row = "Arbitration Panel: two-seat project panel"
        observed: list[list[str]] = []
        for replacement in (
            f"{default_row}\n{custom_row}",
            f"{custom_row}\n{default_row}",
        ):
            def duplicate_panel(
                root: Path,
                outputs: dict[str, str],
                rows: str = replacement,
            ) -> None:
                (root / "STATEMENT_OF_WORK.md").write_text(
                    outputs["STATEMENT_OF_WORK.md"].replace(
                        default_row,
                        rows,
                        1,
                    ),
                    encoding="utf-8",
                )

            with render_fixture(answers, mutation=duplicate_panel) as (
                _root,
                _outputs,
                result,
            ):
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                observed.append(json.loads(result.stdout)["errors"])

        expected = [
            "STATEMENT_OF_WORK.md Definitions duplicate key: Arbitration Panel"
        ]
        self.assertEqual(expected, observed[0])
        self.assertEqual(expected, observed[1])

    def test_invalid_definition_values_do_not_drive_runtime_projection(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        cases = (
            ("Bootstrap Mode", "sometimes", {}),
            ("Execution Mode", "execute-everything", {}),
            ("Dependency Rule", "install-by-default", {}),
            ("Arbitration Panel", "two-seat project panel", {}),
            (
                "Independent Assessment Approval",
                "Maybe",
                {"independent_assessment_approval": "Autonomous"},
            ),
            (
                "Standing Panel Convocation Approval",
                "Sometimes",
                {
                    "standing_panel_convocation_approval": (
                        "Yes, limited to: active disputes"
                    )
                },
            ),
            ("Security Policy File", "maybe", {}),
        )

        for label, invalid_value, overrides in cases:
            def replace_definition(
                root: Path,
                outputs: dict[str, str],
                definition_label: str = label,
                replacement: str = invalid_value,
            ) -> None:
                lines = outputs["STATEMENT_OF_WORK.md"].splitlines()
                in_definitions = False
                replaced = False
                for index, line in enumerate(lines):
                    if line == "Definitions":
                        in_definitions = True
                        continue
                    if in_definitions and line in project_contract_sync.SOW_TITLES:
                        break
                    if in_definitions and line.startswith(
                        f"{definition_label}:"
                    ):
                        lines[index] = f"{definition_label}: {replacement}"
                        replaced = True
                        break
                self.assertTrue(replaced, definition_label)
                (root / "STATEMENT_OF_WORK.md").write_text(
                    "\n".join(lines) + "\n",
                    encoding="utf-8",
                )

            with self.subTest(definition=label):
                with render_fixture(
                    {**answers, **overrides},
                    mutation=replace_definition,
                ) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(1, len(payload["errors"]), payload)
                    self.assertIn(
                        f"STATEMENT_OF_WORK.md Definitions {label}",
                        payload["errors"][0],
                    )

    def test_invalid_arbitration_masks_only_its_model_owned_route(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }
        default_row = (
            "Arbitration Panel: "
            + project_contract_model.DEFAULT_ARBITRATION_PANEL_PROJECTION
        )
        route = project_contract_model.ARBITRATION_PANEL_RUNTIME_ROUTE

        for include_unrelated in (False, True):
            def invalidate_and_inject_route(
                root: Path,
                outputs: dict[str, str],
                add_unrelated: bool = include_unrelated,
            ) -> None:
                sow = outputs["STATEMENT_OF_WORK.md"].replace(
                    default_row,
                    "Arbitration Panel: invalid panel",
                    1,
                )
                (root / "STATEMENT_OF_WORK.md").write_text(
                    sow,
                    encoding="utf-8",
                )
                rows = [f"- {route}"]
                if add_unrelated:
                    rows.append("- load unrelated-review.md before release")
                contract = outputs["AGENT_PROJECT.md"].replace(
                    "## Minimal Bootstrap Deferrals\n",
                    "## Review Routing\n\n"
                    + "\n".join(rows)
                    + "\n\n## Minimal Bootstrap Deferrals\n",
                    1,
                )
                self.assertNotEqual(contract, outputs["AGENT_PROJECT.md"])
                (root / "AGENT_PROJECT.md").write_text(
                    contract,
                    encoding="utf-8",
                )

            with self.subTest(unrelated=include_unrelated):
                with render_fixture(
                    answers,
                    mutation=invalidate_and_inject_route,
                ) as (_root, _outputs, result):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    errors = json.loads(result.stdout)["errors"]
                    self.assertEqual(1 + int(include_unrelated), len(errors), errors)
                    self.assertIn(
                        "STATEMENT_OF_WORK.md Definitions Arbitration Panel",
                        errors[0],
                    )
                    self.assertEqual(
                        include_unrelated,
                        any("Review Routing" in error for error in errors[1:]),
                    )

    def test_section_owned_definition_rows_are_closed_by_label_and_value(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "decision_authority_grant": "User approval before publishing",
        }
        canonical = "- Decision Boundary: User approval before publishing"

        def duplicate_wrong_value(root: Path, outputs: dict[str, str]) -> None:
            contract = outputs["AGENT_PROJECT.md"].replace(
                canonical,
                canonical + "\n- Decision Boundary: Agent may publish",
                1,
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

        with render_fixture(answers, mutation=duplicate_wrong_value) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                [
                    "Decision Boundary must appear exactly once in "
                    "AGENT_PROJECT.md Approval Boundaries"
                ],
                json.loads(result.stdout)["errors"],
            )

        def replace_with_wrong_value(root: Path, outputs: dict[str, str]) -> None:
            contract = outputs["AGENT_PROJECT.md"].replace(
                canonical,
                "- Decision Boundary: Agent may publish",
                1,
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

        with render_fixture(answers, mutation=replace_with_wrong_value) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                [
                    "Decision Boundary in AGENT_PROJECT.md Approval Boundaries "
                    "does not exactly match the canonical SOW Definition value"
                ],
                json.loads(result.stdout)["errors"],
            )

    def test_model_owned_scalar_duplicate_order_never_selects_an_authority_value(self) -> None:
        panel = {
            "seats": [
                {"model": "reviewer-a", "role": "panelist", "focus": "correctness"},
                {"model": "reviewer-b", "role": "panelist", "focus": "security"},
            ],
            "quorum": "all configured seats",
            "recommendation_threshold": "strict majority",
            "failure_handling": "record no recommendation",
            "tie_handling": "record no recommendation",
            "no_majority_handling": "record no recommendation",
            "abstention_handling": "supports no option",
            "unavailable_panelist_handling": "reconstitute with approval",
            "binding_effect": "recommendation only",
            "accountable_owner": "User",
            "appeal_or_override_path": "User decision",
        }
        cases: tuple[tuple[str, str, dict[str, object]], ...] = (
            ("Arbitration Panel", "Quorum", {"arbitration_panel": panel}),
            (
                "Direct Panel Rules",
                "Standing Panel Convocation Approval",
                {"standing_panel_convocation_approval": "Yes, release disputes only"},
            ),
            (
                "Independent Assessment",
                "Independent Assessment Approval",
                {"independent_assessment_approval": "Autonomous"},
            ),
            ("Source Packs", "Shared Framework Source Reference", {"include_source_packs": True}),
            (
                "Source Update Plan",
                "Shared Framework Source Reference",
                {"include_source_packs": True, "include_source_update": True},
            ),
            (
                "Source Monitor Researcher Brief",
                "Role",
                {"include_source_monitor_researcher": True},
            ),
            (
                "Framework Feedback",
                "Framework Feedback File",
                {"include_framework_feedback": True},
            ),
            (
                "Reviewer Lane Feedback",
                "Reviewer Lane Feedback File",
                {"include_reviewer_lane_feedback": True},
            ),
            (
                "Reviewer Lanes",
                "Reviewer Lane Inventory",
                {"reviewer_lane_inventory": "project/reviewer-lanes.md"},
            ),
            (
                "Security Verification Plan",
                "Profile Scope",
                {"include_security_verification": True},
            ),
            (
                "Standing Automation Orders",
                "Preferred Scheduler Backend",
                {
                    "include_automation_orders": True,
                    "automation_orders": {"jobs": [valid_automation_job()]},
                },
            ),
        )

        for section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            rendered = project_bootstrap.render_sow(answers)
            section_lines = project_contract_sync.plain_sections(
                rendered,
                project_contract_sync.SOW_TITLES,
            )[section]
            canonical_rows = [
                line for line in section_lines if line.strip().startswith(f"{key}:")
            ]
            self.assertEqual(1, len(canonical_rows), (section, key, section_lines))
            canonical = canonical_rows[0]
            contradictory = f"{key}: contradictory-value"
            observed: list[list[str]] = []
            for rows in (
                f"{canonical}\n{contradictory}",
                f"{contradictory}\n{canonical}",
            ):
                def duplicate_scalar(
                    root: Path,
                    outputs: dict[str, str],
                    replacement: str = rows,
                    original: str = canonical,
                    owning_section: str = section,
                ) -> None:
                    lines = outputs["STATEMENT_OF_WORK.md"].splitlines()
                    start = lines.index(owning_section)
                    end = next(
                        (
                            index
                            for index in range(start + 1, len(lines))
                            if lines[index] in project_contract_sync.SOW_TITLES
                        ),
                        len(lines),
                    )
                    row_index = next(
                        index
                        for index in range(start + 1, end)
                        if lines[index] == original
                    )
                    lines[row_index : row_index + 1] = replacement.splitlines()
                    (root / "STATEMENT_OF_WORK.md").write_text(
                        "\n".join(lines) + "\n",
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=duplicate_scalar) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])

            with self.subTest(section=section, key=key):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"STATEMENT_OF_WORK.md {section} duplicate key: {key}"],
                    observed[0],
                )

    def test_duplicate_scalar_section_order_does_not_select_an_authority_value(self) -> None:
        cases: tuple[tuple[str, str, dict[str, object]], ...] = (
            (
                "Independent Assessment",
                "Independent Assessment Approval",
                {"independent_assessment_approval": "Autonomous"},
            ),
            (
                "Standing Automation Orders",
                "Preferred Scheduler Backend",
                {
                    "include_automation_orders": True,
                    "automation_orders": {"jobs": [valid_automation_job()]},
                },
            ),
        )
        for section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            observed: list[list[str]] = []
            for before in (True, False):
                def mutation(
                    root: Path,
                    outputs: dict[str, str],
                    insert_before: bool = before,
                    owning_section: str = section,
                    scalar_key: str = key,
                ) -> None:
                    lines = outputs["STATEMENT_OF_WORK.md"].splitlines()
                    start = lines.index(owning_section)
                    end = next(
                        (
                            index
                            for index in range(start + 1, len(lines))
                            if lines[index] in project_contract_sync.SOW_TITLES
                        ),
                        len(lines),
                    )
                    contradictory = [
                        owning_section,
                        "",
                        f"{scalar_key}: contradictory-value",
                        "",
                    ]
                    insertion = start if insert_before else end
                    lines[insertion:insertion] = contradictory
                    (root / "STATEMENT_OF_WORK.md").write_text(
                        "\n".join(lines) + "\n",
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=mutation) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])

            with self.subTest(section=section):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"STATEMENT_OF_WORK.md duplicate section: {section}"],
                    observed[0],
                )

    def test_optional_state_scalar_duplicate_order_never_selects_an_authority_value(self) -> None:
        cases: tuple[tuple[str, str, str, dict[str, object]], ...] = (
            (
                "SOURCE_PACKS.md",
                "Policy",
                "Shared Framework Source Reference",
                {"include_source_packs": True},
            ),
            (
                "SOURCE_UPDATE.md",
                "Update Policy",
                "Source Registry Scope",
                {"include_source_packs": True, "include_source_update": True},
            ),
            (
                "SOURCE_MONITOR_RESEARCHER.md",
                "Project Configuration",
                "Role",
                {"include_source_monitor_researcher": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Scope",
                "Profile Scope",
                {"include_security_verification": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Authorization Boundaries",
                "Default Target Policy",
                {"include_security_verification": True},
            ),
        )

        for filename, section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            state_text = project_bootstrap.render_output_files(
                answers,
                "generic",
                "$FRAMEWORK",
            )[filename]
            canonical_rows = [
                line
                for line in state_text.splitlines()
                if line.strip().removeprefix("- ").startswith(f"{key}:")
            ]
            self.assertEqual(1, len(canonical_rows), (filename, key))
            canonical = canonical_rows[0]
            prefix = canonical[: canonical.index(key)]
            contradictory = f"{prefix}{key}: contradictory-value"
            observed: list[list[str]] = []
            for rows in (
                f"{canonical}\n{contradictory}",
                f"{contradictory}\n{canonical}",
            ):
                def duplicate_state_scalar(
                    root: Path,
                    outputs: dict[str, str],
                    replacement: str = rows,
                    original: str = canonical,
                    state_filename: str = filename,
                ) -> None:
                    (root / state_filename).write_text(
                        outputs[state_filename].replace(original, replacement, 1),
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=duplicate_state_scalar) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])

            with self.subTest(filename=filename, section=section, key=key):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"{filename} {section} duplicate key: {key}"],
                    observed[0],
                )

    def test_optional_state_duplicate_section_order_never_selects_an_authority_value(self) -> None:
        cases: tuple[tuple[str, str, str, dict[str, object]], ...] = (
            (
                "SOURCE_PACKS.md",
                "Policy",
                "Shared Framework Source Reference",
                {"include_source_packs": True},
            ),
            (
                "SOURCE_UPDATE.md",
                "Update Policy",
                "Source Registry Scope",
                {"include_source_packs": True, "include_source_update": True},
            ),
            (
                "SOURCE_MONITOR_RESEARCHER.md",
                "Project Configuration",
                "Role",
                {"include_source_monitor_researcher": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Scope",
                "Profile Scope",
                {"include_security_verification": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Authorization Boundaries",
                "Default Target Policy",
                {"include_security_verification": True},
            ),
        )

        for filename, section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            observed: list[list[str]] = []
            for before in (True, False):
                def duplicate_state_section(
                    root: Path,
                    outputs: dict[str, str],
                    insert_before: bool = before,
                    state_filename: str = filename,
                    state_section: str = section,
                    state_key: str = key,
                ) -> None:
                    lines = outputs[state_filename].splitlines()
                    heading = f"## {state_section}"
                    start = lines.index(heading)
                    end = next(
                        (
                            index
                            for index in range(start + 1, len(lines))
                            if lines[index].startswith("## ")
                        ),
                        len(lines),
                    )
                    contradictory = [
                        heading,
                        "",
                        f"- {state_key}: contradictory-value",
                        "",
                    ]
                    insertion = start if insert_before else end
                    lines[insertion:insertion] = contradictory
                    (root / state_filename).write_text(
                        "\n".join(lines) + "\n",
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=duplicate_state_section) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])

            with self.subTest(filename=filename, section=section):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"{filename} duplicate section: {section}"],
                    observed[0],
                )

    def test_source_monitor_runner_and_framework_reference_projections_are_exact(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "include_source_monitor_researcher": True,
            "project_name": "Demo",
        }
        expected_command = (
            project_contract_model.source_monitor_artifact_lint_command(
                TEST_FRAMEWORK_RUNNER,
                "$FRAMEWORK",
            )
        )
        cases = (
            (
                "runner",
                expected_command,
                expected_command.replace(
                    TEST_FRAMEWORK_RUNNER,
                    "python3 -B",
                    1,
                ),
                "strict monitor command",
            ),
            (
                "command framework reference",
                expected_command,
                expected_command.replace(
                    "${FRAMEWORK:?FRAMEWORK is required}/scripts/source_chain_artifact_lint.py",
                    "${OTHER_FRAMEWORK:?OTHER_FRAMEWORK is required}/scripts/source_chain_artifact_lint.py",
                    1,
                ),
                "strict monitor command",
            ),
            (
                "instruction framework reference",
                "$FRAMEWORK/task_orders/source_update.md",
                "$OTHER_FRAMEWORK/task_orders/source_update.md",
                "model-owned framework-reference projection",
            ),
        )
        for case, original, replacement, diagnostic in cases:
            def mutate_monitor(
                root: Path,
                outputs: dict[str, str],
                old: str = original,
                new: str = replacement,
            ) -> None:
                monitor = outputs["SOURCE_MONITOR_RESEARCHER.md"]
                self.assertIn(old, monitor)
                (root / "SOURCE_MONITOR_RESEARCHER.md").write_text(
                    monitor.replace(old, new, 1),
                    encoding="utf-8",
                )

            with self.subTest(case=case):
                with render_fixture(answers, mutation=mutate_monitor) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    errors = json.loads(result.stdout)["errors"]
                    self.assertEqual(1, len(errors), errors)
                    self.assertIn(diagnostic, errors[0])

    def test_optional_state_case_variant_key_collision_never_selects_authority(self) -> None:
        cases: tuple[tuple[str, str, str, dict[str, object]], ...] = (
            (
                "SOURCE_PACKS.md",
                "Policy",
                "Shared Framework Source Reference",
                {"include_source_packs": True},
            ),
            (
                "SOURCE_UPDATE.md",
                "Update Policy",
                "Source Registry Scope",
                {"include_source_packs": True, "include_source_update": True},
            ),
            (
                "SOURCE_MONITOR_RESEARCHER.md",
                "Project Configuration",
                "Role",
                {"include_source_monitor_researcher": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Scope",
                "Profile Scope",
                {"include_security_verification": True},
            ),
        )
        for filename, section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            state_text = project_bootstrap.render_output_files(
                answers,
                "generic",
                "$FRAMEWORK",
            )[filename]
            canonical = next(
                line
                for line in state_text.splitlines()
                if line.strip().removeprefix("- ").startswith(f"{key}:")
            )
            prefix = canonical[: canonical.index(key)]
            variant = f"{prefix}{key.swapcase()}: contradictory-value"
            observed: list[list[str]] = []
            for replacement in (
                f"{canonical}\n{variant}",
                f"{variant}\n{canonical}",
            ):
                def collide_key(
                    root: Path,
                    outputs: dict[str, str],
                    rows: str = replacement,
                    original: str = canonical,
                    state_filename: str = filename,
                ) -> None:
                    (root / state_filename).write_text(
                        outputs[state_filename].replace(original, rows, 1),
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=collide_key) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])
            with self.subTest(filename=filename, section=section, key=key):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"{filename} {section} duplicate key: {key}"],
                    observed[0],
                )

    def test_optional_state_case_variant_section_collision_never_selects_authority(self) -> None:
        cases: tuple[tuple[str, str, str, dict[str, object]], ...] = (
            (
                "SOURCE_PACKS.md",
                "Policy",
                "Shared Framework Source Reference",
                {"include_source_packs": True},
            ),
            (
                "SOURCE_UPDATE.md",
                "Update Policy",
                "Source Registry Scope",
                {"include_source_packs": True, "include_source_update": True},
            ),
            (
                "SOURCE_MONITOR_RESEARCHER.md",
                "Project Configuration",
                "Role",
                {"include_source_monitor_researcher": True},
            ),
            (
                "SECURITY_VERIFICATION.md",
                "Authorization Boundaries",
                "Default Target Policy",
                {"include_security_verification": True},
            ),
        )
        for filename, section, key, additions in cases:
            answers: dict[str, object] = {
                "bootstrap_mode": "minimal",
                "agent": "Agent",
                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                "project_name": "Demo",
                **additions,
            }
            observed: list[list[str]] = []
            for before in (True, False):
                def collide_section(
                    root: Path,
                    outputs: dict[str, str],
                    insert_before: bool = before,
                    state_filename: str = filename,
                    state_section: str = section,
                    state_key: str = key,
                ) -> None:
                    lines = outputs[state_filename].splitlines()
                    heading = f"## {state_section}"
                    start = lines.index(heading)
                    end = next(
                        (
                            index
                            for index in range(start + 1, len(lines))
                            if lines[index].startswith("## ")
                        ),
                        len(lines),
                    )
                    variant = [
                        f"## {state_section.swapcase()}",
                        "",
                        f"- {state_key}: contradictory-value",
                        "",
                    ]
                    insertion = start if insert_before else end
                    lines[insertion:insertion] = variant
                    (root / state_filename).write_text(
                        "\n".join(lines) + "\n",
                        encoding="utf-8",
                    )

                with render_fixture(answers, mutation=collide_section) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    observed.append(json.loads(result.stdout)["errors"])
            with self.subTest(filename=filename, section=section):
                self.assertEqual(observed[0], observed[1])
                self.assertEqual(
                    [f"{filename} duplicate section: {section}"],
                    observed[0],
                )

    def test_reserved_authority_identity_normalizes_unicode_and_whitespace_only_for_keys(self) -> None:
        blocked, errors = project_contract_sync.reserved_identity_errors(
            ["Update   Policy"],
            {"Update Policy"},
            source="STATE.md",
            kind="section",
        )
        self.assertEqual({"Update Policy"}, blocked)
        self.assertEqual(1, len(errors), errors)

        blocked, errors = project_contract_sync.reserved_identity_errors(
            ["Café", "Cafe\u0301"],
            {"Café"},
            source="STATE.md",
            kind="key",
        )
        self.assertEqual({"Café"}, blocked)
        self.assertEqual(["STATE.md duplicate key: Café"], errors)

    def test_project_contract_sync_duplicate_section_order_does_not_select_values(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        def duplicate_before(root: Path, outputs: dict[str, str]) -> None:
            (root / "AGENT_PROJECT.md").write_text(
                outputs["AGENT_PROJECT.md"].replace(
                    "## Definitions",
                    "## Definitions\n\n- Bootstrap Mode: full\n\n## Definitions",
                    1,
                ),
                encoding="utf-8",
            )

        def duplicate_after(root: Path, outputs: dict[str, str]) -> None:
            lines = outputs["AGENT_PROJECT.md"].splitlines()
            start = lines.index("## Definitions")
            end = next(
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")
            )
            lines[end:end] = [
                "## Definitions",
                "",
                "- Bootstrap Mode: full",
                "",
            ]
            (root / "AGENT_PROJECT.md").write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )

        observed: list[list[str]] = []
        for mutation in (duplicate_before, duplicate_after):
            with render_fixture(answers, mutation=mutation) as (
                _root,
                _outputs,
                result,
            ):
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                observed.append(json.loads(result.stdout)["errors"])

        self.assertEqual(observed[0], observed[1])
        self.assertEqual(
            ["AGENT_PROJECT.md duplicate section: Definitions"],
            observed[0],
        )

    def test_parse_scope_accepts_only_exact_labels(self) -> None:
        self.assertEqual(
            {
                "In scope": [],
                "Out of scope": ["Excluded work"],
            },
            project_contract_sync.parse_scope(
                [
                    "IN SCOPE:",
                    "- silently ignored work",
                    "Out of scope:",
                    "- Excluded work",
                ]
            ),
        )

    def test_project_contract_sync_rejects_duplicate_scope_label_without_dependent_diagnostics(
        self,
    ) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "in_scope": ["Render reports"],
            "out_of_scope": ["Production deployment"],
        }

        def duplicate_empty_label(root: Path, outputs: dict[str, str]) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                outputs["STATEMENT_OF_WORK.md"].replace(
                    "In scope:\n- Render reports",
                    "In scope:\nIn scope:\n- Render reports",
                    1,
                ),
                encoding="utf-8",
            )

        with render_fixture(answers, mutation=duplicate_empty_label) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            errors = json.loads(result.stdout)["errors"]

        scope_errors = [
            error
            for error in errors
            if error.startswith("STATEMENT_OF_WORK.md Scope")
        ]
        self.assertEqual(
            [
                "STATEMENT_OF_WORK.md Scope must contain exactly one "
                "'In scope:' label; found 2"
            ],
            scope_errors,
        )
        self.assertFalse(
            any(
                "scope" in error.casefold() and "drift" in error
                for error in errors
            ),
            errors,
        )
        self.assertFalse(
            any("Minimal Bootstrap Deferrals" in error for error in errors),
            errors,
        )

    def test_project_contract_sync_enforces_closed_scope_grammar_on_both_surfaces(
        self,
    ) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "in_scope": ["Render reports"],
            "out_of_scope": ["Production deployment"],
        }
        canonical = (
            "In scope:\n- Render reports\n\n"
            "Out of scope:\n- Production deployment"
        )
        cases: tuple[
            tuple[str, str, str, str, int, tuple[str, ...]],
            ...,
        ] = (
            (
                "reversed",
                canonical,
                "Out of scope:\n- Production deployment\n\n"
                "In scope:\n- Render reports",
                "labels must appear in order",
                1,
                (),
            ),
            (
                "case variant",
                "In scope:\n- Render reports",
                "IN SCOPE:\n- Render reports",
                "label must be exactly 'In scope:'",
                1,
                (),
            ),
            (
                "stray prose",
                "In scope:\n- Render reports",
                "In scope:\nScope prose is not authoritative.\n- Render reports",
                "is unsupported; expected an exact scope label",
                1,
                (),
            ),
            (
                "stray bullet",
                "In scope:\n- Render reports",
                "- unowned scope bullet\nIn scope:\n- Render reports",
                "is a scope bullet before 'In scope:'",
                1,
                (),
            ),
            (
                "empty bullet",
                "In scope:\n- Render reports",
                "In scope:\n-",
                "must contain a nonempty scope bullet",
                2,
                ("'In scope:' must have at least one nonempty bullet row",),
            ),
        )
        surfaces = (
            ("STATEMENT_OF_WORK.md", "STATEMENT_OF_WORK.md Scope"),
            ("AGENT_PROJECT.md", "AGENT_PROJECT.md Active Scope"),
        )

        for case, original, replacement, expected, count, extra in cases:
            for filename, source in surfaces:
                def mutate_scope(
                    root: Path,
                    outputs: dict[str, str],
                    *,
                    target: str = filename,
                    old: str = original,
                    new: str = replacement,
                ) -> None:
                    (root / target).write_text(
                        outputs[target].replace(old, new, 1),
                        encoding="utf-8",
                    )

                with self.subTest(case=case, surface=filename):
                    with render_fixture(answers, mutation=mutate_scope) as (
                        _root,
                        _outputs,
                        result,
                    ):
                        self.assertEqual(
                            1,
                            result.returncode,
                            result.stdout + result.stderr,
                        )
                        errors = json.loads(result.stdout)["errors"]
                    scope_errors = [
                        error for error in errors if error.startswith(source)
                    ]
                    self.assertEqual(count, len(scope_errors), errors)
                    self.assertTrue(
                        any(
                            error.startswith(source) and expected in error
                            for error in scope_errors
                        ),
                        errors,
                    )
                    for fragment in extra:
                        self.assertTrue(
                            any(
                                error.startswith(source) and fragment in error
                                for error in scope_errors
                            ),
                            errors,
                        )
                    self.assertFalse(
                        any(
                            "scope" in error.casefold() and "drift" in error
                            for error in errors
                        ),
                        errors,
                    )
                    self.assertFalse(
                        any(
                            "Minimal Bootstrap Deferrals" in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_project_contract_sync_bounds_missing_prerequisite_sections(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        def remove_sow_definitions(root: Path, outputs: dict[str, str]) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                remove_plain_section(outputs["STATEMENT_OF_WORK.md"], "Definitions"),
                encoding="utf-8",
            )

        def remove_contract_definitions(root: Path, outputs: dict[str, str]) -> None:
            (root / "AGENT_PROJECT.md").write_text(
                remove_markdown_section(outputs["AGENT_PROJECT.md"], "Definitions"),
                encoding="utf-8",
            )

        def remove_technical_specifications(
            root: Path,
            outputs: dict[str, str],
        ) -> None:
            (root / "STATEMENT_OF_WORK.md").write_text(
                remove_plain_section(
                    outputs["STATEMENT_OF_WORK.md"],
                    "Technical Specifications",
                ),
                encoding="utf-8",
            )

        cases: tuple[tuple[str, FixtureMutation, str], ...] = (
            (
                "SOW Definitions",
                remove_sow_definitions,
                "STATEMENT_OF_WORK.md missing required section: Definitions",
            ),
            (
                "runtime Definitions",
                remove_contract_definitions,
                "AGENT_PROJECT.md missing required section: Definitions",
            ),
            (
                "Technical Specifications",
                remove_technical_specifications,
                "STATEMENT_OF_WORK.md missing required section: Technical Specifications",
            ),
        )
        for label, mutation, expected in cases:
            with self.subTest(section=label):
                with render_fixture(answers, mutation=mutation) as (
                    _root,
                    _outputs,
                    result,
                ):
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    errors = json.loads(result.stdout)["errors"]
                self.assertEqual([expected], errors)

    def test_project_contract_sync_invalid_bootstrap_mode_does_not_select_full_or_minimal(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        def invalidate_mode(root: Path, outputs: dict[str, str]) -> None:
            for name in ("STATEMENT_OF_WORK.md", "AGENT_PROJECT.md"):
                (root / name).write_text(
                    outputs[name].replace(
                        "Bootstrap Mode: minimal",
                        "Bootstrap Mode: invalid",
                        1,
                    ),
                    encoding="utf-8",
                )

        with render_fixture(answers, mutation=invalidate_mode) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            errors = json.loads(result.stdout)["errors"]

        self.assertEqual(1, len(errors), errors)
        self.assertIn("Definitions Bootstrap Mode has invalid value", errors[0])
        self.assertFalse(any("full bootstrap" in error for error in errors), errors)
        self.assertFalse(any("Minimal Bootstrap Deferrals" in error for error in errors), errors)

    def test_project_contract_sync_runner_mismatch_stops_dependent_command_checks(self) -> None:
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
        }

        def mismatch_runner(root: Path, outputs: dict[str, str]) -> None:
            contract = outputs["AGENT_PROJECT.md"].replace(
                f"- Framework Verification Runner: {TEST_FRAMEWORK_RUNNER}",
                "- Framework Verification Runner: python3 -B",
                1,
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

        with render_fixture(answers, mutation=mismatch_runner) as (
            _root,
            _outputs,
            result,
        ):
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            errors = json.loads(result.stdout)["errors"]

        self.assertEqual(
            [
                "AGENT_PROJECT.md Framework Verification Commands runner does not use "
                "the SOW Framework Verification Runner"
            ],
            errors,
        )

    def test_project_contract_sync_accepts_rendered_command_restrictions(self) -> None:
        restriction = {
            "command": "npm install",
            "reason": "unapproved package install",
            "alternative": "ask first",
        }
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "project_name": "Demo",
            "command_restrictions": [restriction],
        }
        canonical = project_contract_model.render_command_restriction(
            restriction["command"],
            restriction["reason"],
            restriction["alternative"],
        )

        self.assertEqual([], project_bootstrap.validate_answers(answers))
        with render_fixture(
            answers,
            flags=("--strict-warnings",),
        ) as (_root, outputs, result):
            self.assertIn(canonical, outputs["STATEMENT_OF_WORK.md"])
            self.assertIn("- " + canonical, outputs["AGENT_PROJECT.md"])
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_project_contract_sync_preserves_exact_restricted_command_values(self) -> None:
        cases = (
            ("case", "printf '%s' 'APPROVED'", "printf '%s' 'approved'"),
            (
                "quoted whitespace",
                "printf '%s' 'first  second'",
                "printf '%s' 'first second'",
            ),
            ("literal em dash", "printf '%s' '—'", "printf '%s' '-'"),
        )
        for label, command, changed_command in cases:
            with self.subTest(change=label):
                restriction = {
                    "command": command,
                    "reason": "requires approval",
                    "alternative": "ask first",
                }
                answers: dict[str, object] = {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    "command_restrictions": [restriction],
                }
                canonical = project_contract_model.render_command_restriction_record(
                    restriction
                )
                changed_row = project_contract_model.render_command_restriction_record(
                    {**restriction, "command": changed_command}
                )
                self.assertEqual([], project_bootstrap.validate_answers(answers))
                with render_fixture(answers) as (root, _outputs, valid):
                    self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
                    contract_path = root / "AGENT_PROJECT.md"
                    contract_path.write_text(
                        contract_path.read_text(encoding="utf-8").replace(
                            f"- {canonical}\n", f"- {changed_row}\n", 1
                        ),
                        encoding="utf-8",
                    )
                    changed = run_sync(root)

                self.assertEqual(1, changed.returncode, changed.stdout + changed.stderr)
                self.assertIn(
                    "Command Restrictions drift between SOW and project contract",
                    changed.stdout,
                )

    def test_project_contract_sync_restrictions_preserve_rows_with_unordered_parity(self) -> None:
        restrictions = [
            {
                "command": command,
                "reason": "requires approval",
                "alternative": "ask first",
            }
            for command in ("uv run python production.py", "uv run python rollback.py")
        ]
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "command_restrictions": restrictions,
        }
        rows = [
            "- " + project_contract_model.render_command_restriction_record(item) + "\n"
            for item in restrictions
        ]
        with render_fixture(answers) as (root, outputs, valid):
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
            reordered = outputs["AGENT_PROJECT.md"].replace(
                "".join(rows), "".join(reversed(rows)), 1
            )
            self.assertNotEqual(outputs["AGENT_PROJECT.md"], reordered)
            contract_path = root / "AGENT_PROJECT.md"
            contract_path.write_text(reordered, encoding="utf-8")
            reordered_result = run_sync(root)
            self.assertEqual(
                0, reordered_result.returncode,
                reordered_result.stdout + reordered_result.stderr,
            )
            contract_path.write_text(
                reordered.replace(rows[0], "", 1), encoding="utf-8"
            )
            missing = run_sync(root)

        self.assertEqual(1, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn(
            "Command Restrictions drift between SOW and project contract", missing.stdout
        )
        for key in project_contract_model.RESTRICTION_KEYS:
            with self.subTest(missing_field=key):
                incomplete = {
                    field: value
                    for field, value in restrictions[0].items()
                    if field != key
                }
                errors = project_bootstrap.validate_answers(
                    {**answers, "command_restrictions": [incomplete]}
                )
                self.assertIn(f"missing command restriction key in item 1: {key}", errors)

    def test_project_contract_sync_warns_when_sow_constraints_deliverables_or_restrictions_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "full",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "tech_stack": "Python CLI",
                    "in_scope": ["Render reports"],
                    "language_runtime_standards": "Python 3.14",
                    "out_of_scope": ["Production deployment"],
                    "commands": {},
                    "constraints": ["Keep generated artifacts reproducible"],
                    "deliverables": [
                        {
                            "description": "Render report",
                            "test": "uv run python -m unittest",
                            "pass_criteria": "tests pass",
                        }
                    ],
                    "command_restrictions": [
                        {
                            "command": "npm install",
                            "reason": "unapproved package install",
                            "alternative": "ask first",
                        }
                    ],
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace("- Keep generated artifacts reproducible\n", "")
            contract = contract.replace(
                "1. Render report — uv run python -m unittest — tests pass\n",
                "",
            )
            contract = contract.replace("- Production deployment\n", "")
            contract = contract.replace(
                "- npm install — never run — unapproved package install — use ask first instead\n",
                "",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root, "--strict-warnings")

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "Non-Negotiable Constraints drift between SOW and project contract",
                result.stdout,
                result.stdout + result.stderr,
            )
            self.assertIn(
                "Active Deliverables drift between SOW and project contract",
                result.stdout,
                result.stdout + result.stderr,
            )
            self.assertIn(
                "AGENT_PROJECT.md Active Scope 'Out of scope:' must have at least "
                "one nonempty bullet row",
                result.stdout,
                result.stdout + result.stderr,
            )
            self.assertIn(
                "Command Restrictions drift between SOW and project contract",
                result.stdout,
                result.stdout + result.stderr,
            )

    def test_project_contract_sync_rejects_weakened_command_restriction_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "full",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "tech_stack": "Python CLI",
                    "in_scope": ["Render reports"],
                    "out_of_scope": ["Production deployment"],
                    "commands": {},
                    "command_restrictions": [
                        {
                            "command": "npm install",
                            "reason": "unapproved package install",
                            "alternative": "ask first",
                        }
                    ],
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            contract = (root / "AGENT_PROJECT.md").read_text(encoding="utf-8")
            contract = contract.replace(
                "npm install — never run — unapproved package install — use ask first instead",
                "npm install — never run except for package refresh — unapproved package install — use ask first instead",
            )
            (root / "AGENT_PROJECT.md").write_text(contract, encoding="utf-8")

            result = run_sync(root, "--strict-warnings")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Command Restrictions drift between SOW and project contract", result.stdout)

    def test_project_contract_sync_warns_for_absolute_path_in_common_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                    "commands": {
                        "deploy": "PYTHONPATH=src:/" + "usr/bin uv run deploy",
                    },
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")

            result = run_sync(root, "--strict-warnings")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("host-specific absolute path in Common Commands Deploy", result.stdout)

    def test_project_bootstrap_refuses_symlink_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            outside = Path(temp_dir) / "outside.md"
            output = root / "TODO.md"
            output.symlink_to(outside)

            errors = project_bootstrap.preflight_writes(
                root,
                {"TODO.md": "content\n"},
            )

            self.assertTrue(any("symlink output path" in error for error in errors))

    def test_project_contract_sync_rejects_hardlinked_contract_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            os.link(root / "STATEMENT_OF_WORK.md", root / "sow-alias.md")

            result = run_sync(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must have exactly one hard link", result.stdout)

    def test_project_contract_sync_reports_invalid_utf8_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = project_bootstrap.render_output_files(
                {
                    "bootstrap_mode": "minimal",
                    "agent": "Agent",
                    "project_name": "Demo",
                },
                "generic",
                "$FRAMEWORK",
            )
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            (root / "AGENT_PROJECT.md").write_bytes(b"\xff\xfe")

            result = run_sync(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("could not be read safely", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_project_bootstrap_reports_excessive_json_nesting_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "answers.json"
            input_path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")

            _resolved, _raw, payload, errors = project_bootstrap.load_json_input(
                str(input_path),
                "bootstrap answers",
            )

            self.assertIsNone(payload)
            self.assertEqual(1, len(errors), errors)
            self.assertIn("JSON nesting exceeds the supported parser depth", errors[0])
            self.assertEqual([input_path], list(root.iterdir()))
