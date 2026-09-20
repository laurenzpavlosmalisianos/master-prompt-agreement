#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

import bounded_subprocess
import integration_registry
import markdown_structure
import product_manifest
import project_bootstrap
import project_contract_model as contract_model
import project_instance_lint
import safe_paths


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PROFILE_REGISTRY = FRAMEWORK_ROOT / "conformance" / "profiles.json"
PROFILE_SCHEMA = FRAMEWORK_ROOT / "conformance" / "profile.schema.json"
ENTRYPOINTS = ("AGENTS.md", "CLAUDE.md")
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CHECK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
CONFORMANCE_SUBJECTS = {"framework", "project"}
HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
REGISTRY_KEYS = {"schema_version", "spec_version", "checks", "profiles"}
PROFILE_KEYS = {
    "description",
    "extends",
    "id",
    "required_checks",
    "required_directories",
    "required_files",
    "subject",
}
EXIT_CONFORMANCE_FAILURE = 1
EXIT_INVALID_INVOCATION = 2
EXIT_INVALID_METADATA = 3
COMMAND_TIMEOUT_SECONDS = 60.0
COMMAND_MAX_TIMEOUT_SECONDS = bounded_subprocess.HARD_MAX_TIMEOUT_SECONDS
COMMAND_TERMINATION_GRACE_SECONDS = 1.0
NESTED_CHILD_SHUTDOWN_MARGIN_SECONDS = 5.0
MAX_COMMAND_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
MAX_PROTOCOL_DIAGNOSTIC_BYTES = 64 * 1024
PRODUCT_LOCAL_METADATA_ROOT_ENTRIES = frozenset({".git"})
PYTHON_CHILD_STARTUP_FLAGS = ("-E", "-S", "-B")
_EXACT_TREE_OPEN_SUPPORTS_DIR_FD = os.open in getattr(os, "supports_dir_fd", set())
_EXACT_TREE_STAT_SUPPORTS_DIR_FD = os.stat in getattr(os, "supports_dir_fd", set())
_EXACT_TREE_STAT_SUPPORTS_NOFOLLOW = os.stat in getattr(
    os,
    "supports_follow_symlinks",
    set(),
)
_EXACT_TREE_SCANDIR_SUPPORTS_FD = os.scandir in getattr(os, "supports_fd", set())


def nested_child_deadline_seconds(parent_timeout_seconds: float) -> float:
    """Reserve cleanup time inside one parent-owned bounded child."""

    if (
        not isinstance(parent_timeout_seconds, (int, float))
        or isinstance(parent_timeout_seconds, bool)
        or not math.isfinite(float(parent_timeout_seconds))
        or parent_timeout_seconds <= NESTED_CHILD_SHUTDOWN_MARGIN_SECONDS
        or parent_timeout_seconds > COMMAND_MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "nested child parent timeout must be finite, exceed the shutdown "
            f"margin, and be at most {COMMAND_MAX_TIMEOUT_SECONDS:g}"
        )
    return float(parent_timeout_seconds) - NESTED_CHILD_SHUTDOWN_MARGIN_SECONDS


def trusted_python_child(script: Path, *args: str) -> list[str]:
    """Build one isolated command for a trusted framework Python child."""

    return [
        sys.executable,
        *PYTHON_CHILD_STARTUP_FLAGS,
        "--",
        str(script),
        *args,
    ]


@dataclass
class _ProfileMetadataContext:
    checks: dict[str, Any]
    check_subjects: dict[str, str]
    errors: list[str]
    profile_ids: set[str]
    profile_subjects: dict[str, str]
    graph: dict[str, list[str]]


@dataclass(frozen=True)
class CheckOutcome:
    """One check result with semantic diagnostics kept separate from protocol failure."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    protocol_failure: str | None = None
    warnings_fail: bool = False

    def report_errors(self) -> list[str]:
        """Return semantic errors only; protocol failures have their own field."""

        return ordered_unique(self.errors)

    def report_warnings(self) -> list[str]:
        return ordered_unique(self.warnings)

    def failed(self) -> bool:
        return bool(
            self.errors
            or self.protocol_failure is not None
            or (self.warnings_fail and self.warnings)
        )


@dataclass(frozen=True)
class ExpandedProfileClaim:
    """One selected profile's inherited claims before union execution."""

    profile_id: str
    subject: str
    required_checks: tuple[str, ...]
    required_files: tuple[str, ...]
    required_directories: tuple[str, ...]

    def report_claim(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "subject": self.subject,
            "required_checks": list(self.required_checks),
            "required_files": list(self.required_files),
            "required_directories": list(self.required_directories),
        }


@dataclass(frozen=True)
class CommandCapture:
    """Bounded child status with stdout and stderr retained as separate streams."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    transport_failure: str | None = None
    stdout_decode_failure: str | None = None
    stderr_decode_failure: str | None = None

    def combined_output(self) -> str:
        return "\n".join(
            part for part in (self.stdout, self.stderr) if part
        )


@dataclass(frozen=True)
class _ExactTreeDirectoryEdge:
    """One retained parent/name binding for a traversed product directory."""

    descriptor: int
    parent_descriptor: int
    name: str
    relative: str
    identity: tuple[int, int, int]


@dataclass(frozen=True)
class _ExactTreeEntryEdge:
    """One observed product entry retained for no-follow name rechecks."""

    parent_descriptor: int
    name: str
    relative: str
    identity: tuple[int, int, int]


@dataclass(frozen=True)
class _ExactTreeDirectorySnapshot:
    """One bounded directory-name snapshot retained for terminal comparison."""

    descriptor: int
    relative: str
    names: frozenset[str]


class _ExactProductTreeFailure(Exception):
    """A bounded exact-tree traversal found its first unsafe condition."""


CheckReturn = list[str] | CheckOutcome
ReportItemRenderer = Callable[[object], str | None]


def ordered_unique(values: list[str] | tuple[str, ...]) -> list[str]:
    """Return deterministic first-owner diagnostics without reordering them."""

    return list(dict.fromkeys(values))


def load_json_object(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = safe_paths.read_regular_file_bytes(path, description=label)
    except FileNotFoundError:
        try:
            display_path = path.relative_to(FRAMEWORK_ROOT)
        except ValueError:
            display_path = path
        return None, [f"{label} is missing: {display_path}"]
    except ValueError as exc:
        return None, [f"{label} is not a bounded regular input: {exc}"]
    except OSError as exc:
        return None, [f"{label} could not be read: {exc}"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [f"{label} must be valid UTF-8: {exc}"]
    try:
        data = safe_paths.loads_json_no_duplicates(text)
    except ValueError as exc:
        return None, [f"{label} is invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{label} must be a JSON object"]
    return data, []


def rel_path_error(value: str, label: str) -> str | None:
    if safe_paths.PATH_CONTROL_RE.search(value):
        return f"{label} must not contain control characters: {value!r}"
    path = Path(value)
    if path.is_absolute() or value.startswith("~") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return f"{label} must be a relative repository path: {value}"
    if "\\" in value:
        return f"{label} must use POSIX separators: {value}"
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return f"{label} must not contain empty, current, or parent-directory segments: {value}"
    return None


def validate_schema_file(schema: dict[str, Any] | None) -> list[str]:
    if schema is None:
        return []
    errors: list[str] = []
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("conformance profile schema must declare JSON Schema draft 2020-12")
    if schema.get("additionalProperties") is not False:
        errors.append("conformance profile schema must reject unknown top-level fields")
    required = schema.get("required")
    if (
        not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or len(required) != len(set(required))
        or set(required) != {"schema_version", "spec_version", "checks", "profiles"}
    ):
        errors.append("conformance profile schema required fields must match profiles.json top-level fields")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        errors.append("conformance profile schema must define properties")
    elif set(properties) != REGISTRY_KEYS:
        errors.append("conformance profile schema properties must match profiles.json top-level fields")
    else:
        profiles_schema = properties.get("profiles")
        item_schema = profiles_schema.get("items") if isinstance(profiles_schema, dict) else None
        profile_properties = item_schema.get("properties") if isinstance(item_schema, dict) else None
        if not isinstance(profile_properties, dict):
            errors.append("conformance profile schema must define profile item properties")
        else:
            for field in ("extends", "required_checks", "required_directories", "required_files"):
                field_schema = profile_properties.get(field)
                if not isinstance(field_schema, dict) or field_schema.get("uniqueItems") is not True:
                    errors.append(f"conformance profile schema {field} must enforce uniqueItems")
    return errors


def _registry_header_errors(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown_top_level = sorted(set(registry) - REGISTRY_KEYS)
    missing_top_level = sorted(REGISTRY_KEYS - set(registry))
    if unknown_top_level:
        errors.append(
            "conformance profiles has unknown top-level fields: "
            + ", ".join(unknown_top_level)
        )
    if missing_top_level:
        errors.append(
            "conformance profiles is missing top-level fields: "
            + ", ".join(missing_top_level)
        )
    if type(registry.get("schema_version")) is not int or registry["schema_version"] != 1:
        errors.append("conformance profiles schema_version must be exactly 1")
    spec_version = registry.get("spec_version")
    if not isinstance(spec_version, str) or not SEMVER_RE.fullmatch(spec_version):
        errors.append("conformance profiles spec_version must be a semantic version string")
    return errors


def _validated_checks(
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    errors: list[str] = []
    checks = registry.get("checks")
    if not isinstance(checks, dict) or not checks:
        errors.append("conformance profiles checks must be a non-empty object")
        checks = {}
    check_subjects: dict[str, str] = {}
    missing_checks = sorted(set(CHECKS) - set(checks))
    extra_checks = sorted(set(checks) - set(CHECKS))
    if missing_checks:
        errors.append(f"conformance profiles missing implemented checks: {', '.join(missing_checks)}")
    if extra_checks:
        errors.append(f"conformance profiles references unsupported checks: {', '.join(extra_checks)}")
    for check_id, check in checks.items():
        if not isinstance(check_id, str) or not CHECK_ID_RE.fullmatch(check_id):
            errors.append(f"conformance check has invalid id: {check_id}")
        if not isinstance(check, dict):
            errors.append(f"conformance check {check_id} must be an object")
            continue
        unknown_keys = sorted(set(check) - {"description", "subject"})
        if unknown_keys:
            errors.append(f"conformance check {check_id} has unknown fields: {', '.join(unknown_keys)}")
        if check.get("subject") not in CONFORMANCE_SUBJECTS:
            errors.append(f"conformance check {check_id} has invalid subject: {check.get('subject')}")
        elif isinstance(check_id, str):
            check_subjects[check_id] = check["subject"]
        if not isinstance(check.get("description"), str) or not check["description"].strip():
            errors.append(f"conformance check {check_id} must have a description")
    return checks, check_subjects, errors


def _validate_profile_string_list(
    context: _ProfileMetadataContext,
    profile: dict[str, Any],
    profile_id: str,
    key: str,
) -> None:
    values = profile.get(key)
    if not isinstance(values, list) or not all(
        isinstance(item, str) and item for item in values
    ):
        context.errors.append(
            f"conformance profile {profile_id} {key} must be a string list"
        )
        return
    if len(values) != len(set(values)):
        context.errors.append(
            f"conformance profile {profile_id} {key} must not contain duplicates"
        )
    if key == "required_checks":
        for check_id in values:
            if check_id not in context.checks:
                context.errors.append(
                    f"conformance profile {profile_id} references unknown check: {check_id}"
                )
            elif (
                profile_id in context.profile_subjects
                and check_id in context.check_subjects
                and context.profile_subjects[profile_id]
                != context.check_subjects[check_id]
            ):
                context.errors.append(
                    f"conformance profile {profile_id} subject "
                    f"{context.profile_subjects[profile_id]} requires {check_id} subject "
                    f"{context.check_subjects[check_id]}"
                )
        return
    for rel in values:
        error = rel_path_error(
            rel,
            f"conformance profile {profile_id} required file",
        )
        if error:
            context.errors.append(error)


def _validate_profile_directories(
    context: _ProfileMetadataContext,
    profile: dict[str, Any],
    profile_id: str,
) -> None:
    directories = profile.get("required_directories", [])
    if not isinstance(directories, list) or not all(
        isinstance(item, str) and item for item in directories
    ):
        context.errors.append(
            f"conformance profile {profile_id} required_directories must be a string list"
        )
        return
    if len(directories) != len(set(directories)):
        context.errors.append(
            f"conformance profile {profile_id} required_directories must not contain duplicates"
        )
    for rel in directories:
        error = rel_path_error(
            rel,
            f"conformance profile {profile_id} required directory",
        )
        if error:
            context.errors.append(error)


def _validated_profile_parents(
    context: _ProfileMetadataContext,
    profile: dict[str, Any],
    profile_id: str,
) -> list[str]:
    extends = profile.get("extends", [])
    if not isinstance(extends, list) or not all(
        isinstance(item, str) and item for item in extends
    ):
        context.errors.append(
            f"conformance profile {profile_id} extends must be a string list"
        )
        return []
    if len(extends) != len(set(extends)):
        context.errors.append(
            f"conformance profile {profile_id} extends must not contain duplicates"
        )
    return extends


def _validate_profile_record(
    context: _ProfileMetadataContext,
    profile: object,
    index: int,
) -> None:
    if not isinstance(profile, dict):
        context.errors.append(f"conformance profile {index} must be an object")
        return
    unknown_keys = sorted(set(profile) - PROFILE_KEYS)
    if unknown_keys:
        context.errors.append(
            f"conformance profile {profile.get('id', index)} has unknown fields: "
            + ", ".join(unknown_keys)
        )
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
        context.errors.append(
            f"conformance profile {index} must have a lowercase kebab-case id"
        )
        return
    if profile_id in context.profile_ids:
        context.errors.append(f"duplicate conformance profile id: {profile_id}")
    context.profile_ids.add(profile_id)
    if profile.get("subject") not in CONFORMANCE_SUBJECTS:
        context.errors.append(
            f"conformance profile {profile_id} has invalid subject: {profile.get('subject')}"
        )
    else:
        context.profile_subjects[profile_id] = profile["subject"]
    if not isinstance(profile.get("description"), str) or not profile[
        "description"
    ].strip():
        context.errors.append(f"conformance profile {profile_id} must have a description")
    for key in ("required_checks", "required_files"):
        _validate_profile_string_list(context, profile, profile_id, key)
    _validate_profile_directories(context, profile, profile_id)
    context.graph[profile_id] = _validated_profile_parents(
        context,
        profile,
        profile_id,
    )


def _profile_link_errors(context: _ProfileMetadataContext) -> list[str]:
    errors: list[str] = []
    for profile_id, parents in context.graph.items():
        for parent in parents:
            if parent not in context.profile_ids:
                errors.append(
                    f"conformance profile {profile_id} extends unknown profile: {parent}"
                )
            elif (
                profile_id in context.profile_subjects
                and parent in context.profile_subjects
                and context.profile_subjects[profile_id]
                != context.profile_subjects[parent]
            ):
                errors.append(
                    f"conformance profile {profile_id} subject "
                    f"{context.profile_subjects[profile_id]} extends {parent} subject "
                    f"{context.profile_subjects[parent]}"
                )
    return errors


def _profile_cycle_errors(graph: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    for root_profile_id in graph:
        stack = [(root_profile_id, False)]
        while stack:
            profile_id, exiting = stack.pop()
            if exiting:
                visiting.remove(profile_id)
                visited.add(profile_id)
                continue
            if profile_id in visited:
                continue
            if profile_id in visiting:
                errors.append(
                    f"conformance profile inheritance cycle: {profile_id}"
                )
                continue
            visiting.add(profile_id)
            stack.append((profile_id, True))
            stack.extend(
                (parent, False) for parent in reversed(graph.get(profile_id, []))
            )
    return errors


def validate_profile_metadata(registry: dict[str, Any]) -> list[str]:
    errors = _registry_header_errors(registry)
    checks, check_subjects, check_errors = _validated_checks(registry)
    errors.extend(check_errors)

    profiles = registry.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        errors.append("conformance profiles must be a non-empty list")
        return errors

    context = _ProfileMetadataContext(
        checks=checks,
        check_subjects=check_subjects,
        errors=errors,
        profile_ids=set(),
        profile_subjects={},
        graph={},
    )
    for index, profile in enumerate(profiles, start=1):
        _validate_profile_record(context, profile, index)
    errors.extend(_profile_link_errors(context))
    errors.extend(_profile_cycle_errors(context.graph))
    return errors


def load_profiles() -> tuple[dict[str, Any] | None, list[str]]:
    registry, registry_errors = load_json_object(PROFILE_REGISTRY, "conformance profiles")
    schema, schema_errors = load_json_object(PROFILE_SCHEMA, "conformance profile schema")
    errors = registry_errors + schema_errors + validate_schema_file(schema)
    if registry is not None:
        errors.extend(validate_profile_metadata(registry))
    return registry, errors


def profile_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = registry.get("profiles", [])
    if not isinstance(profiles, list):
        return {}
    return {profile["id"]: profile for profile in profiles if isinstance(profile, dict) and isinstance(profile.get("id"), str)}


def expand_profile(profile_id: str, registry: dict[str, Any]) -> tuple[list[str], list[str], list[str], str | None]:
    profiles = profile_by_id(registry)
    if profile_id not in profiles:
        return [], [], [], f"unknown profile: {profile_id}"

    checks: list[str] = []
    files: list[str] = []
    directories: list[str] = []
    visiting: set[str] = set()
    expanded: set[str] = set()
    stack = [(profile_id, False)]
    while stack:
        current_id, exiting = stack.pop()
        profile = profiles.get(current_id)
        if profile is None:
            return checks, files, directories, f"unknown inherited profile: {current_id}"
        if exiting:
            visiting.remove(current_id)
            for rel in profile.get("required_files", []):
                if isinstance(rel, str) and rel not in files:
                    files.append(rel)
            for rel in profile.get("required_directories", []):
                if isinstance(rel, str) and rel not in directories:
                    directories.append(rel)
            for check in profile.get("required_checks", []):
                if isinstance(check, str) and check not in checks:
                    checks.append(check)
            expanded.add(current_id)
            continue
        if current_id in expanded:
            continue
        if current_id in visiting:
            return (
                checks,
                files,
                directories,
                f"conformance profile inheritance cycle: {current_id}",
            )
        parents = profile.get("extends", [])
        if not isinstance(parents, list):
            return checks, files, directories, f"profile {current_id} extends must be a list"
        for parent in parents:
            if not isinstance(parent, str):
                return (
                    checks,
                    files,
                    directories,
                    f"profile {current_id} extends value must be a string",
                )
        visiting.add(current_id)
        stack.append((current_id, True))
        stack.extend((parent, False) for parent in reversed(parents))
    return checks, files, directories, None


def expand_profiles(
    profile_ids: list[str] | tuple[str, ...],
    registry: dict[str, Any],
) -> tuple[
    list[ExpandedProfileClaim],
    list[str],
    list[str],
    list[str],
    str | None,
]:
    """Expand a deterministic profile union without duplicating inherited work."""

    if not profile_ids:
        return [], [], [], [], "at least one conformance profile is required"
    if not all(isinstance(profile_id, str) and profile_id for profile_id in profile_ids):
        return [], [], [], [], "conformance profile ids must be non-empty strings"
    if len(profile_ids) != len(set(profile_ids)):
        return [], [], [], [], "conformance profile ids must not contain duplicates"

    profiles = profile_by_id(registry)
    claims: list[ExpandedProfileClaim] = []
    union_checks: list[str] = []
    union_files: list[str] = []
    union_directories: list[str] = []
    selected_subject: str | None = None
    for profile_id in profile_ids:
        selected_profile = profiles.get(profile_id)
        if selected_profile is None:
            return (
                claims,
                union_checks,
                union_files,
                union_directories,
                f"unknown profile: {profile_id}",
            )
        subject = selected_profile.get("subject")
        if not isinstance(subject, str):
            return (
                claims,
                union_checks,
                union_files,
                union_directories,
                f"profile {profile_id} has no valid subject",
            )
        if selected_subject is None:
            selected_subject = subject
        elif subject != selected_subject:
            return (
                claims,
                union_checks,
                union_files,
                union_directories,
                "selected conformance profiles must have one subject; observed "
                f"{selected_subject} and {subject}",
            )
        checks, files, directories, profile_error = expand_profile(
            profile_id,
            registry,
        )
        if profile_error is not None:
            return (
                claims,
                union_checks,
                union_files,
                union_directories,
                profile_error,
            )
        claims.append(
            ExpandedProfileClaim(
                profile_id=profile_id,
                subject=subject,
                required_checks=tuple(checks),
                required_files=tuple(files),
                required_directories=tuple(directories),
            )
        )
        union_checks.extend(
            check_id for check_id in checks if check_id not in union_checks
        )
        union_files.extend(
            relative for relative in files if relative not in union_files
        )
        union_directories.extend(
            relative
            for relative in directories
            if relative not in union_directories
        )
    return claims, union_checks, union_files, union_directories, None


def _decode_capture_stream(
    label: str,
    stream_name: str,
    raw: bytes,
) -> tuple[str, str | None]:
    try:
        return raw.decode("utf-8").strip(), None
    except UnicodeDecodeError as exc:
        display = raw.decode("utf-8", errors="replace").strip()
        return (
            display,
            f"{label} structured-report {stream_name} must be valid UTF-8: "
            f"{exc}",
        )


def bounded_diagnostic_text(
    value: object,
    *,
    max_bytes: int = MAX_PROTOCOL_DIAGNOSTIC_BYTES,
) -> str:
    """Sanitize controls and bound one diagnostic copied across a process hop."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("diagnostic byte limit must be a positive integer")
    text = str(value)
    visible = "".join(
        character
        if character in {"\n", "\t"} or 0x20 <= ord(character) < 0x7F
        or ord(character) >= 0xA0
        else f"\\x{ord(character):02x}"
        for character in text
    )
    encoded = visible.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return visible
    marker = f"\n...[diagnostic truncated from {len(encoded)} bytes]"
    marker_bytes = marker.encode("ascii")
    if len(marker_bytes) >= max_bytes:
        return marker_bytes[:max_bytes].decode("ascii", errors="ignore")
    return (
        encoded[: max_bytes - len(marker_bytes)].decode("utf-8", errors="ignore")
        + marker
    )


def run_command_capture(
    label: str,
    cmd: list[str],
    cwd: Path,
    *,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
) -> CommandCapture:
    if not cmd:
        raise ValueError("cmd must not be empty")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = bounded_subprocess.run_bounded_process(
            cmd,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            maximum_timeout_seconds=COMMAND_MAX_TIMEOUT_SECONDS,
            maximum_output_bytes=MAX_COMMAND_OUTPUT_LIMIT_BYTES,
            termination_grace_seconds=COMMAND_TERMINATION_GRACE_SECONDS,
        )
    except ValueError:
        raise
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        return CommandCapture(
            ok=False,
            transport_failure=f"{label} could not start: {exc}",
        )
    except Exception as exc:
        return CommandCapture(
            ok=False,
            transport_failure=f"{label} output collection failed: {exc}",
        )

    stdout, stdout_decode_failure = _decode_capture_stream(
        label,
        "stdout",
        result.stdout,
    )
    stderr, stderr_decode_failure = _decode_capture_stream(
        label,
        "stderr",
        result.stderr,
    )
    if result.timed_out:
        return CommandCapture(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            returncode=result.returncode,
            transport_failure=f"{label} timed out after {timeout_seconds:g}s",
            stdout_decode_failure=stdout_decode_failure,
            stderr_decode_failure=stderr_decode_failure,
        )
    if result.output_exceeded:
        return CommandCapture(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            returncode=result.returncode,
            transport_failure=(
                f"{label} output exceeded the {max_output_bytes}-byte limit"
            ),
            stdout_decode_failure=stdout_decode_failure,
            stderr_decode_failure=stderr_decode_failure,
        )
    return CommandCapture(
        ok=result.returncode == 0,
        stdout=stdout,
        stderr=stderr,
        returncode=result.returncode,
        stdout_decode_failure=stdout_decode_failure,
        stderr_decode_failure=stderr_decode_failure,
    )


def run_command(
    label: str,
    cmd: list[str],
    cwd: Path,
    *,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
) -> tuple[bool, str]:
    capture = run_command_capture(
        label,
        cmd,
        cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    output = capture.combined_output()
    if capture.transport_failure is not None:
        detail = capture.transport_failure
        return False, f"{detail}\n{output}" if output else detail
    if capture.ok:
        return True, output
    return False, output or f"{label} exited with {capture.returncode}"


def structured_capture_failures(
    label: str,
    capture: CommandCapture,
) -> list[str]:
    """Enforce the structured-child stream contract without discarding stdout."""

    failures: list[str] = []
    if capture.transport_failure is not None:
        failures.append(capture.transport_failure)
    if capture.stdout_decode_failure is not None:
        failures.append(capture.stdout_decode_failure)
    if capture.stderr_decode_failure is not None:
        failures.append(capture.stderr_decode_failure)
    if capture.stderr:
        failures.append(
            f"{label} violated structured-report protocol: stderr must be empty: "
            f"{bounded_diagnostic_text(capture.stderr)}"
        )
    return failures


def combined_protocol_failure(failures: list[str]) -> str | None:
    unique = ordered_unique(failures)
    return "\n".join(unique) if unique else None


def _string_report_item(item: object) -> str | None:
    return item if isinstance(item, str) else None


def _source_report_item(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    path = item.get("path")
    line = item.get("line")
    message = item.get("message")
    severity = item.get("severity")
    if (
        not isinstance(path, str)
        or type(line) is not int
        or line < 1
        or not isinstance(message, str)
        or severity not in {"error", "warning"}
    ):
        return None
    return f"{path}:{line}: {message}"


def _validated_report_items(
    payload: dict[str, Any],
    field: str,
    label: str,
    renderer: ReportItemRenderer,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw_items = payload.get(field)
    if not isinstance(raw_items, list):
        return (
            (),
            (f"{label} returned an invalid report: {field} must be a list",),
        )
    rendered: list[str] = []
    failures: list[str] = []
    for index, item in enumerate(raw_items):
        value = renderer(item)
        if value is None:
            failures.append(
                f"{label} returned an invalid report: {field}[{index}] has an unsupported shape",
            )
            continue
        rendered.append(value)
    return (
        tuple(ordered_unique(rendered)),
        tuple(ordered_unique(failures)),
    )


def run_json_child(
    label: str,
    cmd: list[str],
    cwd: Path,
    *,
    item_renderer: ReportItemRenderer = _string_report_item,
    warnings_fail: bool = False,
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> CheckOutcome:
    """Run and validate a child report even when semantic diagnostics make it nonzero."""

    capture = run_command_capture(
        label,
        cmd,
        cwd,
        timeout_seconds=timeout_seconds,
    )
    protocol_failures = structured_capture_failures(label, capture)
    if capture.stdout_decode_failure is not None:
        return CheckOutcome(
            protocol_failure=combined_protocol_failure(protocol_failures),
            warnings_fail=warnings_fail,
        )
    try:
        payload = safe_paths.loads_json_no_duplicates(capture.stdout)
    except ValueError as exc:
        if capture.ok:
            failure = f"{label} returned invalid JSON on stdout: {exc}"
        else:
            failure = (
                f"{label} command failed before returning a valid report on "
                f"stdout: {exc}"
            )
        protocol_failures.append(failure)
        return CheckOutcome(
            protocol_failure=combined_protocol_failure(protocol_failures),
            warnings_fail=warnings_fail,
        )
    if not isinstance(payload, dict):
        protocol_failures.append(
            f"{label} returned an invalid report: top level must be an object"
        )
        return CheckOutcome(
            protocol_failure=combined_protocol_failure(protocol_failures),
            warnings_fail=warnings_fail,
        )
    errors, errors_failures = _validated_report_items(
        payload,
        "errors",
        label,
        item_renderer,
    )
    warnings, warnings_failures = _validated_report_items(
        payload,
        "warnings",
        label,
        item_renderer,
    )
    child_protocol_failures: tuple[str, ...] = ()
    child_protocol_shape_failures: tuple[str, ...] = ()
    if "protocol_failures" in payload:
        child_protocol_failures, child_protocol_shape_failures = (
            _validated_report_items(
                payload,
                "protocol_failures",
                label,
                _string_report_item,
            )
        )
    shape_failures = [
        *errors_failures,
        *warnings_failures,
        *child_protocol_shape_failures,
    ]
    protocol_failures.extend(shape_failures)
    protocol_failures.extend(child_protocol_failures)
    report_should_fail = bool(
        errors
        or child_protocol_failures
        or (warnings_fail and warnings)
    )
    if not protocol_failures:
        if capture.ok and report_should_fail:
            protocol_failures.append(
                f"{label} exited zero despite reporting failing diagnostics"
            )
        elif not capture.ok and not report_should_fail:
            protocol_failures.append(
                f"{label} exited nonzero despite reporting no failing diagnostics"
            )
    return CheckOutcome(
        errors=errors,
        warnings=warnings,
        protocol_failure=combined_protocol_failure(protocol_failures),
        warnings_fail=warnings_fail,
    )


def normalized_outcome(
    value: object,
    *,
    check_id: str = "unknown",
) -> CheckOutcome:
    if isinstance(value, CheckOutcome):
        return value
    if not isinstance(value, list):
        return CheckOutcome(
            protocol_failure=(
                f"conformance check {check_id} returned an invalid result: "
                "expected CheckOutcome or list[str], observed "
                f"{type(value).__name__}"
            )
        )
    errors: list[str] = []
    failures: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            errors.append(item)
        else:
            failures.append(
                f"conformance check {check_id} returned an invalid result: "
                f"item[{index}] must be a string, observed {type(item).__name__}"
            )
    return CheckOutcome(
        errors=tuple(ordered_unique(errors)),
        protocol_failure=combined_protocol_failure(failures),
    )


def _bounded_exception_detail(exc: Exception, *, limit: int = 512) -> str:
    detail = " ".join(str(exc).splitlines()).strip() or type(exc).__name__
    if len(detail) <= limit:
        return detail
    return detail[: limit - 1] + "…"


def _read_bounded_utf8(path: Path, description: str) -> tuple[str | None, str | None]:
    try:
        raw = safe_paths.read_regular_file_bytes(path, description=description)
    except FileNotFoundError:
        return None, f"{description} is missing: {path}"
    except ValueError as exc:
        return None, f"{description} is not a bounded regular input: {exc}"
    except OSError as exc:
        return None, f"{description} could not be read safely: {exc}"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, f"{description} must be valid UTF-8: {exc}"


def _read_entrypoint_texts(
    project_root: Path,
) -> tuple[list[tuple[str, str]], list[str]]:
    entrypoints: list[tuple[str, str]] = []
    errors: list[str] = []
    for name in ENTRYPOINTS:
        path = project_root / name
        input_errors = safe_paths.bounded_input_errors(
            path,
            project_root,
            description=f"{name} input",
        )
        if input_errors:
            errors.extend(input_errors)
            continue
        if not path.exists() and not path.is_symlink():
            continue
        text, read_error = _read_bounded_utf8(path, f"{name} input")
        if read_error:
            errors.append(read_error)
        elif text is not None:
            entrypoints.append((name, text))
    return entrypoints, errors


def _framework_roots_from_entrypoints(
    entrypoints: list[tuple[str, str]],
    project_root: Path,
    *,
    contract_root_ref: str = ".",
) -> tuple[list[Path], list[str]]:
    roots: list[Path] = []
    errors: list[str] = []
    for name, text in entrypoints:
        reference, structural_errors = (
            integration_registry.entrypoint_authority_load_references(
                name,
                text,
                contract_root_ref=contract_root_ref,
                repo_root=FRAMEWORK_ROOT,
            )
        )
        errors.extend(structural_errors)
        if reference is None:
            continue
        root = safe_paths.resolve_framework_reference(reference, project_root)
        if root is None:
            errors.append(
                f"{name} framework reference is not concretely resolvable: "
                f"{reference}"
            )
            continue
        roots.append(root)
    return roots, errors


def _entrypoint_state(
    project_root: Path,
    *,
    contract_root_ref: str = ".",
) -> tuple[list[tuple[str, str]], list[Path], list[str]]:
    entrypoints, read_errors = _read_entrypoint_texts(project_root)
    roots, reference_errors = _framework_roots_from_entrypoints(
        entrypoints,
        project_root,
        contract_root_ref=contract_root_ref,
    )
    errors = read_errors + reference_errors
    if not entrypoints and not errors:
        errors.append("missing generated runtime entrypoint: AGENTS.md or CLAUDE.md")
    return entrypoints, roots, errors


def entrypoint_framework_roots(
    project_root: Path,
    *,
    contract_root_ref: str = ".",
) -> tuple[list[Path], list[str]]:
    _entrypoints, roots, errors = _entrypoint_state(
        project_root,
        contract_root_ref=contract_root_ref,
    )
    return roots, errors


PROJECT_ROOT_REQUIRED_FILES = frozenset({"PROJECT_INSTANCE.json"})


def required_file_diagnostic_map(
    root: Path,
    files: list[str],
) -> dict[str, list[str]]:
    """Inspect every unique required file once and retain its diagnostics."""

    diagnostics: dict[str, list[str]] = {}
    for rel in files:
        path = root / rel
        errors = safe_paths.bounded_input_errors(
            path,
            root,
            description=f"required profile file {rel}",
        )
        if not path.exists() and not path.is_symlink():
            errors.append(f"missing required file for selected profile: {rel}")
        diagnostics[rel] = ordered_unique(errors)
    return diagnostics


def required_file_diagnostics(
    root: Path,
    files: list[str],
) -> tuple[list[str], set[str]]:
    diagnostics = required_file_diagnostic_map(root, files)
    return (
        ordered_unique(
            [error for rel in files for error in diagnostics.get(rel, [])]
        ),
        {rel for rel, errors in diagnostics.items() if errors},
    )


def project_required_file_diagnostic_map(
    project_root: Path,
    contract_root: Path,
    files: list[str],
) -> dict[str, list[str]]:
    """Route the receipt to project root and contract/state files to contract root."""

    diagnostics: dict[str, list[str]] = {}
    for rel in files:
        surface_root = (
            project_root if rel in PROJECT_ROOT_REQUIRED_FILES else contract_root
        )
        diagnostics.update(required_file_diagnostic_map(surface_root, [rel]))
    return diagnostics


def check_required_files(root: Path, files: list[str]) -> list[str]:
    return required_file_diagnostics(root, files)[0]


def required_directory_diagnostic_map(
    root: Path,
    directories: list[str],
) -> dict[str, list[str]]:
    """Inspect every unique required directory once and retain its diagnostics."""

    diagnostics: dict[str, list[str]] = {}
    for rel in directories:
        path = root / rel
        errors = safe_paths.bounded_input_errors(
            path,
            root,
            description=f"required profile directory {rel}",
            expected_kind="directory",
        )
        if not path.exists() and not path.is_symlink():
            errors.append(f"missing required directory for selected profile: {rel}")
        diagnostics[rel] = ordered_unique(errors)
    return diagnostics


def required_directory_diagnostics(
    root: Path,
    directories: list[str],
) -> tuple[list[str], set[str]]:
    diagnostics = required_directory_diagnostic_map(root, directories)
    return (
        ordered_unique(
            [error for rel in directories for error in diagnostics.get(rel, [])]
        ),
        {rel for rel, errors in diagnostics.items() if errors},
    )


def check_required_directories(root: Path, directories: list[str]) -> list[str]:
    return required_directory_diagnostics(root, directories)[0]


def _exact_tree_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _exact_product_tree_support_error() -> str | None:
    missing: list[str] = []
    if not _EXACT_TREE_OPEN_SUPPORTS_DIR_FD:
        missing.append("os.open(dir_fd)")
    if not _EXACT_TREE_STAT_SUPPORTS_DIR_FD:
        missing.append("os.stat(dir_fd)")
    if not _EXACT_TREE_STAT_SUPPORTS_NOFOLLOW:
        missing.append("os.stat(follow_symlinks=False)")
    if not _EXACT_TREE_SCANDIR_SUPPORTS_FD:
        missing.append("os.scandir(fd)")
    for flag_name in ("O_DIRECTORY", "O_NOFOLLOW"):
        value = getattr(os, flag_name, None)
        if not isinstance(value, int) or value == 0:
            missing.append(flag_name)
    if not missing:
        return None
    return (
        "exact product tree inspection requires descriptor-safe filesystem "
        "primitives: " + ", ".join(missing)
    )


def _exact_product_tree_errors(
    root: Path,
    *,
    _test_hook: Callable[[str, str, tuple[int, int, int]], None] | None = None,
) -> list[str]:
    """Return the first bounded exact-tree conformance diagnostic.

    This pass binds the root once and owns completeness, entry types, and
    contamination checks for exact mode.  It walks only manifest-declared
    directories through retained no-follow descriptors and stops at the first
    missing, undeclared, or unsafe entry.  A conforming directory can expose no
    more names than the manifest-derived set below; repeated names also fail
    closed so an abnormal iterator cannot drive unbounded work.
    ``_test_hook`` is an internal deterministic race seam; production callers
    never supply it.
    """

    support_error = _exact_product_tree_support_error()
    if support_error is not None:
        return [support_error]

    declared_children: dict[str, set[str]] = {}
    for relative in (
        product_manifest.PRODUCT_REQUIRED_FILE_SET
        | product_manifest.PRODUCT_DIRECTORY_PATHS
    ):
        parent, _separator, name = relative.rpartition("/")
        declared_children.setdefault(parent, set()).add(name)

    directory_flag = getattr(os, "O_DIRECTORY")
    no_follow_flag = getattr(os, "O_NOFOLLOW")
    directory_flags = (
        os.O_RDONLY
        | directory_flag
        | no_follow_flag
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        root_binding = safe_paths.open_output_directory(
            root,
            create_missing=False,
        )
    except (OSError, ValueError, safe_paths.OutputDirectoryBindingError) as exc:
        return [f"exact product distribution root is unsafe: {exc}"]

    opened_directories: list[_ExactTreeDirectoryEdge] = []
    observed_entries: list[_ExactTreeEntryEdge] = []
    directory_snapshots: list[_ExactTreeDirectorySnapshot] = []
    result: list[str] = []
    cleanup_errors: list[str] = []

    @contextmanager
    def fresh_directory_entries(
        directory_descriptor: int,
        relative_directory: str,
        *,
        operation: str,
    ) -> Iterator[Any]:
        """Enumerate through a fresh open description without sharing offsets."""

        label = relative_directory or "."
        scan_descriptor: int | None = None
        try:
            scan_descriptor = os.open(
                ".",
                directory_flags,
                dir_fd=directory_descriptor,
            )
            if _exact_tree_identity(
                os.fstat(scan_descriptor)
            ) != _exact_tree_identity(os.fstat(directory_descriptor)):
                raise _ExactProductTreeFailure(
                    "product distribution directory binding changed before "
                    f"{operation}: {label}"
                )
            with os.scandir(scan_descriptor) as iterator:
                yield iterator
        except OSError as exc:
            raise _ExactProductTreeFailure(
                f"could not {operation} product directory {label}: {exc}"
            ) from exc
        finally:
            if scan_descriptor is not None:
                primary = sys.exception()
                try:
                    os.close(scan_descriptor)
                except OSError as cleanup:
                    cleanup_diagnostic = (
                        "could not close product directory scan descriptor "
                        f"{label}: {_bounded_exception_detail(cleanup)}"
                    )
                    cleanup_errors.append(cleanup_diagnostic)
                    if primary is not None:
                        primary.add_note(cleanup_diagnostic)
                    else:
                        raise _ExactProductTreeFailure(
                            cleanup_diagnostic
                        ) from cleanup

    def require_same_names(
        directory_descriptor: int,
        relative_directory: str,
        expected_names: frozenset[str],
    ) -> None:
        label = relative_directory or "."
        current_names: set[str] = set()
        with fresh_directory_entries(
            directory_descriptor,
            relative_directory,
            operation="re-enumerate",
        ) as iterator:
            for entry in iterator:
                if entry.name in current_names:
                    raise _ExactProductTreeFailure(
                        "product distribution directory enumeration "
                        f"repeated an entry name in {label}"
                    )
                current_names.add(entry.name)
                if entry.name not in expected_names:
                    raise _ExactProductTreeFailure(
                        "product distribution directory entries changed "
                        f"during traversal: {label}"
                    )
        if current_names != expected_names:
            raise _ExactProductTreeFailure(
                "product distribution directory entries changed during "
                f"traversal: {label}"
            )

    def require_same_entry(edge: _ExactTreeEntryEdge) -> None:
        try:
            current = os.stat(
                edge.name,
                dir_fd=edge.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise _ExactProductTreeFailure(
                "product distribution entry name changed during traversal: "
                f"{edge.relative}: {exc}"
            ) from exc
        if _exact_tree_identity(current) != edge.identity:
            raise _ExactProductTreeFailure(
                "product distribution entry name changed during traversal: "
                f"{edge.relative}"
            )

    def bind_directory(entry_edge: _ExactTreeEntryEdge) -> int:
        if _test_hook is not None:
            _test_hook(
                "before_directory_open",
                entry_edge.relative,
                entry_edge.identity,
            )
        try:
            child_descriptor = os.open(
                entry_edge.name,
                directory_flags,
                dir_fd=entry_edge.parent_descriptor,
            )
        except OSError as exc:
            try:
                current = os.stat(
                    entry_edge.name,
                    dir_fd=entry_edge.parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                current = None
            if (
                current is None
                or _exact_tree_identity(current) != entry_edge.identity
            ):
                raise _ExactProductTreeFailure(
                    "product distribution directory changed before traversal: "
                    f"{entry_edge.relative}"
                ) from exc
            raise _ExactProductTreeFailure(
                "could not bind enumerated product directory without following "
                f"links: {entry_edge.relative}: {exc}"
            ) from exc
        edge = _ExactTreeDirectoryEdge(
            descriptor=child_descriptor,
            parent_descriptor=entry_edge.parent_descriptor,
            name=entry_edge.name,
            relative=entry_edge.relative,
            identity=entry_edge.identity,
        )
        opened_directories.append(edge)
        opened = os.fstat(child_descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _exact_tree_identity(opened) != edge.identity
        ):
            raise _ExactProductTreeFailure(
                "product distribution directory changed before traversal: "
                f"{entry_edge.relative}"
            )
        if _test_hook is not None:
            _test_hook(
                "after_directory_open",
                entry_edge.relative,
                _exact_tree_identity(opened),
            )
        try:
            named_after_open = os.stat(
                entry_edge.name,
                dir_fd=entry_edge.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise _ExactProductTreeFailure(
                "product distribution directory name changed before traversal: "
                f"{entry_edge.relative}: {exc}"
            ) from exc
        if (
            not stat.S_ISDIR(named_after_open.st_mode)
            or _exact_tree_identity(named_after_open) != edge.identity
        ):
            raise _ExactProductTreeFailure(
                "product distribution directory name changed before traversal: "
                f"{entry_edge.relative}"
            )
        return child_descriptor

    try:
        pending: list[tuple[int, str] | _ExactTreeEntryEdge] = [
            (root_binding.descriptor, "")
        ]
        while pending:
            pending_directory = pending.pop()
            if isinstance(pending_directory, _ExactTreeEntryEdge):
                directory_descriptor = bind_directory(pending_directory)
                relative_directory = pending_directory.relative
            else:
                directory_descriptor, relative_directory = pending_directory
            permitted_names = set(
                declared_children.get(relative_directory, set())
            )
            if not relative_directory:
                permitted_names.update(PRODUCT_LOCAL_METADATA_ROOT_ENTRIES)
            observed_names: set[str] = set()
            directory_entries: list[_ExactTreeEntryEdge] = []
            directories_to_open: list[_ExactTreeEntryEdge] = []
            label = relative_directory or "."
            if _test_hook is not None:
                _test_hook(
                    "before_directory_enumeration",
                    label,
                    _exact_tree_identity(os.fstat(directory_descriptor)),
                )
            with fresh_directory_entries(
                directory_descriptor,
                relative_directory,
                operation="enumerate",
            ) as iterator:
                for entry in iterator:
                    if entry.name in observed_names:
                        raise _ExactProductTreeFailure(
                            "product distribution directory enumeration "
                            f"repeated an entry name in {label}"
                        )
                    observed_names.add(entry.name)

                    relative = (
                        f"{relative_directory}/{entry.name}"
                        if relative_directory
                        else entry.name
                    )
                    if _test_hook is not None:
                        _test_hook(
                            "before_entry_stat",
                            relative,
                            _exact_tree_identity(
                                os.fstat(directory_descriptor)
                            ),
                        )
                    try:
                        metadata = os.stat(
                            entry.name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        raise _ExactProductTreeFailure(
                            "could not inspect product tree entry "
                            f"{relative}: {exc}"
                        ) from exc
                    mode = metadata.st_mode
                    if stat.S_ISLNK(mode):
                        raise _ExactProductTreeFailure(
                            "product distribution contains symlink: "
                            f"{relative}"
                        )
                    if (
                        not relative_directory
                        and entry.name in PRODUCT_LOCAL_METADATA_ROOT_ENTRIES
                    ):
                        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                            raise _ExactProductTreeFailure(
                                "product local metadata entry has unsupported "
                                f"type: {relative}"
                            )
                        edge = _ExactTreeEntryEdge(
                            parent_descriptor=directory_descriptor,
                            name=entry.name,
                            relative=relative,
                            identity=_exact_tree_identity(metadata),
                        )
                        observed_entries.append(edge)
                        directory_entries.append(edge)
                        continue
                    if stat.S_ISDIR(mode):
                        if (
                            entry.name not in permitted_names
                            or relative
                            not in product_manifest.PRODUCT_DIRECTORY_PATHS
                        ):
                            raise _ExactProductTreeFailure(
                                f"undeclared product directory: {relative}"
                            )
                        entry_edge = _ExactTreeEntryEdge(
                            parent_descriptor=directory_descriptor,
                            name=entry.name,
                            relative=relative,
                            identity=_exact_tree_identity(metadata),
                        )
                        observed_entries.append(entry_edge)
                        directory_entries.append(entry_edge)
                        directories_to_open.append(entry_edge)
                        continue
                    if stat.S_ISREG(mode):
                        if (
                            entry.name not in permitted_names
                            or relative
                            not in product_manifest.PRODUCT_REQUIRED_FILE_SET
                        ):
                            raise _ExactProductTreeFailure(
                                f"undeclared product file: {relative}"
                            )
                        edge = _ExactTreeEntryEdge(
                            parent_descriptor=directory_descriptor,
                            name=entry.name,
                            relative=relative,
                            identity=_exact_tree_identity(metadata),
                        )
                        observed_entries.append(edge)
                        directory_entries.append(edge)
                        continue
                    raise _ExactProductTreeFailure(
                        "product distribution contains special entry: "
                        f"{relative}"
                    )
            missing_names = sorted(
                declared_children.get(relative_directory, set())
                - observed_names
            )
            if missing_names:
                missing_name = missing_names[0]
                missing_relative = (
                    f"{relative_directory}/{missing_name}"
                    if relative_directory
                    else missing_name
                )
                if missing_relative in product_manifest.PRODUCT_DIRECTORY_PATHS:
                    raise _ExactProductTreeFailure(
                        f"missing product directory: {missing_relative}"
                    )
                raise _ExactProductTreeFailure(
                    f"missing product file: {missing_relative}"
                )
            snapshot = _ExactTreeDirectorySnapshot(
                descriptor=directory_descriptor,
                relative=relative_directory,
                names=frozenset(observed_names),
            )
            directory_snapshots.append(snapshot)
            if _test_hook is not None:
                _test_hook(
                    "after_directory_enumeration",
                    label,
                    _exact_tree_identity(os.fstat(directory_descriptor)),
                )
            require_same_names(
                snapshot.descriptor,
                snapshot.relative,
                snapshot.names,
            )
            for edge in directory_entries:
                require_same_entry(edge)
            pending.extend(directories_to_open)

        for snapshot in directory_snapshots:
            require_same_names(
                snapshot.descriptor,
                snapshot.relative,
                snapshot.names,
            )
        for entry_edge in observed_entries:
            require_same_entry(entry_edge)
        for edge in opened_directories:
            if _test_hook is not None:
                _test_hook(
                    "before_directory_edge_recheck",
                    edge.relative,
                    edge.identity,
                )
            try:
                named = os.stat(
                    edge.name,
                    dir_fd=edge.parent_descriptor,
                    follow_symlinks=False,
                )
                opened = os.fstat(edge.descriptor)
            except OSError as exc:
                raise _ExactProductTreeFailure(
                    "product distribution directory name changed during "
                    f"traversal: {edge.relative}: {exc}"
                ) from exc
            if (
                not stat.S_ISDIR(named.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or _exact_tree_identity(named) != edge.identity
                or _exact_tree_identity(opened) != edge.identity
            ):
                raise _ExactProductTreeFailure(
                    "product distribution directory name changed during "
                    f"traversal: {edge.relative}"
                )
        if _test_hook is not None:
            _test_hook(
                "before_root_edge_recheck",
                ".",
                _exact_tree_identity(os.fstat(root_binding.descriptor)),
            )
        try:
            root_binding.require_lexical_binding(
                description="exact product distribution root",
            )
        except (OSError, ValueError) as exc:
            raise _ExactProductTreeFailure(
                "product distribution root name changed during traversal: "
                f"{_bounded_exception_detail(exc)}"
            ) from exc
    except _ExactProductTreeFailure as exc:
        result = [str(exc)]
    except (OSError, ValueError) as exc:
        result = [f"could not inspect product tree safely: {exc}"]
    finally:
        for edge in reversed(opened_directories):
            try:
                os.close(edge.descriptor)
            except OSError as exc:
                cleanup_errors.append(
                    "could not close product directory descriptor "
                    f"{edge.relative}: {_bounded_exception_detail(exc)}"
                )
        try:
            root_binding.close()
        except OSError as exc:
            cleanup_errors.append(
                "could not close exact product distribution root: "
                f"{_bounded_exception_detail(exc)}"
            )
    return ordered_unique([*result, *cleanup_errors[:1]])


def check_framework_product_files(
    root: Path,
    *,
    exact_product_tree: bool = False,
) -> list[str]:
    if exact_product_tree:
        return _exact_product_tree_errors(root)
    errors: list[str] = []
    for rel in product_manifest.PRODUCT_REQUIRED_FILES:
        path = root / rel
        errors.extend(
            safe_paths.bounded_input_errors(
                path,
                root,
                description=f"product file {rel}",
            )
        )
        if not path.exists() and not path.is_symlink():
            errors.append(f"missing product file: {rel}")
    return ordered_unique(errors)


def check_project_core_files(
    project_root: Path,
    contract_root: Path | None = None,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
) -> CheckOutcome:
    """Validate the readable current-instance receipt and retained preimage.

    Profile metadata owns required-surface existence.  The scheduler invokes
    this check whenever the receipt itself is readable, including when another
    required surface is absent, so the current-format identity result remains
    the primary lifecycle diagnostic.
    """

    instance_result = project_instance_lint.lint_instance(
        project_root,
        contract_root_ref,
        framework_root=FRAMEWORK_ROOT,
        expected_project_kind=project_kind,
    )
    return CheckOutcome(
        errors=tuple(instance_result["errors"]),
        warnings=tuple(instance_result["warnings"]),
    )


def check_project_entrypoint_resolves(
    project_root: Path,
    contract_root: Path | None = None,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    profile_prerequisites_checked: bool = False,
) -> list[str]:
    contract_root = project_root if contract_root is None else contract_root
    errors: list[str] = []
    policy = contract_model.project_layout_policy(project_kind)
    if not policy.manages_runtime_entrypoint:
        return project_bootstrap.project_layout_errors(
            project_root,
            contract_root,
            contract_root_ref,
            FRAMEWORK_ROOT,
            project_kind,
        )
    _entrypoints, roots, root_errors = _entrypoint_state(
        project_root,
        contract_root_ref=contract_root_ref,
    )
    errors.extend(root_errors)
    contract_path = contract_root / "AGENT_PROJECT.md"
    if not profile_prerequisites_checked:
        errors.extend(
            safe_paths.bounded_input_errors(
                contract_path,
                project_root,
                description="AGENT_PROJECT.md input",
            )
        )
        if not contract_path.exists() and not contract_path.is_symlink():
            errors.append("AGENT_PROJECT.md missing for generated entrypoint")
    for framework_root in roots:
        if not (framework_root / "runtime" / "operative_charter.md").exists():
            errors.append(f"entrypoint framework reference does not resolve operative charter: {framework_root}")
    return errors


def check_project_contract_sync(
    project_root: Path,
    contract_root: Path | None = None,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
) -> CheckOutcome:
    del contract_root
    policy = contract_model.project_layout_policy(project_kind)
    layout_args = ["--project-kind", project_kind]
    if contract_root_ref != ".":
        layout_args.extend(["--contract-root", contract_root_ref])
    command_prefix = (
        list(policy.contract_sync_command_prefix)
        if policy.contract_sync_command_prefix
        else trusted_python_child(
            FRAMEWORK_ROOT / "scripts" / "project_contract_sync.py"
        )
    )
    return run_json_child(
        "project-contract-sync",
        [
            *command_prefix,
            str(project_root),
            *layout_args,
        ],
        FRAMEWORK_ROOT,
    )


def check_project_state_files_lint(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> CheckOutcome:
    contract_root = project_root if contract_root is None else contract_root
    return run_json_child(
        "project-state-lint",
        trusted_python_child(
            FRAMEWORK_ROOT / "scripts" / "project_state_lint.py",
            "--root",
            str(contract_root),
            "--project-root",
            str(project_root),
        ),
        FRAMEWORK_ROOT,
    )


def check_source_freshness_metadata(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> CheckReturn:
    contract_root = project_root if contract_root is None else contract_root
    errors = check_required_files(contract_root, ["SOURCE_PACKS.md", "SOURCE_UPDATE.md"])
    if errors:
        return errors
    child_deadline = nested_child_deadline_seconds(COMMAND_TIMEOUT_SECONDS)
    return run_json_child(
        "check-reference-freshness",
        trusted_python_child(
            FRAMEWORK_ROOT / "scripts" / "check_reference_freshness.py",
            "--root",
            str(contract_root),
            "--audit-monitor-roots",
            "--warnings-as-errors",
            "--run-deadline",
            f"{child_deadline:g}",
            "--format",
            "json",
        ),
        FRAMEWORK_ROOT,
        item_renderer=_source_report_item,
        warnings_fail=True,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )


def markdown_h2_sections(text: str) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = {}
    for section in markdown_structure.markdown_sections(
        text,
        include_fenced_content=False,
    ):
        sections.setdefault(section.title, []).append(
            [line for _line_number, line in section.lines]
        )
    return sections


def section_has_substantive_content(lines: list[str]) -> bool:
    visible_text = HTML_COMMENT_RE.sub("", "\n".join(lines))
    return any(
        line.strip()
        and not line.lstrip().startswith("## ")
        for line in visible_text.splitlines()
    )


def check_security_verification_file(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> list[str]:
    contract_root = project_root if contract_root is None else contract_root
    path = contract_root / "SECURITY_VERIFICATION.md"
    errors = check_required_files(contract_root, ["SECURITY_VERIFICATION.md"])
    if errors:
        return errors
    text, read_error = _read_bounded_utf8(
        path,
        "SECURITY_VERIFICATION.md input",
    )
    if read_error:
        return [read_error]
    if text is None:
        return ["SECURITY_VERIFICATION.md input could not be read"]
    required = ("Scope", "Profiles", "Authorization Boundaries", "Tool Output Triage")
    sections = markdown_h2_sections(text)
    for heading in required:
        instances = sections.get(heading, [])
        if not instances:
            errors.append(f"SECURITY_VERIFICATION.md missing section: ## {heading}")
        elif len(instances) > 1:
            errors.append(f"SECURITY_VERIFICATION.md duplicate section: ## {heading}")
        elif not section_has_substantive_content(instances[0]):
            errors.append(f"SECURITY_VERIFICATION.md section has no substantive content: ## {heading}")
    return errors


def check_automation_manifest_lints(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> CheckReturn:
    contract_root = project_root if contract_root is None else contract_root
    errors = check_required_files(contract_root, ["AUTOMATION_ORDERS.json"])
    if errors:
        return errors
    manifest_path = contract_root / "AUTOMATION_ORDERS.json"
    target_args: list[str] = []
    try:
        raw = safe_paths.read_regular_file_bytes(
            manifest_path,
            description="automation conformance manifest",
        )
        payload = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and payload.get("preferred_backend") == "cron":
        target_args = ["--target", "cron"]
    return run_json_child(
        "automation-orders-lint",
        trusted_python_child(
            FRAMEWORK_ROOT / "scripts" / "automation_orders_lint.py",
            str(manifest_path),
            "--project-root",
            str(project_root),
            *target_args,
        ),
        FRAMEWORK_ROOT,
    )


def check_multi_agent_state_files(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> list[str]:
    contract_root = project_root if contract_root is None else contract_root
    return check_required_files(contract_root, ["PRECEDENTS.md"])


def check_reviewer_lane_feedback_lint(
    project_root: Path,
    contract_root: Path | None = None,
    **_layout: object,
) -> CheckReturn:
    contract_root = project_root if contract_root is None else contract_root
    path = contract_root / "REVIEWER_LANE_FEEDBACK.md"
    errors = check_required_files(contract_root, ["REVIEWER_LANE_FEEDBACK.md"])
    if errors:
        return errors
    return run_json_child(
        "reviewer-lane-feedback-lint",
        trusted_python_child(
            FRAMEWORK_ROOT / "scripts" / "lint_reviewer_lane_feedback.py",
            "--path",
            str(path),
            "--root",
            str(project_root),
        ),
        FRAMEWORK_ROOT,
    )


CHECKS = {
    "automation_manifest_lints": check_automation_manifest_lints,
    "framework_product_files": check_framework_product_files,
    "multi_agent_state_files": check_multi_agent_state_files,
    "project_contract_sync": check_project_contract_sync,
    "project_core_files": check_project_core_files,
    "project_entrypoint_resolves": check_project_entrypoint_resolves,
    "project_state_files_lint": check_project_state_files_lint,
    "reviewer_lane_feedback_lint": check_reviewer_lane_feedback_lint,
    "security_verification_file": check_security_verification_file,
    "source_freshness_metadata": check_source_freshness_metadata,
}

# Reserved report phase: it is an implicit prerequisite owned by every profile,
# not a selectable check from conformance/profiles.json.
PROFILE_PREREQUISITE_PHASE_ID = "profile_required_surfaces"
CHECK_FILE_PREREQUISITES: dict[str, frozenset[str]] = {
    "automation_manifest_lints": frozenset({"AUTOMATION_ORDERS.json"}),
    "multi_agent_state_files": frozenset({"PRECEDENTS.md"}),
    "project_contract_sync": frozenset(
        {"STATEMENT_OF_WORK.md", "AGENT_PROJECT.md"}
    ),
    # Required-surface existence is owned by profiles.json. Receipt
    # readability alone gates the current-format identity check; missing or unsafe
    # sibling surfaces remain independent prerequisite diagnostics.
    "project_core_files": frozenset({"PROJECT_INSTANCE.json"}),
    "project_state_files_lint": frozenset({"TODO.md", "DECISIONS.md"}),
    "reviewer_lane_feedback_lint": frozenset({"REVIEWER_LANE_FEEDBACK.md"}),
    "security_verification_file": frozenset({"SECURITY_VERIFICATION.md"}),
    "source_freshness_metadata": frozenset(
        {"SOURCE_PACKS.md", "SOURCE_UPDATE.md"}
    ),
}
CHECK_DIRECTORY_PREREQUISITES: dict[str, frozenset[str]] = {}


def blocked_profile_surfaces(
    check_id: str,
    invalid_files: set[str],
    invalid_directories: set[str],
    *,
    project_kind: str = "downstream",
) -> list[str]:
    file_prerequisites = CHECK_FILE_PREREQUISITES.get(
        check_id,
        frozenset(),
    )
    directory_prerequisites = CHECK_DIRECTORY_PREREQUISITES.get(
        check_id,
        frozenset(),
    )
    return sorted(
        [
            *invalid_files.intersection(file_prerequisites),
            *(
                f"{item}/"
                for item in invalid_directories.intersection(
                    directory_prerequisites
                )
            ),
        ]
    )


def run_profiles(
    profile_ids: list[str] | tuple[str, ...],
    root: Path,
    *,
    contract_root: Path | None = None,
    contract_root_ref: str = ".",
    project_kind: str = "downstream",
    exact_product_tree: bool = False,
) -> dict[str, Any]:
    """Run the union of selected profiles once and retain per-profile claims."""

    selected_ids = list(profile_ids)
    registry, metadata_errors = load_profiles()
    if registry is None or metadata_errors:
        return {
            "profiles": selected_ids,
            "profile_results": [],
            "root": str(root),
            "checks": [],
            "errors": ordered_unique(metadata_errors),
            "warnings": [],
            "protocol_failures": [],
            "status": "fail",
            "error_class": "metadata",
        }
    claims, checks, files, directories, profile_error = expand_profiles(
        selected_ids,
        registry,
    )
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    protocol_failures: list[str] = []
    if profile_error:
        return {
            "profiles": selected_ids,
            "profile_results": [],
            "root": str(root),
            "checks": [],
            "errors": [profile_error],
            "warnings": [],
            "protocol_failures": [],
            "status": "fail",
            "error_class": "invocation",
        }
    if exact_product_tree and "framework_product_files" not in checks:
        return {
            "profiles": selected_ids,
            "profile_results": [],
            "root": str(root),
            "checks": [],
            "errors": [
                "--exact-product-tree requires a profile containing "
                "framework_product_files"
            ],
            "warnings": [],
            "protocol_failures": [],
            "status": "fail",
            "error_class": "invocation",
        }
    subject = claims[0].subject

    if subject == "project":
        selected_contract_root = root if contract_root is None else contract_root
        file_diagnostics = project_required_file_diagnostic_map(
            root,
            selected_contract_root,
            files,
        )
        directory_diagnostics = required_directory_diagnostic_map(
            selected_contract_root,
            directories,
        )
    else:
        file_diagnostics = required_file_diagnostic_map(root, files)
        directory_diagnostics = required_directory_diagnostic_map(
            root,
            directories,
        )
    file_errors = ordered_unique(
        [error for rel in files for error in file_diagnostics.get(rel, [])]
    )
    directory_errors = ordered_unique(
        [
            error
            for rel in directories
            for error in directory_diagnostics.get(rel, [])
        ]
    )
    invalid_files = {
        rel for rel, diagnostics in file_diagnostics.items() if diagnostics
    }
    invalid_directories = {
        rel
        for rel, diagnostics in directory_diagnostics.items()
        if diagnostics
    }
    profile_surface_errors = ordered_unique(file_errors + directory_errors)
    if profile_surface_errors:
        errors.extend(profile_surface_errors)
    results.append(
        {
            "id": PROFILE_PREREQUISITE_PHASE_ID,
            "phase": "prerequisite",
            "status": "fail" if profile_surface_errors else "pass",
            "errors": profile_surface_errors,
            "warnings": [],
            "protocol_failure": None,
        }
    )

    for check_id in checks:
        blocked_by = blocked_profile_surfaces(
            check_id,
            invalid_files,
            invalid_directories,
            project_kind=project_kind,
        )
        if blocked_by:
            results.append(
                {
                    "id": check_id,
                    "phase": "check",
                    "status": "blocked",
                    "errors": [],
                    "warnings": [],
                    "protocol_failure": None,
                    "blocked_by": blocked_by,
                }
            )
            continue
        check = CHECKS.get(check_id)
        try:
            if check is None:
                outcome = CheckOutcome(
                    errors=(f"profile references unsupported check: {check_id}",)
                )
            elif subject == "project":
                check_kwargs: dict[str, object] = {
                    "project_kind": project_kind,
                    "contract_root_ref": contract_root_ref,
                }
                if check_id == "project_entrypoint_resolves":
                    check_kwargs["profile_prerequisites_checked"] = True
                outcome = normalized_outcome(
                    check(
                        root,
                        contract_root,
                        **check_kwargs,
                    ),
                    check_id=check_id,
                )
            else:
                outcome = normalized_outcome(
                    check(
                        root,
                        **(
                            {"exact_product_tree": True}
                            if check_id == "framework_product_files"
                            and exact_product_tree
                            else {}
                        ),
                    ),
                    check_id=check_id,
                )
            check_errors = outcome.report_errors()
            check_warnings = outcome.report_warnings()
        except Exception as exc:
            outcome = CheckOutcome(
                protocol_failure=(
                    f"conformance check {check_id} raised "
                    f"{type(exc).__name__}: {_bounded_exception_detail(exc)}"
                )
            )
            check_errors = outcome.report_errors()
            check_warnings = outcome.report_warnings()
        if check_errors:
            errors.extend(check_errors)
        if check_warnings:
            warnings.extend(check_warnings)
        if outcome.protocol_failure is not None:
            protocol_failures.append(outcome.protocol_failure)
        if outcome.failed():
            check_status = "fail"
        elif check_warnings:
            check_status = "warn"
        else:
            check_status = "pass"
        results.append(
            {
                "id": check_id,
                "phase": "check",
                "status": check_status,
                "errors": check_errors,
                "warnings": check_warnings,
                "protocol_failure": outcome.protocol_failure,
            }
        )
    check_results_by_id = {
        result["id"]: result
        for result in results
        if result.get("phase") == "check"
    }
    errors = ordered_unique(errors)
    warnings = ordered_unique(warnings)
    protocol_failures = ordered_unique(protocol_failures)
    failed = bool(errors) or bool(protocol_failures) or any(
        result.get("status") == "fail" for result in results
    )
    status = "fail" if failed else "warn" if warnings else "pass"
    profile_results: list[dict[str, Any]] = []
    for claim in claims:
        claim_surface_errors = ordered_unique(
            [
                *(
                    error
                    for rel in claim.required_files
                    for error in file_diagnostics.get(rel, [])
                ),
                *(
                    error
                    for rel in claim.required_directories
                    for error in directory_diagnostics.get(rel, [])
                ),
            ]
        )
        claim_prerequisite = {
            "id": PROFILE_PREREQUISITE_PHASE_ID,
            "phase": "prerequisite",
            "status": "fail" if claim_surface_errors else "pass",
            "errors": claim_surface_errors,
            "warnings": [],
            "protocol_failure": None,
        }
        claim_check_results = [
            check_results_by_id[check_id]
            for check_id in claim.required_checks
            if check_id in check_results_by_id
        ]
        claim_errors = ordered_unique(
            [
                *claim_surface_errors,
                *(
                    error
                    for result in claim_check_results
                    for error in result.get("errors", [])
                    if isinstance(error, str)
                ),
            ]
        )
        claim_warnings = ordered_unique(
            [
                warning
                for result in claim_check_results
                for warning in result.get("warnings", [])
                if isinstance(warning, str)
            ]
        )
        claim_protocol_failures = ordered_unique(
            [
                failure
                for result in claim_check_results
                for failure in (result.get("protocol_failure"),)
                if isinstance(failure, str)
            ]
        )
        claim_failed = bool(claim_errors) or bool(claim_protocol_failures) or any(
            result.get("status") in {"fail", "blocked"}
            for result in claim_check_results
        )
        claim_status = (
            "fail"
            if claim_failed
            else "warn"
            if claim_warnings
            else "pass"
        )
        profile_results.append(
            {
                **claim.report_claim(),
                "checks": [claim_prerequisite, *claim_check_results],
                "errors": claim_errors,
                "warnings": claim_warnings,
                "protocol_failures": claim_protocol_failures,
                "status": claim_status,
            }
        )
    return {
        "profiles": selected_ids,
        "profile_results": profile_results,
        "root": str(root),
        "contract_root": contract_root_ref if subject == "project" else None,
        "project_kind": project_kind if subject == "project" else None,
        "checks": results,
        "errors": errors,
        "warnings": warnings,
        "protocol_failures": protocol_failures,
        "status": status,
        "error_class": "conformance" if failed else "none",
    }


def apply_strict_warning_policy(
    report: dict[str, Any],
    *,
    strict_warnings: bool,
) -> None:
    """Escalate aggregate warning status without rewriting check diagnostics."""

    if (
        strict_warnings
        and report.get("warnings")
        and report.get("status") != "fail"
    ):
        report["status"] = "fail"
        report["error_class"] = "conformance"


def print_report(report: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return
    printed_errors: set[str] = set()
    printed_warnings: set[str] = set()
    printed_protocol_failures: set[str] = set()
    for check in report["checks"]:
        print(f"{check['id']}: {check['status'].upper()}")
        if check.get("blocked_by"):
            print(f"  BLOCKED BY: {', '.join(check['blocked_by'])}")
        for error in check.get("errors", []):
            if error not in printed_errors:
                print(f"  ERROR: {error}")
                printed_errors.add(error)
        for warning in check.get("warnings", []):
            if warning not in printed_warnings:
                print(f"  WARNING: {warning}")
                printed_warnings.add(warning)
        protocol_failure = check.get("protocol_failure")
        if (
            isinstance(protocol_failure, str)
            and protocol_failure not in printed_protocol_failures
        ):
            print(f"  PROTOCOL FAILURE: {protocol_failure}")
            printed_protocol_failures.add(protocol_failure)
    for error in report.get("errors", []):
        if error not in printed_errors:
            print(f"ERROR: {error}")
            printed_errors.add(error)
    for warning in report.get("warnings", []):
        if warning not in printed_warnings:
            print(f"WARNING: {warning}")
            printed_warnings.add(warning)
    for protocol_failure in report.get("protocol_failures", []):
        if protocol_failure not in printed_protocol_failures:
            print(f"PROTOCOL FAILURE: {protocol_failure}")
            printed_protocol_failures.add(protocol_failure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Master Prompt Agreement conformance checks.",
        allow_abbrev=False,
    )
    parser.add_argument("--profile", help="Profile id from conformance/profiles.json.")
    parser.add_argument("--root", type=Path, default=FRAMEWORK_ROOT, help="Framework or downstream project root.")
    parser.add_argument(
        "--contract-root",
        default=".",
        help="Safe project-relative directory containing generated contract and state files.",
    )
    parser.add_argument(
        "--project-kind",
        choices=sorted(contract_model.PROJECT_KINDS),
        default="downstream",
        help="Selected project layout for project-subject profiles.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Conformance report format (default: text).",
    )
    parser.add_argument("--list", action="store_true", help="List available profiles and exit.")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Make aggregate warnings fail without changing per-check diagnostics.",
    )
    parser.add_argument(
        "--exact-product-tree",
        action="store_true",
        help=(
            "For framework-product, reject undeclared files, directories, links, "
            "and special entries; permit only the root .git administrative entry."
        ),
    )
    args = parser.parse_args(argv)

    if args.list:
        registry, metadata_errors = load_profiles()
        if registry is None or metadata_errors:
            report = {
                "profiles": [],
                "profile_results": [],
                "root": str(args.root),
                "checks": [],
                "errors": ordered_unique(metadata_errors),
                "warnings": [],
                "protocol_failures": [],
                "status": "fail",
                "error_class": "metadata",
            }
            print_report(report, args.format)
            return EXIT_INVALID_METADATA
        payload = [{"id": item["id"], "subject": item.get("subject")} for item in registry.get("profiles", [])]
        print(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
            if args.format == "json"
            else "\n".join(item["id"] for item in payload)
        )
        return 0
    if not args.profile:
        parser.error("--profile is required unless --list is used")

    project_root = args.root.resolve()
    contract_root, contract_root_error = project_instance_lint.contract_root_path(
        project_root,
        args.contract_root,
    )
    if contract_root_error:
        report = {
            "profiles": [args.profile],
            "profile_results": [],
            "root": str(project_root),
            "contract_root": args.contract_root,
            "checks": [],
            "errors": [contract_root_error],
            "warnings": [],
            "protocol_failures": [],
            "status": "fail",
            "error_class": "invocation",
        }
    else:
        report = run_profiles(
            [args.profile],
            project_root,
            contract_root=contract_root,
            contract_root_ref=args.contract_root,
            project_kind=args.project_kind,
            exact_product_tree=args.exact_product_tree,
        )
    apply_strict_warning_policy(
        report,
        strict_warnings=args.strict_warnings,
    )
    print_report(report, args.format)
    if report.get("status") != "fail":
        return 0
    if report.get("error_class") == "metadata":
        return EXIT_INVALID_METADATA
    if report.get("error_class") == "invocation":
        return EXIT_INVALID_INVOCATION
    return EXIT_CONFORMANCE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
