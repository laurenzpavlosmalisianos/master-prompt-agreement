#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import safe_paths


PROJECT_ROOT_PLACEHOLDER = "{PROJECT_ROOT}"
SCHEMA_VERSION = 6

VALID_AUTOMATION_KINDS = {"cron", "operator_trigger", "thread_wakeup"}
VALID_CONTEXT_MODES = {"fresh_run", "thread_continuity"}
VALID_STATUSES = {"ACTIVE", "MANUAL", "PAUSED"}
VALID_AUTONOMY_LEVELS = {"observe", "propose", "act"}
VALID_CADENCE_ROLES = {
    "broad_source_discovery",
    "general",
    "narrow_source_chain",
    "recovery_diagnostic",
}

TOP_LEVEL_FIELDS = {
    "automations",
    "install_notes",
    "operator_trigger_contract",
    "project_root_placeholder",
    "schema_version",
    "timezone",
}
COMMON_ENTRY_FIELDS = {
    "autonomy_level",
    "cadence_role",
    "context_mode",
    "execution_environment",
    "id",
    "instruction_sources",
    "kind",
    "model_route",
    "prompt_lines",
    "status",
    "timezone",
}
CRON_REQUIRED_FIELDS = {"cwd", "rrule"}
CRON_OPTIONAL_FIELDS = {"cadence_note", "discovery_policy"}
OPERATOR_REQUIRED_FIELDS = {"cwd", "trigger_note", "trigger_policy"}
OPERATOR_OPTIONAL_FIELDS = {"chain_stage", "discovery_policy"}
THREAD_WAKEUP_REQUIRED_FIELDS = {"target_thread"}
THREAD_WAKEUP_OPTIONAL_FIELDS = {"cadence_note"}

PORTABLE_TARGET_THREAD_VALUES = {"current_thread_when_installed"}
PORTABLE_TARGET_THREAD_ALIAS_RE = re.compile(
    r"^thread_alias:[a-z0-9][a-z0-9_-]{0,63}$"
)
PORTABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
MODEL_ROUTE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MODEL_SETTING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$")

OPERATOR_TRIGGER_POLICY = "explicit_user_request"
OPERATOR_TRIGGER_PLACEHOLDERS = {
    "logical_date_placeholder": "{LOGICAL_DATE}",
    "run_slot_placeholder": "{RUN_SLOT}",
    "scope_placeholder": "{MONITOR_SCOPE}",
}
OPERATOR_TRIGGER_CONTRACT_FIELDS = {
    "activation",
    "default_model_route",
    "model_routing_reference",
    "source_chain_order",
    "stage_assignments",
    *OPERATOR_TRIGGER_PLACEHOLDERS,
}

SOURCE_CHAIN_STAGES = ("monitor", "review", "apply", "assurance")
SOURCE_CHAIN_STAGE_AUTONOMY = {
    "monitor": "observe",
    "review": "propose",
    "apply": "act",
    "assurance": "observe",
}
SOURCE_CHAIN_ASSIGNMENT_FIELDS = {
    "execution_mode",
    "model_label",
    "reasoning_effort",
}
ASSIGNMENT_SETTING_FIELDS = {"value", "visibility"}
VALID_SETTING_VISIBILITY = {"exposed", "not_exposed"}
RESERVED_EXPOSED_ASSIGNMENT_VALUES = {"not_exposed"}

EXECUTION_ENVIRONMENT_FIELDS = {
    "boundary_mode",
    "environment_ref",
    "runtime_class",
}
VALID_RUNTIME_CLASSES = {"agent_app", "cli", "deterministic_tool", "human"}
VALID_BOUNDARY_MODES = {"external", "local"}

DISCOVERY_POLICY_FIELDS = {
    "digest_validator",
    "launch_mode",
    "primary_source_verification",
    "result_authority",
}
DISCOVERY_POLICY_VALUES = {
    "digest_validator": "scripts/source_deep_research_lint.py",
    "launch_mode": "operator_supervised",
    "primary_source_verification": "required",
    "result_authority": "candidate_only",
}

RRULE_KEYS = {
    "BYDAY",
    "BYHOUR",
    "BYMINUTE",
    "BYMONTH",
    "BYMONTHDAY",
    "BYSECOND",
    "BYSETPOS",
    "BYWEEKNO",
    "BYYEARDAY",
    "COUNT",
    "FREQ",
    "INTERVAL",
    "UNTIL",
    "WKST",
}
RRULE_FREQUENCIES = {
    "DAILY",
    "HOURLY",
    "MINUTELY",
    "MONTHLY",
    "SECONDLY",
    "WEEKLY",
    "YEARLY",
}
RRULE_PART_RE = re.compile(r"^([A-Z]+)=([A-Z0-9,+-]+)$")
RRULE_WEEKDAY_RE = re.compile(r"^(?:(-?\d{1,2}))?(MO|TU|WE|TH|FR|SA|SU)$")
RRULE_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
RRULE_NUMERIC_RANGES = {
    "BYHOUR": (0, 23, False),
    "BYMINUTE": (0, 59, False),
    "BYMONTH": (1, 12, False),
    "BYMONTHDAY": (-31, 31, True),
    "BYSECOND": (0, 60, False),
    "BYSETPOS": (-366, 366, True),
    "BYWEEKNO": (-53, 53, True),
    "BYYEARDAY": (-366, 366, True),
}
PROMPT_PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")
PROJECT_ROOT_PROMPT_PLACEHOLDER = "PROJECT_ROOT"
OPERATOR_COMMON_PROMPT_PLACEHOLDERS = {
    "LOGICAL_DATE",
    "MONITOR_SCOPE",
    PROJECT_ROOT_PROMPT_PLACEHOLDER,
}
NARROW_OPERATOR_PROMPT_PLACEHOLDERS = {
    *OPERATOR_COMMON_PROMPT_PLACEHOLDERS,
    "RUN_SLOT",
}


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def normalize_display_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def has_host_path(value: str) -> bool:
    return safe_paths.contains_local_absolute_path(value)


def is_portable_target_thread(value: str) -> bool:
    return value in PORTABLE_TARGET_THREAD_VALUES or bool(
        PORTABLE_TARGET_THREAD_ALIAS_RE.fullmatch(value)
    )


def registry_root(path: Path) -> Path:
    for candidate in path.parents:
        if (candidate / "AGENTS.md").is_file() and (
            candidate / "runtime" / "operative_charter.md"
        ).is_file():
            return candidate
    return path.parent


def validate_closed_object(
    value: object,
    *,
    description: str,
    expected_fields: set[str],
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{description} must be an object")
        return None
    observed = set(value)
    missing = sorted(expected_fields - observed)
    unknown = sorted(observed - expected_fields)
    if missing:
        errors.append(f"{description} is missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{description} has unknown fields: {', '.join(unknown)}")
    return value


def validate_timezone(
    value: object,
    *,
    description: str,
    errors: list[str],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{description} must be a valid normalized IANA timezone name")
        return None
    if Path(value).is_absolute() or ".." in Path(value).parts:
        errors.append(
            f"{description} must be a normalized IANA timezone name, not an absolute or traversal path"
        )
        return None
    if value != "UTC" and "/" not in value:
        errors.append(
            f"{description} must be a normalized IANA timezone name, not an abbreviation or alias"
        )
        return None
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        errors.append(f"{description} must be a valid normalized IANA timezone name")
        return None
    return value


def instruction_source_error(value: str, root: Path, *, description: str) -> str | None:
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            value,
            root,
            description=description,
        )
    except ValueError as exc:
        return str(exc)
    candidate = root / normalized
    if not candidate.is_file() or candidate.is_symlink():
        return (
            f"{description} file does not exist as a regular non-symlink file: "
            f"{normalized}"
        )
    return None


def validate_instruction_sources(
    entry: dict[str, Any],
    prefix: str,
    root: Path,
    errors: list[str],
) -> None:
    raw_sources = entry.get("instruction_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        errors.append(
            f"{prefix}: instruction_sources must be a non-empty list of repo-relative files"
        )
        return

    declared: set[str] = set()
    for index, source in enumerate(raw_sources):
        description = f"{prefix} instruction_sources[{index}]"
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{description} must be a non-empty string")
            continue
        if source in declared:
            errors.append(
                f"{description} duplicates an earlier instruction source: {source}"
            )
            continue
        declared.add(source)
        error = instruction_source_error(source, root, description=description)
        if error:
            errors.append(error)


def validate_text_lines(
    value: object,
    *,
    description: str,
    errors: list[str],
) -> str:
    if not isinstance(value, list) or not value:
        errors.append(f"{description} must be a non-empty list of non-empty strings")
        return ""
    lines: list[str] = []
    for index, line in enumerate(value):
        line_description = f"{description}[{index}]"
        if not isinstance(line, str) or not line.strip():
            errors.append(f"{line_description} must be a non-empty string")
            continue
        if "\n" in line or "\r" in line:
            errors.append(f"{line_description} must contain exactly one text line")
        if has_control_characters(line):
            errors.append(f"{line_description} must not contain control characters")
        lines.append(line)
    return "\n".join(lines)


def validate_prompt_placeholders(
    prompt: str,
    *,
    prefix: str,
    allowed: set[str],
    required: set[str],
    errors: list[str],
) -> None:
    observed = set(PROMPT_PLACEHOLDER_RE.findall(prompt))
    remainder = PROMPT_PLACEHOLDER_RE.sub("", prompt)
    if "{" in remainder or "}" in remainder:
        errors.append(f"{prefix}: prompt_lines contain malformed placeholder syntax")
    unknown = sorted(observed - allowed)
    missing = sorted(required - observed)
    if unknown:
        errors.append(
            f"{prefix}: prompt_lines contain unsupported placeholders: "
            + ", ".join(unknown)
        )
    if missing:
        errors.append(
            f"{prefix}: prompt_lines are missing required placeholders: "
            + ", ".join(missing)
        )


def validate_optional_note(
    entry: dict[str, Any],
    field_name: str,
    prefix: str,
    errors: list[str],
) -> None:
    if field_name not in entry:
        return
    value = entry[field_name]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}: {field_name} must be a non-empty string when present")
    elif has_control_characters(value):
        errors.append(f"{prefix}: {field_name} must not contain control characters")


def iter_string_values(value: object, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        items: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            items.extend(iter_string_values(item, f"{path}[{index}]"))
        return items
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            items.extend(iter_string_values(item, f"{path}.{key}"))
        return items
    return []


def validate_execution_environment(
    value: object,
    *,
    prefix: str,
    errors: list[str],
) -> None:
    environment = validate_closed_object(
        value,
        description=f"{prefix}: execution_environment",
        expected_fields=EXECUTION_ENVIRONMENT_FIELDS,
        errors=errors,
    )
    if environment is None:
        return
    if environment.get("runtime_class") not in VALID_RUNTIME_CLASSES:
        errors.append(
            f"{prefix}: execution_environment.runtime_class must be one of "
            f"{sorted(VALID_RUNTIME_CLASSES)}"
        )
    if environment.get("boundary_mode") not in VALID_BOUNDARY_MODES:
        errors.append(
            f"{prefix}: execution_environment.boundary_mode must be local or external"
        )
    environment_ref = environment.get("environment_ref")
    if not isinstance(environment_ref, str) or not PORTABLE_ID_RE.fullmatch(
        environment_ref
    ):
        errors.append(
            f"{prefix}: execution_environment.environment_ref must be a portable id"
        )


def validate_assignment_setting(
    value: object,
    *,
    description: str,
    require_exposed: bool,
    display_text: bool,
    errors: list[str],
) -> None:
    setting = validate_closed_object(
        value,
        description=description,
        expected_fields=ASSIGNMENT_SETTING_FIELDS,
        errors=errors,
    )
    if setting is None:
        return
    visibility = setting.get("visibility")
    if visibility not in VALID_SETTING_VISIBILITY:
        errors.append(
            f"{description}.visibility must be exposed or not_exposed"
        )
        return
    if require_exposed and visibility != "exposed":
        errors.append(f"{description}.visibility must be exposed")
    raw_value = setting.get("value")
    if visibility == "not_exposed":
        if raw_value is not None:
            errors.append(f"{description}.value must be null when visibility is not_exposed")
        return
    if not isinstance(raw_value, str) or not raw_value:
        errors.append(f"{description}.value must be a non-empty string when exposed")
        return
    if raw_value.casefold() in RESERVED_EXPOSED_ASSIGNMENT_VALUES:
        errors.append(
            f"{description}.value must not use the reserved token not_exposed "
            "when visibility is exposed"
        )
        return
    if display_text:
        if raw_value != normalize_display_text(raw_value):
            errors.append(
                f"{description}.value must use canonical NFKC text with collapsed whitespace"
            )
        if len(raw_value.encode("utf-8")) > 256:
            errors.append(f"{description}.value must be at most 256 UTF-8 bytes")
        if has_control_characters(raw_value):
            errors.append(f"{description}.value must not contain control characters")
    elif not MODEL_SETTING_RE.fullmatch(raw_value):
        errors.append(f"{description}.value must be a portable setting token")


def validate_source_chain_stage_assignments(
    value: object,
    errors: list[str],
) -> None:
    prefix = "operator_trigger_contract.stage_assignments"
    assignments = validate_closed_object(
        value,
        description=prefix,
        expected_fields=set(SOURCE_CHAIN_STAGES),
        errors=errors,
    )
    if assignments is None:
        return
    for stage in SOURCE_CHAIN_STAGES:
        stage_prefix = f"{prefix}.{stage}"
        assignment = validate_closed_object(
            assignments.get(stage),
            description=stage_prefix,
            expected_fields=SOURCE_CHAIN_ASSIGNMENT_FIELDS,
            errors=errors,
        )
        if assignment is None:
            continue
        validate_assignment_setting(
            assignment.get("model_label"),
            description=f"{stage_prefix}.model_label",
            require_exposed=True,
            display_text=True,
            errors=errors,
        )
        for field_name in ("reasoning_effort", "execution_mode"):
            validate_assignment_setting(
                assignment.get(field_name),
                description=f"{stage_prefix}.{field_name}",
                require_exposed=False,
                display_text=False,
                errors=errors,
            )


def _validate_rrule_number_list(
    key: str,
    value: str,
    *,
    prefix: str,
    errors: list[str],
) -> None:
    minimum, maximum, excludes_zero = RRULE_NUMERIC_RANGES[key]
    for item in value.split(","):
        try:
            number = int(item)
        except ValueError:
            errors.append(f"{prefix}: RRULE {key} values must be integers")
            return
        if number < minimum or number > maximum or (excludes_zero and number == 0):
            errors.append(
                f"{prefix}: RRULE {key} value {number} is outside its allowed range"
            )


def parse_rrule_frequency(
    value: object,
    *,
    prefix: str,
    errors: list[str],
) -> str | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{prefix}: cron automation must define an RRULE")
        return None
    parts: dict[str, str] = {}
    for raw_part in value.split(";"):
        match = RRULE_PART_RE.fullmatch(raw_part)
        if match is None:
            errors.append(f"{prefix}: rrule must use canonical RRULE key=value syntax")
            return None
        key, part_value = match.groups()
        if key not in RRULE_KEYS:
            errors.append(f"{prefix}: rrule has unsupported key {key}")
            continue
        if key in parts:
            errors.append(f"{prefix}: rrule repeats key {key}")
            continue
        parts[key] = part_value
    frequency = parts.get("FREQ")
    if frequency not in RRULE_FREQUENCIES:
        errors.append(f"{prefix}: rrule FREQ must be one of {sorted(RRULE_FREQUENCIES)}")
        frequency = None
    for key in ("COUNT", "INTERVAL"):
        if key not in parts:
            continue
        try:
            number = int(parts[key])
        except ValueError:
            errors.append(f"{prefix}: RRULE {key} must be a positive integer")
        else:
            if number <= 0:
                errors.append(f"{prefix}: RRULE {key} must be a positive integer")
    if "COUNT" in parts and "UNTIL" in parts:
        errors.append(f"{prefix}: rrule must not define both COUNT and UNTIL")
    if "UNTIL" in parts:
        until = parts["UNTIL"]
        formats = ("%Y%m%d", "%Y%m%dT%H%M%SZ")
        if not any(_is_datetime(until, date_format) for date_format in formats):
            errors.append(
                f"{prefix}: RRULE UNTIL must be a valid YYYYMMDD or YYYYMMDDTHHMMSSZ value"
            )
    for key in RRULE_NUMERIC_RANGES:
        if key in parts:
            _validate_rrule_number_list(
                key,
                parts[key],
                prefix=prefix,
                errors=errors,
            )
    if "BYDAY" in parts:
        for item in parts["BYDAY"].split(","):
            match = RRULE_WEEKDAY_RE.fullmatch(item)
            if match is None:
                errors.append(f"{prefix}: RRULE BYDAY contains an invalid value: {item}")
                continue
            ordinal = match.group(1)
            if ordinal is not None and (int(ordinal) == 0 or abs(int(ordinal)) > 53):
                errors.append(
                    f"{prefix}: RRULE BYDAY ordinal is outside -53..-1 or 1..53: {item}"
                )
    if "WKST" in parts and parts["WKST"] not in RRULE_WEEKDAYS:
        errors.append(f"{prefix}: RRULE WKST must be a weekday token")
    return frequency


def _is_datetime(value: str, date_format: str) -> bool:
    try:
        datetime.strptime(value, date_format)
    except ValueError:
        return False
    return True


def validate_discovery_policy(
    value: object,
    *,
    prefix: str,
    root: Path,
    errors: list[str],
) -> None:
    policy = validate_closed_object(
        value,
        description=f"{prefix}: discovery_policy",
        expected_fields=DISCOVERY_POLICY_FIELDS,
        errors=errors,
    )
    if policy is None:
        return
    for field_name, expected in DISCOVERY_POLICY_VALUES.items():
        if policy.get(field_name) != expected:
            errors.append(
                f"{prefix}: discovery_policy.{field_name} must be {expected}"
            )
    digest_validator = policy.get("digest_validator")
    if isinstance(digest_validator, str):
        error = instruction_source_error(
            digest_validator,
            root,
            description=f"{prefix}: discovery_policy.digest_validator",
        )
        if error:
            errors.append(error)


@dataclass(frozen=True, slots=True)
class _RegistryEntryContext:
    entry: dict[str, Any]
    automation_id: str
    kind: Any
    status: Any
    context_mode: Any
    autonomy_level: Any
    cadence_role: Any
    prompt: str
    rrule_frequency: str | None = None


def _entry_fields(kind: object) -> tuple[set[str], set[str]]:
    if kind == "cron":
        return (
            COMMON_ENTRY_FIELDS | CRON_REQUIRED_FIELDS,
            COMMON_ENTRY_FIELDS | CRON_REQUIRED_FIELDS | CRON_OPTIONAL_FIELDS,
        )
    if kind == "operator_trigger":
        return (
            COMMON_ENTRY_FIELDS | OPERATOR_REQUIRED_FIELDS,
            COMMON_ENTRY_FIELDS | OPERATOR_REQUIRED_FIELDS | OPERATOR_OPTIONAL_FIELDS,
        )
    if kind == "thread_wakeup":
        return (
            COMMON_ENTRY_FIELDS | THREAD_WAKEUP_REQUIRED_FIELDS,
            COMMON_ENTRY_FIELDS
            | THREAD_WAKEUP_REQUIRED_FIELDS
            | THREAD_WAKEUP_OPTIONAL_FIELDS,
        )
    return COMMON_ENTRY_FIELDS, COMMON_ENTRY_FIELDS


def _validate_common_entry(
    raw_entry: dict[str, Any],
    index: int,
    *,
    registry_timezone: str | None,
    repo_root: Path,
    seen_ids: set[str],
    entries_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> _RegistryEntryContext:
    item_prefix = f"automations[{index}]"
    kind = raw_entry.get("kind")
    required_fields, allowed_fields = _entry_fields(kind)
    missing_fields = sorted(required_fields - set(raw_entry))
    unknown_fields = sorted(set(raw_entry) - allowed_fields)
    if missing_fields:
        errors.append(f"{item_prefix} is missing fields: {', '.join(missing_fields)}")
    if unknown_fields:
        errors.append(f"{item_prefix} has unknown fields: {', '.join(unknown_fields)}")

    automation_id = raw_entry.get("id")
    if not isinstance(automation_id, str) or not PORTABLE_ID_RE.fullmatch(automation_id):
        errors.append(f"{item_prefix}: id must be a portable lowercase id")
        automation_id = f"<missing-{index}>"
    if automation_id in seen_ids:
        errors.append(f"{item_prefix}: duplicate id {automation_id}")
    seen_ids.add(automation_id)
    entries_by_id[automation_id] = raw_entry
    prefix = automation_id

    if kind not in VALID_AUTOMATION_KINDS:
        errors.append(f"{prefix}: kind must be one of {sorted(VALID_AUTOMATION_KINDS)}")
    status = raw_entry.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"{prefix}: status must be ACTIVE, MANUAL, or PAUSED")
    context_mode = raw_entry.get("context_mode")
    if context_mode not in VALID_CONTEXT_MODES:
        errors.append(f"{prefix}: context_mode must be fresh_run or thread_continuity")
    autonomy_level = raw_entry.get("autonomy_level")
    if autonomy_level not in VALID_AUTONOMY_LEVELS:
        errors.append(f"{prefix}: autonomy_level must be observe, propose, or act")
    cadence_role = raw_entry.get("cadence_role")
    if cadence_role not in VALID_CADENCE_ROLES:
        errors.append(f"{prefix}: cadence_role must be one of {sorted(VALID_CADENCE_ROLES)}")
    model_route = raw_entry.get("model_route")
    if not isinstance(model_route, str) or not MODEL_ROUTE_RE.fullmatch(model_route):
        errors.append(f"{prefix}: model_route must be a portable route id")

    entry_timezone = validate_timezone(
        raw_entry.get("timezone"),
        description=f"{prefix}: timezone",
        errors=errors,
    )
    if (
        registry_timezone is not None
        and entry_timezone is not None
        and entry_timezone != registry_timezone
    ):
        errors.append(f"{prefix}: timezone must match registry timezone {registry_timezone}")

    prompt = validate_text_lines(
        raw_entry.get("prompt_lines"),
        description=f"{prefix}: prompt_lines",
        errors=errors,
    )
    validate_instruction_sources(raw_entry, prefix, repo_root, errors)
    validate_execution_environment(
        raw_entry.get("execution_environment"),
        prefix=prefix,
        errors=errors,
    )
    validate_optional_note(raw_entry, "cadence_note", prefix, errors)
    validate_optional_note(raw_entry, "trigger_note", prefix, errors)

    if cadence_role == "broad_source_discovery":
        if kind == "thread_wakeup":
            errors.append(f"{prefix}: broad_source_discovery cannot use kind thread_wakeup")
        if autonomy_level != "observe":
            errors.append(f"{prefix}: broad_source_discovery must stay observe-only")
        validate_discovery_policy(
            raw_entry.get("discovery_policy"),
            prefix=prefix,
            root=repo_root,
            errors=errors,
        )
    elif "discovery_policy" in raw_entry:
        errors.append(
            f"{prefix}: discovery_policy is allowed only for cadence_role broad_source_discovery"
        )

    if cadence_role == "recovery_diagnostic" and kind != "thread_wakeup":
        errors.append(f"{prefix}: recovery_diagnostic must use kind thread_wakeup")
    if kind == "thread_wakeup" and cadence_role != "recovery_diagnostic":
        errors.append(
            f"{prefix}: thread_wakeup automation must use cadence_role recovery_diagnostic"
        )

    return _RegistryEntryContext(
        entry=raw_entry,
        automation_id=automation_id,
        kind=kind,
        status=status,
        context_mode=context_mode,
        autonomy_level=autonomy_level,
        cadence_role=cadence_role,
        prompt=prompt,
    )


def _validate_cron_entry(
    context: _RegistryEntryContext,
    errors: list[str],
) -> _RegistryEntryContext:
    entry = context.entry
    prefix = context.automation_id
    if context.status == "MANUAL":
        errors.append(f"{prefix}: cron automation status must be ACTIVE or PAUSED")
    frequency = parse_rrule_frequency(entry.get("rrule"), prefix=prefix, errors=errors)
    if entry.get("cwd") != PROJECT_ROOT_PLACEHOLDER:
        errors.append(f"{prefix}: cron automation cwd must be {PROJECT_ROOT_PLACEHOLDER}")
    if context.context_mode != "fresh_run":
        errors.append(f"{prefix}: cron automation must use fresh_run")
    validate_prompt_placeholders(
        context.prompt,
        prefix=prefix,
        allowed={PROJECT_ROOT_PROMPT_PLACEHOLDER},
        required=set(),
        errors=errors,
    )
    if context.cadence_role == "broad_source_discovery" and frequency not in {
        "MONTHLY",
        "YEARLY",
    }:
        errors.append(
            f"{prefix}: broad_source_discovery cron RRULE must be MONTHLY or YEARLY"
        )
    return _RegistryEntryContext(
        entry=context.entry,
        automation_id=context.automation_id,
        kind=context.kind,
        status=context.status,
        context_mode=context.context_mode,
        autonomy_level=context.autonomy_level,
        cadence_role=context.cadence_role,
        prompt=context.prompt,
        rrule_frequency=frequency,
    )


def _validate_operator_entry(
    context: _RegistryEntryContext,
    errors: list[str],
) -> None:
    entry = context.entry
    prefix = context.automation_id
    if context.status != "MANUAL":
        errors.append(f"{prefix}: operator_trigger automation must use status MANUAL")
    if context.context_mode != "fresh_run":
        errors.append(f"{prefix}: operator_trigger automation must use fresh_run")
    if entry.get("trigger_policy") != OPERATOR_TRIGGER_POLICY:
        errors.append(
            f"{prefix}: operator_trigger trigger_policy must be {OPERATOR_TRIGGER_POLICY}"
        )
    if entry.get("cwd") != PROJECT_ROOT_PLACEHOLDER:
        errors.append(
            f"{prefix}: operator_trigger automation cwd must be {PROJECT_ROOT_PLACEHOLDER}"
        )
    if context.cadence_role == "narrow_source_chain":
        validate_prompt_placeholders(
            context.prompt,
            prefix=prefix,
            allowed=NARROW_OPERATOR_PROMPT_PLACEHOLDERS,
            required=NARROW_OPERATOR_PROMPT_PLACEHOLDERS,
            errors=errors,
        )
        chain_stage = entry.get("chain_stage")
        if chain_stage not in SOURCE_CHAIN_STAGES:
            errors.append(
                f"{prefix}: narrow source-chain operator chain_stage must be one of "
                f"{list(SOURCE_CHAIN_STAGES)}"
            )
            return
        expected_autonomy = SOURCE_CHAIN_STAGE_AUTONOMY[str(chain_stage)]
        if context.autonomy_level != expected_autonomy:
            errors.append(
                f"{prefix}: {chain_stage} operator trigger autonomy_level must be "
                f"{expected_autonomy}"
            )
    else:
        required_placeholders = (
            OPERATOR_COMMON_PROMPT_PLACEHOLDERS
            if context.cadence_role == "broad_source_discovery"
            else {PROJECT_ROOT_PROMPT_PLACEHOLDER}
        )
        validate_prompt_placeholders(
            context.prompt,
            prefix=prefix,
            allowed=required_placeholders,
            required=required_placeholders,
            errors=errors,
        )
        if "chain_stage" in entry:
            errors.append(
                f"{prefix}: chain_stage is allowed only for cadence_role narrow_source_chain"
            )


def _validate_thread_wakeup_entry(
    context: _RegistryEntryContext,
    errors: list[str],
) -> None:
    entry = context.entry
    prefix = context.automation_id
    target_thread = entry.get("target_thread")
    if not isinstance(target_thread, str) or not is_portable_target_thread(target_thread):
        errors.append(
            f"{prefix}: target_thread must be current_thread_when_installed or "
            "thread_alias:<portable-name>"
        )
    if context.context_mode != "thread_continuity":
        errors.append(f"{prefix}: thread_wakeup automation must use thread_continuity")
    if context.status != "PAUSED":
        errors.append(
            f"{prefix}: thread_wakeup automation must stay PAUSED in the portable registry"
        )
    if context.autonomy_level != "observe":
        errors.append(f"{prefix}: thread_wakeup automation must stay observe-only")
    validate_prompt_placeholders(
        context.prompt,
        prefix=prefix,
        allowed=set(),
        required=set(),
        errors=errors,
    )


def validate_operator_trigger_contract(
    data: dict[str, Any],
    entries_by_id: dict[str, dict[str, Any]],
    operator_entries: list[dict[str, Any]],
    root: Path,
    errors: list[str],
) -> None:
    raw_contract = data.get("operator_trigger_contract")
    if not operator_entries:
        if raw_contract is not None:
            errors.append(
                "operator_trigger_contract must be absent when no operator_trigger entries exist"
            )
        return
    contract = validate_closed_object(
        raw_contract,
        description="operator_trigger_contract",
        expected_fields=OPERATOR_TRIGGER_CONTRACT_FIELDS,
        errors=errors,
    )
    if contract is None:
        return
    if contract.get("activation") != OPERATOR_TRIGGER_POLICY:
        errors.append(
            f"operator_trigger_contract.activation must be {OPERATOR_TRIGGER_POLICY}"
        )
    for field_name, expected in OPERATOR_TRIGGER_PLACEHOLDERS.items():
        if contract.get(field_name) != expected:
            errors.append(f"operator_trigger_contract.{field_name} must be {expected}")

    default_model_route = contract.get("default_model_route")
    if not isinstance(default_model_route, str) or not MODEL_ROUTE_RE.fullmatch(
        default_model_route
    ):
        errors.append(
            "operator_trigger_contract.default_model_route must be a portable route id"
        )
        default_model_route = None

    routing_reference = contract.get("model_routing_reference")
    if not isinstance(routing_reference, str) or not routing_reference.strip():
        errors.append(
            "operator_trigger_contract.model_routing_reference must be a non-empty "
            "repo-relative file"
        )
        routing_reference = None
    else:
        error = instruction_source_error(
            routing_reference,
            root,
            description="operator_trigger_contract.model_routing_reference",
        )
        if error:
            errors.append(error)

    validate_source_chain_stage_assignments(contract.get("stage_assignments"), errors)

    for entry in operator_entries:
        automation_id = str(entry.get("id", "<missing>"))
        if default_model_route is not None and entry.get("model_route") != default_model_route:
            errors.append(
                f"{automation_id}: operator_trigger model_route must match "
                "operator_trigger_contract.default_model_route"
            )
        if routing_reference is not None and routing_reference not in string_list(
            entry.get("instruction_sources")
        ):
            errors.append(
                f"{automation_id}: model_routing_reference must be declared in "
                "instruction_sources"
            )

    raw_order = contract.get("source_chain_order")
    if not isinstance(raw_order, list) or not raw_order:
        errors.append(
            "operator_trigger_contract.source_chain_order must be a non-empty list"
        )
        return
    if not all(
        isinstance(item, str) and PORTABLE_ID_RE.fullmatch(item) for item in raw_order
    ):
        errors.append(
            "operator_trigger_contract.source_chain_order must contain portable automation ids"
        )
        return
    order = list(raw_order)
    if len(order) != len(set(order)):
        errors.append(
            "operator_trigger_contract.source_chain_order must not contain duplicates"
        )
    narrow_operator_ids = {
        str(entry.get("id"))
        for entry in operator_entries
        if entry.get("cadence_role") == "narrow_source_chain"
    }
    if set(order) != narrow_operator_ids:
        errors.append(
            "operator_trigger_contract.source_chain_order must contain every and only "
            "narrow_source_chain operator-trigger id"
        )

    observed_stages: list[str] = []
    for automation_id in order:
        entry = entries_by_id.get(automation_id)
        if entry is None:
            errors.append(
                "operator_trigger_contract.source_chain_order references unknown "
                f"automation id: {automation_id}"
            )
            continue
        if entry.get("kind") != "operator_trigger":
            errors.append(
                "operator_trigger_contract.source_chain_order entry "
                f"{automation_id} must use kind operator_trigger"
            )
        if entry.get("cadence_role") != "narrow_source_chain":
            errors.append(
                "operator_trigger_contract.source_chain_order entry "
                f"{automation_id} must use cadence_role narrow_source_chain"
            )
        stage = entry.get("chain_stage")
        if isinstance(stage, str):
            observed_stages.append(stage)
    if tuple(observed_stages) != SOURCE_CHAIN_STAGES:
        errors.append(
            "operator_trigger_contract.source_chain_order must resolve to chain_stage "
            f"values {', '.join(SOURCE_CHAIN_STAGES)}"
        )


def validate_registry(
    path: Path,
    *,
    require_active_source_chain: bool = False,
    root: Path | None = None,
    raw_bytes: bytes | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        raw = (
            raw_bytes
            if raw_bytes is not None
            else safe_paths.read_regular_file_bytes(
                path,
                description="automation registry",
            )
        )
        data = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
    except OSError as exc:
        return [f"cannot read registry: {exc}"]
    except UnicodeDecodeError as exc:
        return [f"registry must be UTF-8: {exc}"]
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    except ValueError as exc:
        return [str(exc)]

    if not isinstance(data, dict):
        return ["registry root must be an object"]
    missing_top_level = sorted(
        {"automations", "project_root_placeholder", "schema_version", "timezone"}
        - set(data)
    )
    unknown_top_level = sorted(set(data) - TOP_LEVEL_FIELDS)
    if missing_top_level:
        errors.append(f"registry is missing fields: {', '.join(missing_top_level)}")
    if unknown_top_level:
        errors.append(f"registry has unknown fields: {', '.join(unknown_top_level)}")

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("project_root_placeholder") != PROJECT_ROOT_PLACEHOLDER:
        errors.append("project_root_placeholder must be {PROJECT_ROOT}")
    registry_timezone = validate_timezone(
        data.get("timezone"),
        description="timezone",
        errors=errors,
    )
    if "install_notes" in data:
        validate_text_lines(
            data.get("install_notes"),
            description="install_notes",
            errors=errors,
        )
    for value_path, value in iter_string_values(data):
        if has_host_path(value):
            errors.append(f"{value_path}: must not contain host-specific absolute paths")

    automations = data.get("automations")
    if not isinstance(automations, list) or not automations:
        errors.append("automations must be a non-empty list")
        return errors

    repo_root = root if root is not None else registry_root(path)
    seen_ids: set[str] = set()
    entries_by_id: dict[str, dict[str, Any]] = {}
    operator_entries: list[dict[str, Any]] = []
    active_narrow_source_chain = False
    for index, raw_entry in enumerate(automations):
        prefix = f"automations[{index}]"
        if not isinstance(raw_entry, dict):
            errors.append(f"{prefix}: entry must be an object")
            continue
        context = _validate_common_entry(
            raw_entry,
            index,
            registry_timezone=registry_timezone,
            repo_root=repo_root,
            seen_ids=seen_ids,
            entries_by_id=entries_by_id,
            errors=errors,
        )
        if context.kind == "cron":
            context = _validate_cron_entry(context, errors)
            if (
                context.cadence_role == "narrow_source_chain"
                and context.status == "ACTIVE"
            ):
                active_narrow_source_chain = True
        elif context.kind == "operator_trigger":
            operator_entries.append(context.entry)
            _validate_operator_entry(context, errors)
        elif context.kind == "thread_wakeup":
            _validate_thread_wakeup_entry(context, errors)

    validate_operator_trigger_contract(
        data,
        entries_by_id,
        operator_entries,
        repo_root,
        errors,
    )

    if require_active_source_chain and not active_narrow_source_chain:
        errors.append("no ACTIVE narrow_source_chain cron automation is registered")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint the portable Codex automation registry.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "registry",
        nargs="?",
        default="codex_automation_registry.json",
        help=(
            "Automation registry JSON file to lint "
            "(default: codex_automation_registry.json)."
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root used to resolve repo-relative instruction_sources.",
    )
    parser.add_argument(
        "--require-active-source-chain",
        action="store_true",
        help="Fail when no narrow source-chain cron automation is ACTIVE.",
    )
    args = parser.parse_args()

    raw_root = Path(args.root).expanduser()
    if raw_root.is_symlink():
        parser.error("--root must not be a symlink")
    try:
        root = raw_root.resolve(strict=True)
    except OSError as exc:
        parser.error(f"--root cannot be resolved: {exc}")
    if not root.is_dir():
        parser.error("--root must be a directory")
    registry = Path(args.registry).expanduser().absolute()
    input_errors = safe_paths.bounded_input_errors(
        registry,
        root,
        description="automation registry input",
    )

    report = {
        "registry": str(registry),
        "root": str(root),
        "errors": [
            *input_errors,
            *(
                validate_registry(
                    registry,
                    require_active_source_chain=args.require_active_source_chain,
                    root=root,
                )
                if not input_errors
                else []
            ),
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
