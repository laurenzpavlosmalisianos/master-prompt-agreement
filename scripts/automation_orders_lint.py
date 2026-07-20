#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import generated_sow_text
import project_state_identity
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
AUTONOMY_LEVELS = {"observe", "propose", "act"}
APPROVAL_MODES = {"per_run", "standing_order"}
CONCURRENCY_MODES = {"allow", "forbid"}
FAILURE_POLICIES = {"log", "log-and-notify", "disable-until-review"}
STANDARDS = {"standard", "careful", "adversarial", "forensic"}
WRITE_SCOPES = {"none", "artifacts", "repo", "external"}
SCHEDULER_CONTEXT_MODES = {"fresh_run", "thread_continuity"}
TARGETS = {"cron"}
SCHEMA_VERSION = 7
CONTROL_RE = generated_sow_text.SINGLE_LINE_FORBIDDEN_CONTROL_RE
JOB_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
BACKEND_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
TOP_LEVEL_KEYS = {
    "jobs",
    project_state_identity.JSON_STATE_ORIGIN_KEY,
    "preferred_backend",
    "schema_version",
}
REQUIRED_TOP_LEVEL_KEYS = {"jobs", "preferred_backend", "schema_version"}
REQUIRED_JOB_KEYS = {
    "approval_mode",
    "autonomy_level",
    "command",
    "concurrency",
    "cwd",
    "enabled",
    "execution_sources",
    "failure_policy",
    "id",
    "idempotency",
    "instruction_sources",
    "objective",
    "outputs",
    "schedule",
    "scheduler_artifacts",
    "scheduler_context_mode",
    "state_policy",
    "standard_of_care",
    "timeout_minutes",
    "timezone",
    "workload_class",
    "write_scope",
}
AUTOMATION_SOW_SUMMARY_FIELDS = (
    "id",
    "objective",
    "schedule",
    "timezone",
    "autonomy_level",
    "approval_mode",
)
LIST_JOB_KEYS = {"execution_sources", "instruction_sources"}
SCHEDULER_ARTIFACT_KEYS = {
    "lock_file",
    "log_file",
    "max_log_bytes",
    "redaction",
    "retention",
    "root",
}
MIN_SCHEDULER_LOG_BYTES = 4 * 1024
MAX_SCHEDULER_LOG_BYTES = 1024 * 1024 * 1024
MAX_TIMEOUT_MINUTES = 60
REVIEWER_RUNTIME_CLASSES = {"deterministic_tool", "human", "hybrid", "model"}
REVIEWER_BOUNDARY_MODES = {"external", "local"}
WORKLOAD_CLASSES = {"general", "parser_or_extractor_change"}
SOURCE_ACCESS_CLASSES = {
    "account_visible",
    "authenticated",
    "public_unauthenticated",
    "sensitive",
}
NONPUBLIC_SOURCE_ACCESS_CLASSES = SOURCE_ACCESS_CLASSES - {"public_unauthenticated"}
IDEMPOTENCY_KEYS = {"key", "mode"}
IDEMPOTENCY_MODES = {
    "deduplicate",
    "disabled_only",
    "read_only",
    "replace",
    "transactional",
}
STATE_POLICY_KEYS = {"checkpoint", "persistence", "reference", "resume"}
STATE_PERSISTENCE_MODES = {"external_store", "none", "project_file"}
STATE_CHECKPOINT_MODES = {"none", "per_run", "transactional"}
STATE_RESUME_MODES = {"cursor", "restart"}
RETENTION_KEYS = {"days", "manual_owner", "manual_trigger", "mode"}
RETENTION_MODES = {
    "bounded_days",
    "delete_after_run",
    "indefinite",
    "manual_archive_or_truncate",
}
REDACTION_KEYS = {"mode"}
REDACTION_MODES = {"command_redacts_before_capture", "retain_verbatim"}
EXTERNAL_REVIEW_KEYS = {
    "allowed_data_classes",
    "authentication",
    "egress",
    "max_requests",
    "redaction",
    "retained_artifacts",
    "retention_days",
    "sensitive_data",
    "unlisted_data",
}
EXTERNAL_REVIEW_DATA_CLASSES = {
    "public_advisory_urls",
    "public_documentation",
    "public_release_notes",
    "public_source_metadata",
    "public_source_urls",
    "user_supplied_packet",
}
EXTERNAL_REVIEW_AUTH_MODES = {"approved_service_identity", "isolated_session", "none"}
EXTERNAL_REVIEW_REDACTION_MODES = {"before_egress", "not_required_public_only"}
EXTERNAL_REVIEW_RETAINED_MODES = {"none", "sanitized_result_only"}
SOURCE_POLICY_KEYS = {
    "allowed_capabilities",
    "max_requests_per_run",
    "oauth_scopes",
    "primary_source_verification",
    "retention_days",
    "source_aliases",
    "terms_reviewed_on",
    "write_access",
}
SOURCE_CAPABILITIES = {"fetch", "list", "read", "search"}
PARSER_CHANGE_KEYS = {
    "approval_record",
    "approved_output_digests",
    "change_kind",
    "change_record",
    "expected_output_digests",
    "fail_closed_action",
    "golden_fixture_paths",
    "implementation_version",
    "input_fixture_digests",
    "old_new_comparison_completed",
    "primary_evidence_verified",
    "schema_version",
    "verification_command",
}
PARSER_CHANGE_KINDS = {"extractor", "parser", "parser_and_extractor"}
PARSER_FAIL_CLOSED_ACTIONS = {"block", "manual_review", "stop"}
AUTHORITY_KEYS = {
    "allowed_actions",
    "basis",
    "effect_class",
    "failure_action",
    "resource_refs",
    "source_ref",
    "validity",
    "verification",
}
AUTHORITY_BASES = {"per_run_user_approval", "standing_project_grant"}
AUTHORITY_EFFECT_CLASSES = {"external_write", "observe", "propose", "repo_write"}
AUTHORITY_FAILURE_ACTIONS = {
    "disable_until_review",
    "record_and_continue",
    "record_and_notify",
}
AUTHORITY_VALIDITY_KEYS = {"expires_on", "mode", "revocation_events"}
AUTHORITY_VALIDITY_MODES = {"per_run", "time_window", "until_revoked"}
AUTHORITY_REVOCATION_EVENTS = {
    "date_reached",
    "repeated_failure",
    "schedule_disabled",
    "user_revocation",
}
AUTHORITY_VERIFICATION_KEYS = {"evidence_refs", "kind", "on_failure"}
AUTHORITY_VERIFICATION_KINDS = {"deterministic", "human", "hybrid"}
ACTION_TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
REFERENCE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,255}")
VERSION_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}")
SHA256_TOKEN_RE = re.compile(r"sha256:[0-9a-f]{64}")
DESCRIPTIVE_JOB_KEYS = {"description"}
CLASSIFICATION_KEYS = {
    "reviewer_boundary_mode",
    "reviewer_runtime_class",
    "source_access_class",
}
STRUCTURED_JOB_KEYS = {
    "authority",
    "external_review",
    "idempotency",
    "parser_change",
    "source_policy",
    "state_policy",
}
JOB_KEYS = (
    REQUIRED_JOB_KEYS
    | LIST_JOB_KEYS
    | DESCRIPTIVE_JOB_KEYS
    | CLASSIFICATION_KEYS
    | STRUCTURED_JOB_KEYS
)
CRON_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
CRON_FAILURE_POLICIES = {"log"}
CRON_SUPPORTED_RETENTION_MODES = {"indefinite", "manual_archive_or_truncate"}
MAX_CRON_EXPRESSION_CHARS = 256
CRON_EXPRESSION_RE = re.compile(
    r"[0-9*/,-]+(?: +[0-9*/,-]+){4}",
    re.ASCII,
)
CRON_NUMBER_RE = re.compile(r"[0-9]{1,3}", re.ASCII)
EXACT_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
AUTOMATION_REQUIRED_INSTRUCTION_SOURCES = {
    "practice_guides/scheduled_automation.md",
    "task_orders/automation.md",
}
SOURCE_REFERENCE_KEYS = {"path", "root"}
SOURCE_REFERENCE_ROOTS = {"framework", "project"}
MAX_BOUND_SOURCE_REFERENCES = 128
MAX_BOUND_SOURCE_FILE_BYTES = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES
MAX_BOUND_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
INSTRUCTION_SOURCE_PREFIXES = (
    "local_overlays/",
    "practice_guides/",
    "runtime/",
    "task_orders/",
    "project_state_templates/",
)
PROJECT_STATE_INSTRUCTION_SOURCES = {
    "AGENT_PROJECT.md",
    "AUTOMATION_ORDERS.json",
    "DECISIONS.md",
    "PRECEDENTS.md",
    "SOURCE_MONITOR_RESEARCHER.md",
    "SOURCE_PACKS.md",
    "SOURCE_UPDATE.md",
    "STATEMENT_OF_WORK.md",
    "TODO.md",
}
ARTIFACT_OUTPUT_PREFIXES = ("artifacts/", "review_artifacts/")


def current_utc_date() -> date:
    """Capture the UTC calendar date for one manifest-validation invocation."""

    return datetime.now(timezone.utc).date()


def parse_exact_calendar_date(
    prefix: str,
    value: object,
    errors: list[str],
    *,
    qualifier: str = "",
) -> date | None:
    """Parse one exact ASCII YYYY-MM-DD value without accepting ISO variants."""

    if not isinstance(value, str) or EXACT_DATE_RE.fullmatch(value) is None:
        errors.append(f"{prefix} must be an exact YYYY-MM-DD date{qualifier}")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{prefix} must be an exact YYYY-MM-DD date{qualifier}")
        return None


def load_manifest(path: Path) -> object:
    raw = safe_paths.read_regular_file_bytes(
        path,
        description="automation orders manifest",
    )
    return safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))


def _normalize_project_root_lexical(
    project_root: Path,
    *,
    description: str,
) -> Path:
    expanded = project_root.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{description} must be an absolute directory path")
    if CONTROL_RE.search(os.fspath(expanded)):
        raise ValueError(f"{description} must not contain control characters")
    normalized = Path(os.path.normpath(os.fspath(expanded)))
    if normalized.anchor != "/":
        raise ValueError(f"{description} must be a normalized POSIX absolute path")
    if normalized == Path(normalized.anchor):
        raise ValueError(f"{description} must not be the filesystem root")
    home = Path.home().expanduser().absolute()
    if normalized == home:
        raise ValueError(f"{description} must not be the scheduler user's home directory")
    return normalized


def normalize_project_root(
    project_root: Path,
    *,
    description: str = "selected project root",
    require_existing: bool = True,
) -> Path:
    """Return one explicit project-directory boundary suitable for scheduling."""

    normalized = _normalize_project_root_lexical(
        project_root,
        description=description,
    )
    unsafe_symlinks = [
        component
        for component in safe_paths.symlink_components(normalized)
        if not safe_paths.is_allowed_system_symlink(component)
    ]
    if unsafe_symlinks:
        raise ValueError(
            f"{description} must not contain symlink components: {unsafe_symlinks[0]}"
        )
    if require_existing and not normalized.exists():
        raise ValueError(f"{description} does not exist: {normalized}")
    if normalized.exists() and not normalized.is_dir():
        raise ValueError(f"{description} must be a directory: {normalized}")
    return normalized


def _manifest_relative_to_project_lexical(
    project_root: Path,
    manifest_path: Path,
) -> tuple[Path, Path]:
    if not manifest_path.is_absolute():
        raise ValueError("automation manifest path must be absolute")
    if CONTROL_RE.search(os.fspath(manifest_path)):
        raise ValueError("automation manifest path must not contain control characters")
    normalized_manifest = Path(os.path.normpath(os.fspath(manifest_path.expanduser())))
    try:
        relative = normalized_manifest.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            "automation manifest must be inside the selected project root"
        ) from exc
    if not relative.parts:
        raise ValueError("automation manifest must name a file inside the selected project root")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("automation manifest must use one normalized safe relative path")
    return normalized_manifest, relative


def manifest_relative_to_project(
    project_root: Path,
    manifest_path: Path,
    *,
    require_existing: bool = True,
) -> Path:
    """Return the manifest path relative to its explicit selected project root."""

    _normalized_manifest, relative = _manifest_relative_to_project_lexical(
        project_root,
        manifest_path,
    )
    candidate = safe_paths.safe_relative_child(
        project_root,
        relative,
        description="automation manifest",
    )
    if require_existing:
        spelling_errors = safe_paths.exact_relative_path_spelling_errors(
            project_root,
            relative,
            description="automation manifest",
        )
        if spelling_errors:
            raise ValueError(spelling_errors[0])
        if not candidate.exists():
            raise ValueError(f"automation manifest does not exist: {relative.as_posix()}")
        if not candidate.is_file():
            raise ValueError(
                f"automation manifest must be a regular file: {relative.as_posix()}"
            )
    return relative


def has_control(value: str) -> bool:
    return bool(CONTROL_RE.search(value))


def validate_text(
    prefix: str,
    value: object,
    errors: list[str],
    *,
    cron_safe: bool = False,
    non_empty: bool = True,
) -> bool:
    if not isinstance(value, str):
        errors.append(f"{prefix} must be a string")
        return False
    if non_empty and not value.strip():
        errors.append(f"{prefix} must be non-empty")
        return False
    if has_control(value):
        errors.append(f"{prefix} must not contain control characters")
        return False
    if cron_safe and "%" in value:
        errors.append(f"{prefix} must not contain '%' because cron treats it as a command delimiter")
        return False
    return True


def validate_generated_sow_summary_text(
    prefix: str,
    value: object,
    errors: list[str],
) -> bool:
    """Reject grammar that could create structure in the generated SOW row."""

    if not isinstance(value, str):
        return True
    if has_control(value):
        errors.append(f"{prefix} must not contain control characters")
        return False
    syntax_kind = generated_sow_text.generated_sow_control_syntax_kind(value)
    if syntax_kind is not None:
        errors.append(
            f"{prefix} must not contain generated-SOW {syntax_kind}"
        )
        return False
    return True


def cron_part_valid(part: str, lower: int, upper: int) -> bool:
    if not part or len(part) > MAX_CRON_EXPRESSION_CHARS or not part.isascii():
        return False
    for piece in part.split(","):
        base, separator, step = piece.partition("/")
        if separator:
            if CRON_NUMBER_RE.fullmatch(step) is None or int(step) <= 0:
                return False
        if base == "*":
            continue
        if "-" in base:
            start, _, end = base.partition("-")
            if (
                CRON_NUMBER_RE.fullmatch(start) is None
                or CRON_NUMBER_RE.fullmatch(end) is None
            ):
                return False
            left, right = int(start), int(end)
            if left > right or left < lower or right > upper:
                return False
            continue
        if CRON_NUMBER_RE.fullmatch(base) is None:
            return False
        value = int(base)
        if value < lower or value > upper:
            return False
    return True


def validate_cron(value: object) -> bool:
    if (
        not isinstance(value, str)
        or len(value) > MAX_CRON_EXPRESSION_CHARS
        or has_control(value)
        or "%" in value
        or CRON_EXPRESSION_RE.fullmatch(value) is None
    ):
        return False
    fields = value.split()
    return len(fields) == 5 and all(
        cron_part_valid(field, lower, upper)
        for field, (lower, upper) in zip(fields, CRON_BOUNDS, strict=True)
    )


def output_path_error(value: str, write_scope: str) -> str | None:
    if not value.strip() or has_control(value):
        return "outputs must be non-empty strings without control characters"
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return f"output path must be repo-relative: {value}"
    if "\\" in value:
        return f"output path must use POSIX separators: {value}"
    if any(part in {"", ".", ".."} for part in value.split("/")) or ".." in windows_path.parts:
        return f"output path must not contain empty, current-directory, or traversal segments: {value}"
    if write_scope == "none":
        return "write_scope none must not declare outputs"
    if write_scope == "artifacts" and not value.startswith(ARTIFACT_OUTPUT_PREFIXES):
        return (
            "write_scope artifacts outputs must stay under "
            f"{', '.join(ARTIFACT_OUTPUT_PREFIXES)}: {value}"
        )
    return None


def validate_outputs(
    prefix: str,
    outputs: object,
    write_scope: object,
    errors: list[str],
) -> bool:
    if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
        errors.append(f"{prefix}: outputs must be a list of strings")
        return False
    scope = write_scope if isinstance(write_scope, str) else ""
    valid = True
    for item in outputs:
        error = output_path_error(item, scope)
        if error:
            errors.append(f"{prefix}: {error}")
            valid = False
    return valid


def _normalize_relative_path_lexical(value: str, *, description: str) -> str:
    """Validate a relative path without consulting mutable filesystem state."""

    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or has_control(value)
        or any(marker in value for marker in ("<", ">"))
    ):
        raise ValueError(f"{description} must be non-empty plain path text")
    if "://" in value or safe_paths.URI_SCHEME_RE.match(value):
        raise ValueError(
            f"{description} must be repo-relative, not a URI or absolute path: {value}"
        )
    if (
        "\\" in value
        or path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or not path.parts
    ):
        raise ValueError(f"{description} must be a safe repo-relative path: {value}")
    return path.as_posix()


def normalized_scheduler_path(
    prefix: str,
    value: object,
    root: Path,
    errors: list[str],
    *,
    filesystem_checks: bool,
) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{prefix} must be a string")
        return None
    if has_control(value):
        errors.append(f"{prefix} must not contain control characters")
        return None
    try:
        if filesystem_checks:
            normalized = safe_paths.normalize_repo_relative_path(
                value,
                root,
                description=prefix,
            )
            if root.exists():
                spelling_errors = safe_paths.exact_relative_path_spelling_errors(
                    root,
                    Path(normalized),
                    description=prefix,
                )
                if spelling_errors:
                    errors.extend(spelling_errors)
                    return None
            return normalized
        return _normalize_relative_path_lexical(value, description=prefix)
    except ValueError as exc:
        errors.append(str(exc))
        return None


def _portable_artifact_components(*values: str) -> tuple[str, ...]:
    components: list[str] = []
    for value in values:
        if value == ".":
            continue
        normalized = _normalize_relative_path_lexical(
            value,
            description="scheduler artifact topology path",
        )
        components.extend(PurePosixPath(normalized).parts)
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in components)


def validate_scheduler_artifact_topology(
    jobs: list[object],
    errors: list[str],
) -> None:
    """Reject portable file/directory collisions across every declared job."""

    files: list[tuple[str, str, tuple[str, ...]]] = []
    directories: dict[tuple[str, ...], set[str]] = {}
    for index, item in enumerate(jobs, start=1):
        if not isinstance(item, dict):
            continue
        job_id = item.get("id")
        cwd = item.get("cwd")
        artifacts = item.get("scheduler_artifacts")
        if (
            not isinstance(job_id, str)
            or not isinstance(cwd, str)
            or not isinstance(artifacts, dict)
        ):
            continue
        root = artifacts.get("root")
        log_file = artifacts.get("log_file")
        lock_file = artifacts.get("lock_file")
        if not isinstance(root, str) or not isinstance(log_file, str):
            continue
        role_paths: list[tuple[str, str]] = [("log_file", log_file)]
        if isinstance(lock_file, str):
            role_paths.append(("lock_file", lock_file))
        for role, relative in role_paths:
            try:
                path = _portable_artifact_components(cwd, root, relative)
            except ValueError:
                continue
            if not path:
                continue
            label = f"job {job_id} {role}"
            files.append((job_id, label, path))
            for length in range(1, len(path)):
                directories.setdefault(path[:length], set()).add(label)

    reported: set[tuple[str, ...]] = set()
    for left_index, (_left_job, left_label, left_path) in enumerate(files):
        for _right_job, right_label, right_path in files[left_index + 1 :]:
            if left_path != right_path:
                continue
            key = ("file", *left_path, left_label, right_label)
            if key not in reported:
                errors.append(
                    "scheduler artifact topology collision: "
                    f"{left_label} and {right_label} resolve to the same portable file path"
                )
                reported.add(key)
        for directory_label in sorted(directories.get(left_path, set())):
            if directory_label == left_label:
                continue
            key = ("directory", *left_path, left_label, directory_label)
            if key in reported:
                continue
            errors.append(
                "scheduler artifact topology collision: "
                f"{left_label} resolves where {directory_label} requires a directory"
            )
            reported.add(key)


def validate_scheduler_artifacts(
    prefix: str,
    job: dict[str, object],
    errors: list[str],
    *,
    job_cwd: Path | None,
    concurrency_valid: bool,
    filesystem_checks: bool,
) -> None:
    artifacts = job.get("scheduler_artifacts")
    if not isinstance(artifacts, dict):
        errors.append(f"{prefix}: scheduler_artifacts must be an object")
        return
    unknown = sorted(set(artifacts) - SCHEDULER_ARTIFACT_KEYS)
    if unknown:
        errors.append(f"{prefix}: scheduler_artifacts has unknown keys {unknown}")
    missing = sorted(SCHEDULER_ARTIFACT_KEYS - set(artifacts))
    if missing:
        errors.append(f"{prefix}: scheduler_artifacts is missing keys {missing}")
        return

    max_log_bytes = artifacts["max_log_bytes"]
    if (
        not isinstance(max_log_bytes, int)
        or isinstance(max_log_bytes, bool)
        or not MIN_SCHEDULER_LOG_BYTES
        <= max_log_bytes
        <= MAX_SCHEDULER_LOG_BYTES
    ):
        errors.append(
            f"{prefix}: scheduler_artifacts.max_log_bytes must be an integer "
            f"from {MIN_SCHEDULER_LOG_BYTES} through {MAX_SCHEDULER_LOG_BYTES}"
        )

    retention = validate_closed_object(
        f"{prefix}: scheduler_artifacts.retention",
        artifacts["retention"],
        RETENTION_KEYS,
        errors,
    )
    if retention is not None:
        mode = retention["mode"]
        mode_valid = validate_choice(
            f"{prefix}: scheduler_artifacts.retention.mode",
            mode,
            RETENTION_MODES,
            errors,
        )
        days = retention["days"]
        manual_owner = retention["manual_owner"]
        manual_trigger = retention["manual_trigger"]
        if mode_valid and mode == "bounded_days":
            validate_bounded_integer(
                f"{prefix}: scheduler_artifacts.retention.days",
                days,
                1,
                3650,
                errors,
            )
        elif mode_valid and days is not None:
            errors.append(
                f"{prefix}: scheduler_artifacts.retention.days must be null "
                "unless mode is bounded_days"
            )
        if mode_valid and mode == "manual_archive_or_truncate":
            validate_text(
                f"{prefix}: scheduler_artifacts.retention.manual_owner",
                manual_owner,
                errors,
                non_empty=True,
            )
            validate_text(
                f"{prefix}: scheduler_artifacts.retention.manual_trigger",
                manual_trigger,
                errors,
                non_empty=True,
            )
        elif mode_valid:
            if manual_owner is not None:
                errors.append(
                    f"{prefix}: scheduler_artifacts.retention.manual_owner must be "
                    "null unless mode is manual_archive_or_truncate"
                )
            if manual_trigger is not None:
                errors.append(
                    f"{prefix}: scheduler_artifacts.retention.manual_trigger must be "
                    "null unless mode is manual_archive_or_truncate"
                )

    redaction = validate_closed_object(
        f"{prefix}: scheduler_artifacts.redaction",
        artifacts["redaction"],
        REDACTION_KEYS,
        errors,
    )
    if redaction is not None:
        validate_choice(
            f"{prefix}: scheduler_artifacts.redaction.mode",
            redaction["mode"],
            REDACTION_MODES,
            errors,
        )

    if job_cwd is None:
        return
    cwd = job_cwd
    root_value = normalized_scheduler_path(
        f"{prefix}: scheduler_artifacts.root",
        artifacts["root"],
        cwd,
        errors,
        filesystem_checks=filesystem_checks,
    )
    if root_value is None:
        return
    artifact_root = cwd / root_value
    if filesystem_checks and artifact_root.exists() and not artifact_root.is_dir():
        errors.append(f"{prefix}: scheduler_artifacts.root must be a directory path")
        return

    log_value = normalized_scheduler_path(
        f"{prefix}: scheduler_artifacts.log_file",
        artifacts["log_file"],
        artifact_root,
        errors,
        filesystem_checks=filesystem_checks,
    )
    lock_value = artifacts["lock_file"]
    normalized_lock: str | None = None
    concurrency = job.get("concurrency")
    if concurrency_valid and concurrency == "forbid":
        normalized_lock = normalized_scheduler_path(
            f"{prefix}: scheduler_artifacts.lock_file",
            lock_value,
            artifact_root,
            errors,
            filesystem_checks=filesystem_checks,
        )
    elif concurrency_valid and concurrency == "allow" and lock_value is not None:
        errors.append(
            f"{prefix}: scheduler_artifacts.lock_file must be null when concurrency is allow"
        )

    if log_value is not None:
        log_path = artifact_root / log_value
        if filesystem_checks and log_path.exists() and log_path.is_dir():
            errors.append(f"{prefix}: scheduler_artifacts.log_file must not name a directory")
    if normalized_lock is not None:
        lock_path = artifact_root / normalized_lock
        if filesystem_checks and lock_path.exists() and lock_path.is_dir():
            errors.append(f"{prefix}: scheduler_artifacts.lock_file must not name a directory")
        if normalized_lock == log_value:
            errors.append(
                f"{prefix}: scheduler_artifacts.log_file and lock_file must be distinct"
            )


def timezone_data_available() -> bool:
    try:
        ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        return False
    return True


def validate_timezone(prefix: str, value: object, errors: list[str]) -> bool:
    if not validate_text(prefix, value, errors, cron_safe=True):
        return False
    if not isinstance(value, str):
        errors.append(f"{prefix} must be a string")
        return False
    if not timezone_data_available():
        errors.append(
            f"{prefix} cannot be validated because timezone data is unavailable; "
            "install system tzdata or the Python tzdata package"
        )
        return False
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        errors.append(f"{prefix} must be a valid IANA timezone name")
        return False
    except ValueError:
        errors.append(f"{prefix} must be a normalized IANA timezone name, not an absolute or traversal path")
        return False
    return True


def validate_choice(prefix: str, value: object, choices: set[str], errors: list[str]) -> bool:
    if not isinstance(value, str):
        errors.append(f"{prefix} must be a string")
        return False
    if value not in choices:
        errors.append(f"{prefix} must be one of {sorted(choices)}")
        return False
    return True


def validate_string_list(prefix: str, value: object, errors: list[str]) -> bool:
    if not isinstance(value, list) or not value:
        errors.append(f"{prefix} must be a non-empty list")
        return False
    valid = True
    for index, item in enumerate(value, start=1):
        if not validate_text(f"{prefix}[{index}]", item, errors, non_empty=True):
            valid = False
    if valid and len(value) != len(set(value)):
        errors.append(f"{prefix} must not contain duplicates")
        valid = False
    return valid


def validate_closed_object(
    prefix: str,
    value: object,
    keys: set[str],
    errors: list[str],
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return None
    mapping = cast(dict[str, object], value)
    unknown = sorted(set(mapping) - keys)
    missing = sorted(keys - set(mapping))
    if unknown:
        errors.append(f"{prefix} has unknown keys {unknown}")
    if missing:
        errors.append(f"{prefix} is missing keys {missing}")
        return None
    return mapping


def validate_enum_list(
    prefix: str,
    value: object,
    choices: set[str],
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> list[str] | None:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        errors.append(f"{prefix} must be {qualifier}")
        return None
    items: list[str] = []
    valid = True
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or item not in choices:
            errors.append(f"{prefix}[{index}] must be one of {sorted(choices)}")
            valid = False
            continue
        items.append(item)
    if len(items) != len(set(items)):
        errors.append(f"{prefix} must not contain duplicates")
        valid = False
    return items if valid else None


def validate_token_list(
    prefix: str,
    value: object,
    pattern: re.Pattern[str],
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> list[str] | None:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        errors.append(f"{prefix} must be {qualifier}")
        return None
    items: list[str] = []
    valid = True
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or pattern.fullmatch(item) is None:
            errors.append(f"{prefix}[{index}] must match {pattern.pattern}")
            valid = False
            continue
        items.append(item)
    if len(items) != len(set(items)):
        errors.append(f"{prefix} must not contain duplicates")
        valid = False
    return items if valid else None


def validate_bounded_integer(
    prefix: str,
    value: object,
    lower: int,
    upper: int,
    errors: list[str],
) -> bool:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not lower <= value <= upper
    ):
        errors.append(f"{prefix} must be an integer from {lower} through {upper}")
        return False
    return True


def normalized_job_cwd(
    prefix: str,
    value: object,
    project_root: Path,
    errors: list[str],
    *,
    require_existing: bool = False,
    filesystem_checks: bool = True,
) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{prefix} must be a string")
        return None
    if has_control(value):
        errors.append(f"{prefix} must not contain control characters")
        return None
    if value == ".":
        return value
    try:
        if filesystem_checks:
            normalized = safe_paths.normalize_repo_relative_path(
                value,
                project_root,
                description=prefix,
            )
        else:
            normalized = _normalize_relative_path_lexical(value, description=prefix)
    except ValueError as exc:
        errors.append(str(exc))
        return None
    candidate = project_root / normalized
    if filesystem_checks and require_existing and not candidate.exists():
        errors.append(
            f"{prefix} must name an existing directory inside the selected project root"
        )
        return None
    if filesystem_checks and candidate.exists() and not candidate.is_dir():
        errors.append(f"{prefix} must name a directory inside the selected project root")
        return None
    if filesystem_checks and candidate.exists():
        spelling_errors = safe_paths.exact_relative_path_spelling_errors(
            project_root,
            Path(normalized),
            description=prefix,
        )
        if spelling_errors:
            errors.extend(spelling_errors)
            return None
    return normalized


def source_reference_path_error(
    field_name: str,
    source_root: str,
    value: str,
    project_root: Path,
    *,
    instruction_source: bool,
    filesystem_checks: bool,
) -> str | None:
    if instruction_source and not (
        value in PROJECT_STATE_INSTRUCTION_SOURCES
        or value.startswith(INSTRUCTION_SOURCE_PREFIXES)
    ):
        return (
            f"{field_name} paths must stay under approved instruction roots "
            f"or project state files: {value}"
        )
    if instruction_source and value.startswith("local_overlays/") and source_root != "project":
        return f"{field_name} local_overlays paths must be project-owned: {value}"

    root = REPO_ROOT if source_root == "framework" else project_root
    description = f"{field_name} {source_root}-rooted source"
    try:
        if filesystem_checks:
            normalized = safe_paths.normalize_repo_relative_path(
                value,
                root,
                description=description,
            )
        else:
            normalized = _normalize_relative_path_lexical(
                value,
                description=description,
            )
    except ValueError as exc:
        return str(exc)
    if not filesystem_checks:
        return None

    relative = Path(normalized)
    candidate = root / relative
    boundary_errors = safe_paths.bounded_input_errors(
        candidate,
        root,
        description=description,
    )
    if boundary_errors:
        return boundary_errors[0]
    spelling_errors = safe_paths.exact_relative_path_spelling_errors(
        root,
        relative,
        description=description,
    )
    if spelling_errors:
        return spelling_errors[0]
    if not candidate.exists():
        return f"{field_name} {source_root}-rooted source does not exist: {value}"
    if not candidate.is_file():
        return f"{field_name} {source_root}-rooted source must be a regular file: {value}"
    metadata = candidate.stat(follow_symlinks=False)
    if metadata.st_nlink != 1:
        return f"{field_name} {source_root}-rooted source must have exactly one hard link: {value}"
    if metadata.st_size > MAX_BOUND_SOURCE_FILE_BYTES:
        return (
            f"{field_name} {source_root}-rooted source exceeds the "
            f"{MAX_BOUND_SOURCE_FILE_BYTES}-byte limit: {value}"
        )
    return None


def validate_source_references(
    prefix: str,
    field_name: str,
    value: object,
    errors: list[str],
    *,
    project_root: Path,
    instruction_source: bool,
    allow_empty: bool,
    filesystem_checks: bool,
) -> bool:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        errors.append(f"{prefix}: {field_name} must be {qualifier}")
        return False
    if len(value) > MAX_BOUND_SOURCE_REFERENCES:
        errors.append(
            f"{prefix}: {field_name} must contain at most "
            f"{MAX_BOUND_SOURCE_REFERENCES} references"
        )
        return False

    valid = True
    references: list[tuple[str, str]] = []
    for index, item in enumerate(value, start=1):
        item_prefix = f"{prefix}: {field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_prefix} must be an object")
            valid = False
            continue
        mapping = cast(dict[str, object], item)
        unknown = sorted(set(mapping) - SOURCE_REFERENCE_KEYS)
        missing = sorted(SOURCE_REFERENCE_KEYS - set(mapping))
        if unknown:
            errors.append(f"{item_prefix} has unknown keys {unknown}")
            valid = False
        if missing:
            errors.append(f"{item_prefix} is missing keys {missing}")
            valid = False
            continue
        source_root = mapping["root"]
        path = mapping["path"]
        root_valid = validate_choice(
            f"{item_prefix}.root",
            source_root,
            SOURCE_REFERENCE_ROOTS,
            errors,
        )
        path_valid = validate_text(
            f"{item_prefix}.path",
            path,
            errors,
            non_empty=True,
        )
        if not root_valid or not path_valid:
            valid = False
            continue
        assert isinstance(source_root, str)
        assert isinstance(path, str)
        references.append((source_root, path))
        path_error = source_reference_path_error(
            field_name,
            source_root,
            path,
            project_root,
            instruction_source=instruction_source,
            filesystem_checks=filesystem_checks,
        )
        if path_error is not None:
            errors.append(f"{item_prefix}: {path_error}")
            valid = False
            continue

    collision_identities = [
        (source_root, unicodedata.normalize("NFC", path).casefold())
        for source_root, path in references
    ]
    if len(collision_identities) != len(set(collision_identities)):
        errors.append(
            f"{prefix}: {field_name} must not contain duplicate, case-colliding, "
            "or Unicode-normalization-colliding root/path pairs"
        )
        valid = False
    framework_instruction_paths = {
        path for source_root, path in references if source_root == "framework"
    }
    missing_automation_sources = sorted(
        AUTOMATION_REQUIRED_INSTRUCTION_SOURCES - framework_instruction_paths
    )
    if instruction_source and valid and missing_automation_sources:
        errors.append(
            f"{prefix}: instruction_sources must include the complete framework-rooted "
            f"automation instruction closure; missing {missing_automation_sources}"
        )
        valid = False
    return valid


def validate_combined_source_budget(
    prefix: str,
    job: dict[str, object],
    errors: list[str],
    *,
    project_root: Path,
    filesystem_checks: bool,
) -> bool:
    references: list[tuple[str, str]] = []
    for field_name in ("instruction_sources", "execution_sources"):
        value = job.get(field_name)
        if not isinstance(value, list):
            return False
        for item in value:
            if not isinstance(item, dict):
                return False
            source_root = item.get("root")
            path = item.get("path")
            if not isinstance(source_root, str) or not isinstance(path, str):
                return False
            references.append((source_root, path))
    if len(references) > MAX_BOUND_SOURCE_REFERENCES:
        errors.append(
            f"{prefix}: instruction_sources and execution_sources together must "
            f"contain at most {MAX_BOUND_SOURCE_REFERENCES} references"
        )
        return False
    if not filesystem_checks:
        return True
    total_bytes = 0
    for source_root, path in references:
        root = REPO_ROOT if source_root == "framework" else project_root
        try:
            total_bytes += (root / path).stat(follow_symlinks=False).st_size
        except OSError:
            return False
    if total_bytes > MAX_BOUND_SOURCE_TOTAL_BYTES:
        errors.append(
            f"{prefix}: declared instruction and execution sources exceed the "
            f"{MAX_BOUND_SOURCE_TOTAL_BYTES}-byte aggregate limit"
        )
        return False
    return True


def requires_external_reviewer_boundary(job: dict[str, object]) -> bool:
    return job.get("reviewer_boundary_mode") == "external"


def requires_sensitive_source_boundary(job: dict[str, object]) -> bool:
    source_access_class = job.get("source_access_class")
    return (
        isinstance(source_access_class, str)
        and source_access_class in NONPUBLIC_SOURCE_ACCESS_CLASSES
    )


def validate_idempotency(
    prefix: str,
    job: dict[str, object],
    errors: list[str],
    *,
    enabled_valid: bool,
    write_scope_valid: bool,
) -> None:
    policy = validate_closed_object(
        f"{prefix}: idempotency",
        job.get("idempotency"),
        IDEMPOTENCY_KEYS,
        errors,
    )
    if policy is None:
        return
    mode = policy["mode"]
    mode_valid = validate_choice(
        f"{prefix}: idempotency.mode",
        mode,
        IDEMPOTENCY_MODES,
        errors,
    )
    key = policy["key"]
    if not mode_valid:
        return
    if mode in {"deduplicate", "replace", "transactional"}:
        if not isinstance(key, str) or REFERENCE_TOKEN_RE.fullmatch(key) is None:
            errors.append(
                f"{prefix}: idempotency.key must match {REFERENCE_TOKEN_RE.pattern} "
                f"when mode is {mode}"
            )
    elif key is not None:
        errors.append(
            f"{prefix}: idempotency.key must be null when mode is {mode}"
        )
    if enabled_valid and job.get("enabled") is True and mode == "disabled_only":
        errors.append(f"{prefix}: enabled jobs cannot use idempotency.mode disabled_only")
    if (
        mode == "read_only"
        and write_scope_valid
        and job.get("write_scope") != "none"
    ):
        errors.append(f"{prefix}: idempotency.mode read_only requires write_scope none")


def validate_state_policy(
    prefix: str,
    job: dict[str, object],
    errors: list[str],
    *,
    write_scope_valid: bool,
) -> dict[str, object] | None:
    policy = validate_closed_object(
        f"{prefix}: state_policy",
        job.get("state_policy"),
        STATE_POLICY_KEYS,
        errors,
    )
    if policy is None:
        return None
    persistence = policy["persistence"]
    checkpoint = policy["checkpoint"]
    resume = policy["resume"]
    persistence_valid = validate_choice(
        f"{prefix}: state_policy.persistence",
        persistence,
        STATE_PERSISTENCE_MODES,
        errors,
    )
    checkpoint_valid = validate_choice(
        f"{prefix}: state_policy.checkpoint",
        checkpoint,
        STATE_CHECKPOINT_MODES,
        errors,
    )
    resume_valid = validate_choice(
        f"{prefix}: state_policy.resume",
        resume,
        STATE_RESUME_MODES,
        errors,
    )
    reference = policy["reference"]
    if persistence_valid and persistence == "none":
        if reference is not None:
            errors.append(
                f"{prefix}: state_policy.reference must be null when persistence is none"
            )
    elif persistence_valid and persistence == "project_file":
        if not isinstance(reference, str):
            errors.append(
                f"{prefix}: state_policy.reference must be a safe project-relative path"
            )
        else:
            try:
                _normalize_relative_path_lexical(
                    reference,
                    description=f"{prefix}: state_policy.reference",
                )
            except ValueError as exc:
                errors.append(str(exc))
            else:
                write_scope = job.get("write_scope")
                if write_scope_valid and isinstance(write_scope, str):
                    if write_scope == "artifacts" and not reference.startswith(
                        ARTIFACT_OUTPUT_PREFIXES
                    ):
                        errors.append(
                            f"{prefix}: state_policy.reference must stay under "
                            f"{ARTIFACT_OUTPUT_PREFIXES} when write_scope is artifacts"
                        )
                    elif write_scope not in {"artifacts", "repo"}:
                        errors.append(
                            f"{prefix}: state_policy.persistence project_file requires "
                            "write_scope artifacts or repo"
                        )
    elif persistence_valid and persistence == "external_store":
        if not isinstance(reference, str) or REFERENCE_TOKEN_RE.fullmatch(reference) is None:
            errors.append(
                f"{prefix}: state_policy.reference must match {REFERENCE_TOKEN_RE.pattern} "
                "for an external store"
            )
        if write_scope_valid and job.get("write_scope") != "external":
            errors.append(
                f"{prefix}: state_policy.persistence external_store requires "
                "write_scope external"
            )
    if (
        checkpoint_valid
        and persistence_valid
        and checkpoint != "none"
        and persistence == "none"
    ):
        errors.append(
            f"{prefix}: state_policy.checkpoint {checkpoint} requires persistent state"
        )
    if (
        resume_valid
        and persistence_valid
        and resume == "cursor"
        and persistence == "none"
    ):
        errors.append(
            f"{prefix}: state_policy.resume cursor requires persistent state"
        )
    return policy


def validate_external_review(
    prefix: str,
    value: object,
    errors: list[str],
) -> None:
    policy = validate_closed_object(
        f"{prefix}: external_review",
        value,
        EXTERNAL_REVIEW_KEYS,
        errors,
    )
    if policy is None:
        return
    validate_enum_list(
        f"{prefix}: external_review.allowed_data_classes",
        policy["allowed_data_classes"],
        EXTERNAL_REVIEW_DATA_CLASSES,
        errors,
    )
    if policy["unlisted_data"] != "deny":
        errors.append(f"{prefix}: external_review.unlisted_data must be deny")
    if policy["sensitive_data"] != "deny":
        errors.append(f"{prefix}: external_review.sensitive_data must be deny")
    validate_choice(
        f"{prefix}: external_review.authentication",
        policy["authentication"],
        EXTERNAL_REVIEW_AUTH_MODES,
        errors,
    )
    if policy["egress"] != "approved_endpoints_only":
        errors.append(
            f"{prefix}: external_review.egress must be approved_endpoints_only"
        )
    validate_choice(
        f"{prefix}: external_review.redaction",
        policy["redaction"],
        EXTERNAL_REVIEW_REDACTION_MODES,
        errors,
    )
    retained_artifacts_valid = validate_choice(
        f"{prefix}: external_review.retained_artifacts",
        policy["retained_artifacts"],
        EXTERNAL_REVIEW_RETAINED_MODES,
        errors,
    )
    retention_days_valid = validate_bounded_integer(
        f"{prefix}: external_review.retention_days",
        policy["retention_days"],
        0,
        3650,
        errors,
    )
    if (
        retained_artifacts_valid
        and retention_days_valid
        and policy["retained_artifacts"] == "none"
        and policy["retention_days"] != 0
    ):
        errors.append(
            f"{prefix}: external_review.retention_days must be 0 when "
            "retained_artifacts is none"
        )
    if (
        retained_artifacts_valid
        and retention_days_valid
        and
        policy["retained_artifacts"] == "sanitized_result_only"
        and policy["retention_days"] == 0
    ):
        errors.append(
            f"{prefix}: external_review.retention_days must be at least 1 when "
            "retained_artifacts is sanitized_result_only"
        )
    validate_bounded_integer(
        f"{prefix}: external_review.max_requests",
        policy["max_requests"],
        1,
        100000,
        errors,
    )


def validate_source_policy(
    prefix: str,
    value: object,
    errors: list[str],
    *,
    effective_date: date,
) -> None:
    policy = validate_closed_object(
        f"{prefix}: source_policy",
        value,
        SOURCE_POLICY_KEYS,
        errors,
    )
    if policy is None:
        return
    validate_token_list(
        f"{prefix}: source_policy.source_aliases",
        policy["source_aliases"],
        ACTION_TOKEN_RE,
        errors,
    )
    validate_enum_list(
        f"{prefix}: source_policy.allowed_capabilities",
        policy["allowed_capabilities"],
        SOURCE_CAPABILITIES,
        errors,
    )
    validate_token_list(
        f"{prefix}: source_policy.oauth_scopes",
        policy["oauth_scopes"],
        REFERENCE_TOKEN_RE,
        errors,
        allow_empty=True,
    )
    validate_bounded_integer(
        f"{prefix}: source_policy.max_requests_per_run",
        policy["max_requests_per_run"],
        1,
        100000,
        errors,
    )
    reviewed_on = policy["terms_reviewed_on"]
    parsed = parse_exact_calendar_date(
        f"{prefix}: source_policy.terms_reviewed_on",
        reviewed_on,
        errors,
    )
    if parsed is not None and parsed > effective_date:
        errors.append(
            f"{prefix}: source_policy.terms_reviewed_on must not be in the future"
        )
    validate_bounded_integer(
        f"{prefix}: source_policy.retention_days",
        policy["retention_days"],
        0,
        3650,
        errors,
    )
    if policy["write_access"] != "deny":
        errors.append(f"{prefix}: source_policy.write_access must be deny")
    if policy["primary_source_verification"] != "required":
        errors.append(
            f"{prefix}: source_policy.primary_source_verification must be required"
        )


def validate_parser_change(
    prefix: str,
    value: object,
    errors: list[str],
) -> None:
    policy = validate_closed_object(
        f"{prefix}: parser_change",
        value,
        PARSER_CHANGE_KEYS,
        errors,
    )
    if policy is None:
        return
    validate_choice(
        f"{prefix}: parser_change.change_kind",
        policy["change_kind"],
        PARSER_CHANGE_KINDS,
        errors,
    )
    validate_token_list(
        f"{prefix}: parser_change.input_fixture_digests",
        policy["input_fixture_digests"],
        SHA256_TOKEN_RE,
        errors,
    )
    expected_digests = validate_token_list(
        f"{prefix}: parser_change.expected_output_digests",
        policy["expected_output_digests"],
        SHA256_TOKEN_RE,
        errors,
    )
    approved_digests = validate_token_list(
        f"{prefix}: parser_change.approved_output_digests",
        policy["approved_output_digests"],
        SHA256_TOKEN_RE,
        errors,
    )
    if expected_digests is not None and approved_digests is not None:
        if not set(expected_digests).issubset(approved_digests):
            errors.append(
                f"{prefix}: parser_change.approved_output_digests must cover "
                "expected_output_digests"
            )
    paths = policy["golden_fixture_paths"]
    if not isinstance(paths, list) or not paths:
        errors.append(
            f"{prefix}: parser_change.golden_fixture_paths must be a non-empty list"
        )
    else:
        for index, path_value in enumerate(paths, start=1):
            if not isinstance(path_value, str):
                errors.append(
                    f"{prefix}: parser_change.golden_fixture_paths[{index}] must be a string"
                )
                continue
            try:
                _normalize_relative_path_lexical(
                    path_value,
                    description=f"{prefix}: parser_change.golden_fixture_paths[{index}]",
                )
            except ValueError as exc:
                errors.append(str(exc))
    for key in ("schema_version", "implementation_version"):
        value_item = policy[key]
        if not isinstance(value_item, str) or VERSION_TOKEN_RE.fullmatch(value_item) is None:
            errors.append(
                f"{prefix}: parser_change.{key} must match {VERSION_TOKEN_RE.pattern}"
            )
    for key in ("change_record", "approval_record"):
        value_item = policy[key]
        if not isinstance(value_item, str):
            errors.append(f"{prefix}: parser_change.{key} must be a safe relative path")
            continue
        try:
            _normalize_relative_path_lexical(
                value_item,
                description=f"{prefix}: parser_change.{key}",
            )
        except ValueError as exc:
            errors.append(str(exc))
    validate_text(
        f"{prefix}: parser_change.verification_command",
        policy["verification_command"],
        errors,
    )
    for key in ("primary_evidence_verified", "old_new_comparison_completed"):
        if policy[key] is not True:
            errors.append(f"{prefix}: parser_change.{key} must be true")
    validate_choice(
        f"{prefix}: parser_change.fail_closed_action",
        policy["fail_closed_action"],
        PARSER_FAIL_CLOSED_ACTIONS,
        errors,
    )


def validate_authority(
    prefix: str,
    job: dict[str, object],
    errors: list[str],
    *,
    effective_date: date,
    valid_fields: frozenset[str],
) -> None:
    policy = validate_closed_object(
        f"{prefix}: authority",
        job.get("authority"),
        AUTHORITY_KEYS,
        errors,
    )
    if policy is None:
        return
    basis = policy["basis"]
    effect_class = policy["effect_class"]
    basis_valid = validate_choice(
        f"{prefix}: authority.basis",
        basis,
        AUTHORITY_BASES,
        errors,
    )
    effect_class_valid = validate_choice(
        f"{prefix}: authority.effect_class",
        effect_class,
        AUTHORITY_EFFECT_CLASSES,
        errors,
    )
    source_ref = policy["source_ref"]
    if not isinstance(source_ref, str) or REFERENCE_TOKEN_RE.fullmatch(source_ref) is None:
        errors.append(
            f"{prefix}: authority.source_ref must match {REFERENCE_TOKEN_RE.pattern}"
        )
    validate_token_list(
        f"{prefix}: authority.resource_refs",
        policy["resource_refs"],
        REFERENCE_TOKEN_RE,
        errors,
    )
    validate_token_list(
        f"{prefix}: authority.allowed_actions",
        policy["allowed_actions"],
        ACTION_TOKEN_RE,
        errors,
    )
    failure_action_valid = validate_choice(
        f"{prefix}: authority.failure_action",
        policy["failure_action"],
        AUTHORITY_FAILURE_ACTIONS,
        errors,
    )

    validity = validate_closed_object(
        f"{prefix}: authority.validity",
        policy["validity"],
        AUTHORITY_VALIDITY_KEYS,
        errors,
    )
    if validity is not None:
        mode = validity["mode"]
        mode_valid = validate_choice(
            f"{prefix}: authority.validity.mode",
            mode,
            AUTHORITY_VALIDITY_MODES,
            errors,
        )
        revocation_events = validate_enum_list(
            f"{prefix}: authority.validity.revocation_events",
            validity["revocation_events"],
            AUTHORITY_REVOCATION_EVENTS,
            errors,
        )
        expires_on = validity["expires_on"]
        if mode_valid and mode == "time_window":
            expiry = parse_exact_calendar_date(
                f"{prefix}: authority.validity.expires_on",
                expires_on,
                errors,
                qualifier=" when mode is time_window",
            )
            if expiry is not None and expiry < effective_date:
                errors.append(
                    f"{prefix}: authority.validity.expires_on must not be in the past"
                )
            if revocation_events is not None and "date_reached" not in revocation_events:
                errors.append(
                    f"{prefix}: authority.validity.revocation_events must include "
                    "date_reached for time_window"
                )
        elif mode_valid and expires_on is not None:
            errors.append(
                f"{prefix}: authority.validity.expires_on must be null unless "
                "mode is time_window"
            )
        if (
            mode_valid
            and mode != "time_window"
            and revocation_events is not None
            and "date_reached" in revocation_events
        ):
            errors.append(
                f"{prefix}: authority.validity.revocation_events may include "
                "date_reached only for time_window"
            )
        if (
            basis_valid
            and basis == "standing_project_grant"
            and revocation_events is not None
            and "user_revocation" not in revocation_events
        ):
            errors.append(
                f"{prefix}: standing_project_grant must include user_revocation "
                "in authority.validity.revocation_events"
            )
        if (
            basis_valid
            and mode_valid
            and basis == "per_run_user_approval"
            and mode != "per_run"
        ):
            errors.append(
                f"{prefix}: authority.validity.mode must be per_run for "
                "per_run_user_approval"
            )
        if (
            basis_valid
            and mode_valid
            and basis == "standing_project_grant"
            and mode == "per_run"
        ):
            errors.append(
                f"{prefix}: authority.validity.mode must be time_window or "
                "until_revoked for standing_project_grant"
            )

    verification = validate_closed_object(
        f"{prefix}: authority.verification",
        policy["verification"],
        AUTHORITY_VERIFICATION_KEYS,
        errors,
    )
    if verification is not None:
        validate_choice(
            f"{prefix}: authority.verification.kind",
            verification["kind"],
            AUTHORITY_VERIFICATION_KINDS,
            errors,
        )
        validate_token_list(
            f"{prefix}: authority.verification.evidence_refs",
            verification["evidence_refs"],
            REFERENCE_TOKEN_RE,
            errors,
        )
        if verification["on_failure"] != "block":
            errors.append(
                f"{prefix}: authority.verification.on_failure must be block"
            )

    approval_mode = job.get("approval_mode")
    if (
        "approval_mode" in valid_fields
        and basis_valid
        and isinstance(approval_mode, str)
    ):
        expected_basis = (
            "standing_project_grant"
            if approval_mode == "standing_order"
            else "per_run_user_approval"
        )
        if basis != expected_basis:
            errors.append(
                f"{prefix}: authority.basis must be {expected_basis} for "
                f"approval_mode {approval_mode}"
            )
    autonomy_value = job.get("autonomy_level")
    write_scope_value = job.get("write_scope")
    effect_map = {
        ("observe", "none"): "observe",
        ("observe", "artifacts"): "observe",
        ("propose", "artifacts"): "propose",
        ("propose", "repo"): "propose",
        ("act", "repo"): "repo_write",
        ("act", "external"): "external_write",
    }
    expected_effect = (
        effect_map.get((autonomy_value, write_scope_value))
        if (
            "autonomy_level" in valid_fields
            and "write_scope" in valid_fields
            and isinstance(autonomy_value, str)
            and isinstance(write_scope_value, str)
        )
        else None
    )
    if (
        expected_effect is not None
        and effect_class_valid
        and effect_class != expected_effect
    ):
        errors.append(
            f"{prefix}: authority.effect_class must be {expected_effect} for the "
            "declared autonomy_level and write_scope"
        )
    failure_value = job.get("failure_policy")
    failure_map = {
        "log": "record_and_continue",
        "log-and-notify": "record_and_notify",
        "disable-until-review": "disable_until_review",
    }
    expected_failure = (
        failure_map.get(failure_value)
        if "failure_policy" in valid_fields and isinstance(failure_value, str)
        else None
    )
    if (
        expected_failure is not None
        and failure_action_valid
        and policy["failure_action"] != expected_failure
    ):
        errors.append(
            f"{prefix}: authority.failure_action must be {expected_failure} for "
            f"failure_policy {job.get('failure_policy')}"
        )


def _validate_job_core(
    job: dict[str, object],
    prefix: str,
    seen_ids: set[str],
    errors: list[str],
    *,
    project_root: Path,
    require_existing_cwd: bool,
    filesystem_checks: bool,
) -> frozenset[str]:
    valid_fields: set[str] = set()
    sow_summary_text_valid = {
        key: validate_generated_sow_summary_text(
            f"{prefix}: {key}",
            job[key],
            errors,
        )
        for key in AUTOMATION_SOW_SUMMARY_FIELDS
    }
    job_id = job["id"]
    if sow_summary_text_valid["id"]:
        if (
            not isinstance(job_id, str)
            or has_control(job_id)
            or JOB_ID_RE.fullmatch(job_id) is None
        ):
            errors.append(
                f"{prefix}: id must be one control-free value matching "
                f"{JOB_ID_RE.pattern}"
            )
        elif job_id in seen_ids:
            errors.append(f"{prefix}: duplicate id")
        else:
            seen_ids.add(job_id)
            valid_fields.add("id")

    if isinstance(job["enabled"], bool):
        valid_fields.add("enabled")
    else:
        errors.append(f"{prefix}: enabled must be boolean")
    if sow_summary_text_valid["schedule"]:
        if validate_cron(job["schedule"]):
            valid_fields.add("schedule")
        else:
            errors.append(
                f"{prefix}: schedule must be a bounded ASCII numeric 5-field cron expression "
                "without '%'"
            )
    if sow_summary_text_valid["timezone"] and validate_timezone(
        f"{prefix}: timezone",
        job["timezone"],
        errors,
    ):
        valid_fields.add("timezone")
    if sow_summary_text_valid["objective"] and validate_text(
        f"{prefix}: objective",
        job["objective"],
        errors,
    ):
        valid_fields.add("objective")
    if sow_summary_text_valid["autonomy_level"] and validate_choice(
            f"{prefix}: autonomy_level",
            job["autonomy_level"],
            AUTONOMY_LEVELS,
            errors,
        ):
        valid_fields.add("autonomy_level")
    if validate_choice(
        f"{prefix}: standard_of_care",
        job["standard_of_care"],
        STANDARDS,
        errors,
    ):
        valid_fields.add("standard_of_care")
    if validate_choice(
        f"{prefix}: write_scope",
        job["write_scope"],
        WRITE_SCOPES,
        errors,
    ):
        valid_fields.add("write_scope")
    if sow_summary_text_valid["approval_mode"] and validate_choice(
            f"{prefix}: approval_mode",
            job["approval_mode"],
            APPROVAL_MODES,
            errors,
        ):
        valid_fields.add("approval_mode")
    if validate_choice(
        f"{prefix}: concurrency",
        job["concurrency"],
        CONCURRENCY_MODES,
        errors,
    ):
        valid_fields.add("concurrency")
    if validate_choice(
        f"{prefix}: failure_policy",
        job["failure_policy"],
        FAILURE_POLICIES,
        errors,
    ):
        valid_fields.add("failure_policy")
    if validate_choice(
        f"{prefix}: scheduler_context_mode",
        job["scheduler_context_mode"],
        SCHEDULER_CONTEXT_MODES,
        errors,
    ):
        valid_fields.add("scheduler_context_mode")
    if validate_choice(
        f"{prefix}: workload_class",
        job["workload_class"],
        WORKLOAD_CLASSES,
        errors,
    ):
        valid_fields.add("workload_class")
    normalized_cwd = normalized_job_cwd(
        f"{prefix}: cwd",
        job["cwd"],
        project_root,
        errors,
        require_existing=require_existing_cwd,
        filesystem_checks=filesystem_checks,
    )
    job_cwd: Path | None = None
    if normalized_cwd is not None:
        valid_fields.add("cwd")
        job_cwd = (
            project_root
            if normalized_cwd == "."
            else project_root / normalized_cwd
        )
    if validate_text(
        f"{prefix}: command",
        job["command"],
        errors,
    ):
        valid_fields.add("command")
    if (
        not isinstance(job["timeout_minutes"], int)
        or isinstance(job["timeout_minutes"], bool)
        or not 1 <= job["timeout_minutes"] <= MAX_TIMEOUT_MINUTES
    ):
        errors.append(
            f"{prefix}: timeout_minutes must be an integer from 1 through "
            f"{MAX_TIMEOUT_MINUTES}"
        )
    else:
        valid_fields.add("timeout_minutes")
    if validate_outputs(prefix, job["outputs"], job["write_scope"], errors):
        valid_fields.add("outputs")
    validate_scheduler_artifacts(
        prefix,
        job,
        errors,
        job_cwd=job_cwd,
        concurrency_valid="concurrency" in valid_fields,
        filesystem_checks=filesystem_checks,
    )
    validate_idempotency(
        prefix,
        job,
        errors,
        enabled_valid="enabled" in valid_fields,
        write_scope_valid="write_scope" in valid_fields,
    )
    validate_state_policy(
        prefix,
        job,
        errors,
        write_scope_valid="write_scope" in valid_fields,
    )

    for key in sorted(set(job) & DESCRIPTIVE_JOB_KEYS):
        validate_text(f"{prefix}: {key}", job[key], errors)
    instruction_sources_valid = validate_source_references(
        prefix,
        "instruction_sources",
        job["instruction_sources"],
        errors,
        project_root=project_root,
        instruction_source=True,
        allow_empty=False,
        filesystem_checks=filesystem_checks,
    )
    if instruction_sources_valid:
        valid_fields.add("instruction_sources")
    execution_sources_valid = validate_source_references(
        prefix,
        "execution_sources",
        job["execution_sources"],
        errors,
        project_root=project_root,
        instruction_source=False,
        allow_empty=True,
        filesystem_checks=filesystem_checks,
    )
    if execution_sources_valid:
        valid_fields.add("execution_sources")
    if instruction_sources_valid and execution_sources_valid:
        validate_combined_source_budget(
            prefix,
            job,
            errors,
            project_root=project_root,
            filesystem_checks=filesystem_checks,
        )
    return frozenset(valid_fields)


def _validate_job_context_mode(
    job: dict[str, object],
    prefix: str,
    errors: list[str],
    *,
    valid_fields: frozenset[str],
) -> None:
    if (
        "scheduler_context_mode" in valid_fields
        and job["scheduler_context_mode"] == "thread_continuity"
    ):
        raw_policy = job.get("state_policy")
        policy = cast(dict[str, object], raw_policy) if isinstance(raw_policy, dict) else {}
        if (
            policy.get("persistence") == "none"
            and policy.get("checkpoint") == "none"
            and policy.get("resume") == "restart"
        ):
            errors.append(
                f"{prefix}: thread_continuity requires persistent state, a checkpoint, "
                "or cursor resume"
            )


def _validate_job_special_boundaries(
    job: dict[str, object],
    prefix: str,
    errors: list[str],
    *,
    effective_date: date,
    valid_fields: frozenset[str],
) -> None:
    reviewer_runtime_present = "reviewer_runtime_class" in job
    reviewer_boundary_present = "reviewer_boundary_mode" in job
    if reviewer_runtime_present:
        validate_choice(
            f"{prefix}: reviewer_runtime_class",
            job["reviewer_runtime_class"],
            REVIEWER_RUNTIME_CLASSES,
            errors,
        )
    reviewer_boundary_valid = False
    if reviewer_boundary_present:
        reviewer_boundary_valid = validate_choice(
            f"{prefix}: reviewer_boundary_mode",
            job["reviewer_boundary_mode"],
            REVIEWER_BOUNDARY_MODES,
            errors,
        )
    if reviewer_runtime_present != reviewer_boundary_present:
        errors.append(
            f"{prefix}: reviewer jobs must define reviewer_runtime_class and "
            "reviewer_boundary_mode together"
        )

    external_review_present = "external_review" in job
    if reviewer_boundary_valid and requires_external_reviewer_boundary(job):
        if not external_review_present:
            errors.append(
                f"{prefix}: external reviewer jobs must define external_review"
            )
        else:
            validate_external_review(prefix, job["external_review"], errors)
    elif reviewer_boundary_valid and external_review_present:
        errors.append(
            f"{prefix}: external_review is valid only when reviewer_boundary_mode is external"
        )
    elif external_review_present and not reviewer_boundary_present:
        errors.append(
            f"{prefix}: external_review requires reviewer_boundary_mode"
        )

    source_access_present = "source_access_class" in job
    source_policy_present = "source_policy" in job
    source_access_valid = False
    if source_access_present:
        source_access_valid = validate_choice(
            f"{prefix}: source_access_class",
            job["source_access_class"],
            SOURCE_ACCESS_CLASSES,
            errors,
        )
    elif source_policy_present:
        errors.append(
            f"{prefix}: source_policy requires source_access_class"
        )

    if source_access_valid and (
        job.get("source_access_class") == "public_unauthenticated"
        and source_policy_present
    ):
        errors.append(
            f"{prefix}: public_unauthenticated source access must not declare "
            "source_policy"
        )
    elif source_access_valid and requires_sensitive_source_boundary(job):
        if not source_policy_present:
            errors.append(
                f"{prefix}: non-public source access must define source_policy"
            )
        else:
            validate_source_policy(
                prefix,
                job["source_policy"],
                errors,
                effective_date=effective_date,
            )

    parser_change_present = "parser_change" in job
    if (
        "workload_class" in valid_fields
        and job.get("workload_class") == "parser_or_extractor_change"
    ):
        if not parser_change_present:
            errors.append(
                f"{prefix}: parser_or_extractor_change workload must define parser_change"
            )
        else:
            validate_parser_change(prefix, job["parser_change"], errors)
    elif "workload_class" in valid_fields and parser_change_present:
        errors.append(
            f"{prefix}: parser_change is valid only for workload_class "
            "parser_or_extractor_change"
        )


def _validate_job_authority(
    job: dict[str, object],
    prefix: str,
    errors: list[str],
    *,
    effective_date: date,
    valid_fields: frozenset[str],
) -> None:
    level = (
        job["autonomy_level"]
        if "autonomy_level" in valid_fields
        and isinstance(job["autonomy_level"], str)
        else None
    )
    scope = (
        job["write_scope"]
        if "write_scope" in valid_fields and isinstance(job["write_scope"], str)
        else None
    )
    if level == "observe" and scope is not None and scope not in {"none", "artifacts"}:
        errors.append(f"{prefix}: observe jobs may only use write_scope none or artifacts")
    if level == "propose" and scope is not None and scope not in {"artifacts", "repo"}:
        errors.append(f"{prefix}: propose jobs may only use write_scope artifacts or repo")
    if (
        "enabled" in valid_fields
        and job["enabled"] is True
        and level == "propose"
        and scope == "repo"
        and "concurrency" in valid_fields
        and job["concurrency"] != "forbid"
    ):
        errors.append(f"{prefix}: enabled state-changing propose jobs must use concurrency forbid")
    if level == "act":
        if scope is not None and scope not in {"repo", "external"}:
            errors.append(f"{prefix}: act jobs must use write_scope repo or external")
        if (
            "approval_mode" in valid_fields
            and job["approval_mode"] != "standing_order"
        ):
            errors.append(f"{prefix}: act jobs require approval_mode standing_order")
        if "concurrency" in valid_fields and job["concurrency"] != "forbid":
            errors.append(f"{prefix}: act jobs must use concurrency forbid")

    authority_present = "authority" in job
    authority_required = (
        ("enabled" in valid_fields and job["enabled"] is True)
        or level == "act"
        or (
            "approval_mode" in valid_fields
            and job["approval_mode"] == "standing_order"
        )
    )
    if authority_required:
        if not authority_present:
            errors.append(f"{prefix}: authority-bearing jobs must define authority")
        else:
            validate_authority(
                prefix,
                job,
                errors,
                effective_date=effective_date,
                valid_fields=valid_fields,
            )
    elif authority_present:
        validate_authority(
            prefix,
            job,
            errors,
            effective_date=effective_date,
            valid_fields=valid_fields,
        )

    if scope == "external" and level is not None and level != "act":
        errors.append(f"{prefix}: external write_scope requires act autonomy")


def _validate_job_trace_and_target(
    job: dict[str, object],
    prefix: str,
    *,
    target: str | None,
    errors: list[str],
    valid_fields: frozenset[str],
) -> None:
    if (
        "enabled" in valid_fields
        and "outputs" in valid_fields
        and job["enabled"] is True
        and not job["outputs"]
    ):
        raw_state_policy = job.get("state_policy")
        state_policy = (
            cast(dict[str, object], raw_state_policy)
            if isinstance(raw_state_policy, dict)
            else {}
        )
        durable_trace = (
            state_policy.get("persistence") != "none"
            or state_policy.get("checkpoint") != "none"
        )
        if not durable_trace:
            errors.append(
                f"{prefix}: enabled recurring jobs must declare outputs or persistent state/checkpoint"
            )
    if (
        target == "cron"
        and "enabled" in valid_fields
        and "approval_mode" in valid_fields
        and job["enabled"] is True
        and job["approval_mode"] != "standing_order"
    ):
        errors.append(
            f"{prefix}: target cron requires enabled jobs to use approval_mode "
            "standing_order because the runtime has no per-run approval gate"
        )
    if (
        target == "cron"
        and "enabled" in valid_fields
        and "concurrency" in valid_fields
        and job["enabled"] is True
        and job["concurrency"] != "forbid"
    ):
        errors.append(
            f"{prefix}: target cron requires enabled jobs to use concurrency "
            "forbid because this backend does not isolate concurrent command effects"
        )
    if (
        target == "cron"
        and "enabled" in valid_fields
        and "failure_policy" in valid_fields
        and job["enabled"] is True
        and job["failure_policy"] not in CRON_FAILURE_POLICIES
    ):
        errors.append(
            f"{prefix}: target cron supports failure_policy {sorted(CRON_FAILURE_POLICIES)}"
        )
    if target == "cron":
        artifacts = job.get("scheduler_artifacts")
        retention = (
            artifacts.get("retention") if isinstance(artifacts, dict) else None
        )
        retention_mode = (
            retention.get("mode") if isinstance(retention, dict) else None
        )
        if (
            isinstance(retention_mode, str)
            and retention_mode in RETENTION_MODES
            and retention_mode not in CRON_SUPPORTED_RETENTION_MODES
        ):
            errors.append(
                f"{prefix}: target cron does not execute "
                f"scheduler_artifacts.retention.mode {retention_mode!r}; use one of "
                f"{sorted(CRON_SUPPORTED_RETENTION_MODES)}"
            )


def _validate_job(
    job: dict[str, object],
    seen_ids: set[str],
    errors: list[str],
    *,
    effective_date: date,
    target: str | None,
    project_root: Path,
    require_existing_project_root: bool,
    filesystem_checks: bool,
) -> None:
    raw_job_id = job.get("id", "<missing-id>")
    diagnostic_job_id = raw_job_id
    if isinstance(raw_job_id, str) and (
        has_control(raw_job_id)
        or generated_sow_text.generated_sow_control_syntax_kind(raw_job_id)
        is not None
    ):
        diagnostic_job_id = "<invalid-id>"
    prefix = f"job {diagnostic_job_id}"
    for key in sorted(set(job) - JOB_KEYS):
        errors.append(f"{prefix}: unknown key {key}")
    missing = sorted(REQUIRED_JOB_KEYS - set(job))
    if missing:
        errors.append(f"{prefix}: missing keys {missing}")
        return
    valid_fields = _validate_job_core(
        job,
        prefix,
        seen_ids,
        errors,
        project_root=project_root,
        require_existing_cwd=(
            target == "cron" and require_existing_project_root
        ),
        filesystem_checks=filesystem_checks,
    )
    _validate_job_context_mode(
        job,
        prefix,
        errors,
        valid_fields=valid_fields,
    )
    _validate_job_special_boundaries(
        job,
        prefix,
        errors,
        effective_date=effective_date,
        valid_fields=valid_fields,
    )
    _validate_job_authority(
        job,
        prefix,
        errors,
        effective_date=effective_date,
        valid_fields=valid_fields,
    )
    _validate_job_trace_and_target(
        job,
        prefix,
        target=target,
        errors=errors,
        valid_fields=valid_fields,
    )


def _validate_manifest(
    data: object,
    target: str | None = None,
    *,
    effective_date: date,
    project_root: Path | None = None,
    manifest_path: Path | None = None,
    require_existing_project_root: bool = True,
    filesystem_checks: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if target is not None and target not in TARGETS:
        return [f"target must be one of {sorted(TARGETS)}"], warnings

    selected_root: Path | None = None
    if project_root is not None:
        try:
            if filesystem_checks:
                selected_root = normalize_project_root(
                    project_root,
                    require_existing=require_existing_project_root,
                )
            else:
                selected_root = _normalize_project_root_lexical(
                    project_root,
                    description="selected project root",
                )
            if target == "cron" and "%" in os.fspath(selected_root):
                errors.append(
                    "target cron requires a selected project root without '%'"
                )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    elif target == "cron":
        errors.append("target cron requires an explicit selected project root")

    if manifest_path is not None and selected_root is not None:
        try:
            if filesystem_checks:
                manifest_relative_to_project(
                    selected_root,
                    manifest_path,
                    require_existing=require_existing_project_root,
                )
            else:
                _manifest_relative_to_project_lexical(
                    selected_root,
                    manifest_path,
                )
            if target == "cron" and "%" in os.fspath(manifest_path):
                errors.append(
                    "target cron requires an automation manifest path without '%'"
                )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    elif target == "cron" and manifest_path is None:
        errors.append("target cron requires an explicit automation manifest path")

    validation_root = selected_root if selected_root is not None else REPO_ROOT

    if not isinstance(data, dict):
        errors.append("manifest must be a JSON object")
        return errors, warnings

    for key in sorted(set(data) - TOP_LEVEL_KEYS):
        errors.append(f"unknown top-level key: {key}")
    missing_top_level = sorted(REQUIRED_TOP_LEVEL_KEYS - set(data))
    if missing_top_level:
        errors.append(f"manifest is missing top-level keys {missing_top_level}")

    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    elif schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    generated_state_origin = data.get(project_state_identity.JSON_STATE_ORIGIN_KEY)
    if (
        generated_state_origin is not None
        and generated_state_origin != project_state_identity.JSON_STATE_ORIGIN_VALUE
    ):
        errors.append(
            f"{project_state_identity.JSON_STATE_ORIGIN_KEY} must be "
            f"{project_state_identity.JSON_STATE_ORIGIN_VALUE!r} when present"
        )

    preferred_backend = data.get("preferred_backend")
    if (
        not isinstance(preferred_backend, str)
        or has_control(preferred_backend)
        or BACKEND_RE.fullmatch(preferred_backend) is None
    ):
        errors.append(
            "preferred_backend must be one control-free lowercase slug matching "
            f"{BACKEND_RE.pattern}"
        )
    elif target is not None and preferred_backend != target:
        errors.append(
            f"target {target} requires preferred_backend {target!r}, got "
            f"{preferred_backend!r}"
        )

    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        errors.append("jobs must be a list")
        return errors, warnings
    if not jobs:
        return errors, warnings

    seen_ids: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            errors.append("each job must be an object")
            continue
        _validate_job(
            job,
            seen_ids,
            errors,
            effective_date=effective_date,
            target=target,
            project_root=validation_root,
            require_existing_project_root=require_existing_project_root,
            filesystem_checks=filesystem_checks,
        )
    validate_scheduler_artifact_topology(jobs, errors)
    return errors, warnings


def validate_manifest(
    data: object,
    target: str | None = None,
    *,
    project_root: Path | None = None,
    manifest_path: Path | None = None,
    require_existing_project_root: bool = True,
) -> tuple[list[str], list[str]]:
    """Validate semantics plus the currently named filesystem projection.

    The current UTC date is captured exactly once and used for every
    time-sensitive check in this validation run.
    """

    return _validate_manifest(
        data,
        target,
        effective_date=current_utc_date(),
        project_root=project_root,
        manifest_path=manifest_path,
        require_existing_project_root=require_existing_project_root,
        filesystem_checks=True,
    )


def validate_descriptor_bound_manifest(
    data: object,
    target: str,
    *,
    project_root: Path,
    manifest_path: Path,
) -> tuple[list[str], list[str]]:
    """Validate a manifest whose project, file, and cwd are already descriptor-bound.

    This runtime-only entrypoint deliberately performs lexical and semantic
    checks without reacquiring mutable pathnames. Its caller must first open
    the project root, manifest, and selected cwd through no-follow directory
    descriptors and verify their bound identities.
    """

    return _validate_manifest(
        data,
        target,
        effective_date=current_utc_date(),
        project_root=project_root,
        manifest_path=manifest_path,
        require_existing_project_root=True,
        filesystem_checks=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint standing automation orders.",
        allow_abbrev=False,
    )
    parser.add_argument("manifest", help="Path to AUTOMATION_ORDERS.json")
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Absolute selected project root that owns the manifest and all repo-relative job cwd values.",
    )
    parser.add_argument("--target", choices=sorted(TARGETS), help="Optional scheduler-backend compatibility check.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().absolute()
    project_root = args.project_root.expanduser()
    preflight_errors: list[str] = []
    normalized_root: Path | None = None
    try:
        normalized_root = normalize_project_root(project_root)
        manifest_relative_to_project(normalized_root, manifest_path)
    except (OSError, ValueError) as exc:
        preflight_errors.append(str(exc))

    try:
        if preflight_errors:
            raise ValueError("; ".join(preflight_errors))
        if normalized_root is None:
            raise ValueError("selected project root could not be normalized")
        manifest = load_manifest(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors, warnings = [f"manifest input is invalid: {exc}"], []
    else:
        errors, warnings = validate_manifest(
            manifest,
            target=args.target,
            project_root=normalized_root,
            manifest_path=manifest_path,
        )
    print(json.dumps({"errors": errors, "warnings": warnings}, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
