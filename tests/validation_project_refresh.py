"""Lifecycle tests for retained downstream project refreshes."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from typing import Any, Callable, Mapping, cast
from unittest import mock

from tests.validation_test_support import (
    REPO_ROOT,
    TEST_FRAMEWORK_RUNNER,
    compile_adjacent_bytecode,
    run_bounded,
    valid_automation_job,
)

import bootstrap_transaction  # noqa: E402
import integration_registry  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_model  # noqa: E402
import project_input  # noqa: E402
import project_refresh  # noqa: E402
import project_state_identity  # noqa: E402


def _materialize_project(
    project_root: Path,
    *,
    runtime: str = "generic",
    runtime_wrappers: tuple[str, ...] = (),
    revision_policy: str = "live",
    contract_root_ref: str = ".",
    answer_overrides: Mapping[str, object] | None = None,
) -> None:
    answers: dict[str, object] = {
        "bootstrap_mode": "minimal",
        "agent": "Agent",
        "project_name": "Demo",
        "date": "2026-07-14",
        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
    }
    if answer_overrides is not None:
        answers.update(answer_overrides)
    framework_reference = os.path.relpath(REPO_ROOT, project_root)
    input_text = project_input.render_project_input(
        project_kind="downstream",
        contract_root=contract_root_ref,
        runtime=runtime,
        framework_reference=framework_reference,
        framework_revision_policy=revision_policy,
        answers=answers,
        runtime_wrappers=runtime_wrappers,
    )
    outputs = project_bootstrap.render_output_files(
        answers,
        runtime,
        framework_reference,
        project_kind="downstream",
        contract_root_ref=contract_root_ref,
        effective_date="2026-07-14",
        runtime_wrappers=runtime_wrappers,
    )
    input_name = project_bootstrap.project_relative_output(
        contract_root_ref,
        project_input.INPUT_NAME,
    )
    outputs[input_name] = input_text
    managed, immutable, mutable = project_bootstrap.project_instance_file_sets(
        answers=answers,
        runtime=runtime,
        project_kind="downstream",
        contract_root_ref=contract_root_ref,
        runtime_wrappers=runtime_wrappers,
    )
    outputs[project_bootstrap.INSTANCE_MANIFEST] = (
        project_bootstrap.render_instance_manifest(
            input_bytes=input_text.encode("utf-8"),
            project_kind="downstream",
            contract_root_ref=contract_root_ref,
            runtime=runtime,
            framework_reference=framework_reference,
            framework_revision_policy=revision_policy,
            framework_reference_status="verified",
            managed_files=managed,
            immutable_files=immutable,
            mutable_files=mutable,
            runtime_wrapper_outputs=integration_registry.wrapper_output_map(
                runtime,
                list(runtime_wrappers),
                REPO_ROOT,
            ),
            rendered_outputs=outputs,
            active_profiles=project_bootstrap.active_project_profiles(
                answers,
                project_kind="downstream",
            ),
            effective_date="2026-07-14",
        )
    )
    for name, content in outputs.items():
        target = project_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _run_cli(arguments: list[str]) -> tuple[int, dict[str, Any]]:
    with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        code = project_refresh.main(arguments)
    return code, json.loads(stdout.getvalue())


def _warning_ids(plan: dict[str, object]) -> list[str]:
    warnings = plan.get("warnings", [])
    assert isinstance(warnings, list)
    return [
        str(item["id"])
        for item in warnings
        if isinstance(item, dict) and "id" in item
    ]


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | str | None]]:
    """Capture the complete controlled tree independently of a refresh plan."""

    snapshot: dict[str, tuple[str, int, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode, None)
        elif path.is_file():
            snapshot[relative] = ("file", mode, path.read_bytes())
        else:
            snapshot[relative] = ("other", mode, None)
    return snapshot


class ProjectRefreshLifecycleTests(unittest.TestCase):
    def test_project_refresh_ignores_cache_and_rejects_package_shadows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts_root = root / "scripts"
            shutil.copytree(
                REPO_ROOT / "scripts",
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
                    str(scripts_root / "project_refresh.py"),
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
                    str(scripts_root / "project_refresh.py"),
                    "--help",
                ],
                cwd=root,
                check=False,
            )
            self.assertFalse(package_marker.exists())

        self.assertNotEqual(0, shadow_result.returncode)
        self.assertIn(
            "project refresh rejected local import shadow: bootstrap_transaction",
            shadow_result.stderr,
        )

    def test_real_cli_process_reports_json_success_and_argparse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            script = REPO_ROOT / "scripts" / "project_refresh.py"
            inspect_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(script),
                    "inspect",
                    "--project-root",
                    str(project_root),
                    "--check",
                ],
                cwd=project_root,
                check=False,
            )
            plan_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(script),
                    "plan",
                    "--project-root",
                    str(project_root),
                ],
                cwd=project_root,
                check=False,
            )
            invalid_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(script),
                    "inspect",
                    "--project-root",
                    str(project_root),
                    "--unknown-option",
                ],
                cwd=project_root,
                check=False,
            )
            abbreviated_result = run_bounded(
                [
                    sys.executable,
                    "-E",
                    "-S",
                    "-B",
                    str(script),
                    "inspect",
                    "--project-root",
                    str(project_root),
                    "--che",
                ],
                cwd=project_root,
                check=False,
            )

        self.assertEqual(0, inspect_result.returncode, inspect_result.stderr)
        self.assertEqual("", inspect_result.stderr)
        self.assertEqual("current", json.loads(inspect_result.stdout)["status"])
        self.assertEqual(0, plan_result.returncode, plan_result.stderr)
        self.assertEqual("", plan_result.stderr)
        self.assertEqual("no-op", json.loads(plan_result.stdout)["mode"])
        self.assertEqual(2, invalid_result.returncode)
        self.assertEqual("", invalid_result.stdout)
        self.assertIn("usage:", invalid_result.stderr)
        self.assertIn("unrecognized arguments: --unknown-option", invalid_result.stderr)
        self.assertEqual(2, abbreviated_result.returncode)
        self.assertEqual("", abbreviated_result.stdout)
        self.assertIn("usage:", abbreviated_result.stderr)
        self.assertIn("unrecognized arguments: --che", abbreviated_result.stderr)

    def test_root_receipt_selects_nested_contract_and_rejects_explicit_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            contract_ref = "contracts/authority"
            _materialize_project(
                project_root,
                contract_root_ref=contract_ref,
            )
            retained_input = json.loads(
                (
                    project_root
                    / project_bootstrap.project_relative_output(
                        contract_ref,
                        project_input.INPUT_NAME,
                    )
                ).read_text(encoding="utf-8")
            )
            answers_path = root / "candidate-answers.json"
            answers_path.write_text(
                json.dumps(retained_input["answers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            inspected = project_refresh.inspect_project(project_root)
            planned = project_refresh.build_plan(project_root)
            mismatched = project_refresh.inspect_project(project_root, ".")
            candidate, candidate_errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=None,
                runtime="generic",
                framework_reference=str(retained_input["framework_reference"]),
                framework_revision_policy="live",
            )

        self.assertEqual("current", inspected["status"], inspected)
        self.assertEqual(contract_ref, inspected["contract_root"])
        self.assertIsNotNone(planned.payload, planned.errors)
        assert planned.payload is not None
        self.assertEqual("no-op", planned.payload["mode"])
        self.assertEqual(contract_ref, planned.payload["current_contract_root"])
        self.assertEqual("invalid", mismatched["status"], mismatched)
        self.assertTrue(
            any(
                "does not match the root-scoped" in error
                for error in cast(list[str], mismatched["errors"])
            ),
            mismatched,
        )
        self.assertEqual([], candidate_errors)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(contract_ref, candidate["contract_root"])

    def test_nested_refresh_keeps_selected_wrappers_root_scoped_and_receipted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            contract_ref = "contracts/authority"
            _materialize_project(
                project_root,
                runtime="codex",
                contract_root_ref=contract_ref,
            )
            retained_input = json.loads(
                (
                    project_root
                    / project_bootstrap.project_relative_output(
                        contract_ref,
                        project_input.INPUT_NAME,
                    )
                ).read_text(encoding="utf-8")
            )
            answers_path = root / "candidate-answers.json"
            answers_path.write_text(
                json.dumps(retained_input["answers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            selected_wrappers = ("project_refresh", "project_init")
            candidate, candidate_errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=contract_ref,
                runtime="codex",
                runtime_wrappers=selected_wrappers,
                framework_reference=str(retained_input["framework_reference"]),
                framework_revision_policy="live",
            )
            assert candidate is not None
            built = project_refresh.build_plan(
                project_root,
                contract_ref,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            expected_wrapper_outputs = integration_registry.wrapper_output_map(
                "codex",
                list(selected_wrappers),
                REPO_ROOT,
            )

        self.assertEqual([], candidate_errors)
        self.assertEqual(["project_init", "project_refresh"], candidate["runtime_wrappers"])
        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        receipt = json.loads(
            built.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
        )
        operations = {
            str(operation["path"]): operation
            for operation in cast(
                list[dict[str, object]],
                built.payload["operations"],
            )
        }
        self.assertEqual(expected_wrapper_outputs, receipt["runtime_wrapper_outputs"])
        self.assertIn(
            "REVISE-RUNTIME-WRAPPERS",
            cast(list[str], built.payload["required_actions"]),
        )
        for output in expected_wrapper_outputs.values():
            self.assertEqual("create", operations[output]["action"])
            self.assertIn(output, built.target_outputs)
            self.assertFalse(output.startswith(f"{contract_ref}/"))
        self.assertIn("AGENTS.md", built.target_outputs)
        self.assertNotIn(f"{contract_ref}/AGENTS.md", built.target_outputs)
        self.assertIn(f"{contract_ref}/STATEMENT_OF_WORK.md", built.target_outputs)

    def test_source_monitor_brief_refreshes_as_generated_immutable_procedure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(
                project_root,
                answer_overrides={"include_source_monitor_researcher": True},
            )
            original_renderer = project_bootstrap.state_template_content

            def revised_template(
                name: str,
                answers: dict[str, object],
                framework_ref: str | None = None,
                *,
                contract_root_ref: str = ".",
            ) -> str:
                rendered = original_renderer(
                    name,
                    answers,
                    framework_ref,
                    contract_root_ref=contract_root_ref,
                )
                if name == "SOURCE_MONITOR_RESEARCHER.md":
                    return rendered + "\n<!-- reviewed framework procedure revision -->\n"
                return rendered

            with mock.patch.object(
                project_bootstrap,
                "state_template_content",
                side_effect=revised_template,
            ):
                built = project_refresh.build_plan(
                    project_root,
                    ".",
                    post_apply_backout={"kind": "none"},
                )

        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        operation = next(
            item
            for item in cast(list[dict[str, object]], built.payload["operations"])
            if item["path"] == "SOURCE_MONITOR_RESEARCHER.md"
        )
        target_receipt = json.loads(
            built.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
        )
        self.assertEqual("replace", operation["action"])
        self.assertEqual("immutable", operation["category"])
        self.assertIn("SOURCE_MONITOR_RESEARCHER.md", target_receipt["immutable_files"])
        self.assertNotIn("SOURCE_MONITOR_RESEARCHER.md", target_receipt["mutable_files"])

    def test_optional_state_retirement_categories_follow_model_declarations(self) -> None:
        for spec in project_contract_model.OPTIONAL_STATE_SPECS:
            with (
                self.subTest(state=spec.filename, partition=spec.partition),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                overrides: dict[str, object] = {spec.flag: True}
                if spec.flag == "include_source_update":
                    overrides["include_source_packs"] = True
                if spec.flag == "include_automation_orders":
                    overrides["automation_orders"] = {
                        "preferred_backend": "unspecified",
                        "jobs": [valid_automation_job()],
                    }
                _materialize_project(
                    project_root,
                    answer_overrides=overrides,
                )
                candidate = json.loads(
                    (project_root / project_input.INPUT_NAME).read_text(
                        encoding="utf-8"
                    )
                )
                candidate["answers"][spec.flag] = False
                if spec.flag == "include_automation_orders":
                    candidate["answers"].pop("automation_orders")
                backout_root = root / "private-backouts"
                backout_root.mkdir(mode=0o700)

                built = project_refresh.build_plan(
                    project_root,
                    candidate_input=candidate,
                    post_apply_backout={
                        "kind": "exact-preimage-bundle",
                        "root": str(backout_root.resolve()),
                    },
                )

                self.assertIsNotNone(built.payload, built.errors)
                assert built.payload is not None
                operation = next(
                    item
                    for item in cast(
                        list[dict[str, object]],
                        built.payload["operations"],
                    )
                    if item["path"] == spec.filename
                )
                target_receipt = json.loads(
                    built.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
                )
                expected_warning = (
                    project_refresh._optional_state_retirement_warning(
                        spec.filename,
                        spec.partition,
                    )
                )

                self.assertEqual("remove", operation["action"])
                self.assertEqual(spec.partition, operation["category"])
                self.assertIn(
                    expected_warning,
                    {
                        str(item["message"])
                        for item in cast(
                            list[dict[str, object]],
                            built.payload["warnings"],
                        )
                    },
                )
                self.assertNotIn(
                    spec.filename,
                    target_receipt[f"{spec.partition}_files"],
                )

    def test_source_monitor_brief_drift_is_refused_and_disabling_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(
                project_root,
                answer_overrides={"include_source_monitor_researcher": True},
            )
            monitor = project_root / "SOURCE_MONITOR_RESEARCHER.md"
            exact = monitor.read_bytes()
            monitor.write_bytes(exact + b"\nmanual drift\n")
            drifted = project_refresh.build_plan(
                project_root,
                ".",
                post_apply_backout={"kind": "none"},
            )
            monitor.write_bytes(exact)

            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["include_source_monitor_researcher"] = False
            retired = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            self.assertIsNotNone(retired.payload, retired.errors)
            assert retired.payload is not None
            retirement_warning = project_refresh._optional_state_retirement_warning(
                "SOURCE_MONITOR_RESEARCHER.md",
                "immutable",
            )
            retirement_warning_id = project_refresh._warning_id(retirement_warning)
            tree_before_refusal = _tree_snapshot(project_root)
            missing_approval_code, missing_approval = project_refresh.apply_plan(
                project_root,
                retired.payload,
                approved_digest=str(retired.payload["plan_sha256"]),
                approved_actions=set(
                    cast(list[str], retired.payload["required_actions"])
                ),
                approved_warnings=(
                    set(_warning_ids(retired.payload)) - {retirement_warning_id}
                ),
            )
            tree_after_refusal = _tree_snapshot(project_root)
            missing_record_plan = copy.deepcopy(retired.payload)
            missing_record_plan["warnings"] = [
                warning
                for warning in cast(
                    list[dict[str, str]],
                    missing_record_plan["warnings"],
                )
                if warning["id"] != retirement_warning_id
            ]
            project_refresh._finalize_plan(missing_record_plan)
            missing_record_errors = project_refresh._validate_plan(
                missing_record_plan
            )

        self.assertIsNone(drifted.payload)
        self.assertIn(
            "immutable generated output digest mismatch: SOURCE_MONITOR_RESEARCHER.md",
            " ".join(drifted.errors),
        )
        operation = next(
            item
            for item in cast(list[dict[str, object]], retired.payload["operations"])
            if item["path"] == "SOURCE_MONITOR_RESEARCHER.md"
        )
        self.assertEqual("remove", operation["action"])
        self.assertEqual("immutable", operation["category"])
        self.assertEqual("RETIRE-IMMUTABLE-0001", operation["approval_id"])
        self.assertIn(
            "RETIRE-IMMUTABLE-0001",
            cast(list[str], retired.payload["required_actions"]),
        )
        self.assertIn(
            "ACCEPT-NO-POST-APPLY-BACKOUT",
            cast(list[str], retired.payload["required_actions"]),
        )
        self.assertNotIn(
            "USE-EXACT-PREIMAGE-BUNDLE",
            cast(list[str], retired.payload["required_actions"]),
        )
        self.assertIn(
            {
                "id": retirement_warning_id,
                "message": retirement_warning,
            },
            cast(list[dict[str, str]], retired.payload["warnings"]),
        )
        self.assertEqual(project_refresh.EXIT_BLOCKED, missing_approval_code)
        self.assertEqual("approval-required", missing_approval["status"])
        self.assertEqual(tree_before_refusal, tree_after_refusal)
        self.assertIn(
            "refresh plan warnings must include the exact optional immutable-state "
            "retirement warning for SOURCE_MONITOR_RESEARCHER.md",
            missing_record_errors,
        )

    def test_candidate_omission_preserves_verified_current_wrapper_selection(
        self,
    ) -> None:
        wrapper_id = "project_init"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(
                project_root,
                runtime="codex",
                runtime_wrappers=(wrapper_id,),
            )
            retained = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(retained["answers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            candidate, errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=None,
                runtime="codex",
                framework_reference=str(retained["framework_reference"]),
                framework_revision_policy="live",
            )
            assert candidate is not None
            built = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )

        self.assertEqual([], errors)
        self.assertEqual([wrapper_id], candidate["runtime_wrappers"])
        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        self.assertNotIn(
            "REVISE-RUNTIME-WRAPPERS",
            cast(list[str], built.payload["required_actions"]),
        )
        wrapper_paths = set(
            integration_registry.wrapper_output_map("codex", [wrapper_id], REPO_ROOT).values()
        )
        retired_paths = {
            str(item["path"])
            for item in cast(list[dict[str, object]], built.payload["operations"])
            if item["action"] == "remove"
        }
        self.assertTrue(wrapper_paths.isdisjoint(retired_paths))

    def test_runtime_family_change_requires_explicit_wrapper_selection_and_action(
        self,
    ) -> None:
        wrapper_id = "security_audit"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(
                project_root,
                runtime="codex",
                runtime_wrappers=(wrapper_id,),
            )
            retained = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(retained["answers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            implicit, implicit_errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=None,
                runtime="claude-code",
                framework_reference=str(retained["framework_reference"]),
                framework_revision_policy="live",
            )
            explicit, explicit_errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=None,
                runtime="claude-code",
                runtime_wrappers=(wrapper_id,),
                framework_reference=str(retained["framework_reference"]),
                framework_revision_policy="live",
            )
            assert explicit is not None
            built = project_refresh.build_plan(
                project_root,
                candidate_input=explicit,
                post_apply_backout={"kind": "none"},
            )

        self.assertIsNone(implicit)
        self.assertEqual(1, len(implicit_errors), implicit_errors)
        self.assertIn("requires an explicit complete runtime-wrapper selection", implicit_errors[0])
        self.assertEqual([], explicit_errors)
        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        self.assertIn(
            "REVISE-RUNTIME-WRAPPERS",
            cast(list[str], built.payload["required_actions"]),
        )
        current_mapping = integration_registry.wrapper_output_map(
            "codex",
            [wrapper_id],
            REPO_ROOT,
        )
        target_mapping = integration_registry.wrapper_output_map(
            "claude-code",
            [wrapper_id],
            REPO_ROOT,
        )
        self.assertNotEqual(current_mapping, target_mapping)

    def test_candidate_wrapper_clear_is_explicit_and_approval_visible(self) -> None:
        wrapper_id = "project_init"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(
                project_root,
                runtime="codex",
                runtime_wrappers=(wrapper_id,),
            )
            retained = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            answers_path = root / "answers.json"
            answers_path.write_text(
                json.dumps(retained["answers"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            code, candidate = _run_cli(
                [
                    "candidate",
                    "--answers",
                    str(answers_path),
                    "--project-root",
                    str(project_root),
                    "--project-kind",
                    "downstream",
                    "--runtime",
                    "codex",
                    "--clear-runtime-wrappers",
                    "--framework-ref",
                    str(retained["framework_reference"]),
                    "--framework-revision-policy",
                    "live",
                ]
            )
            built = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )

        self.assertEqual(0, code, candidate)
        self.assertEqual([], candidate["runtime_wrappers"])
        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        self.assertIn(
            "REVISE-RUNTIME-WRAPPERS",
            cast(list[str], built.payload["required_actions"]),
        )
        self.assertTrue(
            any(
                str(action).startswith("RETIRE-IMMUTABLE-")
                for action in cast(list[str], built.payload["required_actions"])
            )
        )

    def test_explicit_wrapper_selection_cannot_bypass_a_missing_current_receipt(
        self,
    ) -> None:
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
                        "project_name": "Current-only update",
                        "date": "2026-07-14",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            def render_with(
                runtime_wrappers: tuple[str, ...] | None,
            ) -> tuple[dict[str, object] | None, list[str]]:
                return project_refresh.render_candidate_input(
                    answers_path=answers_path,
                    project_root=project_root,
                    project_kind="downstream",
                    contract_root_ref=".",
                    runtime="generic",
                    runtime_wrappers=runtime_wrappers,
                    framework_reference=os.path.relpath(REPO_ROOT, project_root),
                    framework_revision_policy="live",
                )

            results = [render_with(None), render_with(())]

        for candidate, errors in results:
            self.assertIsNone(candidate)
            self.assertEqual(1, len(errors), errors)
            self.assertTrue(
                errors[0].startswith(project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX),
                errors,
            )
            self.assertIn("manual update", errors[0])

    def test_candidate_wrapper_replace_and_clear_flags_are_mutually_exclusive(
        self,
    ) -> None:
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:
                project_refresh.main(
                    [
                        "candidate",
                        "--answers",
                        "answers.json",
                        "--project-root",
                        "missing-project",
                        "--runtime",
                        "codex",
                        "--runtime-wrapper",
                        "project_init",
                        "--clear-runtime-wrappers",
                        "--framework-ref",
                        "../framework",
                        "--framework-revision-policy",
                        "live",
                    ]
                )
        self.assertEqual(2, raised.exception.code)

    def test_direct_recovery_rejects_unknown_actions_before_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            with (
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transaction_recovery_status",
                    side_effect=AssertionError("invalid action inspected recovery state"),
                ),
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "rollback_interrupted_transaction",
                    side_effect=AssertionError("invalid action rolled back"),
                ),
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "finalize_interrupted_transaction",
                    side_effect=AssertionError("invalid action finalized"),
                ),
            ):
                code, report = project_refresh.recover_project(
                    project_root,
                    action="unexpected",
                    approved_transaction_id="a" * 32,
                )
                backout_code, backout_report = project_refresh.recover_backout_bundle(
                    project_root,
                    {},
                    project_root / "backout",
                    action="unexpected",
                    approved_transaction_id="a" * 32,
                )

        self.assertEqual(project_refresh.EXIT_INVOCATION, code, report)
        self.assertEqual("invalid-recovery-request", report["status"])
        self.assertEqual(project_refresh.EXIT_INVOCATION, backout_code, backout_report)
        self.assertEqual(
            "invalid-backout-recovery-request",
            backout_report["status"],
        )

    def test_recovery_controls_block_every_non_recovery_route_before_project_reads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).write_text(
                "orphan transaction control\n",
                encoding="utf-8",
            )
            commands = (
                [
                    "candidate",
                    "--answers",
                    str(root / "missing-answers.json"),
                    "--project-root",
                    str(project_root),
                    "--runtime",
                    "generic",
                    "--framework-ref",
                    "../framework",
                    "--framework-revision-policy",
                    "live",
                ],
                ["plan", "--project-root", str(project_root)],
                [
                    "preview",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                ],
                [
                    "apply",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--approve-plan-sha256",
                    "a" * 64,
                ],
                [
                    "backout-create",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--backout-root",
                    str(root / "backout"),
                ],
                [
                    "backout-verify",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--backout-root",
                    str(root / "backout"),
                ],
                [
                    "backout-restore",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--backout-root",
                    str(root / "backout"),
                    "--approve-plan-sha256",
                    "a" * 64,
                    "--approve-refresh-transaction-id",
                    "b" * 32,
                ],
                [
                    "backout-recover",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--backout-root",
                    str(root / "backout"),
                    "--action",
                    "finalize",
                    "--approve-transaction-id",
                    "b" * 32,
                ],
            )
            with (
                mock.patch.object(
                    project_refresh,
                    "_load_plan",
                    side_effect=AssertionError("route read plan before recovery gate"),
                ),
                mock.patch.object(
                    project_refresh,
                    "render_candidate_input",
                    side_effect=AssertionError("route read candidate before recovery gate"),
                ),
                mock.patch.object(
                    project_refresh,
                    "build_plan",
                    side_effect=AssertionError("route read project before recovery gate"),
                ),
            ):
                reports = [_run_cli(arguments) for arguments in commands]

            with mock.patch.object(
                project_refresh,
                "_validate_plan",
                side_effect=AssertionError("direct route validated plan before recovery gate"),
            ):
                direct = (
                    project_refresh.preview_plan(project_root, {}),
                    project_refresh.create_backout_bundle(
                        project_root,
                        {},
                        root / "backout",
                    ),
                    project_refresh.verify_backout_bundle(
                        project_root,
                        {},
                        root / "backout",
                        require_project_preimage=True,
                    ),
                    project_refresh.restore_backout_bundle(
                        project_root,
                        {},
                        root / "backout",
                        approved_digest="a" * 64,
                        approved_transaction_id="b" * 32,
                    ),
                    project_refresh.apply_plan(
                        project_root,
                        {},
                        approved_digest="a" * 64,
                        approved_actions=set(),
                        approved_warnings=set(),
                    ),
                    project_refresh.recover_backout_bundle(
                        project_root,
                        {},
                        root / "backout",
                        action="finalize",
                        approved_transaction_id="b" * 32,
                    ),
                )

        for code, report in (*reports, *direct):
            self.assertEqual(project_refresh.EXIT_RECOVERY_REQUIRED, code, report)
            self.assertEqual("recovery-required", report["status"])

    def test_refresh_repairs_and_retires_receipt_owned_wrappers(self) -> None:
        wrapper_id = "project_init"
        wrapper_output = integration_registry.wrapper_output_map(
            "codex",
            [wrapper_id],
            REPO_ROOT,
        )[wrapper_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            repair_root = root / "repair"
            repair_root.mkdir()
            _materialize_project(
                repair_root,
                runtime="codex",
                runtime_wrappers=(wrapper_id,),
            )
            corrupted = "Historical receipt-owned wrapper bytes.\n"
            (repair_root / wrapper_output).write_text(corrupted, encoding="utf-8")
            repair_manifest_path = repair_root / project_bootstrap.INSTANCE_MANIFEST
            repair_manifest = json.loads(
                repair_manifest_path.read_text(encoding="utf-8")
            )
            repair_manifest["output_digests"][wrapper_output] = hashlib.sha256(
                corrupted.encode("utf-8")
            ).hexdigest()
            repair_manifest_path.write_text(
                json.dumps(repair_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            repair_candidate = json.loads(
                (repair_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            repaired = project_refresh.build_plan(
                repair_root,
                ".",
                candidate_input=repair_candidate,
                post_apply_backout={"kind": "none"},
            )

            retire_root = root / "retire"
            retire_root.mkdir()
            _materialize_project(
                retire_root,
                runtime="codex",
                runtime_wrappers=(wrapper_id,),
            )
            retire_candidate = json.loads(
                (retire_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            retire_candidate["runtime_wrappers"] = []
            retired = project_refresh.build_plan(
                retire_root,
                ".",
                candidate_input=retire_candidate,
                post_apply_backout={"kind": "none"},
            )

        self.assertIsNotNone(repaired.payload, repaired.errors)
        assert repaired.payload is not None
        repair_operations = {
            str(operation["path"]): operation
            for operation in cast(list[dict[str, object]], repaired.payload["operations"])
        }
        self.assertEqual("refresh", repaired.payload["mode"])
        self.assertEqual("replace", repair_operations[wrapper_output]["action"])
        self.assertNotEqual(
            corrupted,
            repaired.target_outputs[wrapper_output],
        )
        self.assertIsNotNone(retired.payload, retired.errors)
        assert retired.payload is not None
        retire_operations = {
            str(operation["path"]): operation
            for operation in cast(list[dict[str, object]], retired.payload["operations"])
        }
        self.assertEqual("remove", retire_operations[wrapper_output]["action"])
        self.assertIsNotNone(retire_operations[wrapper_output]["approval_id"])
        self.assertIn(
            "REVISE-RUNTIME-WRAPPERS",
            cast(list[str], retired.payload["required_actions"]),
        )
        retired_receipt = json.loads(
            retired.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
        )
        self.assertEqual({}, retired_receipt["runtime_wrapper_outputs"])

    def test_refresh_rejects_wrapper_output_graph_collisions_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root, runtime="codex")
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["runtime_wrappers"] = ["project_init"]
            cases = (
                ("AGENTS.md", "multiple bootstrap outputs resolve to the same target"),
                (
                    "AGENTS.md/nested/SKILL.md",
                    "both a file and an ancestor directory",
                ),
            )
            reports: list[tuple[dict[str, str], list[str], str]] = []
            for output, expected in cases:
                with mock.patch.object(
                    integration_registry,
                    "wrapper_output_map",
                    return_value={"project_init": output},
                ):
                    rendered, errors, _warnings, _profiles = (
                        project_refresh._target_for_input(project_root, candidate)
                    )
                reports.append((rendered, errors, expected))

        for rendered, errors, expected in reports:
            self.assertEqual({}, rendered)
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_root_receipt_and_obsolete_nested_receipt_fail_closed_together(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            contract_ref = "contracts/authority"
            _materialize_project(project_root, contract_root_ref=contract_ref)
            root_receipt = project_root / project_bootstrap.INSTANCE_MANIFEST
            nested_receipt = project_root / contract_ref / project_bootstrap.INSTANCE_MANIFEST
            nested_receipt.write_bytes(root_receipt.read_bytes())

            inspected = project_refresh.inspect_project(project_root)
            planned = project_refresh.build_plan(project_root)

        self.assertEqual("manual-update-required", inspected["status"], inspected)
        self.assertTrue(
            any(
                "remains alongside the root-scoped" in error
                for error in cast(list[str], inspected["errors"])
            ),
            inspected,
        )
        self.assertIsNone(planned.payload)
        self.assertTrue(
            any("remains alongside the root-scoped" in error for error in planned.errors),
            planned.errors,
        )
        self.assertTrue(
            all(
                error.startswith(project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX)
                for error in planned.errors
            ),
            planned.errors,
        )

    def test_malformed_contract_root_placement_requires_manual_update(self) -> None:
        cases: tuple[tuple[str, object], ...] = (
            ("non-string", ["contracts"]),
            ("escaping", "../contracts"),
        )
        for label, contract_root in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["contract_root"] = contract_root
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                inspected = project_refresh.inspect_project(project_root)
                planned = project_refresh.build_plan(project_root)

            self.assertEqual("manual-update-required", inspected["status"], inspected)
            inspected_errors = cast(list[str], inspected["errors"])
            self.assertEqual(1, len(inspected_errors), inspected)
            self.assertTrue(
                inspected_errors[0].startswith(
                    project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
                ),
                inspected,
            )
            self.assertIsNone(planned.payload)
            self.assertEqual(1, len(planned.errors), planned.errors)
            self.assertTrue(
                planned.errors[0].startswith(
                    project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
                ),
                planned.errors,
            )

    def test_generated_format_identity_and_recorded_preimage_drift_require_manual_update(
        self,
    ) -> None:
        marker = project_bootstrap.contract_model.CONTRACT_FORMAT_MARKER
        older = project_bootstrap.contract_model.contract_format_marker(
            project_bootstrap.contract_model.CONTRACT_FORMAT_VERSION - 1
        )
        mutations = (
            ("older", older),
            ("missing", ""),
            ("malformed", "<!-- mpa-project-contract-format: current -->"),
            ("misplaced", "# preamble before marker\n" + marker),
            (
                "oversized",
                "<!-- mpa-project-contract-format: " + ("9" * 5000) + " -->",
            ),
        )
        for label, replacement in mutations:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                sow_path = project_root / "STATEMENT_OF_WORK.md"
                sow = sow_path.read_text(encoding="utf-8")
                sow_path.write_text(
                    sow.replace(marker, replacement, 1),
                    encoding="utf-8",
                )

                inspected = project_refresh.inspect_project(project_root)
                planned = project_refresh.build_plan(project_root)

            self.assertEqual("manual-update-required", inspected["status"], inspected)
            self.assertIsNone(planned.payload)
            self.assertTrue(
                cast(list[str], inspected["errors"])[0].startswith(
                    project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
                ),
                inspected,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            sow_path = project_root / "STATEMENT_OF_WORK.md"
            sow_path.write_text(
                sow_path.read_text(encoding="utf-8").replace(
                    "Statement of Work — Demo",
                    "Statement of Work — Digest Drift",
                    1,
                ),
                encoding="utf-8",
            )
            digest_drift = project_refresh.inspect_project(project_root)

        self.assertEqual(
            "manual-update-required",
            digest_drift["status"],
            digest_drift,
        )
        self.assertTrue(
            cast(list[str], digest_drift["errors"])[0].startswith(
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
            ),
            digest_drift,
        )

        for missing_name in ("AGENTS.md", "AGENT_PROJECT.md"):
            with (
                self.subTest(missing_managed_file=missing_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                (project_root / missing_name).unlink()
                managed_file_drift = project_refresh.inspect_project(project_root)

            self.assertEqual(
                "manual-update-required",
                managed_file_drift["status"],
                managed_file_drift,
            )
            self.assertTrue(
                cast(list[str], managed_file_drift["errors"])[0].startswith(
                    project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
                ),
                managed_file_drift,
            )

    def test_malformed_unknown_input_and_receipt_parity_drift_require_manual_update(
        self,
    ) -> None:
        def inspect_after_input_mutation(
            mutate: Callable[[dict[str, object]], bytes],
        ) -> dict[str, object]:
            with tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                input_path = project_root / project_input.INPUT_NAME
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                raw = mutate(payload)
                input_path.write_bytes(raw)
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["input_sha256"] = hashlib.sha256(raw).hexdigest()
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return project_refresh.inspect_project(project_root)

        malformed = inspect_after_input_mutation(lambda _payload: b"{\n")

        def add_unknown_field(payload: dict[str, object]) -> bytes:
            payload["unknown_current_field"] = True
            return project_input.canonical_project_input_bytes(payload)

        unknown = inspect_after_input_mutation(add_unknown_field)

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["framework_revision_policy"] = "pinned"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            parity_drift = project_refresh.inspect_project(project_root)

        for label, report, decisive_detail in (
            (
                "malformed input",
                malformed,
                "cannot supply a readable current-format identity",
            ),
            ("unknown input", unknown, "unknown keys"),
            ("receipt parity", parity_drift, "does not match retained project input"),
        ):
            with self.subTest(case=label):
                self.assertEqual("manual-update-required", report["status"], report)
                errors = cast(list[str], report["errors"])
                self.assertEqual(1, len(errors), report)
                self.assertTrue(
                    errors[0].startswith(
                        project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
                    ),
                    report,
                )
                self.assertIn(decisive_detail, errors[0], report)

    def test_malformed_root_receipt_never_falls_back_to_obsolete_nested_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            contract_ref = "contracts/authority"
            _materialize_project(project_root, contract_root_ref=contract_ref)
            root_receipt = project_root / project_bootstrap.INSTANCE_MANIFEST
            nested_receipt = project_root / contract_ref / project_bootstrap.INSTANCE_MANIFEST
            nested_receipt.write_bytes(root_receipt.read_bytes())
            root_receipt.write_text("{\n", encoding="utf-8")

            inspected = project_refresh.inspect_project(project_root, contract_ref)
            planned = project_refresh.build_plan(project_root, contract_ref)

        self.assertEqual("manual-update-required", inspected["status"], inspected)
        inspected_errors = cast(list[str], inspected["errors"])
        self.assertEqual(1, len(inspected_errors), inspected)
        self.assertTrue(
            inspected_errors[0].startswith(
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
            ),
            inspected,
        )
        self.assertIsNone(planned.payload)
        self.assertEqual(1, len(planned.errors), planned.errors)
        self.assertTrue(
            planned.errors[0].startswith(
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
            ),
            planned.errors,
        )

    def test_explicit_contract_root_cannot_bypass_a_missing_current_receipt(
        self,
    ) -> None:
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
                        "project_name": "Current-only update",
                        "date": "2026-07-14",
                        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            candidate, errors = project_refresh.render_candidate_input(
                answers_path=answers_path,
                project_root=project_root,
                project_kind="downstream",
                contract_root_ref=".",
                runtime="generic",
                framework_reference=os.path.relpath(REPO_ROOT, project_root),
                framework_revision_policy="live",
                runtime_wrappers=(),
            )

        self.assertIsNone(candidate)
        self.assertEqual(1, len(errors), errors)
        self.assertTrue(
            errors[0].startswith(project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX),
            errors,
        )
        self.assertIn("manual update", errors[0])

    def test_cli_reports_invalid_filesystem_paths_without_a_traceback(self) -> None:
        cases = (
            ("invalid\x00project-root", "embedded null"),
            (
                "~mpa_refresh_account_that_must_not_exist_724c95/project",
                "Could not determine home directory",
            ),
        )
        for project_root, expected_error in cases:
            with self.subTest(project_root=project_root):
                code, report = _run_cli(
                    [
                        "candidate",
                        "--answers",
                        "answers.json",
                        "--project-root",
                        project_root,
                        "--project-kind",
                        "downstream",
                        "--runtime",
                        "generic",
                        "--framework-ref",
                        "../framework",
                        "--framework-revision-policy",
                        "pinned",
                    ]
                )

                self.assertEqual(project_refresh.EXIT_INVOCATION, code)
                self.assertEqual("invalid-invocation", report["status"])
                self.assertIn(expected_error, " ".join(report["errors"]))

    def test_candidate_requires_an_explicit_framework_revision_policy(self) -> None:
        absolute_project_root = str(Path("/", "tmp", "project"))
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:
                project_refresh.main(
                    [
                        "candidate",
                        "--answers",
                        "answers.json",
                        "--project-root",
                        absolute_project_root,
                        "--runtime",
                        "generic",
                        "--framework-ref",
                        "../framework",
                    ]
                )
        self.assertEqual(2, raised.exception.code)

    def test_inspect_routes_noncurrent_identity_formats_to_one_manual_update_boundary(
        self,
    ) -> None:
        current_schema = project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION
        cases: list[tuple[str, str | None, bool, str, str]] = [
            (
                "no retained identity",
                None,
                False,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "input without receipt",
                None,
                True,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "malformed receipt",
                "{",
                False,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "receipt without schema",
                "{}",
                False,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "receipt with malformed schema",
                json.dumps({"schema_version": True}),
                False,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "older receipt",
                json.dumps({"schema_version": current_schema - 1}),
                False,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "newer receipt",
                json.dumps({"schema_version": current_schema + 1}),
                False,
                "newer-framework-required",
                project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX,
            ),
        ]
        for label, receipt_text, write_input, expected_status, expected_prefix in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                if receipt_text is not None:
                    (project_root / project_bootstrap.INSTANCE_MANIFEST).write_text(
                        receipt_text + "\n",
                        encoding="utf-8",
                    )
                if write_input:
                    (project_root / project_input.INPUT_NAME).write_text(
                        "{}\n",
                        encoding="utf-8",
                    )

                inspected = project_refresh.inspect_project(project_root, ".")

                self.assertEqual(expected_status, inspected["status"], inspected)
                errors = cast(list[str], inspected["errors"])
                self.assertEqual(1, len(errors), inspected)
                self.assertTrue(errors[0].startswith(expected_prefix), inspected)
                if expected_status == "manual-update-required":
                    self.assertIn("manual update", errors[0])
                else:
                    self.assertIn("framework checkout", errors[0])
                self.assertNotIn("contract_effective_date", errors[0])
                self.assertNotIn("framework_content", errors[0])

    def test_input_schema_versions_route_inspect_and_plan_to_current_only_boundaries(
        self,
    ) -> None:
        current_schema = project_input.SCHEMA_VERSION
        missing = object()
        cases = (
            (
                "receipt missing",
                "receipt",
                missing,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "receipt malformed",
                "receipt",
                True,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "receipt older",
                "receipt",
                current_schema - 1,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "receipt newer",
                "receipt",
                current_schema + 1,
                "newer-framework-required",
                project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX,
            ),
            (
                "retained input missing",
                "retained-input",
                missing,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "retained input malformed",
                "retained-input",
                True,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "retained input older",
                "retained-input",
                current_schema - 1,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "retained input newer",
                "retained-input",
                current_schema + 1,
                "newer-framework-required",
                project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX,
            ),
        )
        for label, surface, value, expected_status, expected_prefix in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if surface == "receipt":
                    if value is missing:
                        receipt.pop("project_input_schema_version")
                    else:
                        receipt["project_input_schema_version"] = value
                else:
                    input_path = project_root / project_input.INPUT_NAME
                    retained_input = json.loads(input_path.read_text(encoding="utf-8"))
                    if value is missing:
                        retained_input.pop("schema_version")
                    else:
                        retained_input["schema_version"] = value
                    input_raw = project_input.canonical_project_input_bytes(retained_input)
                    input_path.write_bytes(input_raw)
                    receipt["input_sha256"] = project_input.project_input_sha256(
                        input_raw
                    )
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                inspected = project_refresh.inspect_project(project_root, ".")
                planned = project_refresh.build_plan(
                    project_root,
                    ".",
                    post_apply_backout={"kind": "none"},
                )

                self.assertEqual(expected_status, inspected["status"], inspected)
                inspect_errors = cast(list[str], inspected["errors"])
                self.assertEqual(1, len(inspect_errors), inspected)
                self.assertTrue(
                    inspect_errors[0].startswith(expected_prefix),
                    inspected,
                )
                self.assertIsNone(planned.payload, planned)
                self.assertEqual(inspect_errors, planned.errors, planned.errors)

    def test_contract_format_cannot_enter_refresh_planning(self) -> None:
        current_format = project_bootstrap.contract_model.CONTRACT_FORMAT_VERSION
        cases = (
            (
                "older",
                current_format - 1,
                "manual-update-required",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "newer",
                current_format + 1,
                "newer-framework-required",
                project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX,
            ),
        )
        for label, contract_format, status, prefix in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                _materialize_project(project_root)
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["project_contract_format"] = contract_format
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                inspected = project_refresh.inspect_project(project_root, ".")
                planned = project_refresh.build_plan(
                    project_root,
                    ".",
                    post_apply_backout={"kind": "none"},
                )

                self.assertEqual(status, inspected["status"], inspected)
                self.assertTrue(
                    cast(list[str], inspected["errors"])[0].startswith(prefix),
                    inspected,
                )
                self.assertIsNone(planned.payload, planned)
                self.assertEqual(1, len(planned.errors), planned.errors)
                self.assertTrue(planned.errors[0].startswith(prefix), planned.errors)

    def test_unreadable_receipt_routes_to_manual_update_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / project_bootstrap.INSTANCE_MANIFEST).mkdir()

            unreadable = project_refresh.inspect_project(project_root, ".")

        self.assertEqual("manual-update-required", unreadable["status"], unreadable)
        unreadable_errors = cast(list[str], unreadable["errors"])
        self.assertEqual(1, len(unreadable_errors), unreadable)
        self.assertTrue(
            unreadable_errors[0].startswith(
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX
            ),
            unreadable,
        )

    def test_noncurrent_receipt_never_selects_contract_root_implicitly_or_explicitly(
        self,
    ) -> None:
        current_schema = project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION
        for label, receipt_text, expected_prefix in (
            (
                "missing schema",
                "{}",
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "malformed schema",
                json.dumps({"schema_version": True}),
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "older schema",
                json.dumps({"schema_version": current_schema - 1}),
                project_refresh.CURRENT_ONLY_MANUAL_UPDATE_PREFIX,
            ),
            (
                "newer schema",
                json.dumps({"schema_version": current_schema + 1}),
                project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX,
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                (project_root / project_bootstrap.INSTANCE_MANIFEST).write_text(
                    receipt_text + "\n",
                    encoding="utf-8",
                )

                implicit, implicit_errors = (
                    project_refresh._resolve_contract_root_selection(
                        project_root,
                        None,
                    )
                )
                explicit, explicit_errors = (
                    project_refresh._resolve_contract_root_selection(
                        project_root,
                        "reviewed-layout",
                    )
                )

            self.assertIsNone(implicit)
            self.assertEqual(1, len(implicit_errors), implicit_errors)
            self.assertTrue(
                implicit_errors[0].startswith(expected_prefix),
                implicit_errors,
            )
            self.assertIsNone(explicit)
            self.assertEqual(implicit_errors, explicit_errors)

    def test_currency_separates_distribution_drift_effective_drift_and_pinned_advance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            manifest_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["framework_distribution_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            distribution = project_refresh.inspect_project(project_root, ".")
            distribution_plan = project_refresh.build_plan(
                project_root,
                ".",
                post_apply_backout={"kind": "none"},
            )

            _materialize_project(project_root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            effective_map = dict(manifest["framework_effective_file_digests"])
            changed_path = sorted(effective_map)[0]
            effective_map[changed_path] = "0" * 64
            manifest["framework_effective_file_digests"] = effective_map
            manifest["framework_content_sha256"] = project_bootstrap.canonical_json_digest(
                effective_map
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            effective = project_refresh.inspect_project(project_root, ".")
            effective_plan = project_refresh.build_plan(
                project_root,
                ".",
                post_apply_backout={"kind": "none"},
            )

            _materialize_project(project_root, revision_policy="pinned")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["framework_distribution_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pinned_plan = project_refresh.build_plan(
                project_root,
                ".",
                post_apply_backout={"kind": "none"},
            )

        self.assertEqual("distribution-only-drift", distribution["status"])
        self.assertIsNotNone(distribution_plan.payload, distribution_plan.errors)
        assert distribution_plan.payload is not None
        distribution_payload = cast(dict[str, Any], distribution_plan.payload)
        self.assertNotIn(
            "ACCEPT-SELECTED-FRAMEWORK-CHANGE",
            distribution_payload["required_actions"],
        )
        self.assertEqual("refresh-available", effective["status"])
        effective_changes = cast(dict[str, Any], effective["framework_effective_changes"])
        self.assertEqual([changed_path], effective_changes["changed"])
        self.assertIsNotNone(effective_plan.payload, effective_plan.errors)
        assert effective_plan.payload is not None
        effective_payload = cast(dict[str, Any], effective_plan.payload)
        self.assertIn(
            "ACCEPT-SELECTED-FRAMEWORK-CHANGE",
            effective_payload["required_actions"],
        )
        self.assertIsNotNone(pinned_plan.payload, pinned_plan.errors)
        assert pinned_plan.payload is not None
        pinned_payload = cast(dict[str, Any], pinned_plan.payload)
        self.assertIn(
            "ADVANCE-PINNED-FRAMEWORK",
            pinned_payload["required_actions"],
        )

    def test_effective_framework_delta_requires_exact_digest_maps(self) -> None:
        recorded = {
            "removed.md": "1" * 64,
            "changed.md": "2" * 64,
            "stable.md": "3" * 64,
        }
        selected = {
            "added.md": "4" * 64,
            "changed.md": "5" * 64,
            "stable.md": "3" * 64,
        }

        exact = project_refresh._effective_framework_changes(recorded, selected)
        self.assertEqual(
            {
                "exact_delta_available": True,
                "added": ["added.md"],
                "removed": ["removed.md"],
                "changed": ["changed.md"],
            },
            exact,
        )
        with self.assertRaisesRegex(
            ValueError,
            "exact framework-change reporting requires valid recorded and selected digest maps",
        ):
            project_refresh._effective_framework_changes(
                {"unsafe.md": "not-a-digest"},
                selected,
            )

    def test_unsupported_identity_transitions_and_unmanaged_targets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            retained = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            relocated = dict(retained)
            relocated["contract_root"] = "nested"
            root_plan = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=relocated,
                post_apply_backout={"kind": "none"},
            )
            runtime_candidate = dict(retained)
            runtime_candidate["runtime"] = "claude-code"
            (project_root / "CLAUDE.md").write_text(
                "Unmanaged target collision.\n",
                encoding="utf-8",
            )
            collision_plan = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=runtime_candidate,
                post_apply_backout={"kind": "none"},
            )

        self.assertIsNone(root_plan.payload)
        self.assertTrue(
            any("contract-root relocation is not supported" in error for error in root_plan.errors),
            root_plan.errors,
        )
        self.assertIsNone(collision_plan.payload)
        self.assertTrue(
            any("target path already exists outside" in error for error in collision_plan.errors),
            collision_plan.errors,
        )

    def test_removed_runtime_preimage_can_be_revised_to_a_supported_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            input_path = project_root / project_input.INPUT_NAME
            manifest_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            retained = json.loads(input_path.read_text(encoding="utf-8"))
            retained["runtime"] = "retired-runtime"
            input_raw = project_input.canonical_project_input_bytes(retained)
            input_path.write_bytes(input_raw)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["runtime"] = "retired-runtime"
            manifest["input_sha256"] = project_input.project_input_sha256(input_raw)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            inspected = project_refresh.inspect_project(project_root, ".")
            candidate = dict(retained)
            candidate["runtime"] = "claude-code"
            plan = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )

        self.assertEqual("runtime-revision-required", inspected["status"], inspected)
        self.assertIsNotNone(plan.payload, plan.errors)
        assert plan.payload is not None
        payload = cast(dict[str, Any], plan.payload)
        self.assertEqual("revise", plan.payload["mode"])
        self.assertTrue(
            any(
                operation["path"] == "AGENTS.md" and operation["action"] == "remove"
                for operation in payload["operations"]
            ),
            plan.payload,
        )
        self.assertTrue(
            any(
                operation["path"] == "CLAUDE.md" and operation["action"] == "create"
                for operation in payload["operations"]
            ),
            plan.payload,
        )

    def test_malformed_plan_reports_all_structured_faults_without_raising(self) -> None:
        malformed: dict[str, object] = {
            "schema_version": project_refresh.PLAN_SCHEMA_VERSION,
            "kind": project_refresh.PLAN_KIND,
            "project_root": "/project",
            "current_contract_root": ".",
            "target_contract_root": ".",
            "mode": "no-op",
            "framework_content_sha256": "a" * 64,
            "framework_distribution_sha256": "b" * 64,
            "framework_effective_changes": {
                "exact_delta_available": True,
                "added": [],
                "removed": [],
                "changed": [],
            },
            "current_input_sha256": "c" * 64,
            "current_instance_sha256": "d" * 64,
            "target_input": {"schema_version": project_input.SCHEMA_VERSION},
            "target_input_sha256": "e" * 64,
            "current_files": {},
            "target_files": {},
            "operations": [],
            "absent_parent_directories": [],
            "creation_modes": {"file": None, "directory": None},
            "required_actions": [{}],
            "warnings": [{}],
            "active_profiles": [1],
            "post_apply_backout": {"kind": "not-required"},
        }
        project_refresh._finalize_plan(malformed)

        errors = project_refresh._validate_plan(malformed)
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "malformed-plan.json"
            plan_path.write_text(
                json.dumps(malformed, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            loaded, load_errors = project_refresh._load_plan(plan_path)

        self.assertIn("refresh plan required_actions must be a string list", errors)
        self.assertIn("refresh plan active_profiles must be a string list", errors)
        self.assertIn(
            "refresh plan warnings[0] must use the exact warning schema",
            errors,
        )
        self.assertIsNotNone(loaded)
        self.assertEqual(errors, load_errors)

    def test_noncurrent_plan_schema_stops_at_one_version_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            built = project_refresh.build_plan(project_root, ".")
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            variants: dict[str, list[str]] = {}
            for name, version in (
                ("missing", None),
                ("malformed", True),
                ("older", project_refresh.PLAN_SCHEMA_VERSION - 1),
                ("newer", project_refresh.PLAN_SCHEMA_VERSION + 1),
            ):
                plan = copy.deepcopy(built.payload)
                if version is None:
                    plan.pop("schema_version")
                else:
                    plan["schema_version"] = version
                plan["kind"] = "derivative-kind-error"
                plan["required_actions"] = [{}]
                variants[name] = project_refresh._validate_plan(plan)

        for name, errors in variants.items():
            with self.subTest(name=name):
                self.assertEqual(1, len(errors), errors)
                expected_prefix = (
                    project_refresh.NEWER_FRAMEWORK_REQUIRED_PREFIX
                    if name == "newer"
                    else "refresh plan schema_version"
                )
                self.assertTrue(errors[0].startswith(expected_prefix), errors)
                if name == "newer":
                    self.assertIn("newer than the supported", errors[0])
                    self.assertIn("framework checkout", errors[0])
                else:
                    self.assertIn("Regenerate and review the temporary plan", errors[0])
                self.assertNotIn("kind", errors[0])
                self.assertNotIn("required_actions", errors[0])

    def test_plan_semantics_reject_tampering_after_outer_digests_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            built = project_refresh.build_plan(project_root, ".")

            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            valid = built.payload
            self.assertEqual([], project_refresh._validate_plan(valid))
            self.assertRegex(
                cast(str, valid["current_input_sha256"]),
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(
                cast(str, valid["current_instance_sha256"]),
                r"^[0-9a-f]{64}$",
            )

            input_path = project_bootstrap.project_relative_output(
                str(valid["target_contract_root"]),
                project_input.INPUT_NAME,
            )
            receipt_path = project_bootstrap.INSTANCE_MANIFEST

            cases: list[tuple[str, Any, str]] = []

            def warnings_wrong_type(plan: dict[str, object]) -> None:
                plan["warnings"] = ["warning"]

            cases.append(
                (
                    "warning record type",
                    warnings_wrong_type,
                    "warnings[0] must use the exact warning schema",
                )
            )

            def duplicate_warning(plan: dict[str, object]) -> None:
                warning = project_refresh._warning_records(["same warning"])[0]
                plan["warnings"] = [dict(warning), dict(warning)]

            cases.append(
                ("duplicate warning id", duplicate_warning, "warnings[1].id must be unique")
            )

            def wrong_warning_binding(plan: dict[str, object]) -> None:
                plan["warnings"] = [
                    {"id": "REFRESH-W-" + "0" * 64, "message": "bound warning"}
                ]

            cases.append(
                (
                    "warning content binding",
                    wrong_warning_binding,
                    "warnings[0].id does not bind its exact warning message",
                )
            )

            def unsafe_map_path(plan: dict[str, object]) -> None:
                cast(dict[str, str], plan["current_files"])["../escape"] = "a" * 64

            cases.append(
                ("unsafe map path", unsafe_map_path, "must be a safe repo-relative path")
            )

            def invalid_map_digest(plan: dict[str, object]) -> None:
                cast(dict[str, str], plan["target_files"])[input_path] = "invalid"

            cases.append(
                (
                    "invalid map digest",
                    invalid_map_digest,
                    "value must be a lowercase SHA-256 digest",
                )
            )

            def open_target_input_schema(plan: dict[str, object]) -> None:
                cast(dict[str, object], plan["target_input"])["unexpected"] = True

            cases.append(
                (
                    "open target input schema",
                    open_target_input_schema,
                    "target_input: project input has unknown keys: unexpected",
                )
            )

            def invalid_target_answers(plan: dict[str, object]) -> None:
                target_input = cast(dict[str, object], plan["target_input"])
                answers = cast(dict[str, object], target_input["answers"])
                answers["agent"] = ""
                raw = project_input.canonical_project_input_bytes(target_input)
                digest = project_input.project_input_sha256(raw)
                plan["target_input_sha256"] = digest
                cast(dict[str, str], plan["target_files"])[input_path] = digest
                for operation in cast(
                    list[dict[str, object]], plan["operations"]
                ):
                    if operation["path"] == input_path:
                        operation["target_sha256"] = digest

            cases.append(
                (
                    "semantic target answers",
                    invalid_target_answers,
                    "target_input answers: required bootstrap answer key 'agent' must not be empty",
                )
            )

            def target_input_digest_mismatch(plan: dict[str, object]) -> None:
                plan["target_input_sha256"] = "0" * 64

            cases.append(
                (
                    "target input digest binding",
                    target_input_digest_mismatch,
                    "target_input_sha256 does not bind canonical target_input bytes",
                )
            )

            def current_input_digest_mismatch(plan: dict[str, object]) -> None:
                plan["current_input_sha256"] = "0" * 64

            cases.append(
                (
                    "current input map binding",
                    current_input_digest_mismatch,
                    "current_input_sha256 does not match current_files retained input",
                )
            )

            def current_receipt_digest_mismatch(plan: dict[str, object]) -> None:
                plan["current_instance_sha256"] = "0" * 64

            cases.append(
                (
                    "current receipt map binding",
                    current_receipt_digest_mismatch,
                    "current_instance_sha256 does not match current_files receipt",
                )
            )

            def null_current_input_digest(plan: dict[str, object]) -> None:
                plan["current_input_sha256"] = None

            cases.append(
                (
                    "current input digest nullability",
                    null_current_input_digest,
                    "current_input_sha256 must be a lowercase SHA-256 digest",
                )
            )

            def null_current_receipt_digest(plan: dict[str, object]) -> None:
                plan["current_instance_sha256"] = None

            cases.append(
                (
                    "current receipt digest nullability",
                    null_current_receipt_digest,
                    "current_instance_sha256 must be a lowercase SHA-256 digest",
                )
            )

            def missing_operation(plan: dict[str, object]) -> None:
                cast(list[dict[str, object]], plan["operations"]).pop()

            cases.append(
                (
                    "operation map parity",
                    missing_operation,
                    "operation paths must exactly equal current_files union target_files",
                )
            )

            def operation_digest_mismatch(plan: dict[str, object]) -> None:
                operation = cast(list[dict[str, object]], plan["operations"])[0]
                operation["current_sha256"] = "0" * 64

            cases.append(
                (
                    "operation digest binding",
                    operation_digest_mismatch,
                    "operation current_sha256 does not match current_files",
                )
            )

            def invalid_operation_mode(plan: dict[str, object]) -> None:
                operation = next(
                    item
                    for item in cast(
                        list[dict[str, object]],
                        plan["operations"],
                    )
                    if item["action"] == "preserve"
                )
                operation["current_mode"] = 0o1000
                operation["target_mode"] = 0o1000

            cases.append(
                (
                    "operation mode contract",
                    invalid_operation_mode,
                    "preserve must bind one unchanged digest and mode",
                )
            )

            def unowned_creation_mode(plan: dict[str, object]) -> None:
                creation_modes = cast(dict[str, int | None], plan["creation_modes"])
                creation_modes["file"] = 0o644

            cases.append(
                (
                    "creation mode ownership",
                    unowned_creation_mode,
                    "creation_modes.file must be present exactly when files are created",
                )
            )

            def reversed_operations(plan: dict[str, object]) -> None:
                cast(list[dict[str, object]], plan["operations"]).reverse()

            cases.append(
                (
                    "canonical operation ordering",
                    reversed_operations,
                    "operations must be in canonical path/action order",
                )
            )

            def mismatched_profiles(plan: dict[str, object]) -> None:
                plan["active_profiles"] = ["core-project", "security-managed"]

            cases.append(
                (
                    "active profile derivation",
                    mismatched_profiles,
                    "active_profiles must exactly match target_input answers",
                )
            )

            def invalid_framework_digest(plan: dict[str, object]) -> None:
                plan["framework_content_sha256"] = "invalid"

            cases.append(
                (
                    "framework digest",
                    invalid_framework_digest,
                    "framework_content_sha256 must be a lowercase SHA-256 digest",
                )
            )

            def overlapping_delta(plan: dict[str, object]) -> None:
                delta = cast(dict[str, object], plan["framework_effective_changes"])
                delta["added"] = ["README.md"]
                delta["changed"] = ["README.md"]

            cases.append(
                (
                    "overlapping effective delta",
                    overlapping_delta,
                    "framework_effective_changes path classes must be disjoint",
                )
            )

            def unavailable_exact_delta(plan: dict[str, object]) -> None:
                delta = cast(dict[str, object], plan["framework_effective_changes"])
                delta["exact_delta_available"] = False

            cases.append(
                (
                    "unavailable exact effective delta",
                    unavailable_exact_delta,
                    "exact_delta_available must be exactly true",
                )
            )

            def unsafe_delta_path(plan: dict[str, object]) -> None:
                delta = cast(dict[str, object], plan["framework_effective_changes"])
                delta["added"] = ["../escape"]

            cases.append(
                (
                    "unsafe effective delta path",
                    unsafe_delta_path,
                    "must be a safe repo-relative path",
                )
            )

            def missing_target_receipt(plan: dict[str, object]) -> None:
                cast(dict[str, str], plan["target_files"]).pop(receipt_path)

            cases.append(
                (
                    "target receipt binding",
                    missing_target_receipt,
                    "target_files must contain the target instance receipt",
                )
            )

            for label, mutate, expected_error in cases:
                with self.subTest(label=label):
                    tampered = copy.deepcopy(valid)
                    mutate(tampered)
                    project_refresh._finalize_plan(tampered)
                    errors = project_refresh._validate_plan(tampered)
                    self.assertTrue(
                        any(expected_error in error for error in errors),
                        errors,
                    )

    def test_transaction_warnings_exclude_outputs_absent_from_the_write_set(self) -> None:
        warnings = [
            {"id": "REFRESH-W0001", "message": "reference warning"},
            {
                "id": "REFRESH-W0002",
                "message": "rendered output warning: AGENT_PROJECT.md references local state",
            },
            {
                "id": "REFRESH-W0003",
                "message": "rendered output warning: TODO.md references local state",
            },
        ]

        filtered = project_refresh._warnings_for_transaction_outputs(
            warnings,
            {"AGENT_PROJECT.md": "replacement"},
        )

        expected = sorted(
            [
                {
                    "id": project_refresh._warning_id(
                        "rendered output warning: AGENT_PROJECT.md references local state"
                    ),
                    "message": (
                        "rendered output warning: AGENT_PROJECT.md references local state"
                    ),
                },
                {
                    "id": project_refresh._warning_id("reference warning"),
                    "message": "reference warning",
                },
            ],
            key=lambda item: (item["id"], item["message"]),
        )
        self.assertEqual(expected, filtered)

    def test_inspect_and_plan_do_not_write_a_read_only_project_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            locked_parent = root / "locked-parent"
            project_root = locked_parent / "project"
            project_root.mkdir(parents=True)
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["include_precedents"] = True

            initial_umask = os.umask(0)
            os.umask(initial_umask)
            initial_parent_mode = stat.S_IMODE(locked_parent.stat().st_mode)
            locked_parent.chmod(0o555)
            try:
                before = _tree_snapshot(locked_parent)
                with (
                    mock.patch.object(
                        project_refresh.conformance_check,
                        "run_profiles",
                    ) as run_profiles,
                    mock.patch.object(
                        tempfile,
                        "TemporaryDirectory",
                        side_effect=AssertionError(
                            "inspection and planning must not materialize scratch trees"
                        ),
                    ) as temporary_directory,
                ):
                    inspected = project_refresh.inspect_project(project_root)
                    built = project_refresh.build_plan(
                        project_root,
                        candidate_input=candidate,
                        post_apply_backout={"kind": "none"},
                    )
                after = _tree_snapshot(locked_parent)
                final_umask = os.umask(0)
                os.umask(final_umask)
                parent_entries = sorted(path.name for path in locked_parent.iterdir())
            finally:
                locked_parent.chmod(initial_parent_mode)

        self.assertEqual("current", inspected["status"], inspected)
        self.assertIsNotNone(built.payload, built.errors)
        assert built.payload is not None
        precedents = next(
            operation
            for operation in cast(list[dict[str, object]], built.payload["operations"])
            if operation["path"] == "PRECEDENTS.md"
        )
        self.assertEqual("create", precedents["action"])
        expected_file_mode = 0o666 & ~initial_umask
        self.assertEqual(expected_file_mode, precedents["target_mode"])
        self.assertEqual(
            {"file": expected_file_mode, "directory": None},
            built.payload["creation_modes"],
        )
        run_profiles.assert_not_called()
        temporary_directory.assert_not_called()
        self.assertEqual(initial_umask, final_umask)
        self.assertEqual(before, after)
        self.assertEqual(["project"], parent_entries)

    def test_plan_preview_exposes_exact_plan_bound_authority_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Previewed Authority"
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            before = _tree_snapshot(project_root)
            code, preview = project_refresh.preview_plan(project_root, built.payload)
            after = _tree_snapshot(project_root)

        self.assertEqual(0, code, preview)
        self.assertEqual("plan-preview", preview["status"])
        self.assertTrue(preview["target_files_verified"])
        self.assertEqual(before, after)
        changed = cast(list[dict[str, object]], preview["changed_files"])
        self.assertTrue(changed)
        saw_authority_change = False
        target_files = cast(dict[str, str], built.payload["target_files"])
        operations = {
            str(item["path"]): item
            for item in cast(list[dict[str, object]], built.payload["operations"])
        }
        for item in changed:
            path = str(item["path"])
            target_text = str(item["target_text"])
            target_digest = item["target_sha256"]
            self.assertEqual(operations[path]["current_mode"], item["current_mode"])
            self.assertEqual(operations[path]["target_mode"], item["target_mode"])
            if item["action"] in {"create", "replace"}:
                self.assertEqual(
                    hashlib.sha256(target_text.encode("utf-8")).hexdigest(),
                    target_digest,
                )
                self.assertEqual(target_files[path], target_digest)
            if "Previewed Authority" in target_text:
                saw_authority_change = True
                self.assertIn("Previewed Authority", str(item["unified_diff"]))
        self.assertTrue(saw_authority_change, changed)

    def test_apply_rolls_back_non_waivable_conformance_warnings_and_errors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Strict Transaction Profiles"
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            before = _tree_snapshot(project_root)
            original_run_profiles = cast(
                Callable[..., dict[str, Any]],
                project_refresh.conformance_check.run_profiles,
            )

            outcomes: dict[str, tuple[int, dict[str, object]]] = {}
            for diagnostic_kind in ("warning", "error"):
                with self.subTest(diagnostic_kind=diagnostic_kind):
                    diagnostic = (
                        "injected post-install warning absent from the reviewed plan"
                        if diagnostic_kind == "warning"
                        else "injected post-install conformance error"
                    )

                    def run_profiles_with_live_diagnostic(
                        profiles: list[str] | tuple[str, ...],
                        root: Path,
                        **kwargs: object,
                    ) -> dict[str, object]:
                        report = dict(original_run_profiles(profiles, root, **kwargs))
                        if Path(root).resolve() != project_root.resolve():
                            return report
                        key = "warnings" if diagnostic_kind == "warning" else "errors"
                        diagnostics = list(cast(list[str], report.get(key, [])))
                        diagnostics.append(diagnostic)
                        report[key] = diagnostics
                        report["status"] = "warn" if diagnostic_kind == "warning" else "fail"
                        return report

                    with mock.patch.object(
                        project_refresh.conformance_check,
                        "run_profiles",
                        side_effect=run_profiles_with_live_diagnostic,
                    ):
                        outcomes[diagnostic_kind] = project_refresh.apply_plan(
                            project_root,
                            built.payload,
                            approved_digest=str(built.payload["plan_sha256"]),
                            approved_actions=set(
                                cast(list[str], built.payload["required_actions"])
                            ),
                            approved_warnings=set(_warning_ids(built.payload)),
                        )
                    self.assertEqual(before, _tree_snapshot(project_root))

        for diagnostic_kind, (code, report) in outcomes.items():
            with self.subTest(diagnostic_kind=diagnostic_kind):
                self.assertEqual(project_refresh.EXIT_ROLLED_BACK, code, report)
                self.assertEqual("rolled-back", report["status"])
                details = " ".join(cast(list[str], report["errors"]))
                expected = (
                    "non-waivable warnings"
                    if diagnostic_kind == "warning"
                    else "did not pass"
                )
                self.assertIn(expected, details)

    def test_post_install_conformance_requires_exact_pass_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            with self.assertRaisesRegex(
                ValueError,
                "did not return pass without warnings",
            ), mock.patch.object(
                project_refresh.conformance_check,
                "run_profiles",
                return_value={"status": "warn", "errors": [], "warnings": []},
            ):
                project_refresh._run_profiles(
                    project_root,
                    ".",
                    ["core-project"],
                    project_kind="downstream",
                )

    def test_non_conformance_plan_warning_requires_exact_named_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["framework_reference"] = str(REPO_ROOT)
            candidate["answers"]["project_name"] = "Approved Plan Warning"
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )

            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            warning_ids = set(_warning_ids(built.payload))
            self.assertTrue(warning_ids, built.payload["warnings"])
            blocked_code, blocked = project_refresh.apply_plan(
                project_root,
                built.payload,
                approved_digest=str(built.payload["plan_sha256"]),
                approved_actions=set(
                    cast(list[str], built.payload["required_actions"])
                ),
                approved_warnings=set(),
            )
            applied_code, applied = project_refresh.apply_plan(
                project_root,
                built.payload,
                approved_digest=str(built.payload["plan_sha256"]),
                approved_actions=set(
                    cast(list[str], built.payload["required_actions"])
                ),
                approved_warnings=warning_ids,
            )

        self.assertEqual(project_refresh.EXIT_BLOCKED, blocked_code, blocked)
        self.assertEqual("approval-required", blocked["status"])
        self.assertEqual(0, applied_code, applied)

    def test_exact_preimage_bundle_supports_verified_apply_and_exact_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            removed_preimage = project_root / "AGENTS.md"
            removed_preimage.chmod(0o640)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Restorable Revision"
            candidate["answers"]["include_findings"] = True
            candidate["runtime"] = "claude-code"
            candidate_path = root / "candidate.json"
            candidate_path.write_text(
                json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            plan_code, plan = _run_cli(
                [
                    "plan",
                    "--project-root",
                    str(project_root),
                    "--contract-root",
                    ".",
                    "--candidate-input",
                    str(candidate_path),
                    "--backout-root",
                    str(backout_root),
                ]
            )
            self.assertEqual(0, plan_code, plan)
            original = {
                str(operation["path"]): (
                    None
                    if operation["current_sha256"] is None
                    else (project_root / str(operation["path"])).read_bytes()
                )
                for operation in plan["operations"]
                if operation["action"] != "preserve"
            }
            plan_path = root / "bundle-plan.json"
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            create_code, created = _run_cli(
                [
                    "backout-create",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(plan_path),
                    "--backout-root",
                    str(backout_root),
                ]
            )
            self.assertEqual(0, create_code, created)
            bundle_path = Path(str(created.get("bundle", backout_root / "missing")))
            bundle_modes = {
                "bundle": stat.S_IMODE(bundle_path.stat().st_mode),
                "manifest": stat.S_IMODE(
                    (bundle_path / project_refresh.BACKOUT_BUNDLE_MANIFEST).stat().st_mode
                ),
                "files": stat.S_IMODE((bundle_path / "files").stat().st_mode),
            }
            blob_modes = {
                stat.S_IMODE(path.stat().st_mode)
                for path in (bundle_path / "files").iterdir()
            }
            bundle_manifest_path = bundle_path / project_refresh.BACKOUT_BUNDLE_MANIFEST
            bundle_manifest_path.chmod(0o644)
            insecure_code, insecure = _run_cli(
                [
                    "backout-verify",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(plan_path),
                    "--backout-root",
                    str(backout_root),
                ]
            )
            bundle_manifest_path.chmod(0o600)
            apply_arguments = [
                "apply",
                "--project-root",
                str(project_root),
                "--plan",
                str(plan_path),
                "--approve-plan-sha256",
                str(plan["plan_sha256"]),
            ]
            for action_id in plan["required_actions"]:
                apply_arguments.extend(["--approve-action", str(action_id)])
            for warning_id in _warning_ids(plan):
                apply_arguments.extend(["--approve-warning", warning_id])
            removal_operation = next(
                operation
                for operation in plan["operations"]
                if operation["action"] == "remove"
                and operation["path"] == "AGENTS.md"
            )
            self.assertEqual(0o640, removal_operation["current_mode"])
            removed_preimage.chmod(0o600)
            mode_drift_verify_code, mode_drift_verify = _run_cli(
                [
                    "backout-verify",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(plan_path),
                    "--backout-root",
                    str(backout_root),
                    "--require-project-preimage",
                ]
            )
            mode_drift_apply_code, mode_drift_apply = _run_cli(apply_arguments)
            mode_after_preimage_refusal = stat.S_IMODE(removed_preimage.stat().st_mode)
            removed_preimage.chmod(0o640)
            verify_code, verified = _run_cli(
                [
                    "backout-verify",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(plan_path),
                    "--backout-root",
                    str(backout_root),
                    "--require-project-preimage",
                ]
            )
            tree_before_apply = _tree_snapshot(project_root)
            apply_code, applied = _run_cli(apply_arguments)
            enabled_findings = (project_root / "FINDINGS.md").read_text(
                encoding="utf-8"
            )
            receipt_after_apply = json.loads(
                (project_root / project_bootstrap.INSTANCE_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            restore_arguments = [
                "backout-restore",
                "--project-root",
                str(project_root),
                "--plan",
                str(plan_path),
                "--backout-root",
                str(backout_root),
                "--approve-plan-sha256",
                str(plan["plan_sha256"]),
                "--approve-refresh-transaction-id",
                str(plan["refresh_transaction_id"]),
            ]
            changed_operation = next(
                operation
                for operation in plan["operations"]
                if operation["action"] in {"create", "replace"}
            )
            changed_target_path = project_root / str(changed_operation["path"])
            exact_target_bytes = changed_target_path.read_bytes()
            exact_target_mode = stat.S_IMODE(changed_target_path.stat().st_mode)
            changed_target_path.chmod(0o600 if exact_target_mode != 0o600 else 0o640)
            stale_mode_code, stale_mode = _run_cli(restore_arguments)
            mode_after_target_refusal = stat.S_IMODE(changed_target_path.stat().st_mode)
            changed_target_path.chmod(exact_target_mode)
            later_work = exact_target_bytes + b"\nLater project work.\n"
            changed_target_path.write_bytes(later_work)
            stale_target_code, stale_target = _run_cli(restore_arguments)
            stale_target_bytes = changed_target_path.read_bytes()
            changed_target_path.write_bytes(exact_target_bytes)

            exact_bundle_manifest = bundle_manifest_path.read_bytes()
            bundle_manifest = json.loads(exact_bundle_manifest)
            present_entry = next(
                entry for entry in bundle_manifest["entries"] if entry["state"] == "file"
            )
            original_entry_mode = present_entry["mode"]
            present_entry["mode"] = 0o600 if original_entry_mode != 0o600 else 0o640
            bundle_manifest_path.write_bytes(
                project_refresh._canonical_json_bytes(bundle_manifest)
            )
            tampered_mode_code, tampered_mode = _run_cli(restore_arguments)
            bundle_manifest_path.write_bytes(exact_bundle_manifest)
            blob_path = bundle_path / str(present_entry["blob"])
            exact_blob = blob_path.read_bytes()
            project_before_corrupt_bundle = {
                str(operation["path"]): (
                    (project_root / str(operation["path"])).read_bytes()
                    if (project_root / str(operation["path"])).exists()
                    else None
                )
                for operation in plan["operations"]
            }
            blob_path.write_bytes(exact_blob + b"corrupt")
            corrupt_bundle_code, corrupt_bundle = _run_cli(restore_arguments)
            project_after_corrupt_bundle = {
                str(operation["path"]): (
                    (project_root / str(operation["path"])).read_bytes()
                    if (project_root / str(operation["path"])).exists()
                    else None
                )
                for operation in plan["operations"]
            }
            blob_path.write_bytes(exact_blob)
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transactional_write_outputs",
                side_effect=ValueError("simulated bounded restore preflight failure"),
            ):
                preflight_code, preflight = _run_cli(restore_arguments)
            restore_code, restored = _run_cli(restore_arguments)
            tree_after_restore = _tree_snapshot(project_root)
            restored_bytes = {
                path: None if not (project_root / path).exists() else (project_root / path).read_bytes()
                for path in original
            }
            inspected_after_restore = project_refresh.inspect_project(project_root, ".")
            reapply_code, reapplied = _run_cli(apply_arguments)
            inspected_after_reapply = project_refresh.inspect_project(project_root, ".")

        self.assertEqual(0, plan_code, plan)
        self.assertIn("USE-EXACT-PREIMAGE-BUNDLE", plan["required_actions"])
        self.assertEqual(0, create_code, created)
        self.assertEqual("backout-bundle-created", created["status"])
        self.assertEqual({"bundle": 0o700, "manifest": 0o600, "files": 0o700}, bundle_modes)
        self.assertEqual({0o600}, blob_modes)
        self.assertEqual(project_refresh.EXIT_BLOCKED, insecure_code, insecure)
        self.assertTrue(
            any("group or world" in error for error in insecure["errors"]),
            insecure,
        )
        self.assertEqual(
            project_refresh.EXIT_BLOCKED,
            mode_drift_verify_code,
            mode_drift_verify,
        )
        self.assertEqual("invalid-backout-bundle", mode_drift_verify["status"])
        self.assertIn("preimage changed", " ".join(mode_drift_verify["errors"]))
        self.assertEqual(
            project_refresh.EXIT_BLOCKED,
            mode_drift_apply_code,
            mode_drift_apply,
        )
        self.assertEqual("invalid-backout-bundle", mode_drift_apply["status"])
        self.assertEqual(0o600, mode_after_preimage_refusal)
        self.assertEqual(0, verify_code, verified)
        self.assertEqual(0, apply_code, applied)
        self.assertIn(
            project_state_identity.MARKDOWN_STATE_MARKER,
            enabled_findings,
        )
        self.assertIn("FINDINGS.md", receipt_after_apply["mutable_files"])
        self.assertEqual(project_refresh.EXIT_BLOCKED, stale_mode_code, stale_mode)
        self.assertEqual("stale-target", stale_mode["status"])
        self.assertNotEqual(exact_target_mode, mode_after_target_refusal)
        self.assertEqual(project_refresh.EXIT_BLOCKED, stale_target_code, stale_target)
        self.assertEqual("stale-target", stale_target["status"])
        self.assertEqual(later_work, stale_target_bytes)
        self.assertEqual(
            project_refresh.EXIT_BLOCKED,
            tampered_mode_code,
            tampered_mode,
        )
        self.assertEqual("invalid-backout-bundle", tampered_mode["status"])
        self.assertEqual(
            project_refresh.EXIT_BLOCKED,
            corrupt_bundle_code,
            corrupt_bundle,
        )
        self.assertEqual("invalid-backout-bundle", corrupt_bundle["status"])
        self.assertEqual(project_before_corrupt_bundle, project_after_corrupt_bundle)
        self.assertEqual(project_refresh.EXIT_ROLLED_BACK, preflight_code, preflight)
        self.assertEqual("rolled-back", preflight["status"])
        self.assertIn("simulated bounded restore", preflight["errors"][0])
        self.assertEqual(0, restore_code, restored)
        self.assertEqual("restored", restored["status"])
        self.assertEqual("pass", restored["verification"]["recorded_preimage"])
        self.assertEqual(original, restored_bytes)
        self.assertEqual(tree_before_apply, tree_after_restore)
        self.assertEqual("current", inspected_after_restore["status"])
        self.assertEqual(0, reapply_code, reapplied)
        self.assertEqual("applied", reapplied["status"])
        self.assertEqual("current", inspected_after_reapply["status"])

    def test_optional_mutable_state_retirement_is_explicit_atomic_and_restorable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(
                project_root,
                answer_overrides={"include_precedents": True},
            )
            state_path = project_root / "PRECEDENTS.md"
            original_state = state_path.read_bytes()
            self.assertIn(
                project_state_identity.MARKDOWN_STATE_MARKER.encode("utf-8"),
                original_state,
            )
            custom_state = original_state.replace(
                b"# Precedents\n",
                b"# Precedents\n\n<!-- exact retirement restore probe -->\n",
                1,
            )
            self.assertNotEqual(original_state, custom_state)
            state_path.write_bytes(custom_state)
            state_path.chmod(0o640)

            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["include_precedents"] = False
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)

            no_backout = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            built = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            plan = built.payload
            operation = next(
                item
                for item in cast(list[dict[str, object]], plan["operations"])
                if item["path"] == "PRECEDENTS.md"
            )
            retirement_warning = project_refresh._optional_state_retirement_warning(
                "PRECEDENTS.md",
                "mutable",
            )
            target_receipt = json.loads(
                built.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
            )
            target_input = cast(dict[str, object], plan["target_input"])
            target_answers = cast(dict[str, object], target_input["answers"])
            tree_before_apply = _tree_snapshot(project_root)
            retirement_warning_id = project_refresh._warning_id(retirement_warning)

            missing_action_code, missing_action = project_refresh.apply_plan(
                project_root,
                plan,
                approved_digest=str(plan["plan_sha256"]),
                approved_actions=(
                    set(cast(list[str], plan["required_actions"]))
                    - {"RETIRE-MUTABLE-0001"}
                ),
                approved_warnings=set(_warning_ids(plan)),
            )
            tree_after_missing_action = _tree_snapshot(project_root)
            missing_warning_code, missing_warning = project_refresh.apply_plan(
                project_root,
                plan,
                approved_digest=str(plan["plan_sha256"]),
                approved_actions=set(cast(list[str], plan["required_actions"])),
                approved_warnings=set(_warning_ids(plan)) - {retirement_warning_id},
            )
            tree_after_missing_warning = _tree_snapshot(project_root)

            create_code, created = project_refresh.create_backout_bundle(
                project_root,
                plan,
                backout_root,
            )
            apply_code, applied = project_refresh.apply_plan(
                project_root,
                plan,
                approved_digest=str(plan["plan_sha256"]),
                approved_actions=set(cast(list[str], plan["required_actions"])),
                approved_warnings=set(_warning_ids(plan)),
            )
            applied_receipt = json.loads(
                (project_root / project_bootstrap.INSTANCE_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            applied_input = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            state_absent_after_apply = not state_path.exists()
            inspected_after_apply = project_refresh.inspect_project(project_root)
            todo_path = project_root / "TODO.md"
            exact_post_apply_todo = todo_path.read_bytes()
            exact_post_apply_todo_mode = stat.S_IMODE(todo_path.stat().st_mode)
            todo_path.write_bytes(
                exact_post_apply_todo
                + b"\n<!-- post-apply managed-target drift probe -->\n"
            )
            todo_path.chmod(
                0o600 if exact_post_apply_todo_mode != 0o600 else 0o640
            )
            tree_before_stale_restore = _tree_snapshot(project_root)
            stale_restore_code, stale_restore = (
                project_refresh.restore_backout_bundle(
                    project_root,
                    plan,
                    backout_root,
                    approved_digest=str(plan["plan_sha256"]),
                    approved_transaction_id=str(plan["refresh_transaction_id"]),
                )
            )
            tree_after_stale_restore = _tree_snapshot(project_root)
            todo_path.write_bytes(exact_post_apply_todo)
            todo_path.chmod(exact_post_apply_todo_mode)
            restore_code, restored = project_refresh.restore_backout_bundle(
                project_root,
                plan,
                backout_root,
                approved_digest=str(plan["plan_sha256"]),
                approved_transaction_id=str(plan["refresh_transaction_id"]),
            )
            tree_after_restore = _tree_snapshot(project_root)
            restored_receipt = json.loads(
                (project_root / project_bootstrap.INSTANCE_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            restored_input = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            restored_state_bytes = state_path.read_bytes()
            restored_state_mode = stat.S_IMODE(state_path.stat().st_mode)
            inspected_after_restore = project_refresh.inspect_project(project_root)

        self.assertIsNone(no_backout.payload)
        self.assertIn(
            "requires a verified exact-preimage backout bundle",
            " ".join(no_backout.errors),
        )
        self.assertEqual("remove", operation["action"])
        self.assertEqual("mutable", operation["category"])
        self.assertEqual(hashlib.sha256(custom_state).hexdigest(), operation["current_sha256"])
        self.assertIsNone(operation["target_sha256"])
        self.assertEqual(0o640, operation["current_mode"])
        self.assertIsNone(operation["target_mode"])
        self.assertEqual("RETIRE-MUTABLE-0001", operation["approval_id"])
        self.assertIn(
            "RETIRE-MUTABLE-0001",
            cast(list[str], plan["required_actions"]),
        )
        self.assertIn(
            "USE-EXACT-PREIMAGE-BUNDLE",
            cast(list[str], plan["required_actions"]),
        )
        self.assertIn(
            {
                "id": retirement_warning_id,
                "message": retirement_warning,
            },
            cast(list[dict[str, str]], plan["warnings"]),
        )
        self.assertNotIn("PRECEDENTS.md", built.target_outputs)
        self.assertNotIn("PRECEDENTS.md", target_receipt["mutable_files"])
        self.assertNotIn("multi-agent-managed", target_receipt["active_profiles"])
        self.assertFalse(target_answers["include_precedents"])
        self.assertEqual(project_refresh.EXIT_BLOCKED, missing_action_code, missing_action)
        self.assertEqual("approval-required", missing_action["status"])
        self.assertEqual(tree_before_apply, tree_after_missing_action)
        self.assertEqual(
            project_refresh.EXIT_BLOCKED,
            missing_warning_code,
            missing_warning,
        )
        self.assertEqual("approval-required", missing_warning["status"])
        self.assertEqual(tree_before_apply, tree_after_missing_warning)
        self.assertEqual(0, create_code, created)
        self.assertEqual("backout-bundle-created", created["status"])
        self.assertEqual(0, apply_code, applied)
        self.assertEqual("applied", applied["status"])
        self.assertTrue(state_absent_after_apply)
        self.assertNotIn("PRECEDENTS.md", applied_receipt["mutable_files"])
        self.assertNotIn("multi-agent-managed", applied_receipt["active_profiles"])
        self.assertFalse(applied_input["answers"]["include_precedents"])
        self.assertEqual("current", inspected_after_apply["status"])
        self.assertEqual(project_refresh.EXIT_BLOCKED, stale_restore_code, stale_restore)
        self.assertEqual("stale-target", stale_restore["status"])
        self.assertEqual(tree_before_stale_restore, tree_after_stale_restore)
        self.assertEqual(0, restore_code, restored)
        self.assertEqual("restored", restored["status"])
        self.assertEqual(tree_before_apply, tree_after_restore)
        self.assertEqual(custom_state, restored_state_bytes)
        self.assertEqual(0o640, restored_state_mode)
        self.assertIn("PRECEDENTS.md", restored_receipt["mutable_files"])
        self.assertIn("multi-agent-managed", restored_receipt["active_profiles"])
        self.assertTrue(restored_input["answers"]["include_precedents"])
        self.assertEqual("current", inspected_after_restore["status"])

    def test_backout_restore_rejects_wrong_refresh_transaction_id_before_bundle_access(
        self,
    ) -> None:
        clean = bootstrap_transaction.BootstrapRecoveryStatus(
            state="clean",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Restore Approval Binding"
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            self.assertFalse(project_refresh._validate_plan(built.payload))
            refresh_transaction_id = str(built.payload["refresh_transaction_id"])
            wrong_transaction_id = (
                "0" * 32 if refresh_transaction_id != "0" * 32 else "1" * 32
            )
            project_before = _tree_snapshot(project_root)
            backout_before = _tree_snapshot(backout_root)
            with (
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transaction_recovery_status",
                    return_value=clean,
                ) as recovery_status,
                mock.patch.object(
                    project_refresh,
                    "_backout_bundle_location",
                    side_effect=AssertionError("wrong approval reached bundle location"),
                ) as bundle_location,
                mock.patch.object(
                    project_refresh,
                    "_read_verified_backout_bundle",
                    side_effect=AssertionError("wrong approval read bundle bytes"),
                ) as bundle_read,
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transactional_write_outputs",
                    side_effect=AssertionError("wrong approval mutated project tree"),
                ) as transaction_write,
            ):
                code, report = project_refresh.restore_backout_bundle(
                    project_root,
                    built.payload,
                    backout_root,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_transaction_id=wrong_transaction_id,
                )
            project_after = _tree_snapshot(project_root)
            backout_after = _tree_snapshot(backout_root)

        self.assertEqual(project_refresh.EXIT_BLOCKED, code, report)
        self.assertEqual("approval-required", report["status"])
        self.assertIn(
            "--approve-refresh-transaction-id must exactly match",
            " ".join(cast(list[str], report["errors"])),
        )
        recovery_status.assert_called_once_with(project_root.resolve(strict=False))
        bundle_location.assert_not_called()
        bundle_read.assert_not_called()
        transaction_write.assert_not_called()
        self.assertEqual(project_before, project_after)
        self.assertEqual(backout_before, backout_after)

    def test_wrapper_backout_restores_exact_tree_and_refuses_unrelated_siblings(
        self,
    ) -> None:
        wrapper_id = "project_init"
        wrapper_output = integration_registry.wrapper_output_map(
            "codex",
            [wrapper_id],
            REPO_ROOT,
        )[wrapper_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root, runtime="codex")
            existing_wrapper_parent = project_root / ".agents"
            existing_wrapper_parent.mkdir()
            (existing_wrapper_parent / "preserved.txt").write_text(
                "Pre-existing project data.\n",
                encoding="utf-8",
            )
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["runtime_wrappers"] = [wrapper_id]
            candidate_path = root / "wrapper-candidate.json"
            candidate_path.write_text(
                json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            plan_code, plan = _run_cli(
                [
                    "plan",
                    "--project-root",
                    str(project_root),
                    "--candidate-input",
                    str(candidate_path),
                    "--backout-root",
                    str(backout_root),
                ]
            )
            self.assertEqual(0, plan_code, plan)
            plan_path = root / "wrapper-plan.json"
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            create_code, created = _run_cli(
                [
                    "backout-create",
                    "--project-root",
                    str(project_root),
                    "--plan",
                    str(plan_path),
                    "--backout-root",
                    str(backout_root),
                ]
            )
            self.assertEqual(0, create_code, created)
            tree_before_apply = _tree_snapshot(project_root)
            apply_arguments = [
                "apply",
                "--project-root",
                str(project_root),
                "--plan",
                str(plan_path),
                "--approve-plan-sha256",
                str(plan["plan_sha256"]),
            ]
            for action_id in plan["required_actions"]:
                apply_arguments.extend(["--approve-action", str(action_id)])
            for warning_id in _warning_ids(plan):
                apply_arguments.extend(["--approve-warning", warning_id])
            apply_code, applied = _run_cli(apply_arguments)
            self.assertEqual(0, apply_code, applied)

            restore_arguments = [
                "backout-restore",
                "--project-root",
                str(project_root),
                "--plan",
                str(plan_path),
                "--backout-root",
                str(backout_root),
                "--approve-plan-sha256",
                str(plan["plan_sha256"]),
                "--approve-refresh-transaction-id",
                str(plan["refresh_transaction_id"]),
            ]
            unrelated = project_root / ".agents" / "skills" / "unrelated.txt"
            unrelated.write_text("Unrelated later work.\n", encoding="utf-8")
            refused_code, refused = _run_cli(restore_arguments)
            target_after_refusal = (project_root / wrapper_output).read_bytes()
            unrelated_after_refusal = unrelated.read_bytes()
            unrelated.unlink()
            restore_code, restored = _run_cli(restore_arguments)
            tree_after_restore = _tree_snapshot(project_root)
            preserved_parent_remains = (
                project_root / ".agents" / "preserved.txt"
            ).is_file()
            introduced_skills_parent_remains = (
                project_root / ".agents" / "skills"
            ).exists()

        self.assertEqual(0, plan_code, plan)
        self.assertEqual(
            [
                ".agents/skills",
                ".agents/skills/master-prompt-new-project",
            ],
            plan["absent_parent_directories"],
        )
        self.assertEqual(0, create_code, created)
        self.assertEqual("backout-bundle-created", created["status"])
        self.assertEqual(0, apply_code, applied)
        self.assertEqual("applied", applied["status"])
        self.assertEqual(project_refresh.EXIT_ROLLED_BACK, refused_code, refused)
        self.assertEqual("rolled-back", refused["status"])
        self.assertTrue(
            any("unrelated" in error for error in refused["errors"]),
            refused,
        )
        self.assertTrue(target_after_refusal)
        self.assertEqual(b"Unrelated later work.\n", unrelated_after_refusal)
        self.assertEqual(0, restore_code, restored)
        self.assertEqual("restored", restored["status"])
        self.assertEqual(tree_before_apply, tree_after_restore)
        self.assertTrue(preserved_parent_remains)
        self.assertFalse(introduced_skills_parent_remains)

    def test_dirty_backout_root_blocks_every_non_recovery_bundle_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Backout Root Gate"
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            create_code, created = project_refresh.create_backout_bundle(
                project_root,
                built.payload,
                backout_root,
            )
            self.assertEqual(0, create_code, created)
            _validated_root, bundle_ref, location_errors = (
                project_refresh._backout_bundle_location(
                    built.payload,
                    backout_root,
                    require_current=True,
                )
            )
            self.assertFalse(location_errors, location_errors)
            assert bundle_ref is not None
            dirty = bootstrap_transaction.BootstrapRecoveryStatus(
                state="recovery-required",
                transaction_id="f" * 32,
                phase="applying",
                operation_paths=project_refresh._expected_backout_transaction_paths(
                    built.payload,
                    bundle_ref,
                ),
                can_rollback=True,
                can_finalize=False,
                errors=(),
            )
            contradictory_clean = bootstrap_transaction.BootstrapRecoveryStatus(
                state="clean",
                transaction_id=None,
                phase="applying",
                operation_paths=project_refresh._expected_backout_transaction_paths(
                    built.payload,
                    bundle_ref,
                ),
                can_rollback=False,
                can_finalize=False,
                errors=(),
            )
            clean = bootstrap_transaction.BootstrapRecoveryStatus(
                state="clean",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(),
            )

            def status_for(path: Path) -> bootstrap_transaction.BootstrapRecoveryStatus:
                return dirty if Path(path).resolve() == backout_root.resolve() else clean

            before = {
                str(path.relative_to(project_root)): path.read_bytes()
                for path in project_root.rglob("*")
                if path.is_file()
            }
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                side_effect=status_for,
            ):
                blocked_create = project_refresh.create_backout_bundle(
                    project_root,
                    built.payload,
                    backout_root,
                )
                blocked_verify = project_refresh.verify_backout_bundle(
                    project_root,
                    built.payload,
                    backout_root,
                    require_project_preimage=True,
                )
                blocked_apply = project_refresh.apply_plan(
                    project_root,
                    built.payload,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_actions=set(
                        cast(list[str], built.payload["required_actions"])
                    ),
                    approved_warnings=set(_warning_ids(built.payload)),
                )
                blocked_restore = project_refresh.restore_backout_bundle(
                    project_root,
                    built.payload,
                    backout_root,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_transaction_id=str(
                        built.payload["refresh_transaction_id"]
                    ),
                )
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                return_value=contradictory_clean,
            ):
                contradictory_verify = project_refresh.verify_backout_bundle(
                    project_root,
                    built.payload,
                    backout_root,
                    require_project_preimage=True,
                )
            after = {
                str(path.relative_to(project_root)): path.read_bytes()
                for path in project_root.rglob("*")
                if path.is_file()
            }

        for label, result in (
            ("create", blocked_create),
            ("verify", blocked_verify),
            ("apply", blocked_apply),
            ("restore", blocked_restore),
        ):
            with self.subTest(operation=label):
                code, report = result
                self.assertEqual(project_refresh.EXIT_RECOVERY_REQUIRED, code, report)
                self.assertEqual("backout-bundle-recovery-required", report["status"])
        contradictory_code, contradictory_report = contradictory_verify
        self.assertEqual(
            project_refresh.EXIT_RECOVERY_REQUIRED,
            contradictory_code,
            contradictory_report,
        )
        self.assertEqual(
            "backout-bundle-recovery-required",
            contradictory_report["status"],
        )
        self.assertEqual(before, after)

    def test_bundle_change_after_preflight_rolls_back_project_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Bundle Race"
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            built = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            create_code, created = project_refresh.create_backout_bundle(
                project_root,
                built.payload,
                backout_root,
            )
            self.assertEqual(0, create_code, created)
            bundle_path = Path(str(created["bundle"]))
            manifest = json.loads(
                (bundle_path / project_refresh.BACKOUT_BUNDLE_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            entry = next(item for item in manifest["entries"] if item["state"] == "file")
            blob_path = bundle_path / str(entry["blob"])
            blob_bytes = blob_path.read_bytes()
            before = _tree_snapshot(project_root)
            original_verify = cast(
                Callable[..., tuple[int, dict[str, object]]],
                project_refresh.verify_backout_bundle,
            )
            changed = False

            def verify_then_change_bundle(
                *args: object,
                **kwargs: object,
            ) -> tuple[int, dict[str, object]]:
                nonlocal changed
                result = original_verify(*args, **kwargs)
                if result[0] == 0 and not changed:
                    blob_path.write_bytes(blob_bytes + b"changed-after-preflight")
                    changed = True
                return result

            with mock.patch.object(
                project_refresh,
                "verify_backout_bundle",
                side_effect=verify_then_change_bundle,
            ):
                apply_code, applied = project_refresh.apply_plan(
                    project_root,
                    built.payload,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_actions=set(
                        cast(list[str], built.payload["required_actions"])
                    ),
                    approved_warnings=set(_warning_ids(built.payload)),
                )
            after = _tree_snapshot(project_root)
            blob_path.write_bytes(blob_bytes)

        self.assertTrue(changed)
        self.assertEqual(project_refresh.EXIT_ROLLED_BACK, apply_code, applied)
        self.assertEqual("rolled-back", applied["status"])
        applied_errors = cast(list[str], applied["errors"])
        self.assertIn("changed after preflight", " ".join(applied_errors))
        self.assertEqual(before, after)

    def test_refresh_revalidates_preimages_preserves_state_and_retires_old_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)

            inspect_code, initial = _run_cli(
                ["inspect", "--project-root", str(project_root), "--check"]
            )
            no_op_code, no_op = _run_cli(
                ["plan", "--project-root", str(project_root)]
            )

            custom_todo = (
                "state_schema_version: 1\n"
                "active_count: 1\n\n"
                f"{project_state_identity.MARKDOWN_STATE_MARKER}\n\n"
                "# TODO\n\n"
                "- [ ] TODO-2026-07-14-01 Preserve this current work.\n"
            )
            todo_path = project_root / "TODO.md"
            todo_path.write_text(custom_todo, encoding="utf-8")
            current_input = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            current_input["answers"]["project_name"] = "Revised"
            candidate_path = root / "candidate-input.json"
            candidate_path.write_text(
                json.dumps(current_input, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            revise_code, revise_plan = _run_cli(
                [
                    "plan",
                    "--project-root",
                    str(project_root),
                    "--contract-root",
                    ".",
                    "--candidate-input",
                    str(candidate_path),
                    "--accept-no-post-apply-backout",
                ]
            )
            plan_path = root / "refresh-plan.json"
            plan_path.write_text(
                json.dumps(revise_plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            # The plan binds mutable state even though refresh will preserve it.
            changed_todo = custom_todo.replace("current work", "changed after planning")
            todo_path.write_text(changed_todo, encoding="utf-8")
            stale_arguments = [
                "apply",
                "--project-root",
                str(project_root),
                "--plan",
                str(plan_path),
                "--approve-plan-sha256",
                str(revise_plan["plan_sha256"]),
            ]
            for warning_id in _warning_ids(revise_plan):
                stale_arguments.extend(["--approve-warning", warning_id])
            for action_id in revise_plan["required_actions"]:
                stale_arguments.extend(["--approve-action", str(action_id)])
            stale_code, stale = _run_cli(stale_arguments)
            todo_path.write_text(custom_todo, encoding="utf-8")

            apply_arguments = list(stale_arguments)
            rebuilt_before_apply = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=revise_plan["target_input"],
                post_apply_backout=revise_plan["post_apply_backout"],
            )
            differing_plan_keys = sorted(
                key
                for key in revise_plan
                if rebuilt_before_apply.payload is None
                or revise_plan[key] != rebuilt_before_apply.payload.get(key)
            )
            apply_code, applied = _run_cli(apply_arguments)
            revised_sow = (project_root / "STATEMENT_OF_WORK.md").read_text(
                encoding="utf-8"
            )
            preserved_todo = todo_path.read_text(encoding="utf-8")
            current_after_revision = project_refresh.inspect_project(project_root, ".")

            # A runtime revision is input-owned.  Removing the previous immutable
            # entrypoint additionally requires the action id from this exact plan.
            claude_input = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            claude_input["runtime"] = "claude-code"
            claude_candidate = root / "claude-input.json"
            claude_candidate.write_text(
                json.dumps(claude_input, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            runtime_plan_code, runtime_plan = _run_cli(
                [
                    "plan",
                    "--project-root",
                    str(project_root),
                    "--contract-root",
                    ".",
                    "--candidate-input",
                    str(claude_candidate),
                    "--accept-no-post-apply-backout",
                ]
            )
            runtime_plan_path = root / "runtime-plan.json"
            runtime_plan_path.write_text(
                json.dumps(runtime_plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            missing_action_arguments = [
                "apply",
                "--project-root",
                str(project_root),
                "--plan",
                str(runtime_plan_path),
                "--approve-plan-sha256",
                str(runtime_plan["plan_sha256"]),
            ]
            for warning_id in _warning_ids(runtime_plan):
                missing_action_arguments.extend(["--approve-warning", warning_id])
            for action_id in runtime_plan["required_actions"]:
                if not str(action_id).startswith("RETIRE-IMMUTABLE-"):
                    missing_action_arguments.extend(["--approve-action", str(action_id)])
            missing_action_code, missing_action = _run_cli(missing_action_arguments)
            approved_arguments = list(missing_action_arguments)
            for action_id in runtime_plan["required_actions"]:
                if str(action_id).startswith("RETIRE-IMMUTABLE-"):
                    approved_arguments.extend(["--approve-action", str(action_id)])
            runtime_apply_code, runtime_applied = _run_cli(approved_arguments)
            final_inspect = project_refresh.inspect_project(project_root, ".")
            old_entrypoint_exists = (project_root / "AGENTS.md").exists()
            new_entrypoint_exists = (project_root / "CLAUDE.md").is_file()
            final_todo = (project_root / "TODO.md").read_text(encoding="utf-8")

        self.assertEqual(0, inspect_code, initial)
        self.assertEqual("current", initial["status"])
        self.assertEqual(0, no_op_code, no_op)
        self.assertEqual("no-op", no_op["mode"])
        self.assertEqual(0, revise_code, revise_plan)
        self.assertEqual("revise", revise_plan["mode"])
        self.assertEqual(1, stale_code, stale)
        self.assertEqual("stale-plan", stale["status"])
        self.assertEqual([], differing_plan_keys, rebuilt_before_apply.errors)
        self.assertEqual(0, apply_code, applied)
        self.assertEqual("applied", applied["status"])
        self.assertIn("Statement of Work — Revised", revised_sow)
        self.assertEqual(custom_todo, preserved_todo)
        self.assertEqual("current", current_after_revision["status"])
        self.assertEqual(0, runtime_plan_code, runtime_plan)
        self.assertIn("RETIRE-IMMUTABLE-0001", runtime_plan["required_actions"])
        self.assertEqual(1, missing_action_code, missing_action)
        self.assertEqual("approval-required", missing_action["status"])
        self.assertEqual(0, runtime_apply_code, runtime_applied)
        self.assertFalse(old_entrypoint_exists)
        self.assertTrue(new_entrypoint_exists)
        self.assertEqual(custom_todo, final_todo)
        self.assertEqual("current", final_inspect["status"])
    def test_orphan_transaction_blocks_inspection_and_planning(self) -> None:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="recovery-required",
            transaction_id="a" * 32,
            phase="applying",
            operation_paths=("AGENTS.md",),
            can_rollback=True,
            can_finalize=False,
            errors=(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                return_value=recovery,
            ):
                inspected = project_refresh.inspect_project(project_root, ".")
                planned = project_refresh.build_plan(project_root, ".")

        self.assertEqual("recovery-required", inspected["status"])
        self.assertIsNone(planned.payload)
        self.assertTrue(
            any("requires explicit recovery" in error for error in planned.errors),
            planned.errors,
        )

    def test_private_backout_recovery_is_plan_and_root_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Bundle Failure"
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            plan = project_refresh.build_plan(
                project_root,
                ".",
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(plan.payload, plan.errors)
            assert plan.payload is not None
            _validated_root, bundle_ref, location_errors = (
                project_refresh._backout_bundle_location(
                    plan.payload,
                    backout_root,
                    require_current=True,
                )
            )
            self.assertFalse(location_errors, location_errors)
            assert bundle_ref is not None
            expected_paths = project_refresh._expected_backout_transaction_paths(
                plan.payload,
                bundle_ref,
            )
            transaction_id = "d" * 32
            clean = bootstrap_transaction.BootstrapRecoveryStatus(
                state="clean",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(),
            )
            interrupted = bootstrap_transaction.BootstrapRecoveryStatus(
                state="recovery-required",
                transaction_id=transaction_id,
                phase="applying",
                operation_paths=expected_paths,
                can_rollback=True,
                can_finalize=False,
                errors=(),
            )
            unrelated = bootstrap_transaction.BootstrapRecoveryStatus(
                state="recovery-required",
                transaction_id=transaction_id,
                phase="applying",
                operation_paths=("unrelated-plan/private-artifact.bin",),
                can_rollback=True,
                can_finalize=False,
                errors=(),
            )
            nonactionable = bootstrap_transaction.BootstrapRecoveryStatus(
                state="recovery-required",
                transaction_id=transaction_id,
                phase="unknown",
                operation_paths=expected_paths,
                can_rollback=False,
                can_finalize=False,
                errors=(),
            )
            finalizable = bootstrap_transaction.BootstrapRecoveryStatus(
                state="verified",
                transaction_id=transaction_id,
                phase="verified",
                operation_paths=expected_paths,
                can_rollback=False,
                can_finalize=True,
                errors=(),
            )

            def bound_status_for(path: Path) -> bootstrap_transaction.BootstrapRecoveryStatus:
                return interrupted if Path(path).resolve() == backout_root.resolve() else clean

            def unrelated_status_for(
                path: Path,
            ) -> bootstrap_transaction.BootstrapRecoveryStatus:
                return unrelated if Path(path).resolve() == backout_root.resolve() else clean

            def status_for(
                selected: bootstrap_transaction.BootstrapRecoveryStatus,
            ) -> Callable[[Path], bootstrap_transaction.BootstrapRecoveryStatus]:
                def selected_status(
                    path: Path,
                ) -> bootstrap_transaction.BootstrapRecoveryStatus:
                    return (
                        selected
                        if Path(path).resolve() == backout_root.resolve()
                        else clean
                    )

                return selected_status

            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                side_effect=unrelated_status_for,
            ):
                mismatch_code, mismatch = project_refresh.create_backout_bundle(
                    project_root,
                    plan.payload,
                    backout_root,
                )
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                side_effect=bound_status_for,
            ):
                code, report = project_refresh.create_backout_bundle(
                    project_root,
                    plan.payload,
                    backout_root,
                )
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                side_effect=status_for(nonactionable),
            ):
                nonactionable_code, nonactionable_report = (
                    project_refresh.create_backout_bundle(
                        project_root,
                        plan.payload,
                        backout_root,
                    )
                )
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                side_effect=status_for(finalizable),
            ):
                finalizable_code, finalizable_report = (
                    project_refresh.create_backout_bundle(
                        project_root,
                        plan.payload,
                        backout_root,
                    )
                )
            with (
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transaction_recovery_status",
                    side_effect=unrelated_status_for,
                ),
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "rollback_interrupted_transaction",
                    return_value=clean,
                ) as unrelated_rollback,
            ):
                mismatch_recovery_code, mismatch_recovery = (
                    project_refresh.recover_backout_bundle(
                        project_root,
                        plan.payload,
                        backout_root,
                        action="rollback",
                        approved_transaction_id=transaction_id,
                    )
                )
            with (
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transaction_recovery_status",
                    side_effect=bound_status_for,
                ),
                mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "rollback_interrupted_transaction",
                    return_value=clean,
                ) as rollback,
            ):
                recovery_code, recovered = project_refresh.recover_backout_bundle(
                    project_root,
                    plan.payload,
                    backout_root,
                    action="rollback",
                    approved_transaction_id=transaction_id,
                )

        self.assertEqual(project_refresh.EXIT_RECOVERY_REQUIRED, mismatch_code, mismatch)
        self.assertNotIn("recovery_route", mismatch)
        mismatch_errors = cast(list[str], mismatch["errors"])
        self.assertTrue(
            any("do not match" in error for error in mismatch_errors),
            mismatch,
        )
        self.assertEqual(project_refresh.EXIT_RECOVERY_REQUIRED, code, report)
        self.assertEqual("backout-bundle-recovery-required", report["status"])
        self.assertEqual(str(backout_root.resolve()), report["recovery_root"])
        self.assertEqual(transaction_id, report["transaction_id"])
        recovery_route = cast(dict[str, Any], report["recovery_route"])
        self.assertEqual("backout-recover", recovery_route["command"])
        self.assertEqual("rollback", recovery_route["action"])
        self.assertEqual(str(project_root.resolve()), recovery_route["project_root"])
        self.assertEqual(
            project_refresh.EXIT_RECOVERY_REQUIRED,
            nonactionable_code,
            nonactionable_report,
        )
        self.assertNotIn("recovery_route", nonactionable_report)
        self.assertEqual(
            project_refresh.EXIT_RECOVERY_REQUIRED,
            finalizable_code,
            finalizable_report,
        )
        finalizable_route = cast(
            dict[str, Any],
            finalizable_report["recovery_route"],
        )
        self.assertEqual("finalize", finalizable_route["action"])
        self.assertEqual(
            project_refresh.EXIT_RECOVERY_REQUIRED,
            mismatch_recovery_code,
            mismatch_recovery,
        )
        self.assertEqual("invalid-backout-recovery-request", mismatch_recovery["status"])
        unrelated_rollback.assert_not_called()
        self.assertEqual(0, recovery_code, recovered)
        self.assertEqual("clean", recovered["status"])
        self.assertTrue(recovered["backout_recovery"])
        self.assertEqual(str(backout_root.resolve()), recovered["recovery_root"])
        rollback.assert_called_once_with(
            backout_root.resolve(),
            expected_transaction_id=transaction_id,
        )

    def test_active_transaction_is_busy_and_not_presented_as_recoverable(self) -> None:
        active = bootstrap_transaction.BootstrapRecoveryStatus(
            state="active",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            _materialize_project(project_root)
            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transaction_recovery_status",
                return_value=active,
            ):
                inspected = project_refresh.inspect_project(project_root, ".")
                planned = project_refresh.build_plan(project_root, ".")

        self.assertEqual("transaction-active", inspected["status"])
        self.assertFalse(inspected["can_rollback"])
        self.assertFalse(inspected["can_finalize"])
        self.assertIsNone(planned.payload)
        self.assertTrue(
            any("wait for its owner" in error for error in planned.errors),
            planned.errors,
        )
        self.assertFalse(
            any("requires explicit recovery" in error for error in planned.errors),
            planned.errors,
        )


    def test_recovery_routes_exactly_one_allowed_action_by_capability_and_id(
        self,
    ) -> None:
        clean = bootstrap_transaction.BootstrapRecoveryStatus(
            state="clean",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(),
        )
        cases = (
            (
                "rollback",
                "b" * 32,
                bootstrap_transaction.BootstrapRecoveryStatus(
                    state="recovery-required",
                    transaction_id="b" * 32,
                    phase="applying",
                    operation_paths=("AGENTS.md",),
                    can_rollback=True,
                    can_finalize=False,
                    errors=(),
                ),
                "finalize",
            ),
            (
                "finalize",
                "d" * 32,
                bootstrap_transaction.BootstrapRecoveryStatus(
                    state="verified",
                    transaction_id="d" * 32,
                    phase="verified",
                    operation_paths=("AGENTS.md",),
                    can_rollback=False,
                    can_finalize=True,
                    errors=(),
                ),
                "rollback",
            ),
        )
        for allowed_action, transaction_id, recovery, disallowed_action in cases:
            with self.subTest(action=allowed_action), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                project_before = _tree_snapshot(project_root)
                with (
                    mock.patch.object(
                        project_refresh.bootstrap_transaction,
                        "transaction_recovery_status",
                        return_value=recovery,
                    ) as recovery_status,
                    mock.patch.object(
                        project_refresh.bootstrap_transaction,
                        "rollback_interrupted_transaction",
                        return_value=clean,
                    ) as rollback,
                    mock.patch.object(
                        project_refresh.bootstrap_transaction,
                        "finalize_interrupted_transaction",
                        return_value=clean,
                    ) as finalize,
                ):
                    wrong_code, wrong = project_refresh.recover_project(
                        project_root,
                        action=allowed_action,
                        approved_transaction_id="f" * 32,
                    )
                    project_after_wrong_id = _tree_snapshot(project_root)
                    disallowed_code, disallowed = project_refresh.recover_project(
                        project_root,
                        action=disallowed_action,
                        approved_transaction_id=transaction_id,
                    )
                    project_after_disallowed_action = _tree_snapshot(project_root)
                    correct_code, correct = project_refresh.recover_project(
                        project_root,
                        action=allowed_action,
                        approved_transaction_id=transaction_id,
                    )

                self.assertEqual(project_refresh.EXIT_BLOCKED, wrong_code, wrong)
                self.assertEqual("approval-required", wrong["status"])
                self.assertEqual(project_before, project_after_wrong_id)
                self.assertEqual(
                    project_refresh.EXIT_BLOCKED,
                    disallowed_code,
                    disallowed,
                )
                self.assertEqual("action-not-allowed", disallowed["status"])
                self.assertEqual(project_before, project_after_disallowed_action)
                self.assertEqual(0, correct_code, correct)
                self.assertEqual("clean", correct["status"])
                recovery_status.assert_has_calls(
                    [mock.call(project_root.resolve(strict=False))] * 3
                )
                self.assertEqual(3, recovery_status.call_count)
                selected = rollback if allowed_action == "rollback" else finalize
                unselected = finalize if allowed_action == "rollback" else rollback
                selected.assert_called_once_with(
                    project_root.resolve(strict=False),
                    expected_transaction_id=transaction_id,
                )
                unselected.assert_not_called()


if __name__ == "__main__":
    unittest.main()
