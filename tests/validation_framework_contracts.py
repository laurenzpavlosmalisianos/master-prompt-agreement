"""Framework consistency, contracts, conformance, and compliance tests."""

from __future__ import annotations

import ast
from collections.abc import Callable
import io
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
    run_bounded,
)

import conformance_check  # noqa: E402
import framework_compliance  # noqa: E402
import framework_consistency  # noqa: E402
import framework_contracts  # noqa: E402
import integration_registry  # noqa: E402
import safe_paths  # noqa: E402
import validate_framework  # noqa: E402


FRAMEWORK_UNAVAILABLE_CLAUSE = integration_registry.FRAMEWORK_UNAVAILABLE_CLAUSE
FRAMEWORK_LOAD_TOKEN = "{{FRAMEWORK_ROOT}}/runtime/operative_charter.md"
GENERIC_ENTRYPOINT_PATH = "integrations/templates/generic/AGENTS.md.template"


def _clean_authoring_workspace_hygiene_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "checked_entry_count": 2,
        "stability_scan_count": 2,
        "deletion_candidates": [],
        "review_required": [],
        "diagnostics_truncated": False,
        "omitted_diagnostic_count": 0,
        "errors": [],
        "warnings": [],
    }


def _call_keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next(
        (keyword.value for keyword in call.keywords if keyword.arg == name),
        None,
    )


def _is_argparse_suppress(value: ast.expr) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "SUPPRESS"
        and isinstance(value.value, ast.Name)
        and value.value.id == "argparse"
    )


def _declares_nonblank_cli_text(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if _is_argparse_suppress(value):
        return True
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str) and bool(value.value.strip())
    if isinstance(value, ast.JoinedStr):
        return any(
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and bool(item.value.strip())
            for item in value.values
        )
    # These names are fed by the nonblank routing registries or the local
    # literal subcommand-help table. New dynamic sources require explicit
    # review here instead of silently bypassing the contract.
    return isinstance(value, ast.Name) and value.id in {
        "command_description",
        "command_help",
        "help_text",
    }


def _is_argument_parser_constructor(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "ArgumentParser"
    return (
        isinstance(call.func, ast.Name)
        and call.func.id.endswith("ArgumentParser")
    )


def entrypoint_consistency_rules(
    *,
    forbidden_fragments: list[str] | None = None,
) -> dict[str, object]:
    return {
        "entrypoints": {
            "forbid_eager_practice_guide_imports": True,
            "forbidden_state_loading_fragments": forbidden_fragments or [],
        }
    }


def generic_entrypoint_registry() -> dict[str, object]:
    return {
        "families": {
            "generic": {
                "entrypoint": {
                    "path": GENERIC_ENTRYPOINT_PATH,
                    "output": "AGENTS.md",
                }
            }
        }
    }


class FrameworkConsistencyContractComplianceTests(unittest.TestCase):
    def test_public_command_parsers_have_discoverable_cli_help(self) -> None:
        parser_files: set[str] = set()
        failures: list[str] = []

        for path in sorted(SCRIPTS_DIR.glob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=relative,
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                if _is_argument_parser_constructor(node):
                    parser_files.add(relative)
                    description = _call_keyword(node, "description")
                    if not (
                        isinstance(description, ast.Constant)
                        and isinstance(description.value, str)
                        and len(description.value.split()) >= 2
                    ):
                        failures.append(
                            f"{relative}:{node.lineno}: root parser requires a "
                            "static description of at least two words"
                        )

                if not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr == "add_argument":
                    help_value = _call_keyword(node, "help")
                    if not _declares_nonblank_cli_text(help_value):
                        failures.append(
                            f"{relative}:{node.lineno}: add_argument requires "
                            "nonblank help or argparse.SUPPRESS"
                        )
                elif node.func.attr == "add_parser":
                    for keyword in ("help", "description"):
                        value = _call_keyword(node, keyword)
                        if not _declares_nonblank_cli_text(value):
                            failures.append(
                                f"{relative}:{node.lineno}: subcommand requires "
                                f"nonblank {keyword}"
                            )

        self.assertTrue(parser_files, "expected public command parsers")
        self.assertEqual([], failures, "\n".join(failures))

    def test_setup_contract_retains_runner_schema_and_collision_invariants(self) -> None:
        expected = {
            "README.md": {
                "runner_usable: true",
                "no collision at any selected managed output path",
                "full schema is compiler input",
            },
            "GETTING_STARTED.md": {
                "<framework-checkout-on-diagnostic-host>",
                "exact tested interpreter",
                "full schema is compiler input",
                "every selected managed output path is free",
            },
            "docs/downstream_setup.md": {
                "<framework-checkout-on-diagnostic-host>",
                "<framework-checkout-as-visible-to-runner>",
                "only its exact executing interpreter is qualified",
                "targeted schema lookup",
                "no selected managed output path collides",
            },
            "CONFORMANCE.md": {
                "exact retained runner",
                "<framework-checkout-as-visible-to-runner>",
                "no selected managed output path collides",
            },
            "task_orders/init.md": {
                "<framework-checkout-on-diagnostic-host>",
                "exact interpreter that executed it",
                "Do not load the full schema",
                "Inventory the exact planned output paths before dry run.",
            },
            "scripts/README.md": {
                "exact tested stdlib-only Python interpreter",
                "Treat the full schema as compiler input",
                "no selected managed output collides",
            },
        }
        contract = json.loads(
            (REPO_ROOT / "runtime" / "consistency_contract.json").read_text(
                encoding="utf-8"
            )
        )
        setup_docs = contract.get("setup_docs")
        self.assertIsInstance(setup_docs, dict)
        setup_docs = setup_docs if isinstance(setup_docs, dict) else {}
        for rel, markers in expected.items():
            with self.subTest(document=rel):
                registered = setup_docs.get(rel)
                self.assertIsInstance(registered, list)
                self.assertTrue(markers <= set(registered or ()))

        errors: list[str] = []
        framework_consistency.validate_setup_docs(contract, errors)
        self.assertEqual([], errors)

    def test_bootstrap_acceptance_docs_have_one_transaction_owner(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "runtime" / "consistency_contract.json").read_text(
                encoding="utf-8"
            )
        )
        acceptance = contract.get("bootstrap_acceptance_docs")
        self.assertIsInstance(acceptance, dict)
        acceptance = acceptance if isinstance(acceptance, dict) else {}
        self.assertEqual(
            {
                "schema_version",
                "documents",
                "required_anchors",
                "forbidden_fragments",
                "codex_wrapper_orientation",
                "refresh_wrapper_orientation",
            },
            set(acceptance),
        )
        self.assertIs(type(acceptance.get("schema_version")), int)
        self.assertEqual(1, acceptance.get("schema_version"))

        documents = acceptance.get("documents")
        self.assertEqual(
            [
                "GETTING_STARTED.md",
                "docs/downstream_setup.md",
                "task_orders/init.md",
                "CONFORMANCE.md",
            ],
            documents,
        )
        anchors = acceptance.get("required_anchors")
        forbidden = acceptance.get("forbidden_fragments")
        self.assertIsInstance(anchors, list)
        self.assertIsInstance(forbidden, list)
        anchor_strings = (
            [item for item in anchors if isinstance(item, str)]
            if isinstance(anchors, list)
            else []
        )
        forbidden_strings = (
            [item for item in forbidden if isinstance(item, str)]
            if isinstance(forbidden, list)
            else []
        )
        self.assertTrue(anchor_strings)
        self.assertTrue(forbidden_strings)
        self.assertEqual(anchors, anchor_strings)
        self.assertEqual(forbidden, forbidden_strings)
        self.assertTrue(all(anchor_strings))
        self.assertTrue(all(forbidden_strings))
        document_paths = (
            [item for item in documents if isinstance(item, str)]
            if isinstance(documents, list)
            else []
        )
        self.assertEqual(documents, document_paths)

        for rel in document_paths:
            with self.subTest(document=rel):
                prose = framework_consistency.operative_prose(
                    (REPO_ROOT / rel).read_text(encoding="utf-8")
                )
                anchor_errors: list[str] = []
                for anchor in anchor_strings:
                    framework_consistency.validate_operative_anchor(
                        anchor,
                        prose,
                        rel,
                        anchor_errors,
                        "bootstrap_acceptance_anchor",
                    )
                self.assertEqual([], anchor_errors)
                for fragment in forbidden_strings:
                    self.assertNotIn(" ".join(fragment.split()), prose)

        orientation = acceptance.get("codex_wrapper_orientation")
        self.assertIsInstance(orientation, dict)
        orientation = orientation if isinstance(orientation, dict) else {}
        self.assertEqual(
            {"path", "required_fragments", "forbidden_fragments"},
            set(orientation),
        )
        orientation_path = orientation.get("path")
        self.assertEqual("integrations/README.md", orientation_path)
        integration_text = framework_consistency.operative_prose(
            (REPO_ROOT / str(orientation_path)).read_text(encoding="utf-8")
        )
        for fragment in orientation.get("required_fragments", []):
            self.assertIsInstance(fragment, str)
            self.assertIn(" ".join(fragment.split()), integration_text)
        for fragment in orientation.get("forbidden_fragments", []):
            self.assertIsInstance(fragment, str)
            self.assertNotIn(" ".join(fragment.split()), integration_text)

        refresh_orientation = acceptance.get("refresh_wrapper_orientation")
        self.assertIsInstance(refresh_orientation, dict)
        refresh_orientation = (
            refresh_orientation if isinstance(refresh_orientation, dict) else {}
        )
        self.assertEqual(
            {"path", "required_fragments", "forbidden_fragments"},
            set(refresh_orientation),
        )
        refresh_path = refresh_orientation.get("path")
        self.assertEqual("docs/downstream_setup.md", refresh_path)
        refresh_text = framework_consistency.operative_prose(
            (REPO_ROOT / str(refresh_path)).read_text(encoding="utf-8")
        )
        for fragment in refresh_orientation.get("required_fragments", []):
            self.assertIsInstance(fragment, str)
            self.assertIn(" ".join(fragment.split()), refresh_text)
        for fragment in refresh_orientation.get("forbidden_fragments", []):
            self.assertIsInstance(fragment, str)
            self.assertNotIn(" ".join(fragment.split()), refresh_text)

    def test_validate_framework_loader_rejects_hostile_core_json_inputs(self) -> None:
        documents = (
            "runtime/operative_schedule.json",
            "runtime/msa_clause_map.json",
        )
        cases = (
            ("missing", "missing file"),
            ("malformed-json", "invalid JSON"),
            ("invalid-utf8", "valid UTF-8"),
            ("oversized", "input limit"),
            ("fifo", "regular file"),
            ("symlink", "symlink"),
            ("hardlink", "hard link"),
        )
        for rel in documents:
            for case, expected_fragment in cases:
                with (
                    self.subTest(document=rel, case=case),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    root = Path(temp_dir)
                    path = root / rel
                    path.parent.mkdir(parents=True)
                    if case == "malformed-json":
                        path.write_text("{", encoding="utf-8")
                    elif case == "invalid-utf8":
                        path.write_bytes(b"\xff")
                    elif case == "oversized":
                        path.write_bytes(
                            b" " * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                        )
                    elif case == "fifo":
                        os.mkfifo(path)
                    elif case == "symlink":
                        target = root / "target.json"
                        target.write_text("{}", encoding="utf-8")
                        path.symlink_to(target)
                    elif case == "hardlink":
                        source = root / "source.json"
                        source.write_text("{}", encoding="utf-8")
                        os.link(source, path)

                    errors: list[str] = []
                    document = validate_framework.load_json_object_if_file(
                        path,
                        errors,
                        rel,
                    )

                    self.assertIsNone(document)
                    self.assertEqual(1, len(errors))
                    self.assertIn(expected_fragment, errors[0])
                    self.assertLess(len(errors[0]), 700)

    def test_validate_framework_gates_invalid_core_json_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "operative_schedule.json").write_text("{", encoding="utf-8")
            (runtime / "msa_clause_map.json").write_text("{", encoding="utf-8")

            with (
                mock.patch.object(validate_framework, "REPO_ROOT", REPO_ROOT),
                mock.patch.object(validate_framework, "gitignore_contract_errors", return_value=[]),
                mock.patch.object(validate_framework, "required_surface_errors", return_value=([], [])),
                mock.patch.object(validate_framework, "task_order_catalog_errors", return_value=[]),
                mock.patch.object(validate_framework, "stale_terminology_errors", return_value=[]),
                mock.patch.object(validate_framework, "public_content_boundary_errors", return_value=[]),
                mock.patch.object(validate_framework, "schedule_contract_errors") as schedule_check,
                mock.patch.object(
                    validate_framework.integration_registry,
                    "entrypoint_paths",
                    return_value=[],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = validate_framework.main(["--root", str(root)])

        self.assertEqual(1, result)
        schedule_check.assert_not_called()
        output = stdout.getvalue()
        self.assertEqual(1, output.count("invalid JSON in runtime/operative_schedule.json"))
        self.assertEqual(1, output.count("invalid JSON in runtime/msa_clause_map.json"))
        self.assertNotIn("Traceback", output)

    def test_validate_framework_bounds_phase_failure_and_runs_later_checks(self) -> None:
        later_defect = "later clause and entrypoint defect"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clause_check = mock.Mock(return_value=[later_defect])
            with (
                mock.patch.object(
                    validate_framework,
                    "gitignore_contract_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "required_surface_errors",
                    side_effect=FileNotFoundError("integrations/registry.json"),
                ),
                mock.patch.object(
                    validate_framework,
                    "task_order_catalog_errors",
                    side_effect=RuntimeError("catalog\nfailed"),
                ),
                mock.patch.object(
                    validate_framework,
                    "stale_terminology_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "public_content_boundary_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "clause_and_entrypoint_errors",
                    clause_check,
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = validate_framework.main(["--root", str(root)])

        self.assertEqual(1, result)
        clause_check.assert_called_once_with(root)
        output = stdout.getvalue()
        self.assertIn(
            "required-surface validation could not complete: "
            "FileNotFoundError: integrations/registry.json",
            output,
        )
        self.assertIn(
            "Task Order catalog validation could not complete: "
            "RuntimeError: catalog failed",
            output,
        )
        self.assertIn(later_defect, output)
        self.assertNotIn("Traceback", output)

    def test_required_surface_continues_after_missing_integration_registry(self) -> None:
        later_defect = "later standards-surface defect"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(
                    validate_framework,
                    "public_symlink_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework.integration_registry,
                    "required_template_files",
                    side_effect=FileNotFoundError(
                        "integrations/registry.json"
                    ),
                ),
                mock.patch.object(
                    validate_framework.prompt_load_report,
                    "loaded_surface_budget_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "standards_surface_errors",
                    return_value=[later_defect],
                ),
                mock.patch.object(
                    validate_framework,
                    "interactive_docs_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "script_index_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework,
                    "project_state_template_inventory_errors",
                    return_value=[],
                ),
                mock.patch.object(
                    validate_framework.project_contract_model,
                    "generated_asset_errors",
                    return_value=[],
                ),
            ):
                _required_files, errors = (
                    validate_framework.required_surface_errors(root)
                )

        self.assertTrue(
            any(
                "integration registry required-template inventory could not complete: "
                "FileNotFoundError" in error
                for error in errors
            ),
            errors,
        )
        self.assertIn(later_defect, errors)

    def test_schedule_shape_failures_do_not_abort_independent_phases(self) -> None:
        schedule = {
            "purpose": "routing-table-not-doctrine",
            "standards_of_care": 7,
            "evidentiary_scopes": "invalid",
            "practice_guides": {},
            "minimum_evidence_by_risk": [],
        }
        with mock.patch.object(
            validate_framework,
            "native_wrapper_registration_errors",
            side_effect=FileNotFoundError("integrations/registry.json"),
        ):
            errors = validate_framework.schedule_contract_errors(
                REPO_ROOT,
                schedule,
                [],
            )

        self.assertIn(
            "operative schedule standards_of_care must be a list",
            errors,
        )
        self.assertIn(
            "operative schedule evidentiary_scopes must be a list",
            errors,
        )
        self.assertIn(
            "operative schedule practice_guides must be a list",
            errors,
        )
        self.assertIn(
            "operative schedule minimum_evidence_by_risk must be an object",
            errors,
        )
        self.assertTrue(
            any(
                "native wrapper registration validation could not complete: "
                "FileNotFoundError" in error
                for error in errors
            ),
            errors,
        )

    def test_framework_consistency_loader_serializes_untrusted_inputs(self) -> None:
        cases = (
            ("missing", "is missing"),
            ("malformed-json", "invalid JSON"),
            ("invalid-utf8", "valid UTF-8"),
            ("oversized", "input limit"),
            ("fifo", "regular file"),
            ("symlink", "symlink"),
            ("hardlink", "hard link"),
        )
        for case, expected_fragment in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                path = root / "runtime" / "consistency_contract.json"
                path.parent.mkdir(parents=True)
                if case == "malformed-json":
                    path.write_text("{", encoding="utf-8")
                elif case == "invalid-utf8":
                    path.write_bytes(b"\xff")
                elif case == "oversized":
                    path.write_bytes(
                        b" " * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                    )
                elif case == "fifo":
                    os.mkfifo(path)
                elif case == "symlink":
                    target = root / "target.json"
                    target.write_text("{}", encoding="utf-8")
                    path.symlink_to(target)
                elif case == "hardlink":
                    source = root / "source.json"
                    source.write_text("{}", encoding="utf-8")
                    os.link(source, path)

                errors: list[str] = []
                with mock.patch.object(framework_consistency, "REPO_ROOT", root):
                    document = framework_consistency.load_json(
                        "runtime/consistency_contract.json",
                        errors,
                        "consistency contract",
                    )

                self.assertIsNone(document)
                self.assertTrue(errors)
                self.assertIn(expected_fragment, "\n".join(errors))

    def test_framework_consistency_main_serializes_malformed_document_shapes(self) -> None:
        documents = (
            "runtime/consistency_contract.json",
            "runtime/operative_schedule.json",
            "runtime/workflow_catalog.json",
            "runtime/task_module_obligations.json",
            "runtime/finding_schema.json",
            "runtime/msa_clause_map.json",
            "conformance/profiles.json",
            "integrations/registry.json",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for rel in documents:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(framework_consistency, "REPO_ROOT", root),
                mock.patch("sys.stdout", stdout),
            ):
                result = framework_consistency.main(["--root", str(root)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertIsInstance(payload.get("errors"), list)
        self.assertTrue(payload["errors"])
        self.assertIsInstance(payload.get("warnings"), list)
        self.assertNotIn("Traceback", stdout.getvalue())

    def test_framework_unavailable_clause_is_structurally_owned_before_entrypoint_load(self) -> None:
        rules = entrypoint_consistency_rules()
        registry = generic_entrypoint_registry()
        template = (REPO_ROOT / GENERIC_ENTRYPOINT_PATH).read_text(encoding="utf-8")
        load_line = next(
            line for line in template.splitlines() if FRAMEWORK_LOAD_TOKEN in line
        )

        def validate(candidate: str) -> list[str]:
            candidate_errors: list[str] = []
            with mock.patch.object(
                framework_consistency,
                "read_repo_text",
                return_value=candidate,
            ):
                framework_consistency.validate_entrypoint_contract(
                    rules,
                    candidate_errors,
                    [],
                    registry=registry,
                )
            return candidate_errors

        good_errors = validate(template)
        late_errors = validate(
            template.replace(
                f"{FRAMEWORK_UNAVAILABLE_CLAUSE}\n{load_line}",
                f"{load_line}\n{FRAMEWORK_UNAVAILABLE_CLAUSE}",
                1,
            )
        )
        missing_errors = validate(
            template.replace(FRAMEWORK_UNAVAILABLE_CLAUSE, "", 1)
        )
        duplicate_errors = validate(
            template.replace(
                FRAMEWORK_UNAVAILABLE_CLAUSE,
                f"{FRAMEWORK_UNAVAILABLE_CLAUSE}\n{FRAMEWORK_UNAVAILABLE_CLAUSE}",
                1,
            )
        )

        self.assertEqual([], good_errors)
        for candidate_errors in (late_errors, missing_errors, duplicate_errors):
            self.assertTrue(
                any("framework-unavailable clause" in error for error in candidate_errors),
                candidate_errors,
            )

    def test_entrypoint_contract_keeps_separate_negative_thinness_guards(self) -> None:
        rules = entrypoint_consistency_rules(
            forbidden_fragments=["active_count: 0", "directive_count: 0"]
        )
        registry = generic_entrypoint_registry()
        template = (REPO_ROOT / GENERIC_ENTRYPOINT_PATH).read_text(encoding="utf-8")
        with mock.patch.object(
            framework_consistency,
            "read_repo_text",
            side_effect=(template, template + "TODO is empty at active_count: 0.\n"),
        ):
            good_errors: list[str] = []
            framework_consistency.validate_entrypoint_contract(
                rules,
                good_errors,
                [],
                registry=registry,
            )
            copied_detail_errors: list[str] = []
            framework_consistency.validate_entrypoint_contract(
                rules,
                copied_detail_errors,
                [],
                registry=registry,
            )

        self.assertEqual([], good_errors)
        self.assertTrue(
            any("duplicates state-loading detail" in error for error in copied_detail_errors),
            copied_detail_errors,
        )

    def test_entrypoint_template_decoys_cannot_rescue_marker_owned_authority_load(self) -> None:
        rules = entrypoint_consistency_rules()
        registry = generic_entrypoint_registry()
        template = (REPO_ROOT / GENERIC_ENTRYPOINT_PATH).read_text(encoding="utf-8")
        load_line = next(
            line for line in template.splitlines() if FRAMEWORK_LOAD_TOKEN in line
        )
        malformed_load = load_line.replace(
            "runtime/operative_charter.md",
            "runtime/operative_charter.md.bak",
        )
        candidate = template.replace(load_line, malformed_load, 1)
        candidate += (
            "\nBody-token decoy: "
            "{{FRAMEWORK_ROOT}}/runtime/operative_charter.md\n"
        )
        moved_directive = template.replace(
            load_line,
            "Authority body token: "
            "{{FRAMEWORK_ROOT}}/runtime/operative_charter.md",
            1,
        )
        moved_directive += f"\n{load_line}\n"
        for mutation, candidate in (
            ("bak-with-body-token", candidate),
            ("directive-moved-outside-owner-block", moved_directive),
        ):
            with self.subTest(mutation=mutation), mock.patch.object(
                framework_consistency,
                "read_repo_text",
                return_value=candidate,
            ):
                errors: list[str] = []
                framework_consistency.validate_entrypoint_contract(
                    rules,
                    errors,
                    [],
                    registry=registry,
                )

            self.assertTrue(
                any(
                    "framework authority-load directive is missing, inactive, or malformed"
                    in error
                    for error in errors
                ),
                errors,
            )

    def test_entrypoint_contract_rejects_legacy_substring_authority_fields(self) -> None:
        rules = entrypoint_consistency_rules()
        entrypoint_rules = rules["entrypoints"]
        if not isinstance(entrypoint_rules, dict):
            self.fail("test fixture entrypoint rules are not an object")
        entrypoint_rules["framework_load_tokens"] = [FRAMEWORK_LOAD_TOKEN]
        errors: list[str] = []
        framework_consistency.validate_entrypoint_contract(
            rules,
            errors,
            [],
            registry={"families": {}},
        )

        self.assertTrue(
            any("unknown fields: framework_load_tokens" in error for error in errors),
            errors,
        )

    def test_operative_anchor_uses_exact_prose_not_length_as_its_invariant(self) -> None:
        valid_errors: list[str] = []
        framework_consistency.validate_operative_anchor(
            "Stop.",
            "Inspect evidence. Stop. Record the result.",
            "short anchor",
            valid_errors,
        )
        self.assertEqual(valid_errors, [])

        for invalid_anchor in ("", "   ", "<!-- Stop. -->"):
            with self.subTest(invalid_anchor=invalid_anchor):
                invalid_errors: list[str] = []
                framework_consistency.validate_operative_anchor(
                    invalid_anchor,
                    "Inspect evidence. Stop. Record the result.",
                    "invalid anchor",
                    invalid_errors,
                )
                self.assertEqual(
                    invalid_errors,
                    [
                        "invalid anchor operative_anchor must be non-empty "
                        "operative prose without HTML comments"
                    ],
                )

    def test_framework_surface_signature_tracks_public_and_local_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            scripts = root / "scripts"
            scripts.mkdir()
            readme.write_text("one\n", encoding="utf-8")
            (scripts / "keep.py").write_text("pass\n", encoding="utf-8")
            baseline = validate_framework.framework_product_surface_signature(root)

            readme.write_text("two\n", encoding="utf-8")
            rewritten = validate_framework.framework_product_surface_signature(root)
            (scripts / "added.py").write_text("pass\n", encoding="utf-8")
            added = validate_framework.framework_product_surface_signature(root)
            (root / "TODO.md").write_text("active_count: 0\n", encoding="utf-8")
            local_state = validate_framework.framework_product_surface_signature(root)

        self.assertNotEqual(baseline, rewritten)
        self.assertNotEqual(rewritten, added)
        self.assertNotEqual(added, local_state)

    def test_framework_surface_signature_ignores_private_and_cache_churn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "keep.py").write_text("pass\n", encoding="utf-8")
            baseline = validate_framework.framework_product_surface_signature(root)

            private = root / "private"
            private.mkdir()
            (private / "working.md").write_text("changed\n", encoding="utf-8")
            cache = scripts / "__pycache__"
            cache.mkdir()
            (cache / "keep.pyc").write_bytes(b"cache")
            after = validate_framework.framework_product_surface_signature(root)

        self.assertEqual(baseline, after)

    def test_validate_framework_rejects_midrun_product_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            readme.write_text("one\n", encoding="utf-8")

            def mutate_public_surface(_root: Path) -> list[str]:
                readme.write_text("two\n", encoding="utf-8")
                return []

            with (
                mock.patch.object(validate_framework, "REPO_ROOT", REPO_ROOT),
                mock.patch.object(validate_framework, "gitignore_contract_errors", return_value=[]),
                mock.patch.object(validate_framework, "required_surface_errors", return_value=([], [])),
                mock.patch.object(
                    validate_framework,
                    "task_order_catalog_errors",
                    side_effect=mutate_public_surface,
                ),
                mock.patch.object(validate_framework, "stale_terminology_errors", return_value=[]),
                mock.patch.object(validate_framework, "public_content_boundary_errors", return_value=[]),
                mock.patch.object(validate_framework, "load_json", return_value={}),
                mock.patch.object(validate_framework, "schedule_contract_errors", return_value=[]),
                mock.patch.object(validate_framework, "clause_and_entrypoint_errors", return_value=[]),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = validate_framework.main(["--root", str(root)])

        self.assertEqual(1, result)
        self.assertIn(
            "framework product surface changed while validation was running",
            stdout.getvalue(),
        )

    def test_validate_framework_main_restores_process_global_root(self) -> None:
        original_root = validate_framework.REPO_ROOT
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                result = validate_framework.main(["--root", temp_dir])

        self.assertEqual(1, result)
        self.assertEqual(original_root, validate_framework.REPO_ROOT)

    def test_framework_consistency_main_restores_process_global_root(self) -> None:
        original_root = framework_consistency.REPO_ROOT
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                framework_consistency,
                "collect_consistency_issues",
                side_effect=RuntimeError("synthetic collector failure"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic collector failure",
                ):
                    framework_consistency.main(["--root", temp_dir])

        self.assertEqual(original_root, framework_consistency.REPO_ROOT)

    def test_framework_consistency_blocks_paths_outside_repo(self) -> None:
        errors: list[str] = []

        self.assertIsNone(framework_consistency.resolve_repo_file("../outside.md", errors, "escape"))
        self.assertTrue(errors)

    def test_native_wrapper_candidate_does_not_require_packaging(self) -> None:
        schedule = {
            "practice_guides": [
                {"name": "review", "wrapper_status": "candidate"}
            ]
        }
        registry = {"families": {"codex": {"wrappers": {}}}}
        errors: list[str] = []

        framework_consistency.validate_practice_guide_contract(
            schedule,
            registry,
            errors,
        )

        self.assertEqual([], errors)

    def test_native_wrapper_candidate_may_exist_in_only_one_family(self) -> None:
        schedule = {
            "practice_guides": [
                {"name": "review", "wrapper_status": "candidate"}
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper = root / "codex-review.template"
            wrapper.write_text("launcher\n", encoding="utf-8")
            (root / "claude-other.template").write_text(
                "launcher\n",
                encoding="utf-8",
            )
            registry = {
                "families": {
                    "codex": {
                        "wrappers": {"review": {"path": wrapper.name}}
                    },
                    "claude-code": {
                        "wrappers": {
                            "other": {"path": "claude-other.template"}
                        }
                    },
                }
            }
            errors: list[str] = []
            with mock.patch.object(framework_consistency, "REPO_ROOT", root):
                framework_consistency.validate_practice_guide_contract(
                    schedule,
                    registry,
                    errors,
                )

        self.assertEqual([], errors)

    def test_required_native_wrapper_requires_each_supported_family(self) -> None:
        schedule = {
            "practice_guides": [
                {"name": "review", "wrapper_status": "required"}
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper = root / "codex-review.template"
            wrapper.write_text("launcher\n", encoding="utf-8")
            (root / "claude-other.template").write_text(
                "launcher\n",
                encoding="utf-8",
            )
            registry = {
                "families": {
                    "codex": {
                        "wrappers": {"review": {"path": wrapper.name}}
                    },
                    "claude-code": {
                        "wrappers": {
                            "other": {"path": "claude-other.template"}
                        }
                    },
                }
            }
            errors: list[str] = []
            with mock.patch.object(framework_consistency, "REPO_ROOT", root):
                framework_consistency.validate_practice_guide_contract(
                    schedule,
                    registry,
                    errors,
                )

        self.assertEqual(
            ["missing claude-code wrapper for required native wrapper review"],
            errors,
        )

    def test_registered_candidate_wrapper_path_must_be_a_file(self) -> None:
        schedule = {
            "practice_guides": [
                {"name": "review", "wrapper_status": "candidate"}
            ]
        }
        registry = {
            "families": {
                "codex": {
                    "wrappers": {
                        "review": {"path": "missing-review.template"}
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            errors: list[str] = []
            with mock.patch.object(
                framework_consistency,
                "REPO_ROOT",
                Path(temp_dir),
            ):
                framework_consistency.validate_practice_guide_contract(
                    schedule,
                    registry,
                    errors,
                )

        self.assertEqual(
            [
                "registered codex wrapper path missing for review: "
                "missing-review.template"
            ],
            errors,
        )

    def test_framework_consistency_validates_startup_state_rules_structurally(self) -> None:
        contract = {
            "schema_version": 2,
            "phase_order": [
                "platform_enforcement",
                "operative_charter",
                "project_contract",
                "user_request",
                "startup_state",
                "routing",
                "workflow_selection",
                "practice_guide_modules",
                "evidence_bundle",
                "tool_results",
            ],
            "phase_titles": {
                "platform_enforcement": "Platform enforcement",
                "operative_charter": "runtime/operative_charter.md",
                "project_contract": "Project contract",
                "user_request": "User request",
                "startup_state": "Startup state",
                "routing": "Routing",
                "workflow_selection": "Workflow selection",
                "practice_guide_modules": "Practice Guide module(s)",
                "evidence_bundle": "Evidence bundle",
                "tool_results": "Tool results",
            },
            "startup_state": {
                "header_files": ["TODO.md", "DECISIONS.md"],
                "empty_count_markers": {
                    "TODO.md": ["active_count: 0"],
                    "DECISIONS.md": ["durable_decision_count: 0", "directive_count: 0"],
                },
                "empty_markers": ["template-empty files", "- None."],
                "full_record_gate": ["header", "index", "scope", "task tag"],
                "barred_by": ["scope", "privacy"],
                "permission_effect": "none",
                "conditional_files": {
                    "FINDINGS.md": ["insights", "framework-feedback"],
                    "PRECEDENTS.md": ["recorded trigger"],
                },
            },
            "projection_paths": ["runtime/load_order.md"],
        }
        text = "\n".join(
            [
                "# Runtime Load Order",
                "",
                "1. Platform enforcement",
                "2. `runtime/operative_charter.md`",
                "3. Project contract",
                "4. User request",
                "5. Startup state",
                "   State files are header-gated: inspect `TODO.md` and `DECISIONS.md` headers.",
                "   TODO is empty at active_count: 0; DECISIONS is empty only when durable_decision_count: 0 and directive_count: 0.",
                "   Treat template-empty files and - None. as empty.",
                "   Full records depend on header, index, scope, and task tag, unless barred by scope or privacy.",
                "   Load `FINDINGS.md` only for insights and framework-feedback work.",
                "   Load `PRECEDENTS.md` only when a recorded trigger matches.",
                "6. Routing",
                "7. Workflow selection",
                "8. Practice Guide module(s)",
                "9. Evidence bundle",
                "10. Tool results",
            ]
        )
        good_errors: list[str] = []
        missing_trigger_errors: list[str] = []
        missing_directive_marker_errors: list[str] = []

        framework_consistency.validate_runtime_load_order(text, contract, good_errors)
        framework_consistency.validate_runtime_load_order(
            text.replace("framework-feedback", "framework maintenance"),
            contract,
            missing_trigger_errors,
        )
        framework_consistency.validate_runtime_load_order(
            text.replace("directive_count: 0", "directive count is empty"),
            contract,
            missing_directive_marker_errors,
        )

        self.assertEqual([], good_errors)
        self.assertTrue(
            any("missing trigger 'framework-feedback' for FINDINGS.md" in error for error in missing_trigger_errors),
            missing_trigger_errors,
        )
        self.assertTrue(
            any("directive_count: 0" in error for error in missing_directive_marker_errors),
            missing_directive_marker_errors,
        )

    def test_framework_consistency_validates_workflow_selection_route_structurally(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        prose_catalog = dict(catalog)
        prose_policy = dict(catalog["workflow_selection"])
        prose_policy["ambiguous_workflow_route"] = (
            "Load the router instead of choosing a compact runtime task module by natural-language guess."
        )
        prose_catalog["workflow_selection"] = prose_policy
        missing_intent_catalog = dict(catalog)
        missing_intent_policy = dict(catalog["workflow_selection"])
        missing_intent_policy["known_workflow_provenance"] = [
            item
            for item in missing_intent_policy["known_workflow_provenance"]
            if item != "single unambiguous natural-language match to one catalog workflow"
        ]
        missing_intent_catalog["workflow_selection"] = missing_intent_policy
        stale_route_catalog = dict(catalog)
        stale_route_policy = dict(catalog["workflow_selection"])
        stale_route = dict(stale_route_policy["ambiguous_workflow_route"])
        stale_route["conditions"] = [
            "missing_explicit_provenance",
            "multiple_matching_workflows",
        ]
        stale_route_policy["ambiguous_workflow_route"] = stale_route
        stale_route_catalog["workflow_selection"] = stale_route_policy
        prose_errors: list[str] = []
        missing_intent_errors: list[str] = []
        stale_route_errors: list[str] = []
        good_errors: list[str] = []

        framework_consistency.validate_workflow_selection_policy(catalog, good_errors)
        framework_consistency.validate_workflow_selection_policy(prose_catalog, prose_errors)
        framework_consistency.validate_workflow_selection_policy(
            missing_intent_catalog,
            missing_intent_errors,
        )
        framework_consistency.validate_workflow_selection_policy(
            stale_route_catalog,
            stale_route_errors,
        )

        self.assertEqual([], good_errors)
        self.assertTrue(
            any("ambiguous_workflow_route must be a structural route object" in error for error in prose_errors),
            prose_errors,
        )
        self.assertTrue(
            any("must match supported selection evidence" in error for error in missing_intent_errors),
            missing_intent_errors,
        )
        self.assertTrue(
            any("ambiguous_workflow_route conditions drift" in error for error in stale_route_errors),
            stale_route_errors,
        )

    def test_framework_contracts_validate_operative_schedule_authority_scope(self) -> None:
        schedule = validate_framework.load_json(REPO_ROOT / "runtime" / "operative_schedule.json")
        good_errors: list[str] = []
        bad_errors: list[str] = []
        bad_schedule = dict(schedule)
        bad_schedule["authority_scope"] = {
            "allowed_effect": "select-runtime-routing",
            "selects": ["standards_of_care", "practice_guides"],
            "does_not_override": ["MSA"],
            "grants_permission": True,
            "grants_doctrine": False,
        }

        framework_contracts.validate_operative_schedule_authority_scope(schedule, good_errors)
        framework_contracts.validate_operative_schedule_authority_scope(bad_schedule, bad_errors)

        self.assertEqual([], good_errors)
        self.assertTrue(any("authority_scope.selects" in error for error in bad_errors), bad_errors)
        self.assertTrue(any("authority_scope.does_not_override" in error for error in bad_errors), bad_errors)
        self.assertTrue(any("grants_permission must be false" in error for error in bad_errors), bad_errors)

    def test_framework_compliance_rejects_invalid_json_output(self) -> None:
        ok, payload, message = framework_compliance.run_json(
            "invalid-json",
            [sys.executable, "-c", "print('not json')"],
            REPO_ROOT,
        )

        self.assertFalse(ok)
        self.assertIsNone(payload)
        self.assertIn("invalid JSON output", message)

        direct_result = framework_compliance.assert_true(
            ok and payload is not None,
            "invalid-json",
            "generic semantic failure",
        )
        result = framework_compliance.assert_command_result(
            False,
            "invalid-json",
            "generic semantic failure",
            command_ok=ok,
            command_message=message,
        )
        self.assertFalse(result[0])
        self.assertIn("invalid JSON output", result[1])
        self.assertNotIn("generic semantic failure", result[1])
        self.assertFalse(direct_result[0])
        self.assertIn("invalid JSON output", direct_result[1])
        self.assertNotIn("generic semantic failure", direct_result[1])

    def test_framework_compliance_preserves_structured_nonzero_output(self) -> None:
        child_report = {"errors": ["semantic failure"], "warnings": ["advisory"]}
        ok, payload, message = framework_compliance.run_json(
            "structured-failure",
            [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    f"print(json.dumps({child_report!r})); "
                    "sys.exit(7)"
                ),
            ],
            REPO_ROOT,
        )

        self.assertFalse(ok)
        self.assertEqual(child_report, payload)
        self.assertIn("structured-failure: FAIL", message)
        semantic_result = framework_compliance.assert_command_result(
            payload == child_report,
            "structured-failure",
            "generic semantic failure",
            command_ok=ok,
            command_message=message,
        )
        self.assertFalse(semantic_result[0])
        self.assertEqual(message, semantic_result[1])

    def test_framework_compliance_rejects_structured_stderr_without_losing_payload(self) -> None:
        child_report = {
            "errors": ["semantic failure"],
            "warnings": ["advisory"],
        }
        ok, payload, message = framework_compliance.run_json(
            "structured-stderr",
            [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    f"print(json.dumps({child_report!r})); "
                    "print('side-channel diagnostic', file=sys.stderr)"
                ),
            ],
            REPO_ROOT,
        )

        self.assertFalse(ok)
        self.assertEqual(child_report, payload)
        self.assertIn("stderr must be empty", message)
        self.assertIn("side-channel diagnostic", message)
        self.assertIn("semantic failure", message)
        self.assertIn("advisory", message)
        self.assertIn("structured report:", message)
        self.assertNotIn("invalid JSON", message)

    def test_framework_compliance_retains_and_validates_warning_reports(self) -> None:
        warning_report = {
            "errors": [],
            "warnings": ["kept warning"],
        }
        retained = framework_compliance.assert_clean_json_report(
            warning_report,
            "diagnostic-child",
            "expected a clean diagnostic report",
            command_ok=True,
            command_message="diagnostic-child: PASS",
        )
        strict = framework_compliance.assert_clean_json_report(
            warning_report,
            "diagnostic-child",
            "expected no warnings",
            command_ok=True,
            command_message="diagnostic-child: PASS",
            require_no_warnings=True,
        )
        malformed = framework_compliance.assert_clean_json_report(
            {"errors": [], "warnings": "malformed"},
            "diagnostic-child",
            "expected a clean diagnostic report",
            command_ok=True,
            command_message="diagnostic-child: PASS",
        )
        missing = framework_compliance.assert_clean_json_report(
            {"errors": []},
            "diagnostic-child",
            "expected a clean diagnostic report",
            command_ok=True,
            command_message="diagnostic-child: PASS",
        )

        self.assertTrue(retained[0])
        self.assertIn("reported warning: kept warning", retained[1])
        self.assertFalse(strict[0])
        self.assertIn("reported warning: kept warning", strict[1])
        self.assertFalse(malformed[0])
        self.assertIn("$.warnings must be a JSON array", malformed[1])
        self.assertFalse(missing[0])
        self.assertIn("$.warnings is required", missing[1])

    def test_conformance_release_checks_bind_fixed_tree_roles(self) -> None:
        captured_commands: list[tuple[list[str], Path]] = []

        def fake_run_command(
            _label: str,
            cmd: list[str],
            cwd: Path,
            **_kwargs: object,
        ) -> conformance_check.CommandCapture:
            captured_commands.append((cmd, cwd))
            return conformance_check.CommandCapture(
                ok=True,
                stdout=json.dumps({"errors": [], "warnings": []}),
                returncode=0,
            )

        with mock.patch.object(
            conformance_check,
            "run_command_capture",
            side_effect=fake_run_command,
        ):
            public_outcome = conformance_check.check_framework_public_release(
                REPO_ROOT
            )
            authoring_outcome = conformance_check.check_framework_authoring_release(
                REPO_ROOT
            )

        self.assertEqual((), public_outcome.errors)
        self.assertEqual((), public_outcome.warnings)
        self.assertIsNone(public_outcome.protocol_failure)
        self.assertEqual((), authoring_outcome.errors)
        self.assertEqual((), authoring_outcome.warnings)
        self.assertIsNone(authoring_outcome.protocol_failure)

        first_command, first_cwd = captured_commands[0]
        second_command, second_cwd = captured_commands[1]
        self.assertEqual(
            str(conformance_check.FRAMEWORK_ROOT / "scripts" / "public_release_check.py"),
            first_command[2],
        )
        self.assertEqual(
            ["--tree-role", "public-export"],
            first_command[-2:],
        )
        self.assertEqual(
            ["--tree-role", "authoring-source"],
            second_command[-2:],
        )
        self.assertEqual(conformance_check.FRAMEWORK_ROOT, first_cwd)
        self.assertEqual(conformance_check.FRAMEWORK_ROOT, second_cwd)

    def test_conformance_framework_checks_use_trusted_programs_for_selected_root(self) -> None:
        selected_root = REPO_ROOT / "tests"
        captured: list[tuple[str, list[str], Path]] = []

        def fake_run_command(
            label: str,
            cmd: list[str],
            cwd: Path,
        ) -> tuple[bool, str]:
            captured.append((label, cmd, cwd))
            return True, json.dumps({"errors": [], "warnings": []})

        def fake_run_capture(
            label: str,
            cmd: list[str],
            cwd: Path,
            **_kwargs: object,
        ) -> conformance_check.CommandCapture:
            captured.append((label, cmd, cwd))
            return conformance_check.CommandCapture(
                ok=True,
                stdout=json.dumps({"errors": [], "warnings": []}),
                returncode=0,
            )

        with (
            mock.patch.object(
                conformance_check,
                "run_command",
                side_effect=fake_run_command,
            ),
            mock.patch.object(
                conformance_check,
                "run_command_capture",
                side_effect=fake_run_capture,
            ),
        ):
            self.assertEqual(
                [],
                conformance_check.check_framework_validate(selected_root),
            )
            consistency = conformance_check.check_framework_consistency(
                selected_root
            )

        self.assertEqual((), consistency.errors)
        self.assertEqual((), consistency.warnings)
        self.assertIsNone(consistency.protocol_failure)

        self.assertEqual(
            [
                str(conformance_check.FRAMEWORK_ROOT / "scripts" / "validate_framework.py"),
                str(conformance_check.FRAMEWORK_ROOT / "scripts" / "framework_consistency.py"),
            ],
            [command[2] for _label, command, _cwd in captured],
        )
        for _label, command, cwd in captured:
            self.assertEqual(["--root", str(selected_root)], command[3:])
            self.assertEqual(conformance_check.FRAMEWORK_ROOT, cwd)

    def test_framework_compliance_prefers_preinstalled_basedpyright(self) -> None:
        def fake_which(tool: str) -> str | None:
            return "/usr/bin/basedpyright" if tool == "basedpyright" else None

        with mock.patch("framework_compliance.shutil.which", side_effect=fake_which):
            self.assertEqual(
                [
                    "/usr/bin/basedpyright",
                    "scripts",
                    "tests",
                ],
                framework_compliance.python_type_check_command(),
            )

    def test_framework_compliance_uses_offline_uvx_for_basedpyright_fallback(self) -> None:
        def fake_which(tool: str) -> str | None:
            if tool == "basedpyright":
                return None
            if tool == "uvx":
                return "/usr/bin/uvx"
            return None

        with mock.patch("framework_compliance.shutil.which", side_effect=fake_which):
            self.assertEqual(
                [
                    "uvx",
                    "--offline",
                    "basedpyright",
                    "scripts",
                    "tests",
                ],
                framework_compliance.python_type_check_command(),
            )

    def test_framework_compliance_has_no_other_literal_private_root_child(self) -> None:
        source = (SCRIPTS_DIR / "framework_compliance.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        direct_private_children = {
            node.right.value
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.left, ast.Name)
            and node.left.id == "private_root"
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
        }

        self.assertEqual({"validate.py"}, direct_private_children)

    def test_framework_compliance_requires_tracked_regular_private_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_root_name = "private"
            validator_rel = f"{private_root_name}/validate.py"
            private = root / private_root_name
            private.mkdir()
            validator = private / "validate.py"
            validator.write_text("raise SystemExit(99)\n", encoding="utf-8")

            self.assertIsNone(
                framework_compliance.tracked_regular_file(
                    root,
                    validator_rel,
                    tracked_files=frozenset(),
                )
            )
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            self.assertIsNone(
                framework_compliance.tracked_regular_file(
                    root,
                    validator_rel,
                    tracked_files=frozenset(),
                )
            )
            run_bounded(
                ["git", "add", validator_rel],
                cwd=root,
                check=True,
            )
            self.assertEqual(
                validator,
                framework_compliance.tracked_regular_file(
                    root,
                    validator_rel,
                    tracked_files=frozenset({validator_rel}),
                ),
            )

            replacement = root / "replacement.py"
            replacement.write_text("raise SystemExit(98)\n", encoding="utf-8")
            validator.unlink()
            validator.symlink_to(replacement)
            self.assertIsNone(
                framework_compliance.tracked_regular_file(
                    root,
                    validator_rel,
                    tracked_files=frozenset({validator_rel}),
                )
            )

            validator.unlink()
            private.rmdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "validate.py").write_text(
                "raise SystemExit(97)\n",
                encoding="utf-8",
            )
            private.symlink_to(outside, target_is_directory=True)
            self.assertIsNone(
                framework_compliance.tracked_regular_file(
                    root,
                    validator_rel,
                    tracked_files=frozenset({validator_rel}),
                )
            )

    def test_framework_compliance_fails_closed_for_untrusted_authoring_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_root_name = "private"
            validator_rel = f"{private_root_name}/validate.py"
            manifest_rel = "PROJECT_INSTANCE.json"
            validator = root / private_root_name / "validate.py"
            manifest = root / manifest_rel
            validator.parent.mkdir(parents=True)
            validator.write_text("raise SystemExit(99)\n", encoding="utf-8")
            manifest.write_text("{}\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(
                ["git", "add", validator_rel, manifest_rel],
                cwd=root,
                check=True,
            )

            tracked_files = frozenset({validator_rel, manifest_rel})
            entrypoint, error = framework_compliance.private_validation_entrypoint(
                root,
                tracked_files=tracked_files,
                authoring_surface_expected=True,
            )
            self.assertEqual(validator, entrypoint)
            self.assertIsNone(error)

            validator.unlink()
            entrypoint, error = framework_compliance.private_validation_entrypoint(
                root,
                tracked_files=tracked_files,
                authoring_surface_expected=True,
            )
            self.assertIsNone(entrypoint)
            self.assertIn("authoring identity state requires", error or "")

            validator.write_text("raise SystemExit(98)\n", encoding="utf-8")
            alias = root / "validator-alias.py"
            os.link(validator, alias)
            entrypoint, error = framework_compliance.private_validation_entrypoint(
                root,
                tracked_files=tracked_files,
                authoring_surface_expected=True,
            )
            self.assertIsNone(entrypoint)
            self.assertIn("single-link regular", error or "")

    def test_private_authoring_routing_ignores_foreign_ambient_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            foreign = base / "foreign"
            validator_rel = "private" + "/validate.py"
            manifest_rel = "PROJECT_INSTANCE.json"
            validator = root / validator_rel
            validator.parent.mkdir(parents=True)
            validator.write_text("raise SystemExit(99)\n", encoding="utf-8")
            (root / manifest_rel).write_text("{}\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", manifest_rel], cwd=root, check=True)

            (foreign / "private").mkdir(parents=True)
            (foreign / validator_rel).write_text("pass\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=foreign, check=True)
            run_bounded(["git", "add", validator_rel], cwd=foreign, check=True)
            ambient = {
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(foreign),
                "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
            }

            with (
                mock.patch.dict(os.environ, ambient, clear=False),
                mock.patch.object(
                    framework_compliance.public_release_check,
                    "git_tracked_files",
                    wraps=framework_compliance.public_release_check.git_tracked_files,
                ) as inventory,
                mock.patch.object(
                    framework_compliance,
                    "deep_research_digest_paths",
                    return_value=[],
                ),
                mock.patch.object(
                    framework_compliance,
                    "codex_automation_registry_path",
                    return_value=None,
                ),
                mock.patch.object(framework_compliance, "run_json") as private_run,
                mock.patch.object(
                    framework_compliance.conformance_check,
                    "run_json_child",
                    return_value=conformance_check.CheckOutcome(warnings_fail=True),
                ),
            ):
                checks = framework_compliance._collect_private_authoring_checks(
                    sys.executable,
                    root,
                )

        private_run.assert_not_called()
        self.assertTrue(
            any(
                "authoring identity state requires" in message
                for _ok, message in checks
            ),
            checks,
        )

    def test_private_authoring_checks_reject_midrun_git_inventory_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# tracked\n", encoding="utf-8")
            candidate = root / "late-tracked.md"
            candidate.write_text("# late\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "README.md"], cwd=root, check=True)
            mutated = False

            def mutate_inventory(_repo_root: Path) -> list[Path]:
                nonlocal mutated
                run_bounded(["git", "add", candidate.name], cwd=root, check=True)
                mutated = True
                return []

            with (
                mock.patch.object(
                    framework_compliance,
                    "deep_research_digest_paths",
                    side_effect=mutate_inventory,
                ),
                mock.patch.object(
                    framework_compliance,
                    "codex_automation_registry_path",
                    return_value=None,
                ),
            ):
                checks = framework_compliance._collect_private_authoring_checks(
                    sys.executable,
                    root,
                )

            self.assertTrue(mutated)
            self.assertIn(
                (
                    False,
                    "private-authoring-git-inventory-stability: FAIL\n"
                    "Git-tracked inventory changed while private authoring checks "
                    "were running",
                ),
                checks,
            )

    def test_private_authoring_checks_fail_when_final_git_inventory_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(
                    framework_compliance.public_release_check,
                    "git_tracked_files",
                    side_effect=[{"README.md"}, None],
                ),
                mock.patch.object(
                    framework_compliance,
                    "deep_research_digest_paths",
                    return_value=[],
                ),
                mock.patch.object(
                    framework_compliance,
                    "codex_automation_registry_path",
                    return_value=None,
                ),
            ):
                checks = framework_compliance._collect_private_authoring_checks(
                    sys.executable,
                    root,
                )

            self.assertTrue(
                any(
                    not ok
                    and "final authoring-source compliance requires a usable"
                    in message
                    for ok, message in checks
                ),
                checks,
            )

    def test_private_authoring_routing_fails_before_execution_without_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "PROJECT_INSTANCE.json").write_text("{}\n", encoding="utf-8")
            with (
                mock.patch.object(
                    framework_compliance,
                    "deep_research_digest_paths",
                    return_value=[],
                ),
                mock.patch.object(
                    framework_compliance,
                    "codex_automation_registry_path",
                    return_value=None,
                ),
                mock.patch.object(framework_compliance, "run_json") as private_run,
                mock.patch.object(
                    framework_compliance.conformance_check,
                    "run_json_child",
                ) as child,
            ):
                checks = framework_compliance._collect_private_authoring_checks(
                    sys.executable,
                    root,
                )

        private_run.assert_not_called()
        child.assert_not_called()
        self.assertEqual(1, len(checks))
        self.assertFalse(checks[0][0])
        self.assertIn("private-authoring-git-inventory: FAIL", checks[0][1])

    def test_framework_compliance_preserves_private_failure_diagnostics(self) -> None:
        result = framework_compliance.private_validation_result(
            False,
            None,
            "private-authoring-validation: FAIL\nprivate-maintenance-check: timed out",
        )

        self.assertFalse(result[0])
        self.assertIn("private-maintenance-check: timed out", result[1])

    def test_framework_compliance_rejects_incompatible_json_shapes(self) -> None:
        private_result = framework_compliance.private_validation_result(
            True,
            [],
            "private-authoring-validation: PASS",
        )
        semantic_result = framework_compliance.assert_json_result(
            {},
            "check-prereqs",
            "expected prerequisite report to declare its selected runner",
            command_ok=True,
            command_message="check-prereqs: PASS",
            shape=framework_compliance._PREREQUISITE_REPORT_SHAPE,
            predicate=lambda value: "runner" in value,
        )

        def malformed_collector(_python: str, _root: Path) -> list[tuple[bool, str]]:
            raise KeyError("required_field")

        collected = framework_compliance._collect_checks_safely(
            "shape-check-collection",
            malformed_collector,
            sys.executable,
            REPO_ROOT,
        )

        self.assertFalse(private_result[0])
        self.assertIn("must be a JSON object", private_result[1])
        self.assertFalse(semantic_result[0])
        self.assertIn("check-prereqs: FAIL", semantic_result[1])
        self.assertNotIn("check-prereqs: PASS", semantic_result[1])
        self.assertEqual(1, len(collected))
        self.assertFalse(collected[0][0])
        self.assertIn("incompatible result shape", collected[0][1])

    def test_framework_compliance_bounds_runtime_collector_failures(self) -> None:
        for failure in (
            FileNotFoundError("runtime/operative_schedule.json"),
            RuntimeError("collector\nfailed"),
        ):
            with self.subTest(failure=type(failure).__name__):
                def failing_collector(
                    _python: str,
                    _root: Path,
                    *,
                    failure: Exception = failure,
                ) -> list[tuple[bool, str]]:
                    raise failure

                collected = framework_compliance._collect_checks_safely(
                    "runtime-check-collection",
                    failing_collector,
                    sys.executable,
                    REPO_ROOT,
                )

            self.assertEqual(1, len(collected))
            self.assertFalse(collected[0][0])
            self.assertIn(
                "compliance collector could not complete",
                collected[0][1],
            )
            self.assertIn(type(failure).__name__, collected[0][1])
            self.assertNotIn("\nfailed", collected[0][1])

    def test_framework_compliance_main_runs_later_collectors_after_failure(self) -> None:
        calls: list[str] = []

        def failing_collector(
            _python: str,
            _root: Path,
            _tree_role: framework_compliance.ReleaseTreeRole,
            *,
            uv_executable: object | None = None,
        ) -> list[tuple[bool, str]]:
            self.assertIsNone(uv_executable)
            self.assertEqual("1", os.environ.get("PYTHONDONTWRITEBYTECODE"))
            self.assertEqual(
                framework_compliance.PUBLICATION_NODE_OPTIONS,
                os.environ.get("NODE_OPTIONS"),
            )
            calls.append("foundation")
            raise FileNotFoundError("runtime/operative_schedule.json")

        def successful_collector(
            label: str,
        ) -> Callable[[str, Path], list[tuple[bool, str]]]:
            def collect(
                _python: str,
                _root: Path,
                *,
                git_executable: object | None = None,
            ) -> list[tuple[bool, str]]:
                self.assertIsNone(git_executable)
                self.assertEqual("1", os.environ.get("PYTHONDONTWRITEBYTECODE"))
                self.assertEqual(
                    framework_compliance.PUBLICATION_NODE_OPTIONS,
                    os.environ.get("NODE_OPTIONS"),
                )
                calls.append(label)
                return [(True, f"{label}: PASS")]

            return collect

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                framework_compliance,
                "_collect_foundation_checks",
                side_effect=failing_collector,
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_private_authoring_checks",
                side_effect=successful_collector("private"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_routing_checks",
                side_effect=successful_collector("routing"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_context_checks",
                side_effect=successful_collector("context"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_consistency_checks",
                side_effect=successful_collector("consistency"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_authoring_workspace_hygiene_checks",
                side_effect=successful_collector("hygiene"),
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = framework_compliance.main(
                ["--tree-role", "authoring-source"]
            )

        self.assertEqual(1, result)
        self.assertEqual(
            ["foundation", "private", "routing", "context", "consistency", "hygiene"],
            calls,
        )
        self.assertIn("FileNotFoundError", stdout.getvalue())

    def test_framework_compliance_bounds_and_restores_routine_environment(
        self,
    ) -> None:
        default = framework_compliance.PUBLICATION_NODE_OPTIONS
        cases = (
            (None, default),
            ("", default),
            ("--trace-warnings", f"{default} --trace-warnings"),
            (
                "--max-old-space-size=896",
                f"{default} --max-old-space-size=896",
            ),
        )
        for original, expected in cases:
            with self.subTest(original=original):
                initial = {} if original is None else {"NODE_OPTIONS": original}
                with mock.patch.dict(os.environ, initial, clear=True):
                    with framework_compliance._routine_child_environment():
                        self.assertEqual(expected, os.environ.get("NODE_OPTIONS"))
                        self.assertEqual(
                            "1",
                            os.environ.get("PYTHONDONTWRITEBYTECODE"),
                        )
                    if original is None:
                        self.assertNotIn("NODE_OPTIONS", os.environ)
                    else:
                        self.assertEqual(original, os.environ.get("NODE_OPTIONS"))
                    self.assertNotIn("PYTHONDONTWRITEBYTECODE", os.environ)

    def test_framework_compliance_requires_explicit_tree_role(self) -> None:
        with (
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            framework_compliance.main([])

        self.assertEqual(2, ctx.exception.code)
        self.assertIn("--tree-role", stderr.getvalue())

    def test_framework_compliance_public_role_skips_private_collector(self) -> None:
        calls: list[str] = []

        def foundation_collector(
            _python: str,
            _root: Path,
            tree_role: framework_compliance.ReleaseTreeRole,
            *,
            uv_executable: object | None = None,
        ) -> list[tuple[bool, str]]:
            self.assertIsNone(uv_executable)
            calls.append(f"foundation:{tree_role.value}")
            return [(True, "foundation: PASS")]

        def successful_collector(
            label: str,
        ) -> Callable[[str, Path], list[tuple[bool, str]]]:
            def collect(_python: str, _root: Path) -> list[tuple[bool, str]]:
                calls.append(label)
                return [(True, f"{label}: PASS")]

            return collect

        private_collector = mock.Mock(
            side_effect=successful_collector("private")
        )
        hygiene_collector = mock.Mock(
            side_effect=successful_collector("hygiene")
        )
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                framework_compliance,
                "_collect_foundation_checks",
                side_effect=foundation_collector,
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_private_authoring_checks",
                private_collector,
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_routing_checks",
                side_effect=successful_collector("routing"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_context_checks",
                side_effect=successful_collector("context"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_consistency_checks",
                side_effect=successful_collector("consistency"),
            ),
            mock.patch.object(
                framework_compliance,
                "_collect_authoring_workspace_hygiene_checks",
                hygiene_collector,
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = framework_compliance.main(
                ["--tree-role", "public-export"]
            )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                "foundation:public-export",
                "routing",
                "context",
                "consistency",
            ],
            calls,
        )
        private_collector.assert_not_called()
        hygiene_collector.assert_not_called()

    def test_authoring_workspace_hygiene_collector_requires_tracked_stable_inputs(
        self,
    ) -> None:
        checker_ref, policy_ref = (
            framework_compliance._authoring_workspace_hygiene_refs()
        )
        tracked = {checker_ref, policy_ref}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for rel in sorted(tracked):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            with (
                mock.patch.object(
                    framework_compliance.public_release_check,
                    "git_tracked_files",
                    side_effect=(set(tracked), set(tracked)),
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_json",
                    return_value=(
                        True,
                        _clean_authoring_workspace_hygiene_report(),
                        "authoring-workspace-hygiene: PASS",
                    ),
                ) as run_json,
            ):
                checks = framework_compliance._collect_authoring_workspace_hygiene_checks(
                    sys.executable,
                    root,
                )

        self.assertEqual(
            [
                (True, "authoring-workspace-hygiene: PASS"),
                (True, "authoring-workspace-hygiene-input-stability: PASS"),
            ],
            checks,
        )
        run_json.assert_called_once()
        label, command, cwd = run_json.call_args.args
        self.assertEqual("authoring-workspace-hygiene", label)
        self.assertEqual(root, cwd)
        self.assertEqual(
            [
                sys.executable,
                "-B",
                str(root / checker_ref),
                "--root",
                str(root),
                "--policy",
                policy_ref,
                "--format",
                "json",
            ],
            command,
        )

    def test_authoring_workspace_hygiene_collector_rejects_incomplete_or_dirty_reports(
        self,
    ) -> None:
        checker_ref, policy_ref = (
            framework_compliance._authoring_workspace_hygiene_refs()
        )
        tracked = {checker_ref, policy_ref}
        clean = _clean_authoring_workspace_hygiene_report()
        reports: dict[str, dict[str, object]] = {}
        for field in tuple(clean):
            incomplete = dict(clean)
            del incomplete[field]
            reports[f"missing-{field}"] = incomplete
        reports.update(
            {
                "candidate": {
                    **clean,
                    "deletion_candidates": [
                        {
                            "path": "work/residue.tmp",
                            "reason_code": "ignored-residue",
                            "reason": "disposable test residue",
                        }
                    ],
                },
                "review": {
                    **clean,
                    "review_required": [
                        {
                            "path": "work/unknown",
                            "reason_code": "unclassified-entry",
                            "reason": "entry requires review",
                        }
                    ],
                },
                "truncated": {
                    **clean,
                    "diagnostics_truncated": True,
                    "omitted_diagnostic_count": 1,
                },
                "zero-checked-entry-count": {
                    **clean,
                    "checked_entry_count": 0,
                },
                "negative-checked-entry-count": {
                    **clean,
                    "checked_entry_count": -1,
                },
                "wrong-stability-scan-count": {
                    **clean,
                    "stability_scan_count": 1,
                },
                "nonzero-omitted-count": {
                    **clean,
                    "omitted_diagnostic_count": 1,
                },
                "negative-omitted-count": {
                    **clean,
                    "omitted_diagnostic_count": -1,
                },
                "wrong-schema-version": {
                    **clean,
                    "schema_version": 2,
                },
                "boolean-integer": {
                    **clean,
                    "checked_entry_count": True,
                },
                "integer-boolean": {
                    **clean,
                    "diagnostics_truncated": 0,
                },
                "array-type": {
                    **clean,
                    "deletion_candidates": {},
                },
                "error": {
                    **clean,
                    "errors": ["physical scan failed"],
                },
                "warning": {
                    **clean,
                    "warnings": ["scan result is incomplete"],
                },
                "unknown-field": {
                    **clean,
                    "unexpected": "not part of the report contract",
                },
                "malformed-diagnostic-item": {
                    **clean,
                    "deletion_candidates": [
                        {
                            "path": "work/residue.tmp",
                            "reason_code": "ignored-residue",
                        }
                    ],
                },
                "malformed-diagnostic-value": {
                    **clean,
                    "review_required": [
                        {
                            "path": 7,
                            "reason_code": "unclassified-entry",
                            "reason": "entry requires review",
                        }
                    ],
                },
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for rel in sorted(tracked):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            for label, report in reports.items():
                with self.subTest(label=label):
                    with (
                        mock.patch.object(
                            framework_compliance.public_release_check,
                            "git_tracked_files",
                            side_effect=(set(tracked), set(tracked)),
                        ),
                        mock.patch.object(
                            framework_compliance,
                            "run_json",
                            return_value=(
                                True,
                                report,
                                "authoring-workspace-hygiene: PASS",
                            ),
                        ),
                    ):
                        checks = framework_compliance._collect_authoring_workspace_hygiene_checks(
                            sys.executable,
                            root,
                        )

                self.assertTrue(any(not passed for passed, _message in checks), checks)
                self.assertTrue(
                    any(
                        "authoring-workspace-hygiene: FAIL" in message
                        for _passed, message in checks
                    ),
                    checks,
                )

    def test_authoring_workspace_hygiene_collector_rejects_input_byte_drift(
        self,
    ) -> None:
        checker_ref, policy_ref = (
            framework_compliance._authoring_workspace_hygiene_refs()
        )
        tracked = {checker_ref, policy_ref}
        cases = {
            "checker": (
                (
                    b"checker-before",
                    b"policy-stable",
                    b"checker-after",
                    b"policy-stable",
                ),
                checker_ref,
            ),
            "policy": (
                (
                    b"checker-stable",
                    b"policy-before",
                    b"checker-stable",
                    b"policy-after",
                ),
                policy_ref,
            ),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for rel in sorted(tracked):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            for changed_input, (observed_bytes, expected_ref) in cases.items():
                with self.subTest(changed_input=changed_input):
                    with (
                        mock.patch.object(
                            framework_compliance.public_release_check,
                            "git_tracked_files",
                            side_effect=(set(tracked), set(tracked)),
                        ),
                        mock.patch.object(
                            framework_compliance.safe_paths,
                            "read_regular_file_bytes",
                            side_effect=observed_bytes,
                        ),
                        mock.patch.object(
                            framework_compliance,
                            "run_json",
                            return_value=(
                                True,
                                _clean_authoring_workspace_hygiene_report(),
                                "authoring-workspace-hygiene: PASS",
                            ),
                        ),
                    ):
                        checks = framework_compliance._collect_authoring_workspace_hygiene_checks(
                            sys.executable,
                            root,
                        )

                self.assertTrue(any(not passed for passed, _message in checks), checks)
                rendered = "\n".join(message for _passed, message in checks)
                self.assertIn("changed", rendered)
                self.assertIn(expected_ref, rendered)

    def test_authoring_workspace_hygiene_collector_rejects_untracked_policy(
        self,
    ) -> None:
        checker_ref, policy_ref = (
            framework_compliance._authoring_workspace_hygiene_refs()
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / checker_ref
            script.parent.mkdir(parents=True)
            script.write_text("pass\n", encoding="utf-8")
            tracked = {checker_ref}
            with (
                mock.patch.object(
                    framework_compliance.public_release_check,
                    "git_tracked_files",
                    side_effect=(set(tracked), set(tracked)),
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_json",
                ) as run_json,
            ):
                checks = framework_compliance._collect_authoring_workspace_hygiene_checks(
                    sys.executable,
                    root,
                )

        self.assertFalse(checks[0][0])
        self.assertIn(policy_ref, checks[0][1])
        run_json.assert_not_called()

    def test_routing_collector_preserves_checks_around_missing_schedule(self) -> None:
        child_labels: list[str] = []

        def fake_run_json(
            label: str,
            _command: list[str],
            _cwd: Path,
            **_kwargs: object,
        ) -> tuple[bool, object, str]:
            child_labels.append(label)
            return True, {}, f"{label}: PASS"

        def fake_assert_json_result(
            _report: object,
            label: str,
            _detail: str,
            **_kwargs: object,
        ) -> tuple[bool, str]:
            return True, f"{label}: PASS"

        with (
            mock.patch.object(
                framework_compliance,
                "run_json",
                side_effect=fake_run_json,
            ),
            mock.patch.object(
                framework_compliance,
                "assert_json_result",
                side_effect=fake_assert_json_result,
            ),
            mock.patch.object(
                framework_compliance.recommend_stack,
                "load_schedule",
                side_effect=FileNotFoundError(
                    "runtime/operative_schedule.json"
                ),
            ),
        ):
            checks = framework_compliance._collect_routing_checks(
                sys.executable,
                REPO_ROOT,
            )

        self.assertEqual(
            ["check-prereqs", "query-clause-map", "recommend-stack-e2e"],
            child_labels,
        )
        self.assertEqual(4, len(checks))
        self.assertTrue(checks[0][0])
        self.assertTrue(checks[1][0])
        self.assertFalse(checks[2][0])
        self.assertIn("routing-schedule-load: FAIL", checks[2][1])
        self.assertTrue(checks[3][0])

    def test_framework_compliance_child_contracts_reject_shape_variants(self) -> None:
        contracts = (
            (
                "errors-report",
                framework_compliance._ERROR_REPORT_SHAPE,
                {"errors": "not-a-list"},
            ),
            (
                "diagnostic-report",
                framework_compliance._DIAGNOSTIC_REPORT_SHAPE,
                {"errors": [], "warnings": "not-a-list"},
            ),
            (
                "private-report",
                framework_compliance._PRIVATE_REPORT_SHAPE,
                {"errors": [], "self_test_errors": "not-a-list"},
            ),
            (
                "budget-report",
                framework_compliance._PRIVATE_BUDGET_REPORT_SHAPE,
                {
                    "schema_version": "2",
                    "validation_timeout_seconds": 1,
                    "self_test_timeout_seconds": 1,
                    "checks": [],
                    "shutdown_margin_seconds": 1,
                    "minimum_outer_timeout_seconds": 1,
                },
            ),
            (
                "deep-research-report",
                framework_compliance._DEEP_RESEARCH_REPORT_SHAPE,
                {"artifacts": [{"errors": "not-a-list"}]},
            ),
            (
                "prompt-load-report",
                framework_compliance._PROMPT_LOAD_REPORT_SHAPE,
                {
                    "eager_practice_guide_imports": [],
                    "budget_errors": "not-a-list",
                },
            ),
            (
                "prerequisite-report",
                framework_compliance._PREREQUISITE_REPORT_SHAPE,
                {"runner": 7},
            ),
            (
                "recommend-report",
                framework_compliance._RECOMMEND_REPORT_SHAPE,
                {
                    "schema_version": 1,
                    "standard_of_care": "normal",
                    "evidentiary_scope": "touched-files",
                    "practice_guides": [7],
                    "required_checks": [],
                },
            ),
            (
                "context-manifest-report",
                framework_compliance._CONTEXT_MANIFEST_REPORT_SHAPE,
                {"task_module": {"name": 7}, "required_checks": []},
            ),
            (
                "evidence-scope-report",
                framework_compliance._EVIDENCE_SCOPE_REPORT_SHAPE,
                {"recommended_scope": 7},
            ),
            (
                "verification-report",
                framework_compliance._VERIFICATION_REPORT_SHAPE,
                {"schema_version": 1, "phase_checks": []},
            ),
        )
        for label, shape, wrong_field in contracts:
            variants = (
                ("missing", {}),
                ("wrong-field", wrong_field),
            )
            for variant, payload in variants:
                with self.subTest(contract=label, variant=variant):
                    result = framework_compliance.assert_json_result(
                        payload,
                        label,
                        "semantic mismatch",
                        command_ok=True,
                        command_message=f"{label}: PASS",
                        shape=shape,
                        predicate=lambda _value: True,
                    )
                self.assertFalse(result[0])
                self.assertIn(f"{label}: FAIL", result[1])
                self.assertIn("child JSON shape", result[1])

        for variant, payload in (("object", {}), ("scalar", 7)):
            with self.subTest(contract="list-report", variant=variant):
                result = framework_compliance.assert_json_result(
                    payload,
                    "list-report",
                    "expected a non-empty list",
                    command_ok=True,
                    command_message="list-report: PASS",
                    shape=framework_compliance._JSON_ARRAY,
                    predicate=bool,
                )
            self.assertFalse(result[0])
            self.assertIn("list-report: FAIL", result[1])

        for variant, payload in (("list", []), ("scalar", 7)):
            with self.subTest(contract="object-report", variant=variant):
                result = framework_compliance.assert_json_result(
                    payload,
                    "object-report",
                    "expected an object",
                    command_ok=True,
                    command_message="object-report: PASS",
                    shape=framework_compliance._JSON_OBJECT,
                    predicate=lambda _value: True,
                )
            self.assertFalse(result[0])
            self.assertIn("object-report: FAIL", result[1])

    def test_foundation_shape_failures_keep_child_label_and_later_checks(self) -> None:
        payload = {"errors": "not-a-list"}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            labels: list[str] = []

            def fake_run_json(
                label: str,
                _command: list[str],
                _cwd: Path,
                **_kwargs: object,
            ) -> tuple[bool, object, str]:
                labels.append(label)
                if label == "framework-quality-lint":
                    return True, payload, f"{label}: PASS"
                if label == "check-reference-freshness":
                    return (
                        True,
                        {"errors": [], "warnings": []},
                        f"{label}: PASS",
                    )
                if label in {
                    "conformance-framework-public-release",
                    "link-check",
                    "nonpublic-link-check",
                }:
                    return (
                        True,
                        {"errors": [], "warnings": []},
                        f"{label}: PASS",
                    )
                return True, {"errors": []}, f"{label}: PASS"

            with (
                mock.patch.object(
                    framework_compliance,
                    "run_json",
                    side_effect=fake_run_json,
                ),
                mock.patch.object(
                    framework_compliance,
                    "run",
                    return_value=(True, "non-json-check: PASS", ""),
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_zero_skip_unittests",
                    return_value=(True, "unit-tests: PASS"),
                ),
            ):
                checks = framework_compliance._collect_foundation_checks(
                    sys.executable,
                    root,
                    framework_compliance.ReleaseTreeRole.PUBLIC_EXPORT,
                )

            by_label = {message.split(":", 1)[0]: (ok, message) for ok, message in checks}
            quality = by_label["framework-quality-lint"]
            self.assertFalse(quality[0])
            self.assertIn("framework-quality-lint: FAIL", quality[1])
            self.assertIn("child JSON shape", quality[1])
            self.assertIn("link-check", labels)
            self.assertTrue(by_label["link-check"][0])

    def test_framework_compliance_authoring_role_uses_authoring_profile(
        self,
    ) -> None:
        run_calls: list[tuple[str, list[str]]] = []
        json_calls: list[tuple[str, list[str]]] = []
        json_call_options: dict[str, dict[str, object]] = {}

        def fake_run(
            label: str,
            command: list[str],
            _cwd: Path,
            **_kwargs: object,
        ) -> tuple[bool, str, str]:
            run_calls.append((label, command))
            return True, f"{label}: PASS", ""

        def fake_run_json(
            label: str,
            command: list[str],
            _cwd: Path,
            **kwargs: object,
        ) -> tuple[bool, object, str]:
            json_calls.append((label, command))
            json_call_options[label] = kwargs
            if label in {
                "check-reference-freshness",
                "conformance-framework-authoring-release",
                "link-check",
                "nonpublic-link-check",
            }:
                report: object = {"errors": [], "warnings": []}
            else:
                report = {"errors": []}
            return True, report, f"{label}: PASS"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scripts").mkdir()
            with (
                mock.patch.object(
                    framework_compliance,
                    "run",
                    side_effect=fake_run,
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_json",
                    side_effect=fake_run_json,
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_zero_skip_unittests",
                    return_value=(True, "unit-tests: PASS"),
                ),
                mock.patch.object(
                    framework_compliance,
                    "nonpublic_link_check_command",
                    return_value=[
                        sys.executable,
                        "scripts/link_check.py",
                        "--root",
                        str(root),
                        "--include-nonpublic",
                    ],
                ),
            ):
                checks = framework_compliance._collect_foundation_checks(
                    sys.executable,
                    root,
                    framework_compliance.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertTrue(all(ok for ok, _message in checks), checks)
        conformance = [
            command
            for label, command in json_calls
            if label == "conformance-framework-authoring-release"
        ]
        self.assertEqual(1, len(conformance))
        self.assertEqual(
            "framework-authoring-release",
            conformance[0][conformance[0].index("--profile") + 1],
        )
        self.assertIn("--strict-warnings", conformance[0])
        self.assertEqual(
            conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
            json_call_options["conformance-framework-authoring-release"].get(
                "timeout_seconds"
            ),
        )
        self.assertIn("nonpublic-link-check", {label for label, _command in json_calls})
        self.assertEqual(
            len({label for label, _command in (*run_calls, *json_calls)}),
            len(run_calls) + len(json_calls),
        )
        flattened = [
            argument
            for _label, command in (*run_calls, *json_calls)
            for argument in command
        ]
        for duplicate_child in (
            "scripts/validate_framework.py",
            "scripts/framework_consistency.py",
            "scripts/public_release_check.py",
            "scripts/public_export.py",
        ):
            self.assertNotIn(duplicate_child, flattened)

    def test_framework_compliance_git_backed_public_role_uses_public_profile(
        self,
    ) -> None:
        json_calls: list[tuple[str, list[str]]] = []
        json_call_options: dict[str, dict[str, object]] = {}

        def fake_run_json(
            label: str,
            command: list[str],
            _cwd: Path,
            **kwargs: object,
        ) -> tuple[bool, object, str]:
            json_calls.append((label, command))
            json_call_options[label] = kwargs
            report: object = (
                {"errors": [], "warnings": []}
                if label
                in {
                    "check-reference-freshness",
                    "conformance-framework-public-release",
                    "link-check",
                    "nonpublic-link-check",
                }
                else {"errors": []}
            )
            return True, report, f"{label}: PASS"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "scripts").mkdir()
            with (
                mock.patch.object(
                    framework_compliance,
                    "run",
                    return_value=(True, "child: PASS", ""),
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_json",
                    side_effect=fake_run_json,
                ),
                mock.patch.object(
                    framework_compliance,
                    "run_zero_skip_unittests",
                    return_value=(True, "unit-tests: PASS"),
                ),
            ):
                framework_compliance._collect_foundation_checks(
                    sys.executable,
                    root,
                    framework_compliance.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        command = next(
            command
            for label, command in json_calls
            if label == "conformance-framework-public-release"
        )
        self.assertEqual(
            "framework-public-release",
            command[command.index("--profile") + 1],
        )
        self.assertIn("--strict-warnings", command)
        self.assertEqual(
            conformance_check.EXPORTED_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS,
            json_call_options["conformance-framework-public-release"].get(
                "timeout_seconds"
            ),
        )
        self.assertNotIn(
            "nonpublic-link-check",
            {label for label, _command in json_calls},
        )

    def test_consistency_shape_failures_keep_later_checks(self) -> None:
        payload = {
            "eager_practice_guide_imports": [],
            "budget_errors": "not-a-list",
        }
        labels: list[str] = []

        def fake_run_json(
            label: str,
            _command: list[str],
            _cwd: Path,
            **_kwargs: object,
        ) -> tuple[bool, object, str]:
            labels.append(label)
            report = payload if label == "prompt-load-report" else {"errors": []}
            return True, report, f"{label}: PASS"

        with mock.patch.object(
            framework_compliance,
            "run_json",
            side_effect=fake_run_json,
        ):
            checks = framework_compliance._collect_consistency_checks(
                sys.executable,
                REPO_ROOT,
            )

        self.assertEqual(["prompt-load-report"], labels)
        self.assertFalse(checks[0][0])
        self.assertIn("prompt-load-report: FAIL", checks[0][1])

    def test_private_authoring_structured_failure_keeps_diagnostics(self) -> None:
        with (
            mock.patch.object(
                framework_compliance,
                "private_validation_entrypoint",
                return_value=(None, None),
            ),
            mock.patch.object(
                framework_compliance.public_release_check,
                "git_tracked_files",
                return_value={"PROJECT_INSTANCE.json"},
            ) as inventory,
            mock.patch.object(
                framework_compliance,
                "deep_research_digest_paths",
                return_value=[],
            ),
            mock.patch.object(
                framework_compliance,
                "codex_automation_registry_path",
                return_value=None,
            ),
            mock.patch.object(
                framework_compliance.conformance_check,
                "run_json_child",
                return_value=conformance_check.CheckOutcome(
                    protocol_failure=(
                        "authoring-core-conformance returned an invalid report: "
                        "errors must be a list"
                    ),
                    warnings_fail=True,
                ),
            ),
        ):
            checks = framework_compliance._collect_private_authoring_checks(
                sys.executable,
                REPO_ROOT,
            )

        self.assertEqual(1, len(checks))
        self.assertFalse(checks[0][0])
        self.assertIn("authoring-core-conformance: FAIL", checks[0][1])
        self.assertIn("errors must be a list", checks[0][1])

    def test_private_authoring_presence_or_tracking_matrix_is_fail_closed(self) -> None:
        authoring_root_ref = "private" + "/authoring"
        input_path = f"{authoring_root_ref}/PROJECT_INPUT.json"
        receipt_path = "PROJECT_INSTANCE.json"
        cases = (
            ("untracked complete pair", {input_path, receipt_path}, set()),
            ("untracked input only", {input_path}, set()),
            ("untracked corrupt receipt only", {receipt_path}, set()),
            ("tracked deleted input", set(), {input_path}),
            ("absent", set(), set()),
        )

        for label, present, tracked in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for relative_path in present:
                    path = root / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(
                        "{" if "corrupt" in label else "{}\n",
                        encoding="utf-8",
                    )
                with (
                    mock.patch.object(
                        framework_compliance.public_release_check,
                        "git_tracked_files",
                        return_value=set(tracked),
                    ) as inventory,
                    mock.patch.object(
                        framework_compliance,
                        "tracked_regular_file",
                        return_value=None,
                    ),
                    mock.patch.object(
                        framework_compliance,
                        "deep_research_digest_paths",
                        return_value=[],
                    ),
                    mock.patch.object(
                        framework_compliance,
                        "codex_automation_registry_path",
                        return_value=None,
                    ),
                    mock.patch.object(
                        framework_compliance.conformance_check,
                        "run_json_child",
                        return_value=conformance_check.CheckOutcome(
                            warnings_fail=True
                        ),
                    ) as child,
                ):
                    selected = (
                        framework_compliance.authoring_instance_members(
                            root,
                            authoring_root_ref,
                            tracked_files=frozenset(tracked),
                        )
                    )
                    checks = framework_compliance._collect_private_authoring_checks(
                        sys.executable,
                        root,
                    )

                self.assertEqual(
                    tuple(
                        candidate
                        for candidate in (input_path, receipt_path)
                        if candidate in present or candidate in tracked
                    ),
                    selected,
                )
                if present or tracked:
                    self.assertEqual(2, len(checks))
                    self.assertFalse(checks[0][0])
                    self.assertIn("authoring identity state requires", checks[0][1])
                    self.assertTrue(checks[1][0])
                    child.assert_called_once()
                else:
                    self.assertEqual([], checks)
                    child.assert_not_called()

    def test_authoring_core_conformance_preserves_semantic_diagnostics(self) -> None:
        authoring_root_ref = "private" + "/authoring"
        capture = conformance_check.CommandCapture(
            ok=False,
            stdout=json.dumps(
                {
                    "errors": ["migration required", "migration required"],
                    "warnings": ["review projection", "review projection"],
                }
            ),
            returncode=1,
        )
        with mock.patch.object(
            framework_compliance.conformance_check,
            "run_command_capture",
            return_value=capture,
        ) as child:
            ok, message = framework_compliance.run_authoring_core_conformance(
                sys.executable,
                REPO_ROOT,
                authoring_root_ref,
            )

        self.assertFalse(ok)
        self.assertEqual(1, message.count("reported error: migration required"))
        self.assertEqual(1, message.count("reported warning: review projection"))
        self.assertNotIn("command failed before", message)
        self.assertNotIn("exited nonzero despite", message)
        self.assertEqual(
            conformance_check.CORE_PROJECT_AUTHORING_TIMEOUT_SECONDS,
            child.call_args.kwargs["timeout_seconds"],
        )

    def test_authoring_core_conformance_rejects_protocol_failures(self) -> None:
        authoring_root_ref = "private" + "/authoring"
        semantic_failure = json.dumps(
            {"errors": ["migration required"], "warnings": []}
        )
        clean_report = json.dumps({"errors": [], "warnings": []})
        cases = (
            (
                "malformed JSON",
                conformance_check.CommandCapture(
                    ok=False,
                    stdout="{",
                    returncode=1,
                ),
                "before returning a valid report",
            ),
            (
                "stderr",
                conformance_check.CommandCapture(
                    ok=False,
                    stdout=semantic_failure,
                    stderr="unexpected diagnostic stream",
                    returncode=1,
                ),
                "stderr must be empty",
            ),
            (
                "transport",
                conformance_check.CommandCapture(
                    ok=False,
                    stdout=clean_report,
                    transport_failure="authoring-core-conformance timed out",
                ),
                "timed out",
            ),
            (
                "zero with failing diagnostics",
                conformance_check.CommandCapture(
                    ok=True,
                    stdout=semantic_failure,
                    returncode=0,
                ),
                "exited zero despite reporting failing diagnostics",
            ),
            (
                "nonzero without failing diagnostics",
                conformance_check.CommandCapture(
                    ok=False,
                    stdout=clean_report,
                    returncode=1,
                ),
                "exited nonzero despite reporting no failing diagnostics",
            ),
        )

        for label, capture, expected in cases:
            with self.subTest(case=label):
                with mock.patch.object(
                    framework_compliance.conformance_check,
                    "run_command_capture",
                    return_value=capture,
                ):
                    ok, message = (
                        framework_compliance.run_authoring_core_conformance(
                            sys.executable,
                            REPO_ROOT,
                            authoring_root_ref,
                        )
                    )

                self.assertFalse(ok)
                self.assertIn("protocol failure:", message)
                self.assertIn(expected, message)

    def test_framework_compliance_derives_nonpublic_timeout_from_registry_report(
        self,
    ) -> None:
        budget_report = {
            "schema_version": 2,
            "validation_timeout_seconds": 60,
            "self_test_timeout_seconds": 60,
            "checks": [
                {"check_id": "first", "timeout_seconds": 60},
                {"check_id": "second", "timeout_seconds": 120},
            ],
            "shutdown_margin_seconds": 60,
            "minimum_outer_timeout_seconds": 360,
        }
        private_report = {
            "errors": [],
            "self_test_errors": [],
            "maintenance_check_errors": [],
        }
        calls: list[tuple[str, list[str], dict[str, object]]] = []

        def fake_run_json(
            label: str,
            command: list[str],
            _cwd: Path,
            **kwargs: object,
        ) -> tuple[bool, object, str]:
            calls.append((label, command, kwargs))
            if label == "private-authoring-validation-budget":
                return True, budget_report, f"{label}: PASS"
            if label == "private-authoring-validation":
                return True, private_report, f"{label}: PASS"
            self.fail(f"unexpected command: {label}")

        private_validator = REPO_ROOT / "private" / "validate.py"
        with (
            mock.patch.object(
                framework_compliance,
                "private_validation_entrypoint",
                return_value=(private_validator, None),
            ),
            mock.patch.object(
                framework_compliance,
                "run_json",
                side_effect=fake_run_json,
            ),
            mock.patch.object(
                framework_compliance.public_release_check,
                "git_tracked_files",
                return_value={"PROJECT_INSTANCE.json"},
            ) as inventory,
            mock.patch.object(
                framework_compliance,
                "deep_research_digest_paths",
                return_value=[],
            ),
            mock.patch.object(
                framework_compliance,
                "codex_automation_registry_path",
                return_value=None,
            ),
            mock.patch.object(
                framework_compliance.conformance_check,
                "run_json_child",
                return_value=conformance_check.CheckOutcome(warnings_fail=True),
            ) as child,
        ):
            checks = framework_compliance._collect_private_authoring_checks(
                sys.executable,
                REPO_ROOT,
            )

        self.assertEqual(
            [
                (True, "private-authoring-validation: PASS"),
                (True, "authoring-core-conformance: PASS"),
            ],
            checks,
        )
        self.assertEqual(
            [
                "private-authoring-validation-budget",
                "private-authoring-validation",
            ],
            [call[0] for call in calls],
        )
        expected_outer_timeout = (
            budget_report["validation_timeout_seconds"]
            + budget_report["self_test_timeout_seconds"]
            + sum(
                item["timeout_seconds"]
                for item in budget_report["checks"]
            )
            + budget_report["shutdown_margin_seconds"]
        )
        self.assertEqual(
            expected_outer_timeout,
            budget_report["minimum_outer_timeout_seconds"],
        )
        self.assertEqual(
            expected_outer_timeout,
            calls[1][2]["timeout_seconds"],
        )
        self.assertEqual(
            [
                "--self-test",
                "--outer-timeout-seconds",
                str(expected_outer_timeout),
            ],
            calls[1][1][-3:],
        )
        child.assert_called_once()
        child_call = child.call_args
        self.assertIn("--strict-warnings", child_call.args[1])
        self.assertTrue(child_call.kwargs["warnings_fail"])

    def test_framework_compliance_rejects_incoherent_nonpublic_budget_metadata(
        self,
    ) -> None:
        valid = {
            "schema_version": 2,
            "validation_timeout_seconds": 20,
            "self_test_timeout_seconds": 20,
            "checks": [{"check_id": "only", "timeout_seconds": 60}],
            "shutdown_margin_seconds": 20,
            "minimum_outer_timeout_seconds": 120,
        }
        invalid_reports = (
            (
                {**valid, "minimum_outer_timeout_seconds": 119},
                "does not equal",
            ),
            (
                {
                    **valid,
                    "checks": [
                        {"check_id": "duplicate", "timeout_seconds": 30},
                        {"check_id": "duplicate", "timeout_seconds": 30},
                    ],
                },
                "duplicate check IDs",
            ),
            (
                {
                    **valid,
                    "checks": [{"check_id": "only", "timeout_seconds": 3600}],
                    "minimum_outer_timeout_seconds": 3660,
                },
                "exceeds the shared bounded-runner maximum",
            ),
            (
                {
                    **valid,
                    "checks": [{"check_id": "only", "timeout_seconds": True}],
                    "minimum_outer_timeout_seconds": 60,
                },
                "timeout_seconds must be a JSON integer",
            ),
        )

        for report, expected_error in invalid_reports:
            with self.subTest(expected_error=expected_error):
                timeout, error = framework_compliance.private_validation_budget_result(
                    True,
                    report,
                    "private-authoring-validation-budget: PASS",
                )
                self.assertIsNone(timeout)
                self.assertIn(expected_error, error or "")

    def test_framework_compliance_stops_before_private_run_on_invalid_budget(self) -> None:
        calls: list[str] = []

        def fake_run_json(
            label: str,
            _command: list[str],
            _cwd: Path,
            **_kwargs: object,
        ) -> tuple[bool, object, str]:
            calls.append(label)
            return (
                True,
                {
                    "schema_version": 2,
                    "validation_timeout_seconds": 20,
                    "self_test_timeout_seconds": 20,
                    "checks": [{"check_id": "only", "timeout_seconds": 60}],
                    "shutdown_margin_seconds": 20,
                    "minimum_outer_timeout_seconds": 119,
                },
                f"{label}: PASS",
            )

        with (
            mock.patch.object(
                framework_compliance,
                "private_validation_entrypoint",
                return_value=(REPO_ROOT / "private" / "validate.py", None),
            ),
            mock.patch.object(
                framework_compliance,
                "run_json",
                side_effect=fake_run_json,
            ),
            mock.patch.object(
                framework_compliance.public_release_check,
                "git_tracked_files",
                return_value={"PROJECT_INSTANCE.json"},
            ) as inventory,
            mock.patch.object(
                framework_compliance,
                "deep_research_digest_paths",
                return_value=[],
            ),
            mock.patch.object(
                framework_compliance,
                "codex_automation_registry_path",
                return_value=None,
            ),
            mock.patch.object(
                framework_compliance.conformance_check,
                "run_json_child",
                return_value=conformance_check.CheckOutcome(warnings_fail=True),
            ) as child,
        ):
            checks = framework_compliance._collect_private_authoring_checks(
                sys.executable,
                REPO_ROOT,
            )

        self.assertEqual(
            ["private-authoring-validation-budget"],
            calls,
        )
        child.assert_called_once()
        self.assertEqual(2, len(checks))
        self.assertFalse(checks[0][0])
        self.assertIn("does not equal", checks[0][1])
        self.assertTrue(checks[1][0])

    def test_framework_compliance_requires_zero_skip_unit_evidence(self) -> None:
        with mock.patch.object(
            framework_compliance,
            "run",
            return_value=(
                True,
                "unit-tests: PASS",
                "Ran 5 tests in 0.001s\n\nOK (skipped=5)",
            ),
        ):
            skipped = framework_compliance.run_zero_skip_unittests(
                "unit-tests",
                [sys.executable, "-m", "unittest"],
                REPO_ROOT,
            )
        with mock.patch.object(
            framework_compliance,
            "run",
            return_value=(
                True,
                "unit-tests: PASS",
                "Ran 3 tests in 0.001s\n\nOK\nRan 0 tests in 0.000s\n\nOK",
            ),
        ):
            empty = framework_compliance.run_zero_skip_unittests(
                "unit-tests",
                [sys.executable, "-m", "unittest"],
                REPO_ROOT,
            )
        with mock.patch.object(
            framework_compliance,
            "run",
            return_value=(True, "unit-tests: PASS", "OK"),
        ):
            missing_count = framework_compliance.run_zero_skip_unittests(
                "unit-tests",
                [sys.executable, "-m", "unittest"],
                REPO_ROOT,
            )
        with mock.patch.object(
            framework_compliance,
            "run",
            return_value=(
                True,
                "unit-tests: PASS",
                "Ran 3 tests in 0.001s\n\nOK",
            ),
        ):
            complete = framework_compliance.run_zero_skip_unittests(
                "unit-tests",
                [sys.executable, "-m", "unittest"],
                REPO_ROOT,
            )

        self.assertFalse(skipped[0])
        self.assertIn("5 test(s) skipped", skipped[1])
        self.assertIn("publication evidence must be zero-skip", skipped[1])
        self.assertFalse(empty[0])
        self.assertIn("executed zero tests", empty[1])
        self.assertFalse(missing_count[0])
        self.assertIn("did not contain a parseable", missing_count[1])
        self.assertTrue(complete[0])
        self.assertIn("3 tests completed with zero skips", complete[1])

    def test_framework_compliance_runs_monitor_root_audit(self) -> None:
        command = framework_compliance.reference_freshness_command("python")

        self.assertIn("--audit-monitor-roots", command)

    def test_framework_compliance_nonpublic_link_command_is_explicitly_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIsNone(framework_compliance.nonpublic_link_check_command("python", root))
            private = root / "private"
            private.mkdir()
            command = framework_compliance.nonpublic_link_check_command("python", root)

        if command is None:
            self.fail("nonpublic link-check command was not constructed")
        self.assertEqual(1, command.count("--include-root-path"))
        self.assertIn("private" + "/**/*.md", command)
        self.assertNotIn("review_" + "artifacts/**/*.md", command)

    def test_framework_consistency_requires_status_conditioned_obligation_markers(self) -> None:
        manifest = json.loads((REPO_ROOT / "runtime" / "task_module_obligations.json").read_text(encoding="utf-8"))
        catalog = json.loads((REPO_ROOT / "runtime" / "workflow_catalog.json").read_text(encoding="utf-8"))

        original_read_repo_text = framework_consistency.read_repo_text
        with mock.patch.object(
            framework_consistency,
            "read_repo_text",
            side_effect=lambda rel, errors, label: original_read_repo_text(rel, errors, label).replace(
                "<!-- mpa-common-precondition -->", ""
            )
            if rel == "runtime/task_modules/review.md"
            else original_read_repo_text(rel, errors, label),
        ):
            common_errors: list[str] = []
            framework_consistency.validate_runtime_task_module_obligations(
                manifest,
                catalog["task_orders"],
                common_errors,
            )

        self.assertTrue(
            any("runtime/task_modules/review.md missing common project-contract precondition" in error for error in common_errors),
            common_errors,
        )

        manifest["common_precondition"]["module_marker"] = "mpa-common-precondition-v2"
        common_drift_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(
            manifest,
            catalog["task_orders"],
            common_drift_errors,
        )

        self.assertTrue(
            any("common_precondition module_marker drift" in error for error in common_drift_errors),
            common_drift_errors,
        )

        review_anchor = "Choose the smallest justified Evidence Scope."
        with mock.patch.object(
            framework_consistency,
            "read_repo_text",
            side_effect=lambda rel, errors, label: (
                original_read_repo_text(rel, errors, label).replace(review_anchor, "")
                + f"\n<!-- {review_anchor} -->\n"
            )
            if rel == "runtime/task_modules/review.md"
            else original_read_repo_text(rel, errors, label),
        ):
            anchor_errors: list[str] = []
            framework_consistency.validate_runtime_task_module_obligations(
                manifest,
                catalog["task_orders"],
                anchor_errors,
            )

        self.assertTrue(
            any(
                "REVIEW-evidence-scope missing operative anchor from prose" in error
                for error in anchor_errors
            ),
            anchor_errors,
        )

        manifest = json.loads((REPO_ROOT / "runtime" / "task_module_obligations.json").read_text(encoding="utf-8"))

        ideate_coverage = manifest["modules"]["runtime/task_modules/ideate.md"]["runtime_coverage"]
        del ideate_coverage["IDEATE-escalate-source-or-safety"]["full_order_anchor"]
        missing_full_anchor_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(
            manifest,
            catalog["task_orders"],
            missing_full_anchor_errors,
        )

        self.assertTrue(
            any("must define full_order_anchor" in error for error in missing_full_anchor_errors),
            missing_full_anchor_errors,
        )

        ideate_coverage["IDEATE-escalate-source-or-safety"] = {
            "status": "delegates_to_full_order",
            "module_marker": "mpa-obligation: IDEATE-escalate-source-or-safety",
            "catalog_condition_id": "IDEATE-escalate-source-or-safety",
        }
        delegate_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(manifest, catalog["task_orders"], delegate_errors)

        self.assertTrue(
            any("delegates without full-order marker" in error for error in delegate_errors),
            delegate_errors,
        )

        ideate_coverage["IDEATE-escalate-source-or-safety"] = {
            "status": "delegates_to_full_order",
            "catalog_condition_id": "IDEATE-escalate-source-or-safety",
            "full_order_marker": "mpa-full-order-obligation: IDEATE-escalate-source-or-safety",
        }
        compact_delegate_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(
            manifest, catalog["task_orders"], compact_delegate_errors
        )

        self.assertTrue(
            any("delegates without module marker" in error for error in compact_delegate_errors),
            compact_delegate_errors,
        )

        ideate_coverage["IDEATE-escalate-source-or-safety"] = {
            "status": "delegates_to_full_order",
            "module_marker": "mpa-obligation: IDEATE-escalate-source-or-safety",
            "catalog_condition_id": "external-sources",
            "full_order_marker": "mpa-full-order-obligation: IDEATE-escalate-source-or-safety",
        }
        catalog_substring_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(
            manifest, catalog["task_orders"], catalog_substring_errors
        )

        self.assertTrue(
            any("delegates without catalog condition id" in error for error in catalog_substring_errors),
            catalog_substring_errors,
        )

        ideate_coverage["IDEATE-escalate-source-or-safety"] = {
            "status": "not_applicable",
            "module_marker": "mpa-obligation: wrong-id",
            "reason": "not applicable",
        }
        reason_errors: list[str] = []
        framework_consistency.validate_runtime_task_module_obligations(manifest, catalog["task_orders"], reason_errors)

        self.assertTrue(
            any("not_applicable without module marker" in error for error in reason_errors),
            reason_errors,
        )

    def test_framework_consistency_rejects_incomplete_finding_schema(self) -> None:
        schema = {
            "schema_version": 1,
            "fields": {"category": ["Bug"]},
            "conditional_constraints": [],
            "required_report_fields": ["file"],
        }
        errors: list[str] = []

        framework_consistency.validate_finding_schema(schema, errors)

        self.assertTrue(any("finding schema missing fields" in error for error in errors), errors)
        self.assertIn("finding schema conditional_constraints must be a non-empty list", errors)

    def test_finding_schema_requires_observed_result_pair_and_defines_every_category(
        self,
    ) -> None:
        schema = json.loads(
            (REPO_ROOT / "runtime" / "finding_schema.json").read_text(
                encoding="utf-8"
            )
        )
        required = schema["required_report_fields"]
        for field in ("expected_result", "actual_result"):
            with self.subTest(required_field=field):
                self.assertIn(field, required)
                mutated = {
                    **schema,
                    "required_report_fields": [
                        item for item in required if item != field
                    ],
                }
                errors: list[str] = []
                framework_consistency.validate_finding_schema(mutated, errors)
                self.assertIn(
                    f"finding schema required_report_fields missing: {field}",
                    errors,
                )

        expected_categories = {
            "Bug",
            "Documentation",
            "Edge Case",
            "Performance",
            "Process",
            "Security",
            "Standards Violation",
            "Weakness",
        }
        self.assertEqual(expected_categories, set(schema["fields"]["category"]))
        for category in expected_categories:
            with self.subTest(missing_category=category):
                mutated = json.loads(json.dumps(schema))
                mutated["fields"]["category"].remove(category)
                errors = []
                framework_consistency.validate_finding_schema(mutated, errors)
                self.assertIn(
                    f"finding schema category missing values: {category}",
                    errors,
                )

        review = (REPO_ROOT / "task_orders" / "review.md").read_text(
            encoding="utf-8"
        )
        for category in expected_categories:
            with self.subTest(category=category):
                self.assertIn(f"   - {category} —", review)

    def test_generated_memory_boundary_never_uses_provenance_as_write_authority(
        self,
    ) -> None:
        import project_contract_model

        boundary = project_contract_model.DEFAULT_PERSISTENT_MEMORY_BOUNDARY
        for required_text in (
            "enabled project policy authorizes the write class",
            "current User request or confirmation",
            "independent validation under that policy",
            "Provenance is evidence only and never write authority",
        ):
            self.assertIn(required_text, boundary)
        self.assertNotIn("confirmation or verified provenance", boundary)

        agreement = (REPO_ROOT / "master_service_agreement.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"Memory Boundary: {boundary}", agreement)

        example = json.loads(
            (
                REPO_ROOT
                / "examples"
                / "project_bootstrap_answers.example.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(boundary, example["persistent_memory_boundary"])

        memory_guide = (
            REPO_ROOT / "practice_guides" / "prompt_injection_review.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Permit every persistent write only when", memory_guide)
        self.assertIn(
            "the current User requests or confirms the write or the claim is independently validated",
            memory_guide,
        )
        self.assertNotIn("unless an exact SOW grant", memory_guide)

        init_order = (REPO_ROOT / "task_orders" / "init.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Verified provenance is evidence only and never write authority.",
            init_order,
        )
        self.assertIn(
            "authorizes that write class and, in addition, either the current User",
            init_order,
        )

    def test_framework_consistency_rejects_invalid_finding_constraint_values(self) -> None:
        schema = json.loads((REPO_ROOT / "runtime" / "finding_schema.json").read_text(encoding="utf-8"))
        schema["conditional_constraints"] = [
            {"when": {"disposition": "Finding"}, "then": {"severity": ["Severe"]}}
        ]
        errors: list[str] = []

        framework_consistency.validate_finding_schema(schema, errors)

        self.assertTrue(
            any("constraint 0.then.severity uses unknown values: Severe" in error for error in errors),
            errors,
        )

    def test_framework_consistency_rejects_conflicting_finding_schema_constraints(self) -> None:
        schema = json.loads((REPO_ROOT / "runtime" / "finding_schema.json").read_text(encoding="utf-8"))
        schema["conditional_constraints"].append(
            {"when": {"disposition": "Finding"}, "then": {"severity": ["Not applicable"]}}
        )
        errors: list[str] = []

        framework_consistency.validate_finding_schema(schema, errors)

        self.assertTrue(
            any("duplicates condition" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("unsupported conditional constraint" in error for error in errors),
            errors,
        )
