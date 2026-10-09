#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
import re
from pathlib import Path
from typing import Iterable

import automation_orders_lint
import lint_reviewer_lane_feedback
import markdown_structure
import project_contract_model
import safe_paths


TOP_LEVEL_BULLET = re.compile(r"^[-*+] ")
DATE_BULLET = re.compile(r"^[-*+] (\d{4}-\d{2}-\d{2}), ")
CHECKBOX = re.compile(r"^\s*[-*+]\s\[[ xX]\]")
DONE_CHECKBOX = re.compile(r"^\s*[-*+]\s\[[xX]\]")
FRAMEWORK_FEEDBACK_ENTRY = re.compile(
    r"^### (?P<entry_id>FF-\d{4}) - (?P<title>.*)$"
)
FRAMEWORK_FEEDBACK_SECOND_LEVEL_HEADING = re.compile(r"^## (?!#)(.+)$")
FRAMEWORK_FEEDBACK_THIRD_LEVEL_HEADING = re.compile(r"^###(?:[ \t]+.*)?$")
FRAMEWORK_FEEDBACK_FIELD = re.compile(
    r"^(Status|Category|Framework Target|Evidence Basis|Evidence Source|Confidence):\s*(.*)$"
)
FRAMEWORK_FEEDBACK_MAINTAINER_FIELD = re.compile(
    r"^(Decision|Rationale|Framework Change):\s*(.*)$"
)
FRAMEWORK_FEEDBACK_SECTION = re.compile(r"^#### (.+)$")
FRAMEWORK_FEEDBACK_CHECKLIST_ITEM = re.compile(
    r"^\s*[-*+]\s\[(?P<state>[ xX])\]\s+(?P<text>\S(?:.*\S)?)\s*$"
)
FRAMEWORK_FEEDBACK_CHECKBOX_SHAPED_ITEM = re.compile(
    r"^\s*[-*+]\s+\[[^\]\r\n]*\](?:\s+.*)?\s*$"
)
FRAMEWORK_FEEDBACK_NEXT_CANDIDATE_ID = re.compile(
    r"^Next candidate ID: `(?P<entry_id>FF-\d{4})`\.$"
)
FRAMEWORK_FEEDBACK_REQUIRED_FIELDS = {
    "Status",
    "Category",
    "Framework Target",
    "Evidence Basis",
    "Evidence Source",
    "Confidence",
}
FRAMEWORK_FEEDBACK_REQUIRED_SECTIONS = {
    "Sanitized Observation",
    "Abstracted Pattern",
    "Candidate Framework Change",
    "Applicability",
    "Non-Goals And Limits",
    "Source-Registry Implication",
    "Deterministic-Check Implication",
    "Evidence Summary",
    "Public Sources",
    "Anti-Leak Checklist",
    "Maintainer Decision",
}
FRAMEWORK_FEEDBACK_PROSE_SECTIONS = FRAMEWORK_FEEDBACK_REQUIRED_SECTIONS - {
    "Anti-Leak Checklist",
    "Maintainer Decision",
}
FRAMEWORK_FEEDBACK_ANTI_LEAK_ATTESTATIONS = (
    "No project, client, repository, branch, issue, pull-request, commit, team, "
    "user, or organization identifiers",
    "No local paths, private URLs, internal domains, hostnames, IP addresses, "
    "database names, bucket names, or service names",
    "No secrets, tokens, credentials, certificates, connection strings, "
    "environment values, or redacted-near-misses",
    "No personal names, emails, handles, customer data, private metrics, or "
    "proprietary business context",
    "No raw logs, stack traces, transcripts, screenshots, copied private code, "
    "or proprietary architecture",
    "Observation is abstracted before framework use",
)
FRAMEWORK_FEEDBACK_MAINTAINER_FIELDS = (
    "Decision",
    "Rationale",
    "Framework Change",
)
FRAMEWORK_FEEDBACK_NONSUBSTANTIVE_VALUE_KEYS = {
    "",
    "na",
    "none",
    "notapplicable",
    "pending",
    "tbd",
    "todo",
}
FRAMEWORK_FEEDBACK_TARGETS = {
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
FRAMEWORK_FEEDBACK_ALLOWED_VALUES = {
    "Status": {"candidate", "needs-review", "promoted", "adapted", "rejected", "no-action"},
    "Category": {
        "observed-friction",
        "source-gap",
        "duplicate-research",
        "practice-guide-gap",
        "reviewer-lane-feedback",
        "deterministic-check-candidate",
        "contract-gap",
        "rejected-idea",
        "other",
    },
    "Framework Target": FRAMEWORK_FEEDBACK_TARGETS,
    "Evidence Basis": {
        "single-observation",
        "repeated-in-project",
        "repeated-across-projects",
    },
    "Evidence Source": {
        "project-evidence",
        "deterministic-tool-evidence",
        "primary-external-source",
        "expert-commentary",
        "model-reviewer-advice",
        "insufficient-evidence",
    },
    "Confidence": {"low", "medium", "high"},
}
FRAMEWORK_FEEDBACK_DECISIONS = {"pending", "promote", "adapt", "reject", "no-action"}
FRAMEWORK_FEEDBACK_STATUSES_BY_DECISION = {
    "pending": {"candidate", "needs-review"},
    "promote": {"promoted"},
    "adapt": {"adapted"},
    "reject": {"rejected"},
    "no-action": {"no-action"},
}
FRAMEWORK_FEEDBACK_WEAK_PROMOTION_SOURCES = frozenset(
    {
        "project-evidence",
        "expert-commentary",
        "model-reviewer-advice",
        "insufficient-evidence",
    }
)
STRUCTURED_OPTIONAL_STATE_SECTIONS = {
    "SOURCE_PACKS.md": (
        "Policy",
        "Sources",
        "Open Source Gaps",
        "Upstream Framework Candidates",
    ),
    "SOURCE_UPDATE.md": (
        "Update Policy",
        "Source Registry",
        "Recent Checks",
        "Open Gaps",
        "Framework Source Feedback",
    ),
    "SOURCE_MONITOR_RESEARCHER.md": (
        "Project Configuration",
        "Objective",
        "Required Context",
        "Acquisition Boundary",
        "Report Output",
        "Non-Goals",
    ),
    "SECURITY_VERIFICATION.md": (
        "Scope",
        "Profiles",
        "Authorization Boundaries",
        "Tool Output Triage",
    ),
}


def structured_optional_state_keys() -> dict[str, dict[str, tuple[str, ...]]]:
    """Return state-lint keys from the canonical projection registry."""

    accumulated: dict[str, dict[str, list[str]]] = {
        "SOURCE_PACKS.md": {
            "Policy": ["Shared Framework Source Reference"],
        }
    }
    for projection in project_contract_model.STATE_DEFINITION_PROJECTION_SPECS:
        accumulated.setdefault(projection.filename, {}).setdefault(
            projection.state_section,
            [],
        ).append(projection.state_key)
    return {
        filename: {
            section: tuple(keys)
            for section, keys in sections.items()
        }
        for filename, sections in accumulated.items()
    }


STRUCTURED_OPTIONAL_STATE_KEYS = structured_optional_state_keys()
FRAMEWORK_FEEDBACK_LEAK_PATTERNS = (
    ("host path", safe_paths.LOCAL_ABSOLUTE_PATH_RE),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("private URL", re.compile(r"https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2[0-9]|3[01])\.|[^/\s]+\.(?:local|internal|corp|lan)\b)", re.IGNORECASE)),
    ("IP address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("environment assignment", re.compile(r"\b[A-Z][A-Z0-9_]{2,}=")),
    ("long token", re.compile(r"\b[A-Za-z0-9_-]{40,}\b")),
    ("git commit hash", re.compile(r"\b[0-9a-f]{40}\b")),
    ("stack trace", re.compile(r"(Traceback \(most recent call last\)|\bat\s+\S+:\d+|Exception:)")),
)
STATE_FILE_MAX_BYTES = 1024 * 1024
STATE_HEADER_SCHEMA_VERSION = "1"
STATE_HEADER_FIELDS = {
    "TODO.md": ("state_schema_version", "active_count"),
    "DECISIONS.md": ("state_schema_version", "durable_decision_count", "directive_count"),
}
STATE_HEADER_KEYS = {
    key
    for keys in STATE_HEADER_FIELDS.values()
    for key in keys
}
HEADER_FIELD_RE = re.compile(r"^([a-z][a-z0-9_]*):\s*(.*)$")
OPEN_CHECKBOX = re.compile(r"^\s*[-*+]\s\[ \]\s*(.*)$")
TODO_EXPLICIT_ID = re.compile(r"^ID:\s*(\S+)?(?:\s+.*)?$")
TODO_NAMED_ID = re.compile(r"^((?:TODO|TASK)-\d{4}-\d{2}-\d{2}-\d{2})(?:\s+.*)?$")
DURABLE_RECORD_HEADER = re.compile(
    r"^[-*+] (?P<date>\d{4}-\d{2}-\d{2}), "
    r"(?P<kind>decision_id|directive_id):\s*"
    r"(?P<record_id>[^\s,;]+)(?P<suffix>.*)$"
)
DECISION_REQUIRED_FIELDS = (
    "Status",
    "Scope",
    "Decision",
    "Rationale",
    "Alternatives considered",
    "Evidence or verification",
    "Authority source",
    "Supersession relationship",
    "Review trigger",
)
DIRECTIVE_REQUIRED_FIELDS = (
    "Status",
    "Directive",
    "Authority source",
    "Scope",
    "Expiry or review trigger",
    "Affected files or surfaces",
)
DURABLE_RECORD_FIELDS = DECISION_REQUIRED_FIELDS + tuple(
    field for field in DIRECTIVE_REQUIRED_FIELDS if field not in DECISION_REQUIRED_FIELDS
)
DURABLE_RECORD_FIELD = re.compile(
    r"^\s{2,}(" + "|".join(re.escape(field) for field in DURABLE_RECORD_FIELDS) + r"):\s*(.*)$"
)
PRECEDENT_ID_PATTERN = r"P-\d{4}-\d{2}-\d{2}-\d{2}"
PRECEDENT_CITATION = re.compile(
    rf"^- Citation:\s*`(?P<citation>{PRECEDENT_ID_PATTERN})`\s*$"
)
PRECEDENT_FIELD_NAMES = ("Trigger", "Holding", "Required Checks", "Source")
PRECEDENT_FIELD = re.compile(
    r"^ {2}(?P<field>"
    + "|".join(re.escape(field) for field in PRECEDENT_FIELD_NAMES)
    + r"):\s*(?P<value>\S(?:.*\S)?)\s*$"
)
PRECEDENT_TRIGGER_INDEX_ENTRY = re.compile(
    rf"^- (?P<trigger>\S(?:.*\S)?):\s*`(?P<citation>{PRECEDENT_ID_PATTERN})`\s*$"
)
DECISION_STATUSES = frozenset({"active", "superseded"})
DIRECTIVE_STATUSES = frozenset({"active", "superseded", "expired", "revoked"})
SUPERSESSION_RELATIONSHIP = re.compile(
    r"^(supersedes|superseded by)\s+([^\s,;]+)$"
)


@dataclass(frozen=True)
class DurableRecord:
    index: int
    lines: tuple[str, ...]
    kind: str | None
    record_id: str | None
    header_suffix: str
    fields: dict[str, str]
    duplicate_fields: frozenset[str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint downstream project state files created from project_state_templates/.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=".", help="Project contract root containing state files.")
    parser.add_argument(
        "--project-root",
        help=(
            "Selected project root for project-relative automation paths and "
            "reviewer evidence references. Defaults to --root."
        ),
    )
    return parser


def _state_text(path: Path, text: str | None = None) -> str:
    if text is not None:
        return text
    return safe_paths.read_regular_file_bytes(
        path,
        description=f"{path.name} state input",
        max_bytes=STATE_FILE_MAX_BYTES,
    ).decode("utf-8")


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


def substantive_section(lines: list[str]) -> bool:
    return any(
        value
        and not value.startswith("<!--")
        and not (value.startswith("_") and value.endswith("_"))
        for value in (line.strip() for line in lines)
    )


def substantive_framework_feedback_value(value: str) -> bool:
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return (
        normalized not in FRAMEWORK_FEEDBACK_NONSUBSTANTIVE_VALUE_KEYS
        and any(character.isalnum() for character in normalized)
    )


def section_key_values(lines: list[str]) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    for raw in lines:
        value = raw.strip()
        if value.startswith("- "):
            value = value[2:].strip()
        if ":" not in value:
            continue
        key, field_value = value.split(":", 1)
        normalized_key = key.strip()
        if normalized_key in values:
            duplicates.add(normalized_key)
        values[normalized_key] = field_value.strip()
    return values, duplicates


def lint_structured_optional_state(
    name: str,
    text: str,
    errors: list[str],
) -> None:
    if "{{" in text or "}}" in text:
        errors.append(f"{name}: unresolved template placeholder")
    sections = markdown_h2_sections(text)
    for heading in STRUCTURED_OPTIONAL_STATE_SECTIONS[name]:
        instances = sections.get(heading, [])
        if not instances:
            errors.append(f"{name}: missing required section: ## {heading}")
            continue
        if len(instances) > 1:
            errors.append(f"{name}: duplicate required section: ## {heading}")
            continue
        if not substantive_section(instances[0]):
            errors.append(f"{name}: required section has no substantive content: ## {heading}")
    for heading, keys in STRUCTURED_OPTIONAL_STATE_KEYS.get(name, {}).items():
        instances = sections.get(heading, [])
        if len(instances) != 1:
            continue
        values, duplicates = section_key_values(instances[0])
        errors.extend(
            f"{name}: ## {heading} duplicates field: {key}"
            for key in sorted(duplicates)
        )
        for key in keys:
            value = values.get(key, "").strip()
            if not value or (value.startswith("[") and value.endswith("]")):
                errors.append(f"{name}: ## {heading} missing concrete field: {key}")


def substantive_lines(path: Path, text: str | None = None) -> list[str]:
    ignored_prefixes = ("# ", "## ", "### ", "_Format:", "_Maintained")
    lines = []
    for _line_number, raw in markdown_structure.operative_lines(_state_text(path, text)):
        line = raw.strip()
        if not line or line in {"None.", "- None.", "* None.", "+ None."}:
            continue
        header_match = HEADER_FIELD_RE.match(line)
        if header_match and header_match.group(1) in STATE_HEADER_KEYS:
            continue
        if any(line.startswith(prefix) for prefix in ignored_prefixes):
            continue
        lines.append(raw)
    return lines


def non_fenced_lines(path: Path, text: str | None = None) -> list[str]:
    return [
        line
        for _line_number, line in markdown_structure.operative_lines(
            _state_text(path, text)
        )
    ]


def non_fenced_raw_lines(
    path: Path,
    text: str | None = None,
) -> list[tuple[int, str]]:
    """Return numbered non-fence lines without masking HTML comments.

    Structural state parsing ignores comments, but privacy scanning must inspect
    their raw bytes so non-rendered text cannot conceal project information.
    """

    visibility = markdown_structure.MarkdownVisibilityState()
    lines: list[tuple[int, str]] = []
    for line_number, raw in enumerate(_state_text(path, text).splitlines(), start=1):
        fence_event, _visible_line = visibility.consume(raw)
        if fence_event is None:
            lines.append((line_number, raw))
    return lines


def read_state_header(path: Path, text: str | None = None) -> dict[str, str]:
    header: dict[str, str] = {}
    for raw in _state_text(path, text).splitlines():
        if not raw.strip():
            break
        match = HEADER_FIELD_RE.match(raw.strip())
        if not match:
            break
        header[match.group(1)] = match.group(2).strip()
    return header


def _append_unique(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)


def dated_durable_record_lines(path: Path, text: str | None = None) -> list[tuple[str, ...]]:
    records: list[tuple[str, ...]] = []
    current: list[str] | None = None
    for raw in non_fenced_lines(path, text):
        if TOP_LEVEL_BULLET.match(raw):
            if current is not None:
                records.append(tuple(current))
            current = [raw] if DATE_BULLET.match(raw) else None
        elif current is not None:
            current.append(raw)
    if current is not None:
        records.append(tuple(current))
    return records


def parse_durable_record(index: int, lines: tuple[str, ...]) -> DurableRecord:
    header = DURABLE_RECORD_HEADER.match(lines[0])
    kind = header.group("kind") if header else None
    record_id = header.group("record_id") if header else None
    header_suffix = header.group("suffix").strip() if header else ""
    field_parts: dict[str, list[str]] = {}
    duplicate_fields: set[str] = set()
    current_field: str | None = None
    for raw in lines[1:]:
        field_match = DURABLE_RECORD_FIELD.match(raw)
        if field_match:
            field_name = field_match.group(1)
            current_field = field_name
            if field_name in field_parts:
                duplicate_fields.add(field_name)
            field_parts.setdefault(field_name, []).append(field_match.group(2).strip())
            continue
        if current_field is not None and (raw.startswith("  ") or raw.startswith("\t")):
            continuation = raw.strip()
            if continuation:
                field_parts[current_field].append(continuation)
    fields = {
        field: " ".join(part for part in parts if part).strip()
        for field, parts in field_parts.items()
    }
    return DurableRecord(
        index=index,
        lines=lines,
        kind=kind,
        record_id=record_id,
        header_suffix=header_suffix,
        fields=fields,
        duplicate_fields=frozenset(duplicate_fields),
    )


def durable_records(path: Path, text: str | None = None) -> list[DurableRecord]:
    return [
        parse_durable_record(index, lines)
        for index, lines in enumerate(dated_durable_record_lines(path, text), start=1)
    ]


def durable_record_kind(
    record: DurableRecord,
    errors: list[str],
) -> str | None:
    if record.kind is None:
        _append_unique(
            errors,
            f"DECISIONS.md: dated record {record.index} has neither decision_id nor directive_id; exactly one record kind is required",
        )
        return None
    return "decision" if record.kind == "decision_id" else "directive"


def classified_decision_record_counts(
    path: Path,
    errors: list[str],
    text: str | None = None,
) -> tuple[int, int, int]:
    records = durable_records(path, text)
    durable = 0
    directives = 0
    for record in records:
        kind = durable_record_kind(record, errors)
        if kind == "decision":
            durable += 1
        elif kind == "directive":
            directives += 1
    return durable, directives, len(records)


def active_todo_id(raw: str) -> str | None:
    checkbox = OPEN_CHECKBOX.match(raw)
    if not checkbox:
        return None
    content = checkbox.group(1).strip()
    explicit = TODO_EXPLICIT_ID.match(content)
    if explicit:
        return explicit.group(1)
    named = TODO_NAMED_ID.match(content)
    return named.group(1) if named else None


def lint_state_header(path: Path, errors: list[str], text: str | None = None) -> None:
    required = STATE_HEADER_FIELDS.get(path.name)
    if required is None:
        return
    state_text = _state_text(path, text)
    header = read_state_header(path, state_text)
    if not header:
        errors.append(f"{path.name}: missing machine-readable state header")
        return
    header_keys: list[str] = []
    for raw in state_text.splitlines():
        if not raw.strip():
            break
        match = HEADER_FIELD_RE.match(raw.strip())
        if not match:
            break
        header_keys.append(match.group(1))
    duplicates = sorted(key for key in set(header_keys) if header_keys.count(key) > 1)
    if duplicates:
        errors.append(f"{path.name}: state header has duplicate fields: {', '.join(duplicates)}")
    unknown = sorted(set(header_keys) - set(required))
    if unknown:
        errors.append(f"{path.name}: state header has unknown fields: {', '.join(unknown)}")
    missing = [key for key in required if key not in header]
    if missing:
        errors.append(f"{path.name}: state header missing fields: {', '.join(missing)}")
        return
    if header["state_schema_version"] != STATE_HEADER_SCHEMA_VERSION:
        errors.append(f"{path.name}: state_schema_version must be {STATE_HEADER_SCHEMA_VERSION}")
    counts: dict[str, int] = {}
    for key in required:
        if key == "state_schema_version":
            continue
        value = header.get(key, "")
        count = -1
        if value.isascii() and value.isdecimal():
            try:
                count = int(value)
            except ValueError:
                # Respect the interpreter's integer-conversion bound rather
                # than imposing a separate state-file digit-count policy.
                pass
        counts[key] = count
        if count < 0:
            errors.append(f"{path.name}: {key} must be a non-negative integer")
    lines = substantive_lines(path, state_text)
    has_records = any(TOP_LEVEL_BULLET.match(line) or CHECKBOX.match(line) for line in lines)
    if path.name == "TODO.md":
        active_count = counts["active_count"]
        actual_active_count = sum(
            1 for raw in lines if CHECKBOX.match(raw) and not DONE_CHECKBOX.match(raw)
        )
        if active_count >= 0 and active_count != actual_active_count:
            errors.append(
                f"TODO.md: active_count is {active_count}, but {actual_active_count} active checklist entr{'y' if actual_active_count == 1 else 'ies'} exist"
            )
        if active_count == 0 and has_records:
            errors.append("TODO.md: active_count is 0 but active state entries exist")
        if active_count > 0:
            seen_ids: set[str] = set()
            for raw in lines:
                if not CHECKBOX.match(raw) or DONE_CHECKBOX.match(raw):
                    continue
                item_id = active_todo_id(raw)
                if not item_id:
                    errors.append("TODO.md: active entries must carry a nonempty ID")
                    continue
                if item_id in seen_ids:
                    errors.append(f"TODO.md: duplicate active entry ID: {item_id}")
                seen_ids.add(item_id)
    elif path.name == "DECISIONS.md":
        durable_count = counts["durable_decision_count"]
        directive_count = counts["directive_count"]
        actual_durable_count, actual_directive_count, actual_record_count = classified_decision_record_counts(
            path,
            errors,
            state_text,
        )
        if (
            durable_count >= 0
            and directive_count >= 0
            and durable_count + directive_count != actual_record_count
        ):
            errors.append(
                "DECISIONS.md: durable_decision_count plus directive_count does not match "
                f"the dated decision/directive record count ({actual_record_count})"
            )
        if durable_count >= 0 and durable_count != actual_durable_count:
            errors.append(
                f"DECISIONS.md: durable_decision_count is {durable_count}, but {actual_durable_count} "
                f"dated decision_id record{'s' if actual_durable_count != 1 else ''} exist"
            )
        if directive_count >= 0 and directive_count != actual_directive_count:
            errors.append(
                f"DECISIONS.md: directive_count is {directive_count}, but {actual_directive_count} "
                f"dated directive_id record{'s' if actual_directive_count != 1 else ''} exist"
            )
        if durable_count == 0 and directive_count == 0 and has_records:
            errors.append("DECISIONS.md: durable_decision_count and directive_count are 0 but decision entries exist")


def lint_todo(
    path: Path,
    errors: list[str],
    warnings: list[str],
    text: str | None = None,
) -> None:
    for _line_number, raw in markdown_structure.operative_lines(_state_text(path, text)):
        if DONE_CHECKBOX.match(raw):
            errors.append(f"{path.name}: completed items must be removed from active state")
        if DATE_BULLET.match(raw):
            warnings.append(f"{path.name}: dated durable entry looks misplaced in TODO")


def has_valid_date_bullet(path: Path, raw: str, errors: list[str]) -> bool:
    match = DATE_BULLET.match(raw)
    if not match:
        return False
    try:
        parsed = date.fromisoformat(match.group(1))
    except ValueError:
        errors.append(f"{path.name}: date bullet is not a valid ISO date: {match.group(1)}")
        return False
    if parsed > date.today():
        errors.append(f"{path.name}: date bullet is in the future: {match.group(1)}")
        return False
    return True


def parsed_supersession_relationship(value: str) -> tuple[str, str | None] | None:
    if value == "none":
        return "none", None
    match = SUPERSESSION_RELATIONSHIP.fullmatch(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def validate_durable_record_shapes(
    path: Path,
    records: list[DurableRecord],
    errors: list[str],
) -> tuple[dict[str, DurableRecord], dict[str, str]]:
    records_by_id: dict[str, DurableRecord] = {}
    kinds_by_id: dict[str, str] = {}
    for record in records:
        kind = durable_record_kind(record, errors)
        if record.kind is None or record.record_id is None or kind is None:
            _append_unique(
                errors,
                f"{path.name}: dated record {record.index} must begin with a date, "
                "one record kind, and a nonempty record ID",
            )
            continue
        record_id = record.record_id
        if record.header_suffix:
            _append_unique(
                errors,
                f"{path.name}: {record_id} record header must end after its ID",
            )
        if record_id in records_by_id:
            _append_unique(errors, f"{path.name}: duplicate record ID: {record_id}")
        else:
            records_by_id[record_id] = record
            kinds_by_id[record_id] = kind

        required_fields = (
            DECISION_REQUIRED_FIELDS if kind == "decision" else DIRECTIVE_REQUIRED_FIELDS
        )
        if record.duplicate_fields:
            _append_unique(
                errors,
                f"{path.name}: {record_id} duplicates fields: "
                + ", ".join(sorted(record.duplicate_fields)),
            )
        missing_fields = [field for field in required_fields if field not in record.fields]
        empty_fields = [
            field
            for field in required_fields
            if field in record.fields and not record.fields[field]
        ]
        if missing_fields:
            _append_unique(
                errors,
                f"{path.name}: {record_id} missing fields: {', '.join(missing_fields)}",
            )
        if empty_fields:
            _append_unique(
                errors,
                f"{path.name}: {record_id} has empty fields: {', '.join(empty_fields)}",
            )

        status = record.fields.get("Status")
        allowed_statuses = DECISION_STATUSES if kind == "decision" else DIRECTIVE_STATUSES
        if status and status not in allowed_statuses:
            _append_unique(
                errors,
                f"{path.name}: {record_id} has invalid Status: {status}; expected one of "
                + ", ".join(sorted(allowed_statuses)),
            )
    return records_by_id, kinds_by_id


def validate_decision_supersession(
    path: Path,
    decision_records: dict[str, DurableRecord],
    errors: list[str],
) -> None:
    relationships: dict[str, tuple[str, str | None]] = {}
    for record_id, record in decision_records.items():
        relationship_text = record.fields.get("Supersession relationship")
        if not relationship_text:
            continue
        relationship = parsed_supersession_relationship(relationship_text)
        if relationship is None:
            _append_unique(
                errors,
                f"{path.name}: {record_id} has invalid Supersession relationship: "
                f"{relationship_text}; expected none, supersedes <decision_id>, or "
                "superseded by <decision_id>",
            )
            continue
        relationships[record_id] = relationship
        direction, target_id = relationship
        status = record.fields.get("Status")
        if status == "superseded" and direction != "superseded by":
            _append_unique(
                errors,
                f"{path.name}: superseded decision {record_id} must reference its replacement "
                "with 'superseded by <decision_id>'",
            )
        if status == "active" and direction == "superseded by":
            _append_unique(
                errors,
                f"{path.name}: active decision {record_id} cannot use a 'superseded by' relationship",
            )
        if target_id is None:
            continue
        if target_id == record_id:
            _append_unique(
                errors,
                f"{path.name}: decision {record_id} cannot supersede or be superseded by itself",
            )
            continue
        target = decision_records.get(target_id)
        if target is None:
            _append_unique(
                errors,
                f"{path.name}: decision {record_id} references unknown decision ID: {target_id}",
            )
            continue
        expected_target_status = "superseded" if direction == "supersedes" else "active"
        target_status = target.fields.get("Status")
        if target_status in DECISION_STATUSES and target_status != expected_target_status:
            _append_unique(
                errors,
                f"{path.name}: decision {record_id} {direction} {target_id}, but {target_id} "
                f"has Status {target_status}; expected {expected_target_status}",
            )

    for record_id, (direction, target_id) in relationships.items():
        if direction != "supersedes" or target_id not in relationships:
            continue
        reverse_direction, reverse_target_id = relationships[target_id]
        if reverse_direction == "superseded by" and reverse_target_id != record_id:
            _append_unique(
                errors,
                f"{path.name}: decision {record_id} supersedes {target_id}, but {target_id} "
                f"names {reverse_target_id} as its replacement",
            )


def validate_durable_records(
    path: Path,
    errors: list[str],
    text: str | None = None,
) -> None:
    records_by_id, kinds_by_id = validate_durable_record_shapes(
        path,
        durable_records(path, text),
        errors,
    )
    decision_records = {
        record_id: record
        for record_id, record in records_by_id.items()
        if kinds_by_id[record_id] == "decision"
    }
    validate_decision_supersession(path, decision_records, errors)


def lint_decisions(path: Path, errors: list[str], text: str | None = None) -> None:
    for raw in substantive_lines(path, text):
        if CHECKBOX.match(raw):
            errors.append(f"{path.name}: task checkboxes do not belong in durable decisions")
        elif TOP_LEVEL_BULLET.match(raw):
            if DATE_BULLET.match(raw):
                has_valid_date_bullet(path, raw, errors)
            else:
                errors.append(f"{path.name}: decision entries must start with an ISO date bullet")
    validate_durable_records(path, errors, text)


def lint_findings(path: Path, errors: list[str], text: str | None = None) -> None:
    for raw in substantive_lines(path, text):
        if CHECKBOX.match(raw):
            errors.append(f"{path.name}: task checkboxes do not belong in findings")
        elif TOP_LEVEL_BULLET.match(raw):
            if DATE_BULLET.match(raw):
                has_valid_date_bullet(path, raw, errors)
            else:
                errors.append(f"{path.name}: finding entries must start with an ISO date bullet")


def lint_precedents(path: Path, errors: list[str], text: str | None = None) -> None:
    state_text = _state_text(path, text)
    sections: dict[str, list[markdown_structure.MarkdownSection]] = {}
    for section in markdown_structure.markdown_sections(state_text):
        sections.setdefault(section.title, []).append(section)

    current_h2: str | None = None
    for line_number, raw in markdown_structure.operative_lines(state_text):
        h2_match = re.fullmatch(r"## (?!#)(.+)", raw)
        if h2_match is not None:
            current_h2 = h2_match.group(1).strip()
            continue
        record_shaped = (
            PRECEDENT_CITATION.fullmatch(raw) is not None
            or PRECEDENT_FIELD.fullmatch(raw) is not None
        )
        if record_shaped:
            if current_h2 != "Records":
                errors.append(
                    f"{path.name}: precedent record content outside ## Records "
                    f"on line {line_number}"
                )
        elif (
            PRECEDENT_TRIGGER_INDEX_ENTRY.fullmatch(raw) is not None
            and current_h2 != "Trigger Index"
        ):
            errors.append(
                f"{path.name}: precedent index entry outside ## Trigger Index "
                f"on line {line_number}"
            )

    required_sections: dict[str, markdown_structure.MarkdownSection] = {}
    for title in ("Trigger Index", "Records"):
        instances = sections.get(title, [])
        if not instances:
            errors.append(f"{path.name}: missing required section: ## {title}")
            continue
        if len(instances) > 1:
            errors.append(f"{path.name}: duplicate required section: ## {title}")
            continue
        required_sections[title] = instances[0]

    records_section = required_sections.get("Records")
    record_ids: list[str] = []
    record_fields: dict[str, str] | None = None
    record_id: str | None = None
    record_line = 0
    record_sentinel_lines: list[int] = []
    record_orphan_lines: list[int] = []

    def finish_record() -> None:
        nonlocal record_fields, record_id, record_line
        if record_fields is None or record_id is None:
            return
        for field in PRECEDENT_FIELD_NAMES:
            if field not in record_fields:
                errors.append(
                    f"{path.name}: precedent {record_id} on line {record_line} "
                    f"missing field: {field}"
                )
        record_fields = None
        record_id = None
        record_line = 0

    if records_section is not None:
        for line_number, raw in records_section.lines:
            if not raw.strip():
                continue
            if raw.strip() == "- None.":
                finish_record()
                record_sentinel_lines.append(line_number)
                continue
            citation_match = PRECEDENT_CITATION.fullmatch(raw)
            if citation_match is not None:
                finish_record()
                citation = citation_match.group("citation")
                record_id = citation
                record_line = line_number
                record_fields = {}
                record_ids.append(citation)
                continue
            field_match = PRECEDENT_FIELD.fullmatch(raw)
            if field_match is not None and record_fields is not None and record_id is not None:
                field = field_match.group("field")
                if field in record_fields:
                    errors.append(
                        f"{path.name}: precedent {record_id} has duplicate field: {field}"
                    )
                else:
                    record_fields[field] = field_match.group("value").strip()
                continue
            record_orphan_lines.append(line_number)
            errors.append(
                f"{path.name}: malformed or orphan precedent content on line {line_number}"
            )
        finish_record()

        if record_sentinel_lines:
            if len(record_sentinel_lines) != 1 or record_ids or record_orphan_lines:
                errors.append(
                    f"{path.name}: Records '- None.' sentinel must be the only substantive content"
                )
        elif not record_ids:
            errors.append(
                f"{path.name}: Records must contain exact precedent records or the '- None.' sentinel"
            )

    for citation, count in Counter(record_ids).items():
        if count != 1:
            errors.append(f"{path.name}: duplicate precedent citation: {citation}")

    index_section = required_sections.get("Trigger Index")
    index_ids: list[str] = []
    index_sentinel_lines: list[int] = []
    index_orphan_lines: list[int] = []
    if index_section is not None:
        for line_number, raw in index_section.lines:
            if not raw.strip():
                continue
            if raw.strip() == "- None.":
                index_sentinel_lines.append(line_number)
                continue
            entry_match = PRECEDENT_TRIGGER_INDEX_ENTRY.fullmatch(raw)
            if entry_match is None:
                index_orphan_lines.append(line_number)
                errors.append(
                    f"{path.name}: malformed or orphan Trigger Index content on line {line_number}"
                )
                continue
            index_ids.append(entry_match.group("citation"))

        if index_sentinel_lines:
            if (
                len(index_sentinel_lines) != 1
                or index_ids
                or index_orphan_lines
                or record_ids
            ):
                errors.append(
                    f"{path.name}: Trigger Index '- None.' sentinel may be used only "
                    "when no records exist and must be the only substantive index content"
                )
        elif not index_ids:
            errors.append(
                f"{path.name}: Trigger Index must contain exact entries or the '- None.' sentinel"
            )

    if record_ids and index_section is None:
        errors.append(f"{path.name}: precedents with records must include a Trigger Index")

    record_id_set = set(record_ids)
    index_counts = Counter(index_ids)
    for citation in sorted(record_id_set):
        count = index_counts[citation]
        if count != 1:
            errors.append(
                f"{path.name}: Trigger Index must reference precedent citation {citation} exactly once"
            )
    for citation in sorted(set(index_ids) - record_id_set):
        errors.append(
            f"{path.name}: Trigger Index references unknown precedent citation {citation}"
        )


def lint_framework_feedback(
    path: Path,
    errors: list[str],
    warnings: list[str],
    text: str | None = None,
) -> None:
    state_text = _state_text(path, text)
    lines = list(markdown_structure.operative_lines(state_text))
    for line_number, raw in non_fenced_raw_lines(path, state_text):
        for label, pattern in FRAMEWORK_FEEDBACK_LEAK_PATTERNS:
            if pattern.search(raw):
                errors.append(f"{path.name}: possible {label} in non-fenced content on line {line_number}")

    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_section: str | None = None
    current_h2: str | None = None
    open_candidate_sentinel_lines: list[int] = []
    open_candidate_section_count = 0
    candidate_sequence_section_count = 0
    next_candidate_ids: list[str] = []
    skip_misowned_entry_body = False
    for line_number, raw in lines:
        h2_match = FRAMEWORK_FEEDBACK_SECOND_LEVEL_HEADING.match(raw)
        if h2_match:
            current_h2 = h2_match.group(1).strip()
            if current_h2 == "Candidate Sequence":
                candidate_sequence_section_count += 1
            elif current_h2 == "Open Candidates":
                open_candidate_section_count += 1
            current = None
            current_section = None
            skip_misowned_entry_body = False
            continue
        if skip_misowned_entry_body:
            continue
        entry_match = FRAMEWORK_FEEDBACK_ENTRY.match(raw)
        if entry_match:
            if current_h2 != "Open Candidates":
                errors.append(
                    f"{path.name}: framework feedback entry outside "
                    f"'## Open Candidates' on line {line_number}"
                )
                current = None
                current_section = None
                skip_misowned_entry_body = True
                continue
            if not entry_match.group("title").strip():
                errors.append(
                    f"{path.name}: framework feedback entry title must not be empty "
                    f"on line {line_number}"
                )
                current = None
                current_section = None
                continue
            current = {
                "id": entry_match.group("entry_id"),
                "fields": {},
                "sections": set(),
                "section_counts": {},
                "section_bodies": {},
                "checklist_items": [],
                "malformed_checklist_items": 0,
                "maintainer_fields": {},
                "stray_maintainer_fields": [],
            }
            entries.append(current)
            current_section = None
            continue
        if current is None and current_h2 == "Open Candidates" and raw == "- None.":
            open_candidate_sentinel_lines.append(line_number)
            continue
        if FRAMEWORK_FEEDBACK_THIRD_LEVEL_HEADING.match(raw):
            errors.append(
                f"{path.name}: malformed third-level heading on line {line_number}; "
                "expected '### FF-NNNN - title'"
            )
            current = None
            current_section = None
            continue
        section_match = FRAMEWORK_FEEDBACK_SECTION.match(raw)
        field_match = FRAMEWORK_FEEDBACK_FIELD.match(raw)
        maintainer_match = FRAMEWORK_FEEDBACK_MAINTAINER_FIELD.match(raw)
        if current is None:
            next_candidate_match = FRAMEWORK_FEEDBACK_NEXT_CANDIDATE_ID.match(raw)
            if current_h2 == "Candidate Sequence" and next_candidate_match:
                next_candidate_ids.append(next_candidate_match.group("entry_id"))
            elif section_match:
                errors.append(
                    f"{path.name}: fourth-level feedback section outside a valid "
                    f"entry on line {line_number}"
                )
            elif maintainer_match:
                errors.append(
                    f"{path.name}: Maintainer Decision field outside a valid entry "
                    f"on line {line_number}"
                )
            elif field_match and current_h2 != "Allowed Values":
                errors.append(
                    f"{path.name}: candidate header field outside a valid entry "
                    f"on line {line_number}"
                )
            elif current_h2 == "Candidate Sequence" and raw.strip():
                errors.append(
                    f"{path.name}: unrecognized content in '## Candidate Sequence' "
                    f"on line {line_number}"
                )
            elif current_h2 == "Open Candidates" and raw.strip():
                errors.append(
                    f"{path.name}: unrecognized content outside an entry in "
                    f"'## Open Candidates' on line {line_number}"
                )
            continue
        if section_match:
            current_section = section_match.group(1)
            sections = current["sections"]
            if not isinstance(sections, set):
                errors.append(f"{path.name}: internal feedback section state is invalid")
                return
            sections.add(current_section)
            section_counts = current["section_counts"]
            if not isinstance(section_counts, dict):
                errors.append(f"{path.name}: internal feedback section count state is invalid")
                return
            count = section_counts.get(current_section, 0)
            section_counts[current_section] = count + 1 if isinstance(count, int) else 1
            section_bodies = current["section_bodies"]
            if not isinstance(section_bodies, dict):
                errors.append(f"{path.name}: internal feedback section body state is invalid")
                return
            bodies = section_bodies.setdefault(current_section, [])
            if not isinstance(bodies, list):
                errors.append(f"{path.name}: internal feedback section bodies are invalid")
                return
            bodies.append([])
            continue
        if current_section is None:
            if not raw.strip():
                continue
            if field_match:
                fields = current["fields"]
                if not isinstance(fields, dict):
                    errors.append(f"{path.name}: internal feedback field state is invalid")
                    return
                field_name = field_match.group(1)
                values = fields.setdefault(field_name, [])
                if not isinstance(values, list):
                    errors.append(f"{path.name}: internal feedback field values are invalid")
                    return
                values.append(field_match.group(2).strip())
                continue
            if maintainer_match:
                stray_fields = current["stray_maintainer_fields"]
                if not isinstance(stray_fields, list):
                    errors.append(f"{path.name}: internal feedback maintainer state is invalid")
                    return
                stray_fields.append(maintainer_match.group(1))
                continue
            errors.append(
                f"{path.name}: unrecognized nonblank entry-header content "
                f"on line {line_number}"
            )
            continue

        if current_section is not None:
            section_bodies = current["section_bodies"]
            if not isinstance(section_bodies, dict):
                errors.append(f"{path.name}: internal feedback section body state is invalid")
                return
            bodies = section_bodies.get(current_section)
            if not isinstance(bodies, list) or not bodies or not isinstance(bodies[-1], list):
                errors.append(f"{path.name}: internal feedback section body is invalid")
                return
            bodies[-1].append(raw)
        if maintainer_match:
            if current_section == "Maintainer Decision":
                maintainer_fields = current["maintainer_fields"]
                if not isinstance(maintainer_fields, dict):
                    errors.append(f"{path.name}: internal feedback maintainer state is invalid")
                    return
                field_name = maintainer_match.group(1)
                values = maintainer_fields.setdefault(field_name, [])
                if not isinstance(values, list):
                    errors.append(f"{path.name}: internal feedback maintainer values are invalid")
                    return
                values.append(maintainer_match.group(2).strip())
            else:
                stray_fields = current["stray_maintainer_fields"]
                if not isinstance(stray_fields, list):
                    errors.append(f"{path.name}: internal feedback maintainer state is invalid")
                    return
                stray_fields.append(maintainer_match.group(1))
            continue
        if (
            current_section == "Anti-Leak Checklist"
            and FRAMEWORK_FEEDBACK_CHECKBOX_SHAPED_ITEM.match(raw)
        ):
            checklist_match = FRAMEWORK_FEEDBACK_CHECKLIST_ITEM.match(raw)
            if checklist_match is None:
                malformed_count = current["malformed_checklist_items"]
                current["malformed_checklist_items"] = (
                    malformed_count + 1 if isinstance(malformed_count, int) else 1
                )
                continue
            checklist_items = current["checklist_items"]
            if not isinstance(checklist_items, list):
                errors.append(f"{path.name}: internal feedback checklist state is invalid")
                return
            checklist_items.append(
                (
                    checklist_match.group("text"),
                    checklist_match.group("state").lower() == "x",
                )
            )

    if open_candidate_section_count != 1:
        errors.append(
            f"{path.name}: must contain exactly one '## Open Candidates' "
            f"section; found {open_candidate_section_count}"
        )
    if candidate_sequence_section_count != 1:
        errors.append(
            f"{path.name}: must contain exactly one '## Candidate Sequence' "
            f"section; found {candidate_sequence_section_count}"
        )
    if candidate_sequence_section_count == 1 and len(next_candidate_ids) != 1:
        errors.append(
            f"{path.name}: '## Candidate Sequence' must contain exactly one "
            f"Next candidate ID field; found {len(next_candidate_ids)}"
        )
    if entries:
        if open_candidate_sentinel_lines:
            errors.append(
                f"{path.name}: '## Open Candidates' must not mix '- None.' with "
                "framework feedback entries"
            )
    elif len(open_candidate_sentinel_lines) != 1:
        errors.append(
            f"{path.name}: '## Open Candidates' without entries must contain "
            f"exactly one '- None.' sentinel; found {len(open_candidate_sentinel_lines)}"
        )

    seen_ids: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        entry_id = str(entry["id"])
        if entry_id in seen_ids:
            errors.append(f"{path.name}: duplicate framework feedback entry id: {entry_id}")
        seen_ids.add(entry_id)

        fields = entry["fields"]
        sections = entry["sections"]
        section_counts = entry["section_counts"]
        section_bodies = entry["section_bodies"]
        checklist_items = entry["checklist_items"]
        malformed_checklist_items = entry["malformed_checklist_items"]
        maintainer_fields = entry["maintainer_fields"]
        stray_maintainer_fields = entry["stray_maintainer_fields"]
        if (
            not isinstance(fields, dict)
            or not isinstance(sections, set)
            or not isinstance(section_counts, dict)
            or not isinstance(section_bodies, dict)
            or not isinstance(checklist_items, list)
            or not isinstance(malformed_checklist_items, int)
            or not isinstance(maintainer_fields, dict)
            or not isinstance(stray_maintainer_fields, list)
        ):
            errors.append(f"{path.name}: {entry_id} has invalid internal parser state")
            continue
        missing_fields = sorted(FRAMEWORK_FEEDBACK_REQUIRED_FIELDS - set(fields))
        missing_sections = sorted(
            (FRAMEWORK_FEEDBACK_REQUIRED_SECTIONS - {"Maintainer Decision"})
            - sections
        )
        if missing_fields:
            errors.append(f"{path.name}: {entry_id} missing fields: {', '.join(missing_fields)}")
        if missing_sections:
            errors.append(f"{path.name}: {entry_id} missing sections: {', '.join(missing_sections)}")
        duplicate_sections = sorted(
            section
            for section, count in section_counts.items()
            if section in FRAMEWORK_FEEDBACK_REQUIRED_SECTIONS
            and section != "Maintainer Decision"
            and isinstance(count, int)
            and count > 1
        )
        if duplicate_sections:
            errors.append(
                f"{path.name}: {entry_id} duplicates sections: "
                f"{', '.join(duplicate_sections)}"
            )
        unknown_sections = sorted(
            section
            for section in section_counts
            if section not in FRAMEWORK_FEEDBACK_REQUIRED_SECTIONS
        )
        if unknown_sections:
            errors.append(
                f"{path.name}: {entry_id} has unknown sections: "
                f"{', '.join(unknown_sections)}"
            )
        maintainer_section_count = section_counts.get("Maintainer Decision", 0)
        if maintainer_section_count != 1:
            errors.append(
                f"{path.name}: {entry_id} must contain exactly one Maintainer Decision "
                f"section; found {maintainer_section_count}"
            )
        for section in sorted(FRAMEWORK_FEEDBACK_PROSE_SECTIONS):
            bodies = section_bodies.get(section)
            if not isinstance(bodies, list) or len(bodies) != 1:
                continue
            body = bodies[0]
            if not isinstance(body, list):
                errors.append(f"{path.name}: {entry_id} has invalid {section} body")
                continue
            if not any(
                value
                and not value.startswith("#")
                and not (value.startswith("_") and value.endswith("_"))
                for value in (str(line).strip() for line in body)
            ):
                errors.append(
                    f"{path.name}: {entry_id} section {section!r} "
                    "has no substantive non-fenced content"
                )

        duplicate_fields = sorted(
            field
            for field, values in fields.items()
            if isinstance(field, str) and isinstance(values, list) and len(values) > 1
        )
        if duplicate_fields:
            errors.append(
                f"{path.name}: {entry_id} duplicates fields: {', '.join(duplicate_fields)}"
            )

        for field, allowed in FRAMEWORK_FEEDBACK_ALLOWED_VALUES.items():
            values = fields.get(field)
            if not isinstance(values, list):
                continue
            for value in sorted({value for value in values if isinstance(value, str)}):
                if value not in allowed:
                    errors.append(
                        f"{path.name}: {entry_id} field {field!r} has invalid value: {value}"
                    )

        single_values = {
            field: values[0]
            for field, values in fields.items()
            if isinstance(field, str)
            and isinstance(values, list)
            and len(values) == 1
            and isinstance(values[0], str)
        }

        stray_field_counts = Counter(
            field for field in stray_maintainer_fields if isinstance(field, str)
        )
        for field in FRAMEWORK_FEEDBACK_MAINTAINER_FIELDS:
            count = stray_field_counts.get(field, 0)
            if count:
                errors.append(
                    f"{path.name}: {entry_id} must not contain {field} fields "
                    f"outside Maintainer Decision; found {count}"
                )

        maintainer_values: dict[str, str] = {}
        for field in FRAMEWORK_FEEDBACK_MAINTAINER_FIELDS:
            values = maintainer_fields.get(field)
            if not isinstance(values, list) or len(values) != 1:
                count = len(values) if isinstance(values, list) else 0
                errors.append(
                    f"{path.name}: {entry_id} must contain exactly one {field} "
                    f"field inside Maintainer Decision; found {count}"
                )
                continue
            value = values[0]
            if isinstance(value, str):
                maintainer_values[field] = value

        decision: str | None = None
        decision_value = maintainer_values.get("Decision")
        if decision_value is not None and not decision_value:
            errors.append(
                f"{path.name}: {entry_id} Maintainer Decision must not be empty"
            )
        elif decision_value is not None:
            decision = decision_value
        if decision is not None and decision not in FRAMEWORK_FEEDBACK_DECISIONS:
            errors.append(f"{path.name}: {entry_id} maintainer decision has invalid value: {decision}")
        elif decision is not None:
            status = single_values.get("Status")
            expected_statuses = FRAMEWORK_FEEDBACK_STATUSES_BY_DECISION[decision]
            if status is not None and status not in expected_statuses:
                errors.append(
                    f"{path.name}: {entry_id} status {status!r} is inconsistent "
                    f"with maintainer decision {decision!r}"
                )
            rationale = maintainer_values.get("Rationale", "")
            framework_change = maintainer_values.get("Framework Change", "")
            if decision != "pending" and not substantive_framework_feedback_value(rationale):
                errors.append(
                    f"{path.name}: {entry_id} non-pending Maintainer Decision "
                    "requires a substantive Rationale"
                )
            if decision in {"promote", "adapt"} and not substantive_framework_feedback_value(
                framework_change
            ):
                errors.append(
                    f"{path.name}: {entry_id} {decision} decision requires a "
                    "substantive Framework Change"
                )

        if malformed_checklist_items:
            errors.append(
                f"{path.name}: {entry_id} anti-leak checklist contains "
                f"{malformed_checklist_items} malformed item(s)"
            )
        parsed_checklist_items = [
            item
            for item in checklist_items
            if isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], bool)
        ]
        checklist_counts = Counter(item[0] for item in parsed_checklist_items)
        missing_attestations = [
            attestation
            for attestation in FRAMEWORK_FEEDBACK_ANTI_LEAK_ATTESTATIONS
            if checklist_counts.get(attestation, 0) == 0
        ]
        if missing_attestations:
            errors.append(
                f"{path.name}: {entry_id} anti-leak checklist is missing declared "
                f"attestations: {', '.join(missing_attestations)}"
            )
        if any(count > 1 for count in checklist_counts.values()):
            errors.append(
                f"{path.name}: {entry_id} anti-leak checklist contains duplicate item text"
            )
        if any(not item[1] for item in parsed_checklist_items):
            errors.append(
                f"{path.name}: {entry_id} anti-leak checklist must be completed "
                "before maintainer review"
            )

        if (
            single_values.get("Evidence Basis") == "single-observation"
            and single_values.get("Evidence Source")
            in FRAMEWORK_FEEDBACK_WEAK_PROMOTION_SOURCES
            and decision == "promote"
        ):
            warnings.append(f"{path.name}: {entry_id} promotes a single-observation candidate")
        has_broad_msa_evidence = (
            single_values.get("Evidence Basis") == "repeated-across-projects"
            or single_values.get("Evidence Source") == "primary-external-source"
        )
        has_direct_structural_doctrine_evidence = (
            single_values.get("Category") == "contract-gap"
            and single_values.get("Evidence Source")
            == "deterministic-tool-evidence"
        )
        if (
            single_values.get("Framework Target") == "doctrine"
            and not has_broad_msa_evidence
            and not has_direct_structural_doctrine_evidence
        ):
            warnings.append(f"{path.name}: {entry_id} targets doctrine without broad or public evidence")
        if len(single_values.get("Status", "")) > 32:
            errors.append(f"{path.name}: framework feedback entry {index} has an overlong status field")

    if len(next_candidate_ids) == 1 and entries:
        next_candidate_number = int(next_candidate_ids[0].removeprefix("FF-"))
        current_numbers = [
            int(str(entry["id"]).removeprefix("FF-")) for entry in entries
        ]
        if next_candidate_number <= max(current_numbers):
            errors.append(
                f"{path.name}: Next candidate ID {next_candidate_ids[0]} must be "
                "greater than every current framework feedback entry ID"
            )


def lint_state_files(
    root: Path,
    selected_names: Iterable[str] | None = None,
    *,
    require_core: bool = True,
    project_root: Path | None = None,
) -> dict[str, list[str]]:
    root = root.resolve()
    selected_project_root = (project_root or root).resolve()
    files = {
        "TODO.md": root / "TODO.md",
        "DECISIONS.md": root / "DECISIONS.md",
        "FRAMEWORK_FEEDBACK.md": root / "FRAMEWORK_FEEDBACK.md",
        "FINDINGS.md": root / "FINDINGS.md",
        "PRECEDENTS.md": root / "PRECEDENTS.md",
        "REVIEWER_LANE_FEEDBACK.md": root / "REVIEWER_LANE_FEEDBACK.md",
        "SOURCE_PACKS.md": root / "SOURCE_PACKS.md",
        "SOURCE_UPDATE.md": root / "SOURCE_UPDATE.md",
        "SOURCE_MONITOR_RESEARCHER.md": root / "SOURCE_MONITOR_RESEARCHER.md",
        "SECURITY_VERIFICATION.md": root / "SECURITY_VERIFICATION.md",
        "AUTOMATION_ORDERS.json": root / "AUTOMATION_ORDERS.json",
    }
    errors: list[str] = []
    warnings: list[str] = []
    snapshots: dict[str, str] = {}
    missing_inputs: set[str] = set()
    selected = set(files) if selected_names is None else set(selected_names)
    unsupported = sorted(selected - set(files))
    errors.extend(
        f"unsupported selected project state file: {name}"
        for name in unsupported
    )
    supported = selected & set(files)
    required_names = {"TODO.md", "DECISIONS.md"} if require_core else set()

    for name in sorted(supported | required_names):
        path = files[name]
        try:
            raw = safe_paths.read_regular_file_bytes(
                path,
                description=f"{name} input",
                max_bytes=STATE_FILE_MAX_BYTES,
            )
        except FileNotFoundError:
            missing_inputs.add(name)
            if selected_names is not None and name in supported:
                errors.append(f"missing selected project state file: {name}")
            continue
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: state file could not be read: {exc}")
            continue
        try:
            snapshots[name] = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{name}: state file must be valid UTF-8: {exc}")

    for required in (("TODO.md", "DECISIONS.md") if require_core else ()):
        if required in missing_inputs:
            errors.append(f"missing required project state file: {required}")

    if "TODO.md" in supported and "TODO.md" in snapshots:
        text = snapshots["TODO.md"]
        lint_state_header(files["TODO.md"], errors, text)
        lint_todo(files["TODO.md"], errors, warnings, text)
    if "DECISIONS.md" in supported and "DECISIONS.md" in snapshots:
        text = snapshots["DECISIONS.md"]
        lint_state_header(files["DECISIONS.md"], errors, text)
        lint_decisions(files["DECISIONS.md"], errors, text)
    if "FRAMEWORK_FEEDBACK.md" in supported and "FRAMEWORK_FEEDBACK.md" in snapshots:
        text = snapshots["FRAMEWORK_FEEDBACK.md"]
        lint_framework_feedback(files["FRAMEWORK_FEEDBACK.md"], errors, warnings, text)
    if "FINDINGS.md" in supported and "FINDINGS.md" in snapshots:
        text = snapshots["FINDINGS.md"]
        lint_findings(files["FINDINGS.md"], errors, text)
    if "PRECEDENTS.md" in supported and "PRECEDENTS.md" in snapshots:
        text = snapshots["PRECEDENTS.md"]
        lint_precedents(files["PRECEDENTS.md"], errors, text)
    if "REVIEWER_LANE_FEEDBACK.md" in supported and "REVIEWER_LANE_FEEDBACK.md" in snapshots:
        feedback_result = lint_reviewer_lane_feedback.lint(
            files["REVIEWER_LANE_FEEDBACK.md"],
            selected_project_root,
            text=snapshots["REVIEWER_LANE_FEEDBACK.md"],
        )
        errors.extend(f"REVIEWER_LANE_FEEDBACK.md: {error}" for error in feedback_result["errors"])
        warnings.extend(f"REVIEWER_LANE_FEEDBACK.md: {warning}" for warning in feedback_result["warnings"])
    for name in STRUCTURED_OPTIONAL_STATE_SECTIONS:
        if name in supported and name in snapshots:
            lint_structured_optional_state(name, snapshots[name], errors)
    if "AUTOMATION_ORDERS.json" in supported and "AUTOMATION_ORDERS.json" in snapshots:
        try:
            automation_payload = safe_paths.loads_json_no_duplicates(
                snapshots["AUTOMATION_ORDERS.json"]
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"AUTOMATION_ORDERS.json: invalid JSON: {exc}")
        else:
            automation_errors, automation_warnings = automation_orders_lint.validate_manifest(
                automation_payload,
                project_root=selected_project_root,
                manifest_path=files["AUTOMATION_ORDERS.json"],
            )
            errors.extend(f"AUTOMATION_ORDERS.json: {error}" for error in automation_errors)
            warnings.extend(f"AUTOMATION_ORDERS.json: {warning}" for warning in automation_warnings)

    return {"errors": errors, "warnings": warnings}


def receipt_owned_state_names(
    root: Path,
    project_root: Path,
) -> set[str] | None:
    """Return receipt-owned state names for a valid generated project instance.

    A canonical optional-state filename can also be an ordinary project file.  The
    generated instance receipt, rather than the basename alone, establishes state
    ownership.  Missing or invalid receipts return ``None`` so callers preserve the
    historical all-known-files behavior instead of letting malformed provenance
    suppress lint coverage.
    """

    selected_root = root.expanduser().resolve(strict=False)
    selected_project_root = project_root.expanduser().resolve(strict=False)
    try:
        contract_relative = selected_root.relative_to(selected_project_root)
    except ValueError:
        return None
    contract_root_ref = contract_relative.as_posix()

    # Imported lazily because project_instance_lint imports the bootstrap renderer,
    # while this linter is also invoked by bootstrap's post-install conformance.
    import project_instance_lint

    preimage = project_instance_lint.validate_recorded_preimage(
        selected_project_root,
        contract_root_ref,
    )
    errors = preimage.get("errors")
    managed_files = preimage.get("managed_files")
    if (
        not isinstance(errors, list)
        or errors
        or not isinstance(managed_files, list)
        or not all(isinstance(item, str) for item in managed_files)
    ):
        return None

    managed = set(managed_files)
    selected = {"TODO.md", "DECISIONS.md"}
    for name in project_contract_model.STATE_TEMPLATES:
        if name in selected:
            continue
        project_relative = (
            name if contract_root_ref == "." else f"{contract_root_ref}/{name}"
        )
        if project_relative in managed:
            selected.add(name)
    return selected


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root)
    project_root = Path(args.project_root) if args.project_root else root
    result = lint_state_files(
        root,
        receipt_owned_state_names(root, project_root),
        project_root=project_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
