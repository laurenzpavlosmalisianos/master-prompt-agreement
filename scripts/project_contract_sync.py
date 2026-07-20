#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import json
import re
import shlex
from pathlib import Path
import unicodedata

import automation_orders_lint
import integration_registry
import markdown_structure
import project_bootstrap
import project_contract_model as contract_model
import prompt_load_report
import safe_paths


SOW_TITLES = set(contract_model.SOW_SECTION_TITLES) | {"Definitions"}
FIELD_MAP = dict(contract_model.FIELD_MAP)
COMMON_COMMAND_LABELS = {
    spec.sow_label: spec.runtime_label for spec in contract_model.COMMAND_SPECS
}
COMMAND_DEFERRAL_FIELDS = {
    spec.sow_label: spec.deferral_field for spec in contract_model.COMMAND_SPECS
}
MINIMAL_RUNTIME_DEFERRALS = {
    "Language/Runtime Standards": contract_model.MINIMAL_RUNTIME_STANDARDS_DEFERRAL,
    "Languages and frameworks": contract_model.MINIMAL_STACK_DEFERRAL,
    "Architecture": contract_model.MINIMAL_ARCHITECTURE_DEFERRAL,
    "In scope": contract_model.MINIMAL_IN_SCOPE_DEFERRAL,
    "Out of scope": contract_model.MINIMAL_OUT_OF_SCOPE_DEFERRAL,
}
ABSENT_VALUES = {"", "none", "tbd"}
REQUIRED_SOW_SECTIONS = {
    "Definitions",
    "Build and Development Commands",
    "Scope",
    "Technical Specifications",
}
REQUIRED_PROJECT_SECTIONS = {
    "Active Scope",
    "Active Stack",
    "Common Commands",
    "Definitions",
    "Framework Verification Commands",
    "Loading Rule",
}
MINIMAL_DEFERRAL_KEYS = tuple(
    sorted(
        spec.key
        for spec in contract_model.structured_field_specs("minimal_deferrals")
    )
)
MINIMAL_DEFERRAL_BOUNDARY_TYPES = contract_model.MINIMAL_DEFERRAL_BOUNDARY_TYPES
ARBITRATION_PANEL_REQUIRED_FIELDS = frozenset(
    spec.label
    for spec in contract_model.structured_field_specs("arbitration_panel")
    if spec.render_mode == "labeled" and spec.required
)
MINIMAL_DEFERRABLE_FIELDS = contract_model.MINIMAL_DEFERRABLE_FIELDS
_MINIMAL_DEFERRAL_PATTERN_PARTS = tuple(
    (
        ("" if index == 0 else r"\s+—\s+")
        + re.escape(spec.label)
        + rf":\s*(?P<{spec.key}>.*?)"
    )
    for index, spec in enumerate(
        contract_model.structured_field_specs("minimal_deferrals")
    )
)
MINIMAL_DEFERRAL_RE = re.compile(
    "^" + "".join(_MINIMAL_DEFERRAL_PATTERN_PARTS) + r"\.?$"
)
FRAMEWORK_VERIFICATION_REQUIRED_KEYS = {
    "Framework reference",
    "Framework Verification Runner",
    "Core conformance",
    "Runner fallback",
}
ENTRYPOINT_NAMES = ("AGENTS.md", "CLAUDE.md")
INTERNAL_LOCAL_STATE_PATTERNS = safe_paths.INTERNAL_LOCAL_STATE_PATTERNS
SOW_TITLE_RE = re.compile(r"^Statement of Work\s+[—-]\s+(?P<project>.+?)\s*$", re.MULTILINE)
MSA_VERSION_RE = re.compile(r"^Version:\s*(?P<version>[0-9.]+)\b", re.MULTILINE)
CONTRACT_FORMAT_MARKER_RE = re.compile(
    rf"^<!-- {re.escape(contract_model.CONTRACT_FORMAT_MARKER_KEY)}: (?P<version>0|[1-9][0-9]*) -->$"
)
CONTRACT_FORMAT_VERSION_MAX_DIGITS = 10
CONTRACT_FORMAT_MARKER_MAX_CHARS = len(
    f"<!-- {contract_model.CONTRACT_FORMAT_MARKER_KEY}:  -->"
) + CONTRACT_FORMAT_VERSION_MAX_DIGITS
SOW_VERSION_LINE_RE = re.compile(
    r"^SOW Version: (?P<version>.+?)  MSA Reference: (?P<reference>.+?)  "
    r"Date: (?P<date>\d{4}-\d{2}-\d{2})$"
)
CONTRACT_PROJECT_LINE_RE = re.compile(r"^Project: (?P<project>.+)$")
CONTRACT_DATE_LINE_RE = re.compile(r"^Date: (?P<date>\d{4}-\d{2}-\d{2})$")
PROJECT_NUMBERED_ROW_RE = re.compile(r"^(?P<number>[1-9][0-9]*)\. (?P<value>\S.*)$")
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent


def normalize(text: str) -> str:
    return " ".join(text.replace("—", "-").casefold().split())


def normalized_authority_identity(text: str) -> str:
    """Normalize only model-owned heading and scalar-key identities."""

    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def first_match(pattern: re.Pattern[str], text: str, group: str) -> str:
    match = pattern.search(text)
    return "" if match is None else match.group(group).strip()


def contract_format_observation(text: str) -> tuple[str, int | None]:
    """Return one bounded syntactic observation of a generated-format marker."""

    lines = text.splitlines()
    candidates = [
        line
        for line in lines
        if contract_model.CONTRACT_FORMAT_MARKER_KEY in line
    ]
    if not candidates:
        return "missing", None
    if len(candidates) != 1:
        return f"malformed ({len(candidates)} marker candidates)", None
    if not lines or lines[0] != candidates[0]:
        return "malformed (marker is not the first line)", None
    if len(candidates[0]) > CONTRACT_FORMAT_MARKER_MAX_CHARS:
        return "malformed (marker exceeds the bounded version length)", None
    match = CONTRACT_FORMAT_MARKER_RE.fullmatch(candidates[0])
    if match is None:
        return "malformed", None
    version_text = match.group("version")
    if len(version_text) > CONTRACT_FORMAT_VERSION_MAX_DIGITS:
        return "malformed (version exceeds the bounded digit length)", None
    try:
        version = int(version_text)
    except ValueError:
        return "malformed", None
    if candidates[0] != contract_model.contract_format_marker(version):
        return "malformed", None
    return "present", version


@dataclass(frozen=True)
class ParsedContractPreamble:
    project: str
    rendered_date: str
    msa_reference: str
    errors: tuple[str, ...]


def _candidate_index(
    lines: list[str],
    predicate: Callable[[str], bool],
    *,
    source: str,
    label: str,
    errors: list[str],
) -> int | None:
    indexes = [
        index
        for index, line in enumerate(lines)
        if predicate(line)
    ]
    if len(indexes) != 1:
        errors.append(
            f"{source} preamble {label} occurs {len(indexes)} times; expected exactly one"
        )
        return None
    return indexes[0]


def parse_sow_preamble(text: str) -> ParsedContractPreamble:
    lines = text.splitlines()
    errors: list[str] = []
    boundary = next(
        (
            index
            for index, line in enumerate(lines)
            if line in SOW_TITLES
        ),
        len(lines),
    )
    marker_index = _candidate_index(
        lines,
        lambda line: contract_model.CONTRACT_FORMAT_MARKER_KEY in line,
        source="STATEMENT_OF_WORK.md",
        label="format marker",
        errors=errors,
    )
    title_index = _candidate_index(
        lines,
        lambda line: SOW_TITLE_RE.fullmatch(line) is not None,
        source="STATEMENT_OF_WORK.md",
        label="title",
        errors=errors,
    )
    version_index = _candidate_index(
        lines,
        lambda line: line.startswith("SOW Version:"),
        source="STATEMENT_OF_WORK.md",
        label="version/authority/date row",
        errors=errors,
    )
    nonblank_preamble = [
        index for index, line in enumerate(lines[:boundary]) if line.strip()
    ]
    expected_order = [marker_index, title_index, version_index]
    if (
        None not in expected_order
        and (
            nonblank_preamble[:3] != expected_order
            or nonblank_preamble[3:] != [
                index
                for index in range(boundary)
                if lines[index] == contract_model.SOW_OPTIONAL_DEFAULT_RULE
            ]
            or len(nonblank_preamble) != 4
        )
    ):
        errors.append(
            "STATEMENT_OF_WORK.md preamble must contain only marker, title, "
            "version/authority/date row, and the model-owned optional-default rule "
            "in that order before Definitions"
        )
    if marker_index is not None and (
        marker_index != 0 or lines[marker_index] != contract_model.CONTRACT_FORMAT_MARKER
    ):
        errors.append(
            "STATEMENT_OF_WORK.md preamble format marker must be the exact current "
            "marker on the first line"
        )
    title_match = (
        SOW_TITLE_RE.fullmatch(lines[title_index]) if title_index is not None else None
    )
    version_match = (
        SOW_VERSION_LINE_RE.fullmatch(lines[version_index])
        if version_index is not None
        else None
    )
    if version_index is not None and version_match is None:
        errors.append(
            "STATEMENT_OF_WORK.md preamble version row must exactly contain SOW Version, "
            "MSA Reference, and ISO Date"
        )
    return ParsedContractPreamble(
        project=title_match.group("project").strip() if title_match else "",
        rendered_date=version_match.group("date") if version_match else "",
        msa_reference=version_match.group("reference").strip() if version_match else "",
        errors=tuple(errors),
    )


def parse_runtime_preamble(
    text: str,
    *,
    contract_root_ref: str = ".",
) -> ParsedContractPreamble:
    lines = text.splitlines()
    errors: list[str] = []
    boundary = next(
        (index for index, line in enumerate(lines) if line.startswith("## ")),
        len(lines),
    )
    marker_index = _candidate_index(
        lines,
        lambda line: contract_model.CONTRACT_FORMAT_MARKER_KEY in line,
        source="AGENT_PROJECT.md",
        label="format marker",
        errors=errors,
    )
    heading_index = _candidate_index(
        lines,
        lambda line: line == "# Runtime Project Contract",
        source="AGENT_PROJECT.md",
        label="title",
        errors=errors,
    )
    project_index = _candidate_index(
        lines,
        lambda line: line.startswith("Project:"),
        source="AGENT_PROJECT.md",
        label="Project row",
        errors=errors,
    )
    date_index = _candidate_index(
        lines,
        lambda line: line.startswith("Date:"),
        source="AGENT_PROJECT.md",
        label="Date row",
        errors=errors,
    )
    expected_rule = integration_registry.render_project_file_references(
        contract_model.PROJECT_PREAMBLE_RULE,
        contract_root_ref,
    )
    rule_index = _candidate_index(
        lines,
        lambda line: line == expected_rule,
        source="AGENT_PROJECT.md",
        label="generated-projection rule",
        errors=errors,
    )
    authority_index = _candidate_index(
        lines,
        lambda line: line.startswith("Authority:"),
        source="AGENT_PROJECT.md",
        label="Authority row",
        errors=errors,
    )
    expected_order = [
        marker_index,
        heading_index,
        project_index,
        date_index,
        rule_index,
        authority_index,
    ]
    nonblank_preamble = [
        index for index, line in enumerate(lines[:boundary]) if line.strip()
    ]
    if None not in expected_order and nonblank_preamble != expected_order:
        errors.append(
            "AGENT_PROJECT.md preamble must contain only marker, title, Project, Date, "
            "generated-projection rule, and Authority in model-owned order before "
            "the first section"
        )
    if marker_index is not None and (
        marker_index != 0 or lines[marker_index] != contract_model.CONTRACT_FORMAT_MARKER
    ):
        errors.append(
            "AGENT_PROJECT.md preamble format marker must be the exact current marker "
            "on the first line"
        )
    project_match = (
        CONTRACT_PROJECT_LINE_RE.fullmatch(lines[project_index])
        if project_index is not None
        else None
    )
    date_match = (
        CONTRACT_DATE_LINE_RE.fullmatch(lines[date_index])
        if date_index is not None
        else None
    )
    if project_index is not None and project_match is None:
        errors.append("AGENT_PROJECT.md preamble Project row is malformed")
    if date_index is not None and date_match is None:
        errors.append("AGENT_PROJECT.md preamble Date row must contain one exact ISO date")
    expected_authority = integration_registry.render_project_file_references(
        contract_model.PROJECT_AUTHORITY_TEXT,
        contract_root_ref,
    )
    if authority_index is not None and lines[authority_index] != expected_authority:
        errors.append(
            "AGENT_PROJECT.md preamble Authority row must exactly match the "
            "model-owned generated-projection authority"
        )
    return ParsedContractPreamble(
        project=project_match.group("project").strip() if project_match else "",
        rendered_date=date_match.group("date") if date_match else "",
        msa_reference="",
        errors=tuple(errors),
    )


def contract_format_update_errors(
    sow_text: str,
    contract_text: str,
) -> list[str]:
    """Return one root diagnostic when generated contracts are not current."""

    sow_state, sow_version = contract_format_observation(sow_text)
    contract_state, contract_version = contract_format_observation(contract_text)
    expected = contract_model.CONTRACT_FORMAT_VERSION
    if (
        sow_state == "present"
        and contract_state == "present"
        and sow_version == expected
        and contract_version == expected
    ):
        return []

    if sow_state != "present" or contract_state != "present":
        detail = (
            f"STATEMENT_OF_WORK.md marker is {sow_state}; "
            f"AGENT_PROJECT.md marker is {contract_state}"
        )
    elif sow_version != contract_version:
        detail = (
            "contract markers disagree "
            f"(STATEMENT_OF_WORK.md={sow_version}, AGENT_PROJECT.md={contract_version})"
        )
    elif sow_version is not None and sow_version < expected:
        detail = f"both files use older format {sow_version}; supported format is {expected}"
    elif sow_version is not None and sow_version > expected:
        detail = f"both files use future format {sow_version}; supported format is {expected}"
    else:
        detail = f"both files use unsupported format {sow_version}; supported format is {expected}"

    if (
        sow_state == "present"
        and contract_state == "present"
        and sow_version == contract_version
        and sow_version is not None
        and sow_version > expected
    ):
        resolution = (
            f"Use a framework checkout that supports contract format {sow_version}; this "
            "validator does not interpret newer contract formats."
        )
    else:
        resolution = (
            "The current-only lifecycle refreshes only a complete current-format root receipt "
            "and retained input. Run `scripts/project_refresh.py inspect`; if either identity "
            "file is absent or non-current, perform a reviewed project-specific manual "
            "update. This validator does not parse or rewrite other contract formats."
        )
    return [
        "generated project-contract update required: "
        f"{detail}. Expected exactly one `{contract_model.CONTRACT_FORMAT_MARKER}` line "
        f"in each generated contract. {resolution}"
    ]


def preamble_identity_errors(
    sow_text: str,
    contract_text: str,
    *,
    contract_root_ref: str = ".",
) -> list[str]:
    sow_preamble = parse_sow_preamble(sow_text)
    contract_preamble = parse_runtime_preamble(
        contract_text,
        contract_root_ref=contract_root_ref,
    )
    errors = [*sow_preamble.errors, *contract_preamble.errors]
    sow_project = sow_preamble.project
    contract_project = contract_preamble.project
    sow_date = sow_preamble.rendered_date
    contract_date = contract_preamble.rendered_date
    if not sow_project:
        errors.append("STATEMENT_OF_WORK.md missing project name in title")
    if not contract_project:
        errors.append("AGENT_PROJECT.md missing Project preamble")
    if sow_project and contract_project and normalize(sow_project) != normalize(contract_project):
        errors.append(
            "project identity mismatch between STATEMENT_OF_WORK.md title "
            f"({sow_project!r}) and AGENT_PROJECT.md Project ({contract_project!r})"
        )
    if not sow_date:
        errors.append("STATEMENT_OF_WORK.md missing ISO Date in SOW Version line")
    if not contract_date:
        errors.append("AGENT_PROJECT.md missing ISO Date preamble")
    for source, value in (
        ("STATEMENT_OF_WORK.md", sow_date),
        ("AGENT_PROJECT.md", contract_date),
    ):
        if not value:
            continue
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{source} date is not a valid ISO calendar date: {value}")
    if sow_date and contract_date and sow_date != contract_date:
        errors.append(
            "project date mismatch between STATEMENT_OF_WORK.md "
            f"({sow_date}) and AGENT_PROJECT.md ({contract_date})"
        )
    return errors


def msa_reference_errors(sow_text: str, msa_text: str) -> list[str]:
    errors: list[str] = []
    reference = parse_sow_preamble(sow_text).msa_reference
    current_version = first_match(MSA_VERSION_RE, msa_text, "version")
    if not reference:
        errors.append("STATEMENT_OF_WORK.md missing MSA Reference in version line")
        return errors
    if not current_version:
        errors.append("master_service_agreement.md missing Version line")
        return errors
    expected = f"master_service_agreement.md v{current_version}"
    if normalize(reference) != normalize(expected):
        errors.append(
            "STATEMENT_OF_WORK.md MSA Reference does not match current framework MSA version: "
            f"{reference!r} != {expected!r}"
        )
    return errors


def plain_sections(text: str, titles: set[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for _line_number, raw in markdown_structure.operative_lines(text):
        stripped = raw.strip()
        if raw.lstrip() == raw and stripped in titles:
            current = stripped
            sections[current] = []
            continue
        if current:
            sections[current].append(raw.rstrip())
    return sections


def parse_annex_records(
    source: str,
    lines: list[str],
    *,
    allow_conflict_rule: bool,
) -> tuple[dict[str, str], list[str]]:
    """Parse the closed generated Annex A/B/C/derived-D identity grammar."""

    records: dict[str, str] = {}
    errors: list[str] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if allow_conflict_rule and text == contract_model.ANNEX_CONFLICT_RULE:
            continue
        if not text.startswith("- "):
            errors.append(f"{source} Annexes contains unsupported row: {text!r}")
            continue
        payload = text[2:].strip()
        label, separator, reference = payload.partition(":")
        if not separator or not reference.strip():
            errors.append(
                f"{source} Annexes row must contain a canonical label and project-relative reference: "
                f"{payload!r}"
            )
            continue
        label = label.strip()
        identity_match = re.match(r"^Annex\s+(?P<identity>[A-Za-z0-9]+)\b", label)
        if identity_match is None:
            errors.append(f"{source} Annexes row has no canonical Annex identity: {label!r}")
            continue
        identity = identity_match.group("identity")
        expected_label = contract_model.ANNEX_LABEL_BY_IDENTITY.get(identity)
        if expected_label is None:
            errors.append(f"{source} Annexes contains unsupported Annex identity: {identity}")
            continue
        if label != expected_label:
            errors.append(
                f"{source} Annex {identity} label must be exactly {expected_label!r}, "
                f"not {label!r}"
            )
            continue
        if identity in records:
            errors.append(f"{source} Annexes duplicates canonical Annex identity: {identity}")
            continue
        records[identity] = reference.strip()
    return records, errors


def annex_projection_errors(
    sow_lines: list[str],
    contract_lines: list[str],
    security_policy_file: str | None,
) -> list[str]:
    """Require one closed Annex identity map across canonical and runtime surfaces."""

    sow_records, sow_errors = parse_annex_records(
        "STATEMENT_OF_WORK.md",
        sow_lines,
        allow_conflict_rule=True,
    )
    contract_records, contract_errors = parse_annex_records(
        "AGENT_PROJECT.md Active Project Modules",
        contract_lines,
        allow_conflict_rule=False,
    )
    errors = [*sow_errors, *contract_errors]
    derived_identity = contract_model.SECURITY_POLICY_ANNEX_IDENTITY
    if security_policy_file is not None:
        expected_security_reference = contract_model.SECURITY_POLICY_ANNEX_REFERENCE
        security_annex_authorized = normalize(security_policy_file) == normalize(
            "project SECURITY.md"
        )
        for source, records in (
            ("STATEMENT_OF_WORK.md", sow_records),
            ("AGENT_PROJECT.md Active Project Modules", contract_records),
        ):
            if security_annex_authorized and derived_identity not in records:
                errors.append(
                    f"{source} missing derived Annex {derived_identity} for project SECURITY.md"
                )
            elif (
                security_annex_authorized
                and records[derived_identity] != expected_security_reference
            ):
                errors.append(
                    f"{source} derived Annex {derived_identity} must reference exactly "
                    f"{expected_security_reference!r}, not {records[derived_identity]!r}"
                )
            if not security_annex_authorized and derived_identity in records:
                errors.append(
                    f"{source} contains unauthorized Annex {derived_identity}; "
                    "select Security Policy File 'project SECURITY.md' to derive it"
                )

    sow_identities = set(sow_records)
    contract_identities = set(contract_records)
    for identity in sorted(sow_identities - contract_identities):
        errors.append(
            f"AGENT_PROJECT.md Active Project Modules missing canonical Annex {identity}"
        )
    for identity in sorted(contract_identities - sow_identities):
        errors.append(
            f"AGENT_PROJECT.md Active Project Modules contains unbacked Annex {identity}"
        )
    for identity in sorted(sow_identities & contract_identities):
        if sow_records[identity] != contract_records[identity]:
            errors.append(
                f"Annex {identity} reference drift between SOW and project contract: "
                f"{sow_records[identity]!r} != {contract_records[identity]!r}"
            )
    return errors


def annex_project_file_references(lines: list[str]) -> list[tuple[str, str]]:
    records, _errors = parse_annex_records(
        "STATEMENT_OF_WORK.md",
        lines,
        allow_conflict_rule=True,
    )
    return [
        (contract_model.ANNEX_LABEL_BY_IDENTITY[identity], records[identity])
        for identity in sorted(records)
    ]


def markdown_sections(text: str) -> dict[str, list[str]]:
    return {
        section.title: [line.rstrip() for _line_number, line in section.lines]
        for section in markdown_structure.markdown_sections(
            text,
            include_fenced_content=False,
        )
    }


def entrypoint_state_loading_errors(
    entrypoint_name: str,
    text: str,
    *,
    contract_root_ref: str = ".",
) -> list[str]:
    """Require the compact state-loading rule without requiring template identity."""

    errors: list[str] = []
    normalized_text = normalize(text)
    expected_contract = (
        "AGENT_PROJECT.md"
        if contract_root_ref == "."
        else f"{contract_root_ref}/AGENT_PROJECT.md"
    )
    if "article 5" not in normalized_text:
        errors.append(
            f"{entrypoint_name} does not retain the Article 5 project-state pointer"
        )
    if "bare project-state filename" not in normalized_text:
        errors.append(
            f"{entrypoint_name} does not state the bare project-state filename rule"
        )
    expected_root_rule = normalize(
        f"directory containing the rendered `{expected_contract}`"
    )
    if expected_root_rule not in normalized_text:
        errors.append(
            f"{entrypoint_name} does not resolve bare project-state filenames relative "
            f"to the selected contract directory: {expected_contract}"
        )
    return errors


def entrypoint_stable_resolution_errors(
    project_root: Path,
    entrypoint_name: str,
    text: str,
    *,
    contract_root_ref: str = ".",
    expected_framework_reference: str | None = None,
) -> list[str]:
    """Check entrypoint boundaries that do not depend on contract format."""

    errors: list[str] = []
    if "{{" in text or "}}" in text:
        errors.append(f"{entrypoint_name} contains unresolved template placeholder")
    reference, structural_errors = integration_registry.entrypoint_authority_load_references(
        entrypoint_name,
        text,
        contract_root_ref=contract_root_ref,
    )
    errors.extend(structural_errors)
    if reference is None:
        return errors
    if (
        expected_framework_reference is not None
        and reference != expected_framework_reference
    ):
        errors.append(
            f"{entrypoint_name} framework authority-load directive does not match "
            "AGENT_PROJECT.md Framework reference: "
            f"{reference} != {expected_framework_reference}"
        )
    framework_root = safe_paths.resolve_framework_reference(reference, project_root)
    if framework_root is None:
        if "$" in reference and "{{" not in reference and "}}" not in reference:
            return errors
        errors.append(
            f"{entrypoint_name} framework reference is not concretely resolvable: {reference}"
        )
    elif not (framework_root / "runtime" / "operative_charter.md").exists():
        errors.append(
            f"{entrypoint_name} framework reference does not resolve "
            f"runtime/operative_charter.md: {reference}"
        )
    return errors


def entrypoint_resolution_errors(
    project_root: Path,
    entrypoint_name: str,
    text: str,
    *,
    contract_root_ref: str = ".",
    expected_framework_reference: str | None = None,
) -> list[str]:
    errors = entrypoint_stable_resolution_errors(
        project_root,
        entrypoint_name,
        text,
        contract_root_ref=contract_root_ref,
        expected_framework_reference=expected_framework_reference,
    )
    errors.extend(
        entrypoint_state_loading_errors(
            entrypoint_name,
            text,
            contract_root_ref=contract_root_ref,
        )
    )
    return errors


def parse_key_values(lines: list[str], bullet: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        if bullet and stripped.startswith("- "):
            stripped = stripped[2:]
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def unambiguous_key_values(
    lines: list[str],
    *,
    bullet: bool = False,
) -> dict[str, str] | None:
    """Return scalar rows only when no key has competing authority values."""

    if duplicate_key_names(lines, bullet=bullet):
        return None
    return parse_key_values(lines, bullet=bullet)


def arbitration_panel_errors(lines: list[str]) -> list[str]:
    if not any(line.strip() for line in lines):
        return []
    errors = key_value_duplicate_errors(
        "STATEMENT_OF_WORK.md Arbitration Panel",
        lines,
    )
    if errors:
        return errors
    values = parse_key_values(lines)
    if not any(key.startswith("Seat ") for key in values):
        errors.append("STATEMENT_OF_WORK.md Arbitration Panel must define at least one seat")
    for key in sorted(ARBITRATION_PANEL_REQUIRED_FIELDS):
        value = values.get(key, "").strip()
        if not value or normalize(value) in {"tbd", "none"}:
            errors.append(f"STATEMENT_OF_WORK.md Arbitration Panel missing complete rule: {key}")
    return errors


def sow_scalar_section_lines(section: str, lines: list[str]) -> list[str]:
    """Return only model-owned scalar rows from a mixed SOW section."""

    if section == "Direct Panel Rules":
        return [
            line
            for line in lines
            if not line.lstrip().startswith("- ")
            and line.strip().startswith("Standing Panel Convocation Approval:")
        ]
    return lines


def sow_labeled_definition_parity_errors(
    sections: dict[str, list[str]],
    definitions: dict[str, str],
    unambiguous_sections: frozenset[str] | None = None,
    invalid_definition_keys: frozenset[str] = frozenset(),
) -> list[str]:
    """Evaluate every model-owned labeled row assigned to Definition parity."""

    errors: list[str] = []
    for field_spec in contract_model.SOW_LABELED_FIELD_SPECS:
        if field_spec.semantic_owner != "definition-parity":
            continue
        definition_key = field_spec.definition_label
        if definition_key is None:
            continue
        section = contract_model.sow_section_title(field_spec.section_key)
        section_key = field_spec.label
        if definition_key in invalid_definition_keys:
            continue
        if section not in sections and field_spec.section_absence == "ignore":
            continue
        if (
            section in sections
            and unambiguous_sections is not None
            and section not in unambiguous_sections
        ):
            continue
        section_values = unambiguous_key_values(
            sow_scalar_section_lines(section, sections.get(section, []))
        )
        if section_values is None:
            continue
        if section not in sections and field_spec.section_absence == "use-definition-default":
            definition_spec = contract_model.DEFINITIONS_BY_LABEL[definition_key]
            section_value = contract_model.rendered_definition_default(definition_spec)
        else:
            section_value = section_values.get(section_key)
        comparison = (
            compare_exact_value
            if field_spec.comparison == "exact"
            else compare_value
        )
        diagnostic_label = (
            f"STATEMENT_OF_WORK.md {section_key} projection"
            if section_key.startswith(section)
            else f"STATEMENT_OF_WORK.md {section} {section_key}"
        )
        comparison(
            diagnostic_label,
            section_value,
            definitions.get(definition_key),
            errors,
        )
    return errors


def direct_panel_section_projection(lines: list[str]) -> str:
    rules: list[str] = []
    for raw in lines:
        value = raw.strip()
        if not value or value.startswith("_"):
            continue
        if value.startswith("- "):
            value = value[2:].strip()
        if value.startswith("Standing Panel Convocation Approval:"):
            continue
        rules.append(value)
    return "; ".join(rules) or "none"


def governance_projection_errors(
    sections: dict[str, list[str]],
    definitions: dict[str, str],
    unambiguous_sections: frozenset[str] | None = None,
    invalid_definition_keys: frozenset[str] = frozenset(),
) -> list[str]:
    errors: list[str] = []
    panel_lines = sections.get("Arbitration Panel")
    if not (
        panel_lines is not None
        and unambiguous_sections is not None
        and "Arbitration Panel" not in unambiguous_sections
    ):
        expected_panel = (
            "custom package; consult SOW Arbitration Panel"
            if panel_lines is not None and any(line.strip() for line in panel_lines)
            else "framework default"
        )
        if "Arbitration Panel" not in invalid_definition_keys:
            compare_value(
                "STATEMENT_OF_WORK.md Arbitration Panel projection",
                expected_panel,
                definitions.get("Arbitration Panel"),
                errors,
            )

    direct_lines = sections.get("Direct Panel Rules")
    if not (
        direct_lines is not None
        and unambiguous_sections is not None
        and "Direct Panel Rules" not in unambiguous_sections
    ):
        expected_direct = direct_panel_section_projection(direct_lines or [])
        compare_value(
            "STATEMENT_OF_WORK.md Direct Panel Rules projection",
            expected_direct,
            definitions.get("Direct Panel Rules"),
            errors,
        )
        direct_values = unambiguous_key_values(
            sow_scalar_section_lines("Direct Panel Rules", direct_lines or [])
        )
        if (
            direct_values is not None
            and "Standing Panel Convocation Approval" not in invalid_definition_keys
        ):
            compare_value(
                "STATEMENT_OF_WORK.md Direct Panel Rules Standing Panel "
                "Convocation Approval",
                direct_values.get("Standing Panel Convocation Approval", "No"),
                definitions.get("Standing Panel Convocation Approval"),
                errors,
            )

    return errors


def shared_source_reference_errors(
    sow: dict[str, list[str]],
    project_root: Path,
    unambiguous_sections: frozenset[str] | None = None,
) -> list[str]:
    shared_specs = {
        spec.section_key: spec
        for spec in contract_model.SOW_LABELED_FIELD_SPECS
        if spec.semantic_owner == "shared-source-reference"
    }
    source_pack_spec = shared_specs["source_packs"]
    source_update_spec = shared_specs["source_update"]
    source_pack_title = contract_model.sow_section_title(
        source_pack_spec.section_key
    )
    source_update_title = contract_model.sow_section_title(
        source_update_spec.section_key
    )
    source_pack_lines = sow.get(source_pack_title)
    source_update_lines = sow.get(source_update_title)
    if source_pack_lines is None and source_update_lines is None:
        return []
    errors: list[str] = []
    if source_pack_lines is None:
        return [
            f"STATEMENT_OF_WORK.md {source_update_title} requires a "
            f"{source_pack_title} section"
        ]
    if (
        unambiguous_sections is not None
        and source_pack_title not in unambiguous_sections
    ):
        return []
    source_pack_values = unambiguous_key_values(source_pack_lines)
    if source_pack_values is None:
        return []
    sow_reference = source_pack_values.get(source_pack_spec.label, "").strip()
    if not sow_reference:
        errors.append(
            f"STATEMENT_OF_WORK.md {source_pack_title} missing "
            f"{source_pack_spec.label}"
        )
    if source_update_lines is not None:
        update_values = (
            unambiguous_key_values(source_update_lines)
            if unambiguous_sections is None
            or source_update_title in unambiguous_sections
            else None
        )
        if update_values is not None:
            update_reference = update_values.get(
                source_update_spec.label,
                "",
            ).strip()
            if not update_reference:
                errors.append(
                    f"STATEMENT_OF_WORK.md {source_update_title} missing "
                    f"{source_update_spec.label}"
                )
            elif normalize(update_reference) != normalize(sow_reference):
                errors.append(
                    f"{source_pack_spec.label} drift between SOW "
                    f"{source_pack_title} and {source_update_title}"
                )

    source_pack_path = project_root / "SOURCE_PACKS.md"
    input_errors = safe_paths.bounded_input_errors(
        source_pack_path,
        project_root,
        description="SOURCE_PACKS.md input",
    )
    errors.extend(input_errors)
    if input_errors:
        return errors
    spelling_errors = safe_paths.exact_relative_path_spelling_errors(
        project_root,
        Path("SOURCE_PACKS.md"),
        description="Source Packs File (SOURCE_PACKS.md) input",
    )
    errors.extend(spelling_errors)
    if spelling_errors:
        return errors
    if not source_pack_path.is_file():
        errors.append("STATEMENT_OF_WORK.md Source Packs requires project SOURCE_PACKS.md")
        return errors
    try:
        source_pack_text = safe_paths.read_regular_file_bytes(
            source_pack_path,
            description="SOURCE_PACKS.md input",
        ).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        errors.append(f"SOURCE_PACKS.md could not be read safely: {exc}")
        return errors
    state_section_titles = [
        section.title for section in markdown_structure.markdown_sections(source_pack_text)
    ]
    blocked_sections, section_identity_errors = reserved_identity_errors(
        state_section_titles,
        {"Policy"},
        source="SOURCE_PACKS.md",
        kind="section",
    )
    errors.extend(section_identity_errors)
    if "Policy" in blocked_sections:
        return errors
    state_sections = markdown_sections(source_pack_text)
    policy_lines = state_sections.get("Policy", [])
    blocked_keys, key_identity_errors = reserved_identity_errors(
        key_names(policy_lines, bullet=True),
        {source_pack_spec.label},
        source="SOURCE_PACKS.md Policy",
        kind="key",
    )
    errors.extend(key_identity_errors)
    if source_pack_spec.label in blocked_keys:
        return errors
    policy_duplicates = key_value_duplicate_errors(
        "SOURCE_PACKS.md Policy",
        policy_lines,
        bullet=True,
    )
    errors.extend(policy_duplicates)
    if policy_duplicates:
        return errors
    state_reference = parse_key_values(policy_lines, bullet=True).get(
        source_pack_spec.label,
        "",
    ).strip()
    if not state_reference:
        errors.append(f"SOURCE_PACKS.md Policy missing {source_pack_spec.label}")
    elif normalize(state_reference) != normalize(sow_reference):
        errors.append(
            f"{source_pack_spec.label} drift between SOW {source_pack_title} "
            "and SOURCE_PACKS.md"
        )
    return errors


def read_project_state_sections(
    contract_root: Path,
    filename: str,
    *,
    reserved_sections: set[str],
) -> tuple[dict[str, list[str]] | None, set[str], list[str]]:
    path = contract_root / filename
    optional_spec = next(
        (
            spec
            for spec in contract_model.OPTIONAL_STATE_SPECS
            if spec.filename == filename
        ),
        None,
    )
    description = (
        f"{optional_spec.definition_label} ({filename}) input"
        if optional_spec is not None and optional_spec.definition_label is not None
        else f"{filename} input"
    )
    errors = safe_paths.bounded_input_errors(
        path,
        contract_root,
        description=description,
    )
    if errors:
        return None, set(), errors
    spelling_errors = safe_paths.exact_relative_path_spelling_errors(
        contract_root,
        Path(filename),
        description=description,
    )
    if spelling_errors:
        return None, set(), spelling_errors
    if not path.is_file():
        return None, set(), [f"missing project state file: {filename}"]
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=f"{filename} input",
        )
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, set(), [f"{filename} could not be read safely: {exc}"]
    exact_duplicates = duplicate_markdown_section_titles(text)
    observed_titles = [
        section.title for section in markdown_structure.markdown_sections(text)
    ]
    blocked, identity_errors = reserved_identity_errors(
        observed_titles,
        reserved_sections,
        source=filename,
        kind="section",
    )
    exact_errors = [
        f"{filename} duplicate section: {title}"
        for title in sorted(exact_duplicates)
    ]
    return (
        markdown_sections(text),
        exact_duplicates | blocked,
        list(dict.fromkeys([*exact_errors, *identity_errors])),
    )


def declared_optional_state_value_findings(
    definitions: dict[str, str],
    contract_root_ref: str,
) -> dict[str, str]:
    """Return exact optional-state Definition grammar failures by owner label."""

    findings: dict[str, str] = {}
    for definition_label, filename in contract_model.DECLARED_OPTIONAL_STATE.items():
        raw_value = definitions.get(definition_label, "").strip()
        rendered_filename = integration_registry.render_project_file_references(
            filename,
            contract_root_ref,
        )
        if raw_value not in {"none", rendered_filename}:
            findings[definition_label] = (
                f"STATEMENT_OF_WORK.md Definitions {definition_label} must be "
                f"either {rendered_filename} or none, not {raw_value!r}"
            )
    return findings


def declared_optional_state_errors(
    definitions: dict[str, str],
    contract_root: Path,
    contract_root_ref: str,
) -> list[str]:
    """Require every optional state file that the contract declares."""

    value_findings = declared_optional_state_value_findings(
        definitions,
        contract_root_ref,
    )
    errors = list(value_findings.values())
    for definition_label, filename in contract_model.DECLARED_OPTIONAL_STATE.items():
        if definition_label in value_findings:
            continue
        raw_value = definitions.get(definition_label, "").strip()
        if raw_value == "none":
            continue
        path = contract_root / filename
        boundary_errors = safe_paths.bounded_input_errors(
            path,
            contract_root,
            description=f"{definition_label} ({filename}) input",
        )
        if boundary_errors:
            errors.extend(
                f"{definition_label} declares {filename}: {error}"
                for error in boundary_errors
            )
            continue
        spelling_errors = safe_paths.exact_relative_path_spelling_errors(
            contract_root,
            Path(filename),
            description=f"{definition_label} ({filename}) input",
        )
        if spelling_errors:
            errors.extend(spelling_errors)
            continue
        if not path.is_file():
            errors.append(
                f"{definition_label} declares {filename}, but that project state file is missing"
            )
    return errors


def source_monitor_runtime_projection_errors(
    contract_root: Path,
    *,
    expected_runner: str,
    expected_framework_reference: str,
) -> list[str]:
    """Verify model-owned runner/reference projections in the monitor brief."""

    path = contract_root / "SOURCE_MONITOR_RESEARCHER.md"
    if (
        safe_paths.bounded_input_errors(
            path,
            contract_root,
            description="SOURCE_MONITOR_RESEARCHER.md input",
        )
        or safe_paths.exact_relative_path_spelling_errors(
            contract_root,
            Path("SOURCE_MONITOR_RESEARCHER.md"),
            description="SOURCE_MONITOR_RESEARCHER.md input",
        )
        or not path.is_file()
    ):
        # declared_optional_state_errors owns missing, unsafe, and inexact state
        # diagnostics; projection checks must not add derivative read failures.
        return []
    try:
        text = safe_paths.read_regular_file_bytes(
            path,
            description="SOURCE_MONITOR_RESEARCHER.md input",
        ).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [f"SOURCE_MONITOR_RESEARCHER.md could not be read safely: {exc}"]

    errors: list[str] = []
    actual_lines = text.splitlines()
    expected_reference_lines = (
        contract_model.source_monitor_framework_reference_lines(
            expected_framework_reference,
        )
    )
    if any(actual_lines.count(line) != 1 for line in expected_reference_lines):
        errors.append(
            "SOURCE_MONITOR_RESEARCHER.md model-owned framework-reference "
            "projection does not exactly match AGENT_PROJECT.md Framework reference"
        )

    expected_command = contract_model.source_monitor_artifact_lint_command(
        expected_runner,
        expected_framework_reference,
    )
    bash_blocks = re.findall(r"(?ms)^```bash\n(.*?)\n```$", text)
    if bash_blocks != [expected_command]:
        errors.append(
            "SOURCE_MONITOR_RESEARCHER.md strict monitor command does not "
            "exactly match the SOW Framework Verification Runner and "
            "AGENT_PROJECT.md Framework reference"
        )
    return errors


def state_projection_parity_errors(
    sow: dict[str, list[str]],
    sow_definitions: dict[str, str],
    contract_definitions: dict[str, str],
    contract_root: Path,
    unambiguous_sow_sections: frozenset[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    projections: dict[
        tuple[str, str],
        list[contract_model.StateDefinitionProjectionSpec],
    ] = {}
    for projection in contract_model.STATE_DEFINITION_PROJECTION_SPECS:
        key = (
            contract_model.sow_section_title(projection.sow_section_key),
            projection.filename,
        )
        projections.setdefault(key, []).append(projection)
    for (owning_section, filename), fields in projections.items():
        if owning_section not in sow:
            continue
        if (
            unambiguous_sow_sections is not None
            and owning_section not in unambiguous_sow_sections
        ):
            continue
        reserved_sections = {field.state_section for field in fields}
        state_sections, duplicate_state_sections, read_errors = read_project_state_sections(
            contract_root,
            filename,
            reserved_sections=reserved_sections,
        )
        errors.extend(read_errors)
        if state_sections is None:
            continue
        for field in fields:
            state_section = field.state_section
            state_key = field.state_key
            definition_key = field.definition_label
            if state_section in duplicate_state_sections:
                continue
            state_lines = state_sections.get(state_section, [])
            blocked_keys, key_identity_errors = reserved_identity_errors(
                key_names(state_lines, bullet=True),
                {state_key},
                source=f"{filename} {state_section}",
                kind="key",
            )
            for identity_error in key_identity_errors:
                if identity_error not in errors:
                    errors.append(identity_error)
            if state_key in blocked_keys:
                continue
            state_duplicate_errors = key_value_duplicate_errors(
                f"{filename} {state_section}",
                state_lines,
                bullet=True,
            )
            for duplicate_error in state_duplicate_errors:
                if duplicate_error not in errors:
                    errors.append(duplicate_error)
            if state_duplicate_errors:
                continue
            state_value = parse_key_values(state_lines, bullet=True).get(state_key)
            compare_value(
                f"{filename} {state_section} {state_key}",
                sow_definitions.get(definition_key),
                state_value,
                errors,
            )
            definition_spec = contract_model.DEFINITIONS_BY_LABEL[definition_key]
            if contract_model.runtime_definition_included(
                definition_spec,
                sow_definitions.get(definition_key),
                active_when_enabled=contract_model.runtime_definition_activation_enabled(
                    definition_spec,
                    sow_definitions,
                ),
            ):
                compare_value(
                    f"{filename} {state_section} {state_key} contract projection",
                    contract_definitions.get(definition_key),
                    state_value,
                    errors,
                )
    return errors


def automation_projection_parity_errors(
    sow: dict[str, list[str]],
    contract_root: Path,
    contract_root_ref: str = ".",
    *,
    compare_projection: bool = True,
) -> list[str]:
    manifest_path = contract_root / "AUTOMATION_ORDERS.json"
    errors = safe_paths.bounded_input_errors(
        manifest_path,
        contract_root,
        description="AUTOMATION_ORDERS.json input",
    )
    if errors:
        return errors
    try:
        payload = safe_paths.loads_json_no_duplicates(
            safe_paths.read_regular_file_bytes(
                manifest_path,
                description="AUTOMATION_ORDERS.json input",
            ).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"AUTOMATION_ORDERS.json could not be read safely: {exc}"]
    if not isinstance(payload, dict):
        return ["AUTOMATION_ORDERS.json must contain a JSON object"]
    preferred_backend = payload.get("preferred_backend")
    if not isinstance(preferred_backend, str) or not preferred_backend:
        errors.append("AUTOMATION_ORDERS.json missing preferred_backend")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        errors.append("AUTOMATION_ORDERS.json jobs must be a list of objects")
        return errors
    if not compare_projection:
        return errors

    section = sow.get("Standing Automation Orders")
    if section is None:
        return errors
    values = parse_key_values(section)
    if not present(values.get("Automation Orders File")):
        return errors
    sow_backend = values.get("Preferred Scheduler Backend")
    if not present(sow_backend):
        errors.append(
            "STATEMENT_OF_WORK.md Standing Automation Orders missing Preferred Scheduler Backend"
        )
    compare_value(
        "AUTOMATION_ORDERS.json preferred_backend",
        sow_backend,
        preferred_backend if isinstance(preferred_backend, str) else None,
        errors,
    )
    expected_job_rows = [
        integration_registry.render_project_file_references(
            contract_model.render_automation_job_summary(job),
            contract_root_ref,
        )
        for job in jobs
        if isinstance(job, dict)
    ]
    rendered_policy_lines = {
        integration_registry.render_project_file_references(
            policy_line,
            contract_root_ref,
        )
        for policy_line in contract_model.sow_section_policy_lines("automation")
    }
    scalar_labels = set(
        contract_model.sow_blueprint_labeled_row_labels("automation")
    )
    actual_job_rows: list[str] = []
    for raw in section:
        if not raw or raw in rendered_policy_lines:
            continue
        parsed = _exact_sow_scalar_row(raw)
        if parsed is not None and parsed[0] in scalar_labels:
            continue
        actual_job_rows.append(raw)
    if actual_job_rows != expected_job_rows:
        errors.append(
            "Standing Automation Orders job summaries do not exactly match "
            "AUTOMATION_ORDERS.json jobs"
        )
    return errors


def inline_security_policy_errors(
    sow: dict[str, list[str]],
    contract: dict[str, list[str]],
    sow_definitions: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    inline_selected = normalize(sow_definitions.get("Security Policy File", "")) == normalize(
        "inline in this SOW"
    )
    sow_terms = {normalize(item) for item in parse_bullets(sow.get("Security Policy", []))}
    contract_terms = {
        normalize(item) for item in parse_bullets(contract.get("Security Policy", []))
    }
    if inline_selected and not sow_terms:
        errors.append(
            "STATEMENT_OF_WORK.md inline Security Policy File requires a nonempty Security Policy section"
        )
    if not inline_selected and (sow_terms or contract_terms):
        errors.append(
            "Security Policy section is permitted only when Security Policy File is inline in this SOW"
        )
    if sow_terms != contract_terms:
        errors.append("Security Policy drift between SOW and project contract")
    return errors


def indexed_choice(value: str | None) -> str:
    return (value or "").split(" (", 1)[0].strip()


def definition_value_findings(definitions: dict[str, str]) -> dict[str, str]:
    """Return model-owned semantic Definition failures keyed by their owner fact."""

    findings: dict[str, str] = {}
    checks = (
        ("Bootstrap Mode", contract_model.BOOTSTRAP_MODES, False),
        ("Execution Mode", contract_model.EXECUTION_POSTURES, True),
        ("Dependency Rule", contract_model.DEPENDENCY_POSTURES, True),
        ("Security Policy File", contract_model.SECURITY_POLICY_FILES, False),
        (
            "Independent Assessment Approval",
            contract_model.INDEPENDENT_ASSESSMENT_APPROVALS,
            False,
        ),
        (
            "Arbitration Panel",
            {"framework default", "custom package; consult SOW Arbitration Panel"},
            False,
        ),
    )
    for key, allowed, has_explanatory_suffix in checks:
        raw = definitions.get(key, "")
        value = indexed_choice(raw) if has_explanatory_suffix else raw.strip()
        normalized_allowed = {normalize(item) for item in allowed}
        if normalize(value) not in normalized_allowed:
            findings[key] = (
                f"STATEMENT_OF_WORK.md Definitions {key} has invalid value: "
                f"{raw!r}; expected one of {', '.join(sorted(allowed))}"
            )
    standing_panel = definitions.get("Standing Panel Convocation Approval", "").strip()
    if not (
        standing_panel in {"No", "Yes"}
        or standing_panel.startswith("Yes,")
    ):
        findings["Standing Panel Convocation Approval"] = (
            "STATEMENT_OF_WORK.md Definitions Standing Panel Convocation Approval "
            "must be 'No', 'Yes', or start with 'Yes,'"
        )
    return findings


def definition_value_errors(definitions: dict[str, str]) -> list[str]:
    return list(definition_value_findings(definitions).values())


def reserved_identity_errors(
    observed: list[str],
    reserved: set[str],
    *,
    source: str,
    kind: str,
) -> tuple[set[str], list[str]]:
    """Reject aliases or collisions for model-owned structural identities."""

    canonical_by_identity: dict[str, str] = {}
    for canonical in reserved:
        identity = normalized_authority_identity(canonical)
        existing = canonical_by_identity.get(identity)
        if existing is not None and existing != canonical:
            raise ValueError(
                "model-owned authority identities normalize to the same value: "
                f"{existing!r}, {canonical!r}"
            )
        canonical_by_identity[identity] = canonical

    grouped: dict[str, list[str]] = {}
    for candidate in observed:
        identity = normalized_authority_identity(candidate)
        if identity in canonical_by_identity:
            grouped.setdefault(identity, []).append(candidate)

    blocked: set[str] = set()
    errors: list[str] = []
    for identity, candidates in sorted(grouped.items()):
        canonical = canonical_by_identity[identity]
        if len(candidates) > 1:
            blocked.add(canonical)
            errors.append(f"{source} duplicate {kind}: {canonical}")
        elif candidates[0] != canonical:
            blocked.add(canonical)
            errors.append(
                f"{source} {kind} must use exact model-owned identity: "
                f"{candidates[0]!r}; expected {canonical!r}"
            )
    return blocked, errors


def key_names(lines: list[str], *, bullet: bool = False) -> list[str]:
    """Return scalar-key spellings without assigning their values authority."""

    names: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        if bullet and stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if ":" in stripped:
            key, _value = stripped.split(":", 1)
            names.append(key.strip())
    return names


def duplicate_markdown_section_titles(text: str) -> set[str]:
    duplicates: set[str] = set()
    seen: set[str] = set()
    for section in markdown_structure.markdown_sections(text):
        heading = section.title
        if heading in seen:
            duplicates.add(heading)
        seen.add(heading)
    return duplicates


def duplicate_markdown_section_errors(text: str, source: str) -> list[str]:
    return [
        f"{source} duplicate section: {heading}"
        for heading in sorted(duplicate_markdown_section_titles(text))
    ]


def duplicate_plain_section_titles(text: str, titles: set[str]) -> set[str]:
    duplicates: set[str] = set()
    seen: set[str] = set()
    for _line_number, raw in markdown_structure.operative_lines(text):
        stripped = raw.strip()
        if raw.lstrip() == raw and stripped in titles:
            if stripped in seen:
                duplicates.add(stripped)
            seen.add(stripped)
    return duplicates


def duplicate_plain_section_errors(text: str, titles: set[str], source: str) -> list[str]:
    return [
        f"{source} duplicate section: {title}"
        for title in sorted(duplicate_plain_section_titles(text, titles))
    ]


def duplicate_key_names(lines: list[str], bullet: bool = False) -> set[str]:
    duplicates: set[str] = set()
    seen: set[str] = set()
    for key in key_names(lines, bullet=bullet):
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def key_value_duplicate_errors(source: str, lines: list[str], bullet: bool = False) -> list[str]:
    return [
        f"{source} duplicate key: {key}"
        for key in sorted(duplicate_key_names(lines, bullet=bullet))
    ]


def technical_spec_key_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for raw in lines:
        if raw.strip() == "File structure:":
            break
        result.append(raw)
    return result


def parse_bullets(lines: list[str]) -> list[str]:
    return [raw.strip()[2:] for raw in lines if raw.strip().startswith("- ")]


SCOPE_LABELS = ("In scope:", "Out of scope:")


def scope_grammar_errors(source: str, lines: list[str]) -> list[str]:
    """Validate the closed generated scope-section grammar."""

    errors: list[str] = []
    candidate_indexes: dict[str, list[int]] = {
        label: [
            index
            for index, raw in enumerate(lines, start=1)
            if raw.strip().casefold() == label.casefold()
        ]
        for label in SCOPE_LABELS
    }
    exact_indexes: dict[str, list[int]] = {
        label: [
            index
            for index, raw in enumerate(lines, start=1)
            if raw == label
        ]
        for label in SCOPE_LABELS
    }

    labels_valid = True
    for label in SCOPE_LABELS:
        candidates = candidate_indexes[label]
        exact = exact_indexes[label]
        if len(candidates) != 1:
            labels_valid = False
            errors.append(
                f"{source} must contain exactly one {label!r} label; "
                f"found {len(candidates)}"
            )
        elif len(exact) != 1:
            labels_valid = False
            observed = lines[candidates[0] - 1]
            errors.append(
                f"{source} label must be exactly {label!r}, not {observed!r}"
            )

    candidate_rows = {
        index
        for indexes in candidate_indexes.values()
        for index in indexes
    }
    for index, raw in enumerate(lines, start=1):
        if not raw.strip() or index in candidate_rows:
            continue
        if raw == "-" or raw.startswith("- "):
            if not raw[1:].strip():
                errors.append(
                    f"{source} row {index} must contain a nonempty scope bullet"
                )
            continue
        errors.append(
            f"{source} row {index} is unsupported; expected an exact scope label "
            f"or nonempty '- ' bullet row: {raw!r}"
        )

    if not labels_valid:
        return errors

    in_scope_index = exact_indexes["In scope:"][0]
    out_of_scope_index = exact_indexes["Out of scope:"][0]
    if in_scope_index >= out_of_scope_index:
        errors.append(
            f"{source} labels must appear in order: 'In scope:' followed by "
            "'Out of scope:'"
        )
        return errors

    bullet_counts = {label: 0 for label in SCOPE_LABELS}
    current: str | None = None
    for index, raw in enumerate(lines, start=1):
        if raw in SCOPE_LABELS:
            current = raw
            continue
        if not (raw == "-" or raw.startswith("- ")):
            continue
        if not raw[1:].strip():
            continue
        if current is None:
            errors.append(
                f"{source} row {index} is a scope bullet before 'In scope:'"
            )
            continue
        bullet_counts[current] += 1

    for label in SCOPE_LABELS:
        if bullet_counts[label] == 0:
            errors.append(
                f"{source} {label!r} must have at least one nonempty bullet row"
            )
    return errors


def parse_scope(lines: list[str]) -> dict[str, list[str]]:
    result = {"In scope": [], "Out of scope": []}
    current: str | None = None
    for raw in lines:
        if raw == "In scope:":
            current = "In scope"
            continue
        if raw == "Out of scope:":
            current = "Out of scope"
            continue
        if current and raw.startswith("- ") and raw[2:].strip():
            result[current].append(raw[2:].strip())
    return result


def parse_entries(lines: list[str], bullet: bool = False) -> list[str]:
    result: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_") or stripped == "Examples:":
            continue
        if bullet and stripped.startswith("- "):
            stripped = stripped[2:]
        result.append(stripped)
    return result


def _normalized_identity_collision_errors(
    source: str,
    field: str,
    identities: list[tuple[int, str]],
) -> list[str]:
    """Report collisions only for identities parsed by an owning surface."""

    seen: dict[str, tuple[int, str]] = {}
    errors: list[str] = []
    for index, identity in identities:
        normalized = contract_model.normalized_contract_identity(identity)
        prior = seen.get(normalized)
        if prior is None:
            seen[normalized] = (index, identity)
            continue
        prior_index, prior_identity = prior
        errors.append(
            f"{source} item {index} duplicates normalized {field} identity from "
            f"item {prior_index}: {identity!r} conflicts with {prior_identity!r}"
        )
    return errors


def rendered_workflow_identity_errors(source: str, entries: list[str]) -> list[str]:
    """Parse and validate the model-owned workflow-name identity grammar."""

    delimiter = contract_model.STRUCTURED_IDENTITY_DELIMITERS["workflows"]
    identities: list[tuple[int, str]] = []
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        identity, separator, _detail = entry.partition(delimiter)
        if not separator or not identity.strip():
            errors.append(
                f"{source} item {index} must contain a non-empty workflow name "
                f"before {delimiter!r}"
            )
            continue
        identities.append((index, identity.strip()))
    errors.extend(_normalized_identity_collision_errors(source, "name", identities))
    return errors


def rendered_command_restriction_identity_errors(
    source: str,
    entries: list[str],
) -> list[str]:
    """Parse and validate the model-owned restricted-command identity grammar."""

    delimiter = contract_model.STRUCTURED_IDENTITY_DELIMITERS[
        "command_restrictions"
    ]
    identities: list[tuple[int, str]] = []
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        identity, separator, _detail = entry.partition(delimiter)
        if not separator or not identity.strip():
            errors.append(
                f"{source} item {index} must contain a non-empty command before "
                f"{delimiter!r}"
            )
            continue
        identities.append((index, identity.strip()))
    errors.extend(_normalized_identity_collision_errors(source, "command", identities))
    return errors


def rendered_auxiliary_tool_identity_errors(
    source: str,
    entries: list[str],
) -> list[str]:
    """Parse and validate the model-owned auxiliary-tool-name identity grammar."""

    delimiter = contract_model.STRUCTURED_IDENTITY_DELIMITERS["auxiliary_tools"]
    identities: list[tuple[int, str]] = []
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        identity, separator, _detail = entry.partition(delimiter)
        if not separator or not identity.strip():
            errors.append(
                f"{source} item {index} must contain a non-empty auxiliary-tool name "
                f"before {delimiter!r}"
            )
            continue
        identities.append((index, identity.strip()))
    errors.extend(_normalized_identity_collision_errors(source, "name", identities))
    return errors


def parse_numbered(lines: list[str]) -> list[str]:
    result: list[str] = []
    for raw in lines:
        match = re.match(r"^\d+\.\s+(.*)$", raw.strip())
        if not match:
            continue
        result.append(match.group(1).strip())
    return result


def canonical_minimal_deliverables(items: list[str]) -> list[str]:
    result: list[str] = []
    replacements = tuple(
        contract_model.MINIMAL_DELIVERABLE_VALUES_BY_KEY[spec.key]
        for spec in contract_model.structured_field_specs("deliverables")
    )
    for item in items:
        parts = [part.strip() for part in item.rsplit(" — ", 2)]
        if len(parts) != 3:
            result.append(item)
            continue
        result.append(
            " — ".join(
                replacement if unresolved_full_value(part) else part
                for part, replacement in zip(parts, replacements, strict=True)
            )
        )
    return result


def numbered_section_needs_deferral(lines: list[str], separator: str, min_parts: int) -> bool:
    matched = False
    for raw in lines:
        match = re.match(r"^\d+\.\s+(.*)$", raw.strip())
        if not match:
            continue
        matched = True
        parts = [part.strip() for part in match.group(1).rsplit(separator, maxsplit=min_parts - 1)]
        if len(parts) < min_parts or any(absent_or_deferred(part) for part in parts[:min_parts]):
            return True
    return not matched


def parse_commands(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        separator = " — " if " — " in stripped else " - "
        if separator not in stripped:
            continue
        command, label = stripped.rsplit(separator, 1)
        result[label.strip()] = command.strip()
    return result


def sow_command_row_errors(
    lines: list[str],
    *,
    require_all: bool = True,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    expected_labels = set(COMMON_COMMAND_LABELS)
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        separator = " — " if " — " in stripped else " - "
        if separator not in stripped:
            errors.append(f"STATEMENT_OF_WORK.md Build and Development Commands row must contain a command separator: {stripped!r}")
            continue
        _, label = stripped.rsplit(separator, 1)
        label = label.strip()
        if label in seen:
            errors.append(f"STATEMENT_OF_WORK.md Build and Development Commands duplicate label: {label}")
        seen.add(label)
    if require_all:
        for label in sorted(expected_labels - seen):
            errors.append(
                "STATEMENT_OF_WORK.md Build and Development Commands "
                f"missing required label: {label}"
            )
    for label in sorted(seen - expected_labels):
        errors.append(f"STATEMENT_OF_WORK.md Build and Development Commands contains unbacked label: {label}")
    return errors


def parse_tool_entries(lines: list[str], bullet: bool = False) -> list[str]:
    result: list[str] = []
    for raw in lines:
        continuation = bool(raw[:1].isspace())
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if match:
            stripped = match.group(1)
            continuation = False
        elif bullet and stripped.startswith("- "):
            stripped = stripped[2:]
            continuation = False
        if continuation and result:
            result[-1] = f"{result[-1]} {stripped.lstrip('- ')}"
        else:
            result.append(stripped)
    return result


AUXILIARY_TOOL_RENDERED_LABELS = {
    normalize(label): key
    for label, key in contract_model.structured_labeled_field_map(
        "auxiliary_tools"
    ).items()
}
WORKFLOW_RENDERED_LABELS = {
    normalize(label): key
    for label, key in contract_model.structured_labeled_field_map(
        "workflows"
    ).items()
    if key not in {"sequence"}
}


def parsed_auxiliary_tool_facts(entry: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for segment in entry.split(" — "):
        label, separator, value = segment.partition(":")
        if not separator:
            continue
        field = AUXILIARY_TOOL_RENDERED_LABELS.get(normalize(label))
        if field is not None and value.strip():
            facts[field] = value.strip()
    return facts


def auxiliary_tool_fact_errors(source: str, entries: list[str]) -> list[str]:
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        facts = parsed_auxiliary_tool_facts(entry)
        missing = contract_model.missing_auxiliary_tool_fact_groups(facts)
        if missing:
            errors.append(
                f"{source} Auxiliary Tools item {index} is missing protocol-neutral "
                f"integration facts: {', '.join(missing)}"
            )
        errors.extend(
            f"{source} Auxiliary Tools item {index} {error}"
            for error in contract_model.auxiliary_tool_control_errors(facts)
        )
    return errors


def parsed_sow_workflow(
    entry: str,
    *,
    source: str,
    index: int,
) -> tuple[dict[str, str] | None, list[str]]:
    """Parse the format-2 canonical workflow row into route-relevant facts."""

    segments = entry.split(" — ")
    first = segments[0] if segments else ""
    name, separator, sequence_part = first.partition(":")
    errors: list[str] = []
    if not separator or not name.strip() or not sequence_part.startswith(" sequence: "):
        return None, [
            f"{source} item {index} must use 'name: sequence: ... — when: ...'"
        ]
    sequence = sequence_part.removeprefix(" sequence: ").strip()
    if not sequence:
        errors.append(f"{source} item {index} has an empty sequence")
    item: dict[str, str] = {"name": name.strip(), "sequence": sequence}
    for segment in segments[1:]:
        label, delimiter, value = segment.partition(":")
        normalized_label = normalize(label)
        key = WORKFLOW_RENDERED_LABELS.get(normalized_label)
        if not delimiter or key is None or not value.strip():
            errors.append(
                f"{source} item {index} has malformed or unknown workflow segment: {segment!r}"
            )
            continue
        if key in item:
            errors.append(
                f"{source} item {index} repeats workflow field: {normalized_label}"
            )
            continue
        item[key] = value.strip()
    if not item.get("when"):
        errors.append(f"{source} item {index} is missing workflow field: when")
    return (item if not errors else None), errors


def runtime_workflow_routes(
    source: str,
    entries: list[str],
    *,
    contract_root_ref: str = ".",
) -> tuple[list[str], list[str]]:
    routes: list[str] = []
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        item, item_errors = parsed_sow_workflow(
            entry,
            source=source,
            index=index,
        )
        errors.extend(item_errors)
        if item is not None:
            routes.append(
                integration_registry.render_project_file_references(
                    contract_model.render_runtime_workflow_route(item),
                    contract_root_ref,
                )
            )
    return routes, errors


def parsed_sow_auxiliary_tool(
    entry: str,
    *,
    source: str,
    index: int,
) -> tuple[dict[str, str] | None, list[str]]:
    """Parse one full canonical tool record before deriving its runtime index."""

    segments = entry.split(" — ")
    if len(segments) < 2 or not segments[0].strip() or not segments[1].strip():
        return None, [
            f"{source} item {index} must contain a non-empty name and purpose"
        ]
    item: dict[str, str] = {
        "name": segments[0].strip(),
        "purpose": segments[1].strip(),
    }
    errors: list[str] = []
    for segment in segments[2:]:
        label, delimiter, value = segment.partition(":")
        normalized_label = normalize(label)
        key = AUXILIARY_TOOL_RENDERED_LABELS.get(normalized_label)
        if not delimiter or key is None or not value.strip():
            errors.append(
                f"{source} item {index} has malformed or unknown auxiliary-tool segment: {segment!r}"
            )
            continue
        if key in item:
            errors.append(
                f"{source} item {index} repeats auxiliary-tool field: {normalized_label}"
            )
            continue
        item[key] = value.strip()
    return (item if not errors else None), errors


def runtime_auxiliary_tool_routes(
    source: str,
    entries: list[str],
    *,
    contract_root_ref: str = ".",
) -> tuple[list[str], list[str]]:
    routes: list[str] = []
    errors: list[str] = []
    for index, entry in enumerate(entries, start=1):
        item, item_errors = parsed_sow_auxiliary_tool(
            entry,
            source=source,
            index=index,
        )
        errors.extend(item_errors)
        if item is not None:
            routes.append(
                integration_registry.render_project_file_references(
                    contract_model.render_runtime_auxiliary_tool_route(item),
                    contract_root_ref,
                )
            )
    return routes, errors


def present(value: str | None) -> bool:
    return normalize(value or "") not in ABSENT_VALUES


def absent_or_deferred(value: str | None) -> bool:
    return (
        normalize(value or "") in ABSENT_VALUES
        or contract_model.is_deferred_value(value)
    )


def command_requires_deferral(value: str | None) -> bool:
    normalized = normalize(value or "")
    return (
        normalized in {"", "tbd", normalize(contract_model.MINIMAL_COMMAND_DEFERRAL)}
        or contract_model.is_deferred_value(value)
    )


def unresolved_full_value(value: str | None) -> bool:
    return (
        normalize(value or "") in {"", "tbd"}
        or contract_model.is_deferred_value(value)
    )


def full_mode_semantic_errors(
    sow: dict[str, list[str]],
    definitions: dict[str, str],
    technical_specs: dict[str, str],
    scope: dict[str, list[str]],
    commands: dict[str, str],
    *,
    check_definitions: bool = True,
    check_technical_specs: bool = True,
    check_scope: bool = True,
    check_commands: bool = True,
) -> list[str]:
    errors: list[str] = []
    recitals = parse_entries(sow.get("Recitals", []))
    if not recitals or any(unresolved_full_value(item) for item in recitals):
        errors.append("STATEMENT_OF_WORK.md full bootstrap requires concrete Recitals")
    if check_technical_specs:
        for key in ("Tech stack", "Architecture"):
            if unresolved_full_value(technical_specs.get(key)):
                errors.append(
                    f"STATEMENT_OF_WORK.md full bootstrap requires concrete Technical Specifications {key}"
                )
    if check_definitions and unresolved_full_value(
        definitions.get("Language/Runtime Standards")
    ):
        errors.append(
            "STATEMENT_OF_WORK.md full bootstrap requires concrete Language/Runtime Standards"
        )
    if check_scope:
        for label in ("In scope", "Out of scope"):
            values = scope[label]
            if not values or any(unresolved_full_value(item) for item in values):
                errors.append(f"STATEMENT_OF_WORK.md full bootstrap requires concrete {label} entries")
    if check_commands:
        for label in sorted(COMMON_COMMAND_LABELS):
            if unresolved_full_value(commands.get(label)):
                errors.append(
                    "STATEMENT_OF_WORK.md full bootstrap requires an explicit "
                    f"{label} command; use 'none' when not applicable"
                )
    return errors


def is_minimal_runtime_deferral(label: str, value: str | None) -> bool:
    expected = MINIMAL_RUNTIME_DEFERRALS[label]
    return (value or "").strip() == expected


def parse_minimal_deferral(source: str, index: int, item: str) -> tuple[dict[str, str] | None, list[str]]:
    errors: list[str] = []
    match = MINIMAL_DEFERRAL_RE.fullmatch(item.strip())
    if not match:
        return None, [f"{source} Minimal Bootstrap Deferrals row {index} must match the canonical Field/Owner/Reason/Boundary Type/Closure Boundary format"]
    parsed = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
    for key in MINIMAL_DEFERRAL_KEYS:
        value = parsed[key]
        if not value:
            errors.append(f"{source} Minimal Bootstrap Deferrals row {index} {key} must not be blank")
        elif key in {"owner", "reason", "closure_boundary"} and contract_model.minimal_deferral_value_is_absent_or_placeholder(value):
            errors.append(
                f"{source} Minimal Bootstrap Deferrals row {index} {key} "
                "must be concrete, not absent or placeholder text"
            )
        elif contract_model.is_deferred_value(value):
            errors.append(f"{source} Minimal Bootstrap Deferrals row {index} {key} must not be placeholder text")
    field = parsed["field"]
    if field and field not in MINIMAL_DEFERRABLE_FIELDS:
        errors.append(f"{source} Minimal Bootstrap Deferrals row {index} field is not deferrable: {field}")
    boundary_type = parsed["boundary_type"]
    if boundary_type and boundary_type not in MINIMAL_DEFERRAL_BOUNDARY_TYPES:
        errors.append(
            f"{source} Minimal Bootstrap Deferrals row {index} boundary_type must be one of: "
            + ", ".join(sorted(MINIMAL_DEFERRAL_BOUNDARY_TYPES))
        )
    if (
        boundary_type in MINIMAL_DEFERRAL_BOUNDARY_TYPES
        and not contract_model.minimal_deferral_value_is_absent_or_placeholder(
            parsed["closure_boundary"]
        )
    ):
        boundary_error = contract_model.minimal_deferral_closure_boundary_error(
            boundary_type,
            parsed["closure_boundary"],
        )
        if boundary_error is not None:
            errors.append(
                f"{source} Minimal Bootstrap Deferrals row {index} {boundary_error}"
            )
    return parsed, errors


def minimal_deferral_records(source: str, lines: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    errors: list[str] = []
    records: dict[str, dict[str, str]] = {}
    for index, item in enumerate(parse_bullets(lines), start=1):
        parsed, row_errors = parse_minimal_deferral(source, index, item)
        errors.extend(row_errors)
        if parsed is None:
            continue
        field = parsed["field"]
        if field in records:
            errors.append(f"{source} Minimal Bootstrap Deferrals duplicates field: {field}")
        if row_errors:
            continue
        records[field] = parsed
    return records, errors


def minimal_deferral_errors(source: str, lines: list[str]) -> list[str]:
    return minimal_deferral_records(source, lines)[1]


def minimal_deferral_parity_errors(
    sow_records: dict[str, dict[str, str]],
    contract_records: dict[str, dict[str, str]],
) -> list[str]:
    errors: list[str] = []
    sow_fields = set(sow_records)
    contract_fields = set(contract_records)
    for field in sorted(sow_fields - contract_fields):
        errors.append(f"Minimal Bootstrap Deferrals missing from AGENT_PROJECT.md: {field}")
    for field in sorted(contract_fields - sow_fields):
        errors.append(f"Minimal Bootstrap Deferrals unbacked in AGENT_PROJECT.md: {field}")
    for field in sorted(sow_fields & contract_fields):
        for key in MINIMAL_DEFERRAL_KEYS:
            left = sow_records[field][key]
            right = contract_records[field][key]
            if left != right:
                errors.append(f"Minimal Bootstrap Deferrals drift for {field} {key}: SOW={left!r} contract={right!r}")
    return errors


def required_minimal_deferral_fields(
    sow_recitals: list[str],
    sow_defs: dict[str, str],
    sow_technical_specs: dict[str, str],
    contract_active_stack: dict[str, str],
    sow_scope: dict[str, list[str]],
    contract_scope: dict[str, list[str]],
    sow_commands: dict[str, str],
    contract_common_commands: dict[str, str],
    sow_deliverables_need_deferral: bool,
    contract_deliverables_need_deferral: bool,
) -> set[str]:
    required: set[str] = set()
    if (
        not sow_recitals
        or contract_model.MINIMAL_RECITALS_DEFERRAL in sow_recitals
        or any(unresolved_full_value(item) for item in sow_recitals)
    ):
        required.add("Recitals")
    if (
        unresolved_full_value(sow_defs.get("Language/Runtime Standards"))
        or unresolved_full_value(
            contract_active_stack.get("Language/Runtime Standards")
        )
        or is_minimal_runtime_deferral(
            "Language/Runtime Standards",
            contract_active_stack.get("Language/Runtime Standards"),
        )
    ):
        required.add("Language/Runtime Standards")
    if (
        unresolved_full_value(sow_technical_specs.get("Tech stack"))
        or unresolved_full_value(
            contract_active_stack.get("Languages and frameworks")
        )
        or is_minimal_runtime_deferral(
            "Languages and frameworks",
            contract_active_stack.get("Languages and frameworks"),
        )
    ):
        required.add("Tech stack")
    if (
        unresolved_full_value(sow_technical_specs.get("Architecture"))
        or unresolved_full_value(contract_active_stack.get("Architecture"))
        or is_minimal_runtime_deferral(
            "Architecture",
            contract_active_stack.get("Architecture"),
        )
    ):
        required.add("Architecture")
    for label in ("In scope", "Out of scope"):
        if (
            not sow_scope[label]
            or not contract_scope[label]
            or any(unresolved_full_value(item) for item in sow_scope[label])
            or any(unresolved_full_value(item) for item in contract_scope[label])
            or any(
                is_minimal_runtime_deferral(label, item)
                for item in contract_scope[label]
            )
        ):
            required.add(label)
    if sow_deliverables_need_deferral or contract_deliverables_need_deferral:
        required.add("Deliverables and Acceptance Evidence")
    for sow_label, contract_label in COMMON_COMMAND_LABELS.items():
        if command_requires_deferral(
            sow_commands.get(sow_label)
        ) or command_requires_deferral(
            contract_common_commands.get(contract_label)
        ):
            required.add(COMMAND_DEFERRAL_FIELDS[sow_label])
    return required


def minimal_deferral_required_field_errors(
    records: dict[str, dict[str, str]],
    required_fields: set[str],
) -> list[str]:
    errors = [
        f"Minimal Bootstrap Deferrals missing required deferred field: {field}"
        for field in sorted(required_fields - set(records))
    ]
    errors.extend(
        f"Minimal Bootstrap Deferrals contains resolved canonical field: {field}"
        for field in sorted(set(records) - required_fields)
    )
    return errors


def compare_value(label: str, left: str | None, right: str | None, errors: list[str]) -> None:
    if present(left) != present(right):
        errors.append(f"{label} drift: SOW={left!r} contract={right!r}")
        return
    if present(left) and normalize(left or "") != normalize(right or ""):
        errors.append(f"{label} drift: SOW={left!r} contract={right!r}")


def compare_exact_value(
    label: str,
    left: str | None,
    right: str | None,
    errors: list[str],
) -> None:
    """Compare identity scalars, allowing only structural absence -> exact ``none``."""

    if left == right:
        return
    if (left is None and right == "none") or (right is None and left == "none"):
        return
    if left != right:
        errors.append(f"{label} drift: SOW={left!r} contract={right!r}")


def exact_list_parity_errors(label: str, sow_items: list[str], contract_items: list[str]) -> list[str]:
    left = sorted(normalize(item) for item in sow_items)
    right = sorted(normalize(item) for item in contract_items)
    if left == right:
        return []
    return [f"{label} drift between SOW and project contract"]


def repeated_projection_parity_errors(
    label: str,
    sow_items: list[str],
    contract_items: list[str],
) -> list[str]:
    """Apply the model-owned order semantics for a repeated projection."""

    if label in contract_model.ORDERED_REPEATED_PROJECTIONS:
        left = [normalize(item) for item in sow_items]
        right = [normalize(item) for item in contract_items]
        if left == right:
            return []
        return [f"{label} drift between SOW and project contract"]
    return exact_list_parity_errors(label, sow_items, contract_items)


def command_warnings(label: str, command: str) -> list[str]:
    if not present(command):
        return []
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return [f"{label} is not shell-parseable: {exc}"]
    if any(token_has_absolute_path(token) for token in tokens):
        return [f"host-specific absolute path in {label}: {command!r}; prefer repo-local or relative commands when possible"]
    return []


def token_has_absolute_path(token: str) -> bool:
    return safe_paths.contains_absolute_path(token)


def common_command_row_errors(lines: list[str]) -> list[str]:
    errors: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("_"):
            continue
        if not stripped.startswith("- "):
            errors.append(f"AGENT_PROJECT.md Common Commands row must be a bullet key-value pair: {stripped!r}")
            continue
        payload = stripped[2:].strip()
        if ":" not in payload:
            errors.append(f"AGENT_PROJECT.md Common Commands row must contain ':': {stripped!r}")
            continue
        key, value = payload.split(":", 1)
        if not key.strip() or not value.strip():
            errors.append(
                "AGENT_PROJECT.md Common Commands row must contain a nonempty "
                f"key and command value: {stripped!r}"
            )
    return errors


def framework_verification_command_errors(
    lines: list[str],
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    expected_runner: str = contract_model.FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER,
) -> list[str]:
    errors = contract_model.framework_verification_runner_errors(
        expected_runner,
        "STATEMENT_OF_WORK.md Framework Verification Runner",
    )
    if errors:
        return errors

    errors.extend(
        key_value_duplicate_errors(
            "AGENT_PROJECT.md Framework Verification Commands",
            lines,
            bullet=True,
        )
    )
    if errors:
        return errors

    entries = parse_key_values(lines, bullet=True)
    missing_keys = FRAMEWORK_VERIFICATION_REQUIRED_KEYS - set(entries)
    for key in sorted(missing_keys):
        errors.append(f"AGENT_PROJECT.md Framework Verification Commands missing required key: {key}")
    if missing_keys:
        return errors

    if entries.get("Framework Verification Runner") != expected_runner:
        return [
            "AGENT_PROJECT.md Framework Verification Commands runner does not use "
            "the SOW Framework Verification Runner"
        ]

    framework_reference = entries.get("Framework reference", "")
    reference_errors = safe_paths.framework_reference_errors(framework_reference)
    errors.extend(
        "AGENT_PROJECT.md Framework reference: " + error
        for error in reference_errors
    )
    if reference_errors:
        return errors

    expected_lines = contract_model.framework_verification_command_lines(
        framework_reference,
        project_kind=project_kind,
        contract_root_ref=contract_root_ref,
        runner=expected_runner,
    )
    actual_lines = [line.strip() for line in lines if line.strip()]
    if any(
        re.search(
            r"(?:^|\s)scripts/(?:project_contract_sync|project_state_lint|conformance_check)\.py(?:\s|$)",
            entries.get(key, ""),
        )
        for key in ("Core conformance",)
    ):
        errors.append(
            "AGENT_PROJECT.md Framework Verification Commands must call the framework-owned script through the framework reference, not bare scripts/..."
        )
    if actual_lines != expected_lines:
        errors.append(
            "AGENT_PROJECT.md Framework Verification Commands does not exactly match "
            "the selected runner, declared framework reference, and project layout"
        )
    return errors


def internal_tracking_leaks(name: str, text: str) -> list[str]:
    if any(pattern.search(text) for pattern in INTERNAL_LOCAL_STATE_PATTERNS):
        return [f"{name} contains an internal local-state filename reference"]
    return []


@dataclass(frozen=True)
class SyncValidationContext:
    project_root: Path
    contract_root: Path
    contract_root_ref: str
    project_kind: str
    sow_text: str
    contract_text: str
    sow: dict[str, list[str]]
    contract: dict[str, list[str]]
    sow_defs: dict[str, str]
    contract_defs: dict[str, str]
    sow_technical_specs: dict[str, str]
    contract_active_stack: dict[str, str]
    sow_commands: dict[str, str]
    contract_common_commands: dict[str, str]
    sow_scope: dict[str, list[str]]
    contract_scope: dict[str, list[str]]
    sow_deliverables: list[str]
    contract_deliverables: list[str]
    sow_deliverables_need_deferral: bool
    contract_deliverables_need_deferral: bool


@dataclass(frozen=True)
class SyncValidationPrerequisites:
    valid_sow_row_grammar_sections: frozenset[str]
    valid_project_row_grammar_sections: frozenset[str]
    sow_definitions: bool
    invalid_sow_definition_value_keys: frozenset[str]
    contract_definitions: bool
    sow_technical_specs: bool
    contract_active_stack: bool
    sow_commands: bool
    contract_common_commands: bool
    sow_scope: bool
    contract_scope: bool
    sow_automation: bool
    sow_automation_projection_rows: bool
    automation_manifest_readable: bool
    framework_verification_commands: bool
    unambiguous_sow_scalar_sections: frozenset[str]
    bootstrap_mode: str | None


def sow_contract_control_syntax_errors(text: str) -> list[str]:
    """Reject parser-hidden controls and heading syntax absent from concrete SOWs."""

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number == 1 and line == contract_model.CONTRACT_FORMAT_MARKER:
            continue
        syntax_kind = contract_model.generated_sow_control_syntax_kind(line)
        if syntax_kind is not None:
            if syntax_kind == "HTML comment syntax":
                display_kind = "HTML comment content"
            elif syntax_kind == "Markdown fence":
                display_kind = "fenced Markdown"
            else:
                display_kind = f"{syntax_kind} syntax"
            return [
                f"STATEMENT_OF_WORK.md contains unsupported {display_kind} at line "
                f"{line_number}; generated SOW content must use the declared section "
                "row grammar"
            ]
    return []


def _exact_sow_scalar_row(raw: str) -> tuple[str, str] | None:
    if raw != raw.strip() or ": " not in raw:
        return None
    label, value = raw.split(": ", 1)
    if not label.strip() or label != label.strip() or not value.strip():
        return None
    return label, value


def _sow_policy_line_errors(
    title: str,
    lines: list[str],
    policy_lines: tuple[str, ...],
    *,
    contract_root_ref: str = ".",
) -> list[str]:
    errors: list[str] = []
    for policy_line in policy_lines:
        expected_policy_line = integration_registry.render_project_file_references(
            policy_line,
            contract_root_ref,
        )
        count = sum(raw == expected_policy_line for raw in lines)
        if count != 1:
            if policy_line == contract_model.AUTOMATION_AUTHORITY_RULE:
                errors.append(
                    "STATEMENT_OF_WORK.md Standing Automation Orders must contain "
                    "exactly one model-owned automation-authority boundary"
                )
                continue
            errors.append(
                f"STATEMENT_OF_WORK.md {title} must contain exactly one model-owned "
                f"policy line {expected_policy_line!r}; found {count}"
            )
    return errors


def _sow_labeled_row_errors(
    section_key: str,
    title: str,
    lines: list[str],
    *,
    contract_root_ref: str,
) -> list[str]:
    spec = contract_model.SOW_SECTIONS[section_key]
    allowed_labels = set(
        contract_model.sow_blueprint_labeled_row_labels(section_key)
    )
    rendered_policy_lines = tuple(
        integration_registry.render_project_file_references(line, contract_root_ref)
        for line in spec.policy_lines
    )
    errors = _sow_policy_line_errors(
        title,
        lines,
        spec.policy_lines,
        contract_root_ref=contract_root_ref,
    )
    seen_labels: Counter[str] = Counter()
    for index, raw in enumerate(lines, start=1):
        if not raw or raw in rendered_policy_lines:
            continue
        parsed = _exact_sow_scalar_row(raw)
        if parsed is None:
            candidate_label, separator, _candidate_value = raw.partition(":")
            recognized_label = candidate_label.strip()
            if separator and recognized_label in allowed_labels:
                seen_labels[recognized_label] += 1
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                f"model-owned labeled row or policy literal: {raw!r}"
            )
            continue
        label, _value = parsed
        if label not in allowed_labels:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} contains unbacked "
                f"scalar label: {label}"
            )
            continue
        seen_labels[label] += 1
    for label in sorted(allowed_labels):
        if seen_labels[label] == 0:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} missing required model-owned "
                f"scalar label: {label}"
            )
    return errors


def _sow_arbitration_row_errors(title: str, lines: list[str]) -> list[str]:
    labels = set(contract_model.sow_blueprint_labeled_row_labels("arbitration_panel"))
    required_labels = labels - {"Seat 1"}
    expected_seat = 1
    errors: list[str] = []
    for index, raw in enumerate(lines, start=1):
        if not raw:
            continue
        parsed = _exact_sow_scalar_row(raw)
        if parsed is None:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                f"model-owned arbitration scalar row: {raw!r}"
            )
            continue
        label, _value = parsed
        seat = re.fullmatch(r"Seat (?P<number>[1-9][0-9]*)", label)
        if seat is not None:
            number = int(seat.group("number"))
            if number != expected_seat:
                errors.append(
                    f"STATEMENT_OF_WORK.md {title} row {index} must use seat number "
                    f"{expected_seat}, not {number}"
                )
            expected_seat += 1
            continue
        if label not in required_labels:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} contains unbacked "
                f"scalar label: {label}"
            )
            continue
    if expected_seat == 1:
        errors.append(f"STATEMENT_OF_WORK.md {title} must define at least one seat")
    return errors


def _sow_technical_row_errors(title: str, lines: list[str]) -> list[str]:
    allowed_labels = set(
        contract_model.sow_blueprint_labeled_row_labels(
            "technical_specifications"
        )
    )
    sentinel_seen = False
    tail_has_content = False
    errors: list[str] = []
    for index, raw in enumerate(lines, start=1):
        if not raw:
            continue
        if sentinel_seen:
            tail_has_content = True
            continue
        if raw == "File structure:":
            sentinel_seen = True
            continue
        parsed = _exact_sow_scalar_row(raw)
        if parsed is None:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                "model-owned scalar row or the exact 'File structure:' sentinel: "
                f"{raw!r}"
            )
            continue
        label, _value = parsed
        if label not in allowed_labels:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} contains unbacked "
                f"scalar label: {label}"
            )
            continue
    if sentinel_seen and not tail_has_content:
        errors.append(
            f"STATEMENT_OF_WORK.md {title} exact 'File structure:' sentinel "
            "must be followed by at least one nonempty path row"
        )
    return errors


def _sow_numbered_row_errors(title: str, lines: list[str]) -> list[str]:
    errors: list[str] = []
    expected_number = 1
    for index, raw in enumerate(lines, start=1):
        if not raw:
            continue
        match = PROJECT_NUMBERED_ROW_RE.fullmatch(raw)
        if match is None:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                f"nonempty numbered row: {raw!r}"
            )
            continue
        number = int(match.group("number"))
        if number != expected_number:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must use item number "
                f"{expected_number}, not {number}"
            )
        expected_number += 1
    return errors


def _sow_command_row_grammar_errors(title: str, lines: list[str]) -> list[str]:
    expected_labels = {spec.sow_label for spec in contract_model.COMMAND_SPECS}
    errors: list[str] = []
    for index, raw in enumerate(lines, start=1):
        if not raw:
            continue
        if raw != raw.strip() or " — " not in raw:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must use the exact "
                f"'<command> — <model-owned label>' grammar: {raw!r}"
            )
            continue
        command, label = raw.rsplit(" — ", 1)
        if not command.strip() or label not in expected_labels:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} contains an empty "
                f"command or unbacked command label: {raw!r}"
            )
            continue
    return errors


def _sow_automation_projection_row_errors(
    title: str,
    lines: list[str],
    *,
    contract_root_ref: str,
) -> list[str]:
    spec = contract_model.SOW_SECTIONS["automation"]
    allowed_labels = set(contract_model.sow_blueprint_labeled_row_labels("automation"))
    rendered_policy_lines = tuple(
        integration_registry.render_project_file_references(line, contract_root_ref)
        for line in spec.policy_lines
    )
    errors: list[str] = []
    for index, raw in enumerate(lines, start=1):
        if not raw or raw in rendered_policy_lines:
            continue
        parsed = _exact_sow_scalar_row(raw)
        if parsed is None:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                f"automation scalar or manifest-owned job row: {raw!r}"
            )
            continue
        label, value = parsed
        if label in allowed_labels:
            continue
        fields = value.rsplit(" — ", 3)
        if (
            automation_orders_lint.JOB_ID_RE.fullmatch(label) is None
            or len(fields) != 4
            or any(not field.strip() for field in fields)
        ):
            errors.append(
                f"STATEMENT_OF_WORK.md {title} row {index} is neither a "
                f"model-owned scalar nor a canonical automation job summary: {raw!r}"
            )
    return errors


def _sow_automation_row_errors(
    title: str,
    lines: list[str],
    *,
    contract_root_ref: str,
) -> list[str]:
    spec = contract_model.SOW_SECTIONS["automation"]
    return [
        *_sow_policy_line_errors(
            title,
            lines,
            spec.policy_lines,
            contract_root_ref=contract_root_ref,
        ),
        *_sow_automation_projection_row_errors(
            title,
            lines,
            contract_root_ref=contract_root_ref,
        ),
    ]


def _sow_section_row_grammar_errors_by_title(
    sow: dict[str, list[str]],
    duplicate_sections: set[str],
    *,
    contract_root_ref: str = ".",
) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    definitions = sow.get("Definitions")
    if definitions is not None and "Definitions" not in duplicate_sections:
        definition_errors = _sow_policy_line_errors(
            "Definitions",
            definitions,
            (contract_model.SOW_DEFINITION_INDEX_RULE,),
            contract_root_ref=contract_root_ref,
        )
        allowed = {spec.label for spec in contract_model.SOW_DEFINITION_SPECS}
        for index, raw in enumerate(definitions, start=1):
            if not raw or raw == contract_model.SOW_DEFINITION_INDEX_RULE:
                continue
            parsed = _exact_sow_scalar_row(raw)
            if parsed is None:
                definition_errors.append(
                    "STATEMENT_OF_WORK.md Definitions row "
                    f"{index} must be an exact model-owned scalar row or the exact "
                    f"index policy literal: {raw!r}"
                )
                continue
            label, _value = parsed
            if label not in allowed:
                definition_errors.append(
                    "STATEMENT_OF_WORK.md Definitions row "
                    f"{index} contains unbacked scalar label: {label}"
                )
        if definition_errors:
            findings["Definitions"] = definition_errors

    for spec in contract_model.SOW_SECTION_SPECS:
        title = spec.title
        if title not in sow or title in duplicate_sections:
            continue
        lines = sow[title]
        if not any(raw for raw in lines):
            findings[title] = [
                f"STATEMENT_OF_WORK.md {title} must contain at least one concrete row"
            ]
            continue
        style = spec.sow_row_style
        errors: list[str] = []
        if style == "free-form":
            pass
        elif style == "bullet":
            for index, raw in enumerate(lines, start=1):
                if raw and (not raw.startswith("- ") or not raw[2:].strip()):
                    errors.append(
                        f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                        f"nonempty '- ' bullet: {raw!r}"
                    )
        elif style == "numbered":
            errors.extend(_sow_numbered_row_errors(title, lines))
        elif style == "scope":
            errors.extend(scope_grammar_errors(f"STATEMENT_OF_WORK.md {title}", lines))
        elif style == "labeled":
            errors.extend(
                _sow_labeled_row_errors(
                    spec.key,
                    title,
                    lines,
                    contract_root_ref=contract_root_ref,
                )
            )
        elif style == "arbitration-panel":
            errors.extend(_sow_arbitration_row_errors(title, lines))
        elif style == "direct-panel-rules":
            allowed_label = "Standing Panel Convocation Approval"
            for index, raw in enumerate(lines, start=1):
                if not raw:
                    continue
                if raw.startswith("- ") and raw[2:].strip():
                    continue
                parsed = _exact_sow_scalar_row(raw)
                if parsed is None or parsed[0] != allowed_label:
                    errors.append(
                        f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                        f"nonempty '- ' bullet or {allowed_label!r} scalar: {raw!r}"
                    )
        elif style == "technical-specifications":
            errors.extend(_sow_technical_row_errors(title, lines))
        elif style == "commands":
            errors.extend(_sow_command_row_grammar_errors(title, lines))
        elif style == "command-restrictions":
            delimiter = contract_model.STRUCTURED_IDENTITY_DELIMITERS[
                "command_restrictions"
            ]
            for index, raw in enumerate(lines, start=1):
                if not raw:
                    continue
                command, separator, remainder = raw.partition(delimiter)
                reason, second_separator, alternative = remainder.partition(" — use ")
                if (
                    raw != raw.strip()
                    or not separator
                    or not second_separator
                    or not command.strip()
                    or not reason.strip()
                    or not alternative.endswith(" instead")
                    or not alternative.removesuffix(" instead").strip()
                ):
                    errors.append(
                        f"STATEMENT_OF_WORK.md {title} row {index} must use the exact "
                        "model-owned command-restriction grammar: "
                        f"{raw!r}"
                    )
        elif style == "workflows":
            entries = [raw for raw in lines if raw]
            for index, raw in enumerate(entries, start=1):
                if raw != raw.strip():
                    errors.append(
                        f"STATEMENT_OF_WORK.md {title} item {index} must be unindented"
                    )
                    continue
                _parsed, row_errors = parsed_sow_workflow(
                    raw,
                    source=f"STATEMENT_OF_WORK.md {title}",
                    index=index,
                )
                errors.extend(row_errors)
        elif style == "automation":
            errors.extend(
                _sow_automation_row_errors(
                    title,
                    lines,
                    contract_root_ref=contract_root_ref,
                )
            )
        elif style == "policy-bullet":
            rendered_policy_lines = tuple(
                integration_registry.render_project_file_references(
                    line,
                    contract_root_ref,
                )
                for line in spec.policy_lines
            )
            errors.extend(
                _sow_policy_line_errors(
                    title,
                    lines,
                    spec.policy_lines,
                    contract_root_ref=contract_root_ref,
                )
            )
            for index, raw in enumerate(lines, start=1):
                if not raw or raw in rendered_policy_lines:
                    continue
                if not raw.startswith("- ") or not raw[2:].strip():
                    errors.append(
                        f"STATEMENT_OF_WORK.md {title} row {index} must be an exact "
                        f"model-owned policy literal or nonempty '- ' bullet: {raw!r}"
                    )
        else:
            errors.append(
                f"STATEMENT_OF_WORK.md {title} has no model-owned row grammar"
            )
        if errors:
            findings[title] = errors
    return findings


def sow_section_row_grammar_errors(
    sow: dict[str, list[str]],
    duplicate_sections: set[str],
    *,
    contract_root_ref: str = ".",
) -> list[str]:
    """Reject raw SOW rows that model-owned semantic parsers would ignore."""

    findings = _sow_section_row_grammar_errors_by_title(
        sow,
        duplicate_sections,
        contract_root_ref=contract_root_ref,
    )
    return [error for title in findings for error in findings[title]]


def _project_section_row_grammar_errors_by_title(
    contract: dict[str, list[str]],
    duplicate_sections: set[str],
) -> dict[str, list[str]]:
    """Return project row-grammar findings grouped by owning section."""

    findings: dict[str, list[str]] = {}
    for section_key, style in contract_model.PROJECT_SECTION_ROW_STYLES.items():
        title = contract_model.PROJECT_SECTIONS[section_key].title
        if title not in contract or title in duplicate_sections:
            continue
        if style == "scope":
            scope_errors = scope_grammar_errors(
                "AGENT_PROJECT.md Active Scope",
                contract[title],
            )
            if scope_errors:
                findings[title] = scope_errors
            continue
        errors: list[str] = []
        expected_number = 1
        for index, raw in enumerate(contract[title], start=1):
            if not raw:
                continue
            if style == "bullet":
                if not raw.startswith("- ") or not raw[2:].strip():
                    errors.append(
                        f"AGENT_PROJECT.md {title} row {index} must be an exact "
                        f"nonempty '- ' bullet: {raw!r}"
                    )
                continue
            match = PROJECT_NUMBERED_ROW_RE.fullmatch(raw)
            if match is None:
                errors.append(
                    f"AGENT_PROJECT.md {title} row {index} must be an exact "
                    f"nonempty numbered row: {raw!r}"
                )
                continue
            number = int(match.group("number"))
            if number != expected_number:
                errors.append(
                    f"AGENT_PROJECT.md {title} row {index} must use item number "
                    f"{expected_number}, not {number}"
                )
            expected_number += 1
        if errors:
            findings[title] = errors
    return findings


def project_section_row_grammar_errors(
    contract: dict[str, list[str]],
    duplicate_sections: set[str],
) -> list[str]:
    """Reject raw rows that the generated project-section parser would ignore."""

    findings = _project_section_row_grammar_errors_by_title(
        contract,
        duplicate_sections,
    )
    return [error for title in findings for error in findings[title]]


def generated_contract_fence_errors(text: str) -> list[str]:
    """Reject fenced blocks, which no concrete generated contract can contain."""

    visibility = markdown_structure.MarkdownVisibilityState()
    for line_number, line in enumerate(text.splitlines(), start=1):
        fence_event, _visible = visibility.consume(line)
        if fence_event is not None:
            return [
                "AGENT_PROJECT.md contains unsupported fenced Markdown at line "
                f"{line_number}; generated contract content must use the declared "
                "section row grammar"
            ]
    return []


def generated_contract_comment_errors(text: str) -> list[str]:
    """Permit only the exact line-one generated contract marker comment."""

    visibility = markdown_structure.MarkdownVisibilityState()
    for line_number, line in enumerate(text.splitlines(), start=1):
        fence_event, visible = visibility.consume(line)
        if fence_event is not None or visible is None or visible == line:
            continue
        if line_number == 1 and line == contract_model.CONTRACT_FORMAT_MARKER:
            continue
        return [
            "AGENT_PROJECT.md contains unsupported HTML comment content at line "
            f"{line_number}; only the exact line-one generated contract format "
            "marker comment is permitted"
        ]
    return []


def _validation_prerequisites(
    context: SyncValidationContext,
) -> SyncValidationPrerequisites:
    duplicate_sow_sections = duplicate_plain_section_titles(
        context.sow_text,
        SOW_TITLES,
    )
    duplicate_contract_sections = duplicate_markdown_section_titles(
        context.contract_text
    )
    sow_row_grammar_findings = _sow_section_row_grammar_errors_by_title(
        context.sow,
        duplicate_sow_sections,
        contract_root_ref=context.contract_root_ref,
    )
    valid_sow_row_grammar_sections = frozenset(
        title
        for title in context.sow
        if title not in duplicate_sow_sections
        and title not in sow_row_grammar_findings
    )
    project_row_grammar_findings = _project_section_row_grammar_errors_by_title(
        context.contract,
        duplicate_contract_sections,
    )
    active_stack_grammar_errors = active_stack_closed_row_errors(context)
    if active_stack_grammar_errors:
        project_row_grammar_findings.setdefault("Active Stack", []).extend(
            active_stack_grammar_errors
        )
    valid_project_row_grammar_sections = frozenset(
        title
        for title in context.contract
        if title not in duplicate_contract_sections
        and title not in project_row_grammar_findings
    )
    sow_definitions = (
        "Definitions" in context.sow
        and "Definitions" not in duplicate_sow_sections
        and "Definitions" in valid_sow_row_grammar_sections
        and not duplicate_key_names(context.sow.get("Definitions", []))
    )
    invalid_sow_definition_value_keys = (
        frozenset(
            {
                *definition_value_findings(context.sow_defs),
                *declared_optional_state_value_findings(
                    context.sow_defs,
                    context.contract_root_ref,
                ),
            }
        )
        if sow_definitions
        else frozenset()
    )
    contract_definitions = (
        "Definitions" in context.contract
        and "Definitions" not in duplicate_contract_sections
        and "Definitions" in valid_project_row_grammar_sections
        and not duplicate_key_names(
            context.contract.get("Definitions", []),
            bullet=True,
        )
    )
    sow_technical_specs = (
        "Technical Specifications" in context.sow
        and "Technical Specifications" not in duplicate_sow_sections
        and "Technical Specifications" in valid_sow_row_grammar_sections
        and not duplicate_key_names(
            technical_spec_key_lines(
                context.sow.get("Technical Specifications", [])
            )
        )
    )
    contract_active_stack = (
        "Active Stack" in context.contract
        and "Active Stack" not in duplicate_contract_sections
        and "Active Stack" in valid_project_row_grammar_sections
        and not duplicate_key_names(
            context.contract.get("Active Stack", []),
            bullet=True,
        )
    )
    sow_commands = (
        "Build and Development Commands" in context.sow
        and "Build and Development Commands" not in duplicate_sow_sections
        and "Build and Development Commands" in valid_sow_row_grammar_sections
        and not sow_command_row_errors(
            context.sow.get("Build and Development Commands", []),
            require_all=False,
        )
    )
    contract_common_commands = (
        "Common Commands" in context.contract
        and "Common Commands" not in duplicate_contract_sections
        and "Common Commands" in valid_project_row_grammar_sections
        and not duplicate_key_names(
            context.contract.get("Common Commands", []),
            bullet=True,
        )
        and not common_command_row_errors(
            context.contract.get("Common Commands", [])
        )
    )
    sow_scope = (
        "Scope" in context.sow
        and "Scope" not in duplicate_sow_sections
        and "Scope" in valid_sow_row_grammar_sections
        and not scope_grammar_errors(
            "STATEMENT_OF_WORK.md Scope",
            context.sow.get("Scope", []),
        )
    )
    contract_scope = (
        "Active Scope" in context.contract
        and "Active Scope" not in duplicate_contract_sections
        and "Active Scope" in valid_project_row_grammar_sections
        and not scope_grammar_errors(
            "AGENT_PROJECT.md Active Scope",
            context.contract.get("Active Scope", []),
        )
    )
    sow_automation = (
        "Standing Automation Orders" in context.sow
        and "Standing Automation Orders" not in duplicate_sow_sections
        and "Standing Automation Orders" in valid_sow_row_grammar_sections
        and not duplicate_key_names(
            context.sow.get("Standing Automation Orders", [])
        )
    )
    sow_automation_projection_rows = (
        "Standing Automation Orders" in context.sow
        and "Standing Automation Orders" not in duplicate_sow_sections
        and not duplicate_key_names(
            context.sow.get("Standing Automation Orders", [])
        )
        and not _sow_automation_projection_row_errors(
            "Standing Automation Orders",
            context.sow.get("Standing Automation Orders", []),
            contract_root_ref=context.contract_root_ref,
        )
    )
    automation_file = (
        context.sow_defs.get("Automation Orders File") if sow_definitions else None
    )
    automation_manifest_path = context.contract_root / "AUTOMATION_ORDERS.json"
    automation_manifest_readable = bool(
        present(automation_file)
        and automation_manifest_path.exists()
        and not safe_paths.bounded_input_errors(
            automation_manifest_path,
            context.contract_root,
            description="AUTOMATION_ORDERS.json input",
        )
    )
    framework_verification_commands = (
        "Framework Verification Commands" in context.contract
        and "Framework Verification Commands" not in duplicate_contract_sections
        and "Framework Verification Commands" in valid_project_row_grammar_sections
        and not duplicate_key_names(
            context.contract.get("Framework Verification Commands", []),
            bullet=True,
        )
    )
    unambiguous_sow_scalar_sections = frozenset(
        section
        for section in contract_model.SOW_SCALAR_SECTION_TITLES
        if section in context.sow
        and section not in duplicate_sow_sections
        and section in valid_sow_row_grammar_sections
        and not duplicate_key_names(
            sow_scalar_section_lines(section, context.sow.get(section, []))
        )
    )
    bootstrap_mode: str | None = None
    if sow_definitions:
        candidate = normalize(context.sow_defs.get("Bootstrap Mode", ""))
        if candidate in contract_model.BOOTSTRAP_MODES:
            bootstrap_mode = candidate
    return SyncValidationPrerequisites(
        valid_sow_row_grammar_sections=valid_sow_row_grammar_sections,
        valid_project_row_grammar_sections=valid_project_row_grammar_sections,
        sow_definitions=sow_definitions,
        invalid_sow_definition_value_keys=invalid_sow_definition_value_keys,
        contract_definitions=contract_definitions,
        sow_technical_specs=sow_technical_specs,
        contract_active_stack=contract_active_stack,
        sow_commands=sow_commands,
        contract_common_commands=contract_common_commands,
        sow_scope=sow_scope,
        contract_scope=contract_scope,
        sow_automation=sow_automation,
        sow_automation_projection_rows=sow_automation_projection_rows,
        automation_manifest_readable=automation_manifest_readable,
        framework_verification_commands=framework_verification_commands,
        unambiguous_sow_scalar_sections=unambiguous_sow_scalar_sections,
        bootstrap_mode=bootstrap_mode,
    )


def _read_utf8_input(path: Path, description: str, errors: list[str]) -> str | None:
    try:
        return safe_paths.read_regular_file_bytes(
            path,
            description=description,
        ).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        errors.append(f"{description} could not be read safely: {exc}")
        return None


def _build_validation_context(
    project_root: Path,
    contract_root: Path,
    contract_root_ref: str,
    project_kind: str,
    sow_text: str,
    contract_text: str,
) -> SyncValidationContext:
    sow = plain_sections(sow_text, SOW_TITLES)
    contract = markdown_sections(contract_text)
    sow_defs = parse_key_values(sow.get("Definitions", []))
    contract_defs = parse_key_values(contract.get("Definitions", []), bullet=True)
    sow_technical_specs = parse_key_values(
        technical_spec_key_lines(sow.get("Technical Specifications", []))
    )
    contract_active_stack = parse_key_values(contract.get("Active Stack", []), bullet=True)
    sow_commands = parse_commands(sow.get("Build and Development Commands", []))
    contract_common_commands = parse_key_values(contract.get("Common Commands", []), bullet=True)
    sow_scope = parse_scope(sow.get("Scope", []))
    contract_scope = parse_scope(contract.get("Active Scope", []))
    sow_deliverables = parse_numbered(sow.get("Deliverables and Acceptance Tests", []))
    contract_deliverables = parse_numbered(contract.get("Active Deliverables", []))
    sow_deliverables_need_deferral = numbered_section_needs_deferral(
        sow.get("Deliverables and Acceptance Tests", []),
        " — ",
        3,
    )
    contract_deliverables_need_deferral = numbered_section_needs_deferral(
        contract.get("Active Deliverables", []),
        " — ",
        3,
    )
    return SyncValidationContext(
        project_root=project_root,
        contract_root=contract_root,
        contract_root_ref=contract_root_ref,
        project_kind=project_kind,
        sow_text=sow_text,
        contract_text=contract_text,
        sow=sow,
        contract=contract,
        sow_defs=sow_defs,
        contract_defs=contract_defs,
        sow_technical_specs=sow_technical_specs,
        contract_active_stack=contract_active_stack,
        sow_commands=sow_commands,
        contract_common_commands=contract_common_commands,
        sow_scope=sow_scope,
        contract_scope=contract_scope,
        sow_deliverables=sow_deliverables,
        contract_deliverables=contract_deliverables,
        sow_deliverables_need_deferral=sow_deliverables_need_deferral,
        contract_deliverables_need_deferral=contract_deliverables_need_deferral,
    )


def _collect_structure_errors(
    context: SyncValidationContext,
    msa_text: str,
    errors: list[str],
) -> None:
    duplicate_sow_sections = duplicate_plain_section_titles(
        context.sow_text,
        SOW_TITLES,
    )
    duplicate_contract_sections = duplicate_markdown_section_titles(
        context.contract_text
    )
    errors.extend(internal_tracking_leaks("STATEMENT_OF_WORK.md", context.sow_text))
    errors.extend(internal_tracking_leaks("AGENT_PROJECT.md", context.contract_text))
    errors.extend(sow_contract_control_syntax_errors(context.sow_text))
    errors.extend(generated_contract_fence_errors(context.contract_text))
    errors.extend(generated_contract_comment_errors(context.contract_text))
    errors.extend(
        preamble_identity_errors(
            context.sow_text,
            context.contract_text,
            contract_root_ref=context.contract_root_ref,
        )
    )
    errors.extend(msa_reference_errors(context.sow_text, msa_text))
    errors.extend(
        duplicate_plain_section_errors(
            context.sow_text,
            SOW_TITLES,
            "STATEMENT_OF_WORK.md",
        )
    )
    errors.extend(
        duplicate_markdown_section_errors(
            context.contract_text,
            "AGENT_PROJECT.md",
        )
    )
    errors.extend(
        sow_section_row_grammar_errors(
            context.sow,
            duplicate_sow_sections,
            contract_root_ref=context.contract_root_ref,
        )
    )
    for section in sorted(
        set(context.contract) - contract_model.PROJECT_SECTION_TITLES
    ):
        errors.append(f"AGENT_PROJECT.md contains unbacked section: {section}")
    errors.extend(
        project_section_row_grammar_errors(
            context.contract,
            duplicate_contract_sections,
        )
    )
    if (
        "Active Stack" in context.contract
        and "Active Stack" not in duplicate_contract_sections
    ):
        errors.extend(active_stack_closed_row_errors(context))
    for section in sorted(REQUIRED_SOW_SECTIONS):
        if section not in context.sow:
            errors.append(f"STATEMENT_OF_WORK.md missing required section: {section}")
    for section in sorted(REQUIRED_PROJECT_SECTIONS):
        if section not in context.contract:
            errors.append(f"AGENT_PROJECT.md missing required section: {section}")
    if "Loading Rule" in context.contract:
        actual_loading_rule = [
            line.strip()
            for line in context.contract.get("Loading Rule", [])
            if line.strip()
        ]
        expected_loading_rule = integration_registry.render_project_file_references(
            "\n".join(contract_model.PROJECT_LOADING_RULE_LINES),
            context.contract_root_ref,
        ).splitlines()
        if actual_loading_rule != expected_loading_rule:
            errors.append(
                "AGENT_PROJECT.md Loading Rule drift: the section must exactly match "
                "the declarative project-contract model"
            )
    errors.extend(
        key_value_duplicate_errors(
            "STATEMENT_OF_WORK.md Definitions",
            context.sow.get("Definitions", []),
        )
    )
    for section in sorted(contract_model.SOW_SCALAR_SECTION_TITLES):
        if section not in context.sow:
            continue
        errors.extend(
            key_value_duplicate_errors(
                f"STATEMENT_OF_WORK.md {section}",
                sow_scalar_section_lines(section, context.sow.get(section, [])),
            )
        )
    errors.extend(
        key_value_duplicate_errors(
            "AGENT_PROJECT.md Definitions",
            context.contract.get("Definitions", []),
            bullet=True,
        )
    )
    errors.extend(
        key_value_duplicate_errors(
            "STATEMENT_OF_WORK.md Technical Specifications",
            technical_spec_key_lines(context.sow.get("Technical Specifications", [])),
        )
    )
    errors.extend(
        key_value_duplicate_errors(
            "AGENT_PROJECT.md Active Stack",
            context.contract.get("Active Stack", []),
            bullet=True,
        )
    )
    errors.extend(
        key_value_duplicate_errors(
            "AGENT_PROJECT.md Common Commands",
            context.contract.get("Common Commands", []),
            bullet=True,
        )
    )
    errors.extend(
        key_value_duplicate_errors(
            "AGENT_PROJECT.md Framework Verification Commands",
            context.contract.get("Framework Verification Commands", []),
            bullet=True,
        )
    )


def _collect_semantic_errors(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
) -> None:
    def sow_rows_usable(title: str) -> bool:
        return (
            title not in context.sow
            or title in prerequisites.valid_sow_row_grammar_sections
        )

    def project_rows_usable(title: str) -> bool:
        return (
            title not in context.contract
            or title in prerequisites.valid_project_row_grammar_sections
        )

    runner_valid = False
    if prerequisites.sow_definitions:
        errors.extend(definition_value_errors(context.sow_defs))
        errors.extend(
            sow_labeled_definition_parity_errors(
                context.sow,
                context.sow_defs,
                prerequisites.unambiguous_sow_scalar_sections,
                prerequisites.invalid_sow_definition_value_keys,
            )
        )
        errors.extend(
            governance_projection_errors(
                context.sow,
                context.sow_defs,
                prerequisites.unambiguous_sow_scalar_sections,
                prerequisites.invalid_sow_definition_value_keys,
            )
        )
        errors.extend(
            declared_optional_state_errors(
                context.sow_defs,
                context.contract_root,
                context.contract_root_ref,
            )
        )
        if (
            "Security Policy File"
            not in prerequisites.invalid_sow_definition_value_keys
            and sow_rows_usable("Security Policy")
            and project_rows_usable("Security Policy")
        ):
            errors.extend(
                inline_security_policy_errors(
                    context.sow,
                    context.contract,
                    context.sow_defs,
                )
            )
        runner = context.sow_defs.get("Framework Verification Runner")
        if runner is not None:
            runner_errors = contract_model.framework_verification_runner_errors(
                runner,
                "STATEMENT_OF_WORK.md Framework Verification Runner",
            )
            errors.extend(runner_errors)
            runner_valid = not runner_errors

    if prerequisites.sow_definitions and prerequisites.contract_definitions:
        errors.extend(
            state_projection_parity_errors(
                context.sow,
                context.sow_defs,
                context.contract_defs,
                context.contract_root,
                prerequisites.unambiguous_sow_scalar_sections,
            )
        )

    if prerequisites.automation_manifest_readable:
        errors.extend(
            automation_projection_parity_errors(
                context.sow,
                context.contract_root,
                context.contract_root_ref,
                compare_projection=prerequisites.sow_automation_projection_rows,
            )
        )

    errors.extend(
        shared_source_reference_errors(
            context.sow,
            context.contract_root,
            prerequisites.unambiguous_sow_scalar_sections,
        )
    )
    security_policy_file = (
        context.sow_defs.get("Security Policy File")
        if prerequisites.sow_definitions
        and "Security Policy File"
        not in prerequisites.invalid_sow_definition_value_keys
        else None
    )
    annexes_usable = sow_rows_usable("Annexes") and project_rows_usable(
        "Active Project Modules"
    )
    if annexes_usable:
        errors.extend(
            annex_projection_errors(
                context.sow.get("Annexes", []),
                raw_section_without_owned_definition_rows(
                    context,
                    "active_modules",
                ),
                security_policy_file,
            )
        )
    referenced_files = (
        annex_project_file_references(context.sow.get("Annexes", []))
        if sow_rows_usable("Annexes")
        else []
    )
    if (
        prerequisites.sow_definitions
        and "Security Policy File"
        not in prerequisites.invalid_sow_definition_value_keys
        and normalize(context.sow_defs.get("Security Policy File", ""))
        == normalize("project SECURITY.md")
    ):
        referenced_files.append(("Security Policy File", "SECURITY.md"))
    errors.extend(
        project_bootstrap.project_file_reference_errors(
            context.project_root,
            referenced_files,
        )
    )
    if (
        "Arbitration Panel" not in context.sow
        or "Arbitration Panel" in prerequisites.unambiguous_sow_scalar_sections
    ):
        errors.extend(
            arbitration_panel_errors(context.sow.get("Arbitration Panel", []))
        )
    if prerequisites.bootstrap_mode == "full":
        errors.extend(
            full_mode_semantic_errors(
                context.sow,
                context.sow_defs,
                context.sow_technical_specs,
                context.sow_scope,
                context.sow_commands,
                check_definitions=prerequisites.sow_definitions,
                check_technical_specs=prerequisites.sow_technical_specs,
                check_scope=prerequisites.sow_scope,
                check_commands=prerequisites.sow_commands,
            )
        )
        if sow_rows_usable("Deliverables and Acceptance Tests"):
            if not context.sow_deliverables:
                errors.append(
                    "STATEMENT_OF_WORK.md full bootstrap missing Deliverables and Acceptance Tests entries"
                )
            elif context.sow_deliverables_need_deferral:
                errors.append(
                    "STATEMENT_OF_WORK.md full bootstrap deliverables must include deliverable, test, and pass criteria"
                )
        if project_rows_usable("Active Deliverables"):
            if not context.contract_deliverables:
                errors.append(
                    "AGENT_PROJECT.md full bootstrap missing Active Deliverables entries"
                )
            elif context.contract_deliverables_need_deferral:
                errors.append(
                    "AGENT_PROJECT.md full bootstrap deliverables must include deliverable and acceptance evidence"
                )
    elif prerequisites.bootstrap_mode == "minimal" and sow_rows_usable("Recitals"):
        if any(
            unresolved_full_value(item)
            for item in parse_entries(context.sow.get("Recitals", []))
        ):
            errors.append(
                "STATEMENT_OF_WORK.md minimal bootstrap must use the structured "
                "Recitals deferral instead of bare placeholder text"
            )

    sow_deferrals: dict[str, dict[str, str]] = {}
    sow_deferral_errors: list[str] = []
    if sow_rows_usable("Minimal Bootstrap Deferrals"):
        sow_deferrals, sow_deferral_errors = minimal_deferral_records(
            "STATEMENT_OF_WORK.md",
            context.sow.get("Minimal Bootstrap Deferrals", []),
        )
    contract_deferrals: dict[str, dict[str, str]] = {}
    contract_deferral_errors: list[str] = []
    if project_rows_usable("Minimal Bootstrap Deferrals"):
        contract_deferrals, contract_deferral_errors = minimal_deferral_records(
            "AGENT_PROJECT.md",
            context.contract.get("Minimal Bootstrap Deferrals", []),
        )
    errors.extend(sow_deferral_errors)
    errors.extend(contract_deferral_errors)
    if not sow_deferral_errors and not contract_deferral_errors:
        errors.extend(minimal_deferral_parity_errors(sow_deferrals, contract_deferrals))
        required_fields: set[str] | None = None
        if prerequisites.bootstrap_mode == "full":
            required_fields = set()
        elif prerequisites.bootstrap_mode == "minimal" and all(
            (
                prerequisites.sow_definitions,
                prerequisites.contract_definitions,
                prerequisites.sow_technical_specs,
                prerequisites.contract_active_stack,
                prerequisites.sow_scope,
                prerequisites.contract_scope,
                prerequisites.sow_commands,
                prerequisites.contract_common_commands,
                sow_rows_usable("Deliverables and Acceptance Tests"),
                project_rows_usable("Active Deliverables"),
            )
        ):
            required_fields = required_minimal_deferral_fields(
                parse_entries(context.sow.get("Recitals", [])),
                context.sow_defs,
                context.sow_technical_specs,
                context.contract_active_stack,
                context.sow_scope,
                context.contract_scope,
                context.sow_commands,
                context.contract_common_commands,
                context.sow_deliverables_need_deferral,
                context.contract_deliverables_need_deferral,
            )
        if required_fields is not None:
            errors.extend(
                minimal_deferral_required_field_errors(
                    sow_deferrals,
                    required_fields,
                )
            )

    if (
        "Build and Development Commands" in context.sow
        and "Build and Development Commands"
        in prerequisites.valid_sow_row_grammar_sections
    ):
        errors.extend(
            sow_command_row_errors(
                context.sow.get("Build and Development Commands", [])
            )
        )
    if (
        "Common Commands" in context.contract
        and "Common Commands" in prerequisites.valid_project_row_grammar_sections
    ):
        errors.extend(
            common_command_row_errors(context.contract.get("Common Commands", []))
        )
    if prerequisites.framework_verification_commands and runner_valid:
        verification_lines = raw_section_without_owned_definition_rows(
            context,
            "framework_verification",
        )
        verification_errors = framework_verification_command_errors(
            verification_lines,
            project_kind=context.project_kind,
            contract_root_ref=context.contract_root_ref,
            expected_runner=context.sow_defs["Framework Verification Runner"],
        )
        errors.extend(verification_errors)
        source_monitor_label = "Source Monitor Researcher Brief"
        if (
            not verification_errors
            and source_monitor_label
            not in prerequisites.invalid_sow_definition_value_keys
            and context.sow_defs.get(source_monitor_label) != "none"
        ):
            verification_entries = parse_key_values(
                verification_lines,
                bullet=True,
            )
            framework_reference = verification_entries.get(
                "Framework reference"
            )
            if framework_reference is not None:
                errors.extend(
                    source_monitor_runtime_projection_errors(
                        context.contract_root,
                        expected_runner=context.sow_defs[
                            "Framework Verification Runner"
                        ],
                        expected_framework_reference=framework_reference,
                    )
                )


def _collect_definition_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
) -> None:
    specs_by_label = {
        spec.label: spec for spec in contract_model.PROJECT_DEFINITION_SPECS
    }

    def activation_owner_valid(spec: contract_model.DefinitionSpec) -> bool:
        if spec.active_when is None:
            return True
        owner_label = contract_model.OPTIONAL_STATE_DEFINITION_BY_FLAG.get(
            spec.active_when
        )
        return (
            owner_label is not None
            and owner_label
            not in prerequisites.invalid_sow_definition_value_keys
        )

    expected_sow_definitions = {
        spec.label
        for spec in contract_model.SOW_DEFINITION_SPECS
        if activation_owner_valid(spec)
        if (
            spec.active_when is None
            or contract_model.runtime_definition_activation_enabled(
                spec,
                context.sow_defs,
            )
        )
    }
    if prerequisites.sow_definitions:
        for key in sorted(expected_sow_definitions - set(context.sow_defs)):
            errors.append(f"STATEMENT_OF_WORK.md Definitions missing required key: {key}")
        runtime_standards = context.sow_defs.get("Language/Runtime Standards")
        if runtime_standards is not None and not runtime_standards.strip():
            errors.append(
                "STATEMENT_OF_WORK.md Definitions Language/Runtime Standards "
                "must not be blank"
            )
        known_sow_definitions = {
            spec.label for spec in contract_model.SOW_DEFINITION_SPECS
        }
        for key in sorted(
            (set(context.sow_defs) & known_sow_definitions)
            - expected_sow_definitions
        ):
            errors.append(
                "STATEMENT_OF_WORK.md Definitions contains inactive conditional key: "
                f"{key}"
            )
        for key in sorted(set(context.sow_defs) - known_sow_definitions):
            errors.append(
                f"STATEMENT_OF_WORK.md Definitions contains unbacked key: {key}"
            )
        memory_rows = parse_bullets(context.sow.get("Memory Boundary", []))
        memory_definition = context.sow_defs.get("Memory Boundary")
        if (
            memory_definition is not None
            and (
                len(memory_rows) != 1
                or memory_definition != memory_rows[0]
            )
        ):
            errors.append(
                "Memory Boundary SOW Definitions index does not exactly match "
                "the dedicated Memory Boundary section"
            )
        for label in sorted(contract_model.COMMAND_DEFINITION_FIELDS):
            value = context.sow_defs.get(label)
            if (
                value is not None
                and value != contract_model.COMMAND_DEFINITION_POINTER
            ):
                errors.append(
                    f"{label} SOW Definitions index must be exactly "
                    f"{contract_model.COMMAND_DEFINITION_POINTER!r}"
                )
    if not (prerequisites.sow_definitions and prerequisites.contract_definitions):
        return

    expected_contract_definitions = {
        label
        for label, spec in specs_by_label.items()
        if label not in prerequisites.invalid_sow_definition_value_keys
        if activation_owner_valid(spec)
        if contract_model.runtime_definition_included(
            spec,
            context.sow_defs.get(label),
            active_when_enabled=contract_model.runtime_definition_activation_enabled(
                spec,
                context.sow_defs,
            ),
        )
    }
    for key in sorted(expected_contract_definitions - set(context.contract_defs)):
        errors.append(f"AGENT_PROJECT.md Definitions missing required key: {key}")
    runtime_standards = context.contract_defs.get("Language/Runtime Standards")
    if runtime_standards is not None and not runtime_standards.strip():
        errors.append(
            "AGENT_PROJECT.md Definitions Language/Runtime Standards must not be blank"
        )
    unexpected_contract_definitions = (
        set(context.contract_defs)
        - expected_contract_definitions
        - prerequisites.invalid_sow_definition_value_keys
    )
    for key in sorted(unexpected_contract_definitions):
        if key in specs_by_label:
            errors.append(
                f"{key} SOW Definitions -> AGENT_PROJECT.md Definitions drift: "
                "the runtime Definitions section must omit model-owned defaults, inactive "
                "optional facts, and section-owned facts"
            )
        else:
            errors.append(
                f"AGENT_PROJECT.md Definitions contains unbacked key: {key}"
            )

    for sow_key in sorted(expected_contract_definitions):
        contract_key = FIELD_MAP[sow_key]
        if sow_key not in context.sow_defs or contract_key not in context.contract_defs:
            continue
        left = context.sow_defs.get(sow_key)
        right = context.contract_defs.get(contract_key)
        if (
            prerequisites.bootstrap_mode is None
            and sow_key == "Language/Runtime Standards"
            and (
                contract_model.is_deferred_value(left)
                or is_minimal_runtime_deferral("Language/Runtime Standards", right)
            )
        ):
            continue
        if (
            prerequisites.bootstrap_mode == "minimal"
            and sow_key == "Language/Runtime Standards"
            and contract_model.is_deferred_value(left)
            and is_minimal_runtime_deferral("Language/Runtime Standards", right)
        ):
            continue
        label = contract_key
        if sow_key == "Automation Orders File":
            label = (
                "Automation Orders File SOW Definitions -> "
                "AGENT_PROJECT.md Definitions"
            )
        comparison = (
            compare_exact_value
            if sow_key in contract_model.DECLARED_OPTIONAL_STATE
            else compare_value
        )
        comparison(label, left, right, errors)


OWNER_ORDINARY_SOW_SECTIONS: dict[str, tuple[str, ...]] = {
    "constraints": ("Project-Specific Constraints", "Language-Specific Rules"),
    "approval_boundaries": ("Approval Boundaries",),
    "acquisition_boundary": ("Information Acquisition Boundary",),
    "critical_surfaces": ("Critical Surfaces",),
    "version_control": ("Version Control Profile",),
}


def ordinary_owner_row_allowance(
    context: SyncValidationContext,
    owner: str,
) -> Counter[str]:
    """Return exact SOW-backed ordinary payloads for one open runtime owner."""

    return Counter(
        item
        for title in OWNER_ORDINARY_SOW_SECTIONS.get(owner, ())
        for item in parse_bullets(context.sow.get(title, []))
    )


def raw_section_without_owned_definition_rows(
    context: SyncValidationContext,
    owner: str,
) -> list[str]:
    """Return a runtime owner's raw rows, excluding its labeled facts."""

    title = contract_model.PROJECT_SECTIONS[owner].title
    owned_labels = {
        spec.label
        for spec in contract_model.PROJECT_DEFINITION_SPECS
        if spec.runtime_policy == "section-owned"
        and spec.runtime_owner == owner
        and spec.runtime_owner_style == "labeled"
    }
    ordinary_allowance = ordinary_owner_row_allowance(context, owner)
    rows: list[str] = []
    for raw in context.contract.get(title, []):
        item = raw.strip()
        payload = item[2:] if item.startswith("- ") else item
        label, separator, _value = payload.partition(": ")
        if separator and label in owned_labels:
            if ordinary_allowance[payload] > 0:
                ordinary_allowance[payload] -= 1
                rows.append(raw)
            continue
        rows.append(raw)
    return rows


def section_without_owned_definition_rows(
    context: SyncValidationContext,
    owner: str,
) -> list[str]:
    """Return a runtime owner's ordinary bullets, excluding its labeled facts."""

    return parse_bullets(raw_section_without_owned_definition_rows(context, owner))


def expected_section_owned_definition_value(
    context: SyncValidationContext,
    spec: contract_model.DefinitionSpec,
    invalid_definition_keys: frozenset[str],
) -> str | None:
    """Return the exact generated value for one active labeled owner row."""

    if spec.label in invalid_definition_keys:
        return None
    sow_value = context.sow_defs.get(spec.label)
    if not contract_model.runtime_owned_definition_included(
        spec,
        sow_value,
        active_when_enabled=contract_model.runtime_definition_activation_enabled(
            spec,
            context.sow_defs,
        ),
    ):
        return None
    if (
        spec.label == "Language/Runtime Standards"
        and contract_model.is_deferred_value(sow_value)
    ):
        return contract_model.MINIMAL_RUNTIME_STANDARDS_DEFERRAL
    return sow_value


def active_stack_closed_row_errors(
    context: SyncValidationContext,
) -> list[str]:
    """Enforce the model-derived closed labeled-row grammar for Active Stack."""

    native_labels = set(
        contract_model.project_blueprint_labeled_row_labels("active_stack")
    )
    owned_specs = {
        spec.label: spec
        for spec in contract_model.PROJECT_DEFINITION_SPECS
        if spec.runtime_policy == "section-owned"
        and spec.runtime_owner == "active_stack"
        and spec.runtime_owner_style == "labeled"
    }
    allowed_labels = native_labels | set(owned_specs)
    errors: list[str] = []
    for index, raw in enumerate(context.contract.get("Active Stack", []), start=1):
        if not raw.startswith("- "):
            # The section-wide raw-row grammar reports bare and alternate markers.
            continue
        payload = raw[2:]
        if ":" not in payload:
            errors.append(
                f"AGENT_PROJECT.md Active Stack row {index} must be a labeled "
                f"key-value bullet: {raw!r}"
            )
            continue
        key, value = (part.strip() for part in payload.split(":", 1))
        if not key or not value:
            errors.append(
                f"AGENT_PROJECT.md Active Stack row {index} must contain a "
                f"nonempty label and value: {raw!r}"
            )
            continue
        if key not in allowed_labels:
            errors.append(
                f"AGENT_PROJECT.md Active Stack row {index} contains unbacked "
                f"label: {key}"
            )
            continue
    return errors


def _collect_section_owned_definition_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
) -> None:
    """Enforce one active runtime owner for every labeled canonical fact."""

    if not prerequisites.sow_definitions:
        return
    if prerequisites.contract_active_stack:
        errors.extend(
            active_stack_closed_row_errors(
                context,
            )
        )
    specs = [
        spec
        for spec in contract_model.PROJECT_DEFINITION_SPECS
        if spec.runtime_policy == "section-owned"
        and spec.runtime_owner_style == "labeled"
    ]
    for spec in specs:
        if spec.label in prerequisites.invalid_sow_definition_value_keys:
            continue
        owner = spec.runtime_owner
        if owner is None:
            continue
        owner_title = contract_model.PROJECT_SECTIONS[owner].title
        if (
            owner_title in context.contract
            and owner_title not in prerequisites.valid_project_row_grammar_sections
        ):
            continue
        if (
            owner_title not in context.contract
            and owner_title in REQUIRED_PROJECT_SECTIONS
        ):
            continue
        expected_value = expected_section_owned_definition_value(
            context,
            spec,
            prerequisites.invalid_sow_definition_value_keys,
        )
        # A model-owned label is reserved throughout its declared owner section.
        # Outside that section, only the exact generated value is ownership
        # metadata; ordinary project prose may legitimately begin with the same
        # words (for example, an AI-disclosure constraint).
        ordinary_allowance = ordinary_owner_row_allowance(context, owner)
        labeled_occurrences: list[tuple[str, str]] = []
        for section_title, lines in context.contract.items():
            if section_title not in prerequisites.valid_project_row_grammar_sections:
                continue
            for item in parse_bullets(lines):
                label, separator, value = item.partition(": ")
                if not separator or label != spec.label:
                    continue
                if section_title == owner_title:
                    if ordinary_allowance[item] > 0:
                        ordinary_allowance[item] -= 1
                        continue
                    labeled_occurrences.append((section_title, value))
                elif expected_value is not None and value == expected_value:
                    labeled_occurrences.append((section_title, value))
        if expected_value is None:
            if labeled_occurrences:
                errors.append(
                    f"{spec.label} must be omitted from the runtime projection "
                    "when inactive or model-default"
                )
            continue
        if len(labeled_occurrences) != 1:
            errors.append(
                f"{spec.label} must appear exactly once in AGENT_PROJECT.md {owner_title}"
            )
            continue
        actual_owner, actual_value = labeled_occurrences[0]
        if actual_value != expected_value:
            errors.append(
                f"{spec.label} in AGENT_PROJECT.md {actual_owner} does not exactly "
                "match the canonical SOW Definition value"
            )
            continue
        if actual_owner != owner_title:
            errors.append(
                f"{spec.label} appears in AGENT_PROJECT.md {actual_owner}; declared owner is {owner_title}"
            )


def _collect_stack_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
) -> None:
    if prerequisites.sow_technical_specs:
        for key in ("Tech stack", "Architecture"):
            if key not in context.sow_technical_specs:
                errors.append(
                    "STATEMENT_OF_WORK.md Technical Specifications missing required "
                    f"key: {key}"
                )
            elif not context.sow_technical_specs[key].strip():
                errors.append(
                    "STATEMENT_OF_WORK.md Technical Specifications required key "
                    f"must not be blank: {key}"
                )
    if prerequisites.contract_active_stack:
        for key in (
            "Languages and frameworks",
            "Architecture",
            "Language/Runtime Standards",
        ):
            if key not in context.contract_active_stack:
                errors.append(
                    f"AGENT_PROJECT.md Active Stack missing required key: {key}"
                )
            elif not context.contract_active_stack[key].strip():
                errors.append(
                    f"AGENT_PROJECT.md Active Stack required key must not be blank: {key}"
                )
    if not (
        prerequisites.sow_technical_specs
        and prerequisites.contract_active_stack
    ):
        return
    for label, sow_key, contract_key in (
        ("Tech stack", "Tech stack", "Languages and frameworks"),
        ("Architecture", "Architecture", "Architecture"),
        ("Key dependencies", "Key dependencies", "Key dependencies"),
        ("Key directories", "Key directories", "Key directories"),
    ):
        left = context.sow_technical_specs.get(sow_key)
        right = context.contract_active_stack.get(contract_key)
        if (
            label in {"Tech stack", "Architecture"}
            and prerequisites.bootstrap_mode is None
            and (
                contract_model.is_deferred_value(left)
                or is_minimal_runtime_deferral(contract_key, right)
            )
        ):
            continue
        if (
            label in {"Tech stack", "Architecture"}
            and prerequisites.bootstrap_mode == "minimal"
            and contract_model.is_deferred_value(left)
            and is_minimal_runtime_deferral(contract_key, right)
        ):
            continue
        compare_value(label, left, right, errors)


def _collect_automation_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
) -> None:
    if not prerequisites.sow_definitions:
        return
    automation_file = context.sow_defs.get("Automation Orders File")
    automation_active = present(automation_file)
    section_present = "Standing Automation Orders" in context.sow
    if section_present and not automation_active:
        errors.append(
            "STATEMENT_OF_WORK.md Standing Automation Orders must be omitted "
            "when the canonical Automation Orders File definition is inactive"
        )
        return
    if automation_active and not section_present:
        errors.append(
            "STATEMENT_OF_WORK.md active Automation Orders File requires exactly "
            "one Standing Automation Orders section"
        )
        return
    if not section_present or not prerequisites.sow_automation_projection_rows:
        return
    automation = parse_key_values(context.sow.get("Standing Automation Orders", []))
    compare_exact_value(
        "Automation Orders File SOW section -> SOW Definitions",
        automation.get("Automation Orders File"),
        context.sow_defs.get("Automation Orders File"),
        errors,
    )


def _collect_command_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
    warnings: list[str],
) -> None:
    expected_common_labels = set(COMMON_COMMAND_LABELS.values())
    common_command_keys_valid = False
    if prerequisites.contract_common_commands:
        missing_common_labels = expected_common_labels - set(
            context.contract_common_commands
        )
        unbacked_common_labels = (
            set(context.contract_common_commands) - expected_common_labels
        )
        for contract_label in sorted(missing_common_labels):
            errors.append(
                f"AGENT_PROJECT.md Common Commands missing required key: {contract_label}"
            )
        for contract_label in sorted(unbacked_common_labels):
            errors.append(
                f"AGENT_PROJECT.md Common Commands contains unbacked key: {contract_label}"
            )
        common_command_keys_valid = not (
            missing_common_labels or unbacked_common_labels
        )

    if prerequisites.sow_commands and common_command_keys_valid:
        for sow_label, contract_label in COMMON_COMMAND_LABELS.items():
            compare_value(
                f"Common Commands {contract_label}",
                context.sow_commands.get(sow_label),
                context.contract_common_commands.get(contract_label),
                errors,
            )
    if context.project_kind == "downstream" and common_command_keys_valid:
        for label, value in context.contract_common_commands.items():
            warnings.extend(command_warnings(f"Common Commands {label}", value))


def _collect_definition_and_command_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
    warnings: list[str],
) -> None:
    _collect_definition_parity(context, prerequisites, errors)
    _collect_section_owned_definition_parity(context, prerequisites, errors)
    _collect_stack_parity(context, prerequisites, errors)
    _collect_automation_parity(context, prerequisites, errors)
    _collect_command_parity(context, prerequisites, errors, warnings)


def _collect_list_parity(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
    warnings: list[str],
) -> None:
    def sow_rows_valid(title: str) -> bool:
        return (
            title not in context.sow
            or title in prerequisites.valid_sow_row_grammar_sections
        )

    def project_rows_valid(title: str) -> bool:
        return (
            title not in context.contract
            or title in prerequisites.valid_project_row_grammar_sections
        )

    sow_constraints = [
        *parse_bullets(context.sow.get("Project-Specific Constraints", [])),
        *parse_bullets(context.sow.get("Language-Specific Rules", [])),
    ]
    if (
        sow_rows_valid("Project-Specific Constraints")
        and sow_rows_valid("Language-Specific Rules")
        and project_rows_valid("Non-Negotiable Constraints")
    ):
        errors.extend(
            exact_list_parity_errors(
                "Non-Negotiable Constraints",
                sow_constraints,
                section_without_owned_definition_rows(context, "constraints"),
            )
        )
    for label, sow_section, contract_section, owner in (
        (
            "Acceptance Checklist",
            "Acceptance Checklist (per deliverable)",
            "Acceptance Checklist",
            None,
        ),
        (
            "Acquisition Boundary",
            "Information Acquisition Boundary",
            "Acquisition Boundary",
            "acquisition_boundary",
        ),
        ("Active Project Modules", "Annexes", "Active Project Modules", "active_modules"),
        ("Applicable Standards", "Applicable Standards", "Applicable Standards", None),
        ("Project Vocabulary", "Project Vocabulary", "Project Vocabulary", None),
        ("Critical Surfaces", "Critical Surfaces", "Critical Surfaces", "critical_surfaces"),
        ("Version Control Profile", "Version Control Profile", "Version Control Profile", "version_control"),
        ("Memory Boundary", "Memory Boundary", "Memory Boundary", None),
        ("Verification Profiles", "Verification Profiles", "Verification Profiles", None),
    ):
        if not sow_rows_valid(sow_section) or not project_rows_valid(
            contract_section
        ):
            continue
        contract_items = (
            section_without_owned_definition_rows(context, owner)
            if owner is not None
            else parse_bullets(context.contract.get(contract_section, []))
        )
        errors.extend(
            exact_list_parity_errors(
                label,
                parse_bullets(context.sow.get(sow_section, [])),
                contract_items,
            )
        )

    if prerequisites.bootstrap_mode is not None and sow_rows_valid(
        "Deliverables and Acceptance Tests"
    ) and project_rows_valid("Active Deliverables"):
        expected_contract_deliverables = (
            canonical_minimal_deliverables(context.sow_deliverables)
            if prerequisites.bootstrap_mode == "minimal"
            else context.sow_deliverables
        )
        errors.extend(
            repeated_projection_parity_errors(
                "Active Deliverables",
                expected_contract_deliverables,
                context.contract_deliverables,
            )
        )
    if (
        prerequisites.bootstrap_mode is not None
        and prerequisites.sow_scope
        and prerequisites.contract_scope
    ):
        for label in ("In scope", "Out of scope"):
            sow_items = context.sow_scope[label]
            contract_items = context.contract_scope[label]
            expected_items = sow_items
            if prerequisites.bootstrap_mode == "minimal" and (
                not sow_items
                or any(contract_model.is_deferred_value(item) for item in sow_items)
            ):
                expected_items = [
                    *[
                        item
                        for item in sow_items
                        if not contract_model.is_deferred_value(item)
                    ],
                    MINIMAL_RUNTIME_DEFERRALS[label],
                ]
            if sorted(normalize(item) for item in expected_items) != sorted(
                normalize(item) for item in contract_items
            ):
                errors.append(
                    f"{label} drift between SOW Scope and project contract Active Scope"
                )

    sow_restrictions = parse_entries(context.sow.get("Command Restrictions", []))
    contract_restrictions = parse_entries(
        context.contract.get("Command Restrictions", []),
        bullet=True,
    )
    if sow_rows_valid("Command Restrictions") and project_rows_valid(
        "Command Restrictions"
    ):
        errors.extend(
            rendered_command_restriction_identity_errors(
                "STATEMENT_OF_WORK.md Command Restrictions",
                sow_restrictions,
            )
        )
        errors.extend(
            exact_list_parity_errors(
                "Command Restrictions",
                sow_restrictions,
                contract_restrictions,
            )
        )
    if project_rows_valid("Command Restrictions"):
        errors.extend(
            rendered_command_restriction_identity_errors(
                "AGENT_PROJECT.md Command Restrictions",
                contract_restrictions,
            )
        )
    sow_workflows = parse_entries(context.sow.get("Workflows", []))
    contract_workflows = parse_entries(
        context.contract.get("Active Workflows", []),
        bullet=True,
    )
    if sow_rows_valid("Workflows") and project_rows_valid("Active Workflows"):
        errors.extend(
            rendered_workflow_identity_errors(
                "STATEMENT_OF_WORK.md Workflows",
                sow_workflows,
            )
        )
        expected_workflow_routes, workflow_route_errors = runtime_workflow_routes(
            "STATEMENT_OF_WORK.md Workflows",
            sow_workflows,
            contract_root_ref=context.contract_root_ref,
        )
        errors.extend(workflow_route_errors)
        errors.extend(
            exact_list_parity_errors(
                "Active Workflows",
                expected_workflow_routes,
                contract_workflows,
            )
        )
    if project_rows_valid("Active Workflows"):
        errors.extend(
            rendered_workflow_identity_errors(
                "AGENT_PROJECT.md Active Workflows",
                contract_workflows,
            )
        )
    sow_tools = parse_tool_entries(context.sow.get("Auxiliary Tools", []))
    contract_tools = parse_tool_entries(
        context.contract.get("Auxiliary Tools", []),
        bullet=True,
    )
    if sow_rows_valid("Auxiliary Tools") and project_rows_valid(
        "Auxiliary Tools"
    ):
        errors.extend(
            rendered_auxiliary_tool_identity_errors(
                "STATEMENT_OF_WORK.md Auxiliary Tools",
                sow_tools,
            )
        )
        expected_tool_routes, tool_route_errors = runtime_auxiliary_tool_routes(
            "STATEMENT_OF_WORK.md Auxiliary Tools",
            sow_tools,
            contract_root_ref=context.contract_root_ref,
        )
        errors.extend(tool_route_errors)
        errors.extend(
            exact_list_parity_errors(
                "Auxiliary Tools",
                expected_tool_routes,
                contract_tools,
            )
        )
        errors.extend(auxiliary_tool_fact_errors("SOW", sow_tools))
    if project_rows_valid("Auxiliary Tools"):
        errors.extend(
            rendered_auxiliary_tool_identity_errors(
                "AGENT_PROJECT.md Auxiliary Tools",
                contract_tools,
            )
        )

    arbitration_route = integration_registry.render_project_file_references(
        contract_model.ARBITRATION_PANEL_RUNTIME_ROUTE,
        context.contract_root_ref,
    )
    invalid_arbitration = (
        "Arbitration Panel"
        in prerequisites.invalid_sow_definition_value_keys
    )
    expected_review_routes: list[str] = []
    if prerequisites.sow_definitions and not invalid_arbitration:
        arbitration_panel = context.sow_defs.get("Arbitration Panel")
        if (
            arbitration_panel is not None
            and normalize(arbitration_panel)
            != normalize(contract_model.DEFAULT_ARBITRATION_PANEL_PROJECTION)
        ):
            expected_review_routes.append(arbitration_route)
    if prerequisites.sow_definitions and project_rows_valid("Review Routing"):
        actual_review_routes = section_without_owned_definition_rows(
            context,
            "review_routing",
        )
        if invalid_arbitration:
            actual_review_routes = [
                route for route in actual_review_routes
                if route != arbitration_route
            ]
        errors.extend(
            exact_list_parity_errors(
                "Review Routing",
                expected_review_routes,
                actual_review_routes,
            )
        )

    canonical_source_rows_valid = all(
        sow_rows_valid(title)
        for title in (
            "Technical Specifications",
            "Representative Pattern Sources",
            "Code Review Checklist",
        )
    )
    technical_spec_lines = context.sow.get("Technical Specifications", [])
    file_structure_present = False
    for index, raw in enumerate(technical_spec_lines):
        if raw.strip() == "File structure:":
            file_structure_present = any(
                following.strip()
                for following in technical_spec_lines[index + 1 :]
            )
            break
    active_canonical_fields = {
        "file_structure": file_structure_present,
        "pattern_sources": bool(
            parse_bullets(context.sow.get("Representative Pattern Sources", []))
        ),
        "code_review_checklist": bool(
            parse_numbered(context.sow.get("Code Review Checklist", []))
        ),
    }
    expected_canonical_routes = [
        integration_registry.render_project_file_references(
            route,
            context.contract_root_ref,
        )
        for field, route in contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES.items()
        if active_canonical_fields[field]
    ]
    if (
        canonical_source_rows_valid
        and project_rows_valid("Canonical Detail Routes")
    ):
        errors.extend(
            exact_list_parity_errors(
                "Canonical Detail Routes",
                expected_canonical_routes,
                parse_bullets(context.contract.get("Canonical Detail Routes", [])),
            )
        )

    sow_approval_boundaries = parse_bullets(context.sow.get("Approval Boundaries", []))
    contract_approval_boundaries = parse_bullets(
        raw_section_without_owned_definition_rows(
            context,
            "approval_boundaries",
        )
    )
    if sow_rows_valid("Approval Boundaries") and project_rows_valid(
        "Approval Boundaries"
    ):
        if bool(sow_approval_boundaries) != bool(contract_approval_boundaries):
            errors.append("Approval Boundaries drift between SOW and project contract")
        elif sow_approval_boundaries:
            left = {normalize(item) for item in sow_approval_boundaries}
            right = {normalize(item) for item in contract_approval_boundaries}
            if left != right:
                errors.append("Approval Boundaries drift between SOW and project contract")


def _collect_entrypoint_file_diagnostics(
    project_root: Path,
    contract_root_ref: str,
    *,
    expected_framework_reference: str | None,
    current_contract_format: bool = True,
    errors: list[str],
    warnings: list[str],
) -> None:
    for entrypoint_name in ENTRYPOINT_NAMES:
        entrypoint_path = project_root / entrypoint_name
        if not entrypoint_path.exists():
            continue
        entrypoint_errors = safe_paths.bounded_input_errors(
            entrypoint_path,
            project_root,
            description=f"{entrypoint_name} input",
        )
        if entrypoint_errors:
            errors.extend(entrypoint_errors)
            continue
        entrypoint = _read_utf8_input(
            entrypoint_path,
            f"{entrypoint_name} input",
            errors,
        )
        if entrypoint is None:
            continue
        errors.extend(internal_tracking_leaks(entrypoint_name, entrypoint))
        if current_contract_format:
            errors.extend(
                entrypoint_resolution_errors(
                    project_root,
                    entrypoint_name,
                    entrypoint,
                    contract_root_ref=contract_root_ref,
                    expected_framework_reference=expected_framework_reference,
                )
            )
        else:
            errors.extend(
                entrypoint_stable_resolution_errors(
                    project_root,
                    entrypoint_name,
                    entrypoint,
                    contract_root_ref=contract_root_ref,
                )
            )
        if "<project-rules>" in entrypoint:
            warnings.append(
                f"{entrypoint_name} contains a custom <project-rules> block; "
                "prefer keeping SOW-derived runtime facts in AGENT_PROJECT.md "
                "and durable decisions in DECISIONS.md"
            )
        if len(entrypoint.encode("utf-8")) > prompt_load_report.ENTRYPOINT_MAX_BYTES:
            warnings.append(
                f"{entrypoint_name} exceeds the loaded-entrypoint byte safety target; move "
                "non-startup rules into AGENT_PROJECT.md or DECISIONS.md"
            )


def _collect_entrypoint_diagnostics(
    context: SyncValidationContext,
    prerequisites: SyncValidationPrerequisites,
    errors: list[str],
    warnings: list[str],
) -> None:
    if context.project_kind != "downstream":
        return
    expected_framework_reference: str | None = None
    if prerequisites.framework_verification_commands:
        verification_entries = parse_key_values(
            context.contract.get("Framework Verification Commands", []),
            bullet=True,
        )
        candidate_reference = verification_entries.get("Framework reference")
        if candidate_reference and not safe_paths.framework_reference_errors(
            candidate_reference
        ):
            expected_framework_reference = candidate_reference
    _collect_entrypoint_file_diagnostics(
        context.project_root,
        context.contract_root_ref,
        expected_framework_reference=expected_framework_reference,
        errors=errors,
        warnings=warnings,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check drift between STATEMENT_OF_WORK.md and AGENT_PROJECT.md.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="Project root to inspect.",
    )
    parser.add_argument(
        "--contract-root",
        help=(
            "Safe project-relative directory containing STATEMENT_OF_WORK.md "
            "and AGENT_PROJECT.md. Defaults to the project root."
        ),
    )
    parser.add_argument(
        "--project-kind",
        choices=sorted(contract_model.PROJECT_KINDS),
        default="downstream",
        help="Selected project layout.",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return a failing exit code when warnings are present.",
    )
    return parser


def _print_result(errors: list[str], warnings: list[str]) -> None:
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    print(
        json.dumps(
            {"errors": errors, "warnings": warnings},
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    args = _argument_parser().parse_args()
    _raw_project_root, project_root, project_root_errors = (
        project_bootstrap.resolve_user_path(
            args.project_root,
            "project root",
        )
    )
    if project_root_errors:
        _print_result(project_root_errors, [])
        return 1
    contract_root, contract_root_ref, contract_root_errors = (
        project_bootstrap.resolve_contract_root(
            project_root,
            args.contract_root,
        )
    )
    sow_path = contract_root / "STATEMENT_OF_WORK.md"
    contract_path = contract_root / "AGENT_PROJECT.md"
    errors = list(contract_root_errors)
    warnings: list[str] = []
    if not errors and contract_root_ref != ".":
        errors.extend(
            safe_paths.exact_relative_path_spelling_errors(
                project_root,
                Path(contract_root_ref),
                description="contract root",
            )
        )
    if not errors:
        for filename, description in (
            ("STATEMENT_OF_WORK.md", "STATEMENT_OF_WORK.md input"),
            ("AGENT_PROJECT.md", "AGENT_PROJECT.md input"),
        ):
            errors.extend(
                safe_paths.exact_relative_path_spelling_errors(
                    contract_root,
                    Path(filename),
                    description=description,
                )
            )
    if errors:
        _print_result(errors, warnings)
        return 1
    errors.extend(
        project_bootstrap.project_layout_errors(
            project_root,
            contract_root,
            contract_root_ref,
            FRAMEWORK_ROOT,
            args.project_kind,
        )
    )
    errors.extend(
        safe_paths.bounded_input_errors(
            sow_path,
            project_root,
            description="STATEMENT_OF_WORK.md input",
        )
    )
    errors.extend(
        safe_paths.bounded_input_errors(
            contract_path,
            project_root,
            description="AGENT_PROJECT.md input",
        )
    )
    if not sow_path.exists():
        errors.append("missing STATEMENT_OF_WORK.md")
    if not contract_path.exists():
        errors.append("missing AGENT_PROJECT.md")
    if errors:
        _print_result(errors, warnings)
        return 1

    sow_text = _read_utf8_input(
        sow_path,
        "STATEMENT_OF_WORK.md input",
        errors,
    )
    contract_text = _read_utf8_input(
        contract_path,
        "AGENT_PROJECT.md input",
        errors,
    )
    msa_text = _read_utf8_input(
        FRAMEWORK_ROOT / "master_service_agreement.md",
        "master_service_agreement.md input",
        errors,
    )
    if sow_text is None or contract_text is None or msa_text is None:
        _print_result(errors, warnings)
        return 1

    format_errors = contract_format_update_errors(sow_text, contract_text)
    if format_errors:
        errors.extend(format_errors)
        errors.extend(internal_tracking_leaks("STATEMENT_OF_WORK.md", sow_text))
        errors.extend(internal_tracking_leaks("AGENT_PROJECT.md", contract_text))
        if args.project_kind == "downstream":
            _collect_entrypoint_file_diagnostics(
                project_root,
                contract_root_ref,
                expected_framework_reference=None,
                current_contract_format=False,
                errors=errors,
                warnings=warnings,
            )
        _print_result(errors, warnings)
        return 1

    context = _build_validation_context(
        project_root,
        contract_root,
        contract_root_ref,
        args.project_kind,
        sow_text,
        contract_text,
    )
    _collect_structure_errors(context, msa_text, errors)
    prerequisites = _validation_prerequisites(context)
    _collect_semantic_errors(context, prerequisites, errors)
    _collect_definition_and_command_parity(
        context,
        prerequisites,
        errors,
        warnings,
    )
    _collect_list_parity(context, prerequisites, errors, warnings)
    _collect_entrypoint_diagnostics(
        context,
        prerequisites,
        errors,
        warnings,
    )
    _print_result(errors, warnings)
    return 1 if errors or (args.strict_warnings and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
