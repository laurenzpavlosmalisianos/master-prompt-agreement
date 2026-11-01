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
import project_instance_lint  # noqa: E402
import project_refresh  # noqa: E402
import safe_paths  # noqa: E402


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
    authority_module_digests, authority_errors = (
        project_bootstrap.authority_module_digest_records(
            answers,
            project_root,
            forbidden_paths=frozenset(
                {
                    *managed,
                    input_name,
                    project_bootstrap.INSTANCE_MANIFEST,
                }
            ),
        )
    )
    if authority_errors:
        raise AssertionError(authority_errors)
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
            authority_module_digests=authority_module_digests,
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
                *,
                contract_root_ref: str = ".",
            ) -> tuple[dict[str, object] | None, list[str]]:
                return project_refresh.render_candidate_input(
                    answers_path=answers_path,
                    project_root=project_root,
                    project_kind="downstream",
                    contract_root_ref=contract_root_ref,
                    runtime="generic",
                    runtime_wrappers=runtime_wrappers,
                    framework_reference=os.path.relpath(REPO_ROOT, project_root),
                    framework_revision_policy="live",
                )

            results = [
                render_with(None),
                render_with(()),
                render_with((), contract_root_ref="contracts"),
            ]

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

    def test_schema6_authority_module_receipt_and_reviewed_rebind_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            authority_path = project_root / "AUTHORITY.md"
            authority_path.write_text("# Approved authority\n", encoding="utf-8")
            _materialize_project(
                project_root,
                answer_overrides={
                    "annexes": {"authority": "AUTHORITY.md"}
                },
            )
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            records = receipt["authority_module_digests"]
            self.assertEqual(
                [
                    {
                        "label": "Annex C — Scope of Authority (AUTHORITY.md)",
                        "path": "AUTHORITY.md",
                        "sha256": hashlib.sha256(
                            b"# Approved authority\n"
                        ).hexdigest(),
                    }
                ],
                records,
            )
            self.assertNotIn("AUTHORITY.md", receipt["managed_files"])
            self.assertNotIn("AUTHORITY.md", receipt["immutable_files"])
            self.assertEqual(
                [],
                project_instance_lint.validate_recorded_preimage(project_root)[
                    "errors"
                ],
            )

            revised_bytes = b"# Intentionally revised authority\n"
            authority_path.write_bytes(revised_bytes)
            inspected = project_refresh.inspect_project(project_root)
            blocked = project_refresh.build_plan(project_root)
            candidate_input = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate_input["answers"]["project_name"] = "Combined revision"
            combined = project_refresh.build_plan(
                project_root,
                candidate_input=candidate_input,
                post_apply_backout={"kind": "none"},
                rebind_authority_modules=True,
            )
            expected_authority_mode = stat.S_IMODE(authority_path.stat().st_mode)
            built = project_refresh.build_plan(
                project_root,
                post_apply_backout={"kind": "none"},
                rebind_authority_modules=True,
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            target_receipt = json.loads(
                built.target_outputs[project_bootstrap.INSTANCE_MANIFEST]
            )
            preview_code, preview = project_refresh.preview_plan(
                project_root,
                built.payload,
            )
            apply_code, applied = project_refresh.apply_plan(
                project_root,
                built.payload,
                approved_digest=str(built.payload["plan_sha256"]),
                approved_actions=set(
                    cast(list[str], built.payload["required_actions"])
                ),
                approved_warnings=set(_warning_ids(built.payload)),
            )
            after = project_refresh.inspect_project(project_root)

        self.assertEqual(
            "authority-module-rebind-required",
            inspected["status"],
            inspected,
        )
        self.assertEqual([], inspected["errors"], inspected)
        self.assertTrue(inspected["rebind_eligible"], inspected)
        self.assertTrue(inspected["authority_module_drift"], inspected)
        self.assertIsNone(blocked.payload)
        self.assertIn("--rebind-authority-modules", blocked.errors[0])
        self.assertIsNone(combined.payload)
        self.assertIn("receipt-only recovery route", combined.errors[0])
        self.assertEqual(
            [
                "ACCEPT-NO-POST-APPLY-BACKOUT",
                "REBIND-AUTHORITY-MODULES",
            ],
            built.payload["required_actions"],
        )
        self.assertTrue(
            any(
                "authority-module digest rebind" in warning["message"]
                and "no post-apply semantic backout" in warning["message"]
                for warning in cast(list[dict[str, str]], built.payload["warnings"])
            ),
            built.payload["warnings"],
        )
        self.assertEqual(
            hashlib.sha256(revised_bytes).hexdigest(),
            target_receipt["authority_module_digests"][0]["sha256"],
        )
        self.assertEqual(0, preview_code, preview)
        self.assertEqual([], preview["current_authority_modules"])
        self.assertEqual(
            [
                {
                    "label": "Annex C — Scope of Authority (AUTHORITY.md)",
                    "path": "AUTHORITY.md",
                    "sha256": hashlib.sha256(revised_bytes).hexdigest(),
                    "mode": expected_authority_mode,
                    "text": revised_bytes.decode("utf-8"),
                }
            ],
            preview["authority_modules"],
        )
        self.assertEqual(0, apply_code, applied)
        self.assertEqual("applied", applied["status"])
        self.assertNotIn("AUTHORITY.md", cast(list[str], applied["written"]))
        self.assertEqual("current", after["status"], after)

    def test_authority_module_rebind_rejects_unrelated_receipt_serialization_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            authority_path = project_root / "AUTHORITY.md"
            authority_path.write_text("# Approved authority\n", encoding="utf-8")
            _materialize_project(
                project_root,
                answer_overrides={"annexes": {"authority": "AUTHORITY.md"}},
            )
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_path.write_text(
                json.dumps(receipt, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            authority_path.write_text("# Revised authority\n", encoding="utf-8")

            inspected = project_refresh.inspect_project(project_root)
            built = project_refresh.build_plan(
                project_root,
                post_apply_backout={"kind": "none"},
                rebind_authority_modules=True,
            )

        self.assertEqual("manual-update-required", inspected["status"], inspected)
        self.assertFalse(inspected.get("rebind_eligible", False), inspected)
        self.assertIn(
            "canonical serialization",
            " ".join(cast(list[str], inspected["errors"])),
        )
        self.assertIsNone(built.payload)
        self.assertIn("canonical serialization", " ".join(built.errors))

    def test_authority_module_receipt_rejects_coverage_duplicates_redirects_and_drift(
        self,
    ) -> None:
        cases = (
            "missing-record",
            "missing-file",
            "extra-record",
            "duplicate-record",
            "redirect",
            "oversize",
            "invalid-utf8",
            "digest-drift",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir)
                authority_path = project_root / "AUTHORITY.md"
                authority_path.write_text("# Authority\n", encoding="utf-8")
                _materialize_project(
                    project_root,
                    answer_overrides={
                        "annexes": {"authority": "AUTHORITY.md"}
                    },
                )
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if case == "missing-record":
                    receipt["authority_module_digests"] = []
                elif case == "missing-file":
                    authority_path.unlink()
                elif case == "extra-record":
                    extra_path = project_root / "EXTRA.md"
                    extra_path.write_text("extra\n", encoding="utf-8")
                    receipt["authority_module_digests"].append(
                        {
                            "label": "Non-canonical extra module",
                            "path": "EXTRA.md",
                            "sha256": hashlib.sha256(b"extra\n").hexdigest(),
                        }
                    )
                elif case == "duplicate-record":
                    receipt["authority_module_digests"].append(
                        dict(receipt["authority_module_digests"][0])
                    )
                elif case == "redirect":
                    outside = project_root / "redirect-target.md"
                    outside.write_text("redirected\n", encoding="utf-8")
                    authority_path.unlink()
                    authority_path.symlink_to(outside)
                elif case == "oversize":
                    authority_path.write_bytes(
                        b"x" * (project_bootstrap.AUTHORITY_MODULE_MAX_BYTES + 1)
                    )
                elif case == "invalid-utf8":
                    authority_path.write_bytes(b"authority:\xff\n")
                else:
                    authority_path.write_text("# Drifted authority\n", encoding="utf-8")
                if case in {"missing-record", "extra-record", "duplicate-record"}:
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                preimage = project_instance_lint.validate_recorded_preimage(
                    project_root
                )
                errors = cast(list[str], preimage["errors"])

                self.assertTrue(errors, preimage)
                expected_fragment = {
                    "missing-record": "missing derived module",
                    "missing-file": "authority module is missing",
                    "extra-record": "extra or non-canonical module",
                    "duplicate-record": "duplicated",
                    "redirect": "redirect",
                    "oversize": "bounded read",
                    "invalid-utf8": "non-UTF-8",
                    "digest-drift": "digest drift",
                }[case]
                self.assertTrue(
                    any(expected_fragment in error for error in errors),
                    errors,
                )

    def test_authority_modules_require_exact_directory_entry_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "AUTHORITY.md").write_text(
                "# Authority\n",
                encoding="utf-8",
            )
            answers = {
                "annexes": {"authority": "AUTHORITY.md"},
            }
            exact_spelling_error = [
                "authority module must use exact path spelling 'AUTHORITY.md'"
            ]

            with mock.patch.object(
                safe_paths,
                "exact_relative_path_spelling_errors",
                return_value=exact_spelling_error,
            ):
                records, bootstrap_errors = (
                    project_bootstrap.authority_module_digest_records(
                        answers,
                        project_root,
                    )
                )

            self.assertEqual([], records)
            self.assertEqual(exact_spelling_error, bootstrap_errors)

            _materialize_project(
                project_root,
                answer_overrides=answers,
            )
            with mock.patch.object(
                safe_paths,
                "exact_relative_path_spelling_errors",
                return_value=exact_spelling_error,
            ):
                preimage = project_instance_lint.validate_recorded_preimage(
                    project_root
                )

            self.assertTrue(
                any(
                    "must use exact path spelling" in error
                    for error in cast(list[str], preimage["errors"])
                ),
                preimage,
            )

    def test_authority_module_paths_have_one_canonical_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            shared_path = project_root / "SHARED.md"
            shared_path.write_text("# Shared module\n", encoding="utf-8")
            _materialize_project(project_root)
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            answers = cast(dict[str, object], candidate["answers"])
            answers["annexes"] = {
                "soul": "SHARED.md",
                "authority": "SHARED.md",
            }

            validation_errors = project_bootstrap.validate_answers(answers)
            records, capture_errors = (
                project_bootstrap.authority_module_digest_records(
                    answers,
                    project_root,
                )
            )
            built = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            schema = project_contract_model.answer_json_schema()
            annex_schema = cast(
                dict[str, object],
                cast(dict[str, object], schema["properties"])["annexes"],
            )

        expected = "authority module path must have one canonical owner: SHARED.md"
        self.assertTrue(
            any(expected in error for error in validation_errors),
            validation_errors,
        )
        self.assertEqual(["SHARED.md"], [record["path"] for record in records])
        self.assertTrue(
            any(expected in error for error in capture_errors),
            capture_errors,
        )
        self.assertIsNone(built.payload)
        self.assertTrue(any(expected in error for error in built.errors), built.errors)
        self.assertIn(
            "one path cannot have multiple owner labels",
            str(annex_schema["description"]),
        )

    def test_authority_module_rebind_rechecks_exact_bytes_at_transaction_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            authority_path = project_root / "AUTHORITY.md"
            authority_path.write_text("# Original authority\n", encoding="utf-8")
            _materialize_project(
                project_root,
                answer_overrides={"annexes": {"authority": "AUTHORITY.md"}},
            )
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt_before = receipt_path.read_bytes()
            authority_path.write_text("# Reviewed revision\n", encoding="utf-8")
            built = project_refresh.build_plan(
                project_root,
                post_apply_backout={"kind": "none"},
                rebind_authority_modules=True,
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            real_transaction = (
                project_refresh.bootstrap_transaction.transactional_write_outputs
            )
            injected = False

            def mutate_at_transaction_boundary(
                target_root: Path,
                outputs: list[tuple[str, str]],
                **kwargs: Any,
            ) -> bootstrap_transaction.BootstrapWriteResult:
                nonlocal injected
                authority_path.write_text("# Unreviewed race\n", encoding="utf-8")
                injected = True
                return real_transaction(target_root, outputs, **kwargs)

            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transactional_write_outputs",
                side_effect=mutate_at_transaction_boundary,
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

            self.assertTrue(injected)
            self.assertEqual(project_refresh.EXIT_ROLLED_BACK, apply_code, applied)
            self.assertEqual("rolled-back", applied["status"])
            self.assertIn(
                "bootstrap asserted preimage changed after plan inspection",
                " ".join(cast(list[str], applied["errors"])),
            )
            self.assertEqual(receipt_before, receipt_path.read_bytes())
            self.assertEqual("# Unreviewed race\n", authority_path.read_text(encoding="utf-8"))
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )

    def test_authority_path_transition_asserts_displaced_module_at_apply_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            old_path = project_root / "OLD.md"
            new_path = project_root / "NEW.md"
            old_path.write_text("# Reviewed old authority\n", encoding="utf-8")
            new_path.write_text("# Reviewed new authority\n", encoding="utf-8")
            _materialize_project(
                project_root,
                answer_overrides={"annexes": {"authority": "OLD.md"}},
            )
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt_before = receipt_path.read_bytes()
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["annexes"]["authority"] = "NEW.md"
            built = project_refresh.build_plan(
                project_root,
                candidate_input=candidate,
                post_apply_backout={"kind": "none"},
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            plan = built.payload
            self.assertEqual(
                ["OLD.md"],
                [
                    record["path"]
                    for record in cast(
                        list[dict[str, object]],
                        plan["current_authority_modules"],
                    )
                ],
            )
            self.assertEqual(
                ["NEW.md"],
                [
                    record["path"]
                    for record in cast(
                        list[dict[str, object]],
                        plan["authority_modules"],
                    )
                ],
            )
            real_transaction = (
                project_refresh.bootstrap_transaction.transactional_write_outputs
            )
            injected = False

            def mutate_displaced_module(
                target_root: Path,
                outputs: list[tuple[str, str]],
                **kwargs: Any,
            ) -> bootstrap_transaction.BootstrapWriteResult:
                nonlocal injected
                old_path.write_text("# Unreviewed old mutation\n", encoding="utf-8")
                injected = True
                return real_transaction(target_root, outputs, **kwargs)

            with mock.patch.object(
                project_refresh.bootstrap_transaction,
                "transactional_write_outputs",
                side_effect=mutate_displaced_module,
            ):
                apply_code, applied = project_refresh.apply_plan(
                    project_root,
                    plan,
                    approved_digest=str(plan["plan_sha256"]),
                    approved_actions=set(cast(list[str], plan["required_actions"])),
                    approved_warnings=set(_warning_ids(plan)),
                )

            self.assertTrue(injected)
            self.assertEqual(project_refresh.EXIT_ROLLED_BACK, apply_code, applied)
            self.assertEqual("rolled-back", applied["status"])
            self.assertIn(
                "bootstrap asserted preimage changed after plan inspection",
                " ".join(cast(list[str], applied["errors"])),
            )
            self.assertEqual(receipt_before, receipt_path.read_bytes())
            self.assertEqual(
                "# Unreviewed old mutation\n",
                old_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )

    def test_authority_path_transition_restore_asserts_both_module_snapshots(
        self,
    ) -> None:
        for mutated_name in ("OLD.md", "NEW.md"):
            with (
                self.subTest(mutated_name=mutated_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                old_path = project_root / "OLD.md"
                new_path = project_root / "NEW.md"
                old_path.write_text("# Reviewed old authority\n", encoding="utf-8")
                new_path.write_text("# Reviewed new authority\n", encoding="utf-8")
                _materialize_project(
                    project_root,
                    answer_overrides={"annexes": {"authority": "OLD.md"}},
                )
                candidate = json.loads(
                    (project_root / project_input.INPUT_NAME).read_text(
                        encoding="utf-8"
                    )
                )
                candidate["answers"]["annexes"]["authority"] = "NEW.md"
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
                plan = built.payload
                create_code, created = project_refresh.create_backout_bundle(
                    project_root,
                    plan,
                    backout_root,
                )
                self.assertEqual(0, create_code, created)
                apply_code, applied = project_refresh.apply_plan(
                    project_root,
                    plan,
                    approved_digest=str(plan["plan_sha256"]),
                    approved_actions=set(cast(list[str], plan["required_actions"])),
                    approved_warnings=set(_warning_ids(plan)),
                )
                self.assertEqual(0, apply_code, applied)
                receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
                post_apply_receipt = receipt_path.read_bytes()
                mutated_path = project_root / mutated_name
                mutation = f"# Unreviewed restore mutation: {mutated_name}\n"
                real_transaction = (
                    project_refresh.bootstrap_transaction.transactional_write_outputs
                )
                injected = False

                def mutate_at_restore_boundary(
                    target_root: Path,
                    outputs: list[tuple[str, str]],
                    **kwargs: Any,
                ) -> bootstrap_transaction.BootstrapWriteResult:
                    nonlocal injected
                    mutated_path.write_text(mutation, encoding="utf-8")
                    injected = True
                    return real_transaction(target_root, outputs, **kwargs)

                with mock.patch.object(
                    project_refresh.bootstrap_transaction,
                    "transactional_write_outputs",
                    side_effect=mutate_at_restore_boundary,
                ):
                    restore_code, restored = (
                        project_refresh.restore_backout_bundle(
                            project_root,
                            plan,
                            backout_root,
                            approved_digest=str(plan["plan_sha256"]),
                            approved_transaction_id=str(
                                plan["refresh_transaction_id"]
                            ),
                        )
                    )

                self.assertTrue(injected)
                self.assertEqual(
                    project_refresh.EXIT_ROLLED_BACK,
                    restore_code,
                    restored,
                )
                self.assertEqual("rolled-back", restored["status"])
                self.assertIn(
                    "bootstrap asserted preimage changed after plan inspection",
                    " ".join(cast(list[str], restored["errors"])),
                )
                self.assertEqual(post_apply_receipt, receipt_path.read_bytes())
                self.assertEqual(mutation, mutated_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    "clean",
                    bootstrap_transaction.transaction_recovery_status(
                        project_root
                    ).state,
                )

    def test_refresh_plan_rejects_cloned_root_and_contract_directory_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.subTest("project root"):
                project_root = root / "root-bound-project"
                project_root.mkdir()
                _materialize_project(project_root)
                built = project_refresh.build_plan(project_root)
                self.assertIsNotNone(built.payload, built.errors)
                assert built.payload is not None
                reviewed_identity = cast(
                    dict[str, object],
                    built.payload["target_directory_binding"],
                )["project_root_identity"]
                displaced = root / "reviewed-project-root"
                project_root.rename(displaced)
                shutil.copytree(displaced, project_root)
                code, report = project_refresh.apply_plan(
                    project_root,
                    built.payload,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_actions=set(),
                    approved_warnings=set(_warning_ids(built.payload)),
                )
                self.assertEqual(project_refresh.EXIT_BLOCKED, code, report)
                self.assertEqual("stale-plan", report["status"])
                self.assertNotEqual(
                    reviewed_identity,
                    project_bootstrap.target_directory_identity(project_root),
                )

            with self.subTest("nested contract parent"):
                project_root = root / "contract-bound-project"
                project_root.mkdir()
                _materialize_project(
                    project_root,
                    contract_root_ref="governance/current",
                )
                built = project_refresh.build_plan(
                    project_root,
                    "governance/current",
                )
                self.assertIsNotNone(built.payload, built.errors)
                assert built.payload is not None
                reviewed_directories = cast(
                    dict[str, object],
                    built.payload["target_directory_binding"],
                )["directory_identities"]
                displaced = root / "reviewed-governance-tree"
                (project_root / "governance").rename(displaced)
                shutil.copytree(displaced, project_root / "governance")
                code, report = project_refresh.apply_plan(
                    project_root,
                    built.payload,
                    approved_digest=str(built.payload["plan_sha256"]),
                    approved_actions=set(),
                    approved_warnings=set(_warning_ids(built.payload)),
                )
                self.assertEqual(project_refresh.EXIT_BLOCKED, code, report)
                self.assertEqual("stale-plan", report["status"])
                self.assertNotEqual(
                    reviewed_directories,
                    project_bootstrap.target_directory_identity_bindings(
                        project_root,
                        project_root / "governance" / "current",
                    ),
                )

    def test_backout_restore_rechecks_authority_after_post_install_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            authority_path = project_root / "AUTHORITY.md"
            authority_path.write_text("# Stable authority\n", encoding="utf-8")
            _materialize_project(
                project_root,
                answer_overrides={"annexes": {"authority": "AUTHORITY.md"}},
            )
            candidate = json.loads(
                (project_root / project_input.INPUT_NAME).read_text(encoding="utf-8")
            )
            candidate["answers"]["project_name"] = "Applied candidate"
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
            plan = built.payload
            create_code, created = project_refresh.create_backout_bundle(
                project_root,
                plan,
                backout_root,
            )
            self.assertEqual(0, create_code, created)
            apply_code, applied = project_refresh.apply_plan(
                project_root,
                plan,
                approved_digest=str(plan["plan_sha256"]),
                approved_actions=set(cast(list[str], plan["required_actions"])),
                approved_warnings=set(_warning_ids(plan)),
            )
            self.assertEqual(0, apply_code, applied)
            post_apply_receipt = (
                project_root / project_bootstrap.INSTANCE_MANIFEST
            ).read_bytes()
            real_validate = project_instance_lint.validate_recorded_preimage
            mutated = False

            def validate_then_mutate(
                target_root: Path,
                contract_root_ref: str = ".",
                **kwargs: Any,
            ) -> dict[str, object]:
                nonlocal mutated
                result = real_validate(target_root, contract_root_ref, **kwargs)
                if not mutated and not result["errors"]:
                    authority_path.write_text(
                        "# Raced after validation\n",
                        encoding="utf-8",
                    )
                    mutated = True
                return result

            with mock.patch.object(
                project_refresh.project_instance_lint,
                "validate_recorded_preimage",
                side_effect=validate_then_mutate,
            ):
                restore_code, restored = project_refresh.restore_backout_bundle(
                    project_root,
                    plan,
                    backout_root,
                    approved_digest=str(plan["plan_sha256"]),
                    approved_transaction_id=str(plan["refresh_transaction_id"]),
                )

            self.assertTrue(mutated)
            self.assertEqual(project_refresh.EXIT_ROLLED_BACK, restore_code, restored)
            self.assertEqual("rolled-back", restored["status"])
            self.assertIn(
                "authority module changed during restore",
                " ".join(cast(list[str], restored["errors"])),
            )
            self.assertEqual(
                post_apply_receipt,
                (project_root / project_bootstrap.INSTANCE_MANIFEST).read_bytes(),
            )
            self.assertEqual(
                "# Raced after validation\n",
                authority_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )

    def test_backout_restore_uses_reviewed_contract_directory_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            contract_root_ref = "governance/current"
            _materialize_project(
                project_root,
                contract_root_ref=contract_root_ref,
            )
            input_path = project_root / project_bootstrap.project_relative_output(
                contract_root_ref,
                project_input.INPUT_NAME,
            )
            candidate = json.loads(input_path.read_text(encoding="utf-8"))
            candidate["answers"]["project_name"] = "Applied candidate"
            backout_root = root / "private-backouts"
            backout_root.mkdir(mode=0o700)
            built = project_refresh.build_plan(
                project_root,
                contract_root_ref,
                candidate_input=candidate,
                post_apply_backout={
                    "kind": "exact-preimage-bundle",
                    "root": str(backout_root.resolve()),
                },
            )
            self.assertIsNotNone(built.payload, built.errors)
            assert built.payload is not None
            plan = built.payload
            create_code, created = project_refresh.create_backout_bundle(
                project_root,
                plan,
                backout_root,
            )
            self.assertEqual(0, create_code, created)
            apply_code, applied = project_refresh.apply_plan(
                project_root,
                plan,
                approved_digest=str(plan["plan_sha256"]),
                approved_actions=set(cast(list[str], plan["required_actions"])),
                approved_warnings=set(_warning_ids(plan)),
            )
            self.assertEqual(0, apply_code, applied)
            post_apply_receipt = (
                project_root / project_bootstrap.INSTANCE_MANIFEST
            ).read_bytes()

            displaced = root / "reviewed-governance-tree-after-apply"
            (project_root / "governance").rename(displaced)
            shutil.copytree(displaced, project_root / "governance")
            restore_code, restored = project_refresh.restore_backout_bundle(
                project_root,
                plan,
                backout_root,
                approved_digest=str(plan["plan_sha256"]),
                approved_transaction_id=str(plan["refresh_transaction_id"]),
            )

            self.assertEqual(project_refresh.EXIT_ROLLED_BACK, restore_code, restored)
            self.assertEqual("rolled-back", restored["status"])
            self.assertIn(
                "approved project-relative directory identity changed",
                " ".join(cast(list[str], restored["errors"])),
            )
            self.assertEqual(
                post_apply_receipt,
                (project_root / project_bootstrap.INSTANCE_MANIFEST).read_bytes(),
            )
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )

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



if __name__ == "__main__":
    unittest.main()
