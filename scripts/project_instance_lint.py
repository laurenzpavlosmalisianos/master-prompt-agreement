#!/usr/bin/env python3

"""Validate replayable project-instance provenance for every project kind."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
from typing import Any

import integration_registry
import project_bootstrap
import project_contract_model as contract_model
import project_input
import project_state_identity
import safe_paths


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "PROJECT_INSTANCE.json"
MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "project_input_schema_version",
        "project_contract_format",
        "msa_version",
        "project_kind",
        "contract_root",
        "runtime",
        "runtime_wrapper_outputs",
        "contract_effective_date",
        "framework_reference",
        "framework_revision_policy",
        "framework_reference_status",
        "framework_content_sha256",
        "framework_effective_file_digests",
        "framework_distribution_sha256",
        "input_source",
        "input_sha256",
        "active_profiles",
        "authority_module_digests",
        "managed_files",
        "immutable_files",
        "mutable_files",
        "output_digests",
        "generation_sources",
    }
)
GENERATION_SOURCE_KEYS = frozenset({"path", "sha256"})
REFERENCE_STATUSES = frozenset({"verified", "unresolved"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class LintContext:
    project_root: Path
    contract_root: Path
    contract_root_ref: str
    expected_project_kind: str | None


def file_sha256(path: Path, *, description: str = "file input") -> str:
    raw = safe_paths.read_regular_file_bytes(path, description=description)
    return hashlib.sha256(raw).hexdigest()


def contract_root_path(project_root: Path, value: str) -> tuple[Path, str | None]:
    if value == ".":
        return project_root, None
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            value,
            project_root,
            description="contract root",
        )
    except ValueError as exc:
        return project_root, str(exc)
    return (project_root / normalized).resolve(strict=False), None


def safe_project_file(
    project_root: Path,
    value: object,
    label: str,
) -> tuple[Path | None, str | None]:
    if not isinstance(value, str):
        return None, f"{label} must be a string"
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            value,
            project_root,
            description=label,
        )
    except ValueError as exc:
        return None, str(exc)
    return project_root / normalized, None


def validate_digest(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        return [f"{label} must be a lowercase SHA-256 digest"]
    return []


def load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description="project instance manifest",
        )
    except FileNotFoundError:
        return None, [f"missing project instance manifest: {path}"]
    except ValueError as exc:
        return None, [f"project instance manifest is not a bounded regular input: {exc}"]
    except OSError as exc:
        return None, [f"project instance manifest could not be read: {exc}"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [f"project instance manifest must be valid UTF-8: {exc}"]
    try:
        payload = safe_paths.loads_json_no_duplicates(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, [f"project instance manifest is invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, ["project instance manifest must be a JSON object"]
    return payload, []


def schema_version_preflight_error(manifest: dict[str, Any]) -> str | None:
    """Reject non-current receipts before producing derivative diagnostics."""

    expected = project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION
    if "schema_version" not in manifest:
        issue = "is missing"
    else:
        version = manifest["schema_version"]
        if type(version) is not int:
            issue = "is malformed; expected a non-boolean integer"
        elif version > expected:
            return (
                f"project instance manifest schema_version {version} is newer than the "
                f"supported schema_version {expected}; use a framework checkout that "
                f"supports schema_version {version} before running current-schema checks"
            )
        elif version != expected:
            issue = f"is {version}; expected {expected}"
        else:
            return None
    return (
        f"project instance manifest schema_version {issue}. The current-only lifecycle "
        f"supports exactly schema_version {expected} and does not migrate or rewrite "
        "other receipt formats; perform a reviewed project-specific manual update "
        "before running current-schema checks"
    )


def project_input_schema_version_preflight_error(
    manifest: dict[str, Any],
) -> str | None:
    """Reject receipts that declare a non-current retained-input format."""

    expected = project_input.SCHEMA_VERSION
    version = manifest.get("project_input_schema_version")
    if type(version) is int and version == expected:
        return None
    if "project_input_schema_version" not in manifest:
        issue = "is missing"
    elif type(version) is not int:
        issue = "is malformed; expected a non-boolean integer"
    elif version > expected:
        return (
            f"project instance manifest project_input_schema_version {version} is newer "
            f"than the supported retained-input schema_version {expected}; use a framework "
            f"checkout that supports schema_version {version} before running "
            "current-schema checks"
        )
    else:
        issue = f"is {version}; expected {expected}"
    return (
        f"project instance manifest project_input_schema_version {issue}. The "
        f"current-only lifecycle supports exactly retained-input schema_version {expected} "
        "and does not migrate or reconstruct other input formats; perform a reviewed "
        "project-specific manual update before running current-schema checks"
    )


def project_contract_format_preflight_error(
    manifest: dict[str, Any],
) -> str | None:
    """Reject a noncurrent generated-contract grammar before refresh planning."""

    value = manifest.get("project_contract_format")
    expected = contract_model.CONTRACT_FORMAT_VERSION
    if type(value) is int and value == expected:
        return None
    if type(value) is int and value > expected:
        return (
            f"project instance manifest project_contract_format {value} is newer "
            f"than the supported format {expected}; use a framework checkout that "
            f"supports format {value} before running current-format checks"
        )
    issue = "is missing" if "project_contract_format" not in manifest else f"is {value!r}"
    return (
        f"project instance manifest project_contract_format {issue}. The current-only "
        f"lifecycle supports exactly format {expected}; perform a reviewed "
        "project-specific manual update before running current-format checks"
    )


def _validate_closed_manifest(manifest: dict[str, Any], errors: list[str]) -> None:
    unknown = sorted(set(manifest) - MANIFEST_KEYS)
    missing = sorted(MANIFEST_KEYS - set(manifest))
    if unknown:
        errors.append(f"project instance manifest has unknown keys: {', '.join(unknown)}")
    if missing:
        errors.append(f"project instance manifest is missing keys: {', '.join(missing)}")


def _recorded_relative_path_errors(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty repo-relative path"]
    path = Path(value)
    windows_path = PureWindowsPath(value)
    errors = safe_paths.project_relative_reference_errors(value, label)
    if (
        "\\" in value
        or "://" in value
        or path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or ".." in windows_path.parts
    ):
        errors.append(f"{label} must be a safe repo-relative path")
    return errors


def _validate_recorded_effective_file_digests(
    manifest: dict[str, Any],
    errors: list[str],
) -> dict[str, str] | None:
    value = manifest.get("framework_effective_file_digests")
    if not isinstance(value, dict) or not value:
        errors.append(
            "project instance manifest framework_effective_file_digests must be a "
            "non-empty path-to-digest object"
        )
        return None
    normalized: dict[str, str] = {}
    for path, digest in value.items():
        label = f"framework_effective_file_digests.{path}"
        errors.extend(_recorded_relative_path_errors(path, label))
        errors.extend(validate_digest(digest, label))
        if isinstance(path, str) and isinstance(digest, str):
            normalized[path] = digest
    if len(normalized) != len(value):
        return None
    content_digest = manifest.get("framework_content_sha256")
    if (
        isinstance(content_digest, str)
        and SHA256_RE.fullmatch(content_digest)
        and content_digest != project_bootstrap.canonical_json_digest(normalized)
    ):
        errors.append(
            "project instance manifest framework_content_sha256 must exactly digest "
            "framework_effective_file_digests"
        )
    return normalized


def _validate_recorded_identity(
    context: LintContext,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    if (
        type(manifest.get("project_input_schema_version")) is not int
        or manifest.get("project_input_schema_version") != project_input.SCHEMA_VERSION
    ):
        errors.append(
            "project instance manifest project_input_schema_version must be exact "
            f"non-boolean integer {project_input.SCHEMA_VERSION}"
        )
    project_contract_format = manifest.get("project_contract_format")
    if type(project_contract_format) is not int or project_contract_format <= 0:
        errors.append(
            "project instance manifest project_contract_format must be a positive "
            "non-boolean integer"
        )
    if not isinstance(manifest.get("msa_version"), str) or not manifest.get(
        "msa_version"
    ):
        errors.append("project instance manifest msa_version must be a non-empty string")

    project_kind = manifest.get("project_kind")
    try:
        policy = contract_model.project_layout_policy(project_kind)
    except ValueError:
        policy = None
        errors.append(
            "project instance manifest project_kind must be one of: "
            + ", ".join(sorted(contract_model.PROJECT_KINDS))
        )
    if (
        context.expected_project_kind is not None
        and project_kind != context.expected_project_kind
    ):
        errors.append(
            "project instance manifest project_kind mismatch: "
            f"expected {context.expected_project_kind}, found {project_kind}"
        )
    runtime = manifest.get("runtime")
    if policy is not None and policy.runtime_forbidden and runtime is not None:
        errors.append(f"{policy.kind} project instance runtime must be null")
    if policy is not None and policy.runtime_required and (
        not isinstance(runtime, str) or not runtime.strip()
    ):
        errors.append(
            f"{policy.kind} project instance runtime must be a non-empty string"
        )

    contract_effective_date = manifest.get("contract_effective_date")
    if not isinstance(contract_effective_date, str):
        errors.append(
            "project instance manifest contract_effective_date must be an ISO date string"
        )
    else:
        try:
            normalized = date.fromisoformat(contract_effective_date).isoformat()
        except ValueError:
            errors.append(
                "project instance manifest contract_effective_date must be a valid ISO date"
            )
        else:
            if contract_effective_date != normalized:
                errors.append(
                    "project instance manifest contract_effective_date must use canonical YYYY-MM-DD form"
                )

    framework_reference = manifest.get("framework_reference")
    status = manifest.get("framework_reference_status")
    if not isinstance(status, str) or status not in REFERENCE_STATUSES:
        errors.append(
            "project instance manifest framework_reference_status must be one of: "
            + ", ".join(sorted(REFERENCE_STATUSES))
        )
    if not isinstance(framework_reference, str):
        errors.append("project instance manifest framework_reference must be a string")
    else:
        errors.extend(
            f"project instance manifest framework_reference: {error}"
            for error in safe_paths.framework_reference_errors(framework_reference)
        )
    revision_policy = manifest.get("framework_revision_policy")
    if (
        not isinstance(revision_policy, str)
        or revision_policy not in project_input.REVISION_POLICIES
    ):
        errors.append(
            "project instance manifest framework_revision_policy must be one of: "
            + ", ".join(sorted(project_input.REVISION_POLICIES))
        )

    content_digest = manifest.get("framework_content_sha256")
    errors.extend(
        validate_digest(
            content_digest,
            "project instance manifest framework_content_sha256",
        )
    )
    _validate_recorded_effective_file_digests(manifest, errors)

    distribution_digest = manifest.get("framework_distribution_sha256")
    errors.extend(
        validate_digest(
            distribution_digest,
            "project instance manifest framework_distribution_sha256",
        )
        )


def _selected_contract_root_preflight_error(
    context: LintContext,
    manifest: dict[str, Any],
) -> str | None:
    """Bind caller selection to the root receipt before reading contract files."""

    if manifest.get("contract_root") == context.contract_root_ref:
        return None
    return (
        "project instance manifest contract_root does not match the selected contract root: "
        f"expected {context.contract_root_ref!r}, found {manifest.get('contract_root')!r}"
    )


def _validate_selected_identity(
    context: LintContext,
    manifest: dict[str, Any],
    framework_root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    executing_framework_root = FRAMEWORK_ROOT.resolve(strict=False)
    if framework_root != executing_framework_root:
        errors.append(
            "selected framework root must be the checkout executing project_instance_lint.py: "
            f"expected {executing_framework_root}, found {framework_root}"
        )

    if manifest.get("project_contract_format") != contract_model.CONTRACT_FORMAT_VERSION:
        errors.append(
            "project instance manifest project_contract_format does not match the "
            f"selected framework: expected {contract_model.CONTRACT_FORMAT_VERSION}, "
            f"found {manifest.get('project_contract_format')!r}"
        )
    expected_msa_version = project_bootstrap.msa_version()
    if manifest.get("msa_version") != expected_msa_version:
        errors.append(
            "project instance manifest msa_version mismatch: "
            f"expected {expected_msa_version!r}, found {manifest.get('msa_version')!r}"
        )

    project_kind = manifest.get("project_kind")
    framework_reference = manifest.get("framework_reference")
    status = manifest.get("framework_reference_status")
    if isinstance(framework_reference, str):
        expected_status, binding_errors, binding_warnings = (
            project_bootstrap.framework_reference_binding(
                framework_reference,
                context.project_root,
                framework_root,
            )
        )
        errors.extend(binding_errors)
        warnings.extend(binding_warnings)
        if (
            isinstance(status, str)
            and status in REFERENCE_STATUSES
            and status != expected_status
        ):
            errors.append(
                "project instance manifest framework_reference_status mismatch: "
                f"expected {expected_status!r}, found {status!r}"
            )

    recorded_map = manifest.get("framework_effective_file_digests")
    effective_drift = True
    try:
        selected_map = project_bootstrap.framework_effective_file_digests(framework_root)
        selected_content_digest = project_bootstrap.canonical_json_digest(selected_map)
    except (OSError, ValueError) as exc:
        errors.append(f"selected framework effective identity could not be computed: {exc}")
    else:
        effective_drift = recorded_map != selected_map
        if effective_drift:
            errors.append(
                "project instance manifest framework_content_sha256 does not match "
                "the selected current framework content"
            )
            recorded_paths = set(recorded_map) if isinstance(recorded_map, dict) else set()
            selected_paths = set(selected_map)
            for path in sorted(selected_paths - recorded_paths):
                errors.append(f"selected framework effective file added since receipt: {path}")
            for path in sorted(recorded_paths - selected_paths):
                errors.append(f"selected framework effective file removed since receipt: {path}")
            if isinstance(recorded_map, dict):
                for path in sorted(recorded_paths & selected_paths):
                    if recorded_map.get(path) != selected_map[path]:
                        errors.append(
                            f"selected framework effective file changed since receipt: {path}"
                        )
        elif manifest.get("framework_content_sha256") != selected_content_digest:
            errors.append(
                "project instance manifest framework_content_sha256 does not match "
                "the selected current framework content"
            )

    try:
        expected_distribution_digest = project_bootstrap.framework_distribution_sha256(
            framework_root
        )
    except (OSError, ValueError) as exc:
        errors.append(f"current framework distribution digest could not be computed: {exc}")
    else:
        if (
            not effective_drift
            and manifest.get("framework_distribution_sha256")
            != expected_distribution_digest
        ):
            warnings.append(
                "project instance framework distribution differs from the exact "
                "rendering checkout while downstream-effective content remains "
                "independently verified"
            )

    if isinstance(project_kind, str) and project_kind in contract_model.PROJECT_KINDS:
        errors.extend(
            "project layout: " + error
            for error in project_bootstrap.project_layout_errors(
                context.project_root,
                context.contract_root,
                context.contract_root_ref,
                framework_root,
                project_kind,
            )
        )


def _load_and_validate_input(
    context: LintContext,
    manifest: dict[str, Any],
    errors: list[str],
) -> tuple[dict[str, object] | None, bytes | None, str | None]:
    recorded_input_digest = manifest.get("input_sha256")
    errors.extend(
        validate_digest(recorded_input_digest, "project instance manifest input_sha256")
    )
    expected_input_source = project_bootstrap.project_relative_output(
        context.contract_root_ref,
        project_input.INPUT_NAME,
    )
    if manifest.get("input_source") != expected_input_source:
        errors.append(
            "project instance input_source must exactly name the retained input "
            f"at {expected_input_source!r}"
        )
    input_path, path_error = safe_project_file(
        context.project_root,
        expected_input_source,
        "project instance input_source",
    )
    if path_error:
        errors.append(path_error)
        return None, None, None
    if input_path is None:
        errors.append("project instance input_source did not resolve to a project file")
        return None, None, None
    input_errors = safe_paths.bounded_input_errors(
        input_path,
        context.project_root,
        description="project instance retained input",
    )
    errors.extend(input_errors)
    if input_errors:
        return None, None, (
            "retained project input cannot supply a readable current-format identity: "
            + "; ".join(input_errors)
            + ". The current-only lifecycle supports only a readable exact retained "
            "input; perform a reviewed project-specific manual update before running "
            "current-schema checks"
        )

    payload, raw, load_errors = project_input.load_project_input(input_path)
    errors.extend(load_errors)
    if payload is None or raw is None:
        return None, raw, (
            "retained project input cannot supply a readable current-format identity: "
            + "; ".join(load_errors or ["input payload is unavailable"])
            + ". The current-only lifecycle supports only a readable exact retained "
            "input; perform a reviewed project-specific manual update before running "
            "current-schema checks"
        )
    input_schema_error = project_input.schema_version_preflight_error(payload)
    if input_schema_error is not None:
        return payload, raw, "retained project input: " + input_schema_error
    errors.extend(
        "retained project input: " + error
        for error in project_input.validate_project_input_structure(
            payload,
            project_root=context.project_root,
            input_path=input_path,
        )
    )
    actual_input_digest = project_input.project_input_sha256(raw)
    if (
        isinstance(recorded_input_digest, str)
        and recorded_input_digest != actual_input_digest
    ):
        errors.append(
            "project instance manifest input_sha256 does not match the retained project input"
        )

    parity_fields = (
        "project_kind",
        "contract_root",
        "runtime",
        "framework_reference",
        "framework_revision_policy",
    )
    for field in parity_fields:
        if manifest.get(field) != payload.get(field):
            errors.append(
                f"project instance manifest {field} does not match retained project input"
            )

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return payload, raw, None
    errors.extend(
        "retained project input answers: " + error
        for error in project_bootstrap.validate_answers(
            answers,
            automation_project_root=context.project_root,
            automation_manifest_path=context.contract_root / "AUTOMATION_ORDERS.json",
            require_existing_automation_project_root=False,
        )
    )
    errors.extend(
        "retained project input answers: " + error
        for error in contract_model.framework_verification_runner_errors(
            answers.get("framework_verification_runner"),
            "framework_verification_runner",
        )
    )
    if manifest.get("contract_effective_date") != answers.get("date"):
        errors.append(
            "project instance manifest contract_effective_date must exactly match retained "
            "project input answers.date"
        )
    return payload, raw, None


def _validate_string_list(
    value: object,
    label: str,
    errors: list[str],
    *,
    require_sorted: bool = True,
) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must be a list of strings")
        return None
    if len(value) != len(set(value)):
        errors.append(f"{label} must not contain duplicates")
    if require_sorted and value != sorted(value):
        errors.append(f"{label} must be sorted")
    return value


def _validate_recorded_file_sets(
    context: LintContext,
    manifest: dict[str, Any],
    payload: dict[str, object] | None,
    errors: list[str],
) -> tuple[list[str], list[str], list[str]]:
    managed = _validate_string_list(
        manifest.get("managed_files"),
        "project instance manifest managed_files",
        errors,
    )
    immutable = _validate_string_list(
        manifest.get("immutable_files"),
        "project instance manifest immutable_files",
        errors,
    )
    mutable = _validate_string_list(
        manifest.get("mutable_files"),
        "project instance manifest mutable_files",
        errors,
    )
    managed_values = managed or []
    immutable_values = immutable or []
    mutable_values = mutable or []

    if set(immutable_values) & set(mutable_values):
        errors.append("project instance immutable_files and mutable_files must be disjoint")
    if set(managed_values) != set(immutable_values) | set(mutable_values):
        errors.append(
            "project instance managed_files must be exactly the union of immutable_files "
            "and mutable_files"
        )
    metadata_names = {project_input.INPUT_NAME, MANIFEST_NAME}
    if any(Path(value).name in metadata_names for value in managed_values):
        errors.append(
            "project instance managed_files must exclude retained input and receipt metadata"
        )

    for value in managed_values:
        path, path_error = safe_project_file(
            context.project_root,
            value,
            f"project instance managed file {value}",
        )
        if path_error:
            errors.append(path_error)
            continue
        if path is None:
            continue
        path_errors = safe_paths.bounded_input_errors(
            path,
            context.project_root,
            description=f"project instance managed file {value}",
        )
        errors.extend(path_errors)
        if not path_errors and (not path.is_file() or path.is_symlink()):
            errors.append(f"project instance managed file is missing or not regular: {value}")

    wrapper_outputs_raw = manifest.get("runtime_wrapper_outputs")
    wrapper_outputs: dict[str, str] = {}
    if not isinstance(wrapper_outputs_raw, dict):
        errors.append("project instance manifest runtime_wrapper_outputs must be an object")
    else:
        for wrapper_id, output in wrapper_outputs_raw.items():
            if (
                not isinstance(wrapper_id, str)
                or not integration_registry.WRAPPER_NAME_RE.fullmatch(wrapper_id)
            ):
                errors.append(
                    "project instance manifest runtime_wrapper_outputs keys must be "
                    "wrapper ID strings"
                )
                continue
            if not isinstance(output, str):
                errors.append(
                    "project instance manifest runtime_wrapper_outputs values must be "
                    "repo-relative path strings"
                )
                continue
            _path, path_error = safe_project_file(
                context.project_root,
                output,
                f"project instance runtime wrapper output {wrapper_id}",
            )
            if path_error:
                errors.append(path_error)
                continue
            if output in wrapper_outputs.values():
                errors.append(
                    "project instance manifest runtime_wrapper_outputs values must be unique"
                )
                continue
            wrapper_outputs[wrapper_id] = output
        if list(wrapper_outputs_raw) != sorted(wrapper_outputs_raw):
            errors.append(
                "project instance manifest runtime_wrapper_outputs keys must be sorted"
            )

    if payload is None:
        return managed_values, immutable_values, mutable_values
    answers = payload.get("answers")
    project_kind = payload.get("project_kind")
    runtime = payload.get("runtime")
    runtime_wrappers = payload.get("runtime_wrappers")
    if (
        not isinstance(answers, dict)
        or not isinstance(project_kind, str)
        or project_kind not in contract_model.PROJECT_KINDS
        or (runtime is not None and not isinstance(runtime, str))
        or not isinstance(runtime_wrappers, list)
        or any(not isinstance(item, str) for item in runtime_wrappers)
    ):
        return managed_values, immutable_values, mutable_values
    expected_mutable = sorted(
        project_bootstrap.mutable_state_output_names(
            answers,
            context.contract_root_ref,
        )
    )
    required_contract_outputs = {
        project_bootstrap.project_relative_output(
            context.contract_root_ref,
            "STATEMENT_OF_WORK.md",
        ),
        project_bootstrap.project_relative_output(
            context.contract_root_ref,
            "AGENT_PROJECT.md",
        ),
    }
    immutable_optional_outputs = {
        project_bootstrap.project_relative_output(context.contract_root_ref, name)
        for name in project_bootstrap.immutable_optional_state_names(answers)
    }
    policy = contract_model.project_layout_policy(project_kind)
    if not policy.manages_runtime_entrypoint:
        expected_immutable = sorted(
            [*required_contract_outputs, *immutable_optional_outputs]
        )
        if wrapper_outputs:
            errors.append(
                f"{policy.kind} project instance runtime_wrapper_outputs must be empty"
            )
    else:
        if set(wrapper_outputs) != set(runtime_wrappers):
            errors.append(
                "project instance manifest runtime_wrapper_outputs keys must exactly "
                "match retained project input runtime_wrappers"
            )
        wrapper_paths = set(wrapper_outputs.values())
        recorded_entrypoints = (
            set(immutable_values)
            - required_contract_outputs
            - immutable_optional_outputs
            - wrapper_paths
        )
        expected_immutable = sorted(
            [
                *required_contract_outputs,
                *immutable_optional_outputs,
                *wrapper_paths,
                *recorded_entrypoints,
            ]
        )
        if (
            len(recorded_entrypoints) != 1
            or not required_contract_outputs.issubset(immutable_values)
            or not immutable_optional_outputs.issubset(immutable_values)
        ):
            errors.append(
                "downstream recorded preimage must contain the canonical contract pair, "
                "one receipt-recorded runtime entrypoint, and exactly the receipt-mapped wrappers"
            )
    expected_managed = sorted([*expected_immutable, *expected_mutable])
    for label, actual, expected in (
        ("managed_files", managed_values, expected_managed),
        ("immutable_files", immutable_values, expected_immutable),
        ("mutable_files", mutable_values, expected_mutable),
    ):
        if actual != expected:
            errors.append(
                f"project instance manifest {label} must exactly match retained project input"
            )
    return managed_values, immutable_values, mutable_values


def _validate_recorded_authority_module_digests(
    context: LintContext,
    manifest: dict[str, Any],
    payload: dict[str, object] | None,
    managed_files: list[str],
    errors: list[str],
) -> list[str]:
    """Validate exact retained authority coverage and live bounded digests."""

    drift_errors: list[str] = []
    value = manifest.get("authority_module_digests")
    if not isinstance(value, list):
        errors.append(
            "project instance manifest authority_module_digests must be a list"
        )
        return drift_errors

    answers = payload.get("answers") if isinstance(payload, dict) else None
    expected: list[tuple[str, str]] = []
    expected_labels: set[str] = set()
    expected_paths: set[str] = set()
    if isinstance(answers, dict):
        for canonical_label, raw_path in project_bootstrap.project_module_references(
            answers
        ):
            try:
                canonical_path = safe_paths.normalize_repo_relative_path(
                    raw_path,
                    context.project_root,
                    description=f"authority module {canonical_label}",
                )
            except ValueError as exc:
                errors.append(
                    "retained project input authority module path is unsafe: "
                    + str(exc)
                )
                continue
            if canonical_label in expected_labels:
                errors.append(
                    "retained project input derives a duplicate authority module "
                    f"label: {canonical_label}"
                )
                continue
            if canonical_path in expected_paths:
                errors.append(
                    "retained project input derives a duplicate authority module "
                    f"path: {canonical_path}"
                )
                continue
            expected_labels.add(canonical_label)
            expected_paths.add(canonical_path)
            expected.append((canonical_label, canonical_path))

    actual: list[tuple[str, str]] = []
    valid_records: list[tuple[str, str, str]] = []
    seen_labels: set[str] = set()
    seen_paths: set[str] = set()
    for index, record in enumerate(value):
        record_label = f"authority_module_digests[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{record_label} must be an object")
            continue
        unknown = sorted(
            set(record) - project_bootstrap.AUTHORITY_MODULE_DIGEST_KEYS
        )
        missing = sorted(
            project_bootstrap.AUTHORITY_MODULE_DIGEST_KEYS - set(record)
        )
        if unknown:
            errors.append(
                f"{record_label} has unknown keys: {', '.join(unknown)}"
            )
        if missing:
            errors.append(
                f"{record_label} is missing keys: {', '.join(missing)}"
            )

        canonical_label = record.get("label")
        raw_path = record.get("path")
        digest = record.get("sha256")
        if not isinstance(canonical_label, str) or not canonical_label:
            errors.append(f"{record_label}.label must be a non-empty string")
        elif canonical_label in seen_labels:
            errors.append(
                f"project instance authority module label is duplicated: "
                f"{canonical_label}"
            )
        else:
            seen_labels.add(canonical_label)

        normalized_path: str | None = None
        if not isinstance(raw_path, str):
            errors.append(f"{record_label}.path must be a string")
        else:
            path_errors = _recorded_relative_path_errors(
                raw_path,
                f"{record_label}.path",
            )
            errors.extend(path_errors)
            try:
                normalized_path = safe_paths.normalize_repo_relative_path(
                    raw_path,
                    context.project_root,
                    description=f"{record_label}.path",
                )
            except ValueError as exc:
                errors.append(
                    f"authority module redirect or unsafe path is forbidden: {exc}"
                )
            else:
                if normalized_path != raw_path:
                    errors.append(
                        f"{record_label}.path must use canonical repo-relative form"
                    )
                if normalized_path in seen_paths:
                    errors.append(
                        "project instance authority module path is duplicated: "
                        f"{normalized_path}"
                    )
                else:
                    seen_paths.add(normalized_path)

        digest_errors = validate_digest(digest, f"{record_label}.sha256")
        errors.extend(digest_errors)
        if isinstance(canonical_label, str) and isinstance(raw_path, str):
            actual.append((canonical_label, raw_path))
        if (
            not unknown
            and not missing
            and isinstance(canonical_label, str)
            and canonical_label
            and normalized_path is not None
            and normalized_path == raw_path
            and isinstance(digest, str)
            and SHA256_RE.fullmatch(digest)
        ):
            valid_records.append((canonical_label, normalized_path, digest))

    expected_set = set(expected)
    actual_set = set(actual)
    for canonical_label, path in sorted(expected_set - actual_set):
        errors.append(
            "project instance authority_module_digests is missing derived module: "
            f"{canonical_label}: {path}"
        )
    for canonical_label, path in sorted(actual_set - expected_set):
        errors.append(
            "project instance authority_module_digests has an extra or non-canonical "
            f"module: {canonical_label}: {path}"
        )
    if actual_set == expected_set and actual != expected:
        errors.append(
            "project instance authority_module_digests must use canonical derived order"
        )

    forbidden_paths = {
        *managed_files,
        MANIFEST_NAME,
        project_bootstrap.project_relative_output(
            context.contract_root_ref,
            project_input.INPUT_NAME,
        ),
    }
    for canonical_label, path, digest in valid_records:
        colliding_output = next(
            (
                output
                for output in sorted(forbidden_paths)
                if project_bootstrap.repo_relative_paths_overlap(path, output)
            ),
            None,
        )
        if colliding_output is not None:
            errors.append(
                "authority modules must remain outside managed, immutable, and "
                "lifecycle metadata output paths and their ancestors or descendants: "
                f"{canonical_label}: {path} conflicts with {colliding_output}"
            )
            continue
        spelling_errors = safe_paths.exact_relative_path_spelling_errors(
            context.project_root,
            Path(path),
            description=f"authority module {canonical_label}",
        )
        if spelling_errors:
            errors.extend(spelling_errors)
            continue
        try:
            raw = safe_paths.read_regular_file_bytes(
                context.project_root / path,
                description=f"authority module {canonical_label}",
                max_bytes=project_bootstrap.AUTHORITY_MODULE_MAX_BYTES,
            )
            raw.decode("utf-8")
        except FileNotFoundError:
            errors.append(
                f"authority module is missing: {canonical_label}: {path}"
            )
            continue
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(
                "authority module redirect, non-UTF-8 content, or unsafe bounded "
                "read was rejected: "
                f"{canonical_label}: {path}: {exc}"
            )
            continue
        if hashlib.sha256(raw).hexdigest() != digest:
            drift = f"authority module digest drift: {canonical_label}: {path}"
            errors.append(drift)
            drift_errors.append(drift)
    return drift_errors


def _validate_mutable_state_origins(
    context: LintContext,
    mutable_files: list[str],
    errors: list[str],
) -> None:
    """Require exact renderer ownership on every current mutable state surface."""

    for value in mutable_files:
        name = Path(value).name
        if name not in project_bootstrap.GENERATED_STATE_BASENAMES:
            continue
        path, path_error = safe_project_file(
            context.project_root,
            value,
            f"project instance mutable state {value}",
        )
        if path_error is not None or path is None:
            continue
        try:
            raw = safe_paths.read_regular_file_bytes(
                path,
                description=f"project instance mutable state {value}",
                max_bytes=project_state_identity.STATE_INPUT_MAX_BYTES,
            )
        except (OSError, ValueError) as exc:
            errors.append(
                f"project instance mutable state origin could not be inspected: "
                f"{value}: {exc}"
            )
            continue
        if not project_state_identity.has_generated_state_origin(name, raw):
            errors.append(
                "project instance mutable state is missing or has a malformed "
                f"framework-generated state origin marker: {value}"
            )


def _validate_unreceipted_generated_state(
    context: LintContext,
    managed_files: list[str],
    errors: list[str],
) -> None:
    """Reject exact marked state surfaces omitted from the current receipt."""

    recorded_generated_state = set(managed_files)
    for name in sorted(project_bootstrap.GENERATED_STATE_BASENAMES):
        relative = project_bootstrap.project_relative_output(
            context.contract_root_ref,
            name,
        )
        if relative in recorded_generated_state:
            continue
        path, path_error = safe_project_file(
            context.project_root,
            relative,
            f"unreceipted project state candidate {relative}",
        )
        if path_error is not None or path is None:
            errors.append(
                "project instance unreceipted generated-state candidate could not "
                f"be safely inspected for generated ownership: {relative}: "
                f"{path_error or 'path did not resolve'}"
            )
            continue
        try:
            raw = safe_paths.read_regular_file_bytes(
                path,
                description=f"unreceipted project state candidate {relative}",
                max_bytes=project_state_identity.STATE_INPUT_MAX_BYTES,
            )
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            errors.append(
                "project instance unreceipted generated-state candidate could not "
                f"be safely inspected for generated ownership: {relative}: {exc}"
            )
            continue
        recognized, identity_error = (
            project_state_identity.inspect_generated_state_origin(name, raw)
        )
        if identity_error is not None:
            errors.append(
                "project instance unreceipted generated-state identity could not be "
                f"classified safely: {relative}: {identity_error}"
            )
            continue
        if not recognized:
            # Only a safely bound exact origin marker establishes framework
            # ownership. An ordinary unmarked same-name file remains outside
            # the generated-state ownership claim.
            continue
        if name in contract_model.optional_state_filenames("immutable"):
            errors.append(
                "project instance contains unreceipted/orphan framework-generated "
                f"state in the immutable partition: {relative}. Preserve any "
                "project-specific material separately, authorize and remove the orphan "
                "through a reviewed project-specific cleanup, then enable the optional "
                "surface through candidate-input refresh and accept the canonical "
                "renderer bytes; do not restore project-specific content into the "
                "generated immutable file"
            )
        else:
            errors.append(
                "project instance contains unreceipted/orphan framework-generated "
                f"state in the mutable partition: {relative}. Preserve any needed "
                "content outside the target, authorize and remove the orphan through a "
                "reviewed project-specific cleanup, then enable the optional surface "
                "through candidate-input refresh and restore sanitized content into the "
                "receipt-declared mutable file while preserving its generated-state "
                "origin marker"
            )


def _validate_selected_file_sets(
    context: LintContext,
    payload: dict[str, object],
    managed_files: list[str],
    immutable_files: list[str],
    mutable_files: list[str],
    errors: list[str],
) -> None:
    answers = payload.get("answers")
    project_kind = payload.get("project_kind")
    runtime = payload.get("runtime")
    runtime_wrappers = payload.get("runtime_wrappers")
    if (
        not isinstance(answers, dict)
        or not isinstance(project_kind, str)
        or project_kind not in contract_model.PROJECT_KINDS
        or (runtime is not None and not isinstance(runtime, str))
        or not isinstance(runtime_wrappers, list)
        or any(not isinstance(item, str) for item in runtime_wrappers)
    ):
        return
    policy = contract_model.project_layout_policy(project_kind)
    if policy.manages_runtime_entrypoint and runtime not in project_bootstrap.ENTRYPOINT_TEMPLATES:
        return
    try:
        expected_managed, expected_immutable, expected_mutable = (
            project_bootstrap.project_instance_file_sets(
                answers=answers,
                runtime=runtime,
                project_kind=project_kind,
                contract_root_ref=context.contract_root_ref,
                runtime_wrappers=runtime_wrappers,
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"selected project file sets could not be derived: {exc}")
        return
    for label, actual, expected in (
        ("managed_files", managed_files, expected_managed),
        ("immutable_files", immutable_files, expected_immutable),
        ("mutable_files", mutable_files, expected_mutable),
    ):
        if actual != expected:
            errors.append(
                f"project instance manifest {label} does not match the selected framework"
            )


def _rerender_immutable_outputs(
    context: LintContext,
    payload: dict[str, object] | None,
    errors: list[str],
) -> dict[str, str]:
    if payload is None:
        return {}
    answers = payload.get("answers")
    runtime = payload.get("runtime")
    framework_reference = payload.get("framework_reference")
    project_kind = payload.get("project_kind")
    runtime_wrappers = payload.get("runtime_wrappers")
    if (
        not isinstance(answers, dict)
        or (runtime is not None and not isinstance(runtime, str))
        or not isinstance(framework_reference, str)
        or not isinstance(project_kind, str)
        or project_kind not in contract_model.PROJECT_KINDS
        or not isinstance(runtime_wrappers, list)
        or any(not isinstance(item, str) for item in runtime_wrappers)
    ):
        return {}
    render_date = answers.get("date")
    if not isinstance(render_date, str):
        return {}
    try:
        return project_bootstrap.render_output_files(
            answers,
            runtime,
            framework_reference,
            project_kind=project_kind,
            contract_root_ref=context.contract_root_ref,
            effective_date=render_date,
            runtime_wrappers=runtime_wrappers,
        )
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"immutable project outputs could not be rerendered: {exc}")
        return {}


def _validate_recorded_output_digests(
    context: LintContext,
    manifest: dict[str, Any],
    immutable_files: list[str],
    errors: list[str],
) -> None:
    output_digests = manifest.get("output_digests")
    if not isinstance(output_digests, dict):
        errors.append("project instance manifest output_digests must be an object")
        return
    if set(output_digests) != set(immutable_files):
        errors.append(
            "project instance manifest output_digests must exactly cover immutable_files"
        )
    for output, digest in output_digests.items():
        errors.extend(validate_digest(digest, f"output_digests.{output}"))
        output_path, path_error = safe_project_file(
            context.project_root,
            output,
            f"output_digests.{output}",
        )
        if path_error:
            errors.append(path_error)
            continue
        if output_path is None:
            continue
        path_errors = safe_paths.bounded_input_errors(
            output_path,
            context.project_root,
            description=f"immutable generated output {output}",
        )
        errors.extend(path_errors)
        if path_errors or not output_path.is_file() or output_path.is_symlink():
            errors.append(f"immutable generated output is missing or not regular: {output}")
            continue
        try:
            actual = safe_paths.read_regular_file_bytes(
                output_path,
                description=f"immutable generated output {output}",
            )
        except (OSError, ValueError) as exc:
            errors.append(f"immutable generated output could not be read: {output}: {exc}")
            continue
        if isinstance(digest, str) and hashlib.sha256(actual).hexdigest() != digest:
            errors.append(f"immutable generated output digest mismatch: {output}")


def _validate_rerendered_outputs(
    context: LintContext,
    manifest: dict[str, Any],
    immutable_files: list[str],
    rerendered_outputs: dict[str, str],
    errors: list[str],
) -> None:
    output_digests = manifest.get("output_digests")
    if not isinstance(output_digests, dict):
        return
    for output in immutable_files:
        output_path, path_error = safe_project_file(
            context.project_root,
            output,
            f"output_digests.{output}",
        )
        if path_error or output_path is None:
            continue
        try:
            actual = safe_paths.read_regular_file_bytes(
                output_path,
                description=f"immutable generated output {output}",
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
        digest = output_digests.get(output)
        expected_content = rerendered_outputs.get(output)
        if expected_content is None:
            errors.append(
                f"immutable generated output is not derived from retained project input: {output}"
            )
            continue
        expected_bytes = expected_content.encode("utf-8")
        if actual != expected_bytes:
            errors.append(
                f"immutable generated output does not match retained project input: {output}"
            )
        if (
            isinstance(digest, str)
            and digest != hashlib.sha256(expected_bytes).hexdigest()
        ):
            errors.append(
                "immutable generated output digest does not match rerendered retained "
                f"project input: {output}"
            )


def _validate_recorded_generation_sources(
    manifest: dict[str, Any],
    immutable_files: list[str],
    errors: list[str],
) -> None:
    generation_sources = manifest.get("generation_sources")
    if not isinstance(generation_sources, dict):
        errors.append("project instance manifest generation_sources must be an object")
        return
    if set(generation_sources) != set(immutable_files):
        errors.append(
            "project instance manifest generation_sources must exactly cover immutable_files"
        )
    for output, records in generation_sources.items():
        if not isinstance(records, list) or not records:
            errors.append(f"generation_sources.{output} must be a non-empty list")
            continue
        for index, record in enumerate(records):
            label = f"generation_sources.{output}[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{label} must be an object")
                continue
            unknown = sorted(set(record) - GENERATION_SOURCE_KEYS)
            missing = sorted(GENERATION_SOURCE_KEYS - set(record))
            if unknown:
                errors.append(f"{label} has unknown keys: {', '.join(unknown)}")
            if missing:
                errors.append(f"{label} is missing keys: {', '.join(missing)}")
                continue
            errors.extend(_recorded_relative_path_errors(record.get("path"), f"{label}.path"))
            errors.extend(validate_digest(record.get("sha256"), f"{label}.sha256"))


def _validate_generation_sources(
    context: LintContext,
    manifest: dict[str, Any],
    immutable_files: list[str],
    runtime: str | None,
    framework_root: Path,
    errors: list[str],
) -> None:
    generation_sources = manifest.get("generation_sources")
    if not isinstance(generation_sources, dict):
        errors.append("project instance manifest generation_sources must be an object")
        return
    if set(generation_sources) != set(immutable_files):
        errors.append(
            "project instance manifest generation_sources must exactly cover immutable_files"
        )
    for output, records in generation_sources.items():
        if not isinstance(records, list) or not records:
            errors.append(f"generation_sources.{output} must be a non-empty list")
            continue
        try:
            expected_sources = project_bootstrap.generation_sources_for_output(
                output,
                runtime,
            )
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
            continue
        actual_sources: list[str] = []
        valid_records: list[tuple[str, object]] = []
        for index, record in enumerate(records):
            label = f"generation_sources.{output}[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{label} must be an object")
                continue
            unknown = sorted(set(record) - GENERATION_SOURCE_KEYS)
            missing = sorted(GENERATION_SOURCE_KEYS - set(record))
            if unknown:
                errors.append(f"{label} has unknown keys: {', '.join(unknown)}")
            if missing:
                errors.append(f"{label} is missing keys: {', '.join(missing)}")
                continue
            source = record.get("path")
            try:
                normalized = safe_paths.normalize_repo_relative_path(
                    source if isinstance(source, str) else "",
                    framework_root,
                    description=f"{label}.path",
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            actual_sources.append(normalized)
            valid_records.append((normalized, record.get("sha256")))
        if tuple(actual_sources) != expected_sources:
            errors.append(
                f"generation sources do not match canonical sources for {output}: "
                f"expected {list(expected_sources)}, found {actual_sources}"
            )
            continue
        for index, (source, digest) in enumerate(valid_records):
            label = f"generation_sources.{output}[{index}]"
            errors.extend(validate_digest(digest, f"{label}.sha256"))
            source_path = framework_root / source
            source_errors = safe_paths.bounded_input_errors(
                source_path,
                framework_root,
                description=f"generation source {source}",
            )
            errors.extend(source_errors)
            if source_errors or not source_path.is_file() or source_path.is_symlink():
                errors.append(f"generation source is missing or not regular: {source}")
                continue
            try:
                actual_digest = file_sha256(
                    source_path,
                    description=f"generation source {source}",
                )
            except (OSError, ValueError) as exc:
                errors.append(f"generation source could not be read: {source}: {exc}")
                continue
            if isinstance(digest, str) and digest != actual_digest:
                errors.append(f"generation-source digest is stale for {output}: {source}")


def _preimage_result(
    *,
    errors: list[str],
    warnings: list[str],
    context: LintContext | None,
    manifest: dict[str, Any] | None = None,
    retained_input: dict[str, object] | None = None,
    input_raw: bytes | None = None,
    managed_files: list[str] | None = None,
    immutable_files: list[str] | None = None,
    mutable_files: list[str] | None = None,
    authority_module_drift_errors: list[str] | None = None,
) -> dict[str, object]:
    """Return the closed stage-A result consumed by refresh and conformance."""

    return {
        "errors": errors,
        "warnings": warnings,
        "context": context,
        "manifest": manifest,
        "retained_input": retained_input,
        "input_raw": input_raw,
        "managed_files": managed_files or [],
        "immutable_files": immutable_files or [],
        "mutable_files": mutable_files or [],
        "authority_module_drift_errors": authority_module_drift_errors or [],
    }


def validate_recorded_preimage(
    project_root: Path,
    contract_root_ref: str = ".",
    *,
    expected_project_kind: str | None = None,
) -> dict[str, object]:
    """Validate only the immutable recorded project-instance preimage.

    This stage deliberately does not ask whether the recorded runtime, framework
    reference, generator sources, or framework identities are current in the
    selected checkout. That separation lets refresh plan an explicit revision
    away from stale or removed generation targets without weakening preimage
    integrity.
    """

    project_root = project_root.expanduser().resolve(strict=False)
    errors: list[str] = []
    warnings: list[str] = []
    contract_root, contract_root_error = contract_root_path(project_root, contract_root_ref)
    if contract_root_error:
        return _preimage_result(
            errors=[contract_root_error],
            warnings=warnings,
            context=None,
        )
    context = LintContext(
        project_root=project_root,
        contract_root=contract_root,
        contract_root_ref=contract_root_ref,
        expected_project_kind=expected_project_kind,
    )
    # The receipt owns the project instance and therefore always lives at the
    # exact project root. Its contract_root field locates retained authority and
    # input below that boundary; no contract-root-local receipt alias is consulted.
    manifest_path = project_root / MANIFEST_NAME
    manifest_errors = safe_paths.bounded_input_errors(
        manifest_path,
        project_root,
        description="project instance manifest input",
    )
    errors.extend(manifest_errors)
    if manifest_errors:
        return _preimage_result(
            errors=errors,
            warnings=warnings,
            context=context,
        )
    manifest, load_errors = load_manifest(manifest_path)
    errors.extend(load_errors)
    if manifest is None:
        return _preimage_result(
            errors=errors,
            warnings=warnings,
            context=context,
        )
    schema_error = schema_version_preflight_error(manifest)
    if schema_error is not None:
        return _preimage_result(
            errors=[schema_error],
            warnings=warnings,
            context=context,
            manifest=manifest,
        )
    input_schema_error = project_input_schema_version_preflight_error(manifest)
    if input_schema_error is not None:
        return _preimage_result(
            errors=[input_schema_error],
            warnings=warnings,
            context=context,
            manifest=manifest,
        )
    contract_format_error = project_contract_format_preflight_error(manifest)
    if contract_format_error is not None:
        return _preimage_result(
            errors=[contract_format_error],
            warnings=warnings,
            context=context,
            manifest=manifest,
        )

    _validate_closed_manifest(manifest, errors)
    contract_root_error = _selected_contract_root_preflight_error(context, manifest)
    if contract_root_error is not None:
        errors.append(contract_root_error)
        return _preimage_result(
            errors=errors,
            warnings=warnings,
            context=context,
            manifest=manifest,
        )
    _validate_recorded_identity(context, manifest, errors)
    retained_input, input_raw, retained_input_lifecycle_error = _load_and_validate_input(
        context,
        manifest,
        errors,
    )
    if retained_input_lifecycle_error is not None:
        return _preimage_result(
            errors=[retained_input_lifecycle_error],
            warnings=warnings,
            context=context,
            manifest=manifest,
            retained_input=retained_input,
            input_raw=input_raw,
        )
    managed_files, immutable_files, mutable_files = _validate_recorded_file_sets(
        context,
        manifest,
        retained_input,
        errors,
    )
    authority_module_drift_errors = _validate_recorded_authority_module_digests(
        context,
        manifest,
        retained_input,
        managed_files,
        errors,
    )
    _validate_mutable_state_origins(context, mutable_files, errors)
    _validate_unreceipted_generated_state(context, managed_files, errors)
    _validate_string_list(
        manifest.get("active_profiles"),
        "project instance manifest active_profiles",
        errors,
        require_sorted=False,
    )
    _validate_recorded_output_digests(
        context,
        manifest,
        immutable_files,
        errors,
    )
    _validate_recorded_generation_sources(
        manifest,
        immutable_files,
        errors,
    )
    return _preimage_result(
        errors=errors,
        warnings=warnings,
        context=context,
        manifest=manifest,
        retained_input=retained_input,
        input_raw=input_raw,
        managed_files=managed_files,
        immutable_files=immutable_files,
        mutable_files=mutable_files,
        authority_module_drift_errors=authority_module_drift_errors,
    )


def validate_selected_checkout(
    preimage: dict[str, object],
    *,
    framework_root: Path = FRAMEWORK_ROOT,
) -> dict[str, list[str]]:
    """Validate stage-A evidence against the selected current checkout."""

    errors: list[str] = []
    warnings: list[str] = []
    preimage_errors = preimage.get("errors")
    context = preimage.get("context")
    manifest = preimage.get("manifest")
    retained_input = preimage.get("retained_input")
    managed_files = preimage.get("managed_files")
    immutable_files = preimage.get("immutable_files")
    mutable_files = preimage.get("mutable_files")
    if (
        not isinstance(context, LintContext)
        or not isinstance(manifest, dict)
        or not isinstance(retained_input, dict)
        or not isinstance(managed_files, list)
        or not all(isinstance(item, str) for item in managed_files)
        or not isinstance(immutable_files, list)
        or not all(isinstance(item, str) for item in immutable_files)
        or not isinstance(mutable_files, list)
        or not all(isinstance(item, str) for item in mutable_files)
    ):
        if isinstance(preimage_errors, list) and preimage_errors:
            return {"errors": errors, "warnings": warnings}
        return {
            "errors": ["selected-checkout validation requires a valid recorded-preimage result"],
            "warnings": warnings,
        }

    framework_root = framework_root.expanduser().resolve(strict=False)
    errors.extend(
        "retained project input: " + error
        for error in project_input.selected_project_input_errors(
            retained_input,
            repo_root=framework_root,
        )
    )
    _validate_selected_identity(context, manifest, framework_root, errors, warnings)
    _validate_selected_file_sets(
        context,
        retained_input,
        managed_files,
        immutable_files,
        mutable_files,
        errors,
    )

    answers = retained_input.get("answers")
    project_kind = retained_input.get("project_kind")
    if (
        isinstance(answers, dict)
        and isinstance(project_kind, str)
        and project_kind in contract_model.PROJECT_KINDS
    ):
        expected_profiles = project_bootstrap.active_project_profiles(
            answers,
            project_kind=project_kind,
        )
        active_profiles = manifest.get("active_profiles")
        if active_profiles != expected_profiles:
            errors.append(
                "project instance manifest active_profiles must exactly match the selected framework"
            )

    runtime = retained_input.get("runtime")
    runtime_wrappers = retained_input.get("runtime_wrappers")
    try:
        policy = contract_model.project_layout_policy(project_kind)
    except ValueError:
        policy = None
    if (
        policy is not None
        and policy.runtime_wrappers_allowed
        and isinstance(runtime, str)
        and isinstance(runtime_wrappers, list)
        and all(isinstance(item, str) for item in runtime_wrappers)
        and runtime in integration_registry.family_names(framework_root)
    ):
        try:
            expected_wrapper_outputs = integration_registry.wrapper_output_map(
                runtime,
                runtime_wrappers,
                framework_root,
            )
        except ValueError:
            expected_wrapper_outputs = None
        if (
            expected_wrapper_outputs is not None
            and manifest.get("runtime_wrapper_outputs") != expected_wrapper_outputs
        ):
            errors.append(
                "project instance manifest runtime_wrapper_outputs does not match "
                "the selected framework"
            )
    runtime_available = policy is not None and (
        not policy.manages_runtime_entrypoint
        or (
            isinstance(runtime, str)
            and runtime in project_bootstrap.ENTRYPOINT_TEMPLATES
        )
    )
    if runtime_available:
        rerendered_outputs = _rerender_immutable_outputs(
            context,
            retained_input,
            errors,
        )
        _validate_rerendered_outputs(
            context,
            manifest,
            immutable_files,
            rerendered_outputs,
            errors,
        )
        _validate_generation_sources(
            context,
            manifest,
            immutable_files,
            runtime if isinstance(runtime, str) else None,
            framework_root,
            errors,
        )
    return {"errors": errors, "warnings": warnings}


def lint_instance(
    project_root: Path,
    contract_root_ref: str = ".",
    *,
    framework_root: Path = FRAMEWORK_ROOT,
    expected_project_kind: str | None = None,
) -> dict[str, list[str]]:
    """Compose recorded-preimage integrity and selected-checkout currency."""

    preimage = validate_recorded_preimage(
        project_root,
        contract_root_ref,
        expected_project_kind=expected_project_kind,
    )
    preimage_errors = preimage["errors"]
    preimage_warnings = preimage["warnings"]
    errors = list(preimage_errors) if isinstance(preimage_errors, list) else []
    warnings = list(preimage_warnings) if isinstance(preimage_warnings, list) else []
    selected = validate_selected_checkout(preimage, framework_root=framework_root)
    errors.extend(selected["errors"])
    warnings.extend(selected["warnings"])
    return {"errors": errors, "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lint PROJECT_INSTANCE.json against its retained project input and "
            "selected framework checkout."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--project-root", default=".", help="Project work root.")
    parser.add_argument(
        "--contract-root",
        default=".",
        help="Safe project-relative contract root.",
    )
    parser.add_argument(
        "--project-kind",
        choices=sorted(contract_model.PROJECT_KINDS),
        help="Expected project kind.",
    )
    parser.add_argument(
        "--framework-root",
        default=str(FRAMEWORK_ROOT),
        help="Framework checkout selected for current-state verification.",
    )
    args = parser.parse_args(argv)
    result = lint_instance(
        Path(args.project_root),
        args.contract_root,
        framework_root=Path(args.framework_root),
        expected_project_kind=args.project_kind,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
