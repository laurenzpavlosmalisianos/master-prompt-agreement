#!/usr/bin/env python3

"""Retained, replayable input contract for one generated project instance."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import hashlib
import json
from pathlib import Path, PureWindowsPath
import integration_registry
import project_contract_model as contract_model
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
INPUT_NAME = "PROJECT_INPUT.json"
REVISION_POLICIES = frozenset({"live", "pinned"})
INPUT_KEYS = frozenset(
    {
        "schema_version",
        "project_kind",
        "contract_root",
        "runtime",
        "runtime_wrappers",
        "framework_reference",
        "framework_revision_policy",
        "answers",
    }
)


def canonical_project_input_bytes(payload: Mapping[str, object]) -> bytes:
    """Return the stable serialized representation used by the renderer."""

    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def project_input_sha256(raw: bytes) -> str:
    """Return the exact-byte digest recorded by the project-instance receipt."""

    return hashlib.sha256(raw).hexdigest()


def _contract_root_errors(value: object, project_root: Path | None) -> list[str]:
    if not isinstance(value, str):
        return ["project input contract_root must be a string"]
    if value == ".":
        return []

    errors = safe_paths.project_relative_reference_errors(
        value,
        "project input contract_root",
    )
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if (
        "\\" in value
        or "://" in value
        or path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or not path.parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or ".." in windows_path.parts
    ):
        errors.append("project input contract_root must be '.' or a safe project-relative path")
        return errors

    if project_root is not None:
        try:
            safe_paths.normalize_repo_relative_path(
                value,
                project_root,
                description="project input contract_root",
            )
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def _input_placement_errors(
    *,
    payload: Mapping[str, object],
    project_root: Path,
    input_path: Path,
) -> list[str]:
    errors = safe_paths.bounded_input_errors(
        input_path,
        project_root,
        description="retained project input",
    )
    if errors:
        return errors
    if input_path.exists() and (not input_path.is_file() or input_path.is_symlink()):
        return ["retained project input must be a regular non-symlink file"]

    try:
        input_path.relative_to(project_root)
    except ValueError:
        return ["retained project input must stay inside the project root"]

    try:
        policy = contract_model.project_layout_policy(payload.get("project_kind"))
    except ValueError:
        return []
    if not policy.retained_input_within_contract_root:
        return []
    contract_root_ref = payload.get("contract_root")
    if not isinstance(contract_root_ref, str):
        return []
    contract_root = (
        project_root
        if contract_root_ref == "."
        else project_root / contract_root_ref
    )
    if not safe_paths.path_within_root(input_path, contract_root):
        return [
            f"{policy.kind} retained project input must be inside the selected contract root"
        ]
    return []


def schema_version_preflight_error(payload: object) -> str | None:
    """Reject non-current retained input before derivative validation."""

    if not isinstance(payload, dict):
        return None
    version = payload.get("schema_version")
    if type(version) is int and version == SCHEMA_VERSION:
        return None
    if "schema_version" not in payload:
        issue = "is missing"
    elif type(version) is not int:
        issue = "is malformed; expected a non-boolean integer"
    elif version > SCHEMA_VERSION:
        return (
            f"project input schema_version {version} is newer than the supported "
            f"schema_version {SCHEMA_VERSION}; use a framework checkout that supports "
            f"schema_version {version} before running current-schema checks"
        )
    else:
        issue = f"is {version}; expected {SCHEMA_VERSION}"
    return (
        f"project input schema_version {issue}. The current-only lifecycle supports "
        f"exactly schema_version {SCHEMA_VERSION} and does not migrate or rewrite "
        "other retained-input formats; perform a reviewed project-specific manual "
        "update before running current-schema checks"
    )


def validate_project_input_structure(
    payload: object,
    *,
    project_root: Path | None = None,
    input_path: Path | None = None,
) -> list[str]:
    """Validate the closed retained-input schema and its filesystem placement.

    Semantic validation of the materialized ``answers`` remains owned by
    ``project_bootstrap.validate_answers``. Keeping that dependency one-way
    lets the bootstrap renderer import this module without a cycle.
    """

    if not isinstance(payload, dict):
        return ["project input must be a JSON object"]

    schema_error = schema_version_preflight_error(payload)
    if schema_error is not None:
        return [schema_error]

    errors: list[str] = []
    keys = set(payload)
    unknown = sorted(keys - INPUT_KEYS, key=str)
    missing = sorted(INPUT_KEYS - keys)
    if unknown:
        errors.append(
            "project input has unknown keys: "
            + ", ".join(str(key) for key in unknown)
        )
    if missing:
        errors.append(f"project input is missing keys: {', '.join(missing)}")

    project_kind = payload.get("project_kind")
    try:
        policy = contract_model.project_layout_policy(project_kind)
    except ValueError:
        policy = None
        errors.append(
            "project input project_kind must be one of: "
            + ", ".join(sorted(contract_model.PROJECT_KINDS))
        )

    errors.extend(_contract_root_errors(payload.get("contract_root"), project_root))

    runtime = payload.get("runtime")
    if policy is not None and policy.runtime_forbidden:
        if runtime is not None:
            errors.append(f"{policy.kind} project input runtime must be null")
    elif policy is not None and policy.runtime_required:
        if not isinstance(runtime, str) or not runtime:
            errors.append(
                f"{policy.kind} project input runtime must be a non-empty string"
            )
    elif runtime is not None and not isinstance(runtime, str):
        errors.append("project input runtime must be a string or null")

    runtime_wrappers = payload.get("runtime_wrappers")
    if not isinstance(runtime_wrappers, list) or any(
        not isinstance(item, str) or not integration_registry.WRAPPER_NAME_RE.fullmatch(item)
        for item in runtime_wrappers
    ):
        errors.append(
            "project input runtime_wrappers must be a list of wrapper ID strings"
        )
    else:
        if runtime_wrappers != sorted(runtime_wrappers):
            errors.append("project input runtime_wrappers must be sorted")
        if len(runtime_wrappers) != len(set(runtime_wrappers)):
            errors.append("project input runtime_wrappers must not contain duplicates")
        if (
            policy is not None
            and not policy.runtime_wrappers_allowed
            and runtime_wrappers
        ):
            errors.append(
                f"{policy.kind} project input runtime_wrappers must be empty"
            )

    framework_reference = payload.get("framework_reference")
    if not isinstance(framework_reference, str):
        errors.append("project input framework_reference must be a string")
    else:
        errors.extend(
            f"project input framework_reference: {error}"
            for error in safe_paths.framework_reference_errors(framework_reference)
        )

    revision_policy = payload.get("framework_revision_policy")
    if revision_policy not in REVISION_POLICIES:
        errors.append(
            "project input framework_revision_policy must be one of: "
            + ", ".join(sorted(REVISION_POLICIES))
        )

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        errors.append("project input answers must be a JSON object")
    else:
        answer_unknown = sorted(set(answers) - contract_model.ALLOWED_KEYS, key=str)
        if answer_unknown:
            errors.append(
                "project input answers have unknown keys: "
                + ", ".join(str(key) for key in answer_unknown)
            )
        render_date = answers.get("date")
        if not isinstance(render_date, str):
            errors.append("project input answers.date must be an explicit ISO date string")
        else:
            try:
                normalized_date = date.fromisoformat(render_date).isoformat()
            except ValueError:
                errors.append("project input answers.date must be a valid ISO date")
            else:
                if render_date != normalized_date:
                    errors.append("project input answers.date must use canonical YYYY-MM-DD form")

    if project_root is not None and input_path is not None:
        errors.extend(
            _input_placement_errors(
                payload=payload,
                project_root=project_root,
                input_path=input_path,
            )
        )
    elif input_path is not None:
        errors.append("project_root is required when input_path is supplied")
    return errors


def selected_project_input_errors(
    payload: object,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """Validate runtime and wrapper availability in one selected checkout."""

    if not isinstance(payload, dict):
        return ["project input must be a JSON object"]
    if schema_version_preflight_error(payload) is not None:
        return []
    try:
        policy = contract_model.project_layout_policy(payload.get("project_kind"))
    except ValueError:
        return []
    if not policy.manages_runtime_entrypoint:
        return []
    root = repo_root or REPO_ROOT
    runtime = payload.get("runtime")
    runtimes = integration_registry.family_names(root)
    if runtime not in runtimes:
        return [
            f"{policy.kind} project input runtime must be one of: "
            + ", ".join(runtimes)
        ]
    wrappers = payload.get("runtime_wrappers")
    if not isinstance(wrappers, list) or any(
        not isinstance(item, str) for item in wrappers
    ):
        return []
    try:
        integration_registry.wrapper_output_map(runtime, wrappers, root)
    except ValueError as exc:
        return [str(exc)]
    return []


def validate_project_input(
    payload: object,
    *,
    project_root: Path | None = None,
    input_path: Path | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    """Validate the closed input and its selected-checkout dependencies."""

    structure_errors = validate_project_input_structure(
        payload,
        project_root=project_root,
        input_path=input_path,
    )
    if not isinstance(payload, dict) or schema_version_preflight_error(payload) is not None:
        return structure_errors
    return [
        *structure_errors,
        *selected_project_input_errors(payload, repo_root=repo_root),
    ]


def render_project_input(
    *,
    project_kind: str,
    contract_root: str,
    runtime: str | None,
    framework_reference: str,
    framework_revision_policy: str,
    answers: Mapping[str, object],
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> str:
    """Render one closed, replayable project-input document."""

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "project_kind": project_kind,
        "contract_root": contract_root,
        "runtime": runtime,
        "runtime_wrappers": sorted(runtime_wrappers),
        "framework_reference": framework_reference,
        "framework_revision_policy": framework_revision_policy,
        "answers": dict(answers),
    }
    errors = validate_project_input(payload)
    if errors:
        raise ValueError("invalid project input: " + "; ".join(errors))
    return canonical_project_input_bytes(payload).decode("utf-8")


def load_project_input(
    path: Path,
) -> tuple[dict[str, object] | None, bytes | None, list[str]]:
    """Read a bounded retained-input file without accepting duplicate keys."""

    try:
        raw = safe_paths.read_regular_file_bytes(path, description="retained project input")
    except FileNotFoundError:
        return None, None, [f"missing retained project input: {path}"]
    except ValueError as exc:
        return None, None, [f"retained project input is not a bounded regular input: {exc}"]
    except OSError as exc:
        return None, None, [f"retained project input could not be read: {exc}"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, raw, [f"retained project input must be valid UTF-8: {exc}"]
    try:
        payload = safe_paths.loads_json_no_duplicates(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, raw, [f"retained project input is invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, raw, ["retained project input must be a JSON object"]
    return payload, raw, []


__all__ = [
    "INPUT_KEYS",
    "INPUT_NAME",
    "REVISION_POLICIES",
    "SCHEMA_VERSION",
    "canonical_project_input_bytes",
    "load_project_input",
    "project_input_sha256",
    "render_project_input",
    "schema_version_preflight_error",
    "selected_project_input_errors",
    "validate_project_input",
    "validate_project_input_structure",
]
