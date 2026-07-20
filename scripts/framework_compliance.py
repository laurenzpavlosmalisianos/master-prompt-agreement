#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import conformance_check
import public_release_check
from public_release_check import ReleaseTreeRole
import recommend_stack
import safe_paths
import verification_plan
import verification_registry

COMMAND_TIMEOUT_SECONDS = conformance_check.COMMAND_TIMEOUT_SECONDS
EXPORTED_TREE_CHILD_TIMEOUTS = dict(
    conformance_check.EXPORTED_TREE_COMPLIANCE_CHILD_TIMEOUTS
)
UNIT_TEST_TIMEOUT_SECONDS = EXPORTED_TREE_CHILD_TIMEOUTS["unit-tests"]
COMMAND_MAX_OUTPUT_BYTES = conformance_check.MAX_COMMAND_OUTPUT_BYTES
PRIVATE_VALIDATION_BUDGET_SCHEMA_VERSION = 2
AUTHORING_WORKSPACE_HYGIENE_REPORT_SCHEMA_VERSION = 1
AUTHORING_WORKSPACE_HYGIENE_POLICY_MAX_BYTES = 64 * 1024
MAX_EXCEPTION_DIAGNOSTIC_CHARS = 512
PUBLICATION_UV_PROC_PATH_ENV = "MPA_RELEASE_UV_PROC_PATH"
PUBLICATION_UV_SHA256_ENV = "MPA_RELEASE_UV_SHA256"
BASEDPYRIGHT_VERSION = "1.39.9"
PUBLICATION_CHILD_UMASK = 0o022
PUBLICATION_NODE_OPTIONS = "--max-old-space-size=768"


@contextmanager
def _process_environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextmanager
def _process_umask(mask: int) -> Iterator[None]:
    """Apply one deterministic child-creation mask and restore the caller."""

    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@contextmanager
def _routine_child_environment() -> Iterator[None]:
    """Apply routine child bounds while leaving an operator heap choice last."""

    previous_bytecode = os.environ.get("PYTHONDONTWRITEBYTECODE")
    previous_node_options = os.environ.get("NODE_OPTIONS")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["NODE_OPTIONS"] = (
        f"{PUBLICATION_NODE_OPTIONS} {previous_node_options}"
        if previous_node_options
        else PUBLICATION_NODE_OPTIONS
    )
    try:
        yield
    finally:
        if previous_bytecode is None:
            os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
        else:
            os.environ["PYTHONDONTWRITEBYTECODE"] = previous_bytecode
        if previous_node_options is None:
            os.environ.pop("NODE_OPTIONS", None)
        else:
            os.environ["NODE_OPTIONS"] = previous_node_options


def exported_tree_child_timeout(label: str) -> float:
    """Return the registered allowance for one public-tree compliance child."""

    try:
        return EXPORTED_TREE_CHILD_TIMEOUTS[label]
    except KeyError as exc:
        raise ValueError(
            f"unregistered exported-tree compliance child: {label}"
        ) from exc


@dataclass(frozen=True)
class _CommandFailure:
    """Falsey command status that retains the original bounded diagnostic."""

    message: str

    def __bool__(self) -> bool:
        return False


@dataclass(frozen=True)
class _JSONShape:
    expected_type: type[Any]
    required_fields: tuple[tuple[str, _JSONShape], ...] = ()
    optional_fields: tuple[tuple[str, _JSONShape], ...] = ()
    item_shape: _JSONShape | None = None


def _object_shape(
    *required_fields: tuple[str, _JSONShape],
    optional_fields: tuple[tuple[str, _JSONShape], ...] = (),
) -> _JSONShape:
    return _JSONShape(
        dict,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )


_JSON_OBJECT = _JSONShape(dict)
_JSON_ARRAY = _JSONShape(list)
_JSON_STRING = _JSONShape(str)
_JSON_INTEGER = _JSONShape(int)
_JSON_BOOLEAN = _JSONShape(bool)
_JSON_STRING_ARRAY = _JSONShape(list, item_shape=_JSON_STRING)
_ERROR_REPORT_SHAPE = _object_shape(("errors", _JSON_ARRAY))
_DIAGNOSTIC_REPORT_SHAPE = _object_shape(
    ("errors", _JSON_ARRAY),
    ("warnings", _JSON_ARRAY),
)
_PRIVATE_REPORT_SHAPE = _object_shape(
    ("errors", _JSON_ARRAY),
    optional_fields=(
        ("self_test_errors", _JSON_ARRAY),
        ("maintenance_check_errors", _JSON_ARRAY),
    ),
)
_PRIVATE_BUDGET_CHECK_SHAPE = _object_shape(
    ("check_id", _JSON_STRING),
    ("timeout_seconds", _JSON_INTEGER),
)
_PRIVATE_BUDGET_REPORT_SHAPE = _object_shape(
    ("schema_version", _JSON_INTEGER),
    ("validation_timeout_seconds", _JSON_INTEGER),
    ("self_test_timeout_seconds", _JSON_INTEGER),
    ("checks", _JSONShape(list, item_shape=_PRIVATE_BUDGET_CHECK_SHAPE)),
    ("shutdown_margin_seconds", _JSON_INTEGER),
    ("minimum_outer_timeout_seconds", _JSON_INTEGER),
)
_DEEP_RESEARCH_REPORT_SHAPE = _object_shape(
    (
        "artifacts",
        _JSONShape(
            list,
            item_shape=_object_shape(("errors", _JSON_ARRAY)),
        ),
    ),
)
_PROMPT_LOAD_REPORT_SHAPE = _object_shape(
    ("eager_practice_guide_imports", _JSON_ARRAY),
    ("budget_errors", _JSON_ARRAY),
)
_PREREQUISITE_REPORT_SHAPE = _object_shape(("runner", _JSON_STRING))
_RECOMMEND_REPORT_SHAPE = _object_shape(
    ("schema_version", _JSON_INTEGER),
    ("standard_of_care", _JSON_STRING),
    ("evidentiary_scope", _JSON_STRING),
    ("practice_guides", _JSON_STRING_ARRAY),
    ("required_checks", _JSON_ARRAY),
)
_CONTEXT_MANIFEST_REPORT_SHAPE = _object_shape(
    ("task_module", _object_shape(("name", _JSON_STRING))),
    ("required_checks", _JSON_ARRAY),
)
_EVIDENCE_SCOPE_REPORT_SHAPE = _object_shape(
    ("recommended_scope", _JSON_STRING),
)
_VERIFICATION_REPORT_SHAPE = _object_shape(
    ("schema_version", _JSON_INTEGER),
    ("phase_checks", _JSON_OBJECT),
)
_AUTHORING_WORKSPACE_HYGIENE_ITEM_SHAPE = _object_shape(
    ("path", _JSON_STRING),
    ("reason_code", _JSON_STRING),
    ("reason", _JSON_STRING),
)
_AUTHORING_WORKSPACE_HYGIENE_REPORT_SHAPE = _object_shape(
    ("schema_version", _JSON_INTEGER),
    ("checked_entry_count", _JSON_INTEGER),
    ("stability_scan_count", _JSON_INTEGER),
    (
        "deletion_candidates",
        _JSONShape(list, item_shape=_AUTHORING_WORKSPACE_HYGIENE_ITEM_SHAPE),
    ),
    (
        "review_required",
        _JSONShape(list, item_shape=_AUTHORING_WORKSPACE_HYGIENE_ITEM_SHAPE),
    ),
    ("diagnostics_truncated", _JSON_BOOLEAN),
    ("omitted_diagnostic_count", _JSON_INTEGER),
    ("errors", _JSON_STRING_ARRAY),
    ("warnings", _JSON_STRING_ARRAY),
)
_AUTHORING_WORKSPACE_HYGIENE_REPORT_FIELDS = frozenset(
    field
    for field, _shape in _AUTHORING_WORKSPACE_HYGIENE_REPORT_SHAPE.required_fields
)
_AUTHORING_WORKSPACE_HYGIENE_ITEM_FIELDS = frozenset(
    field
    for field, _shape in _AUTHORING_WORKSPACE_HYGIENE_ITEM_SHAPE.required_fields
)


def _json_type_name(expected_type: type[Any]) -> str:
    return {
        dict: "object",
        list: "array",
        str: "string",
        int: "integer",
        bool: "boolean",
    }.get(expected_type, expected_type.__name__)


def _json_shape_error(
    value: object,
    shape: _JSONShape,
    *,
    location: str = "$",
) -> str | None:
    type_matches = (
        type(value) is int
        if shape.expected_type is int
        else isinstance(value, shape.expected_type)
    )
    if not type_matches:
        return (
            f"{location} must be a JSON {_json_type_name(shape.expected_type)}, "
            f"observed {type(value).__name__}"
        )
    if isinstance(value, dict):
        for field, field_shape in shape.required_fields:
            if field not in value:
                return f"{location}.{field} is required"
            error = _json_shape_error(
                value[field],
                field_shape,
                location=f"{location}.{field}",
            )
            if error is not None:
                return error
        for field, field_shape in shape.optional_fields:
            if field not in value:
                continue
            error = _json_shape_error(
                value[field],
                field_shape,
                location=f"{location}.{field}",
            )
            if error is not None:
                return error
    if isinstance(value, list) and shape.item_shape is not None:
        for index, item in enumerate(value):
            error = _json_shape_error(
                item,
                shape.item_shape,
                location=f"{location}[{index}]",
            )
            if error is not None:
                return error
    return None


def _json_contract_failure(
    report: object,
    label: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
    shape: _JSONShape,
) -> str | None:
    """Return one child-labeled protocol/shape failure, if any."""

    if not command_ok:
        return command_message
    shape_error = _json_shape_error(report, shape)
    if shape_error is None:
        return None
    return (
        f"{label}: FAIL\nchild JSON shape is incompatible with the "
        f"compliance contract: {shape_error}"
    )


def run(
    label: str,
    cmd: list[str],
    cwd: Path,
    *,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    max_output_bytes: int = COMMAND_MAX_OUTPUT_BYTES,
) -> tuple[bool, str, str]:
    ok, output = conformance_check.run_command(
        label,
        cmd,
        cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    if ok:
        return True, f"{label}: PASS", output
    return False, f"{label}: FAIL\n{output}", output


def run_json(
    label: str,
    cmd: list[str],
    cwd: Path,
    *,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    max_output_bytes: int = COMMAND_MAX_OUTPUT_BYTES,
) -> tuple[bool | _CommandFailure, Any | None, str]:
    capture = conformance_check.run_command_capture(
        label,
        cmd,
        cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    protocol_failures = conformance_check.structured_capture_failures(
        label,
        capture,
    )
    if capture.stdout_decode_failure is not None:
        failure = f"{label}: FAIL\n" + "\n".join(protocol_failures)
        return _CommandFailure(failure), None, failure
    try:
        data = safe_paths.loads_json_no_duplicates(capture.stdout)
    except ValueError as exc:
        details = list(protocol_failures)
        if not capture.ok and capture.transport_failure is None:
            details.append(f"{label} exited with {capture.returncode}")
        details.append(f"invalid JSON output on stdout: {exc}")
        if capture.stdout:
            details.append(capture.stdout)
        failure = f"{label}: FAIL\n" + "\n".join(details)
        return _CommandFailure(failure), None, failure
    if not capture.ok or protocol_failures:
        details = list(protocol_failures)
        if not capture.ok and capture.transport_failure is None:
            details.insert(0, f"{label} exited with {capture.returncode}")
        details.append(
            "structured report: "
            + json.dumps(
                data,
                sort_keys=True,
                allow_nan=False,
                ensure_ascii=False,
            )
        )
        message = f"{label}: FAIL\n" + "\n".join(details)
        return _CommandFailure(message), data, message
    return True, data, f"{label}: PASS"


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def assert_true(
    condition: bool | _CommandFailure,
    label: str,
    detail: str,
) -> tuple[bool, str]:
    if isinstance(condition, _CommandFailure):
        return False, condition.message
    if condition:
        return True, f"{label}: PASS"
    return False, f"{label}: FAIL\n{detail}"


def assert_command_result(
    condition: bool | _CommandFailure,
    label: str,
    detail: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
) -> tuple[bool, str]:
    """Preserve the command/JSON failure before applying semantic assertions."""

    if not command_ok:
        return False, command_message
    return assert_true(condition, label, detail)


def assert_json_result(
    report: Any | None,
    label: str,
    detail: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
    shape: _JSONShape,
    predicate: Callable[[Any], bool] = bool,
) -> tuple[bool, str]:
    """Validate a child JSON shape without losing command diagnostics."""

    contract_failure = _json_contract_failure(
        report,
        label,
        command_ok=command_ok,
        command_message=command_message,
        shape=shape,
    )
    if contract_failure is not None:
        return False, contract_failure
    try:
        condition = predicate(report)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        return (
            False,
            f"{label}: FAIL\nchild JSON shape is incompatible with the "
            f"compliance contract: {type(exc).__name__}: {exc}",
        )
    return assert_true(condition, label, detail)


def assert_clean_json_report(
    report: Any | None,
    label: str,
    detail: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
    require_no_warnings: bool = False,
) -> tuple[bool, str]:
    contract_failure = _json_contract_failure(
        report,
        label,
        command_ok=command_ok,
        command_message=command_message,
        shape=_DIAGNOSTIC_REPORT_SHAPE,
    )
    if contract_failure is not None:
        return False, contract_failure
    if not isinstance(report, dict):
        return False, f"{label}: FAIL\nchild report must be an object"

    errors = report["errors"]
    warnings = report["warnings"]
    if not isinstance(errors, list) or not isinstance(warnings, list):
        return False, f"{label}: FAIL\nchild diagnostic arrays are malformed"

    def rendered_items(field: str, items: list[object]) -> list[str]:
        rendered: list[str] = []
        for item in items:
            if isinstance(item, str):
                value = item
            else:
                try:
                    value = json.dumps(
                        item,
                        sort_keys=True,
                        allow_nan=False,
                        ensure_ascii=False,
                    )
                except (TypeError, ValueError):
                    value = f"<{type(item).__name__}>"
            rendered.append(f"reported {field}: {value}")
        return rendered

    diagnostic_lines = [
        *rendered_items("error", errors),
        *rendered_items("warning", warnings),
    ]
    if errors or (require_no_warnings and warnings):
        return (
            False,
            f"{label}: FAIL\n{detail}"
            + ("\n" + "\n".join(diagnostic_lines) if diagnostic_lines else ""),
        )
    if warnings:
        return (
            True,
            f"{label}: PASS\n" + "\n".join(diagnostic_lines),
        )
    return True, f"{label}: PASS"


def assert_clean_authoring_workspace_hygiene_report(
    report: Any | None,
    label: str,
    detail: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
) -> tuple[bool, str]:
    """Validate the exact final-hygiene protocol and its clean-state invariants."""

    contract_failure = _json_contract_failure(
        report,
        label,
        command_ok=command_ok,
        command_message=command_message,
        shape=_AUTHORING_WORKSPACE_HYGIENE_REPORT_SHAPE,
    )
    if contract_failure is not None:
        return False, contract_failure
    if not isinstance(report, dict):
        return False, f"{label}: FAIL\nchild report must be an object"

    observed_fields = set(report)
    if observed_fields != _AUTHORING_WORKSPACE_HYGIENE_REPORT_FIELDS:
        missing = sorted(
            _AUTHORING_WORKSPACE_HYGIENE_REPORT_FIELDS - observed_fields
        )
        unexpected = sorted(
            observed_fields - _AUTHORING_WORKSPACE_HYGIENE_REPORT_FIELDS
        )
        differences = [
            *(f"missing field: {field}" for field in missing),
            *(f"unexpected field: {field}" for field in unexpected),
        ]
        return (
            False,
            f"{label}: FAIL\nchild JSON shape is incompatible with the "
            "compliance contract: hygiene report fields must match exactly"
            + ("\n" + "\n".join(differences) if differences else ""),
        )

    for collection_name in ("deletion_candidates", "review_required"):
        collection = report[collection_name]
        if not isinstance(collection, list):
            return (
                False,
                f"{label}: FAIL\nchild JSON shape is incompatible with the "
                f"compliance contract: {collection_name} must be an array",
            )
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                return (
                    False,
                    f"{label}: FAIL\nchild JSON shape is incompatible with the "
                    f"compliance contract: {collection_name}[{index}] must be "
                    "an object",
                )
            observed_item_fields = set(item)
            if observed_item_fields != _AUTHORING_WORKSPACE_HYGIENE_ITEM_FIELDS:
                return (
                    False,
                    f"{label}: FAIL\nchild JSON shape is incompatible with the "
                    f"compliance contract: {collection_name}[{index}] fields "
                    "must match path, reason_code, and reason exactly",
                )

    failures: list[str] = []
    if report["schema_version"] != AUTHORING_WORKSPACE_HYGIENE_REPORT_SCHEMA_VERSION:
        failures.append(
            "unsupported hygiene report schema_version: "
            f"{report['schema_version']}"
        )
    checked_entry_count = report["checked_entry_count"]
    if checked_entry_count <= 0:
        failures.append("checked_entry_count must be positive for a clean report")
    stability_scan_count = report["stability_scan_count"]
    if stability_scan_count != 2:
        failures.append("stability_scan_count must equal 2 for a clean report")

    deletion_candidates = report["deletion_candidates"]
    review_required = report["review_required"]
    errors = report["errors"]
    warnings = report["warnings"]
    if deletion_candidates:
        failures.extend(
            "reported deletion candidate: "
            f"{item['path']} [{item['reason_code']}]"
            for item in deletion_candidates
        )
    if review_required:
        failures.extend(
            f"reported review item: {item['path']} [{item['reason_code']}]"
            for item in review_required
        )
    failures.extend(f"reported error: {item}" for item in errors)
    failures.extend(f"reported warning: {item}" for item in warnings)

    diagnostics_truncated = report["diagnostics_truncated"]
    omitted_diagnostic_count = report["omitted_diagnostic_count"]
    if omitted_diagnostic_count < 0:
        failures.append("omitted_diagnostic_count must not be negative")
    if diagnostics_truncated != (omitted_diagnostic_count > 0):
        failures.append(
            "diagnostics_truncated must equal whether omitted_diagnostic_count "
            "is positive"
        )
    if diagnostics_truncated:
        failures.append("clean hygiene evidence must not truncate diagnostics")
    if omitted_diagnostic_count:
        failures.append(
            "clean hygiene evidence must not omit diagnostic records: "
            f"{omitted_diagnostic_count} omitted"
        )

    if failures:
        return False, f"{label}: FAIL\n{detail}\n" + "\n".join(failures)
    return True, f"{label}: PASS"


def assert_clean_error_report(
    report: Any | None,
    label: str,
    detail: str,
    *,
    command_ok: bool | _CommandFailure,
    command_message: str,
) -> tuple[bool, str]:
    """Validate a child contract that intentionally exposes only errors."""

    return assert_json_result(
        report,
        label,
        detail,
        command_ok=command_ok,
        command_message=command_message,
        shape=_ERROR_REPORT_SHAPE,
        predicate=lambda value: not value["errors"],
    )


def tracked_regular_file(
    root: Path,
    relative_path: str,
    *,
    tracked_files: frozenset[str],
) -> Path | None:
    """Return one Git-tracked regular file without treating presence as authority."""

    if relative_path not in tracked_files:
        return None
    try:
        path = safe_paths.safe_relative_child(
            root,
            Path(relative_path),
            description="tracked optional validation entrypoint",
        )
    except ValueError:
        return None
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        return None
    return path


def safely_present_regular_file(root: Path, relative_path: str) -> bool:
    """Return whether one untrusted path is a single-link in-root regular file."""

    try:
        path = safe_paths.safe_relative_child(
            root,
            Path(relative_path),
            description="optional authoring-instance member",
        )
        metadata = path.lstat()
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def authoring_instance_members(
    root: Path,
    contract_root_ref: str,
    *,
    tracked_files: frozenset[str],
) -> tuple[str, ...]:
    """Return every safely present or tracked authoring identity member.

    Safe physical presence catches an untracked complete, partial, or malformed
    instance. Git tracking independently catches a deleted or unsafely replaced
    required member so the aggregate gate still fails closed.
    """

    candidates = (
        f"{contract_root_ref}/PROJECT_INPUT.json",
        "PROJECT_INSTANCE.json",
    )
    return tuple(
        relative_path
        for relative_path in candidates
        if safely_present_regular_file(root, relative_path)
        or relative_path in tracked_files
    )


def private_validation_entrypoint(
    root: Path,
    *,
    tracked_files: frozenset[str],
    authoring_surface_expected: bool,
) -> tuple[Path | None, str | None]:
    private_root_name = "private"
    private_root = root / private_root_name
    validator_rel = (private_root / "validate.py").relative_to(root).as_posix()
    validator = tracked_regular_file(
        root,
        validator_rel,
        tracked_files=tracked_files,
    )
    if authoring_surface_expected and validator is None:
        return (
            None,
            "authoring identity state requires a tracked, single-link regular "
            "private validation entrypoint with no symlink components",
        )
    return validator, None


def private_validation_result(
    ok: bool | _CommandFailure,
    report: Any | None,
    message: str,
) -> tuple[bool, str]:
    return assert_json_result(
        report,
        "private-authoring-validation",
        "expected maintained non-public files and their validation checks to pass",
        command_ok=ok,
        command_message=message,
        shape=_PRIVATE_REPORT_SHAPE,
        predicate=lambda value: (
            not value["errors"]
            and not value.get("self_test_errors", [])
            and not value.get("maintenance_check_errors", [])
        ),
    )


def authoring_core_conformance_result(
    outcome: object,
) -> tuple[bool, str]:
    """Render one strict structured authoring-conformance result.

    ``conformance_check.run_json_child`` already validates JSON shape, stream
    discipline, bounded transport, and the relationship between process status
    and reported diagnostics.  This adapter preserves those diagnostics as
    semantic evidence instead of replacing a coherent nonzero result with a
    generic command failure.
    """

    label = "authoring-core-conformance"
    detail = "expected the concrete authoring instance to pass core-project conformance"
    if not isinstance(outcome, conformance_check.CheckOutcome):
        return (
            False,
            f"{label}: FAIL\n{detail}\n"
            "protocol failure: structured conformance runner returned an "
            f"incompatible result: {type(outcome).__name__}",
        )

    errors = conformance_check.ordered_unique(outcome.errors)
    warnings = conformance_check.ordered_unique(outcome.warnings)
    lines = [
        *(f"reported error: {error}" for error in errors),
        *(f"reported warning: {warning}" for warning in warnings),
    ]
    if outcome.protocol_failure is not None:
        lines.append(f"protocol failure: {outcome.protocol_failure}")
    if errors or warnings or outcome.protocol_failure is not None:
        return False, f"{label}: FAIL\n{detail}\n" + "\n".join(lines)
    return True, f"{label}: PASS"


def run_authoring_core_conformance(
    python: str,
    repo_root: Path,
    contract_root_ref: str,
) -> tuple[bool, str]:
    """Run strict authoring conformance through the structured child protocol."""

    outcome = conformance_check.run_json_child(
        "authoring-core-conformance",
        [
            python,
            "scripts/conformance_check.py",
            "--profile",
            "core-project",
            "--root",
            str(repo_root),
            "--contract-root",
            contract_root_ref,
            "--project-kind",
            "framework-authoring",
            "--format",
            "json",
            "--strict-warnings",
        ],
        repo_root,
        timeout_seconds=conformance_check.CORE_PROJECT_AUTHORING_TIMEOUT_SECONDS,
        warnings_fail=True,
    )
    return authoring_core_conformance_result(outcome)


def private_validation_budget_result(
    ok: bool | _CommandFailure,
    report: Any | None,
    message: str,
) -> tuple[int | None, str | None]:
    """Validate the private registry's derived outer-timeout metadata."""

    label = "private-authoring-validation-budget"

    def fail(detail: str) -> tuple[None, str]:
        return None, f"{label}: FAIL\n{detail}"

    contract_failure = _json_contract_failure(
        report,
        label,
        command_ok=ok,
        command_message=message,
        shape=_PRIVATE_BUDGET_REPORT_SHAPE,
    )
    if contract_failure is not None:
        return None, contract_failure
    if not isinstance(report, dict):
        return fail("maintenance-budget metadata must be an object")
    expected_keys = {
        "schema_version",
        "validation_timeout_seconds",
        "self_test_timeout_seconds",
        "checks",
        "shutdown_margin_seconds",
        "minimum_outer_timeout_seconds",
    }
    if set(report) != expected_keys:
        return fail("maintenance-budget metadata has an incompatible top-level shape")
    if report["schema_version"] != PRIVATE_VALIDATION_BUDGET_SCHEMA_VERSION:
        return fail("maintenance-budget metadata has an unsupported schema version")

    checks = report["checks"]
    if not isinstance(checks, list) or not checks:
        return fail("maintenance-budget metadata must declare at least one child check")
    check_ids: list[str] = []
    child_budget = 0
    for index, item in enumerate(checks):
        if not isinstance(item, dict) or set(item) != {"check_id", "timeout_seconds"}:
            return fail(f"maintenance-budget check {index} has an incompatible shape")
        check_id = item["check_id"]
        timeout_seconds = item["timeout_seconds"]
        if not isinstance(check_id, str) or not check_id:
            return fail(f"maintenance-budget check {index} has an invalid check_id")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            return fail(
                f"maintenance-budget check {check_id!r} has an invalid timeout"
            )
        check_ids.append(check_id)
        child_budget += timeout_seconds
    if len(check_ids) != len(set(check_ids)):
        return fail("maintenance-budget metadata contains duplicate check IDs")

    validation_timeout = report["validation_timeout_seconds"]
    self_test_timeout = report["self_test_timeout_seconds"]
    shutdown_margin = report["shutdown_margin_seconds"]
    declared_minimum = report["minimum_outer_timeout_seconds"]
    for field_name, value in (
        ("validation_timeout_seconds", validation_timeout),
        ("self_test_timeout_seconds", self_test_timeout),
        ("shutdown_margin_seconds", shutdown_margin),
        ("minimum_outer_timeout_seconds", declared_minimum),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return fail(f"maintenance-budget {field_name} must be a positive integer")
    computed_minimum = (
        validation_timeout
        + self_test_timeout
        + child_budget
        + shutdown_margin
    )
    if declared_minimum != computed_minimum:
        return fail(
            "maintenance-budget minimum does not equal validation, self-test, "
            "child allowances, and shutdown margin: "
            f"{declared_minimum} != {computed_minimum}"
        )
    if declared_minimum > conformance_check.COMMAND_MAX_TIMEOUT_SECONDS:
        return fail(
            "maintenance-budget minimum exceeds the shared bounded-runner maximum: "
            f"{declared_minimum} > {conformance_check.COMMAND_MAX_TIMEOUT_SECONDS:g}"
        )
    return declared_minimum, None


def python_type_check_command() -> list[str]:
    targets = ["scripts", "tests"]
    basedpyright = shutil.which("basedpyright")
    if basedpyright:
        return [basedpyright, *targets]
    if shutil.which("uvx"):
        return ["uvx", "--offline", "basedpyright", *targets]
    return [
        sys.executable,
        "-c",
        (
            "raise SystemExit("
            "'basedpyright is required for python-type-check; install it or provide an offline uvx cache'"
            ")"
        ),
    ]


def _bound_basedpyright_command(
    uv: public_release_check.GitExecutableBinding,
    *arguments: str,
) -> list[str]:
    uv.require_current()
    return [
        uv.external_command, "--no-config", "tool", "run", "--offline",
        "--isolated", "--no-env-file", "--no-python-downloads",
        "--python", f"/proc/{os.getpid()}/exe",
        "--from", f"basedpyright=={BASEDPYRIGHT_VERSION}", "basedpyright",
        *arguments,
    ]


def run_bound_python_type_check(
    uv: public_release_check.GitExecutableBinding,
    *,
    repo_root: Path,
) -> _Check:
    version_ok, version_message, version_output = run(
        "basedpyright-version",
        _bound_basedpyright_command(uv, "--version"),
        repo_root,
        timeout_seconds=exported_tree_child_timeout("python-type-check"),
    )
    uv.require_current()
    expected = f"basedpyright {BASEDPYRIGHT_VERSION}"
    if not version_ok:
        return False, version_message
    version_lines = version_output.splitlines()
    if not version_lines or version_lines[0] != expected:
        reported = version_lines[0] if version_lines else ""
        return False, (
            "basedpyright-version: FAIL\n"
            f"expected tool-reported version {expected!r}, got {reported!r}"
        )
    ok, message, _output = run(
        "python-type-check",
        _bound_basedpyright_command(uv, "scripts", "tests"),
        repo_root,
        timeout_seconds=exported_tree_child_timeout("python-type-check"),
    )
    uv.require_current()
    if not ok:
        return False, message
    return True, f"{message}\ntool-reported version: {expected}"


def run_zero_skip_unittests(
    label: str,
    command: list[str],
    repo_root: Path,
    *,
    timeout_seconds: float = UNIT_TEST_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    ok, message, output = run(
        label,
        command,
        repo_root,
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        return ok, message
    ran_matches = list(
        re.finditer(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
    )
    if not ran_matches:
        return (
            False,
            f"{label}: FAIL\nunit-test output did not contain a parseable "
            "unittest execution count",
        )
    final_summary = ran_matches[-1]
    summary_tail = output[final_summary.end() :]
    skipped_match = re.search(r"\bskipped=(\d+)\b", summary_tail)
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    if skipped:
        return (
            False,
            f"{label}: FAIL\n{skipped} test(s) skipped; run the same suite in the approved "
            "isolation container because publication evidence must be zero-skip",
        )
    count = int(final_summary.group(1))
    if count < 1:
        return (
            False,
            f"{label}: FAIL\nunit-test discovery executed zero tests",
        )
    return True, f"{message}\n{count} tests completed with zero skips"


def reference_freshness_command(python: str) -> list[str]:
    return [
        python,
        "scripts/check_reference_freshness.py",
        "--include-non-reference-docs",
        "--audit-monitor-roots",
        "--warnings-as-errors",
        "--format",
        "json",
    ]


def deep_research_digest_paths(repo_root: Path) -> list[Path]:
    root = repo_root / "review_artifacts" / "source_deep_research"
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.md") if path.is_file())


def codex_automation_registry_path(repo_root: Path) -> Path | None:
    path = repo_root / "private" / "authoring" / "automation" / "codex_registry.json"
    return path if path.exists() else None


def nonpublic_link_check_command(python: str, repo_root: Path) -> list[str] | None:
    command = [python, "scripts/link_check.py", "--root", str(repo_root)]
    for dirname in (
        "captures",
        "generated",
        "packets",
        "raw_runs",
        "scratch",
        "screenshots",
        "session_logs",
        "source_dumps",
        "source_material",
        "tmp",
        "traces",
        "transcripts",
    ):
        command.extend(["--exclude-dir", dirname])
    included = False
    for root_name in ("private", "review_" + "artifacts"):
        if (repo_root / root_name).is_dir():
            command.extend(["--include", f"{root_name}/**/*.md", "--include-root-path", root_name])
            included = True
    return command if included else None


_Check = tuple[bool, str]


def _bounded_exception_detail(exc: Exception) -> str:
    detail = " ".join(str(exc).splitlines()).strip() or type(exc).__name__
    if len(detail) <= MAX_EXCEPTION_DIAGNOSTIC_CHARS:
        return detail
    return detail[: MAX_EXCEPTION_DIAGNOSTIC_CHARS - 1] + "…"


def _exception_check(label: str, context: str, exc: Exception) -> _Check:
    return (
        False,
        f"{label}: FAIL\n{context}: {type(exc).__name__}: "
        f"{_bounded_exception_detail(exc)}",
    )


def _invoke_check_safely(
    label: str,
    operation: Callable[[], _Check],
) -> _Check:
    try:
        result = operation()
    except Exception as exc:
        return _exception_check(label, "compliance check raised", exc)
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or type(result[0]) is not bool
        or not isinstance(result[1], str)
    ):
        return (
            False,
            f"{label}: FAIL\ncompliance check returned an incompatible result shape",
        )
    return result


def _collect_foundation_checks(
    python: str,
    repo_root: Path,
    tree_role: ReleaseTreeRole,
    *,
    uv_executable: public_release_check.GitExecutableBinding | None = None,
) -> list[_Check]:
    if not isinstance(tree_role, ReleaseTreeRole):
        raise TypeError("tree_role must be a ReleaseTreeRole")
    script_paths = sorted(
        str(path.relative_to(repo_root))
        for path in (repo_root / "scripts").glob("*.py")
    )
    checks: list[_Check] = []
    checks.append(
        run(
            "py-compile",
            [
                python,
                "-B",
                "-c",
                (
                    "from pathlib import Path\n"
                    "import sys\n"
                    "root = Path('.').resolve()\n"
                    "for rel in sys.argv[1:]:\n"
                    "    path = root / rel\n"
                    "    compile(path.read_text(encoding='utf-8'), str(path), 'exec')\n"
                ),
                *script_paths,
            ],
            repo_root,
            timeout_seconds=exported_tree_child_timeout("py-compile"),
        )[:2]
    )
    checks.append(
        run_zero_skip_unittests(
            "unit-tests",
            [python, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            repo_root,
            timeout_seconds=exported_tree_child_timeout("unit-tests"),
        )
    )
    checks.append(
        run(
            "python-type-check",
            python_type_check_command(),
            repo_root,
            timeout_seconds=exported_tree_child_timeout("python-type-check"),
        )[:2]
        if uv_executable is None
        else run_bound_python_type_check(uv_executable, repo_root=repo_root)
    )
    ok, framework_quality, message = run_json(
        "framework-quality-lint",
        [python, "scripts/framework_quality_lint.py", "--format", "json"],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("framework-quality-lint"),
    )
    checks.append(
        assert_clean_error_report(
            framework_quality,
            "framework-quality-lint",
            "expected structural framework-quality guardrails to pass",
            command_ok=ok,
            command_message=message,
        )
    )
    checks.append(
        run(
            "lint-reviewer-lane-feedback",
            [
                python,
                "scripts/lint_reviewer_lane_feedback.py",
                "--path",
                "project_state_templates/REVIEWER_LANE_FEEDBACK.md",
                "--root",
                str(repo_root),
            ],
            repo_root,
            timeout_seconds=exported_tree_child_timeout(
                "lint-reviewer-lane-feedback"
            ),
        )[:2]
    )
    ok, freshness, message = run_json(
        "check-reference-freshness",
        reference_freshness_command(python),
        repo_root,
        timeout_seconds=exported_tree_child_timeout(
            "check-reference-freshness"
        ),
    )
    checks.append(
        assert_clean_json_report(
            freshness,
            "check-reference-freshness",
            "expected no source-freshness errors or warnings in framework compliance",
            command_ok=ok,
            command_message=message,
            require_no_warnings=True,
        )
    )
    if tree_role is ReleaseTreeRole.AUTHORING_SOURCE:
        conformance_profile = "framework-authoring-release"
        conformance_timeout = (
            conformance_check.AUTHORING_FRAMEWORK_CONFORMANCE_TIMEOUT_SECONDS
        )
    else:
        conformance_profile = "framework-public-release"
        conformance_timeout = exported_tree_child_timeout(
            "conformance-framework-public-release"
        )
    conformance_label = f"conformance-{conformance_profile}"
    conformance_command = [
        python,
        "scripts/conformance_check.py",
        "--profile",
        conformance_profile,
        "--format",
        "json",
        "--strict-warnings",
    ]
    ok, conformance_report, message = run_json(
        conformance_label,
        conformance_command,
        repo_root,
        timeout_seconds=conformance_timeout,
    )
    checks.append(
        assert_clean_json_report(
            conformance_report,
            conformance_label,
            f"expected {conformance_profile} conformance profile to pass",
            command_ok=ok,
            command_message=message,
            require_no_warnings=True,
        )
    )
    ok, link_report, message = run_json(
        "link-check",
        [python, "scripts/link_check.py", "--root", str(repo_root)],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("link-check"),
    )
    checks.append(
        assert_clean_json_report(
            link_report,
            "link-check",
            "expected no broken local Markdown links",
            command_ok=ok,
            command_message=message,
        )
    )
    nonpublic_link_command = (
        nonpublic_link_check_command(python, repo_root)
        if tree_role is ReleaseTreeRole.AUTHORING_SOURCE
        else None
    )
    if nonpublic_link_command is not None:
        ok, nonpublic_link_report, message = run_json(
            "nonpublic-link-check",
            nonpublic_link_command,
            repo_root,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        )
        checks.append(
            assert_clean_json_report(
                nonpublic_link_report,
                "nonpublic-link-check",
                "expected no broken local Markdown links in maintained non-public surfaces",
                command_ok=ok,
                command_message=message,
            )
        )
    return checks


def _collect_private_authoring_checks(
    python: str,
    repo_root: Path,
    *,
    git_executable: public_release_check.GitExecutableBinding | None = None,
) -> list[_Check]:
    checks: list[_Check] = []
    private_root_name = "private"
    private_root = repo_root / private_root_name
    tracked_files: frozenset[str] | None

    def git_tracked() -> set[str] | None:
        if git_executable is not None:
            git_executable.require_current()
        result = public_release_check.git_tracked_files(
            repo_root,
            git_executable=git_executable,
        )
        if git_executable is not None:
            git_executable.require_current()
        return result

    try:
        raw_tracked_files = git_tracked()
    except RuntimeError as exc:
        tracked_files = None
        checks.append(
            (
                False,
                "private-authoring-git-inventory: FAIL\n"
                f"could not obtain a sanitized root-bound Git inventory: {exc}",
            )
        )
    else:
        if raw_tracked_files is None:
            tracked_files = None
            checks.append(
                (
                    False,
                    "private-authoring-git-inventory: FAIL\n"
                    "authoring-source compliance requires a usable Git-tracked inventory",
                )
            )
        else:
            tracked_files = frozenset(raw_tracked_files)

    authoring_contract_ref = f"{private_root_name}/authoring"
    authoring_members = (
        authoring_instance_members(
            repo_root,
            authoring_contract_ref,
            tracked_files=tracked_files,
        )
        if tracked_files is not None
        else ()
    )
    private_validator: Path | None = None
    private_entrypoint_error: str | None = None
    if tracked_files is not None:
        private_validator, private_entrypoint_error = private_validation_entrypoint(
            repo_root,
            tracked_files=tracked_files,
            authoring_surface_expected=bool(authoring_members),
        )
    if private_entrypoint_error is not None:
        checks.append(
            (
                False,
                f"private-authoring-validation: FAIL\n{private_entrypoint_error}",
            )
        )
    elif private_validator is not None:
        budget_ok, budget_report, budget_message = run_json(
            "private-authoring-validation-budget",
            [
                python,
                str(private_validator),
                "--root",
                str(repo_root),
                "--describe-maintenance-budget",
            ],
            repo_root,
        )
        private_timeout, budget_error = private_validation_budget_result(
            budget_ok,
            budget_report,
            budget_message,
        )
        if budget_error is not None or private_timeout is None:
            checks.append(
                (False, budget_error or "private maintenance budget is missing")
            )
        else:
            ok, private_report, message = run_json(
                "private-authoring-validation",
                [
                    python,
                    str(private_validator),
                    "--root",
                    str(repo_root),
                    "--self-test",
                    "--outer-timeout-seconds",
                    str(private_timeout),
                ],
                repo_root,
                timeout_seconds=private_timeout,
            )
            checks.append(
                private_validation_result(
                    ok,
                    private_report,
                    message,
                )
            )

    if authoring_members:
        checks.append(
            run_authoring_core_conformance(
                python,
                repo_root,
                authoring_contract_ref,
            )
        )
    deep_research_digests = deep_research_digest_paths(repo_root)
    if deep_research_digests:
        ok, deep_research_lint, message = run_json(
            "source-deep-research-lint",
            [python, "scripts/source_deep_research_lint.py", *[str(path) for path in deep_research_digests]],
            repo_root,
        )
        checks.append(
            assert_json_result(
                deep_research_lint,
                "source-deep-research-lint",
                "expected browser Deep Research digests to record completion, extraction, and verification evidence",
                command_ok=ok,
                command_message=message,
                shape=_DEEP_RESEARCH_REPORT_SHAPE,
                predicate=lambda value: all(
                    not artifact["errors"] for artifact in value["artifacts"]
                ),
            )
        )

    codex_automation_registry = codex_automation_registry_path(repo_root)
    if codex_automation_registry is not None:
        ok, automation_registry_lint, message = run_json(
            "codex-automation-registry-lint",
            [
                python,
                "scripts/codex_automation_registry_lint.py",
                str(codex_automation_registry),
                "--root",
                str(repo_root),
            ],
            repo_root,
        )
        checks.append(
            assert_clean_error_report(
                automation_registry_lint,
                "codex-automation-registry-lint",
                "expected portable Codex automation registry to lint without errors",
                command_ok=ok,
                command_message=message,
            )
        )
    if tracked_files is not None:
        try:
            final_raw_tracked_files = git_tracked()
        except RuntimeError as exc:
            checks.append(
                (
                    False,
                    "private-authoring-git-inventory-stability: FAIL\n"
                    "could not confirm the final sanitized root-bound Git "
                    f"inventory: {exc}",
                )
            )
        else:
            if final_raw_tracked_files is None:
                checks.append(
                    (
                        False,
                        "private-authoring-git-inventory-stability: FAIL\n"
                        "final authoring-source compliance requires a usable "
                        "Git-tracked inventory",
                    )
                )
            elif frozenset(final_raw_tracked_files) != tracked_files:
                checks.append(
                    (
                        False,
                        "private-authoring-git-inventory-stability: FAIL\n"
                        "Git-tracked inventory changed while private authoring "
                        "checks were running",
                    )
                )
    return checks


def _authoring_workspace_hygiene_refs() -> tuple[str, str]:
    checker_ref = "/".join(("scripts", "authoring_workspace_hygiene.py"))
    nonpublic_root_name = "private"
    authoring_root_ref = "/".join((nonpublic_root_name, "authoring"))
    policy_ref = "/".join((authoring_root_ref, "release", "workspace_hygiene.json"))
    return checker_ref, policy_ref


def _read_authoring_workspace_hygiene_inputs(
    checker_path: Path,
    policy_path: Path,
) -> tuple[bytes, bytes]:
    """Bind the exact checker and private policy bytes through safe reads."""

    checker_bytes = safe_paths.read_regular_file_bytes(
        checker_path,
        description="tracked authoring workspace hygiene checker",
        max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
    )
    policy_bytes = safe_paths.read_regular_file_bytes(
        policy_path,
        description="tracked authoring workspace hygiene policy",
        max_bytes=AUTHORING_WORKSPACE_HYGIENE_POLICY_MAX_BYTES,
    )
    return checker_bytes, policy_bytes


def _collect_authoring_workspace_hygiene_checks(
    python: str,
    repo_root: Path,
    *,
    git_executable: public_release_check.GitExecutableBinding | None = None,
) -> list[_Check]:
    """Run the final report-only physical authoring-workspace invariant."""

    checks: list[_Check] = []

    def git_tracked() -> set[str] | None:
        if git_executable is not None:
            git_executable.require_current()
        result = public_release_check.git_tracked_files(
            repo_root,
            git_executable=git_executable,
        )
        if git_executable is not None:
            git_executable.require_current()
        return result

    try:
        initial_raw = git_tracked()
    except RuntimeError as exc:
        return [
            (
                False,
                "authoring-workspace-hygiene-git-inventory: FAIL\n"
                f"could not obtain a sanitized root-bound Git inventory: {exc}",
            )
        ]
    if initial_raw is None:
        return [
            (
                False,
                "authoring-workspace-hygiene-git-inventory: FAIL\n"
                "final authoring hygiene requires a usable Git-tracked inventory",
            )
        ]
    initial = frozenset(initial_raw)
    checker_ref, policy_ref = _authoring_workspace_hygiene_refs()
    checker_path = tracked_regular_file(
        repo_root,
        checker_ref,
        tracked_files=initial,
    )
    policy_path = tracked_regular_file(
        repo_root,
        policy_ref,
        tracked_files=initial,
    )
    invalid_required = [
        ref
        for ref, path in (
            (checker_ref, checker_path),
            (policy_ref, policy_path),
        )
        if path is None
    ]
    if invalid_required:
        checks.append(
            (
                False,
                "authoring-workspace-hygiene-entrypoints: FAIL\n"
                "required hygiene mechanism or policy is not a tracked, single-link "
                "regular file: "
                + ", ".join(invalid_required),
            )
        )
    elif checker_path is not None and policy_path is not None:
        try:
            initial_checker_bytes, initial_policy_bytes = (
                _read_authoring_workspace_hygiene_inputs(
                    checker_path,
                    policy_path,
                )
            )
        except Exception as exc:
            checks.append(
                (
                    False,
                    "authoring-workspace-hygiene-input-binding: FAIL\n"
                    "could not bind the tracked checker and policy bytes before "
                    "execution: "
                    f"{type(exc).__name__}: {_bounded_exception_detail(exc)}",
                )
            )
        else:
            try:
                ok, report, message = run_json(
                    "authoring-workspace-hygiene",
                    [
                        python,
                        "-B",
                        str(checker_path),
                        "--root",
                        str(repo_root),
                        "--policy",
                        policy_ref,
                        "--format",
                        "json",
                    ],
                    repo_root,
                )
            except Exception as exc:
                checks.append(
                    _exception_check(
                        "authoring-workspace-hygiene",
                        "fresh checker child could not complete",
                        exc,
                    )
                )
            else:
                checks.append(
                    assert_clean_authoring_workspace_hygiene_report(
                        report,
                        "authoring-workspace-hygiene",
                        "expected an exact, complete report with no unclassified "
                        "entries, disposable residue, physical workspace anomalies, "
                        "warnings, or omitted diagnostics",
                        command_ok=ok,
                        command_message=message,
                    )
                )

            try:
                final_checker_bytes, final_policy_bytes = (
                    _read_authoring_workspace_hygiene_inputs(
                        checker_path,
                        policy_path,
                    )
                )
            except Exception as exc:
                checks.append(
                    (
                        False,
                        "authoring-workspace-hygiene-input-stability: FAIL\n"
                        "could not revalidate the tracked checker and policy bytes "
                        "after execution: "
                        f"{type(exc).__name__}: {_bounded_exception_detail(exc)}",
                    )
                )
            else:
                changed_inputs = [
                    ref
                    for ref, initial_bytes, final_bytes in (
                        (
                            checker_ref,
                            initial_checker_bytes,
                            final_checker_bytes,
                        ),
                        (
                            policy_ref,
                            initial_policy_bytes,
                            final_policy_bytes,
                        ),
                    )
                    if initial_bytes != final_bytes
                ]
                checks.append(
                    assert_true(
                        not changed_inputs,
                        "authoring-workspace-hygiene-input-stability",
                        "tracked hygiene input bytes changed during the fresh "
                        "checker run: "
                        + ", ".join(changed_inputs),
                    )
                )

    try:
        final_raw = git_tracked()
    except RuntimeError as exc:
        checks.append(
            (
                False,
                "authoring-workspace-hygiene-git-inventory-stability: FAIL\n"
                f"could not revalidate the final Git inventory: {exc}",
            )
        )
    else:
        if final_raw is None:
            checks.append(
                (
                    False,
                    "authoring-workspace-hygiene-git-inventory-stability: FAIL\n"
                    "final authoring hygiene requires a usable Git-tracked inventory",
                )
            )
        elif frozenset(final_raw) != initial:
            checks.append(
                (
                    False,
                    "authoring-workspace-hygiene-git-inventory-stability: FAIL\n"
                    "Git-tracked inventory changed during the final physical hygiene check",
                )
            )
    return checks


@dataclass(frozen=True)
class _RouteCase:
    label: str
    flags: tuple[str, ...]
    standard_of_care: str
    evidentiary_scope: str
    practice_guides: tuple[str, ...]
    required_check_ids: tuple[str, ...] = ()
    forbidden_check_ids: tuple[str, ...] = ()


def _route_case(
    label: str,
    flags: tuple[str, ...],
    standard_of_care: str,
    evidentiary_scope: str,
    practice_guides: tuple[str, ...],
    required_check_ids: tuple[str, ...] = (),
    *,
    forbidden_check_ids: tuple[str, ...] = (),
) -> _RouteCase:
    return _RouteCase(
        label=label,
        flags=tuple(f"--{flag.replace('_', '-')}" for flag in flags),
        standard_of_care=standard_of_care,
        evidentiary_scope=evidentiary_scope,
        practice_guides=practice_guides,
        required_check_ids=required_check_ids,
        forbidden_check_ids=forbidden_check_ids,
    )


ROUTE_CASES: tuple[_RouteCase, ...] = (
    _route_case("default", (), "standard", "touched-files", ()),
    _route_case(
        "planning",
        ("planning", "multi_file"),
        "careful",
        "touched-files",
        ("task_contract", "implementation_planning"),
        ("planning.acceptance-before-edit", "planning.targeted-verification"),
        forbidden_check_ids=("change.targeted-regression",),
    ),
    _route_case(
        "scheduled",
        ("scheduled",),
        "careful",
        "touched-files",
        ("scheduled_automation",),
        (
            "automation.failure-escalation",
            "automation.idempotency-lock",
            "automation.observe-before-act",
        ),
    ),
    _route_case(
        "debugging",
        ("debugging",),
        "careful",
        "touched-files",
        ("root_cause_investigation",),
        (
            "debug.capture-symptom",
            "analysis.competing-hypotheses",
            "state.recurring-pattern-record",
        ),
    ),
    _route_case(
        "current-info",
        ("current_info",),
        "careful",
        "touched-files",
        ("source_grounded_research",),
        ("sources.current-primary",),
    ),
    _route_case(
        "source-refresh-review",
        ("source_refresh", "review"),
        "careful",
        "touched-files",
        ("change_impact_review", "source_freshness_review"),
        (
            "sources.current-primary",
            "sources.delta-hypotheses",
            "sources.freshness-gaps",
            "change.invariant-consumers",
        ),
    ),
    _route_case(
        "logic-review",
        ("logic_review",),
        "careful",
        "touched-files",
        ("logical_spec_review",),
        ("logic.consistency-case-coverage",),
    ),
    _route_case(
        "testing-strategy",
        ("testing_strategy",),
        "careful",
        "touched-files",
        ("testing_strategy_quality",),
        (
            "testing.behavior-oracle-portfolio",
            "testing.assertions-negative-isolation",
        ),
    ),
    _route_case(
        "data-systems",
        ("data_systems",),
        "careful",
        "touched-files",
        ("data_systems_review",),
        (
            "data.model-workload-invariants",
            "data.tradeoffs",
            "data.failure-modes",
        ),
    ),
    _route_case(
        "api-contract",
        ("api_contract_security",),
        "adversarial",
        "trust-boundary",
        ("api_contract_security",),
        (
            "api.contract-boundary",
            "api.validation-authorization",
            "review.independent-pass",
        ),
    ),
    _route_case(
        "privacy-data",
        ("privacy_data_handling",),
        "adversarial",
        "trust-boundary",
        ("privacy_data_handling",),
        ("privacy.classify-boundary", "privacy.handling-lifecycle"),
    ),
    _route_case(
        "delegated-communication-coverage",
        ("delegated_communication_coverage",),
        "adversarial",
        "trust-boundary",
        (
            "privacy_data_handling",
            "delegated_communication_coverage",
            "prompt_injection_review",
        ),
        (
            "privacy.classify-boundary",
            "privacy.handling-lifecycle",
            "communications.grant-activation-boundary",
            "communications.disclosure-effect-gate",
            "communications.expiry-revocation-audit-loop",
            "input.untrusted-data",
        ),
    ),
    _route_case(
        "container-image",
        ("container_image_security",),
        "adversarial",
        "trust-boundary",
        ("container_image_security",),
        ("container.image-boundary", "container.image-verification"),
    ),
    _route_case(
        "build-pipeline",
        ("build_pipeline_integrity",),
        "adversarial",
        "trust-boundary",
        ("build_pipeline_integrity",),
        ("pipeline.boundary", "pipeline.integrity-verification"),
    ),
    _route_case(
        "database",
        ("database_security",),
        "adversarial",
        "trust-boundary",
        ("backend_database_security",),
        ("database.boundary", "database.security-verification"),
    ),
    _route_case(
        "platform",
        ("platform_architecture",),
        "careful",
        "touched-files",
        ("platform_architecture_review",),
        ("platform.boundary", "platform.tradeoffs", "platform.failure-modes"),
    ),
    _route_case(
        "infrastructure-as-code",
        ("infrastructure_as_code",),
        "adversarial",
        "trust-boundary",
        ("infrastructure_as_code_review",),
        ("iac.boundary", "iac.verification"),
    ),
    _route_case(
        "prompt-agent",
        ("prompt_agent_quality",),
        "careful",
        "touched-files",
        ("prompt_agent_quality",),
        (
            "agent.current-sources",
            "agent.acceptance-evals",
            "agent.tool-memory-verifier-boundaries",
            "agent.runtime-goal-contract",
        ),
    ),
    _route_case(
        "source-originality",
        ("source_originality",),
        "careful",
        "touched-files",
        ("source_originality_review",),
        (
            "originality.behavior-contract",
            "originality.license-provenance",
            "originality.fingerprint-scan",
        ),
    ),
    _route_case(
        "dependency-change",
        ("dependency_change",),
        "careful",
        "touched-files",
        ("source_originality_review", "dependency_risk"),
        ("originality.license-provenance", "change.targeted-regression"),
    ),
    _route_case(
        "secure-development",
        ("secure_development",),
        "adversarial",
        "trust-boundary",
        ("secure_development",),
        (
            "secure-development.asset-boundaries",
            "secure-development.verification-profile",
            "secure-development.tool-output-triage",
        ),
    ),
    _route_case(
        "security-audit",
        ("security",),
        "adversarial",
        "trust-boundary",
        ("security_audit",),
    ),
    _route_case(
        "frontend",
        ("frontend_quality", "user_facing"),
        "careful",
        "touched-files",
        (
            "visual_verification",
            "website_frontend_quality",
            "html_quality",
            "css_quality",
        ),
        (
            "language.current-sources",
            "html.source-contract",
            "html.semantic-accessibility",
            "html.validator-triage",
            "css.support-layout-fallback",
            "visual.baseline",
            "visual.viewports",
            "visual.html-warning-triage",
            "visual.generated-assets-review",
            "frontend.layout-contracts",
            "frontend.source-ownership",
            "frontend.evidence-triangulation",
            "frontend.narrative-paths",
            "frontend.user-journeys",
        ),
        forbidden_check_ids=(
            "originality.behavior-contract",
            "originality.license-provenance",
            "originality.fingerprint-scan",
        ),
    ),
    _route_case(
        "visual",
        ("visual", "user_facing"),
        "careful",
        "touched-files",
        ("visual_verification",),
        (
            "visual.baseline",
            "visual.viewports",
            "visual.html-warning-triage",
            "visual.generated-assets-review",
        ),
    ),
    _route_case(
        "video-creation",
        ("video_creation_quality",),
        "careful",
        "touched-files",
        ("video_creation_quality",),
        (
            "video.brief-delivery-contract",
            "video.rights-accessibility-plan",
            "video.temporal-technical-playback",
        ),
    ),
    _route_case(
        "html",
        ("html_quality", "user_facing"),
        "careful",
        "touched-files",
        ("html_quality",),
        (
            "html.source-contract",
            "html.semantic-accessibility",
            "html.validator-triage",
        ),
    ),
    _route_case(
        "css",
        ("css_quality",),
        "careful",
        "touched-files",
        ("css_quality",),
        ("language.current-sources", "css.support-layout-fallback"),
    ),
    _route_case(
        "javascript",
        ("javascript_quality",),
        "careful",
        "touched-files",
        ("javascript_coding_quality",),
        ("language.current-sources", "javascript.runtime-contract"),
    ),
    _route_case(
        "swift",
        ("swift_quality",),
        "careful",
        "touched-files",
        ("swift_coding_quality",),
        ("language.current-sources", "language.build-type-lint-test"),
    ),
    _route_case(
        "rust",
        ("rust_quality",),
        "careful",
        "touched-files",
        ("rust_coding_quality",),
        ("language.current-sources", "language.build-type-lint-test"),
    ),
    _route_case(
        "typescript",
        ("typescript_quality",),
        "careful",
        "touched-files",
        ("typescript_coding_quality",),
        ("language.current-sources", "language.build-type-lint-test"),
    ),
    _route_case(
        "python",
        ("python_quality",),
        "careful",
        "touched-files",
        ("python_coding_quality",),
        ("language.current-sources", "language.build-type-lint-test"),
    ),
    _route_case(
        "go",
        ("go_quality",),
        "careful",
        "touched-files",
        ("go_coding_quality",),
        ("language.current-sources", "language.build-type-lint-test"),
    ),
    _route_case(
        "shell-cli",
        ("shell_cli_quality",),
        "careful",
        "touched-files",
        ("shell_cli_coding_quality",),
        ("language.current-sources", "shell.contract"),
    ),
    _route_case(
        "sql",
        ("sql_quality",),
        "careful",
        "touched-files",
        ("sql_query_quality",),
        ("language.current-sources", "sql.contract"),
    ),
    _route_case(
        "kubernetes",
        ("kubernetes_quality",),
        "careful",
        "touched-files",
        ("kubernetes_workload_review",),
        (
            "kubernetes.target-assumptions",
            "kubernetes.rendered-verification",
        ),
    ),
    _route_case(
        "apple-container",
        ("apple_container_workflow",),
        "careful",
        "touched-files",
        ("apple_container_workflow",),
        (
            "apple-container.runtime-assumptions",
            "apple-container.boundary-cleanup",
        ),
        forbidden_check_ids=("apple-container.image-assumptions",),
    ),
    _route_case(
        "apple-container-image",
        ("apple_container_workflow", "container_image_security"),
        "adversarial",
        "trust-boundary",
        ("container_image_security", "apple_container_workflow"),
        ("apple-container.image-assumptions",),
    ),
    _route_case(
        "seo",
        ("seo",),
        "careful",
        "touched-files",
        ("seo",),
        (
            "seo.current-surface-rules",
            "seo.technical-inspection",
            "seo.baseline-followup",
        ),
    ),
    _route_case(
        "knowledge-transfer",
        ("knowledge_transfer",),
        "careful",
        "touched-files",
        ("knowledge_transfer",),
        (
            "knowledge.scope-depth-evidence",
            "knowledge.grounding",
            "knowledge.optional-comprehension",
        ),
    ),
    _route_case(
        "scholarly-writing",
        ("scholarly_writing",),
        "careful",
        "touched-files",
        ("scholarly_writing",),
        (
            "scholarly.style-guide",
            "scholarly.citation-locators",
            "scholarly.terminology-metadata",
            "scholarly.typography",
        ),
    ),
    _route_case(
        "migration-release",
        ("migration", "release", "multi_file"),
        "careful",
        "touched-files",
        ("task_contract", "migration_safety", "release_readiness"),
        (
            "change.baseline-before-risk",
            "change.targeted-regression",
            "change.invariant-consumers",
            "change.rollback-containment",
        ),
    ),
    _route_case(
        "audit",
        ("audit",),
        "careful",
        "touched-files",
        ("change_impact_review",),
        (
            "review.tool-output-classification",
            "analysis.competing-hypotheses",
            "change.invariant-consumers",
            "state.recurring-pattern-record",
        ),
        forbidden_check_ids=("review.independent-pass",),
    ),
    _route_case(
        "external-privileged-effect",
        ("external_effect", "privileged_effect"),
        "adversarial",
        "trust-boundary",
        (),
        ("effects.authorization-boundary",),
    ),
    _route_case(
        "untrusted-agentic",
        ("untrusted_input", "agentic"),
        "adversarial",
        "trust-boundary",
        ("prompt_injection_review",),
        ("input.untrusted-data", "state.persistent-write-review"),
    ),
    _route_case(
        "incident",
        ("incident", "secret_exposure", "untrusted_input"),
        "forensic",
        "repo-slice",
        ("prompt_injection_review", "incident_response"),
        ("state.persistent-write-review", "state.recurring-pattern-record"),
        forbidden_check_ids=(),
    ),
    _route_case(
        "briefing",
        ("briefing",),
        "careful",
        "touched-files",
        ("decision_brief",),
    ),
)


def _selected_route(
    case: _RouteCase,
    schedule: dict[str, Any],
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    args = recommend_stack.build_parser().parse_args(list(case.flags))
    care = recommend_stack.choose_standard_of_care(args)
    scope = recommend_stack.choose_evidentiary_scope(args, care, schedule)
    guides = tuple(recommend_stack.collect_practice_guides(args, schedule))
    check_ids = tuple(
        check.check_id
        for check in recommend_stack.collect_required_checks(args, care, schedule)
    )
    return care, scope, guides, check_ids


def _route_case_check(
    case: _RouteCase,
    schedule: dict[str, Any],
) -> _Check:
    care, scope, guides, check_ids = _selected_route(case, schedule)
    selected = set(check_ids)
    missing = sorted(set(case.required_check_ids) - selected)
    forbidden = sorted(set(case.forbidden_check_ids) & selected)
    failures: list[str] = []
    if care != case.standard_of_care:
        failures.append(
            f"standard_of_care expected {case.standard_of_care!r}, observed {care!r}"
        )
    if scope != case.evidentiary_scope:
        failures.append(
            f"evidentiary_scope expected {case.evidentiary_scope!r}, observed {scope!r}"
        )
    if guides != case.practice_guides:
        failures.append(
            f"practice_guides expected {list(case.practice_guides)!r}, "
            f"observed {list(guides)!r}"
        )
    if missing:
        failures.append(f"missing check IDs: {', '.join(missing)}")
    if forbidden:
        failures.append(f"forbidden check IDs selected: {', '.join(forbidden)}")
    return assert_true(
        not failures,
        f"routing-case-{case.label}",
        "\n".join(failures),
    )


def _route_table_coverage_check(schedule: dict[str, Any]) -> _Check:
    registered_active = {
        check.check_id
        for check in verification_registry.CHECKS
        if check.activation
    }
    covered_checks = {
        check_id for case in ROUTE_CASES for check_id in case.required_check_ids
    }
    known_guides = {
        guide["name"]
        for guide in schedule["practice_guides"]
        if guide.get("trigger_flags")
    }
    covered_guides = {
        guide for case in ROUTE_CASES for guide in case.practice_guides
    }
    failures: list[str] = []
    missing_checks = sorted(registered_active - covered_checks)
    unknown_checks = sorted(covered_checks - registered_active)
    missing_guides = sorted(known_guides - covered_guides)
    unknown_guides = sorted(covered_guides - known_guides)
    if missing_checks:
        failures.append(
            "activated registry checks absent from route cases: "
            + ", ".join(missing_checks)
        )
    if unknown_checks:
        failures.append(
            "route cases reference non-activated checks: "
            + ", ".join(unknown_checks)
        )
    if missing_guides:
        failures.append(
            "triggered guides absent from route cases: " + ", ".join(missing_guides)
        )
    if unknown_guides:
        failures.append(
            "route cases reference unknown/triggerless guides: "
            + ", ".join(unknown_guides)
        )
    return assert_true(
        not failures,
        "routing-case-coverage",
        "\n".join(failures),
    )


def _verification_phase_matrix_check(schedule: dict[str, Any]) -> _Check:
    failures: list[str] = []
    for case in ROUTE_CASES:
        args = recommend_stack.build_parser().parse_args(list(case.flags))
        care = recommend_stack.choose_standard_of_care(args)
        selected = recommend_stack.collect_required_checks(args, care, schedule)
        grouped = verification_plan.group_checks(selected)
        observed = {
            item["check_id"]: phase
            for phase, items in grouped.items()
            for item in items
        }
        expected = {check.check_id: check.phase for check in selected}
        if observed != expected:
            failures.append(
                f"{case.label}: expected {expected!r}, observed {observed!r}"
            )
    return assert_true(
        not failures,
        "verification-phase-matrix",
        "\n".join(failures),
    )


def _canonical_report_ids(items: object, *, location: str) -> tuple[str, ...]:
    if not isinstance(items, list):
        raise ValueError(f"{location} must be a list")
    check_ids: list[str] = []
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{location}[{position}] must be an object")
        if set(item) != {"check_id", "text", "phase", "owning_guide"}:
            raise ValueError(
                f"{location}[{position}] must expose check_id, text, phase, "
                "and owning_guide exactly"
            )
        check_id = item.get("check_id")
        if not isinstance(check_id, str):
            raise ValueError(f"{location}[{position}].check_id must be a string")
        canonical = verification_registry.get_check(check_id).as_report_item()
        if item != canonical:
            raise ValueError(
                f"{location}[{position}] does not match registry record {check_id}"
            )
        check_ids.append(check_id)
    return tuple(check_ids)


def _recommend_report_matches(
    report: dict[str, Any],
    case: _RouteCase,
) -> bool:
    check_ids = set(
        _canonical_report_ids(
            report.get("required_checks"),
            location="required_checks",
        )
    )
    return (
        report.get("schema_version") == 1
        and report.get("standard_of_care") == case.standard_of_care
        and report.get("evidentiary_scope") == case.evidentiary_scope
        and tuple(report.get("practice_guides", ())) == case.practice_guides
        and set(case.required_check_ids) <= check_ids
        and not (set(case.forbidden_check_ids) & check_ids)
    )


def _verification_report_matches(
    report: dict[str, Any],
    expected_check_ids: tuple[str, ...],
) -> bool:
    phase_checks = report.get("phase_checks")
    if not isinstance(phase_checks, dict):
        raise ValueError("phase_checks must be an object")
    if set(phase_checks) != set(verification_registry.PHASES):
        raise ValueError("phase_checks must expose every canonical phase exactly")
    observed: dict[str, str] = {}
    for phase in verification_registry.PHASES:
        for check_id in _canonical_report_ids(
            phase_checks[phase],
            location=f"phase_checks.{phase}",
        ):
            if check_id in observed:
                raise ValueError(f"duplicate phased check ID: {check_id}")
            observed[check_id] = phase
    for check_id, phase in observed.items():
        if verification_registry.get_check(check_id).phase != phase:
            raise ValueError(
                f"phase_checks places {check_id} in {phase}, not its registry phase"
            )
    return (
        report.get("schema_version") == 1
        and set(expected_check_ids) <= set(observed)
    )


def _collect_routing_checks(python: str, repo_root: Path) -> list[_Check]:
    checks: list[_Check] = []
    ok, prereqs, message = run_json(
        "check-prereqs",
        [python, "scripts/check_prereqs.py"],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("check-prereqs"),
    )
    checks.append(
        assert_json_result(
            prereqs,
            "check-prereqs",
            "expected prerequisite report to declare its selected runner",
            command_ok=ok,
            command_message=message,
            shape=_PREREQUISITE_REPORT_SHAPE,
        )
    )
    ok, clause_map, message = run_json(
        "query-clause-map",
        [python, "scripts/query_clause_map.py", "--disposition", "projected"],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("query-clause-map"),
    )
    checks.append(
        assert_json_result(
            clause_map,
            "query-clause-map",
            "expected at least one projected clause-map row",
            command_ok=ok,
            command_message=message,
            shape=_JSON_ARRAY,
            predicate=bool,
        )
    )

    try:
        schedule = recommend_stack.load_schedule()
    except Exception as exc:
        schedule = None
        checks.append(
            _exception_check(
                "routing-schedule-load",
                "operative schedule could not be loaded",
                exc,
            )
        )
    if schedule is not None:
        checks.append(
            _invoke_check_safely(
                "routing-case-coverage",
                lambda: _route_table_coverage_check(schedule),
            )
        )
        for case in ROUTE_CASES:
            checks.append(
                _invoke_check_safely(
                    f"routing-case-{case.label}",
                    lambda case=case: _route_case_check(case, schedule),
                )
            )
        checks.append(
            _invoke_check_safely(
                "verification-phase-matrix",
                lambda: _verification_phase_matrix_check(schedule),
            )
        )

    representative = next(
        case for case in ROUTE_CASES if case.label == "prompt-agent"
    )
    ok, report, message = run_json(
        "recommend-stack-e2e",
        [python, "scripts/recommend_stack.py", *representative.flags],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("recommend-stack-e2e"),
    )
    checks.append(
        assert_json_result(
            report,
            "recommend-stack-e2e",
            "representative CLI route did not match its registry case",
            command_ok=ok,
            command_message=message,
            shape=_RECOMMEND_REPORT_SHAPE,
            predicate=lambda value: _recommend_report_matches(
                value, representative
            ),
        )
    )
    return checks


def _collect_context_checks(python: str, repo_root: Path) -> list[_Check]:
    checks: list[_Check] = []
    ok, manifest, message = run_json(
        "context-manifest-review",
        [
            python,
            "scripts/context_manifest.py",
            "--review",
            "--multi-file",
            "--impact-review",
            "--path",
            "practice_guides/change_impact_review.md",
            "--path",
            "runtime/operative_schedule.json",
        ],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("context-manifest-review"),
    )
    checks.append(
        assert_json_result(
            manifest,
            "context-manifest-review",
            "expected a review module and canonical check records",
            command_ok=ok,
            command_message=message,
            shape=_CONTEXT_MANIFEST_REPORT_SHAPE,
            predicate=lambda value: (
                value["task_module"]["name"] == "review"
                and bool(
                    _canonical_report_ids(
                        value["required_checks"],
                        location="required_checks",
                    )
                )
            ),
        )
    )

    ok, evidence_scope, message = run_json(
        "evidence-scope",
        [
            python,
            "scripts/evidence_scope.py",
            "--review",
            "--impact-review",
            "--multi-file",
            "--path",
            "practice_guides/change_impact_review.md",
            "--path",
            "runtime/operative_schedule.json",
        ],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("evidence-scope"),
    )
    checks.append(
        assert_json_result(
            evidence_scope,
            "evidence-scope",
            "expected a non-empty recommended evidence scope",
            command_ok=ok,
            command_message=message,
            shape=_EVIDENCE_SCOPE_REPORT_SHAPE,
            predicate=lambda value: bool(value["recommended_scope"]),
        )
    )

    representative = next(
        case for case in ROUTE_CASES if case.label == "frontend"
    )
    ok, plan, message = run_json(
        "verification-plan-e2e",
        [python, "scripts/verification_plan.py", *representative.flags],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("verification-plan-e2e"),
    )
    checks.append(
        assert_json_result(
            plan,
            "verification-plan-e2e",
            "representative phased CLI route did not match registry metadata",
            command_ok=ok,
            command_message=message,
            shape=_VERIFICATION_REPORT_SHAPE,
            predicate=lambda value: _verification_report_matches(
                value, representative.required_check_ids
            ),
        )
    )
    return checks


def _collect_consistency_checks(python: str, repo_root: Path) -> list[_Check]:
    checks: list[_Check] = []
    ok, load_report, message = run_json(
        "prompt-load-report",
        [python, "scripts/prompt_load_report.py"],
        repo_root,
        timeout_seconds=exported_tree_child_timeout("prompt-load-report"),
    )
    checks.append(
        assert_json_result(
            load_report,
            "prompt-load-report",
            "expected no eager Practice Guide imports or configured per-file byte ceiling violations",
            command_ok=ok,
            command_message=message,
            shape=_PROMPT_LOAD_REPORT_SHAPE,
            predicate=lambda value: not value["eager_practice_guide_imports"]
            and not value["budget_errors"],
        )
    )

    return checks


def _print_checks_and_exit_status(checks: list[_Check]) -> int:
    failures: list[str] = []
    for ok, message in checks:
        print(message)
        if not ok:
            failures.append(message.split(":", 1)[0])
    return 1 if failures else 0


def _collect_checks_safely(
    label: str,
    collector: Callable[[str, Path], list[_Check]],
    python: str,
    repo_root: Path,
) -> list[_Check]:
    """Convert collector failures into bounded results so later groups run."""

    try:
        return collector(python, repo_root)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        return [
            _exception_check(
                label,
                "compliance collector received an incompatible result shape",
                exc,
            )
        ]
    except Exception as exc:
        return [
            _exception_check(
                label,
                "compliance collector could not complete",
                exc,
            )
        ]


@contextmanager
def _publication_child_environment(
    *,
    git_executable: public_release_check.GitExecutableBinding | None,
    uv_executable: public_release_check.GitExecutableBinding,
) -> Iterator[None]:
    git_executable_command = (
        git_executable.external_command if git_executable is not None else None
    )
    uv_executable_command = uv_executable.external_command
    with tempfile.TemporaryDirectory(prefix="mpa-release-tools-") as temp_dir:
        tool_root = Path(temp_dir)
        if git_executable_command is not None:
            (tool_root / "git").symlink_to(git_executable_command)
        environment = {
            "LC_ALL": "C.UTF-8",
            public_release_check.PUBLICATION_BOUNDARY_ENV: "1",
            PUBLICATION_UV_PROC_PATH_ENV: uv_executable_command,
            PUBLICATION_UV_SHA256_ENV: uv_executable.sha256,
            "NODE_OPTIONS": PUBLICATION_NODE_OPTIONS,
            "PATH": f"{tool_root}:/usr/sbin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            **(
                {
                    public_release_check.PUBLICATION_GIT_PROC_PATH_ENV: (
                        git_executable.external_command
                    ),
                    public_release_check.PUBLICATION_GIT_SHA256_ENV: git_executable.sha256,
                }
                if git_executable is not None
                else {}
            ),
        }
        with (
            _process_environment(environment),
            _process_umask(PUBLICATION_CHILD_UMASK),
        ):
            yield


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run aggregate Master Prompt Agreement framework compliance.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--tree-role",
        type=ReleaseTreeRole,
        choices=tuple(ReleaseTreeRole),
        required=True,
        help=(
            "Declare whether the checked tree is the private authoring source "
            "or a sanitized public export; the role is never inferred from its files."
        ),
    )
    parser.add_argument(
        "--publication-boundary",
        action="store_true",
        help=(
            "Require isolated child environments, a retained uv executable binding, "
            f"and offline basedpyright {BASEDPYRIGHT_VERSION}; authoring-source also "
            "requires a retained Git binding, while public-export forbids one."
        ),
    )
    parser.add_argument(
        "--git-executable-fd",
        type=int,
        help=(
            "Authoring-source-only inherited descriptor for the reviewed Git "
            "executable; supply it with --git-executable-sha256. Public-export "
            "checks forbid a Git binding."
        ),
    )
    parser.add_argument(
        "--git-executable-sha256",
        help=(
            "Authoring-source-only approved lowercase SHA-256 digest of the "
            "executable bound by --git-executable-fd. Public-export checks forbid "
            "a Git binding."
        ),
    )
    parser.add_argument(
        "--uv-executable-fd",
        type=int,
        help=(
            "Inherited descriptor for the reviewed uv executable; supply it "
            "with --uv-executable-sha256."
        ),
    )
    parser.add_argument(
        "--uv-executable-sha256",
        help=(
            "Approved lowercase SHA-256 digest of the executable bound by "
            "--uv-executable-fd."
        ),
    )
    args = parser.parse_args(argv)
    tree_role = args.tree_role
    git_executable, publication_boundary = (
        public_release_check.publication_git_binding(parser, args)
    )
    try:
        uv_executable = public_release_check.publication_executable_binding(
            parser,
            explicit_descriptor=args.uv_executable_fd,
            explicit_sha256=args.uv_executable_sha256,
            propagated_path_env=PUBLICATION_UV_PROC_PATH_ENV,
            propagated_sha256_env=PUBLICATION_UV_SHA256_ENV,
            description="bound uv executable",
        )
    except BaseException:
        if git_executable is not None:
            git_executable.close()
        raise

    if publication_boundary and uv_executable is None:
        if git_executable is not None:
            git_executable.close()
        parser.error(
            "publication-boundary compliance requires a retained uv descriptor "
            "and approved SHA-256 digest"
        )

    repo_root = Path(__file__).resolve().parent.parent
    python = sys.executable
    checks: list[_Check] = []

    def collect_foundation(
        selected_python: str,
        selected_root: Path,
    ) -> list[_Check]:
        return _collect_foundation_checks(
            selected_python,
            selected_root,
            tree_role,
            uv_executable=uv_executable,
        )

    collectors: list[tuple[str, Callable[[str, Path], list[_Check]]]] = [
        (
            f"foundation-{tree_role.value}-check-collection",
            collect_foundation,
        ),
        ("routing-check-collection", _collect_routing_checks),
        ("context-verification-check-collection", _collect_context_checks),
        ("consistency-check-collection", _collect_consistency_checks),
    ]
    if tree_role is ReleaseTreeRole.AUTHORING_SOURCE:
        collectors.insert(
            1,
            (
                "private-authoring-check-collection",
                lambda selected_python, selected_root: (
                    _collect_private_authoring_checks(
                        selected_python,
                        selected_root,
                        git_executable=git_executable,
                    )
                ),
            ),
        )
        collectors.append(
            (
                "authoring-workspace-hygiene-check-collection",
                lambda selected_python, selected_root: (
                    _collect_authoring_workspace_hygiene_checks(
                        selected_python,
                        selected_root,
                        git_executable=git_executable,
                    )
                ),
            )
        )

    try:
        environment = (
            _publication_child_environment(
                git_executable=git_executable,
                uv_executable=uv_executable,
            )
            if publication_boundary and uv_executable is not None
            else _routine_child_environment()
        )
        with environment:
            for label, collector in collectors:
                checks.extend(
                    _collect_checks_safely(label, collector, python, repo_root)
                )
    finally:
        for description, binding in (
            ("Git executable", git_executable),
            ("uv executable", uv_executable),
        ):
            if binding is None:
                continue
            try:
                binding.close()
            except Exception as exc:
                checks.append(
                    (
                        False,
                        f"publication-{description.lower().replace(' ', '-')}-binding: "
                        f"FAIL\n{exc}",
                    )
                )
    return _print_checks_and_exit_status(checks)


if __name__ == "__main__":
    raise SystemExit(main())
