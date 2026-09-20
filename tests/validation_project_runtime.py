"""Project state, instance, and context-routing tests."""

from __future__ import annotations

import io
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
    dict_items,
    run_bounded,
    string_items,
    valid_automation_job,
)

import context_manifest  # noqa: E402
import integration_registry  # noqa: E402
import lint_reviewer_lane_feedback  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import project_input  # noqa: E402
import project_instance_lint  # noqa: E402
import project_state_identity  # noqa: E402
import project_state_lint  # noqa: E402
import prompt_load_report  # noqa: E402
import routing_policy  # noqa: E402
import safe_paths  # noqa: E402


VALID_FRAMEWORK_FEEDBACK_CHECKLIST = (
    "- [x] No project, client, repository, branch, issue, pull-request, commit, "
    "team, user, or organization identifiers\n"
    "- [x] No local paths, private URLs, internal domains, hostnames, IP addresses, "
    "database names, bucket names, or service names\n"
    "- [x] No secrets, tokens, credentials, certificates, connection strings, "
    "environment values, or redacted-near-misses\n"
    "- [x] No personal names, emails, handles, customer data, private metrics, or "
    "proprietary business context\n"
    "- [x] No raw logs, stack traces, transcripts, screenshots, copied private code, "
    "or proprietary architecture\n"
    "- [x] Observation is abstracted before framework use\n"
)

FRAMEWORK_FEEDBACK_SEQUENCE = (
    "## Candidate Sequence\n\n"
    "Next candidate ID: `FF-0002`.\n\n"
)
FRAMEWORK_FEEDBACK_OPEN_CANDIDATES = (
    FRAMEWORK_FEEDBACK_SEQUENCE + "## Open Candidates\n\n"
)
FRAMEWORK_FEEDBACK_EMPTY_STATE = FRAMEWORK_FEEDBACK_OPEN_CANDIDATES + "- None.\n"


def valid_framework_feedback_entry() -> str:
    return (
        FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
        + "### FF-0001 - bounded feedback grammar\n\n"
        "Status: candidate\n"
        "Category: other\n"
        "Framework Target: none\n"
        "Evidence Basis: single-observation\n"
        "Evidence Source: project-evidence\n"
        "Confidence: medium\n\n"
        "#### Sanitized Observation\n\nA sanitized observation.\n\n"
        "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
        "#### Candidate Framework Change\n\nA bounded change.\n\n"
        "#### Applicability\n\nA bounded context.\n\n"
        "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
        "#### Source-Registry Implication\n\nNone.\n\n"
        "#### Deterministic-Check Implication\n\nNone.\n\n"
        "#### Evidence Summary\n\nOne sanitized observation.\n\n"
        "#### Public Sources\n\nNone.\n\n"
        "#### Anti-Leak Checklist\n\n"
        + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
        + "\n#### Maintainer Decision\n\n"
        "Decision: pending\n"
        "Rationale:\n"
        "Framework Change:\n"
    )


class ProjectStateInstanceContextTests(unittest.TestCase):
    def test_project_state_lint_dispatches_every_optional_template_family(self) -> None:
        names = (
            "SOURCE_PACKS.md",
            "SOURCE_UPDATE.md",
            "SOURCE_MONITOR_RESEARCHER.md",
            "SECURITY_VERIFICATION.md",
        )
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "include_source_packs": True,
            "include_source_update": True,
            "include_source_monitor_researcher": True,
            "include_security_verification": True,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in names:
                (root / name).write_text(
                    project_bootstrap.state_template_content(
                        name,
                        answers,
                        "$FRAMEWORK",
                    ),
                    encoding="utf-8",
                )

            report = project_state_lint.lint_state_files(
                root,
                names,
                require_core=False,
            )

        self.assertEqual([], report["errors"], report)

    def test_project_state_lint_rejects_malformed_and_unknown_selected_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text(
                "# Source Packs\n\n## Policy\n\n- Shared Framework Source Reference: none\n",
                encoding="utf-8",
            )

            report = project_state_lint.lint_state_files(
                root,
                ("SOURCE_PACKS.md", "UNSUPPORTED_STATE.md"),
                require_core=False,
            )

        self.assertTrue(
            any("SOURCE_PACKS.md: missing required section" in error for error in report["errors"]),
            report,
        )
        self.assertIn(
            "unsupported selected project state file: UNSUPPORTED_STATE.md",
            report["errors"],
        )

    def test_project_state_lint_rejects_duplicate_or_placeholder_configuration(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "include_source_packs": True,
            "include_source_update": True,
        }
        rendered = project_bootstrap.state_template_content(
            "SOURCE_UPDATE.md",
            answers,
            "$FRAMEWORK",
        )
        original = (
            "- Source Registry Scope: "
            f"{project_bootstrap.source_registry_scope(answers)}"
        )
        rendered = rendered.replace(
            original,
            f"{original}\n- Source Registry Scope: [select concrete scope]",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_UPDATE.md").write_text(rendered, encoding="utf-8")
            report = project_state_lint.lint_state_files(
                root,
                ("SOURCE_UPDATE.md",),
                require_core=False,
            )

        self.assertIn(
            "SOURCE_UPDATE.md: ## Update Policy duplicates field: Source Registry Scope",
            report["errors"],
        )
        self.assertIn(
            "SOURCE_UPDATE.md: ## Update Policy missing concrete field: Source Registry Scope",
            report["errors"],
        )

    def test_project_state_lint_checks_reviewer_lane_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "TODO.md").write_text(
                "state_schema_version: 1\n"
                "active_count: 0\n"
                "\n"
                "# TODO\n"
                "\n"
                "- None.\n",
                encoding="utf-8",
            )
            (root / "DECISIONS.md").write_text(
                "state_schema_version: 1\n"
                "durable_decision_count: 0\n"
                "directive_count: 0\n"
                "\n"
                "# Decisions\n"
                "\n"
                "- None.\n",
                encoding="utf-8",
            )
            (root / "REVIEWER_LANE_FEEDBACK.md").write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Useful for marker review.","evidence_refs":[".'
                'codex/session.jsonl"],"routing_implication":"Use for schema review.","confidence":"medium"}\n',
                encoding="utf-8",
            )

            with mock.patch.object(sys, "argv", ["project_state_lint.py", "--root", str(root)]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_state_lint.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertTrue(
            any(
                "REVIEWER_LANE_FEEDBACK.md: line" in error
                and "raw logs or transcripts cannot be primary evidence" in error
                for error in string_items(report["errors"])
            ),
            report["errors"],
        )

    def test_project_state_lint_resolves_nested_reviewer_refs_from_project_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            contract_root = project_root / "contracts" / "state"
            reports = project_root / "reports"
            contract_root.mkdir(parents=True)
            reports.mkdir()
            (reports / "lane.md").write_text(
                "# Lane Evidence\n",
                encoding="utf-8",
            )
            (contract_root / "REVIEWER_LANE_FEEDBACK.md").write_text(
                "# Reviewer Lane Feedback\n\n"
                'REVIEWER_LANE_USED {"lane_id":"codex_subagent","task_ref":"T1","lane_class":"local_subagent","purpose":"schema review","output_ref":"reports/lane.md","evidence_refs":["reports/lane.md"]}\n'
                "\n## Lane: codex_subagent\n\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            report = project_state_lint.lint_state_files(
                contract_root,
                ("REVIEWER_LANE_FEEDBACK.md",),
                require_core=False,
                project_root=project_root,
            )

        self.assertEqual([], report["errors"], report)
        self.assertEqual([], report["warnings"], report)

    def test_reviewer_lane_template_heading_routes_enum_validation(self) -> None:
        template = project_bootstrap.state_template_content(
            "REVIEWER_LANE_FEEDBACK.md"
        )
        self.assertIn("## Lane: [lane_id]", template)

        def filled(runtime_class: str) -> str:
            return (
                template.replace("## Lane: [lane_id]", "## Lane: lane_one")
                .replace(
                    "Runtime Class: [local_subagent / external_chat / deep_research / bounded_wrapper / deterministic_script / human / other]",
                    f"Runtime Class: {runtime_class}",
                )
                .replace(
                    "Evidence Basis: [single-observation / repeated-in-project / repeated-across-projects / public-source-backed / design-judgment]",
                    "Evidence Basis: single-observation",
                )
                .replace("Confidence: [low / medium / high]", "Confidence: medium")
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "REVIEWER_LANE_FEEDBACK.md"
            path.write_text(filled("local_subagent"), encoding="utf-8")
            valid = project_state_lint.lint_state_files(
                root,
                ("REVIEWER_LANE_FEEDBACK.md",),
                require_core=False,
            )
            path.write_text(filled("unrecognized_lane_class"), encoding="utf-8")
            invalid = project_state_lint.lint_state_files(
                root,
                ("REVIEWER_LANE_FEEDBACK.md",),
                require_core=False,
            )

        self.assertEqual([], valid["errors"], valid)
        self.assertIn(
            "REVIEWER_LANE_FEEDBACK.md: lane lane_one: invalid or missing Runtime Class: unrecognized_lane_class",
            invalid["errors"],
        )

    def _write_valid_project_instance(
        self,
        project_root: Path,
        *,
        answer_overrides: dict[str, object] | None = None,
    ) -> dict[str, object]:
        contract_ref = ".mpa"
        contract_root = project_root / contract_ref
        contract_root.mkdir(parents=True)
        answers: dict[str, object] = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "date": "2026-07-14",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
            "include_findings": True,
        }
        answers.update(answer_overrides or {})
        runtime = "generic"
        framework_ref = os.path.relpath(REPO_ROOT, project_root)
        outputs = project_bootstrap.render_output_files(
            answers,
            runtime,
            framework_ref,
            project_kind="downstream",
            contract_root_ref=contract_ref,
            effective_date="2026-07-14",
        )
        for name, content in outputs.items():
            target = project_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        input_text = project_input.render_project_input(
            project_kind="downstream",
            contract_root=contract_ref,
            runtime=runtime,
            framework_reference=framework_ref,
            framework_revision_policy="live",
            answers=answers,
        )
        input_path = contract_root / project_input.INPUT_NAME
        input_path.write_text(input_text, encoding="utf-8")
        managed, immutable, mutable = project_bootstrap.project_instance_file_sets(
            answers=answers,
            runtime=runtime,
            project_kind="downstream",
            contract_root_ref=contract_ref,
        )
        manifest_text = project_bootstrap.render_instance_manifest(
            input_bytes=input_text.encode("utf-8"),
            project_kind="downstream",
            contract_root_ref=contract_ref,
            runtime=runtime,
            framework_reference=framework_ref,
            framework_revision_policy="live",
            framework_reference_status="verified",
            managed_files=managed,
            immutable_files=immutable,
            mutable_files=mutable,
            runtime_wrapper_outputs={},
            rendered_outputs=outputs,
            active_profiles=project_bootstrap.active_project_profiles(
                answers,
                project_kind="downstream",
            ),
            effective_date="2026-07-14",
        )
        manifest_path = project_root / project_instance_lint.MANIFEST_NAME
        manifest_path.write_text(manifest_text, encoding="utf-8")
        return {
            "answers": answers,
            "contract_ref": contract_ref,
            "contract_root": contract_root,
            "framework_ref": framework_ref,
            "immutable": immutable,
            "input_path": input_path,
            "manifest": json.loads(manifest_text),
            "manifest_path": manifest_path,
            "mutable": mutable,
            "outputs": outputs,
        }

    def test_project_state_lint_uses_valid_receipt_ownership_for_optional_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            instance = self._write_valid_project_instance(
                project_root,
                answer_overrides={"include_findings": False},
            )
            contract_root = cast(Path, instance["contract_root"])
            (contract_root / "FINDINGS.md").write_text(
                "- ordinary project findings, not framework state\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                sys,
                "argv",
                [
                    "project_state_lint.py",
                    "--root",
                    str(contract_root),
                    "--project-root",
                    str(project_root),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_state_lint.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(0, result, report)
        self.assertEqual([], report["errors"], report)

    def test_project_state_lint_lints_receipt_owned_optional_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            instance = self._write_valid_project_instance(
                project_root,
                answer_overrides={"include_findings": True},
            )
            contract_root = cast(Path, instance["contract_root"])
            findings = contract_root / "FINDINGS.md"
            original = findings.read_text(encoding="utf-8")
            self.assertIn("mpa-generated-state-origin", original)
            findings.write_text(
                original + "\n- malformed receipt-owned finding\n",
                encoding="utf-8",
            )
            selected = project_state_lint.receipt_owned_state_names(
                contract_root,
                project_root,
            )
            self.assertIsNotNone(selected)
            self.assertIn("FINDINGS.md", selected or set())

            with mock.patch.object(
                sys,
                "argv",
                [
                    "project_state_lint.py",
                    "--root",
                    str(contract_root),
                    "--project-root",
                    str(project_root),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_state_lint.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, result, report)
        self.assertIn(
            "FINDINGS.md: finding entries must start with an ISO date bullet",
            report["errors"],
        )

    def test_project_state_lint_bad_receipt_cannot_suppress_same_name_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            instance = self._write_valid_project_instance(
                project_root,
                answer_overrides={"include_findings": False},
            )
            manifest_path = cast(Path, instance["manifest_path"])
            manifest = cast(dict[str, object], instance["manifest"])
            manifest["managed_files"] = "malformed"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            contract_root = cast(Path, instance["contract_root"])
            (contract_root / "FINDINGS.md").write_text(
                "- ordinary project findings, not framework state\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                sys,
                "argv",
                [
                    "project_state_lint.py",
                    "--root",
                    str(contract_root),
                    "--project-root",
                    str(project_root),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = project_state_lint.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, result, report)
        self.assertIn(
            "FINDINGS.md: finding entries must start with an ISO date bullet",
            report["errors"],
        )

    def test_project_input_is_closed_replayable_and_date_explicit(self) -> None:
        answers = {
            "bootstrap_mode": "minimal",
            "agent": "Agent",
            "project_name": "Demo",
            "date": "2026-07-14",
            "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
        }
        rendered = project_input.render_project_input(
            project_kind="downstream",
            contract_root=".mpa",
            runtime="generic",
            framework_reference="$FRAMEWORK_ROOT",
            framework_revision_policy="live",
            answers=answers,
        )
        payload = json.loads(rendered)
        unknown = dict(payload)
        unknown["operation_history"] = []
        missing_date = json.loads(rendered)
        cast(dict[str, object], missing_date["answers"]).pop("date")

        self.assertEqual(
            project_input.INPUT_KEYS,
            set(payload),
        )
        self.assertEqual(
            [],
            project_input.validate_project_input(payload),
        )
        self.assertIn(
            "project input has unknown keys: operation_history",
            project_input.validate_project_input(unknown),
        )
        self.assertIn(
            "project input answers.date must be an explicit ISO date string",
            project_input.validate_project_input(missing_date),
        )

    def test_downstream_instance_replays_retained_input_and_detects_output_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            initial = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

            immutable = cast(list[str], fixture["immutable"])
            sow_name = next(
                name for name in immutable if name.endswith("STATEMENT_OF_WORK.md")
            )
            sow_path = project_root / sow_name
            sow_path.write_text(
                sow_path.read_text(encoding="utf-8") + "manual drift\n",
                encoding="utf-8",
            )
            drifted = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        self.assertEqual([], initial["errors"], initial)
        self.assertEqual([], initial["warnings"], initial)
        self.assertEqual(
            project_root / project_instance_lint.MANIFEST_NAME,
            fixture["manifest_path"],
        )
        self.assertFalse(
            (
                cast(Path, fixture["contract_root"])
                / project_instance_lint.MANIFEST_NAME
            ).exists()
        )
        self.assertTrue(
            any(
                error == f"immutable generated output digest mismatch: {sow_name}"
                for error in drifted["errors"]
            ),
            drifted,
        )
        self.assertTrue(
            any(
                "immutable generated output does not match retained project input"
                in error
                for error in drifted["errors"]
            ),
            drifted,
        )

    def test_recorded_preimage_requires_exact_mutable_state_origin(self) -> None:
        cases = (
            ("FINDINGS.md", "missing"),
            ("FINDINGS.md", "malformed"),
            ("FINDINGS.md", "late"),
            ("AUTOMATION_ORDERS.json", "missing"),
            ("AUTOMATION_ORDERS.json", "malformed"),
        )
        for state_name, mutation in cases:
            with (
                self.subTest(state_name=state_name, mutation=mutation),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                project_root = Path(temp_dir)
                fixture = self._write_valid_project_instance(
                    project_root,
                    answer_overrides={
                        "include_automation_orders": True,
                        "automation_orders": {
                            "preferred_backend": "unspecified",
                            "jobs": [valid_automation_job()],
                        },
                    },
                )
                contract_ref = cast(str, fixture["contract_ref"])
                initial = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )
                self.assertEqual([], initial["errors"], initial)

                state_path = next(
                    project_root / value
                    for value in cast(list[str], fixture["mutable"])
                    if Path(value).name == state_name
                )
                if state_name.endswith(".json"):
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    if mutation == "missing":
                        payload.pop(project_state_identity.JSON_STATE_ORIGIN_KEY)
                    else:
                        payload[project_state_identity.JSON_STATE_ORIGIN_KEY] = (
                            "unrecognized-origin"
                        )
                    state_path.write_text(
                        json.dumps(payload, indent=2) + "\n",
                        encoding="utf-8",
                    )
                else:
                    state_text = state_path.read_text(encoding="utf-8").replace(
                        project_state_identity.MARKDOWN_STATE_MARKER,
                        (
                            ""
                            if mutation in {"missing", "late"}
                            else "<!-- mpa-generated-state-origin: unrecognized -->"
                        ),
                    )
                    if mutation == "late":
                        state_text = (
                            "x" * project_state_identity.STATE_IDENTITY_PROBE_BYTES
                            + "\n"
                            + project_state_identity.MARKDOWN_STATE_MARKER
                            + "\n"
                            + state_text
                        )
                    state_path.write_text(state_text, encoding="utf-8")

                invalid = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )
                self.assertTrue(
                    any(
                        "missing or has a malformed framework-generated state "
                        "origin marker" in error
                        and state_name in error
                        for error in cast(list[str], invalid["errors"])
                    ),
                    invalid,
                )

    def test_recorded_preimage_accepts_reordered_json_state_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(
                project_root,
                answer_overrides={
                    "include_automation_orders": True,
                    "automation_orders": {
                        "preferred_backend": "unspecified",
                        "jobs": [valid_automation_job()],
                    },
                },
            )
            contract_ref = cast(str, fixture["contract_ref"])
            state_path = next(
                project_root / value
                for value in cast(list[str], fixture["mutable"])
                if Path(value).name == "AUTOMATION_ORDERS.json"
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            origin = payload.pop(project_state_identity.JSON_STATE_ORIGIN_KEY)
            payload[project_state_identity.JSON_STATE_ORIGIN_KEY] = origin
            state_path.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

            report = project_instance_lint.validate_recorded_preimage(
                project_root,
                contract_ref,
                expected_project_kind="downstream",
            )

        self.assertEqual([], report["errors"], report)

    def test_recorded_preimage_rejects_marked_unreceipted_state(self) -> None:
        json_origin = (
            json.dumps(
                {
                    project_state_identity.JSON_STATE_ORIGIN_KEY: (
                        project_state_identity.JSON_STATE_ORIGIN_VALUE
                    )
                }
            )
            + "\n"
        )
        cases = {
            spec.filename: (
                json_origin
                if spec.filename.endswith(".json")
                else (
                    project_state_identity.MARKDOWN_STATE_MARKER
                    + f"\n# Generated {spec.filename} fixture\n"
                ),
                spec.partition,
            )
            for spec in project_contract_model.OPTIONAL_STATE_SPECS
        }
        for state_name, (content, partition) in cases.items():
            with (
                self.subTest(state_name=state_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                project_root = Path(temp_dir)
                fixture = self._write_valid_project_instance(
                    project_root,
                    answer_overrides={"include_findings": False},
                )
                contract_ref = cast(str, fixture["contract_ref"])
                contract_root = cast(Path, fixture["contract_root"])
                (contract_root / state_name).write_text(content, encoding="utf-8")

                report = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )

            orphan_error = next(
                (
                    error
                    for error in cast(list[str], report["errors"])
                    if "unreceipted/orphan framework-generated state" in error
                    and f".mpa/{state_name}" in error
                ),
                None,
            )
            self.assertIsNotNone(orphan_error, report)
            assert orphan_error is not None
            self.assertIn(f"in the {partition} partition", orphan_error)
            self.assertIn("authorize and remove the orphan", orphan_error)
            self.assertIn("candidate-input refresh", orphan_error)
            if partition == "immutable":
                self.assertIn("Preserve any project-specific material separately", orphan_error)
                self.assertIn("accept the canonical renderer bytes", orphan_error)
                self.assertIn(
                    "do not restore project-specific content into the generated immutable file",
                    orphan_error,
                )
                self.assertNotIn("restore sanitized content", orphan_error)
            else:
                self.assertIn("restore sanitized content", orphan_error)
                self.assertIn("preserving its generated-state origin marker", orphan_error)

    def test_recorded_preimage_partition_lint_follows_optional_state_declarations(
        self,
    ) -> None:
        for spec in project_contract_model.OPTIONAL_STATE_SPECS:
            with (
                self.subTest(state=spec.filename, partition=spec.partition),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                overrides: dict[str, object] = {spec.flag: True}
                if spec.flag == "include_source_update":
                    overrides["include_source_packs"] = True
                if spec.flag == "include_automation_orders":
                    overrides["automation_orders"] = {
                        "preferred_backend": "unspecified",
                        "jobs": [valid_automation_job()],
                    }
                project_root = Path(temp_dir)
                fixture = self._write_valid_project_instance(
                    project_root,
                    answer_overrides=overrides,
                )
                contract_ref = cast(str, fixture["contract_ref"])
                relative = project_bootstrap.project_relative_output(
                    contract_ref,
                    spec.filename,
                )
                manifest = cast(dict[str, object], fixture["manifest"])
                immutable = cast(list[str], manifest["immutable_files"])
                mutable = cast(list[str], manifest["mutable_files"])
                selected = immutable if spec.partition == "immutable" else mutable
                wrong = mutable if spec.partition == "immutable" else immutable
                self.assertIn(relative, selected)
                selected.remove(relative)
                wrong.append(relative)
                selected.sort()
                wrong.sort()
                cast(Path, fixture["manifest_path"]).write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                report = project_instance_lint.lint_instance(
                    project_root,
                    contract_ref,
                    framework_root=REPO_ROOT,
                    expected_project_kind="downstream",
                )

            self.assertIn(
                "project instance manifest immutable_files does not match the "
                "selected framework",
                report["errors"],
            )
            self.assertIn(
                "project instance manifest mutable_files does not match the "
                "selected framework",
                report["errors"],
            )

    def test_recorded_preimage_accepts_unmarked_same_name_state(self) -> None:
        cases = {
            "PRECEDENTS.md": (
                "# User-owned memo\n\nThis is not framework-generated state.\n"
            ),
            "AUTOMATION_ORDERS.json": '{"owner": "user"}\n',
        }
        for state_name, content in cases.items():
            with (
                self.subTest(state_name=state_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                project_root = Path(temp_dir)
                fixture = self._write_valid_project_instance(project_root)
                contract_ref = cast(str, fixture["contract_ref"])
                contract_root = cast(Path, fixture["contract_root"])
                (contract_root / state_name).write_text(content, encoding="utf-8")

                report = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )

            self.assertEqual([], report["errors"], report)

    def test_recorded_preimage_rejects_uninspectable_same_name_state_identity(
        self,
    ) -> None:
        cases = {
            "malformed-markdown-marker": (
                "PRECEDENTS.md",
                "<!-- mpa-generated-state-origin: invalid -->\n# Precedents\n",
            ),
            "invalid-json": (
                "AUTOMATION_ORDERS.json",
                '{"mpa_generated_state_origin": ',
            ),
            "duplicate-json-origin": (
                "AUTOMATION_ORDERS.json",
                json.dumps(
                    {
                        project_state_identity.JSON_STATE_ORIGIN_KEY: (
                            project_state_identity.JSON_STATE_ORIGIN_VALUE
                        )
                    }
                )[:-1]
                + ', "mpa_generated_state_origin": "invalid"}\n',
            ),
        }
        for case_name, (state_name, content) in cases.items():
            with (
                self.subTest(case_name=case_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                project_root = Path(temp_dir)
                fixture = self._write_valid_project_instance(project_root)
                contract_ref = cast(str, fixture["contract_ref"])
                contract_root = cast(Path, fixture["contract_root"])
                (contract_root / state_name).write_text(content, encoding="utf-8")

                report = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )

            self.assertTrue(
                any(
                    "unreceipted generated-state identity could not be classified safely"
                    in error
                    and f".mpa/{state_name}" in error
                    for error in cast(list[str], report["errors"])
                ),
                report,
            )

    def test_recorded_preimage_is_closed_and_tolerates_a_removed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            input_path = cast(Path, fixture["input_path"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            retained_input = json.loads(input_path.read_text(encoding="utf-8"))
            retained_input["runtime"] = "retired-runtime"
            input_raw = project_input.canonical_project_input_bytes(retained_input)
            input_path.write_bytes(input_raw)
            manifest["runtime"] = "retired-runtime"
            manifest["input_sha256"] = project_input.project_input_sha256(input_raw)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                project_bootstrap,
                "framework_reference_binding",
                side_effect=AssertionError("stage A consulted the selected checkout"),
            ):
                preimage = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    contract_ref,
                    expected_project_kind="downstream",
                )
            selected = project_instance_lint.validate_selected_checkout(
                preimage,
                framework_root=REPO_ROOT,
            )

        self.assertEqual(
            {
                "errors",
                "warnings",
                "context",
                "manifest",
                "retained_input",
                "input_raw",
                "managed_files",
                "immutable_files",
                "mutable_files",
                "authority_module_drift_errors",
            },
            set(preimage),
        )
        self.assertEqual([], preimage["errors"], preimage)
        self.assertEqual([], preimage["authority_module_drift_errors"], preimage)
        self.assertEqual(input_raw, preimage["input_raw"])
        self.assertEqual(
            [
                "retained project input: downstream project input runtime must be one of: "
                + ", ".join(integration_registry.family_names(REPO_ROOT))
            ],
            selected["errors"],
            selected,
        )

    def test_recorded_preimage_accepts_self_consistent_effective_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            recorded_map = cast(
                dict[str, str],
                manifest["framework_effective_file_digests"],
            )
            changed_path = sorted(recorded_map)[0]
            recorded_map[changed_path] = "0" * 64
            manifest["framework_content_sha256"] = (
                project_bootstrap.canonical_json_digest(recorded_map)
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            preimage = project_instance_lint.validate_recorded_preimage(
                project_root,
                contract_ref,
                expected_project_kind="downstream",
            )
            selected = project_instance_lint.validate_selected_checkout(
                preimage,
                framework_root=REPO_ROOT,
            )

        self.assertEqual([], preimage["errors"], preimage)
        self.assertIn(
            "project instance manifest framework_content_sha256 does not match "
            "the selected current framework content",
            selected["errors"],
        )
        self.assertIn(
            f"selected framework effective file changed since receipt: {changed_path}",
            selected["errors"],
        )

    def test_recorded_preimage_binds_effective_map_to_its_aggregate_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            manifest["framework_content_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            preimage = project_instance_lint.validate_recorded_preimage(
                project_root,
                contract_ref,
            )

        self.assertIn(
            "project instance manifest framework_content_sha256 must exactly digest "
            "framework_effective_file_digests",
            cast(list[str], preimage["errors"]),
        )

    def test_instance_rejects_partition_binding_and_provenance_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            manifest_path = cast(Path, fixture["manifest_path"])
            pristine = cast(dict[str, object], fixture["manifest"])

            partition_manifest = json.loads(json.dumps(pristine))
            partition_manifest["managed_files"].remove(
                cast(list[str], partition_manifest["mutable_files"])[0]
            )
            manifest_path.write_text(
                json.dumps(partition_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            partition = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

            binding_manifest = json.loads(json.dumps(pristine))
            binding_manifest["framework_revision_policy"] = "pinned"
            binding_manifest["framework_reference_status"] = "unresolved"
            manifest_path.write_text(
                json.dumps(binding_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            binding = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

            runtime_manifest = json.loads(json.dumps(pristine))
            runtime_manifest["runtime"] = "claude-code"
            manifest_path.write_text(
                json.dumps(runtime_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            runtime_binding = project_instance_lint.validate_recorded_preimage(
                project_root,
                contract_ref,
                expected_project_kind="downstream",
            )

            provenance_manifest = json.loads(json.dumps(pristine))
            provenance_manifest["framework_content_sha256"] = "0" * 64
            immutable_name = cast(list[str], provenance_manifest["immutable_files"])[0]
            source_records = cast(
                dict[str, list[dict[str, str]]],
                provenance_manifest["generation_sources"],
            )
            source_records[immutable_name][0]["sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(provenance_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            provenance = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        self.assertTrue(
            any("managed_files must be exactly the union" in error for error in partition["errors"]),
            partition,
        )
        self.assertTrue(
            any(
                "managed_files must exactly match retained project input" in error
                for error in partition["errors"]
            ),
            partition,
        )
        self.assertIn(
            "project instance manifest framework_revision_policy does not match retained project input",
            binding["errors"],
        )
        self.assertTrue(
            any("framework_reference_status mismatch" in error for error in binding["errors"]),
            binding,
        )
        self.assertIn(
            "project instance manifest runtime does not match retained project input",
            cast(list[str], runtime_binding["errors"]),
            runtime_binding,
        )
        self.assertTrue(
            any(
                "framework_content_sha256 does not match" in error
                for error in provenance["errors"]
            ),
            provenance,
        )
        self.assertTrue(
            any("generation-source digest is stale" in error for error in provenance["errors"]),
            provenance,
        )

    def test_instance_binds_exact_input_bytes_and_validates_retained_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            input_path = cast(Path, fixture["input_path"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            retained_input = json.loads(input_path.read_text(encoding="utf-8"))

            input_path.write_text(
                json.dumps(retained_input, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            byte_drift = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

            answers = cast(dict[str, object], retained_input["answers"])
            answers["framework_verification_runner"] = "echo"
            changed_input = project_input.canonical_project_input_bytes(retained_input)
            input_path.write_bytes(changed_input)
            manifest["input_sha256"] = project_input.project_input_sha256(changed_input)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            invalid_answers = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        self.assertIn(
            "project instance manifest input_sha256 does not match the retained project input",
            byte_drift["errors"],
        )
        self.assertTrue(
            any(
                "framework_verification_runner must end exactly with a supported"
                in error
                for error in invalid_answers["errors"]
            ),
            invalid_answers,
        )

    def test_distribution_only_drift_is_advisory_not_effective_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            manifest["framework_distribution_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        self.assertEqual([], report["errors"], report)
        self.assertTrue(
            any("framework distribution differs" in warning for warning in report["warnings"]),
            report,
        )

    def test_instance_rejects_an_alternate_bounded_input_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            input_path = cast(Path, fixture["input_path"])
            manifest_path = cast(Path, fixture["manifest_path"])
            manifest = cast(dict[str, object], fixture["manifest"])
            alternate = project_root / "alternate-project-input.json"
            alternate.write_bytes(input_path.read_bytes())
            manifest["input_source"] = alternate.name
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        self.assertTrue(
            any(
                "input_source must exactly name the retained input" in error
                for error in report["errors"]
            ),
            report,
        )

    def test_instance_does_not_fall_back_to_a_contract_root_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            contract_root = cast(Path, fixture["contract_root"])
            manifest_path = cast(Path, fixture["manifest_path"])
            nested_manifest = contract_root / project_instance_lint.MANIFEST_NAME
            manifest_path.replace(nested_manifest)

            report = project_instance_lint.validate_recorded_preimage(
                project_root,
                contract_ref,
                expected_project_kind="downstream",
            )

        self.assertEqual(
            [f"missing project instance manifest: {manifest_path}"],
            report["errors"],
            report,
        )

    def test_root_receipt_contract_root_mismatch_stops_before_contract_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            recorded_contract_ref = cast(str, fixture["contract_ref"])
            selected_contract_ref = ".mpa/alternate"
            with mock.patch.object(
                project_input,
                "load_project_input",
                side_effect=AssertionError("mismatched contract tree was read"),
            ):
                report = project_instance_lint.validate_recorded_preimage(
                    project_root,
                    selected_contract_ref,
                    expected_project_kind="downstream",
                )

        self.assertEqual(
            [
                "project instance manifest contract_root does not match the selected "
                "contract root: "
                f"expected {selected_contract_ref!r}, found {recorded_contract_ref!r}"
            ],
            report["errors"],
            report,
        )
        self.assertIsNone(report["retained_input"])

    def test_instance_schema_preflight_bounds_derivative_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            manifest_path = cast(Path, fixture["manifest_path"])
            pristine = cast(dict[str, object], fixture["manifest"])
            variants: dict[str, dict[str, list[str]]] = {}
            for field, current_version in (
                (
                    "schema_version",
                    project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION,
                ),
                ("project_input_schema_version", project_input.SCHEMA_VERSION),
            ):
                for name, version in (
                    ("missing", None),
                    ("malformed", True),
                    ("older", current_version - 1),
                    ("newer", current_version + 1),
                ):
                    manifest = json.loads(json.dumps(pristine))
                    if version is None:
                        manifest.pop(field)
                    else:
                        manifest[field] = version
                    manifest["contract_effective_date"] = "invalid"
                    manifest["framework_content_sha256"] = "0" * 64
                    manifest_path.write_text(
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    variants[f"{field}:{name}"] = project_instance_lint.lint_instance(
                        project_root,
                        contract_ref,
                        framework_root=REPO_ROOT,
                        expected_project_kind="downstream",
                    )

        for name in variants:
            with self.subTest(name=name):
                self.assertEqual(1, len(variants[name]["errors"]), variants[name])
                error = variants[name]["errors"][0]
                if name.endswith(":newer"):
                    self.assertIn("newer than", error)
                    self.assertIn("framework checkout", error)
                else:
                    self.assertIn("current-only", error)
                    self.assertIn("manual update", error)
                self.assertNotIn("contract_effective_date", error)
                self.assertNotIn("framework_content", error)

    def test_retained_input_schema_preflight_bounds_derivative_diagnostics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            fixture = self._write_valid_project_instance(project_root)
            contract_ref = cast(str, fixture["contract_ref"])
            input_path = cast(Path, fixture["input_path"])
            manifest_path = cast(Path, fixture["manifest_path"])
            pristine_input = json.loads(input_path.read_text(encoding="utf-8"))
            pristine_manifest = cast(dict[str, object], fixture["manifest"])
            variants: dict[str, dict[str, list[str]]] = {}
            for name, version in (
                ("missing", None),
                ("malformed", True),
                ("older", project_input.SCHEMA_VERSION - 1),
                ("newer", project_input.SCHEMA_VERSION + 1),
            ):
                retained_input = json.loads(json.dumps(pristine_input))
                if version is None:
                    retained_input.pop("schema_version")
                else:
                    retained_input["schema_version"] = version
                retained_input["runtime"] = "derivative-runtime-error"
                input_raw = project_input.canonical_project_input_bytes(retained_input)
                input_path.write_bytes(input_raw)
                manifest = json.loads(json.dumps(pristine_manifest))
                manifest["input_sha256"] = project_input.project_input_sha256(
                    input_raw
                )
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                variants[name] = project_instance_lint.lint_instance(
                    project_root,
                    contract_ref,
                    framework_root=REPO_ROOT,
                    expected_project_kind="downstream",
                )

            retained_input = json.loads(json.dumps(pristine_input))
            retained_input["runtime"] = "derivative-runtime-error"
            input_raw = project_input.canonical_project_input_bytes(retained_input)
            input_path.write_bytes(input_raw)
            manifest = json.loads(json.dumps(pristine_manifest))
            manifest["input_sha256"] = project_input.project_input_sha256(input_raw)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_schema = project_instance_lint.lint_instance(
                project_root,
                contract_ref,
                framework_root=REPO_ROOT,
                expected_project_kind="downstream",
            )

        for name in variants:
            with self.subTest(name=name):
                self.assertEqual(1, len(variants[name]["errors"]), variants[name])
                error = variants[name]["errors"][0]
                if name == "newer":
                    self.assertIn("newer than", error)
                    self.assertIn("framework checkout", error)
                else:
                    self.assertIn("current-only", error)
                    self.assertIn("manual update", error)
                self.assertNotIn("runtime", error)

        self.assertEqual(2, len(current_schema["errors"]), current_schema)
        self.assertIn(
            "project instance manifest runtime does not match retained project input",
            current_schema["errors"],
        )
        self.assertTrue(
            any(
                "downstream project input runtime must be one of" in error
                for error in current_schema["errors"]
            ),
            current_schema,
        )

    def test_project_instance_lint_stops_before_reading_symlinked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            contract_ref = ".mpa"
            contract_root = project_root / contract_ref
            contract_root.mkdir(parents=True)
            outside_manifest = project_root.parent / f"{project_root.name}-outside-instance.json"
            outside_manifest.write_text("{}\n", encoding="utf-8")
            (project_root / project_instance_lint.MANIFEST_NAME).symlink_to(outside_manifest)
            try:
                with mock.patch.object(
                    project_instance_lint,
                    "load_manifest",
                    side_effect=AssertionError("unsafe manifest read"),
                ):
                    result = project_instance_lint.lint_instance(
                        project_root,
                        contract_ref,
                        framework_root=REPO_ROOT,
                        expected_project_kind="downstream",
                    )
            finally:
                outside_manifest.unlink()

        self.assertTrue(
            any("must not include symlink components" in error for error in result["errors"]),
            result,
        )

    def test_nested_contract_root_passes_sync_and_core_conformance(self) -> None:
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
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                ),
                encoding="utf-8",
            )
            framework_ref = os.path.relpath(REPO_ROOT, project_root)
            bootstrap_arguments = [
                "project_bootstrap.py",
                "--answers",
                str(answers_path),
                "--project-root",
                str(project_root),
                "--contract-root",
                ".mpa/contracts",
                "--create-contract-root",
                "--runtime",
                "generic",
                "--framework-ref",
                framework_ref,
                "--framework-revision-policy",
                "live",
            ]
            with mock.patch.object(
                sys,
                "argv",
                [*bootstrap_arguments, "--dry-run"],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as dry_stdout:
                    dry_result = project_bootstrap.main()
            self.assertEqual(0, dry_result, dry_stdout.getvalue())
            dry_report = json.loads(dry_stdout.getvalue())

            with mock.patch.object(
                sys,
                "argv",
                [
                    *bootstrap_arguments,
                    "--approve-write-plan-sha256",
                    cast(str, dry_report["write_plan_sha256"]),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as bootstrap_stdout:
                    bootstrap_result = project_bootstrap.main()
            self.assertEqual(0, bootstrap_result, bootstrap_stdout.getvalue())
            self.assertTrue(
                (project_root / project_instance_lint.MANIFEST_NAME).is_file()
            )
            self.assertFalse(
                (
                    project_root
                    / ".mpa"
                    / "contracts"
                    / project_instance_lint.MANIFEST_NAME
                ).exists()
            )
            contract_text = (
                project_root / ".mpa" / "contracts" / "AGENT_PROJECT.md"
            ).read_text(encoding="utf-8")
            sync_result = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS_DIR / "project_contract_sync.py"),
                    "--strict-warnings",
                    str(project_root),
                    "--project-kind",
                    "downstream",
                    "--contract-root",
                    ".mpa/contracts",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            conformance_result = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS_DIR / "conformance_check.py"),
                    "--profile",
                    "core-project",
                    "--root",
                    str(project_root),
                    "--project-kind",
                    "downstream",
                    "--contract-root",
                    ".mpa/contracts",
                    "--format",
                    "json",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        preamble_lines = contract_text.split("## ", 1)[0].splitlines()
        expected_rule = integration_registry.render_project_file_references(
            project_contract_model.PROJECT_PREAMBLE_RULE,
            ".mpa/contracts",
        )
        expected_authority = integration_registry.render_project_file_references(
            project_contract_model.PROJECT_AUTHORITY_TEXT,
            ".mpa/contracts",
        )
        self.assertEqual(1, preamble_lines.count(expected_rule), preamble_lines)
        self.assertEqual(1, preamble_lines.count(expected_authority), preamble_lines)
        self.assertEqual(0, sync_result.returncode, sync_result.stdout + sync_result.stderr)
        self.assertEqual(0, conformance_result.returncode, conformance_result.stdout + conformance_result.stderr)

    def test_context_manifest_keeps_security_work_module_explicit(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--security", "--path", "practice_guides/security_audit.md"])

        self.assertIsNone(context_manifest.infer_task_module(args))

        args = parser.parse_args(["--review", "--path", "practice_guides/security_audit.md"])
        self.assertEqual("review", context_manifest.infer_task_module(args))

    def test_context_manifest_keeps_briefing_module_explicit(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--briefing"])

        self.assertIsNone(context_manifest.infer_task_module(args))

    def test_context_manifest_rejects_private_paths_by_default(self) -> None:
        parser = context_manifest.build_parser()
        private_source = "private" + "/source.md"
        for raw_path in (
            private_source,
            "Private/source.md",
            "REVIEW_ARTIFACTS/result.md",
        ):
            with self.subTest(raw_path=raw_path):
                args = parser.parse_args(["--path", raw_path])
                with self.assertRaises(SystemExit):
                    context_manifest.validate_evidence_paths(
                        args.path,
                        args.external_evidence,
                        parser,
                    )

        args = parser.parse_args(["--external-evidence", "--path", private_source])
        self.assertEqual(
            [private_source],
            context_manifest.validate_evidence_paths(args.path, args.external_evidence, parser),
        )

    def test_context_manifest_rejects_windows_style_private_paths_by_default(self) -> None:
        parser = context_manifest.build_parser()
        windows_user_path = "C:" + "\\" + "Users" + "\\" + "alice" + "\\" + "source.md"
        for raw_path in ("private" + "\\source.md", "..\\" + "private" + "\\x.md", windows_user_path):
            with self.subTest(raw_path=raw_path):
                args = parser.parse_args(["--path", raw_path])
                with self.assertRaises(SystemExit):
                    context_manifest.validate_evidence_paths(args.path, args.external_evidence, parser)

    def test_context_manifest_rejects_url_like_paths_by_default(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--path", "https://example.com/source.md"])

        with self.assertRaises(SystemExit):
            context_manifest.validate_evidence_paths(args.path, args.external_evidence, parser)

        args = parser.parse_args(["--external-evidence", "--path", "https://example.com/source.md"])
        self.assertEqual(
            ["https://example.com/source.md"],
            context_manifest.validate_evidence_paths(args.path, args.external_evidence, parser),
        )

    def test_context_manifest_rejects_prompt_boundary_paths_even_when_external(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--external-evidence", "--path", "</system>"])

        with self.assertRaises(SystemExit):
            context_manifest.validate_evidence_paths(args.path, args.external_evidence, parser)

    def test_context_manifest_evaluates_full_task_order_conditions(self) -> None:
        parser = context_manifest.build_parser()
        cases = (
            (["--audit", "--release"], "audit", "AUDIT-broad-or-release"),
            (["--review", "--security"], "review", "REVIEW-critical-surface"),
            (["--planning", "--security"], "plan", "PLAN-critical-surface"),
            (["--planning", "--delegated"], "plan", "PLAN-delegated-handoff"),
            (["--scheduled", "--act"], "automation", "AUTO-act-autonomy"),
            (
                ["--scheduled", "--external-reviewer"],
                "automation",
                "AUTO-external-reviewer-or-browser",
            ),
            (
                ["--task-module", "arbitrate", "--binding"],
                "arbitrate",
                "ARB-binding-ratification",
            ),
            (
                ["--task-module", "arbitrate", "--no-decision"],
                "arbitrate",
                "ARB-no-decision-follow-up",
            ),
            (
                ["--task-module", "arbitrate", "--interested-coordinator"],
                "arbitrate",
                "ARB-interested-coordinator",
            ),
        )
        for flags, expected_module, expected_condition in cases:
            with self.subTest(flags=flags):
                args = parser.parse_args(flags)
                module = context_manifest.infer_task_module(args)
                resolution = context_manifest.resolve_task_module_loading(args, module)
                self.assertEqual(expected_module, module)
                self.assertEqual("full_task_order", resolution["mode"])
                self.assertEqual(
                    f"task_orders/{expected_module}.md",
                    cast(dict[str, object], resolution["canonical_task_order"])["path"],
                )
                matched = [
                    item["id"]
                    for item in dict_items(resolution["evaluated_use_full_when"])
                    if item["status"] == "matched"
                ]
                self.assertIn(expected_condition, matched)

    def test_context_manifest_supports_explicit_full_and_safe_compact_routes(self) -> None:
        parser = context_manifest.build_parser()
        compact_args = parser.parse_args(["--review"])
        compact = context_manifest.resolve_task_module_loading(compact_args, "review")
        self.assertEqual("compact_module", compact["mode"])
        self.assertIsNone(compact["canonical_task_order"])
        self.assertEqual("unambiguous_task_intent", compact["selection_evidence"])

        explicit_args = parser.parse_args(["--task-module", "review"])
        explicit = context_manifest.resolve_task_module_loading(explicit_args, "review")
        self.assertEqual("compact_module", explicit["mode"])
        self.assertEqual("explicit_task_module", explicit["selection_evidence"])

        full_args = parser.parse_args(["--planning", "--full"])
        full = context_manifest.resolve_task_module_loading(full_args, "plan")
        self.assertEqual("full_task_order", full["mode"])
        self.assertTrue(full["explicit_full_task_order"])
        self.assertEqual("task_orders/plan.md", cast(dict[str, object], full["canonical_task_order"])["path"])

        conflicting_args = parser.parse_args(["--task-module", "review", "--audit"])
        conflicting_module = context_manifest.infer_task_module(conflicting_args)
        conflicting = context_manifest.resolve_task_module_loading(
            conflicting_args,
            conflicting_module,
        )
        self.assertIsNone(conflicting_module)
        self.assertEqual("unresolved", conflicting["mode"])
        self.assertEqual(["audit", "review"], conflicting["candidate_task_modules"])

        with mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--task-module", "unknown-workflow"])

    def test_context_manifest_reports_ambiguous_workflow_flags(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--review", "--audit"])
        module = context_manifest.infer_task_module(args)
        resolution = context_manifest.resolve_task_module_loading(args, module)

        self.assertIsNone(module)
        self.assertEqual("unresolved", resolution["mode"])
        self.assertEqual(["audit", "review"], resolution["candidate_task_modules"])

    def test_context_manifest_reads_catalog_once_through_safe_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog_path = root / "workflow_catalog.json"
            catalog_path.write_text('{"task_orders": []}', encoding="utf-8")

            self.assertEqual(
                {"task_orders": []},
                context_manifest.load_workflow_catalog(catalog_path),
            )
            os.link(catalog_path, root / "catalog-alias.json")
            with self.assertRaisesRegex(ValueError, "exactly one hard link"):
                context_manifest.load_workflow_catalog(catalog_path)

    def test_context_manifest_rejects_nonobject_catalog_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "workflow_catalog.json"
            catalog_path.write_text(
                '{"task_orders": ["not-an-object"]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "entries must be objects"):
                context_manifest.load_workflow_catalog(catalog_path)

    def test_context_manifest_rejects_ambiguous_consumer_projection(self) -> None:
        def duplicate_task_name(catalog: dict[str, object]) -> None:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            entries[1]["name"] = entries[0]["name"]

        def duplicate_task_path(catalog: dict[str, object]) -> None:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            entries[1]["path"] = entries[0]["path"]

        def duplicate_module_field(catalog: dict[str, object], field: str) -> None:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            modules = [
                cast(dict[str, object], entry["runtime_task_module"])
                for entry in entries
                if isinstance(entry.get("runtime_task_module"), dict)
            ]
            modules[1][field] = modules[0][field]

        def reset_direct_flags(catalog: dict[str, object]) -> list[dict[str, object]]:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            for entry in entries:
                entry.pop("direct_full_when_flags", None)
            return entries

        def duplicate_direct_owner(catalog: dict[str, object]) -> None:
            entries = reset_direct_flags(catalog)
            entries[0]["direct_full_when_flags"] = ["incident"]
            entries[1]["direct_full_when_flags"] = ["incident"]

        def invalid_direct_flag(catalog: dict[str, object]) -> None:
            entries = reset_direct_flags(catalog)
            entries[0]["direct_full_when_flags"] = ["external_evidence"]

        def wrong_task_path(catalog: dict[str, object]) -> None:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            entries[0]["path"] = "task_orders/wrong.md"

        def wrong_module_field(
            catalog: dict[str, object],
            field: str,
            value: str,
        ) -> None:
            entries = cast(list[dict[str, object]], catalog["task_orders"])
            module = next(
                cast(dict[str, object], entry["runtime_task_module"])
                for entry in entries
                if isinstance(entry.get("runtime_task_module"), dict)
            )
            module[field] = value

        def direct_module_coexistence(catalog: dict[str, object]) -> None:
            entries = reset_direct_flags(catalog)
            module_owner = next(
                entry
                for entry in entries
                if isinstance(entry.get("runtime_task_module"), dict)
            )
            module_owner["direct_full_when_flags"] = ["small"]

        cases = (
            (
                "duplicate-task-name",
                duplicate_task_name,
                context_manifest.load_direct_full_task_orders,
                "duplicate task order name",
            ),
            (
                "duplicate-task-path",
                duplicate_task_path,
                context_manifest.load_direct_full_task_orders,
                "duplicate task order path",
            ),
            (
                "duplicate-module-name",
                lambda catalog: duplicate_module_field(catalog, "name"),
                context_manifest.load_task_modules,
                "duplicate runtime task module name",
            ),
            (
                "duplicate-module-path",
                lambda catalog: duplicate_module_field(catalog, "path"),
                context_manifest.load_task_modules,
                "duplicate runtime task module path",
            ),
            (
                "duplicate-direct-owner",
                duplicate_direct_owner,
                context_manifest.load_direct_full_task_orders,
                "direct routing flag has multiple owners",
            ),
            (
                "invalid-direct-flag",
                invalid_direct_flag,
                context_manifest.load_direct_full_task_orders,
                "uses unknown routing flag: external_evidence",
            ),
            (
                "wrong-task-path",
                wrong_task_path,
                context_manifest.load_direct_full_task_orders,
                "path must equal the name-derived path: task_orders/init.md",
            ),
            (
                "wrong-module-path",
                lambda catalog: wrong_module_field(
                    catalog,
                    "path",
                    "runtime/task_modules/wrong.md",
                ),
                context_manifest.load_task_modules,
                "runtime_task_module.path must equal the name-derived path",
            ),
            (
                "wrong-canonical-task-path",
                lambda catalog: wrong_module_field(
                    catalog,
                    "canonical_task_order",
                    "task_orders/wrong.md",
                ),
                context_manifest.load_task_modules,
                "canonical_task_order must equal its owning task order path",
            ),
            (
                "direct-flags-with-runtime-module",
                direct_module_coexistence,
                context_manifest.load_direct_full_task_orders,
                "direct_full_when_flags cannot coexist with a runtime task module",
            ),
        )

        for name, mutate, loader, expected_error in cases:
            with self.subTest(name=name):
                malformed = json.loads(json.dumps(context_manifest.WORKFLOW_CATALOG))
                mutate(malformed)
                with self.assertRaisesRegex(ValueError, expected_error):
                    loader(malformed)

    def test_context_manifest_reports_unresolved_condition_metadata(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--review"])
        broken = dict(context_manifest.TASK_MODULES["review"])
        broken["use_full_when_conditions"] = []
        with mock.patch.dict(context_manifest.TASK_MODULES, {"review": broken}):
            resolution = context_manifest.resolve_task_module_loading(args, "review")

        self.assertEqual("unresolved", resolution["mode"])
        self.assertEqual("task_orders/review.md", cast(dict[str, object], resolution["canonical_task_order"])["path"])
        self.assertTrue(
            all(
                item["status"] == "unresolved"
                for item in dict_items(resolution["evaluated_use_full_when"])
            )
        )

    def test_context_manifest_condition_registry_matches_parser_destinations(
        self,
    ) -> None:
        parser = context_manifest.build_parser()
        parsed_destinations = set(vars(parser.parse_args([])))

        self.assertTrue(
            routing_policy.runtime_condition_flags() <= parsed_destinations
        )
        for option_strings, destination, _help_text in (
            routing_policy.context_condition_arguments()
        ):
            with self.subTest(destination=destination):
                args = parser.parse_args([option_strings[0]])
                self.assertTrue(getattr(args, destination))

    def test_context_manifest_condition_identity_drift_fails_closed(self) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--task-module", "ideate"])
        cases = (
            (
                "duplicate-id",
                lambda module: module["use_full_when_conditions"][1].__setitem__(
                    "id",
                    module["use_full_when_conditions"][0]["id"],
                ),
            ),
            (
                "duplicate-description",
                lambda module: module["use_full_when_conditions"][1].__setitem__(
                    "description",
                    module["use_full_when_conditions"][0]["description"],
                ),
            ),
            (
                "declared-description-drift",
                lambda module: module["use_full_when"].__setitem__(
                    0,
                    "a description without a machine rule",
                ),
            ),
            (
                "unknown-condition-flag",
                lambda module: module["use_full_when_conditions"][0][
                    "any_flags"
                ].append("nonexistent_runtime_flag"),
            ),
            (
                "parser-bool-outside-condition-registry",
                lambda module: module["use_full_when_conditions"][0][
                    "any_flags"
                ].append("external_evidence"),
            ),
            (
                "parser-control-outside-condition-registry",
                lambda module: module["use_full_when_conditions"][0][
                    "any_flags"
                ].append("task_module"),
            ),
        )

        for name, mutate in cases:
            with self.subTest(name=name):
                broken = json.loads(
                    json.dumps(context_manifest.TASK_MODULES["ideate"])
                )
                mutate(broken)
                with mock.patch.dict(
                    context_manifest.TASK_MODULES,
                    {"ideate": broken},
                ):
                    resolution = context_manifest.resolve_task_module_loading(
                        args,
                        "ideate",
                    )

                self.assertEqual("unresolved", resolution["mode"])
                self.assertIn(
                    "unresolved",
                    {
                        item["status"]
                        for item in dict_items(
                            resolution["evaluated_use_full_when"]
                        )
                    },
                )

    def test_context_manifest_condition_predicates_require_exact_booleans(
        self,
    ) -> None:
        parser = context_manifest.build_parser()
        args = parser.parse_args(["--task-module", "ideate"])
        args.project_write = 1

        resolution = context_manifest.resolve_task_module_loading(args, "ideate")

        self.assertEqual("unresolved", resolution["mode"])
        self.assertIn(
            "unresolved",
            {
                item["status"]
                for item in dict_items(resolution["evaluated_use_full_when"])
            },
        )

    def test_context_manifest_catalog_conditions_are_machine_evaluable(self) -> None:
        parser = context_manifest.build_parser()
        for module in sorted(context_manifest.TASK_MODULES):
            with self.subTest(module=module):
                args = parser.parse_args(["--task-module", module])
                resolution = context_manifest.resolve_task_module_loading(args, module)
                self.assertEqual("compact_module", resolution["mode"])
                self.assertNotIn(
                    "unresolved",
                    {item["status"] for item in dict_items(resolution["evaluated_use_full_when"])},
                )

    def test_prompt_load_report_detects_eager_practice_guide_imports(self) -> None:
        original_files = prompt_load_report.ENTRYPOINT_FILES
        original_load_text = prompt_load_report.load_text
        try:
            prompt_load_report.ENTRYPOINT_FILES = ["entry.md"]
            prompt_load_report.load_text = lambda rel: "@practice_guides/security_audit.md\nplain text\n"

            self.assertEqual(
                ["entry.md: @practice_guides/security_audit.md"],
                prompt_load_report.eager_practice_guide_imports(),
            )
        finally:
            prompt_load_report.ENTRYPOINT_FILES = original_files
            prompt_load_report.load_text = original_load_text

    def test_prompt_load_report_resolves_only_selected_downstream_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_root = root / "contract"
            contract_root.mkdir()
            (root / "CLAUDE.md").write_text(
                f"@{REPO_ROOT}/runtime/operative_charter.md\n"
                "@./contract/AGENT_PROJECT.md\n",
                encoding="utf-8",
            )
            (root / "AGENTS.md").write_text(
                "alternative runtime must not be inventoried\n",
                encoding="utf-8",
            )
            (contract_root / "AGENT_PROJECT.md").write_text(
                "# Runtime Project Contract\n\n"
                "## Active Project Modules\n\n"
                "- Annex A — Agent Profile (SOUL.md): SOUL.md\n"
                "- Annex C — Scope of Authority (AUTHORITY.md): AUTHORITY.md\n\n"
                "## Loading Rule\n\n"
                "Load applicable modules.\n",
                encoding="utf-8",
            )
            (contract_root / "STATEMENT_OF_WORK.md").write_text(
                "# Statement of Work\n",
                encoding="utf-8",
            )
            (contract_root / "TODO.md").write_bytes(
                b"# TODO\nactive_count: 0\n\xff body deliberately not decoded\n"
            )
            (contract_root / "DECISIONS.md").write_text(
                "# Decisions\ndurable_decision_count: 0\ndirective_count: 0\n",
                encoding="utf-8",
            )
            (root / "AUTHORITY.md").write_text(
                "# Scope of Authority\n",
                encoding="utf-8",
            )
            (root / "SOUL.md").write_text(
                "# Agent Profile\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with mock.patch("sys.stdout", new=stdout):
                return_code = prompt_load_report.main(
                    [
                        "--project-root",
                        str(root),
                        "--runtime",
                        "claude-code",
                        "--contract-root",
                        "contract",
                    ]
                )
            report = json.loads(stdout.getvalue())

        self.assertEqual(0, return_code, report)
        self.assertEqual([], report["errors"], report)
        self.assertEqual("selected_downstream_runtime", report["mode"])
        self.assertEqual("claude-code", report["selection"]["runtime"])
        mandatory = {
            (item["source"], item["path"], item["role"], item["load_mode"])
            for item in report["mandatory_files"]
        }
        self.assertIn(
            ("project", "CLAUDE.md", "selected_runtime_entrypoint", "full"),
            mandatory,
        )
        self.assertIn(
            ("framework", "runtime/operative_charter.md", "operative_charter", "full"),
            mandatory,
        )
        self.assertIn(
            ("project", "contract/AGENT_PROJECT.md", "project_contract", "full"),
            mandatory,
        )
        self.assertIn(
            ("project", "AUTHORITY.md", "scope_of_authority", "full"),
            mandatory,
        )
        self.assertIn(
            ("project", "contract/TODO.md", "startup_state_header", "header_only"),
            mandatory,
        )
        self.assertIn(
            (
                "project",
                "contract/DECISIONS.md",
                "startup_state_header",
                "header_only",
            ),
            mandatory,
        )
        header_records = [
            item
            for item in report["mandatory_files"]
            if item["load_mode"] == "header_only"
        ]
        self.assertTrue(header_records, report)
        self.assertTrue(
            all(item["status"] == "present_not_read" for item in header_records),
            report,
        )
        self.assertTrue(
            all("file_bytes" not in item and "file_lines" not in item for item in header_records),
            report,
        )
        self.assertNotIn(
            "AGENTS.md",
            {item["path"] for item in report["mandatory_files"]},
        )
        self.assertFalse(
            any(
                str(item["path"]).startswith("integrations/")
                for item in report["mandatory_files"]
            ),
            report,
        )
        dynamic_by_category = {
            item["category"]: item for item in report["unresolved_dynamic_loads"]
        }
        self.assertEqual("SOUL.md", dynamic_by_category["active_project_module"]["path"])
        self.assertEqual(
            "contract/STATEMENT_OF_WORK.md",
            dynamic_by_category["canonical_project_source"]["path"],
        )
        self.assertIn("workflow_procedure", dynamic_by_category)
        self.assertIn("practice_guides", dynamic_by_category)
        self.assertTrue(
            any(
                "not tokenizer output or prompt/context cost" in limitation
                for limitation in report["measurement_scope"]["limitations"]
            ),
            report,
        )

    def test_prompt_load_report_requires_canonical_authority_module_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text(
                f"Read `{REPO_ROOT}/runtime/operative_charter.md`.\n"
                "Read `AGENT_PROJECT.md`.\n",
                encoding="utf-8",
            )
            (root / "AGENT_PROJECT.md").write_text(
                "# Runtime Project Contract\n\n"
                "## Active Project Modules\n\n"
                "- Project Scope of Authority (AUTHORITY.md): AUTHORITY.md\n\n"
                "## Loading Rule\n",
                encoding="utf-8",
            )
            (root / "AUTHORITY.md").write_text(
                "# Scope of Authority\n",
                encoding="utf-8",
            )

            report = prompt_load_report.selected_runtime_load_surface(root, "codex")

        self.assertIn(
            "unknown Active Project Modules label: Project Scope of Authority (AUTHORITY.md)",
            string_items(report["errors"]),
        )
        self.assertNotIn(
            "scope_of_authority",
            {item["role"] for item in dict_items(report["mandatory_files"])},
        )

    def test_prompt_load_report_fails_closed_for_duplicate_module_sections_in_both_orders(
        self,
    ) -> None:
        authority_section = (
            "## Active Project Modules\n\n"
            "- Annex C — Scope of Authority (AUTHORITY.md): AUTHORITY.md\n"
        )
        profile_section = (
            "## Active Project Modules\n\n"
            "- Annex A — Agent Profile (SOUL.md): SOUL.md\n"
        )
        cases = (
            ("authority_first", authority_section, profile_section),
            ("authority_second", profile_section, authority_section),
        )
        expected_error = (
            "duplicate top-level Active Project Modules headings make module "
            "loading ambiguous"
        )

        for name, first, second in cases:
            with self.subTest(order=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "AGENTS.md").write_text(
                    f"Read `{REPO_ROOT}/runtime/operative_charter.md`.\n"
                    "Read `AGENT_PROJECT.md`.\n",
                    encoding="utf-8",
                )
                (root / "AGENT_PROJECT.md").write_text(
                    f"# Runtime Project Contract\n\n{first}\n{second}\n"
                    "## Loading Rule\n",
                    encoding="utf-8",
                )
                (root / "AUTHORITY.md").write_text(
                    "# Scope of Authority\n",
                    encoding="utf-8",
                )
                (root / "SOUL.md").write_text(
                    "# Agent Profile\n",
                    encoding="utf-8",
                )

                report = prompt_load_report.selected_runtime_load_surface(
                    root,
                    "codex",
                )

            self.assertEqual([expected_error], report["errors"], report)
            self.assertNotIn(
                "scope_of_authority",
                {item["role"] for item in dict_items(report["mandatory_files"])},
            )
            self.assertFalse(
                any(
                    item["category"] == "active_project_module"
                    for item in dict_items(report["unresolved_dynamic_loads"])
                ),
                report,
            )

    def test_active_project_modules_ignores_fenced_heading_examples(self) -> None:
        modules, errors = prompt_load_report.active_project_modules(
            "## Active Project Modules\n\n"
            "- Annex A — Agent Profile (SOUL.md): SOUL.md\n\n"
            "```md\n"
            "## Active Project Modules\n"
            "- Annex C — Scope of Authority (AUTHORITY.md): AUTHORITY.md\n"
            "```\n\n"
            "## Loading Rule\n"
        )

        self.assertEqual([], errors)
        self.assertEqual(
            [
                {
                    "label": "Annex A — Agent Profile (SOUL.md)",
                    "path": "SOUL.md",
                }
            ],
            modules,
        )

    def test_prompt_load_report_rejects_unsafe_active_module_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text(
                f"Read `{REPO_ROOT}/runtime/operative_charter.md`.\n"
                "Read `AGENT_PROJECT.md`.\n",
                encoding="utf-8",
            )
            (root / "AGENT_PROJECT.md").write_text(
                "# Runtime Project Contract\n\n"
                "## Active Project Modules\n\n"
                "- Annex C — Scope of Authority (AUTHORITY.md): ../AUTHORITY.md\n\n"
                "## Loading Rule\n",
                encoding="utf-8",
            )

            report = prompt_load_report.selected_runtime_load_surface(
                root,
                "codex",
            )

        self.assertTrue(
            any(
                "must be a safe repo-relative path" in error
                for error in string_items(report["errors"])
            ),
            report,
        )
        self.assertNotIn(
            "scope_of_authority",
            {item["role"] for item in dict_items(report["mandatory_files"])},
        )

    def test_project_state_lint_rejects_active_done_items_and_undated_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            decisions = root / "DECISIONS.md"
            todo.write_text("- [x] already finished\n", encoding="utf-8")
            decisions.write_text("- decision without date\n", encoding="utf-8")
            errors: list[str] = []
            warnings: list[str] = []

            project_state_lint.lint_todo(todo, errors, warnings)
            project_state_lint.lint_decisions(decisions, errors)

            self.assertIn(
                "TODO.md: completed items must be removed from active state",
                errors,
            )
            self.assertIn(
                "DECISIONS.md: decision entries must start with an ISO date bullet",
                errors,
            )

    def test_project_state_lint_rejects_uppercase_done_and_invalid_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            decisions = root / "DECISIONS.md"
            todo.write_text("- [X] already finished\n", encoding="utf-8")
            decisions.write_text("- 2026-99-99, impossible date\n", encoding="utf-8")
            errors: list[str] = []
            warnings: list[str] = []

            project_state_lint.lint_todo(todo, errors, warnings)
            project_state_lint.lint_decisions(decisions, errors)

            self.assertIn(
                "TODO.md: completed items must be removed from active state",
                errors,
            )
            self.assertIn(
                "DECISIONS.md: date bullet is not a valid ISO date: 2026-99-99",
                errors,
            )

    def test_project_state_lint_accepts_nested_bullets_and_marker_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            todo_example = root / "TODO_EXAMPLE.md"
            decisions = root / "DECISIONS.md"
            findings = root / "FINDINGS.md"
            feedback = root / "FRAMEWORK_FEEDBACK.md"
            todo.write_text("* [X] already finished\n", encoding="utf-8")
            todo_example.write_text(
                "```md\n"
                "* [X] example checklist only\n"
                "```\n"
                "- [ ] active item\n",
                encoding="utf-8",
            )
            decisions.write_text(
                "* 2026-06-12, decision_id: DEC-2026-06-12-01\n"
                "  Status: active\n"
                "  Scope: state parser fixtures\n"
                "  Decision: Accept supported Markdown bullet markers.\n"
                "  Rationale: Marker choice does not change record semantics.\n"
                "    - nested explanation\n"
                "    * nested alternate\n"
                "  Alternatives considered: Restrict records to hyphen bullets.\n"
                "  Evidence or verification: Parser behavior test.\n"
                "  Authority source: Project state template.\n"
                "  Supersession relationship: none\n"
                "  Review trigger: Parser contract change.\n",
                encoding="utf-8",
            )
            findings.write_text(
                "+ 2026-06-12, durable finding\n"
                "  - nested detail\n",
                encoding="utf-8",
            )
            feedback.write_text(
                "# Framework Feedback\n"
                "\n"
                "## Candidate Sequence\n"
                "\n"
                "Next candidate ID: `FF-0002`.\n"
                "\n"
                "## Open Candidates\n"
                "\n"
                "### FF-0001 - reusable source lookup reminder\n"
                "\n"
                "Status: candidate\n"
                "Category: duplicate-research\n"
                "Framework Target: task-order\n"
                "Evidence Basis: repeated-in-project\n"
                "Evidence Source: project-evidence\n"
                "Confidence: medium\n"
                "\n"
                "#### Sanitized Observation\n"
                "\n"
                "A downstream project repeatedly rechecked a source family already covered by an approved source registry.\n"
                "\n"
                "#### Abstracted Pattern\n"
                "\n"
                "Agents should inspect approved shared source registries before routine web research.\n"
                "\n"
                "#### Candidate Framework Change\n"
                "\n"
                "Add a concise source lookup reminder to the relevant task order.\n"
                "\n"
                "#### Applicability\n"
                "\n"
                "Applies to source-sensitive tasks with approved project or framework registries.\n"
                "\n"
                "#### Non-Goals And Limits\n"
                "\n"
                "Do not skip fresh source checks when required by the task.\n"
                "\n"
                "#### Source-Registry Implication\n"
                "\n"
                "None.\n"
                "\n"
                "#### Deterministic-Check Implication\n"
                "\n"
                "None.\n"
                "\n"
                "#### Evidence Summary\n"
                "\n"
                "Observed more than once in one project.\n"
                "\n"
                "#### Public Sources\n"
                "\n"
                "None.\n"
                "\n"
                "#### Anti-Leak Checklist\n"
                "\n"
                "- [x] No project, client, repository, branch, issue, pull-request, commit, team, user, or organization identifiers\n"
                "- [x] No local paths, private URLs, internal domains, hostnames, IP addresses, database names, bucket names, or service names\n"
                "- [x] No secrets, tokens, credentials, certificates, connection strings, environment values, or redacted-near-misses\n"
                "- [x] No personal names, emails, handles, customer data, private metrics, or proprietary business context\n"
                "- [x] No raw logs, stack traces, transcripts, screenshots, copied private code, or proprietary architecture\n"
                "- [x] Observation is abstracted before framework use\n"
                "\n"
                "#### Maintainer Decision\n"
                "\n"
                "Decision: pending\n"
                "Rationale:\n"
                "Framework Change:\n",
                encoding="utf-8",
            )
            todo_errors: list[str] = []
            example_errors: list[str] = []
            warnings: list[str] = []
            example_warnings: list[str] = []
            durable_errors: list[str] = []

            project_state_lint.lint_todo(todo, todo_errors, warnings)
            project_state_lint.lint_todo(todo_example, example_errors, example_warnings)
            project_state_lint.lint_decisions(decisions, durable_errors)
            project_state_lint.lint_findings(findings, durable_errors)
            project_state_lint.lint_framework_feedback(feedback, durable_errors, warnings)

            self.assertIn(
                "TODO.md: completed items must be removed from active state",
                todo_errors,
            )
            self.assertEqual([], warnings)
            self.assertEqual([], example_errors)
            self.assertEqual([], example_warnings)
            self.assertEqual([], durable_errors)

    def test_project_state_lint_requires_precedent_trigger_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            precedents = root / "PRECEDENTS.md"
            precedents.write_text(
                "\n".join(
                    [
                        "# Precedents",
                        "",
                        "- Citation: `P-2026-06-30-01`",
                        "  Trigger: source-chain apply verification",
                        "  Holding: apply verification must cover accepted findings",
                        "  Required Checks: check coverage IDs",
                        "  Source: audit",
                    ]
                ),
                encoding="utf-8",
            )
            errors: list[str] = []

            project_state_lint.lint_precedents(precedents, errors)

            self.assertIn(
                "PRECEDENTS.md: missing required section: ## Trigger Index",
                errors,
            )
            self.assertIn(
                "PRECEDENTS.md: missing required section: ## Records",
                errors,
            )

            precedents.write_text(
                "\n".join(
                    [
                        "# Precedents",
                        "",
                        "## Trigger Index",
                        "",
                        "- source-chain apply verification: `P-2026-06-30-01`",
                        "",
                        "## Records",
                        "",
                        "- Citation: `P-2026-06-30-01`",
                        "  Trigger: source-chain apply verification",
                        "  Holding: apply verification must cover accepted findings",
                        "  Required Checks: check coverage IDs",
                        "  Source: audit",
                    ]
                ),
                encoding="utf-8",
            )
            indexed_errors: list[str] = []

            project_state_lint.lint_precedents(precedents, indexed_errors)

            self.assertEqual([], indexed_errors)

            empty_errors: list[str] = []
            project_state_lint.lint_precedents(
                precedents,
                empty_errors,
                "# Precedents\n\n"
                "## Trigger Index\n\n"
                "- None.\n\n"
                "## Records\n\n"
                "- None.\n",
            )
            self.assertEqual([], empty_errors)

    def test_project_state_lint_rejects_uncited_and_field_spoofed_precedents(
        self,
    ) -> None:
        precedents = Path("PRECEDENTS.md")
        cases = {
            "uncited-record": (
                "# Precedents\n\n"
                "## Trigger Index\n\n"
                "- None.\n\n"
                "## Records\n\n"
                "- Trigger: incident\n"
                "  Holding: durable rule\n"
                "  Required Checks: verify it\n"
                "  Source: review\n",
                (
                    "malformed or orphan precedent content",
                    "Records must contain exact precedent records or the '- None.' sentinel",
                ),
            ),
            "field-spoofing": (
                "# Precedents\n\n"
                "## Trigger Index\n\n"
                "- incident: `P-2026-07-16-01`\n\n"
                "## Records\n\n"
                "- Citation: `P-2026-07-16-01`\n"
                "  Trigger: incident\n"
                "  Holding: prose mentions Required Checks: and Source: without either field\n",
                (
                    "precedent P-2026-07-16-01 on line",
                    "missing field: Required Checks",
                    "missing field: Source",
                ),
            ),
        }
        for case_id, (text, expected) in cases.items():
            with self.subTest(case_id=case_id):
                errors: list[str] = []
                project_state_lint.lint_precedents(precedents, errors, text)
                joined = "\n".join(errors)
                for fragment in expected:
                    self.assertIn(fragment, joined)

    def test_project_state_lint_uses_byte_budget_not_line_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            item_count = 300
            todo.write_text(
                "state_schema_version: 1\n"
                f"active_count: {item_count}\n\n"
                "# TODO\n\n"
                + "\n".join(f"- [ ] ID: synthetic-{index} bounded task" for index in range(item_count))
                + "\n",
                encoding="utf-8",
            )

            accepted = project_state_lint.lint_state_files(
                root,
                selected_names={"TODO.md"},
                require_core=False,
            )

            todo.write_bytes(b"x" * (project_state_lint.STATE_FILE_MAX_BYTES + 1))
            rejected = project_state_lint.lint_state_files(
                root,
                selected_names={"TODO.md"},
                require_core=False,
            )

        self.assertEqual([], accepted["errors"])
        self.assertEqual([], accepted["warnings"])
        self.assertTrue(
            any("exceeds the 1048576-byte input limit" in error for error in rejected["errors"]),
            rejected,
        )

    def test_project_state_lint_rejects_unsafe_state_input_snapshots(self) -> None:
        cases = ("invalid-utf8", "hardlink", "fifo")
        decisions_text = (
            "state_schema_version: 1\n"
            "durable_decision_count: 0\n"
            "directive_count: 0\n\n"
            "# Decisions\n"
        )
        todo_text = "state_schema_version: 1\nactive_count: 0\n\n# TODO\n"
        for case_id in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "DECISIONS.md").write_text(decisions_text, encoding="utf-8")
                todo = root / "TODO.md"
                if case_id == "invalid-utf8":
                    todo.write_bytes(b"state_schema_version: 1\n\xff")
                elif case_id == "hardlink":
                    seed = root / "todo-seed.md"
                    seed.write_text(todo_text, encoding="utf-8")
                    os.link(seed, todo)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("FIFO creation is unavailable")
                    os.mkfifo(todo)

                report = project_state_lint.lint_state_files(root)

            self.assertTrue(
                any(
                    "TODO.md" in error
                    and ("valid UTF-8" in error or "could not be read" in error)
                    for error in report["errors"]
                ),
                report,
            )

    def test_project_state_lint_consumes_one_immutable_state_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            todo.write_text(
                "state_schema_version: 1\n"
                "active_count: 1\n\n"
                "# TODO\n\n"
                "- [ ] ID: TASK-2026-07-12-01 active\n",
                encoding="utf-8",
            )
            (root / "DECISIONS.md").write_text(
                "state_schema_version: 1\n"
                "durable_decision_count: 0\n"
                "directive_count: 0\n\n"
                "# Decisions\n",
                encoding="utf-8",
            )
            real_reader = safe_paths.read_regular_file_bytes
            mutated = False

            def read_then_mutate(
                path: Path,
                *,
                description: str,
                max_bytes: int = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
                require_single_link: bool = True,
            ) -> bytes:
                nonlocal mutated
                raw = real_reader(
                    path,
                    description=description,
                    max_bytes=max_bytes,
                    require_single_link=require_single_link,
                )
                if path == todo and not mutated:
                    mutated = True
                    todo.write_text(
                        "state_schema_version: 1\n"
                        "active_count: 0\n\n"
                        "# TODO\n\n"
                        "- [x] completed\n",
                        encoding="utf-8",
                    )
                return raw

            with mock.patch.object(
                project_state_lint.safe_paths,
                "read_regular_file_bytes",
                side_effect=read_then_mutate,
            ):
                report = project_state_lint.lint_state_files(root)

        self.assertTrue(mutated)
        self.assertFalse(
            any("completed items must be removed" in error for error in report["errors"]),
            report,
        )

    def test_project_state_lint_requires_machine_readable_state_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            decisions = root / "DECISIONS.md"
            todo.write_text("# TODO\n\n- [ ] active item\n", encoding="utf-8")
            decisions.write_text("# Decisions\n\n- 2026-06-30, durable decision\n", encoding="utf-8")
            errors: list[str] = []

            project_state_lint.lint_state_header(todo, errors)
            project_state_lint.lint_state_header(decisions, errors)

        self.assertIn("TODO.md: missing machine-readable state header", errors)
        self.assertIn("DECISIONS.md: missing machine-readable state header", errors)

    def test_project_state_lint_rejects_zero_count_with_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            decisions = root / "DECISIONS.md"
            todo.write_text(
                "\n".join(
                    [
                        "state_schema_version: 1",
                        "active_count: 0",
                        "",
                        "# TODO",
                        "",
                        "- [ ] TODO-2026-06-30-01 active item",
                    ]
                ),
                encoding="utf-8",
            )
            decisions.write_text(
                "\n".join(
                    [
                        "state_schema_version: 1",
                        "durable_decision_count: 0",
                        "directive_count: 0",
                        "",
                        "# Decisions",
                        "",
                        "- 2026-06-30, durable decision",
                    ]
                ),
                encoding="utf-8",
            )
            errors: list[str] = []

            project_state_lint.lint_state_header(todo, errors)
            project_state_lint.lint_state_header(decisions, errors)

        self.assertIn("TODO.md: active_count is 0 but active state entries exist", errors)
        self.assertIn(
            "DECISIONS.md: durable_decision_count and directive_count are 0 but decision entries exist",
            errors,
        )

    def test_project_state_lint_rejects_header_shape_and_independent_decision_count_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            todo = root / "TODO.md"
            decisions = root / "DECISIONS.md"
            todo.write_text(
                "state_schema_version: 1\n"
                "active_count: 1\n"
                "active_count: 1\n"
                "unexpected_count: 0\n\n"
                "# TODO\n\n"
                "- [ ] TODO-2026-06-30-01 active item\n",
                encoding="utf-8",
            )
            decisions.write_text(
                "state_schema_version: 1\n"
                "durable_decision_count: 1\n"
                "directive_count: 0\n\n"
                "# Decisions\n\n"
                "- 2026-06-30, directive_id: DIR-2026-06-30-01; keep the release paused\n",
                encoding="utf-8",
            )
            errors: list[str] = []

            project_state_lint.lint_state_header(todo, errors)
            project_state_lint.lint_state_header(decisions, errors)

        self.assertIn("TODO.md: state header has duplicate fields: active_count", errors)
        self.assertIn("TODO.md: state header has unknown fields: unexpected_count", errors)
        self.assertTrue(any("durable_decision_count is 1, but 0 dated decision_id" in error for error in errors), errors)
        self.assertTrue(any("directive_count is 0, but 1 dated directive_id" in error for error in errors), errors)

    def test_project_state_lint_accepts_complete_durable_record_semantics(self) -> None:
        decisions_text = (
            "- 2026-06-10, decision_id: DEC-2026-06-10-01\n"
            "  Status: superseded\n"
            "  Scope: project state records\n"
            "  Decision: Use the first state representation.\n"
            "  Rationale: It met the initial project requirement.\n"
            "  Alternatives considered: No durable record.\n"
            "  Evidence or verification: Initial state validation.\n"
            "  Authority source: Project owner approval.\n"
            "  Supersession relationship: superseded by DEC-2026-06-11-01\n"
            "  Review trigger: State representation changes.\n"
            "\n"
            "- 2026-06-11, decision_id: DEC-2026-06-11-01\n"
            "  Status: active\n"
            "  Scope: project state records\n"
            "  Decision: Use the revised state representation.\n"
            "  Rationale: It closes the verified semantic gap.\n"
            "  Alternatives considered: Retain the first representation.\n"
            "  Evidence or verification: State parser tests.\n"
            "  Authority source: Project owner approval.\n"
            "  Supersession relationship: supersedes DEC-2026-06-10-01\n"
            "  Review trigger: State representation changes.\n"
            "\n"
            "- 2026-06-11, directive_id: DIR-2026-06-11-01\n"
            "  Status: active\n"
            "  Directive: Keep project state records machine-parseable.\n"
            "  Authority source: Project owner direction.\n"
            "  Scope: project state maintenance\n"
            "  Expiry or review trigger: Review if the state contract changes.\n"
            "  Affected files or surfaces: TODO.md and DECISIONS.md\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "DECISIONS.md"
            path.write_text(decisions_text, encoding="utf-8")
            errors: list[str] = []

            project_state_lint.lint_decisions(path, errors)

        self.assertEqual([], errors)

    def test_project_state_lint_rejects_invalid_durable_record_fields_and_ids(self) -> None:
        valid = (
            "- 2026-06-10, decision_id: DEC-ONE\n"
            "  Status: active\n"
            "  Scope: state records\n"
            "  Decision: Keep structured records.\n"
            "  Rationale: The fields carry durable context.\n"
            "  Alternatives considered: Unstructured prose.\n"
            "  Evidence or verification: Parser tests.\n"
            "  Authority source: Project owner approval.\n"
            "  Supersession relationship: none\n"
            "  Review trigger: State contract changes.\n"
            "\n"
            "- 2026-06-11, directive_id: DIR-ONE\n"
            "  Status: active\n"
            "  Directive: Keep records current.\n"
            "  Authority source: Project owner direction.\n"
            "  Scope: state maintenance\n"
            "  Expiry or review trigger: Review when state policy changes.\n"
            "  Affected files or surfaces: project state files\n"
        )
        cases = {
            "empty-field": (
                valid.replace("  Rationale: The fields carry durable context.\n", "  Rationale:\n"),
                "DECISIONS.md: DEC-ONE has empty fields: Rationale",
            ),
            "missing-field": (
                valid.replace("  Review trigger: State contract changes.\n", ""),
                "DECISIONS.md: DEC-ONE missing fields: Review trigger",
            ),
            "duplicate-field": (
                valid.replace("  Scope: state records\n", "  Scope: state records\n  Scope: duplicate\n"),
                "DECISIONS.md: DEC-ONE duplicates fields: Scope",
            ),
            "invalid-decision-status": (
                valid.replace("  Status: active\n", "  Status: archived\n", 1),
                "DECISIONS.md: DEC-ONE has invalid Status: archived",
            ),
            "invalid-directive-status": (
                valid.replace(
                    "- 2026-06-11, directive_id: DIR-ONE\n  Status: active\n",
                    "- 2026-06-11, directive_id: DIR-ONE\n  Status: archived\n",
                ),
                "DECISIONS.md: DIR-ONE has invalid Status: archived",
            ),
            "duplicate-id": (
                valid.replace("directive_id: DIR-ONE", "directive_id: DEC-ONE"),
                "DECISIONS.md: duplicate record ID: DEC-ONE",
            ),
            "empty-id": (
                valid.replace("decision_id: DEC-ONE", "decision_id:"),
                "must begin with a date, one record kind, and a nonempty record ID",
            ),
            "inline-record-prose": (
                valid.replace("decision_id: DEC-ONE", "decision_id: DEC-ONE; inline prose"),
                "DECISIONS.md: DEC-ONE record header must end after its ID",
            ),
        }
        for case_id, (content, expected) in cases.items():
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "DECISIONS.md"
                path.write_text(content, encoding="utf-8")
                errors: list[str] = []

                project_state_lint.lint_decisions(path, errors)

            self.assertTrue(any(expected in error for error in errors), errors)

    def test_project_state_lint_rejects_incoherent_supersession_references(self) -> None:
        valid = (
            "- 2026-06-10, decision_id: DEC-OLD\n"
            "  Status: superseded\n"
            "  Scope: state records\n"
            "  Decision: Use the old representation.\n"
            "  Rationale: It met the earlier requirement.\n"
            "  Alternatives considered: None.\n"
            "  Evidence or verification: Earlier validation.\n"
            "  Authority source: Project owner approval.\n"
            "  Supersession relationship: superseded by DEC-NEW\n"
            "  Review trigger: State contract changes.\n"
            "\n"
            "- 2026-06-11, decision_id: DEC-NEW\n"
            "  Status: active\n"
            "  Scope: state records\n"
            "  Decision: Use the new representation.\n"
            "  Rationale: It closes the semantic gap.\n"
            "  Alternatives considered: Keep the old representation.\n"
            "  Evidence or verification: Current parser tests.\n"
            "  Authority source: Project owner approval.\n"
            "  Supersession relationship: supersedes DEC-OLD\n"
            "  Review trigger: State contract changes.\n"
        )
        cases = {
            "unknown": (
                valid.replace("superseded by DEC-NEW", "superseded by DEC-MISSING"),
                "decision DEC-OLD references unknown decision ID: DEC-MISSING",
            ),
            "self": (
                valid.replace("superseded by DEC-NEW", "superseded by DEC-OLD"),
                "decision DEC-OLD cannot supersede or be superseded by itself",
            ),
            "missing-replacement": (
                valid.replace("superseded by DEC-NEW", "none", 1),
                "superseded decision DEC-OLD must reference its replacement",
            ),
            "malformed-relationship": (
                valid.replace("superseded by DEC-NEW", "replaced by DEC-NEW"),
                "DEC-OLD has invalid Supersession relationship",
            ),
            "active-forward-pointer": (
                valid.replace("Status: superseded", "Status: active", 1),
                "active decision DEC-OLD cannot use a 'superseded by' relationship",
            ),
            "wrong-target-status": (
                valid.replace("Status: superseded", "Status: active", 1).replace(
                    "Supersession relationship: superseded by DEC-NEW",
                    "Supersession relationship: none",
                ),
                "decision DEC-NEW supersedes DEC-OLD, but DEC-OLD has Status active; expected superseded",
            ),
        }
        for case_id, (content, expected) in cases.items():
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "DECISIONS.md"
                path.write_text(content, encoding="utf-8")
                errors: list[str] = []

                project_state_lint.lint_decisions(path, errors)

            self.assertTrue(any(expected in error for error in errors), errors)

    def test_project_state_lint_preserves_lightweight_todos_with_unique_ids(self) -> None:
        valid = (
            "state_schema_version: 1\n"
            "active_count: 2\n\n"
            "# TODO\n\n"
            "- [ ] ID: small-1 — inspect the current state\n"
            "* [ ] TASK-2026-06-12-01 verify the result\n"
        )
        cases = {
            "valid": (valid, None),
            "duplicate": (
                valid.replace("TASK-2026-06-12-01", "ID: small-1"),
                "TODO.md: duplicate active entry ID: small-1",
            ),
            "empty": (
                valid.replace("ID: small-1 — inspect the current state", "ID:"),
                "TODO.md: active entries must carry a nonempty ID",
            ),
            "missing": (
                valid.replace("ID: small-1 — inspect the current state", "inspect the current state"),
                "TODO.md: active entries must carry a nonempty ID",
            ),
        }
        for case_id, (content, expected) in cases.items():
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "TODO.md"
                path.write_text(content, encoding="utf-8")
                errors: list[str] = []

                project_state_lint.lint_state_header(path, errors)

            if expected is None:
                self.assertEqual([], errors)
            else:
                self.assertIn(expected, errors)

    def test_project_state_lint_rejects_unsafe_framework_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feedback = root / "FRAMEWORK_FEEDBACK.md"
            feedback.write_text(
                "## Candidate Sequence\n"
                "\n"
                "Next candidate ID: `FF-0002`.\n"
                "\n"
                "## Open Candidates\n"
                "\n"
                "### FF-0001 - unsafe private detail\n"
                "\n"
                "Status: promoted\n"
                "Category: other\n"
                "Framework Target: doctrine\n"
                "Evidence Basis: single-observation\n"
                "Evidence Source: project-evidence\n"
                "Confidence: high\n"
                "\n"
                "#### Sanitized Observation\n"
                "\n"
                "Observed at /" + "Users/example/downstream-project with TOKEN=abc.\n"
                "\n"
                "#### Maintainer Decision\n"
                "\n"
                "Decision: promote\n",
                encoding="utf-8",
            )
            errors: list[str] = []
            warnings: list[str] = []

            project_state_lint.lint_framework_feedback(feedback, errors, warnings)

            self.assertTrue(any("possible host path" in error for error in errors), errors)
            self.assertTrue(any("possible environment assignment" in error for error in errors), errors)
            self.assertTrue(any("missing sections" in error for error in errors), errors)
            self.assertTrue(any("promotes a single-observation candidate" in warning for warning in warnings), warnings)

    def test_framework_feedback_privacy_scan_inspects_comments_but_not_fences(self) -> None:
        hidden_path = "/" + "Users/example/hidden-project"
        fenced_path = "/" + "Users/example/fenced-example"
        text = (
            FRAMEWORK_FEEDBACK_EMPTY_STATE
            + f"<!-- private location: {hidden_path} -->\n"
            "```text\n"
            f"example only: {fenced_path}\n"
            "```\n"
        )
        errors: list[str] = []
        warnings: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            text,
        )

        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: possible host path in non-fenced content "
                "on line 8"
            ],
            errors,
        )
        self.assertEqual([], warnings)

    def test_framework_feedback_comment_fence_cannot_hide_later_privacy_leak(self) -> None:
        leaked_path = "/" + "Users/example/leaked-project"
        text = (
            FRAMEWORK_FEEDBACK_EMPTY_STATE
            + "<!--\n```text\n-->\n"
            + leaked_path
            + "\n```\n"
        )
        errors: list[str] = []
        warnings: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            text,
        )

        self.assertIn(
            "FRAMEWORK_FEEDBACK.md: possible host path in non-fenced content on line 11",
            errors,
        )

    def test_framework_feedback_section_grammar_accepts_template_and_valid_entry(
        self,
    ) -> None:
        template = (
            REPO_ROOT / "project_state_templates" / "FRAMEWORK_FEEDBACK.md"
        ).read_text(encoding="utf-8")
        template_attestations = tuple(
            line.removeprefix("- [ ] ")
            for line in template.splitlines()
            if line.startswith("- [ ] ")
        )
        self.assertEqual(
            template_attestations,
            project_state_lint.FRAMEWORK_FEEDBACK_ANTI_LEAK_ATTESTATIONS,
        )
        self.assertNotIn("## Entry Index", template)
        self.assertIn(
            "## Candidate Sequence\n\nNext candidate ID: `FF-0001`.",
            template,
        )

        for label, text in (
            ("clean-template", template),
            ("valid-entry", valid_framework_feedback_entry()),
            (
                "entry-body-none-bullet",
                valid_framework_feedback_entry().replace(
                    "#### Public Sources\n\nNone.\n\n",
                    "#### Public Sources\n\n- None.\n\n",
                ),
            ),
        ):
            with self.subTest(label=label):
                errors: list[str] = []
                warnings: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    text,
                )
                self.assertEqual([], errors)
                self.assertEqual([], warnings)

    def test_framework_feedback_owns_entries_only_under_open_candidates(self) -> None:
        valid = valid_framework_feedback_entry()
        entry_text = valid[valid.index("### FF-0001") :]
        duplicate_with_entries = (
            valid.replace("Next candidate ID: `FF-0002`.", "Next candidate ID: `FF-0003`.")
            + "\n## Open Candidates\n\n"
            + entry_text.replace("### FF-0001", "### FF-0002", 1)
        )
        misowned = (
            valid.replace("## Open Candidates", "## Policy")
            + "\n## Open Candidates\n\n- None.\n"
        )
        misowned_line = misowned.splitlines().index(
            "### FF-0001 - bounded feedback grammar"
        ) + 1
        free_form = (
            FRAMEWORK_FEEDBACK_EMPTY_STATE
            + "A candidate should use the declared entry grammar.\n"
        )
        cases = (
            (
                "entry-under-policy",
                misowned,
                [
                    "FRAMEWORK_FEEDBACK.md: framework feedback entry outside "
                    f"'## Open Candidates' on line {misowned_line}"
                ],
            ),
            (
                "free-form-open-candidate",
                free_form,
                [
                    "FRAMEWORK_FEEDBACK.md: unrecognized content outside an "
                    "entry in '## Open Candidates' on line 8"
                ],
            ),
            (
                "sentinel-with-entry",
                valid.replace(
                    "## Open Candidates\n\n",
                    "## Open Candidates\n\n- None.\n\n",
                ),
                [
                    "FRAMEWORK_FEEDBACK.md: '## Open Candidates' must not mix "
                    "'- None.' with framework feedback entries"
                ],
            ),
            ("explicit-empty-open-candidates", FRAMEWORK_FEEDBACK_EMPTY_STATE, []),
            (
                "comment-only-open-candidates",
                FRAMEWORK_FEEDBACK_EMPTY_STATE
                + "<!-- no current candidates -->\n",
                [],
            ),
            (
                "missing-empty-sentinel",
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES,
                [
                    "FRAMEWORK_FEEDBACK.md: '## Open Candidates' without entries "
                    "must contain exactly one '- None.' sentinel; found 0"
                ],
            ),
            (
                "duplicate-empty-sentinel",
                FRAMEWORK_FEEDBACK_EMPTY_STATE + "- None.\n",
                [
                    "FRAMEWORK_FEEDBACK.md: '## Open Candidates' without entries "
                    "must contain exactly one '- None.' sentinel; found 2"
                ],
            ),
            (
                "duplicate-empty-owner",
                FRAMEWORK_FEEDBACK_EMPTY_STATE + "\n## Open Candidates\n",
                [
                    "FRAMEWORK_FEEDBACK.md: must contain exactly one "
                    "'## Open Candidates' section; found 2"
                ],
            ),
            (
                "duplicate-owner-with-entries",
                duplicate_with_entries,
                [
                    "FRAMEWORK_FEEDBACK.md: must contain exactly one "
                    "'## Open Candidates' section; found 2"
                ],
            ),
        )

        for label, text, expected in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    text,
                )
                self.assertEqual(expected, errors)

    def test_framework_feedback_validates_candidate_sequence_when_present(self) -> None:
        invalid = valid_framework_feedback_entry().replace(
            "Next candidate ID: `FF-0002`.",
            "Next candidate ID: `FF-0001`.",
        )
        errors: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            invalid,
        )

        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: Next candidate ID FF-0001 must be "
                "greater than every current framework feedback entry ID"
            ],
            errors,
        )

        missing_sequence = valid_framework_feedback_entry().replace(
            FRAMEWORK_FEEDBACK_SEQUENCE,
            "",
        )
        errors = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            missing_sequence,
        )
        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: must contain exactly one "
                "'## Candidate Sequence' section; found 0"
            ],
            errors,
        )

    def test_framework_feedback_rejects_duplicate_known_section(self) -> None:
        text = valid_framework_feedback_entry().replace(
            "#### Applicability\n\nA bounded context.\n\n",
            "#### Applicability\n\nA bounded context.\n\n"
            "#### Applicability\n\nA second context.\n\n",
        )
        errors: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            text,
        )

        self.assertEqual(
            ["FRAMEWORK_FEEDBACK.md: FF-0001 duplicates sections: Applicability"],
            errors,
        )

    def test_framework_feedback_rejects_unknown_fourth_level_section(self) -> None:
        text = valid_framework_feedback_entry().replace(
            "#### Maintainer Decision\n",
            "#### Undeclared Review Notes\n\nNot part of the declared entry grammar.\n\n"
            "#### Maintainer Decision\n",
        )
        errors: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            text,
        )

        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: FF-0001 has unknown sections: "
                "Undeclared Review Notes"
            ],
            errors,
        )

    def test_framework_feedback_rejects_malformed_or_arbitrary_entry_heading(
        self,
    ) -> None:
        valid = valid_framework_feedback_entry()
        cases = (
            (
                "short-id",
                FRAMEWORK_FEEDBACK_EMPTY_STATE
                + "### FF-001 - bounded feedback grammar\n",
                "### FF-001 - bounded feedback grammar",
            ),
            (
                "missing-separator",
                FRAMEWORK_FEEDBACK_EMPTY_STATE
                + "### FF-0001 bounded feedback grammar\n",
                "### FF-0001 bounded feedback grammar",
            ),
            (
                "arbitrary-heading-after-entry",
                valid + "\n### Review Notes\n",
                "### Review Notes",
            ),
        )

        for label, text, malformed_heading in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    text,
                )
                line_number = text.splitlines().index(malformed_heading) + 1
                self.assertEqual(
                    [
                        "FRAMEWORK_FEEDBACK.md: malformed third-level heading "
                        f"on line {line_number}; expected '### FF-NNNN - title'"
                    ],
                    errors,
                )

    def test_framework_feedback_rejects_candidate_structure_without_entry(
        self,
    ) -> None:
        cases = (
            (
                "header-field",
                FRAMEWORK_FEEDBACK_EMPTY_STATE + "Status: candidate\n",
                "FRAMEWORK_FEEDBACK.md: candidate header field outside a valid "
                "entry on line 8",
            ),
            (
                "decision-field",
                FRAMEWORK_FEEDBACK_EMPTY_STATE + "Decision: pending\n",
                "FRAMEWORK_FEEDBACK.md: Maintainer Decision field outside a valid "
                "entry on line 8",
            ),
            (
                "fourth-level-section",
                FRAMEWORK_FEEDBACK_EMPTY_STATE
                + "#### Sanitized Observation\n",
                "FRAMEWORK_FEEDBACK.md: fourth-level feedback section outside a "
                "valid entry on line 8",
            ),
        )

        for label, text, expected in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    text,
                )
                self.assertEqual([expected], errors)

    def test_framework_feedback_rejects_invalid_entry_header_content(self) -> None:
        unexpected = valid_framework_feedback_entry().replace(
            "Confidence: medium\n\n",
            "Confidence: medium\nUnexpected Header: value\n\n",
        )
        unexpected_line = unexpected.splitlines().index("Unexpected Header: value") + 1
        cases = (
            (
                "unrecognized-header-line",
                unexpected,
                "FRAMEWORK_FEEDBACK.md: unrecognized nonblank entry-header "
                f"content on line {unexpected_line}",
            ),
            (
                "whitespace-title",
                FRAMEWORK_FEEDBACK_EMPTY_STATE + "### FF-0001 -    \n",
                "FRAMEWORK_FEEDBACK.md: framework feedback entry title must not be "
                "empty on line 8",
            ),
        )

        for label, text, expected in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    text,
                )
                self.assertEqual([expected], errors)

    def test_framework_feedback_enforces_declared_anti_leak_attestations(
        self,
    ) -> None:
        valid = valid_framework_feedback_entry()
        first_line = VALID_FRAMEWORK_FEEDBACK_CHECKLIST.splitlines()[0]
        first_attestation = first_line.removeprefix("- [x] ")
        missing_error = (
            "FRAMEWORK_FEEDBACK.md: FF-0001 anti-leak checklist is missing "
            f"declared attestations: {first_attestation}"
        )
        cases = (
            (
                "missing",
                valid.replace(first_line + "\n", ""),
                [missing_error],
            ),
            (
                "replaced",
                valid.replace(
                    first_line,
                    "- [x] Additional reviewed privacy attestation",
                ),
                [missing_error],
            ),
            (
                "duplicate",
                valid.replace(first_line, first_line + "\n" + first_line),
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 anti-leak checklist contains "
                    "duplicate item text"
                ],
            ),
            (
                "uncompleted",
                valid.replace(first_line, first_line.replace("[x]", "[ ]")),
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 anti-leak checklist must be "
                    "completed before maintainer review"
                ],
            ),
            (
                "unique-reviewed-extra",
                valid.replace(
                    "\n#### Maintainer Decision",
                    "- [x] Additional reviewed privacy attestation\n\n"
                    "#### Maintainer Decision",
                ),
                [],
            ),
            (
                "malformed-checkbox-state",
                valid.replace(
                    "\n#### Maintainer Decision",
                    "- [yes] Additional malformed privacy claim\n\n"
                    "#### Maintainer Decision",
                ),
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 anti-leak checklist "
                    "contains 1 malformed item(s)"
                ],
            ),
        )

        for label, text, expected in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    text,
                )
                self.assertEqual(expected, errors)

    def test_framework_feedback_rejects_empty_required_prose_section(self) -> None:
        text = valid_framework_feedback_entry().replace(
            "#### Evidence Summary\n\nOne sanitized observation.\n\n",
            "#### Evidence Summary\n\n```text\nfenced examples are not evidence\n```\n\n",
        )
        errors: list[str] = []

        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            text,
        )

        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: FF-0001 section 'Evidence Summary' "
                "has no substantive non-fenced content"
            ],
            errors,
        )

    def test_framework_feedback_requires_closed_evidence_source(self) -> None:
        def feedback_text(header_lines: list[str]) -> str:
            sections = (
                "#### Sanitized Observation\n\nA sanitized observation.\n\n"
                "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
                "#### Candidate Framework Change\n\nA bounded change.\n\n"
                "#### Applicability\n\nA bounded context.\n\n"
                "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
                "#### Source-Registry Implication\n\nNone.\n\n"
                "#### Deterministic-Check Implication\n\nNone.\n\n"
                "#### Evidence Summary\n\nOne sanitized observation.\n\n"
                "#### Public Sources\n\nNone.\n\n"
                "#### Anti-Leak Checklist\n\n"
                + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
                + "\n#### Maintainer Decision\n\n"
                "Decision: pending\n"
                "Rationale:\n"
                "Framework Change:\n"
            )
            return (
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
                + "### FF-0001 - evidence source schema\n\n"
                + "\n".join(header_lines)
                + "\n\n"
                + sections
            )

        valid_header = [
            "Status: candidate",
            "Category: other",
            "Framework Target: none",
            "Evidence Basis: single-observation",
            "Evidence Source: project-evidence",
            "Confidence: medium",
        ]

        missing_source = [
            line for line in valid_header if not line.startswith("Evidence Source:")
        ]
        errors: list[str] = []
        warnings: list[str] = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            feedback_text(missing_source),
        )
        self.assertEqual(
            ["FRAMEWORK_FEEDBACK.md: FF-0001 missing fields: Evidence Source"],
            errors,
        )

        invalid_source = [
            "Evidence Source: unsupported-source"
            if line.startswith("Evidence Source:")
            else line
            for line in valid_header
        ]
        errors = []
        warnings = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            feedback_text(invalid_source),
        )
        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: FF-0001 field 'Evidence Source' "
                "has invalid value: unsupported-source"
            ],
            errors,
        )

        primary_source_header = [
            "Framework Target: doctrine"
            if line.startswith("Framework Target:")
            else "Evidence Source: primary-external-source"
            if line.startswith("Evidence Source:")
            else line
            for line in valid_header
        ]
        errors = []
        warnings = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            feedback_text(primary_source_header),
        )
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

        source_in_recurrence_field = [
            "Evidence Basis: public-source-backed"
            if line.startswith("Evidence Basis:")
            else "Evidence Source: primary-external-source"
            if line.startswith("Evidence Source:")
            else line
            for line in valid_header
        ]
        errors = []
        warnings = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            warnings,
            feedback_text(source_in_recurrence_field),
        )
        self.assertEqual(
            [
                "FRAMEWORK_FEEDBACK.md: FF-0001 field 'Evidence Basis' "
                "has invalid value: public-source-backed"
            ],
            errors,
        )
        self.assertEqual([], warnings)

    def test_single_observation_promotion_warns_only_for_weak_evidence_sources(
        self,
    ) -> None:
        def feedback_text(evidence_source: str) -> str:
            return (
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
                + "### FF-0001 - promotion evidence source\n\n"
                "Status: promoted\n"
                "Category: other\n"
                "Framework Target: practice-guide\n"
                "Evidence Basis: single-observation\n"
                f"Evidence Source: {evidence_source}\n"
                "Confidence: medium\n\n"
                "#### Sanitized Observation\n\nA sanitized observation.\n\n"
                "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
                "#### Candidate Framework Change\n\nA bounded change.\n\n"
                "#### Applicability\n\nA bounded context.\n\n"
                "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
                "#### Source-Registry Implication\n\nNone.\n\n"
                "#### Deterministic-Check Implication\n\nNone.\n\n"
                "#### Evidence Summary\n\nOne sanitized observation.\n\n"
                "#### Public Sources\n\nNone.\n\n"
                "#### Anti-Leak Checklist\n\n"
                + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
                + "\n#### Maintainer Decision\n\n"
                "Decision: promote\n"
                "Rationale: The evidence supports semantic review.\n"
                "Framework Change: Advance the bounded candidate to semantic audit.\n"
            )

        for evidence_source in (
            "deterministic-tool-evidence",
            "primary-external-source",
        ):
            with self.subTest(evidence_source=evidence_source):
                errors: list[str] = []
                warnings: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    feedback_text(evidence_source),
                )
                self.assertEqual([], errors)
                self.assertEqual([], warnings)

        expected_warning = (
            "FRAMEWORK_FEEDBACK.md: FF-0001 promotes a single-observation candidate"
        )
        for evidence_source in (
            "project-evidence",
            "expert-commentary",
            "model-reviewer-advice",
            "insufficient-evidence",
        ):
            with self.subTest(evidence_source=evidence_source):
                errors = []
                warnings = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    feedback_text(evidence_source),
                )
                self.assertEqual([], errors)
                self.assertEqual([expected_warning], warnings)

    def test_framework_feedback_status_must_match_maintainer_decision(self) -> None:
        def feedback_text(status: str, decision: str) -> str:
            rationale = (
                "" if decision == "pending" else "The evidence supports this disposition."
            )
            framework_change = (
                "Advance the bounded candidate to semantic audit."
                if decision in {"promote", "adapt"}
                else ""
            )
            return (
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
                + "### FF-0001 - state relationship\n\n"
                f"Status: {status}\n"
                "Category: other\n"
                "Framework Target: none\n"
                "Evidence Basis: single-observation\n"
                "Evidence Source: project-evidence\n"
                "Confidence: medium\n\n"
                "#### Sanitized Observation\n\nA sanitized observation.\n\n"
                "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
                "#### Candidate Framework Change\n\nA bounded change.\n\n"
                "#### Applicability\n\nA bounded context.\n\n"
                "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
                "#### Source-Registry Implication\n\nNone.\n\n"
                "#### Deterministic-Check Implication\n\nNone.\n\n"
                "#### Evidence Summary\n\nOne sanitized observation.\n\n"
                "#### Public Sources\n\nNone.\n\n"
                "#### Anti-Leak Checklist\n\n"
                + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
                + "\n#### Maintainer Decision\n\n"
                f"Decision: {decision}\n"
                f"Rationale: {rationale}\n"
                f"Framework Change: {framework_change}\n"
            )

        consistent_pairs = (
            ("candidate", "pending"),
            ("needs-review", "pending"),
            ("promoted", "promote"),
            ("adapted", "adapt"),
            ("rejected", "reject"),
            ("no-action", "no-action"),
        )
        for status, decision in consistent_pairs:
            with self.subTest(status=status, decision=decision):
                errors: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    [],
                    feedback_text(status, decision),
                )
                self.assertEqual([], errors)

        for status in (
            "candidate",
            "needs-review",
            "promoted",
            "adapted",
            "rejected",
            "no-action",
        ):
            for decision in ("pending", "promote", "adapt", "reject", "no-action"):
                if (status, decision) in consistent_pairs:
                    continue
                with self.subTest(invalid_status=status, invalid_decision=decision):
                    errors = []
                    project_state_lint.lint_framework_feedback(
                        Path("FRAMEWORK_FEEDBACK.md"),
                        errors,
                        [],
                        feedback_text(status, decision),
                    )
                    self.assertEqual(
                        [
                            f"FRAMEWORK_FEEDBACK.md: FF-0001 status {status!r} is "
                            f"inconsistent with maintainer decision {decision!r}"
                        ],
                        errors,
                    )

    def test_framework_feedback_requires_decision_detail_cardinality_and_content(
        self,
    ) -> None:
        valid = valid_framework_feedback_entry()
        rejected = (
            valid.replace("Status: candidate", "Status: rejected")
            .replace("Decision: pending", "Decision: reject")
            .replace("Rationale:\n", "Rationale: None!\n")
        )
        rejected_tbd = rejected.replace("Rationale: None!", "Rationale:  TbD !!!")
        rejected_with_real_prose = rejected.replace(
            "Rationale: None!",
            "Rationale: None of the proposed changes survives source review.",
        )
        promoted_without_change = (
            valid.replace("Status: candidate", "Status: promoted")
            .replace(
                "Evidence Source: project-evidence",
                "Evidence Source: deterministic-tool-evidence",
            )
            .replace("Decision: pending", "Decision: promote")
            .replace(
                "Rationale:\n",
                "Rationale: Direct evidence supports semantic review.\n",
            )
        )
        duplicate_rationale = valid.replace(
            "Rationale:\n",
            "Rationale:\nRationale: duplicate\n",
        )
        missing_framework_change = valid.replace("Framework Change:\n", "")
        valid_promoted = promoted_without_change.replace(
            "Framework Change:\n",
            "Framework Change: Advance the candidate to semantic audit.\n",
        )
        promoted_tbd_change = promoted_without_change.replace(
            "Framework Change:\n",
            "Framework Change: TBD!\n",
        )
        cases = (
            (
                "none-punctuation-rationale",
                rejected,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 non-pending Maintainer "
                    "Decision requires a substantive Rationale"
                ],
            ),
            (
                "tbd-case-whitespace-punctuation-rationale",
                rejected_tbd,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 non-pending Maintainer "
                    "Decision requires a substantive Rationale"
                ],
            ),
            (
                "promote-framework-change",
                promoted_without_change,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 promote decision requires a "
                    "substantive Framework Change"
                ],
            ),
            (
                "duplicate-rationale",
                duplicate_rationale,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one "
                    "Rationale field inside Maintainer Decision; found 2"
                ],
            ),
            (
                "missing-framework-change",
                missing_framework_change,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one "
                    "Framework Change field inside Maintainer Decision; found 0"
                ],
            ),
            (
                "tbd-punctuation-framework-change",
                promoted_tbd_change,
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 promote decision requires a "
                    "substantive Framework Change"
                ],
            ),
            ("real-prose-beginning-with-none", rejected_with_real_prose, []),
            ("valid-promote", valid_promoted, []),
        )

        for label, text, expected in cases:
            with self.subTest(label=label):
                errors: list[str] = []
                warnings: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    text,
                )
                self.assertEqual(expected, errors)
                self.assertEqual([], warnings)

    def test_framework_feedback_doctrine_warning_allows_only_direct_structural_route(
        self,
    ) -> None:
        def feedback_text(category: str, evidence_source: str) -> str:
            return (
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
                + "### FF-0001 - doctrine evidence\n\n"
                "Status: candidate\n"
                f"Category: {category}\n"
                "Framework Target: doctrine\n"
                "Evidence Basis: single-observation\n"
                f"Evidence Source: {evidence_source}\n"
                "Confidence: high\n\n"
                "#### Sanitized Observation\n\nA structural contradiction.\n\n"
                "#### Abstracted Pattern\n\nOne owner per invariant.\n\n"
                "#### Candidate Framework Change\n\nCorrect the contradiction.\n\n"
                "#### Applicability\n\nThe affected doctrine only.\n\n"
                "#### Non-Goals And Limits\n\nNo empirical or generalized claim.\n\n"
                "#### Source-Registry Implication\n\nNone.\n\n"
                "#### Deterministic-Check Implication\n\nCheck exact parity.\n\n"
                "#### Evidence Summary\n\nDirect structural evidence.\n\n"
                "#### Public Sources\n\nNone.\n\n"
                "#### Anti-Leak Checklist\n\n"
                + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
                + "\n#### Maintainer Decision\n\n"
                "Decision: pending\n"
                "Rationale:\n"
                "Framework Change:\n"
            )

        warning = (
            "FRAMEWORK_FEEDBACK.md: FF-0001 targets doctrine without broad or "
            "public evidence"
        )
        cases = (
            ("contract-gap", "deterministic-tool-evidence", []),
            ("other", "deterministic-tool-evidence", [warning]),
            ("contract-gap", "project-evidence", [warning]),
        )
        for category, evidence_source, expected_warnings in cases:
            with self.subTest(category=category, evidence_source=evidence_source):
                errors: list[str] = []
                warnings: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    feedback_text(category, evidence_source),
                )
                self.assertEqual([], errors)
                self.assertEqual(expected_warnings, warnings)

    def test_framework_feedback_requires_one_decision_section_and_field(self) -> None:
        prefix = (
            FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
            + "### FF-0001 - decision cardinality\n\n"
            "Status: candidate\n"
            "Category: other\n"
            "Framework Target: none\n"
            "Evidence Basis: single-observation\n"
            "Evidence Source: project-evidence\n"
            "Confidence: medium\n\n"
            "#### Sanitized Observation\n\nA sanitized observation.\n\n"
            "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
            "#### Candidate Framework Change\n\nA bounded change.\n\n"
            "#### Applicability\n\nA bounded context.\n\n"
            "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
            "#### Source-Registry Implication\n\nNone.\n\n"
            "#### Deterministic-Check Implication\n\nNone.\n\n"
            "#### Evidence Summary\n\nOne sanitized observation.\n\n"
            "#### Public Sources\n\nNone.\n\n"
            "#### Anti-Leak Checklist\n\n"
            + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
            + "\n"
        )
        decision_error = (
            "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one Decision "
            "field inside Maintainer Decision; found 2"
        )
        section_error = (
            "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one Maintainer "
            "Decision section; found 2"
        )

        cases = (
            (
                "one-section-two-fields",
                "#### Maintainer Decision\n\n"
                "Decision: pending\nDecision: promote\nRationale:\nFramework Change:\n",
                [decision_error],
            ),
            (
                "two-sections-one-field",
                "#### Maintainer Decision\n\n"
                "Decision: pending\nRationale:\nFramework Change:\n\n"
                "#### Maintainer Decision\n\nAdditional reviewed context.\n",
                [section_error],
            ),
            (
                "two-sections-two-fields",
                "#### Maintainer Decision\n\n"
                "Decision: pending\nRationale:\nFramework Change:\n\n"
                "#### Maintainer Decision\n\nDecision: promote\n",
                [section_error, decision_error],
            ),
            (
                "one-section-no-field",
                "#### Maintainer Decision\n\nRationale:\nFramework Change:\n",
                [decision_error.replace("found 2", "found 0")],
            ),
            (
                "stray-field-outside-section",
                "Decision: promote\n\n"
                "#### Maintainer Decision\n\n"
                "Decision: pending\nRationale:\nFramework Change:\n",
                [
                    "FRAMEWORK_FEEDBACK.md: FF-0001 must not contain Decision "
                    "fields outside Maintainer Decision; found 1"
                ],
            ),
        )
        for shape, tail, expected_errors in cases:
            with self.subTest(shape=shape):
                errors: list[str] = []
                warnings: list[str] = []
                project_state_lint.lint_framework_feedback(
                    Path("FRAMEWORK_FEEDBACK.md"),
                    errors,
                    warnings,
                    prefix + tail,
                )
                self.assertEqual(expected_errors, errors)
                self.assertEqual([], warnings)

        errors = []
        project_state_lint.lint_framework_feedback(
            Path("FRAMEWORK_FEEDBACK.md"),
            errors,
            [],
            prefix,
        )
        self.assertEqual(
            [
                section_error.replace("found 2", "found 0"),
                decision_error.replace("found 2", "found 0"),
                "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one "
                "Rationale field inside Maintainer Decision; found 0",
                "FRAMEWORK_FEEDBACK.md: FF-0001 must contain exactly one "
                "Framework Change field inside Maintainer Decision; found 0",
            ],
            errors,
        )

    def test_framework_feedback_target_enum_matches_product_owners(self) -> None:
        expected_targets = {
            "doctrine",
            "runtime",
            "task-order",
            "practice-guide",
            "template",
            "integration",
            "conformance-profile",
            "public-documentation",
            "public-asset",
            "public-example",
            "support-tooling",
            "validation-script",
            "test-fixture",
            "source-registry",
            "none",
        }
        template = (
            REPO_ROOT / "project_state_templates" / "FRAMEWORK_FEEDBACK.md"
        ).read_text(encoding="utf-8")
        allowed_line = next(
            line
            for line in template.splitlines()
            if line.startswith("Framework Target: `")
        )
        template_targets = {
            item.strip().removeprefix("`").removesuffix("`")
            for item in allowed_line.removeprefix("Framework Target: ").split(",")
        }

        self.assertEqual(expected_targets, project_state_lint.FRAMEWORK_FEEDBACK_TARGETS)
        self.assertEqual(expected_targets, template_targets)
        self.assertEqual(
            expected_targets,
            project_state_lint.FRAMEWORK_FEEDBACK_ALLOWED_VALUES["Framework Target"],
        )

    def test_framework_feedback_rejects_duplicate_header_fields_order_independently(
        self,
    ) -> None:
        def feedback_text(header_lines: list[str]) -> str:
            return (
                FRAMEWORK_FEEDBACK_OPEN_CANDIDATES
                + "### FF-0001 - duplicate header field\n\n"
                + "\n".join(header_lines)
                + "\n\n"
                "#### Sanitized Observation\n\nA sanitized observation.\n\n"
                "#### Abstracted Pattern\n\nA reusable pattern.\n\n"
                "#### Candidate Framework Change\n\nA bounded change.\n\n"
                "#### Applicability\n\nA bounded context.\n\n"
                "#### Non-Goals And Limits\n\nNo broader claim.\n\n"
                "#### Source-Registry Implication\n\nNone.\n\n"
                "#### Deterministic-Check Implication\n\nNone.\n\n"
                "#### Evidence Summary\n\nOne sanitized observation.\n\n"
                "#### Public Sources\n\nNone.\n\n"
                "#### Anti-Leak Checklist\n\n"
                + VALID_FRAMEWORK_FEEDBACK_CHECKLIST
                + "\n#### Maintainer Decision\n\n"
                "Decision: pending\n"
                "Rationale:\n"
                "Framework Change:\n"
            )

        values_by_field = {
            "Status": ("candidate", "adapted"),
            "Category": ("other", "contract-gap"),
            "Framework Target": ("none", "task-order"),
            "Evidence Basis": ("single-observation", "repeated-in-project"),
            "Evidence Source": ("project-evidence", "deterministic-tool-evidence"),
            "Confidence": ("low", "high"),
        }
        base_header = {
            "Status": "candidate",
            "Category": "other",
            "Framework Target": "none",
            "Evidence Basis": "single-observation",
            "Evidence Source": "project-evidence",
            "Confidence": "medium",
        }

        for field, pair in values_by_field.items():
            for order in (pair, tuple(reversed(pair))):
                with self.subTest(field=field, order=order):
                    header_lines = [
                        f"{name}: {value}"
                        for name, value in base_header.items()
                        if name != field
                    ]
                    header_lines.extend(f"{field}: {value}" for value in order)
                    errors: list[str] = []
                    warnings: list[str] = []

                    project_state_lint.lint_framework_feedback(
                        Path("FRAMEWORK_FEEDBACK.md"),
                        errors,
                        warnings,
                        feedback_text(header_lines),
                    )

                    self.assertEqual(
                        [f"FRAMEWORK_FEEDBACK.md: FF-0001 duplicates fields: {field}"],
                        errors,
                    )
                    self.assertEqual([], warnings)

    def test_reviewer_lane_feedback_lint_accepts_structured_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            task_orders = root / "task_orders"
            reports.mkdir()
            task_orders.mkdir()
            (reports / "lane.md").write_text("# Lane Evidence\n", encoding="utf-8")
            (task_orders / "orchestrate.md").write_text("# Orchestrate\n", encoding="utf-8")
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'REVIEWER_LANE_USED {"lane_id":"codex_subagent","task_ref":"T1","lane_class":"local_subagent","purpose":"schema review","output_ref":"reports/lane.md","evidence_refs":["reports/lane.md"]}\n'
                'REVIEWER_FINDING_ACCEPTED {"finding_id":"T1-F1","source_lane_id":"codex_subagent","evidence_ref":"reports/lane.md","action_ref":"task_orders/orchestrate.md","reason":"Finding identified a missing marker contract."}\n'
                'REVIEWER_FINDING_REJECTED {"finding_id":"T1-F2","source_lane_id":"codex_subagent","evidence_ref":"reports/lane.md","reason_category":"unsupported","reason":"Finding lacked inspected evidence."}\n'
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Converted review risk into a concrete check.","evidence_refs":["reports/lane.md"],"routing_implication":"Use for schema and contract review.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertEqual([], result["errors"])
        self.assertEqual([], result["warnings"])

    def test_reviewer_lane_feedback_lint_rejects_http_evidence_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Useful for marker review.","evidence_refs":["http://example.com/review"],"routing_implication":"Use for schema review.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertIn(
            "line 3: external evidence reference must use https: http://example.com/review",
            result["errors"],
        )

    def test_reviewer_lane_feedback_lint_rejects_empty_typed_and_unsafe_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n\n"
                'REVIEWER_LANE_USED {"lane_id":"lane_one","task_ref":"","lane_class":"local_subagent","purpose":"schema review","output_ref":[],"evidence_refs":"reports/lane.md"}\n'
                'LANE_FIT_OBSERVATION {"lane_id":"lane_two","task_ref":"T2","claim_type":"strength","claim":"Useful for review.","evidence_refs":["https://localhost/review"],"routing_implication":"Use for schema review.","confidence":"medium"}\n',
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        errors = result["errors"]
        self.assertTrue(any("field task_ref must be a non-empty string" in error for error in errors), errors)
        self.assertTrue(any("output_ref must be a non-empty string reference" in error for error in errors), errors)
        self.assertTrue(any("evidence_refs must be a non-empty list" in error for error in errors), errors)
        self.assertTrue(any("unsafe external evidence reference" in error for error in errors), errors)

    def test_reviewer_lane_feedback_cli_preserves_symlink_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.md"
            target.write_text("# Feedback\n", encoding="utf-8")
            linked = root / "REVIEWER_LANE_FEEDBACK.md"
            linked.symlink_to(target)

            with mock.patch(
                "sys.argv",
                [
                    "lint_reviewer_lane_feedback.py",
                    "--root",
                    str(root),
                    "--path",
                    str(linked),
                ],
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    result = lint_reviewer_lane_feedback.main()

        self.assertEqual(1, result)
        self.assertIn("reviewer feedback file must not be a symlink", stdout.getvalue())

    def test_reviewer_lane_feedback_rejects_hardlinked_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            reports.mkdir()
            seed = root / "seed.md"
            seed.write_text("# Evidence\n", encoding="utf-8")
            evidence = reports / "evidence.md"
            os.link(seed, evidence)
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n\n"
                'LANE_FIT_OBSERVATION {"lane_id":"lane_one","task_ref":"T1","claim_type":"strength","claim":"Useful for review.","evidence_refs":["reports/evidence.md"],"routing_implication":"Use for review.","confidence":"medium"}\n'
                "\n## Lane: lane_one\n\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertTrue(
            any("stable bounded regular file" in error for error in result["errors"]),
            result,
        )

    def test_reviewer_lane_feedback_lint_accepts_transcript_named_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            reports.mkdir()
            (reports / "reviewer_transcript_findings.md").write_text("# Reviewed Findings\n", encoding="utf-8")
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Useful for marker review.","evidence_refs":["reports/reviewer_transcript_findings.md"],"routing_implication":"Use for schema review.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertEqual([], result["errors"])

    def test_reviewer_lane_feedback_lint_rejects_raw_log_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Useful for marker review.","evidence_refs":[".'
                'codex/session.jsonl"],"routing_implication":"Use for schema review.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertTrue(
            any("raw logs or transcripts cannot be primary evidence" in error for error in result["errors"]),
            result["errors"],
        )

    def test_reviewer_lane_feedback_lint_scans_fenced_content_for_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            host_path = "/" + "Users" + "/alice/" + "private" + "/project/session.txt"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                "```text\n"
                f"Raw transcript from {host_path}\n"
                "```\n"
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        self.assertTrue(any("possible host path" in error for error in result["errors"]), result["errors"])

    def test_reviewer_lane_feedback_lint_rejects_vote_and_model_comparison_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            reports.mkdir()
            (reports / "lane.md").write_text("# Lane Evidence\n", encoding="utf-8")
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"codex_subagent","task_ref":"T1","claim_type":"strength","claim":"Reviewer A had a 4-1 majority, the votes favored it, and Reviewer B found more issues.","evidence_refs":["reports/lane.md"],"routing_implication":"Always route to that reviewer consensus.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        errors = result["errors"]
        self.assertTrue(any("anti-benchmark wording" in error for error in errors), errors)

    def test_reviewer_lane_feedback_lint_rejects_caveated_model_comparison_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            reports.mkdir()
            (reports / "lane.md").write_text("# Lane Evidence\n", encoding="utf-8")
            feedback = root / "REVIEWER_LANE_FEEDBACK.md"
            feedback.write_text(
                "# Reviewer Lane Feedback\n"
                "\n"
                'LANE_FIT_OBSERVATION {"lane_id":"synthetic_subagent","task_ref":"T1","claim_type":"limit","claim":"The reviewer found more issues without enough inspected evidence.","evidence_refs":["reports/lane.md"],"routing_implication":"Do not use this as routing evidence.","confidence":"medium"}\n'
                "\n"
                "## Lane: codex_subagent\n"
                "\n"
                "Runtime Class: local_subagent\n"
                "Evidence Basis: single-observation\n"
                "Confidence: medium\n",
                encoding="utf-8",
            )

            result = lint_reviewer_lane_feedback.lint(feedback, root)

        errors = result["errors"]
        self.assertTrue(any("anti-benchmark wording" in error for error in errors), errors)
